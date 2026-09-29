"""Structured (JSON) logging to stdout. Deliberately stdlib `logging`, not a
third-party structured-logging library: Python's own level names (INFO/
WARNING/ERROR/CRITICAL) already match Cloud Logging's expected `severity`
values verbatim, so a plain Formatter needs no renaming step, and Cloud Run
picks up anything written to stdout/stderr with no agent or client library
required -- if a line is valid JSON, Cloud Logging parses it as structured
and pulls `severity`/`message` out of the payload into the log entry itself.

Every log line is a single-line JSON object -- required, not stylistic:
Cloud Run's log shipper (like every container log shipper) reads stdout
line by line, so a pretty-printed multi-line object would be split into
several unparseable fragments.
"""

import json
import logging
from datetime import UTC, datetime
from logging.config import dictConfig
from typing import Any

# The set of attributes every LogRecord carries regardless of what the call
# site passed -- computed from a throwaway record rather than hardcoded, so
# it can't quietly drift out of sync with whatever Python version this runs
# under (a new stdlib release adding an attribute here would otherwise leak
# into every log line's output as a bogus "extra" field).
_STANDARD_RECORD_ATTRS = frozenset(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {"message"}


class JsonFormatter(logging.Formatter):
    """Emits one single-line JSON object per record: `severity` (Cloud
    Logging's expected field, taken straight from levelname -- no mapping
    needed), `message`, `time`, `logger`, a traceback under `exception` when
    present, and anything the call site passed via `extra=`."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "severity": record.levelname,
            "message": record.getMessage(),
            "time": datetime.fromtimestamp(record.created, tz=UTC).isoformat(timespec="milliseconds"),
            "logger": record.name,
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD_RECORD_ATTRS:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    """Call once, before constructing the FastAPI app. Attaches a single
    stdout/JSON handler to the root logger and routes uvicorn's own loggers
    (uvicorn, uvicorn.access, uvicorn.error) through it too -- left alone,
    uvicorn keeps its own colorized plain-text handlers, and Cloud Logging
    would end up with two inconsistent formats side by side instead of one."""
    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {"json": {"()": JsonFormatter}},
            "handlers": {
                "stdout": {
                    "class": "logging.StreamHandler",
                    "formatter": "json",
                    "stream": "ext://sys.stdout",
                }
            },
            "root": {"handlers": ["stdout"], "level": level},
            "loggers": {
                # propagate=True (the default) sends these through root's
                # handler instead of uvicorn's own; handlers=[] ensures they
                # don't ALSO keep printing via uvicorn's default ones.
                "uvicorn": {"handlers": [], "level": level},
                "uvicorn.access": {"handlers": [], "level": level},
                "uvicorn.error": {"handlers": [], "level": level},
            },
        }
    )
