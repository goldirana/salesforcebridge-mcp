from __future__ import annotations

import logging
import json
import sys
import time
from datetime import datetime, timezone
from typing import Any


class JSONFormatter(logging.Formatter):
    """Formats log records as single-line JSON for production ingestion."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Attach any extra fields passed via logger.info("msg", extra={...})
        for key in ("user_id", "tenant_id", "tool_name", "duration_ms",
                     "sf_api_calls", "result_count", "error_code", "request_id"):
            value = getattr(record, key, None)
            if value is not None:
                log_entry[key] = value

        if record.exc_info and record.exc_info[1]:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry, default=str)


def setup_logging(level: str = "INFO", json_output: bool = True) -> None:
    """
    Configure root logger.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR).
        json_output: If True, use JSON formatter. If False, use human-readable format (dev).
    """
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Remove existing handlers to avoid duplicates on re-init
    root.handlers.clear()

    handler = logging.StreamHandler(sys.stderr)

    if json_output:
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-8s %(name)s — %(message)s")
        )

    root.addHandler(handler)

    # Quiet down noisy libraries
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


class ToolTimer:
    """Context manager to time tool execution and log the result."""

    def __init__(self, tool_name: str, user_id: str = "", request_id: str = "") -> None:
        self.tool_name = tool_name
        self.user_id = user_id
        self.request_id = request_id
        self._start: float = 0
        self.duration_ms: float = 0

    def __enter__(self) -> "ToolTimer":
        self._start = time.perf_counter()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.duration_ms = round((time.perf_counter() - self._start) * 1000, 2)
        logger = logging.getLogger("tools")

        extra = {
            "tool_name": self.tool_name,
            "user_id": self.user_id,
            "request_id": self.request_id,
            "duration_ms": self.duration_ms,
        }

        if exc_type:
            extra["error_code"] = exc_type.__name__
            logger.error("Tool %s failed (%.1fms)", self.tool_name, self.duration_ms, extra=extra)
        else:
            logger.info("Tool %s completed (%.1fms)", self.tool_name, self.duration_ms, extra=extra)
