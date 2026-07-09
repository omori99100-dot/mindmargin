"""Lightweight file-based background job system.

Each job is a JSON file in ``jobs/`` under the output root.
Jobs can be started, queried, paused, resumed, cancelled, and retried.
"""

import json
import logging
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from mindmargin.core.storage import _safe_base

logger = logging.getLogger(__name__)

# ── Job states ──

PENDING = "PENDING"
RUNNING = "RUNNING"
PAUSED = "PAUSED"
COMPLETED = "COMPLETED"
FAILED = "FAILED"
CANCELLED = "CANCELLED"
RETRYING = "RETRYING"

_TERMINAL_JOB_STATES = {COMPLETED, FAILED, CANCELLED}


def _job_dir() -> Path:
    d = _safe_base() / "jobs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _next_job_id() -> str:
    now = datetime.utcnow()
    seq = int(time.time() * 1000) % 100000
    return f"job_{now.strftime('%Y%m%d_%H%M%S')}_{seq:05d}"


class Job:
    """Represents a single background job."""

    def __init__(self, job_id: str, job_type: str, params: Optional[dict] = None):
        self.job_id = job_id
        self.job_type = job_type
        self.params = params or {}
        self._path = _job_dir() / f"{job_id}.json"
        self._data = self._load()
        if not self._data:
            self._data = {
                "job_id": job_id,
                "job_type": job_type,
                "params": params or {},
                "state": PENDING,
                "created_at": datetime.utcnow().isoformat(),
                "started_at": "",
                "updated_at": datetime.utcnow().isoformat(),
                "completed_at": "",
                "result": {},
                "error": "",
                "retry_count": 0,
                "max_retries": params.get("max_retries", 3) if params else 3,
            }
            self._save()

    # ── Properties ──

    @property
    def state(self) -> str:
        return self._data.get("state", PENDING)

    @property
    def is_terminal(self) -> bool:
        return self.state in _TERMINAL_JOB_STATES

    @property
    def is_running(self) -> bool:
        return self.state == RUNNING

    @property
    def is_paused(self) -> bool:
        return self.state == PAUSED

    @property
    def can_transition(self) -> bool:
        return not self.is_terminal and self.state != CANCELLED

    # ── Mutations ──

    def start(self):
        if self.state != PENDING:
            raise JobError(f"Cannot start job {self.job_id}: state={self.state}")
        self._data["state"] = RUNNING
        self._data["started_at"] = datetime.utcnow().isoformat()
        self._data["updated_at"] = datetime.utcnow().isoformat()
        self._save()

    def complete(self, result: Optional[dict] = None):
        self._data["state"] = COMPLETED
        self._data["completed_at"] = datetime.utcnow().isoformat()
        if result:
            self._data["result"] = result
        self._save()

    def fail(self, error: str):
        self._data["state"] = FAILED
        self._data["error"] = error
        self._data["completed_at"] = datetime.utcnow().isoformat()
        self._save()

    def pause(self):
        if self.state != RUNNING:
            raise JobError(f"Cannot pause job {self.job_id}: state={self.state}")
        self._data["state"] = PAUSED
        self._data["updated_at"] = datetime.utcnow().isoformat()
        self._save()

    def resume(self):
        if self.state != PAUSED:
            raise JobError(f"Cannot resume job {self.job_id}: state={self.state}")
        self._data["state"] = RUNNING
        self._data["updated_at"] = datetime.utcnow().isoformat()
        self._save()

    def cancel(self):
        if self.is_terminal:
            raise JobError(f"Cannot cancel job {self.job_id}: already {self.state}")
        self._data["state"] = CANCELLED
        self._data["updated_at"] = datetime.utcnow().isoformat()
        self._save()

    def retry(self):
        if self.state != FAILED:
            raise JobError(f"Cannot retry job {self.job_id}: state={self.state}")
        self._data["state"] = RETRYING
        self._data["retry_count"] = self._data.get("retry_count", 0) + 1
        self._data["updated_at"] = datetime.utcnow().isoformat()
        self._save()

    def update_meta(self, key: str, value: object):
        self._data.setdefault("metadata", {})[key] = value
        self._data["updated_at"] = datetime.utcnow().isoformat()
        self._save()

    # ── Query ──

    def to_dict(self) -> dict:
        return dict(self._data)

    @classmethod
    def load(cls, job_id: str) -> Optional["Job"]:
        path = _job_dir() / f"{job_id}.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            j = cls.__new__(cls)
            j.job_id = data["job_id"]
            j.job_type = data["job_type"]
            j.params = data.get("params", {})
            j._path = path
            j._data = data
            return j
        except (json.JSONDecodeError, KeyError, Exception):
            return None

    @classmethod
    def list_jobs(cls, limit: int = 50) -> list[dict]:
        """Return recent jobs as dicts, newest first."""
        paths = sorted(_job_dir().glob("*.json"), reverse=True)[:limit]
        results = []
        for p in paths:
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                results.append(data)
            except (json.JSONDecodeError, Exception):
                pass
        return results

    @classmethod
    def count_by_state(cls) -> dict[str, int]:
        counts: dict[str, int] = {}
        for p in _job_dir().glob("*.json"):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                s = data.get("state", "UNKNOWN")
                counts[s] = counts.get(s, 0) + 1
            except (json.JSONDecodeError, Exception):
                pass
        return counts

    # ── Internals ──

    def _load(self) -> dict:
        if self._path.exists():
            try:
                return json.loads(self._path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, Exception):
                pass
        return {}

    def _save(self):
        self._path.write_text(
            json.dumps(self._data, indent=2, default=str), encoding="utf-8")


class JobError(Exception):
    pass


# ── Worker ──

class JobWorker:
    """Runs a job function in a daemon thread with state tracking."""

    def __init__(self, job: Job, fn: Callable[[Job], dict], poll_interval: float = 1.0):
        self.job = job
        self.fn = fn
        self.poll_interval = poll_interval
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def start(self):
        if self._thread and self._thread.is_alive():
            raise JobError(f"Worker already running for {self.job.job_id}")
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()

    def _run(self):
        try:
            self.job.start()
            result = self.fn(self.job)
            if not self._stop_event.is_set():
                self.job.complete(result)
        except JobError:
            pass
        except Exception as e:
            if not self._stop_event.is_set():
                if self.job._data.get("retry_count", 0) < self.job._data.get("max_retries", 3):
                    self.job.retry()
                    logger.info(f"Job {self.job.job_id} queued for retry ({self.job._data['retry_count']})")
                else:
                    self.job.fail(str(e))


# ── Convenience: create + start in one call ──

def run_job(job_type: str, fn: Callable[[Job], dict],
            params: Optional[dict] = None) -> Job:
    """Create a job, start it in a background thread, return immediately."""
    job_id = _next_job_id()
    job = Job(job_id, job_type, params)
    worker = JobWorker(job, fn)
    worker.start()
    logger.info(f"Job {job_id} ({job_type}) started in background")
    return job
