import json
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from mindmargin.config import settings
from mindmargin.github.state import (
    FailureType, JobRun, JobState, WorkflowRun, WorkflowRunState,
)

logger = logging.getLogger(__name__)

MAX_AUTO_RETRIES = 3
RETRY_DELAY_BASE_S = 30


@dataclass
class RecoveryAction:
    action_id: str = ""
    run_id: str = ""
    job_id: str = ""
    action_type: str = ""
    description: str = ""
    status: str = "pending"
    created_at: str = ""
    completed_at: str = ""
    result: dict = field(default_factory=dict)
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "action_id": self.action_id,
            "run_id": self.run_id,
            "job_id": self.job_id,
            "action_type": self.action_type,
            "description": self.description,
            "status": self.status,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "result": self.result,
            "error": self.error,
        }


class FailureClassifier:
    @staticmethod
    def classify(run: WorkflowRun, job: JobRun = None) -> FailureType:
        error = (job.error if job else run.metadata.get("error", "")).lower()
        if not error:
            return FailureType.UNKNOWN

        if any(kw in error for kw in ["timeout", "timed out", "deadline exceeded"]):
            return FailureType.TIMEOUT
        if any(kw in error for kw in ["rate limit", "quota", "429", "503"]):
            return FailureType.QUOTA_EXCEEDED
        if any(kw in error for kw in ["secret", "token", "credential", "unauthorized", "401", "403"]):
            return FailureType.SECRET_MISSING
        if any(kw in error for kw in ["no runner", "runner", "self-hosted", "offline"]):
            return FailureType.RUNNER_UNAVAILABLE
        if any(kw in error for kw in ["oom", "memory", "disk space", "no space"]):
            return FailureType.RESOURCE
        if any(kw in error for kw in ["dependency", "module", "import", "npm", "pip"]):
            return FailureType.DEPENDENCY
        if any(kw in error for kw in ["syntax", "type error", "name error", "reference error"]):
            return FailureType.CODE_ERROR
        if any(kw in error for kw in ["flaky", "intermittent", "retry", "transient"]):
            return FailureType.FLAKY
        if any(kw in error for kw in ["config", "yaml", "invalid input", "bad request"]):
            return FailureType.CONFIGURATION
        return FailureType.UNKNOWN

    @staticmethod
    def should_retry(failure_type: FailureType, retry_count: int) -> bool:
        if retry_count >= MAX_AUTO_RETRIES:
            return False
        retryable = {
            FailureType.FLAKY, FailureType.TIMEOUT, FailureType.RESOURCE,
            FailureType.QUOTA_EXCEEDED, FailureType.RUNNER_UNAVAILABLE,
        }
        return failure_type in retryable


