"""Validate declarative parser configuration and produce typed definitions."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from harborrag_runtime.config.errors import ParserConfigurationError
from harborrag_runtime.config.loading import (
    parse_environment_references,
    reject_unknown_keys,
    require_boolean,
    require_string_mapping,
)
from harborrag_runtime.config.parsers.providers import (
    PDF_BACKEND_PYTHON_ONLY_FIELDS,
    PDF_BACKEND_SECRET_FIELDS,
    PdfBackendSpec,
    check_parser_settings,
    parser_factory,
    parser_family,
    parser_setting_names,
    pdf_backend_spec,
    supported_parser_names,
    supported_pdf_backend_names,
)
from harborrag_runtime.config.parsers.schemas import (
    ParserDefinition,
    PdfBackendDefinition,
)

_PARSER_KEYS = frozenset({"enabled", "engines", "parser", "settings"})
_ENGINE_KEYS = frozenset({"backend", "environment", "secrets", "settings"})


def parse_parser_definitions(
    raw_parsers: Mapping[str, Any],
) -> dict[str, ParserDefinition]:
    """Parse all named parser definitions from the top-level mapping.

    Args:
        raw_parsers: The ``parsers`` mapping of a catalog file, by definition name.

    Returns:
        The definitions by name, in file order.

    Raises:
        ParserConfigurationError: A definition is invalid, or two enabled
            definitions configure the same parser family.
    """
    definitions = {
        _validate_name(name): _parse_definition(name, raw_definition)
        for name, raw_definition in raw_parsers.items()
    }
    _reject_family_conflicts(definitions)
    return definitions


def _reject_family_conflicts(definitions: Mapping[str, ParserDefinition]) -> None:
    """Reject two enabled definitions that configure the same parser family."""
    first_enabled: dict[str, str] = {}
    for name, definition in definitions.items():
        if not definition.enabled:
            continue
        family = parser_family(definition.parser)
        earlier = first_enabled.setdefault(family, name)
        if earlier != name:
            raise ParserConfigurationError(
                f"Enabled parser definitions {earlier!r} and {name!r} "
                f"both configure family {family!r}"
            )


def _validate_name(name: str) -> str:
    """Require a non-empty application-level parser name."""
    if not name.strip():
        raise ParserConfigurationError("Parser names must be non-empty strings")
    return name


def _parse_definition(name: str, raw: object) -> ParserDefinition:
    """Validate one YAML parser definition and create its immutable model."""
    definition = require_string_mapping(
        raw,
        label=f"parser {name!r}",
        error_type=ParserConfigurationError,
    )
    reject_unknown_keys(
        definition,
        _PARSER_KEYS,
        label=f"parser {name!r}",
        error_type=ParserConfigurationError,
    )

    parser = _parse_parser_name(name, definition.get("parser"))
    enabled = _parse_enabled(name, definition.get("enabled", True))
    settings = dict(
        require_string_mapping(
            definition.get("settings", {}),
            label=f"parser {name!r} settings",
            error_type=ParserConfigurationError,
        )
    )
    _validate_parser_settings(name, parser, settings)
    pdf_backends = _parse_pdf_backends(name, parser, definition)
    if pdf_backends and "profile" in settings:
        raise ParserConfigurationError(
            f"Parser {name!r} cannot combine an explicit engines chain with profile"
        )

    return ParserDefinition(
        name=name,
        parser=parser,
        enabled=enabled,
        settings=settings,
        pdf_backends=pdf_backends,
    )


def _parse_parser_name(name: str, raw_parser: object) -> str:
    """Require a stable, supported parser name."""
    if not isinstance(raw_parser, str) or not raw_parser.strip():
        raise ParserConfigurationError(f"Parser {name!r} must define a non-empty parser")
    parser = raw_parser.strip().lower()
    if parser_factory(parser) is None:
        supported = ", ".join(supported_parser_names())
        raise ParserConfigurationError(
            f"Parser {name!r} uses unsupported parser {raw_parser!r}; expected one of: {supported}"
        )
    return parser


def _parse_enabled(name: str, raw_enabled: object) -> bool:
    """Require the optional enabled switch to be a YAML boolean."""
    return require_boolean(
        raw_enabled,
        label=f"Parser {name!r} enabled",
        error_type=ParserConfigurationError,
    )


def _validate_parser_settings(
    name: str,
    parser: str,
    settings: dict[str, Any],
) -> None:
    """Reject settings the selected parser does not know or whose values it refuses."""
    unknown = sorted(set(settings) - parser_setting_names(parser))
    if unknown:
        raise ParserConfigurationError(
            f"Parser {name!r} has unknown {parser} setting(s): {', '.join(unknown)}"
        )
    try:
        check_parser_settings(parser, settings)
    except (TypeError, ValueError) as error:
        raise ParserConfigurationError(
            f"Parser {name!r} has an invalid {parser} setting: {error}"
        ) from error


def _parse_pdf_backends(
    name: str,
    parser: str,
    definition: Mapping[str, Any],
) -> tuple[PdfBackendDefinition, ...]:
    """Parse an optional ordered PDF backend chain."""
    if "engines" not in definition:
        return ()
    if parser != "pdf":
        raise ParserConfigurationError(
            f"Parser {name!r} can define engines only when parser is 'pdf'"
        )

    raw_engines = definition["engines"]
    if not isinstance(raw_engines, list) or not raw_engines:
        raise ParserConfigurationError(f"Parser {name!r} engines must be a non-empty list")

    backends = tuple(
        _parse_pdf_backend(name, index, raw_backend)
        for index, raw_backend in enumerate(raw_engines)
    )
    names = [backend.backend for backend in backends]
    if len(names) != len(set(names)):
        raise ParserConfigurationError(f"Parser {name!r} engines must not repeat a PDF backend")
    return backends


def _parse_pdf_backend(
    parser_name: str,
    index: int,
    raw: object,
) -> PdfBackendDefinition:
    """Validate one PDF backend entry and its backend-specific options."""
    label = f"parser {parser_name!r} engine {index}"
    engine = require_string_mapping(
        raw,
        label=label,
        error_type=ParserConfigurationError,
    )
    reject_unknown_keys(
        engine,
        _ENGINE_KEYS,
        label=label,
        error_type=ParserConfigurationError,
    )

    raw_backend = engine.get("backend")
    supported = ", ".join(supported_pdf_backend_names())
    if not isinstance(raw_backend, str) or not raw_backend.strip():
        raise ParserConfigurationError(
            f"{label} must define a non-empty backend; expected one of: {supported}"
        )
    backend = raw_backend.strip().lower()
    spec = pdf_backend_spec(backend)
    if spec is None:
        raise ParserConfigurationError(
            f"{label} uses unsupported PDF backend {raw_backend!r}; expected one of: {supported}"
        )

    settings = dict(
        require_string_mapping(
            engine.get("settings", {}),
            label=f"{label} settings",
            error_type=ParserConfigurationError,
        )
    )
    secret_environment = parse_environment_references(
        engine.get("secrets", {}),
        label=f"{label} secrets",
        key_suffix="_env",
        error_type=ParserConfigurationError,
    )
    process_environment = parse_environment_references(
        engine.get("environment", {}),
        label=f"{label} environment",
        error_type=ParserConfigurationError,
    )

    unknown = sorted((set(settings) | set(secret_environment)) - spec.setting_names())
    if unknown:
        raise ParserConfigurationError(
            f"{label} has unknown {backend} setting(s): {', '.join(unknown)}"
        )
    protected = sorted(set(settings) & PDF_BACKEND_SECRET_FIELDS)
    if protected:
        raise ParserConfigurationError(
            f"{label} cannot store secret setting(s) in YAML: {', '.join(protected)}"
        )
    overlap = sorted(set(settings) & set(secret_environment))
    if overlap:
        raise ParserConfigurationError(
            f"{label} defines setting(s) in both settings and secrets: {', '.join(overlap)}"
        )
    python_only = sorted(set(settings) & PDF_BACKEND_PYTHON_ONLY_FIELDS)
    if python_only:
        raise ParserConfigurationError(
            f"{label} setting(s) require Python objects and cannot be loaded from "
            f"YAML: {', '.join(python_only)}"
        )
    if process_environment and backend != "mineru":
        raise ParserConfigurationError(
            f"{label} environment is supported only for the MinerU subprocess backend"
        )
    _check_setting_values(label, backend, spec, settings)
    return PdfBackendDefinition(
        backend=backend,
        settings=settings,
        secret_environment=secret_environment,
        process_environment=process_environment,
    )


def _check_setting_values(
    label: str,
    backend: str,
    spec: PdfBackendSpec,
    settings: Mapping[str, Any],
) -> None:
    """Reject setting values the backend refuses, when the catalog loads."""
    try:
        spec.check_settings(settings)
    except (TypeError, ValueError) as error:
        raise ParserConfigurationError(
            f"{label} ({backend}) has an invalid setting: {error}"
        ) from error
