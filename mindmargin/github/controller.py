import json
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from mindmargin.config import settings
from mindmargin.github.artifacts import ArtifactStore, ArtifactType
from mindmargin.github.monitor import GitHubMonitor
from mindmargin.github.recovery import FailureClassifier, RecoveryEngine
from mindmargin.github.reports import ReportGenerator
from mindmargin.github.runner import RunnerManager
from mindmargin.github.secrets import SecretsValidator
from mindmargin.github.state import (
    FailureType, JobRun, JobState, RunStateStore, WorkflowRun, WorkflowRunState,
)
from mindmargin.github.workflows import WorkflowRegistry

logger = logging.getLogger(__name__)

DEFAULT_MAX_CONCURRENT = 3
DEFAULT_DAILY_LIMIT = 50


@dataclass
class ExecutionPolicy:
    max_concurrent_workflows: int = DEFAULT_MAX_CONCURRENT
    daily_execution_limit: int = DEFAULT_DAILY_LIMIT
    cost_limit_usd: float = 100.0
    quota_limit: int = 10000
    maintenance_mode: bool = False
    emergency_stop: bool = False
    time_window_start: str = ""
    time_window_end: str = ""
    enabled: bool = True

    def to_dict(self) -> dict:
        return {
            "max_concurrent_workflows": self.max_concurrent_workflows,
            "daily_execution_limit": self.daily_execution_limit,
            "cost_limit_usd": self.cost_limit_usd,
            "quota_limit": self.quota_limit,
            "maintenance_mode": self.maintenance_mode,
            "emergency_stop": self.emergency_stop,
            "time_window_start": self.time_window_start,
            "time_window_end": self.time_window_end,
            "enabled": self.enabled,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ExecutionPolicy":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class GitHubStatus:
    total_runs: int = 0
    active_runs: int = 0
    completed_today: int = 0
    failed_today: int = 0
    success_rate: float = 100.0
    avg_duration_s: float = 0.0
    registry_workflows: int = 0
    artifacts_count: int = 0
    runners_available: int = 0
    health_score: float = 100.0
    policy: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "total_runs": self.total_runs,
            "active_runs": self.active_runs,
            "completed_today": self.completed_today,
            "failed_today": self.failed_today,
            "success_rate": round(self.success_rate, 1),
            "avg_duration_s": round(self.avg_duration_s, 1),
            "registry_workflows": self.registry_workflows,
            "artifacts_count": self.artifacts_count,
            "runners_available": self.runners_available,
            "health_score": round(self.health_score, 1),
            "policy": self.policy,
        }