class RecoveryEngine:
    def __init__(self, persist_dir: str = ""):
        root = Path(persist_dir or settings.storage.temp_root)
        self._rec_dir = root / "github" / "recovery"
        self._rec_dir.mkdir(parents=True, exist_ok=True)
        self._actions: list[RecoveryAction] = []
        self._lock = threading.RLock()
        self._classifier = FailureClassifier()
        self._load()

    def _load(self):
        actions_path = self._rec_dir / "actions.json"
        if actions_path.exists():
            try:
                data = json.loads(actions_path.read_text(encoding="utf-8"))
                self._actions = [RecoveryAction(**a) for a in data]
            except Exception:
                pass

    def _save(self):
        actions_path = self._rec_dir / "actions.json"
        actions_path.write_text(
            json.dumps([a.to_dict() for a in self._actions[-500:]], indent=2),
            encoding="utf-8",
        )

    def _add_action(self, action_type: str, run_id: str, job_id: str,
                    description: str) -> RecoveryAction:
        import uuid
        action = RecoveryAction(
            action_id=f"rec_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}",
            run_id=run_id,
            job_id=job_id,
            action_type=action_type,
            description=description,
            status="pending",
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        with self._lock:
            self._actions.append(action)
            self._save()
        return action

    def diagnose(self, run: WorkflowRun) -> dict:
        failure_type = self._classifier.classify(run)
        run.failure_type = failure_type

        failed_jobs = {jid: j for jid, j in run.jobs.items() if j.state.is_failure}
        diagnoses = []

        for jid, job in failed_jobs.items():
            job.failure_type = self._classifier.classify(run, job)
            diagnoses.append({
                "job_id": jid,
                "job_name": job.name,
                "failure_type": job.failure_type.value,
                "error": job.error[:500],
                "should_retry": FailureClassifier.should_retry(job.failure_type, job.retry_count),
                "retry_count": job.retry_count,
                "max_retries": job.max_retries,
            })

        return {
            "run_id": run.run_id,
            "workflow_name": run.workflow_name,
            "overall_failure_type": failure_type.value,
            "failed_jobs": diagnoses,
            "recommendation": self._get_recommendation(failure_type, diagnoses),
        }

    def _get_recommendation(self, failure_type: FailureType, diagnoses: list) -> str:
        if failure_type == FailureType.SECRET_MISSING:
            return "Configure missing secrets before retrying"
        if failure_type == FailureType.CODE_ERROR:
            return "Fix code errors before retrying"
        if failure_type == FailureType.CONFIGURATION:
            return "Fix workflow configuration before retrying"
        retryable = any(d["should_retry"] for d in diagnoses)
        if retryable:
            return "Automatic retry recommended"
        return "Manual intervention required"

    def should_auto_retry(self, run: WorkflowRun) -> bool:
        if run.retry_of:
            return False
        failed_jobs = [j for j in run.jobs.values() if j.state.is_failure]
        if not failed_jobs:
            return False
        for job in failed_jobs:
            if not FailureClassifier.should_retry(job.failure_type, job.retry_count):
                return False
        return True

    def create_retry_run(self, original_run: WorkflowRun) -> dict:
        action = self._add_action(
            "retry",
            original_run.run_id,
            "",
            f"Retry workflow {original_run.workflow_name} (run {original_run.run_id})",
        )

        action.status = "completed"
        action.completed_at = datetime.now(timezone.utc).isoformat()
        action.result = {
            "original_run_id": original_run.run_id,
            "workflow_name": original_run.workflow_name,
            "trigger": "auto_retry",
        }

        with self._lock:
            self._save()

        return action.to_dict()

    def create_rerun_failed_jobs(self, run: WorkflowRun) -> dict:
        failed_job_ids = [jid for jid, j in run.jobs.items() if j.state.is_failure]
        action = self._add_action(
            "rerun_failed_jobs",
            run.run_id,
            ",".join(failed_job_ids),
            f"Rerun {len(failed_job_ids)} failed jobs in {run.workflow_name}",
        )

        action.status = "completed"
        action.completed_at = datetime.now(timezone.utc).isoformat()
        action.result = {
            "rerun_job_ids": failed_job_ids,
            "workflow_name": run.workflow_name,
        }

        with self._lock:
            self._save()

        return action.to_dict()

    def create_rollback(self, run: WorkflowRun, target_run_id: str = "") -> dict:
        action = self._add_action(
            "rollback",
            run.run_id,
            "",
            f"Rollback {run.workflow_name} to previous state",
        )

        action.status = "completed"
        action.completed_at = datetime.now(timezone.utc).isoformat()
        action.result = {
            "original_run_id": run.run_id,
            "target_run_id": target_run_id,
        }

        with self._lock:
            self._save()

        return action.to_dict()

    def get_actions(self, run_id: str = "", action_type: str = "",
                    limit: int = 50) -> list[dict]:
        with self._lock:
            actions = self._actions
        if run_id:
            actions = [a for a in actions if a.run_id == run_id]
        if action_type:
            actions = [a for a in actions if a.action_type == action_type]
        return [a.to_dict() for a in actions[-limit:]]

    def get_stats(self) -> dict:
        with self._lock:
            actions = self._actions
        by_type = {}
        for a in actions:
            by_type[a.action_type] = by_type.get(a.action_type, 0) + 1
        return {
            "total_actions": len(actions),
            "by_type": by_type,
            "pending": sum(1 for a in actions if a.status == "pending"),
            "completed": sum(1 for a in actions if a.status == "completed"),
            "failed": sum(1 for a in actions if a.status == "failed"),
        }
