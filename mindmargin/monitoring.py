import json
import logging
import sys
import time
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from mindmargin.config import settings

request_id: ContextVar[Optional[str]] = ContextVar("request_id", default=None)


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        rid = request_id.get()
        if rid:
            log_entry["request_id"] = rid

        if record.exc_info and record.exc_info[0]:
            log_entry["exception"] = self.formatException(record.exc_info)

        if hasattr(record, "extra_data"):
            log_entry["extra"] = record.extra_data

        return json.dumps(log_entry, ensure_ascii=False)


class HumanFormatter(logging.Formatter):
    def __init__(self):
        super().__init__(
            "%(asctime)s | %(levelname)-7s | %(name)s:%(lineno)d | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )


def setup_structured_logging(
    name: str = "mindmargin",
    log_level: Optional[str] = None,
    json_output: Optional[bool] = None,
) -> logging.Logger:
    logger = logging.getLogger(name)
    level = log_level or settings.log_level.upper()
    logger.setLevel(getattr(logging, level, logging.INFO))

    for handler in logger.handlers[:]:
        logger.removeHandler(handler)

    use_json = json_output if json_output is not None else settings.production.enable_structured_logs

    if use_json:
        formatter = JSONFormatter()
    else:
        formatter = HumanFormatter()

    stdout = logging.StreamHandler(sys.stdout)
    stdout.setFormatter(formatter)
    logger.addHandler(stdout)

    log_dir = Path(settings.storage.output_root)
    log_dir.mkdir(parents=True, exist_ok=True)

    fh = logging.handlers.RotatingFileHandler(
        str(log_dir / "pipeline.log"),
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    fh.setFormatter(JSONFormatter())
    logger.addHandler(fh)

    if use_json:
        err_handler = logging.handlers.RotatingFileHandler(
            str(log_dir / "errors.log"),
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        err_handler.setLevel(logging.ERROR)
        err_handler.setFormatter(JSONFormatter())
        logger.addHandler(err_handler)

    return logger


import logging.handlers


class Timer:
    def __init__(self, name: str, logger: Optional[logging.Logger] = None):
        self.name = name
        self.logger = logger or logging.getLogger("mindmargin.timing")
        self.start_time = 0.0
        self.duration = 0.0

    def __enter__(self):
        self.start_time = time.perf_counter()
        return self

    def __exit__(self, *args):
        self.duration = (time.perf_counter() - self.start_time) * 1000
        self.logger.info(
            f"{self.name} completed in {self.duration:.1f}ms",
            extra={"extra_data": {"timer": self.name, "duration_ms": round(self.duration, 1)}},
        )


def log_operation(operation: str, logger: Optional[logging.Logger] = None, **extra):
    lg = logger or logging.getLogger("mindmargin.operations")
    lg.info(
        f"Operation: {operation}",
        extra={"extra_data": {"operation": operation, **extra}},
    )


def log_metric(name: str, value: float, logger: Optional[logging.Logger] = None, **labels):
    lg = logger or logging.getLogger("mindmargin.metrics")
    lg.info(
        f"Metric: {name}={value}",
        extra={"extra_data": {"metric_name": name, "metric_value": value, "labels": labels}},
    )
