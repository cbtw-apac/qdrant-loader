# Parser Configuration

A parser turns a file, such as a PDF, an Office document or an image, into text and
structure that HarborRAG can chunk and embed. Most formats use built-in parsers with
no configuration. [`config/ingestion/parsers.yaml`](../../../config/ingestion/parsers.yaml)
chooses the engines for PDFs and images; the shipped file uses LiteParse for both, with
optional OCR (optical character recognition, reading text from scanned pages and
pictures) through an external OCR server. Alternative profiles and engines stay in the
file as commented blocks.

The runtime reads the file from `HARBORRAG_PARSER_CONFIG_PATH`, and
`harborrag doctor` loads it in its `parsers catalog` check. The file's bytes are part
of every document's processing identity, so editing it reprocesses each connection's
documents on its next sync; see
[What reprocesses on the next sync](runtime-settings.md#what-reprocesses-on-the-next-sync).

## Formats HarborRAG reads

`HarborParser` routes each file by its suffix and media type. Its default stack
supports PPTX/PPTM, legacy PPT, DOCX, legacy DOC, ODT, Excel (including legacy XLS),
CSV/TSV, images, HTML/XHTML, EPUB, JSON/JSONL/NDJSON, Markdown/MDX, PDFs, and plain
text, source and config formats.

An enabled definition in `parsers.yaml` replaces only the engine for its own formats
in that default stack. For example, a `docx` definition replaces the DOCX engine, and
DOC, ODT and EPUB files keep their default engines. A `pdf` definition replaces the
whole PDF parser. Formats the file does not configure stay available.

### Legacy Microsoft Office binary formats

The `document`, `presentation` and `spreadsheet` families read the pre-2007 binary
(OLE compound file) formats without LibreOffice or any other external converter. The
`.doc` and `.ppt` engines need `olefile`, which the `parsers`, `document`,
`presentation` and `parsers-all` extras of `harborrag-adapters` install.

| Format | Suffixes / MIME type | Engine | What is extracted |
| --- | --- | --- | --- |
| Word 97-2003 | `.doc` / `application/msword` | `doc` (olefile) | Body paragraphs and tables, headers/footers, text boxes, footnotes, endnotes, comments; field codes are removed and only their displayed result is kept |
| PowerPoint 97-2003 | `.ppt`, `.pps` / `application/vnd.ms-powerpoint` | `ppt` (olefile) | One element per slide, plus speaker notes; master-slide placeholder prompts are skipped |
| Excel 97-2003 | `.xls` / `application/vnd.ms-excel` | `excel` (xlrd) | One table per sheet |

Limits:

- Only Word 97 and later binary files are read. Word 6.0/95 files are rejected as
  unsupported; re-save them as `.docx`.
- Text written with legacy 8-bit Vietnamese fonts (TCVN3/ABC, VNI) is stored as
  Latin-1 look-alike characters inside the file. It is extracted as stored and is not
  converted to Unicode Vietnamese.
- Password-protected or obfuscated files are rejected as password-protected.
- The file content decides the parser, not its name: a `.doc` or `.ppt` that is
  really a DOCX/PPTX package is handed to the DOCX/PPTX engine, and one that is really
  RTF, HTML or MHTML is rejected as unsupported.
- Table cells in `.doc` files are recovered from cell and row marks without reading
  table formatting, so tables with empty cells can shift a column.
- Word and PowerPoint templates (`.dot`, `.pot`) route here only by their media type:
  those suffixes are also Graphviz graphs and gettext templates, which keep reaching
  the plain-text parser.

## PDFs

### The active LiteParse parser

```yaml
version: 1

parsers:
  pdf-liteparse:
    parser: pdf
    enabled: true
    settings:
      min_content_chars: 20
      max_pages: 200
    engines:
      - backend: liteparse
        settings:
          output_format: markdown
          ocr_enabled: true
          ocr_language: en
          ocr_server_url: ${HARBORRAG_OCR_SERVER_URL:-}
          dpi: 150
          num_workers: 3
          strip_code_fences: true
```

The shipped definition sets a few more LiteParse options; the excerpt keeps the ones
this page explains. A one-item engine chain guarantees that PDFs go through LiteParse;
a built-in profile would create a fallback chain and could select another engine
first.

`max_pages` refuses a longer PDF before any engine reads it; the default is 200 and
`null` turns the check off. A PDF whose pages cannot be counted, such as an encrypted
one, goes to the engines, which report why it failed.

`strip_code_fences` removes Markdown code-fence delimiters from LiteParse's output.
Its layout pass fences any block it reads as preformatted, which on a form or a scanned
page is ordinary prose, sometimes tagged with a guessed language such as
```` ```python ````. Only the delimiter lines are dropped, so no extracted text is
lost; set it to `false` to keep LiteParse's fences.

### OCR server

`ocr_server_url` points at a self-hosted OCR service that LiteParse calls for scanned
pages instead of running OCR in-process. It comes from `HARBORRAG_OCR_SERVER_URL`, in
`env/.env.parser` in a repository checkout. The template leaves it empty; when it is
unset or empty, no OCR server is used and LiteParse OCRs locally with Tesseract. The
repository's Compose files do not start an OCR server.

<details markdown="1">
<summary>Ingestion worker in a container</summary>

Use a Docker DNS name rather than `localhost`, which would be the worker itself. With
the OCR server attached to the external `harborrag-data-network` under the alias
`ppocr-server`, set the container port, not the published host port:

```dotenv
HARBORRAG_OCR_SERVER_URL=http://ppocr-server:8888/ocr
```

</details>

<details markdown="1">
<summary>Parser running on the host</summary>

```dotenv
HARBORRAG_OCR_SERVER_URL=http://localhost:8888/ocr
```

</details>

### Other PDF engines

A PDF definition can instead name an explicit backend chain, tried in order:

```yaml
parsers:
  pdf-layout:
    parser: pdf
    enabled: true
    settings:
      min_content_chars: 20
    engines:
      - backend: pymupdf
      - backend: docling
        settings:
          do_ocr: true
          do_table_structure: true
```

Supported backend names are `pymupdf`, `docling`, `liteparse`, `mineru` and
`paddleocr`. An explicit `engines` chain cannot also set `profile`. Backend settings
are strict and checked against typed option dataclasses.

A definition can name a built-in `profile` instead: `liteparse` (the default when a
PDF definition names neither `engines` nor `profile`: LiteParse, then PyMuPDF),
`fast`, `balanced`, `ocr`, `ocr_first`, `quality` or `scientific`.

To switch PDFs to Docling per tenant, project or connection, see the
`parsing.pdf_parser` [runtime setting](runtime-settings.md#what-reprocesses-on-the-next-sync).

## Images

```yaml
parsers:
  image-liteparse:
    parser: image
    enabled: true
    settings:
      ocr_engine: liteparse
      ocr_server_url: ${HARBORRAG_OCR_SERVER_URL:-}
      lang: en
      max_pixels: 25000000
```

`ocr_engine` is `liteparse` (the default), `rapidocr` or `pytesseract`.

- `liteparse` sends raster images to the same OCR server as scanned PDF pages, or
  OCRs them locally with Tesseract when no server is set, so the worker needs no second
  local inference runtime.
- `rapidocr` runs a local ONNX model and needs the `image-rapidocr` extra. It is loaded
  lazily, and the configured parser reuses one engine instance.
- `pytesseract` calls an external Tesseract binary and needs the `image-tesseract`
  extra.

`lang` sets the OCR language for `liteparse` and `pytesseract`; `config` and `timeout`
apply to `pytesseract` only, and only `liteparse` uses `ocr_server_url`. Pillow
decodes every image first, so `max_pixels` and decompression-bomb limits apply before
anything is uploaded.

## Document limits

| Document | Limit | Setting |
| --- | --- | --- |
| PDF | 200 pages | `max_pages` on the `pdf` parser |
| Image | 25 megapixels | `max_pixels` on the `image` parser |
| Spreadsheet (`xlsx`, `xls`, `csv`) | 50,000 rows or 200,000 cells per file | Fixed |
| Office and EPUB archives | 256 MiB unzipped, 5,000 members, 100:1 per member | Fixed |

A document over a limit fails with a parser error and is not retried.

## Environment and secrets

Backend secrets use `<field>_env`:

```yaml
- backend: liteparse
  secrets:
    password_env: PDF_DOCUMENT_PASSWORD
```

MinerU subprocess environment forwarding maps a target variable to a source variable:

```yaml
- backend: mineru
  settings:
    backend: vlm-http-client
    server_url: http://127.0.0.1:30000
  environment:
    MINERU_VL_API_KEY: OPENAI_API_KEY
```

The referenced process variable must exist and be non-empty when the parser is built.
`env-example/.env.parser.example` lists the optional values. The parser loader does
not read `.env` files itself: in a checkout the CLI loads `env/.env.parser`, and
Compose passes it to the ingestion worker.

Any setting value may also reference the environment directly with `${VARIABLE}` or
`${VARIABLE:-default}`, which is how the OCR server URL above moves between a
containerized worker and a host run. A bare `${VARIABLE}` that is unset fails the
load; give it a default to make it optional. Credentials do not belong here: settings
named after a secret field are rejected whatever their value, so they keep using the
`secrets` block.

## Load the file from Python

```python
from harborrag_runtime.config import load_parser_catalog

catalog = load_parser_catalog("config/ingestion/parsers.yaml")
print(catalog.names(enabled_only=True))

pdf = catalog.build("pdf-liteparse")
image = catalog.build("image-liteparse")
parser_registry = catalog.build_harbor_parser()
```

Each parser family takes at most one enabled definition: `docx` and `epub` share the
document family, `csv` and `excel` the spreadsheet family, and `html` and `markdown`
the markup family. `build_harbor_parser()` rejects conflicting enabled definitions
instead of choosing silently.

Code overrides take precedence over YAML settings:

```python
pdf = catalog.build("pdf-liteparse", overrides={"min_content_chars": 100})
```

Building validates the configuration. A backend whose optional library, executable,
model, device or service is unavailable reports that failure when it parses.
