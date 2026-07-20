import logging
from importlib import import_module


def test_redaction_filter_masks_and_marks(caplog):
    caplog.set_level(logging.INFO)

    logging_mod = import_module("qdrant_loader_core.logging")
    RedactionFilter = logging_mod.RedactionFilter

    # Keep root handlers to restore after test to avoid side-effects
    root = logging.getLogger()
    prev_handlers = list(root.handlers)

    # Create a custom handler that captures messages after redaction
    captured_messages = []

    class TestHandler(logging.Handler):
        def emit(self, record):
            # Format the record to get the final message
            msg = self.format(record)
            captured_messages.append(msg)

    try:
        # Clear existing handlers and add our test handler with redaction filter
        for h in list(root.handlers):
            root.removeHandler(h)

        test_handler = TestHandler()
        test_handler.setLevel(logging.INFO)
        test_handler.addFilter(RedactionFilter())
        root.addHandler(test_handler)
        root.setLevel(logging.INFO)

        logger = logging.getLogger("redaction-test")

        # Message with obvious token in the raw string (no placeholders)
        logger.info("api_key=sk-ABCDEFGHIJKLMN")
        # Message with placeholder + token in args (ensures args are redacted safely)
        logger.info("arg test %s", "sk-ABCDEFGH")

        # Redaction marker should appear at least once
        assert any(
            "***REDACTED***" in m for m in captured_messages
        ), f"Messages: {captured_messages}"
        # Original secrets should not appear
        assert all(
            "sk-ABCDEFGHIJKLMN" not in m for m in captured_messages
        ), f"Messages: {captured_messages}"
        # Mask should keep first/last 2 chars for long secrets.
        # Depending on exact pattern matched, the visible context may be key or value.
        assert any(
            ("sk***REDACTED***MN" in m) or ("ap***REDACTED***MN" in m)
            for m in captured_messages
        ), f"Messages: {captured_messages}"
    finally:
        # Restore handlers
        for h in list(root.handlers):
            root.removeHandler(h)
        for h in prev_handlers:
            root.addHandler(h)


def test_uvicorn_access_redact_filter_masks_query_secret():
    """uvicorn.access logs the raw request line (with query string) via args.

    Regression test for a webhook secret/token passed as a query param (the
    "simple" auth scheme) being written verbatim into uvicorn's access log,
    e.g.: '%s - "%s %s HTTP/%s" %d' % (client_addr, method, path, version, status)
    """
    logging_mod = import_module("qdrant_loader_core.logging")
    UvicornAccessRedactFilter = logging_mod.UvicornAccessRedactFilter

    captured_messages = []

    class TestHandler(logging.Handler):
        def emit(self, record):
            captured_messages.append(self.format(record))

    access_logger = logging.getLogger("uvicorn.access")
    prev_handlers = list(access_logger.handlers)
    prev_filters = list(access_logger.filters)
    prev_propagate = access_logger.propagate

    try:
        for h in list(access_logger.handlers):
            access_logger.removeHandler(h)
        for f in list(access_logger.filters):
            access_logger.removeFilter(f)

        test_handler = TestHandler()
        access_logger.addHandler(test_handler)
        access_logger.addFilter(UvicornAccessRedactFilter())
        access_logger.setLevel(logging.INFO)
        access_logger.propagate = False

        access_logger.info(
            '%s - "%s %s HTTP/%s" %d',
            "127.0.0.1:0",
            "POST",
            "/webhooks/projects/my-project/jira/source?token=NJF36cwbnGwQNp1QSbAo",
            "1.1",
            401,
        )

        assert len(captured_messages) == 1
        message = captured_messages[0]
        assert "NJF36cwbnGwQNp1QSbAo" not in message
        assert "token=***REDACTED***" in message
    finally:
        for f in list(access_logger.filters):
            access_logger.removeFilter(f)
        for h in list(access_logger.handlers):
            access_logger.removeHandler(h)
        for f in prev_filters:
            access_logger.addFilter(f)
        for h in prev_handlers:
            access_logger.addHandler(h)
        access_logger.propagate = prev_propagate


def test_uvicorn_access_redact_filter_masks_additional_credential_params():
    """access_key, private_key and authorization query params must also be masked."""
    logging_mod = import_module("qdrant_loader_core.logging")
    UvicornAccessRedactFilter = logging_mod.UvicornAccessRedactFilter

    captured_messages = []

    class TestHandler(logging.Handler):
        def emit(self, record):
            captured_messages.append(self.format(record))

    access_logger = logging.getLogger("uvicorn.access")
    prev_handlers = list(access_logger.handlers)
    prev_filters = list(access_logger.filters)
    prev_propagate = access_logger.propagate

    try:
        for h in list(access_logger.handlers):
            access_logger.removeHandler(h)
        for f in list(access_logger.filters):
            access_logger.removeFilter(f)

        test_handler = TestHandler()
        access_logger.addHandler(test_handler)
        access_logger.addFilter(UvicornAccessRedactFilter())
        access_logger.setLevel(logging.INFO)
        access_logger.propagate = False

        access_logger.info(
            '%s - "%s %s HTTP/%s" %d',
            "127.0.0.1:0",
            "GET",
            "/path?access_key=AKIAABCDEF&private_key=PRIVATEKEY123&authorization=Bearer123",
            "1.1",
            200,
        )

        assert len(captured_messages) == 1
        message = captured_messages[0]
        assert "AKIAABCDEF" not in message
        assert "PRIVATEKEY123" not in message
        assert "Bearer123" not in message
        assert "access_key=***REDACTED***" in message
        assert "private_key=***REDACTED***" in message
        assert "authorization=***REDACTED***" in message
    finally:
        for f in list(access_logger.filters):
            access_logger.removeFilter(f)
        for h in list(access_logger.handlers):
            access_logger.removeHandler(h)
        for f in prev_filters:
            access_logger.addFilter(f)
        for h in prev_handlers:
            access_logger.addHandler(h)
        access_logger.propagate = prev_propagate


