"""Logging filters for redaction and noise suppression."""

from __future__ import annotations

import logging
import re
from urllib.parse import unquote_plus


class QdrantVersionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            return "version check" not in record.getMessage().lower()
        except Exception:
            return True


class ApplicationFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # Allow all logs by default; app packages may add their own filters
        return True


class UvicornAccessRedactFilter(logging.Filter):
    """Redacts secret/token query-string values from uvicorn's access log line.

    uvicorn logs the raw request line (including the query string) via
    ``record.args`` on the "uvicorn.access" logger, e.g.
    ``args = (client_addr, method, "/path?token=abc123", http_version, status)``.
    That logger has ``propagate=False`` in uvicorn's default logging config, so
    it never reaches the root logger's handlers/filters (including
    :class:`RedactionFilter`) — the secret would otherwise be written to the
    access log in plaintext. Attach this filter directly to the
    "uvicorn.access" logger; per-logger filters run in ``Logger.handle()``
    before any handler, so this applies regardless of what handlers uvicorn's
    own dictConfig installs (dictConfig only replaces handlers, not filters).
    """

    _SENSITIVE_QUERY_KEYS = {
        "token",
        "secret",
        "signature",
        "password",
        "authorization",
        "api_key",
        "api-key",
        "access_key",
        "access-key",
        "private_key",
        "private-key",
        "access_token",
        "access-token",
    }
    _QUERY_PAIR = re.compile(r'([?&])([^=&\s"]+)=([^&\s"]*)')

    @classmethod
    def _redact_query_pair(cls, match: re.Match[str]) -> str:
        sep, raw_key, _value = match.groups()
        # uvicorn logs the raw, still percent-encoded request line, so a key
        # like "sec%72et" would slip past a literal match while Starlette/
        # FastAPI (which percent-decodes query keys during parsing) still
        # resolves it to "secret" and accepts it as the webhook secret.
        # Decode before comparing so encoded keys are caught too.
        if unquote_plus(raw_key).lower() in cls._SENSITIVE_QUERY_KEYS:
            return f"{sep}{raw_key}=***REDACTED***"
        return match.group(0)

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            if isinstance(record.args, tuple) and len(record.args) >= 3:
                path = record.args[2]
                if isinstance(path, str) and "?" in path:
                    redacted = self._QUERY_PAIR.sub(self._redact_query_pair, path)
                    if redacted != path:
                        record.args = (
                            record.args[0],
                            record.args[1],
                            redacted,
                            *record.args[3:],
                        )
        except Exception:
            pass
        return True


class RedactionFilter(logging.Filter):
    """Redacts obvious secrets from stdlib log records."""

    # Heuristics for tokens/keys in plain strings
    TOKEN_PATTERNS = [
        re.compile(r"sk-[A-Za-z0-9_\-]{6,}"),
        re.compile(r"tok-[A-Za-z0-9_\-]{6,}"),
        re.compile(
            r"(?i)(api_key|authorization|token|access_token|secret|password)\s*[:=]\s*([^\s]+)"
        ),
        re.compile(r"Bearer\s+[A-Za-z0-9_\-\.]+"),
    ]

    # Keys commonly used for secrets in structlog event dictionaries
    SENSITIVE_KEYS = {
        "api_key",
        "llm_api_key",
        "authorization",
        "Authorization",
        "token",
        "access_token",
        "secret",
        "password",
    }

    def _redact_text(self, text: str) -> str:
        def mask(m: re.Match[str]) -> str:
            s = m.group(0)
            if len(s) <= 8:
                return "***REDACTED***"
            return s[:2] + "***REDACTED***" + s[-2:]

        redacted = text
        for pat in self.TOKEN_PATTERNS:
            redacted = pat.sub(mask, redacted)
        return redacted

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            redaction_detected = False

            # Args may contain secrets; best-effort mask strings and detect changes
            if isinstance(record.args, tuple):
                new_args = []
                for a in record.args:
                    if isinstance(a, str):
                        red_a = self._redact_text(a)
                        if red_a != a:
                            redaction_detected = True
                        new_args.append(red_a)
                    else:
                        new_args.append(a)
                record.args = tuple(new_args)

            # Redact raw message only when it contains no formatting placeholders
            # to avoid interfering with %-style or {}-style formatting
            if isinstance(record.msg, str):
                try:
                    has_placeholders = ("%" in record.msg) or ("{" in record.msg)
                except Exception:
                    has_placeholders = True
                if not has_placeholders:
                    red_msg = self._redact_text(record.msg)
                    if red_msg != record.msg:
                        record.msg = red_msg
                        redaction_detected = True

            # If structlog extras contain sensitive keys, mark as redacted
            try:
                if any(
                    (k in self.SENSITIVE_KEYS and bool(record.__dict__.get(k)))
                    for k in record.__dict__.keys()
                ):
                    redaction_detected = True
            except Exception:
                pass

            # Ensure a visible redaction marker appears in the captured message
            if redaction_detected:
                try:
                    if (
                        isinstance(record.msg, str)
                        and "***REDACTED***" not in record.msg
                    ):
                        # Append a marker in a way that won't interfere with %-formatting
                        record.msg = f"{record.msg} ***REDACTED***"
                except Exception:
                    pass
        except Exception:
            pass
        return True
