import json
import logging

import pytest

from app.logging_config import JsonFormatter


def _make_record(
    *, level: int = logging.INFO, msg: str = "hello", extra: dict | None = None, exc_info=None
) -> logging.LogRecord:
    record = logging.LogRecord(
        name="app.test",
        level=level,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=(),
        exc_info=exc_info,
    )
    for key, value in (extra or {}).items():
        setattr(record, key, value)
    return record


class TestJsonFormatter:
    def test_produces_single_line_valid_json(self):
        record = _make_record(msg="something happened")
        formatted = JsonFormatter().format(record)

        assert "\n" not in formatted
        payload = json.loads(formatted)
        assert payload["message"] == "something happened"

    @pytest.mark.parametrize(
        "level,expected_severity",
        [
            (logging.DEBUG, "DEBUG"),
            (logging.INFO, "INFO"),
            (logging.WARNING, "WARNING"),
            (logging.ERROR, "ERROR"),
            (logging.CRITICAL, "CRITICAL"),
        ],
    )
    def test_severity_matches_cloud_logging_values(self, level, expected_severity):
        payload = json.loads(JsonFormatter().format(_make_record(level=level)))
        assert payload["severity"] == expected_severity

    def test_includes_logger_name_and_time(self):
        payload = json.loads(JsonFormatter().format(_make_record()))
        assert payload["logger"] == "app.test"
        assert "time" in payload

    def test_extra_fields_pass_through(self):
        payload = json.loads(
            JsonFormatter().format(_make_record(extra={"case_id": "abc-123", "elapsed_ms": 42.0}))
        )
        assert payload["case_id"] == "abc-123"
        assert payload["elapsed_ms"] == 42.0

    def test_exception_info_is_included(self):
        try:
            raise ValueError("boom")
        except ValueError:
            import sys

            record = _make_record(msg="failed", exc_info=sys.exc_info())

        payload = json.loads(JsonFormatter().format(record))
        assert "ValueError: boom" in payload["exception"]