class GitHubController:
    def __init__(self, persist_dir: str = ""):
        root = Path(persist_dir or settings.storage.temp_root)
        self._gh_dir = root / "github"
        self._gh_dir.mkdir(parents=True, exist_ok=True)
        self._policy_path = self._gh_dir / "policy.json"

        self._state_store = RunStateStore(persist_dir)
        self._registry = WorkflowRegistry()
        self._recovery = RecoveryEngine(persist_dir)
        self._artifacts = ArtifactStore(persist_dir)
        self._monitor = GitHubMonitor(persist_dir)
        self._reports = ReportGenerator(persist_dir)
        self._secrets = SecretsValidator(persist_dir)
        self._runner_mgr = RunnerManager(persist_dir)

        self._policy = self._load_policy()
        self._active_runs: dict[str, WorkflowRun] = {}
        self._lock = threading.RLock()

    def _load_policy(self) -> ExecutionPolicy:
        if self._policy_path.exists():
            try:
                data = json.loads(self._policy_path.read_text(encoding="utf-8"))
                return ExecutionPolicy.from_dict(data)
            except Exception:
                pass
        return ExecutionPolicy()

    def _save_policy(self):
        self._policy_path.write_text(
            json.dumps(self._policy.to_dict(), indent=2), encoding="utf-8"
        )

    def start_workflow(self, workflow_id: str, trigger: str = "manual",
                       params: dict = None) -> dict:
        if self._policy.emergency_stop:
            return {"status": "blocked", "error": "Emergency stop is active"}
        if self._policy.maintenance_mode:
            return {"status": "blocked", "error": "Maintenance mode is active"}

        definition = self._registry.get(workflow_id)
        if not definition:
            return {"status": "failed", "error": f"Workflow '{workflow_id}' not found"}
        if not definition.enabled:
            return {"status": "blocked", "error": f"Workflow '{workflow_id}' is disabled"}

        with self._lock:
            if len(self._active_runs) >= self._policy.max_concurrent_workflows:
                return {"status": "blocked", "error": "Max concurrent workflows reached"}

        now = datetime.now(timezone.utc).isoformat()
        run = WorkflowRun(
            run_id=f"run_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{workflow_id}",
            workflow_name=definition.name,
            state=WorkflowRunState.QUEUED,
            created_at=now,
            triggered_by=trigger,
            dispatch_event=json.dumps(params or {}),
            metadata=params or {},
        )

        for step_def in definition.steps:
            job = JobRun(
                job_id=step_def.step_id,
                name=step_def.name,
                state=JobState.QUEUED,
                max_retries=step_def.max_retries,
            )
            run.jobs[step_def.step_id] = job

        self._state_store.save(run)

        with self._lock:
            self._active_runs[run.run_id] = run

        self._monitor.record_workflow_started(definition.name)
        self._monitor.record_dispatch(definition.name, trigger)

        logger.info("Workflow started: %s (run: %s)", definition.name, run.run_id)

        return {
            "status": "started",
            "run_id": run.run_id,
            "workflow_name": definition.name,
            "created_at": now,
        }

    def cancel_workflow(self, run_id: str) -> dict:
        run = self._state_store.get(run_id)
        if not run:
            return {"status": "failed", "error": f"Run '{run_id}' not found"}
        if run.state.is_terminal:
            return {"status": "failed", "error": f"Run already in terminal state: {run.state.value}"}

        run.state = WorkflowRunState.CANCELLED
        run.completed_at = datetime.now(timezone.utc).isoformat()
        for job in run.jobs.values():
            if not job.state.is_terminal:
                job.state = JobState.CANCELLED

        self._state_store.save(run)
        with self._lock:
            self._active_runs.pop(run_id, None)

        logger.info("Workflow cancelled: %s", run_id)
        return {"status": "cancelled", "run_id": run_id}

    def restart_workflow(self, run_id: str) -> dict:
        run = self._state_store.get(run_id)
        if not run:
            return {"status": "failed", "error": f"Run '{run_id}' not found"}

        definition = self._registry.get(run.workflow_name)
        if not definition:
            definition = self._registry.select_workflow({"tag": run.workflow_name})

        if not definition:
            return {"status": "failed", "error": "Cannot find workflow definition for restart"}

        return self.start_workflow(definition.workflow_id, trigger="restart",
                                   params={"restarted_from": run_id})

    def retry_workflow(self, run_id: str) -> dict:
        run = self._state_store.get(run_id)
        if not run:
            return {"status": "failed", "error": f"Run '{run_id}' not found"}

        diagnosis = self._recovery.diagnose(run)
        if self._recovery.should_auto_retry(run):
            result = self._recovery.create_retry_run(run)
            return {
                "status": "retry_scheduled",
                "run_id": run_id,
                "diagnosis": diagnosis,
                "recovery_action": result,
            }

        return {
            "status": "manual_intervention_needed",
            "run_id": run_id,
            "diagnosis": diagnosis,
        }

    def pause_workflow(self, run_id: str) -> dict:
        run = self._state_store.get(run_id)
        if not run:
            return {"status": "failed", "error": f"Run '{run_id}' not found"}
        if run.state != WorkflowRunState.IN_PROGRESS:
            return {"status": "failed", "error": "Can only pause in-progress workflows"}

        run.metadata["paused_at"] = datetime.now(timezone.utc).isoformat()
        self._state_store.save(run)
        return {"status": "paused", "run_id": run_id}

    def resume_workflow(self, run_id: str) -> dict:
        run = self._state_store.get(run_id)
        if not run:
            return {"status": "failed", "error": f"Run '{run_id}' not found"}

        if run.state == WorkflowRunState.IN_PROGRESS:
            run.metadata.pop("paused_at", None)
            self._state_store.save(run)
            return {"status": "resumed", "run_id": run_id}

        return {"status": "failed", "error": "Cannot resume from current state"}

    def get_workflow_status(self, run_id: str) -> dict:
        run = self._state_store.get(run_id)
        if not run:
            return {"error": f"Run '{run_id}' not found"}
        return run.to_dict()

    def get_job_status(self, run_id: str, job_id: str) -> dict:
        run = self._state_store.get(run_id)
        if not run:
            return {"error": f"Run '{run_id}' not found"}
        job = run.jobs.get(job_id)
        if not job:
            return {"error": f"Job '{job_id}' not found"}
        return job.to_dict()

    def get_workflow_logs(self, run_id: str) -> dict:
        run = self._state_store.get(run_id)
        if not run:
            return {"error": f"Run '{run_id}' not found"}
        return {
            "run_id": run_id,
            "logs": run.logs,
            "job_logs": {jid: j.metadata.get("logs", "") for jid, j in run.jobs.items()},
        }

    def get_artifacts(self, run_id: str = "", artifact_type: str = "") -> list[dict]:
        arts = self._artifacts.list_artifacts(
            workflow_run_id=run_id, artifact_type=artifact_type,
        )
        return [a.to_dict() for a in arts]

    def get_status(self) -> GitHubStatus:
        runs = self._state_store.list_runs(limit=1000)
        counts = self._state_store.count_by_state()

        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        today_runs = [r for r in runs if r.created_at and r.created_at.startswith(today)]

        completed = counts.get("completed", 0)
        failed = counts.get("failed", 0)
        total_terminal = completed + failed
        success_rate = (completed / max(total_terminal, 1)) * 100

        durations = [r.duration_s for r in runs if r.duration_s > 0]
        avg_duration = sum(durations) / max(len(durations), 1)

        health = self._monitor.get_health_report()
        pool = self._runner_mgr.get_pool_status()
        art_stats = self._artifacts.get_stats()

        return GitHubStatus(
            total_runs=len(runs),
            active_runs=counts.get("in_progress", 0) + counts.get("queued", 0),
            completed_today=sum(1 for r in today_runs if r.state.is_success),
            failed_today=sum(1 for r in today_runs if r.state.is_failure),
            success_rate=success_rate,
            avg_duration_s=avg_duration,
            registry_workflows=len(self._registry.list_all()),
            artifacts_count=art_stats["total_artifacts"],
            runners_available=pool.available_runners,
            health_score=health["health_score"],
            policy=self._policy.to_dict(),
        )

    def update_policy(self, **kwargs) -> dict:
        for key, value in kwargs.items():
            if hasattr(self._policy, key):
                setattr(self._policy, key, value)
        self._save_policy()
        return self._policy.to_dict()

    def get_policy(self) -> dict:
        return self._policy.to_dict()

    @property
    def state_store(self) -> RunStateStore:
        return self._state_store

    @property
    def registry(self) -> WorkflowRegistry:
        return self._registry

    @property
    def recovery(self) -> RecoveryEngine:
        return self._recovery

    @property
    def artifacts(self) -> ArtifactStore:
        return self._artifacts

    @property
    def monitor(self) -> GitHubMonitor:
        return self._monitor

    @property
    def reports(self) -> ReportGenerator:
        return self._reports

    @property
    def secrets(self) -> SecretsValidator:
        return self._secrets

    @property
    def runner_mgr(self) -> RunnerManager:
        return self._runner_mgr