def test_setup_attaches_uvicorn_access_redact_filter_once():
    logging_mod = import_module("qdrant_loader_core.logging")
    LoggingConfig = logging_mod.LoggingConfig
    UvicornAccessRedactFilter = logging_mod.UvicornAccessRedactFilter

    access_logger = logging.getLogger("uvicorn.access")
    prev_filters = list(access_logger.filters)

    try:
        LoggingConfig.setup(level="DEBUG", disable_console=True)
        LoggingConfig.setup(level="INFO", disable_console=True)

        redact_filters = [
            f for f in access_logger.filters if isinstance(f, UvicornAccessRedactFilter)
        ]
        assert len(redact_filters) == 1
    finally:
        for f in list(access_logger.filters):
            access_logger.removeFilter(f)
        for f in prev_filters:
            access_logger.addFilter(f)


def test_clean_formatter_strips_ansi(tmp_path):
    logging_mod = import_module("qdrant_loader_core.logging")
    CleanFormatter = logging_mod.CleanFormatter

    path = tmp_path / "ansi.log"

    handler = logging.FileHandler(path)
    handler.setFormatter(CleanFormatter("%(message)s"))

    logger = logging.getLogger("ansi-test")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    logger.addHandler(handler)

    try:
        logger.info("\x1b[31mred text\x1b[0m")
        handler.flush()
    finally:
        logger.removeHandler(handler)
        handler.close()

    content = path.read_text()
    assert "\x1b[" not in content
    assert "red text" in content


def test_redact_processor_masks_nested_fields():
    logging_mod = import_module("qdrant_loader_core.logging")
    redact = logging_mod.redact_processor

    event = {
        "api_key": "sk-ABCDEFGHIJKLMNOP",
        "nested": {
            "token": "abcd1234",  # short token -> fully redacted
            "list": [{"password": "supersecret"}, {"ok": "fine"}],
        },
        "note": "keep",
    }

    out = redact(None, "info", event)

    # Top-level sensitive key masked with visible marker in the value
    assert isinstance(out["api_key"], str) and "***REDACTED***" in out["api_key"]
    # Nested sensitive keys redacted/masked
    assert out["nested"]["token"] == "***REDACTED***"
    assert "***REDACTED***" in out["nested"]["list"][0]["password"]
    # Non-sensitive content preserved
    assert out["note"] == "keep"


def test_redact_processor_masks_pattern_sensitive_keys():
    logging_mod = import_module("qdrant_loader_core.logging")
    redact = logging_mod.redact_processor

    event = {
        "jira_token": "ATATT-super-secret",
        "nested": {"client_secret": "very-secret"},
        "ok": "safe",
    }

    out = redact(None, "info", event)

    assert "***REDACTED***" in out["jira_token"]
    assert "***REDACTED***" in out["nested"]["client_secret"]
    assert out["ok"] == "safe"


def test_redact_processor_camelcase_false_positives_not_redacted():
    """Keys that contain a sensitive keyword as a substring but not at a word
    boundary should NOT be redacted (camelCase boundary guards must be
    case-sensitive)."""
    logging_mod = import_module("qdrant_loader_core.logging")
    redact = logging_mod.redact_processor

    event = {
        # "secret" is a prefix of "secretion" — no uppercase follows, so no match
        "secretionRate": "safe-value",
        # "apiKey" is a substring of "notapiKeyish" — no uppercase follows "ish"
        "notapiKeyish": "safe-value",
        # Sanity-check: genuine sensitive camelCase keys must still be redacted
        "apiKey": "sk-ABCDEFGHIJKLMNOP",
        "jiraApiKey": "ATATT-super-secret",
    }

    out = redact(None, "info", event)

    # False-positives must pass through untouched
    assert out["secretionRate"] == "safe-value", "secretionRate should not be redacted"
    assert out["notapiKeyish"] == "safe-value", "notapiKeyish should not be redacted"
    # True sensitive keys must still be masked
    assert "***REDACTED***" in out["apiKey"], "apiKey should be redacted"
    assert "***REDACTED***" in out["jiraApiKey"], "jiraApiKey should be redacted"
