import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from mindmargin.config import settings
from mindmargin.core.hardening import utcnow

logger = logging.getLogger(__name__)


@dataclass
class RecoveryReport:
    recovered_queues: int = 0
    recovered_schedules: int = 0
    recovered_workflows: int = 0
    dlq_items_restored: int = 0
    errors: list[str] = field(default_factory=list)
    timestamp: str = ""

    def to_dict(self) -> dict:
        return {
            "recovered_queues": self.recovered_queues,
            "recovered_schedules": self.recovered_schedules,
            "recovered_workflows": self.recovered_workflows,
            "dlq_items_restored": self.dlq_items_restored,
            "errors": self.errors,
            "timestamp": self.timestamp,
        }


class RecoveryManager:
    def __init__(self, persist_dir: str = ""):
        root = Path(persist_dir or settings.storage.temp_root)
        self._persist_dir = root / "recovery"
        self._persist_dir.mkdir(parents=True, exist_ok=True)
        self._queue_impl = None
        self._scheduler_impl = None
        self._workflow_impl = None

    def bind_queue(self, queue_instance):
        self._queue_impl = queue_instance

    def bind_scheduler(self, scheduler_instance):
        self._scheduler_impl = scheduler_instance

    def bind_workflow(self, workflow_instance):
        self._workflow_impl = workflow_instance

    def recover_all(self) -> RecoveryReport:
        report = RecoveryReport(timestamp=utcnow())
        try:
            if self._queue_impl:
                q_count = self._queue_impl.recover()
                report.recovered_queues = q_count
                logger.info("Recovered %d queue items", q_count)
        except Exception as e:
            report.errors.append(f"Queue recovery failed: {e}")
            logger.error("Queue recovery failed: %s", e)

        try:
            if self._scheduler_impl:
                s_count = self._scheduler_impl.recover()
                report.recovered_schedules = s_count
                logger.info("Recovered %d schedules", s_count)
        except Exception as e:
            report.errors.append(f"Scheduler recovery failed: {e}")
            logger.error("Scheduler recovery failed: %s", e)

        try:
            if self._workflow_impl:
                w_count = self._workflow_impl.recover()
                report.recovered_workflows = w_count
                logger.info("Recovered %d workflows", w_count)
        except Exception as e:
            report.errors.append(f"Workflow recovery failed: {e}")
            logger.error("Workflow recovery failed: %s", e)

        self._save_report(report)
        return report

    def recover_queue(self) -> int:
        if not self._queue_impl:
            return 0
        try:
            return self._queue_impl.recover()
        except Exception as e:
            logger.error("Queue recovery failed: %s", e)
            return 0

    def recover_scheduler(self) -> int:
        if not self._scheduler_impl:
            return 0
        try:
            return self._scheduler_impl.recover()
        except Exception as e:
            logger.error("Scheduler recovery failed: %s", e)
            return 0

    def recover_workflows(self) -> int:
        if not self._workflow_impl:
            return 0
        try:
            return self._workflow_impl.recover()
        except Exception as e:
            logger.error("Workflow recovery failed: %s", e)
            return 0

    def last_report(self) -> Optional[RecoveryReport]:
        reports = sorted(self._persist_dir.glob("recovery_*.json"))
        if not reports:
            return None
        try:
            d = json.loads(reports[-1].read_text(encoding="utf-8"))
            return RecoveryReport(**d)
        except Exception:
            return None

    def list_reports(self) -> list[RecoveryReport]:
        reports = []
        for f in sorted(self._persist_dir.glob("recovery_*.json")):
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
                reports.append(RecoveryReport(**d))
            except Exception:
                continue
        return reports

    def simulate_crash_and_recover(self) -> RecoveryReport:
        return self.recover_all()

    def _save_report(self, report: RecoveryReport):
        path = self._persist_dir / f"recovery_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')}_{uuid.uuid4().hex[:8]}.json"
        path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
