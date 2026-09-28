"""Structured logging: JSON formatter, request-ID injection and redaction of sensitive fields.

Log IDs, not content: never log emails, tokens, passwords, signatures or test names
(a diagnostic test name is health data).
"""

import json
import logging
from datetime import UTC, datetime

from apps.common.request_context import current_request_id

_STANDARD_ATTRS = set(vars(logging.LogRecord("", 0, "", 0, "", (), None))) | {
    "message",
    "asctime",
    "taskName",
}
# Extra attributes Django attaches that must never be serialised (they can embed query strings).
_DROPPED_ATTRS = {"request", "server_time"}
_SENSITIVE_MARKERS = (
    "password",
    "token",
    "authorization",
    "signature",
    "secret",
    "cookie",
    "email",
    "phone",
)
REDACTED = "[REDACTED]"


def _is_sensitive(key: str) -> bool:
    lowered = key.lower()
    return any(marker in lowered for marker in _SENSITIVE_MARKERS)


def _extra_fields(record: logging.LogRecord) -> dict[str, object]:
    return {
        key: value
        for key, value in record.__dict__.items()
        if key not in _STANDARD_ATTRS
        and key not in _DROPPED_ATTRS
        and key != "request_id"
        and not key.startswith("_")
    }


class RequestContextFilter(logging.Filter):
    """Attach the current request ID to every record."""

    def filter(self, record: logging.LogRecord) -> bool:
        if getattr(record, "request_id", None) is None:
            record.request_id = current_request_id()
        return True


class RedactionFilter(logging.Filter):
    """Replace values of sensitive-looking extra fields before any formatter sees them."""

    def filter(self, record: logging.LogRecord) -> bool:
        for key in _extra_fields(record):
            if _is_sensitive(key):
                setattr(record, key, REDACTED)
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", None),
        }
        payload.update(_extra_fields(record))
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


class ConsoleFormatter(logging.Formatter):
    """Human-friendly single-line format for local development (LOG_FORMAT=console)."""

    def format(self, record: logging.LogRecord) -> str:
        extras = " ".join(f"{key}={value}" for key, value in _extra_fields(record).items())
        line = (
            f"{self.formatTime(record)} {record.levelname:<7} {record.name} "
            f"[{getattr(record, 'request_id', None) or '-'}] {record.getMessage()}"
        )
        if extras:
            line = f"{line} {extras}"
        if record.exc_info:
            line = f"{line}\n{self.formatException(record.exc_info)}"
        return line
