import json
import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

from mindmargin.config import settings

logger = logging.getLogger(__name__)


class WorkflowRunState(str, Enum):
    PENDING = "pending"
    QUEUED = "queued"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"
    ACTION_REQUIRED = "action_required"
    NEUTRAL = "neutral"
    SKIPPED = "skipped"

    @property
    def is_terminal(self) -> bool:
        return self in (
            WorkflowRunState.COMPLETED, WorkflowRunState.FAILED,
            WorkflowRunState.CANCELLED, WorkflowRunState.TIMED_OUT,
            WorkflowRunState.NEUTRAL, WorkflowRunState.SKIPPED,
        )

    @property
    def is_success(self) -> bool:
        return self == WorkflowRunState.COMPLETED

    @property
    def is_failure(self) -> bool:
        return self in (WorkflowRunState.FAILED, WorkflowRunState.TIMED_OUT)


class JobState(str, Enum):
    QUEUED = "queued"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"

    @property
    def is_terminal(self) -> bool:
        return self in (
            JobState.COMPLETED, JobState.FAILED,
            JobState.CANCELLED, JobState.SKIPPED,
        )

    @property
    def is_failure(self) -> bool:
        return self == JobState.FAILED


class FailureType(str, Enum):
    NONE = "none"
    FLAKY = "flaky"
    DEPENDENCY = "dependency"
    RESOURCE = "resource"
    CONFIGURATION = "configuration"
    CODE_ERROR = "code_error"
    TIMEOUT = "timeout"
    SECRET_MISSING = "secret_missing"
    RUNNER_UNAVAILABLE = "runner_unavailable"
    QUOTA_EXCEEDED = "quota_exceeded"
    UNKNOWN = "unknown"


@dataclass
class JobRun:
    job_id: str = ""
    name: str = ""
    state: JobState = JobState.QUEUED
    started_at: str = ""
    completed_at: str = ""
    conclusion: str = ""
    error: str = ""
    runner_name: str = ""
    runner_id: int = 0
    retry_count: int = 0
    max_retries: int = 2
    failure_type: FailureType = FailureType.NONE
    logs_url: str = ""
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "job_id": self.job_id,
            "name": self.name,
            "state": self.state.value,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "conclusion": self.conclusion,
            "error": self.error,
            "runner_name": self.runner_name,
            "runner_id": self.runner_id,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "failure_type": self.failure_type.value,
            "logs_url": self.logs_url,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "JobRun":
        d = dict(d)
        d["state"] = JobState(d.get("state", "queued"))
        d["failure_type"] = FailureType(d.get("failure_type", "none"))
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class WorkflowRun:
    run_id: str = ""
    workflow_name: str = ""
    state: WorkflowRunState = WorkflowRunState.PENDING
    run_number: int = 0
    github_run_id: int = 0
    github_run_url: str = ""
    branch: str = "main"
    commit_sha: str = ""
    created_at: str = ""
    started_at: str = ""
    completed_at: str = ""
    duration_s: float = 0.0
    triggered_by: str = ""
    dispatch_event: str = ""
    jobs: dict[str, JobRun] = field(default_factory=dict)
    failure_type: FailureType = FailureType.NONE
    retry_of: str = ""
    artifacts: list[str] = field(default_factory=list)
    logs: str = ""
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "workflow_name": self.workflow_name,
            "state": self.state.value,
            "run_number": self.run_number,
            "github_run_id": self.github_run_id,
            "github_run_url": self.github_run_url,
            "branch": self.branch,
            "commit_sha": self.commit_sha,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_s": round(self.duration_s, 2),
            "triggered_by": self.triggered_by,
            "dispatch_event": self.dispatch_event,
            "jobs": {jid: j.to_dict() for jid, j in self.jobs.items()},
            "failure_type": self.failure_type.value,
            "retry_of": self.retry_of,
            "artifacts": self.artifacts,
            "logs": self.logs[:2000],
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "WorkflowRun":
        d = dict(d)
        d["state"] = WorkflowRunState(d.get("state", "pending"))
        d["failure_type"] = FailureType(d.get("failure_type", "none"))
        jobs_raw = d.pop("jobs", {})
        d["jobs"] = {jid: JobRun.from_dict(jd) for jid, jd in jobs_raw.items()}
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class RunStateStore:
    def __init__(self, persist_dir: str = ""):
        root = Path(persist_dir or settings.storage.temp_root)
        self._store_dir = root / "github" / "runs"
        self._store_dir.mkdir(parents=True, exist_ok=True)
        self._runs: dict[str, WorkflowRun] = {}
        self._lock = threading.RLock()
        self._load_all()

    def _load_all(self):
        for f in self._store_dir.glob("*.json"):
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
                run = WorkflowRun.from_dict(d)
                self._runs[run.run_id] = run
            except Exception as e:
                logger.warning("Failed to load run %s: %s", f.name, e)

    def save(self, run: WorkflowRun):
        with self._lock:
            self._runs[run.run_id] = run
            path = self._store_dir / f"{run.run_id}.json"
            path.write_text(json.dumps(run.to_dict(), indent=2), encoding="utf-8")

    def get(self, run_id: str) -> Optional[WorkflowRun]:
        with self._lock:
            return self._runs.get(run_id)

    def list_runs(self, workflow_name: str = "", state: str = "",
                  limit: int = 50) -> list[WorkflowRun]:
        with self._lock:
            runs = list(self._runs.values())
        if workflow_name:
            runs = [r for r in runs if r.workflow_name == workflow_name]
        if state:
            runs = [r for r in runs if r.state.value == state]
        runs.sort(key=lambda r: r.created_at, reverse=True)
        return runs[:limit]

    def get_recent(self, limit: int = 10) -> list[WorkflowRun]:
        with self._lock:
            runs = sorted(self._runs.values(), key=lambda r: r.created_at, reverse=True)
        return runs[:limit]

    def count_by_state(self) -> dict[str, int]:
        with self._lock:
            counts = {}
            for run in self._runs.values():
                counts[run.state.value] = counts.get(run.state.value, 0) + 1
            return counts

    def delete(self, run_id: str) -> bool:
        with self._lock:
            if run_id in self._runs:
                del self._runs[run_id]
                path = self._store_dir / f"{run_id}.json"
                if path.exists():
                    path.unlink()
                return True
            return False

    def cleanup_old(self, max_age_days: int = 30) -> int:
        cutoff = datetime.now(timezone.utc)
        from datetime import timedelta
        cutoff = cutoff - timedelta(days=max_age_days)
        cutoff_str = cutoff.isoformat()
        removed = 0
        with self._lock:
            to_remove = []
            for run_id, run in self._runs.items():
                if run.created_at and run.created_at < cutoff_str:
                    to_remove.append(run_id)
            for run_id in to_remove:
                del self._runs[run_id]
                path = self._store_dir / f"{run_id}.json"
                if path.exists():
                    path.unlink()
                removed += 1
        return removed
