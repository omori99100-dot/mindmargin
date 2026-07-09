import atexit
import logging
import os
import signal
import sys
import threading
import time
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

_correlation_id: ContextVar[str] = ContextVar("correlation_id", default="")
_shutdown_hooks: list[Callable] = []
_shutdown_lock = threading.Lock()
_shutdown_in_progress = False


def generate_correlation_id() -> str:
    return uuid.uuid4().hex[:16]


def set_correlation_id(cid: Optional[str] = None) -> str:
    cid = cid or generate_correlation_id()
    _correlation_id.set(cid)
    return cid


def get_correlation_id() -> str:
    return _correlation_id.get()


class correlation_scope:
    def __init__(self, cid: Optional[str] = None):
        self._cid = cid or generate_correlation_id()
        self._token = None

    def __enter__(self):
        self._token = _correlation_id.set(self._cid)
        return self._cid

    def __exit__(self, *excinfo):
        if self._token is not None:
            _correlation_id.reset(self._token)


class StructuredLogger:
    def __init__(self, name: str):
        self._logger = logging.getLogger(name)

    def _log(self, level: int, msg: str, *args, **kwargs):
        extra = {"correlation_id": get_correlation_id()}
        self._logger.log(level, msg, *args, extra=extra, stacklevel=3)

    def info(self, msg: str, *args, **kwargs):
        self._log(logging.INFO, msg, *args, **kwargs)

    def warning(self, msg: str, *args, **kwargs):
        self._log(logging.WARNING, msg, *args, **kwargs)

    def error(self, msg: str, *args, **kwargs):
        self._log(logging.ERROR, msg, *args, **kwargs)

    def debug(self, msg: str, *args, **kwargs):
        self._log(logging.DEBUG, msg, *args, **kwargs)


def validate_config(config: dict, schema: dict) -> list[str]:
    errors = []
    for key, expected_type in schema.items():
        if key not in config:
            errors.append(f"Missing required config key: {key}")
        elif not isinstance(config[key], expected_type):
            errors.append(
                f"Config key '{key}' expected {expected_type.__name__}, "
                f"got {type(config[key]).__name__}"
            )
    return errors


def register_shutdown_hook(fn: Callable, priority: int = 100):
    with _shutdown_lock:
        _shutdown_hooks.append((priority, fn))
        _shutdown_hooks.sort(key=lambda x: x[0], reverse=True)


def _reset_shutdown_hooks():
    with _shutdown_lock:
        _shutdown_hooks.clear()
        global _shutdown_in_progress
        _shutdown_in_progress = False


def run_shutdown_hooks():
    global _shutdown_in_progress
    with _shutdown_lock:
        if _shutdown_in_progress:
            return
        _shutdown_in_progress = True
        hooks = list(_shutdown_hooks)
    logger.info("Running %d shutdown hooks ...", len(hooks))
    for priority, fn in hooks:
        try:
            fn()
        except Exception as e:
            logger.error("Shutdown hook failed: %s", e)


def install_signal_handlers():
    def _handler(signum, frame):
        logger.info("Received signal %d, initiating graceful shutdown ...", signum)
        run_shutdown_hooks()
        sys.exit(0)

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, _handler)
        except (ValueError, OSError):
            pass
    atexit.register(run_shutdown_hooks)


class TimeoutGuard:
    def __init__(self, timeout_s: float, label: str = "operation"):
        self.timeout_s = timeout_s
        self.label = label
        self._timer: Optional[threading.Timer] = None
        self._timed_out = False

    def __enter__(self):
        if self.timeout_s > 0:

            def _timeout():
                self._timed_out = True
                logger.warning("TimeoutGuard: %s exceeded %.1fs", self.label, self.timeout_s)

            self._timer = threading.Timer(self.timeout_s, _timeout)
            self._timer.daemon = True
            self._timer.start()
        return self

    def __exit__(self, *excinfo):
        if self._timer is not None:
            self._timer.cancel()

    @property
    def timed_out(self) -> bool:
        return self._timed_out


class ExecutionGuard:
    def __init__(self):
        self._lock = threading.Lock()
        self._running = False

    def acquire(self) -> bool:
        with self._lock:
            if self._running:
                return False
            self._running = True
            return True

    def release(self):
        with self._lock:
            self._running = False

    def __enter__(self):
        if not self.acquire():
            raise RuntimeError("Already running")
        return self

    def __exit__(self, *excinfo):
        self.release()


def safe_path(base: Path, user_path: str) -> Path:
    resolved = (base / user_path).resolve()
    if not str(resolved).startswith(str(base.resolve())):
        raise ValueError(f"Path traversal detected: {user_path}")
    return resolved


def safe_filename(name: str) -> str:
    return "".join(c if c.isalnum() or c in "._- " else "_" for c in name).strip()


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def utcnow_ts() -> float:
    return time.time()
