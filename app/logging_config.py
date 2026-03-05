import json
import logging
import sys
from contextvars import ContextVar
from datetime import datetime, timezone

trace_id_var: ContextVar[str | None] = ContextVar("trace_id_var", default=None)


_STANDARD_ATTRS = frozenset({
    "name", "msg", "args", "created", "filename", "funcName",
    "levelname", "levelno", "lineno", "module", "msecs", "message",
    "pathname", "process", "processName", "relativeCreated", "stack_info",
    "taskName", "thread", "threadName", "exc_info", "exc_text", "asctime",
})


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "trace_id": trace_id_var.get(None),
        }
        # Include any extra fields passed via the `extra` parameter
        for key, value in record.__dict__.items():
            if key not in _STANDARD_ATTRS and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def configure_logging() -> None:
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for handler in root.handlers[:]:
        root.removeHandler(handler)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())
    root.addHandler(handler)

    for noisy in ("uvicorn.access", "httpx", "chromadb"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
