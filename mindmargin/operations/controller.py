import json
import logging
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from mindmargin.config import settings
from mindmargin.core.events import publish
from mindmargin.core.hardening import utcnow
from mindmargin.core.scheduler import Scheduler
from mindmargin.core.workflows import WorkflowEngine
from mindmargin.operations.models import (
    OPERATION_CRON_DEFAULTS,
    OPERATION_TIMEOUT_DEFAULTS,
    OperationRecord,
    OperationReport,
    OperationStatus,
    OperationType,
)
from mindmargin.operations.orchestrator import OperationsOrchestrator

logger = logging.getLogger(__name__)

_OPERATION_HANDLERS: dict[OperationType, Callable] = {}


def _ensure_handler_registry(orchestrator: OperationsOrchestrator):
    if _OPERATION_HANDLERS:
        return
    wf_ids = orchestrator.workflow_ids

    def _op_handler(op_type: OperationType, wid: str) -> Callable:
        def _handler() -> dict:
            engine_wf = orchestrator._engine
            success = engine_wf.start(wid)
            if not success:
                engine_wf.resume(wid)
            wf = engine_wf.get(wid)
            if wf:
                return {
                    "status": wf.state.value,
                    "workflow_id": wid,
                    "steps": {sid: {"state": s.state.value, "error": s.error} for sid, s in wf.steps.items()},
                }
            return {"status": "failed", "error": "workflow_not_found"}
        return _handler

    key_map = {
        "analytics": OperationType.DAILY_ANALYTICS,
        "intelligence": OperationType.DAILY_INTELLIGENCE,
        "executor": OperationType.DECISION_EXECUTOR,
        "feedback": OperationType.FEEDBACK_CYCLE,
        "experiments": OperationType.EXPERIMENT_CYCLE,
        "knowledge_graph": OperationType.KNOWLEDGE_GRAPH,
        "forecast": OperationType.FORECAST,
        "weekly_plan": OperationType.WEEKLY_PLAN,
        "selection": OperationType.SELECTION_PRESSURE,
        "ab_rotation": OperationType.AB_ROTATION,
        "distribution": OperationType.DISTRIBUTION,
    }
    for key, op_type in key_map.items():
        wid = wf_ids.get(key)
        if wid:
            _OPERATION_HANDLERS[op_type] = _op_handler(op_type, wid)
        else:
            logger.warning("No workflow registered for %s", key)


class OperationsController:
    def __init__(self, engine: WorkflowEngine, scheduler: Optional[Scheduler] = None,
                 orchestrator: Optional[OperationsOrchestrator] = None):
        self._engine = engine
        self._scheduler = scheduler
        self._orchestrator = orchestrator or OperationsOrchestrator(engine)
        self._records_dir: Path = (Path(settings.storage.temp_root) / "operations")
        self._records_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._schedules: dict[str, str] = {}

    def schedule_all(self, cron_overrides: Optional[dict[str, str]] = None) -> dict[str, str]:
        if not self._scheduler:
            logger.warning("No scheduler available, cannot schedule operations")
            return {}

        _ensure_handler_registry(self._orchestrator)

        overrides = cron_overrides or {}
        scheduled = {}

        for op_type in OperationType:
            handler = _OPERATION_HANDLERS.get(op_type)
            if not handler:
                logger.debug("No handler for %s, skipping schedule", op_type.value)
                continue
            cron = overrides.get(op_type.value, OPERATION_CRON_DEFAULTS.get(op_type, ""))
            timeout = OPERATION_TIMEOUT_DEFAULTS.get(op_type, 300)
            if not cron:
                logger.debug("No cron expression for %s, skipping", op_type.value)
                continue
            try:
                sid = self._scheduler.register(
                    name=op_type.value,
                    handler=handler,
                    cron=cron,
                    timeout_s=timeout,
                )
                scheduled[op_type.value] = sid
                logger.info("Scheduled %s with cron '%s' (sid=%s)", op_type.value, cron, sid)
            except Exception as e:
                logger.error("Failed to schedule %s: %s", op_type.value, e)

        self._schedules = scheduled
        return scheduled

    def _get_default_orchestrator(self) -> OperationsOrchestrator:
        if not self._orchestrator:
            self._orchestrator = OperationsOrchestrator(self._engine)
            self._orchestrator.register_all()
        return self._orchestrator

    def run_operation(self, op_type: OperationType, metadata: Optional[dict] = None) -> dict:
        orch = self._get_default_orchestrator()

        handler_map = {
            OperationType.DAILY_ANALYTICS: orch.build_analytics_workflow,
            OperationType.DAILY_INTELLIGENCE: orch.build_intelligence_workflow,
            OperationType.DECISION_EXECUTOR: orch.build_executor_workflow,
            OperationType.FEEDBACK_CYCLE: orch.build_feedback_workflow,
            OperationType.EXPERIMENT_CYCLE: orch.build_experiment_workflow,
            OperationType.KNOWLEDGE_GRAPH: orch.build_knowledge_graph_workflow,
            OperationType.FORECAST: orch.build_forecast_workflow,
            OperationType.WEEKLY_PLAN: orch.build_weekly_plan_workflow,
            OperationType.SELECTION_PRESSURE: orch.build_selection_workflow,
            OperationType.AB_ROTATION: orch.build_ab_rotation_workflow,
            OperationType.DISTRIBUTION: orch.build_distribution_workflow,
        }

        builder = handler_map.get(op_type)
        if not builder:
            return {"status": "failed", "error": f"Unknown operation type: {op_type}"}

        try:
            wid = builder()
            record_id = f"op_{op_type.value}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')}"
            self._save_record(OperationRecord(
                operation_id=record_id,
                operation_type=op_type,
                status=OperationStatus.RUNNING,
                started_at=utcnow(),
                workflow_id=wid,
                metadata=metadata or {},
            ))

            self._engine.start(wid)
            import time
            wf = self._engine.get(wid)
            deadline = time.time() + OPERATION_TIMEOUT_DEFAULTS.get(op_type, 300)
            while wf and not wf.is_terminal and time.time() < deadline:
                time.sleep(0.5)
                wf = self._engine.get(wid)

            if wf:
                status = OperationStatus.COMPLETED if wf.state.value == "completed" else OperationStatus.FAILED
                step_errors = [s.error for s in wf.steps.values() if s.error]
                self._save_record(OperationRecord(
                    operation_id=record_id,
                    operation_type=op_type,
                    status=status,
                    started_at=wf.started_at,
                    completed_at=wf.completed_at or utcnow(),
                    workflow_id=wid,
                    result={sid: {"state": s.state.value} for sid, s in wf.steps.items()},
                    error=step_errors[0] if step_errors else "",
                    metadata=metadata or {},
                ))
                return {
                    "status": status.value,
                    "operation_id": record_id,
                    "workflow_id": wid,
                    "workflow_state": wf.state.value,
                    "error": step_errors[0] if step_errors else "",
                }

            return {"status": "failed", "error": "workflow_not_found"}
        except Exception as e:
            logger.error("Operation %s failed: %s", op_type.value, e)
            return {"status": "failed", "error": str(e)}

    def get_status(self) -> OperationReport:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        all_records = self._list_records()
        today_records = [r for r in all_records if r.started_at.startswith(today)]
        completed_today = sum(1 for r in today_records if r.status == OperationStatus.COMPLETED)
        failed_today = sum(1 for r in today_records if r.status == OperationStatus.FAILED)

        active = 0
        non_terminal = [r for r in all_records if r.status in (OperationStatus.PENDING, OperationStatus.RUNNING)]
        for r in non_terminal:
            if r.workflow_id:
                wf = self._engine.get(r.workflow_id)
                if wf and not wf.is_terminal:
                    active += 1

        scheduled_count = len(self._schedules) if self._scheduler else 0

        if failed_today > 3:
            overall = "degraded"
        elif failed_today > 0 and completed_today == 0:
            overall = "degraded"
        else:
            overall = "operational"

        return OperationReport(
            status=overall,
            active_operations=active,
            completed_today=completed_today,
            failed_today=failed_today,
            scheduled=scheduled_count,
            records=list(reversed(all_records))[:20],
        )

    def get_history(self, limit: int = 50) -> list[OperationRecord]:
        return list(reversed(self._list_records()))[:limit]

    def recover_failed(self) -> int:
        recovered = 0
        for record in self._list_records():
            if record.status == OperationStatus.FAILED and record.workflow_id:
                wf = self._engine.get(record.workflow_id)
                if wf and not wf.is_terminal:
                    self._engine.resume(record.workflow_id)
                    record.status = OperationStatus.PENDING
                    self._save_record(record)
                    recovered += 1
                elif wf and wf.is_terminal and wf.state.value == "failed":
                    self._engine.resume(record.workflow_id)
                    record.status = OperationStatus.PENDING
                    self._save_record(record)
                    recovered += 1
        return recovered

    def start_scheduler(self):
        if self._scheduler:
            self._scheduler.start()

    def stop_scheduler(self, timeout_s: float = 5.0):
        if self._scheduler:
            self._scheduler.stop(timeout_s=timeout_s)

    def _path_for(self, record_id: str) -> Path:
        return self._records_dir / f"{record_id}.json"

    def _save_record(self, record: OperationRecord):
        with self._lock:
            self._path_for(record.operation_id).write_text(
                json.dumps(record.to_dict(), indent=2),
                encoding="utf-8",
            )

    def _list_records(self) -> list[OperationRecord]:
        records = []
        with self._lock:
            for f in sorted(self._records_dir.glob("*.json"), reverse=True):
                try:
                    d = json.loads(f.read_text(encoding="utf-8"))
                    records.append(OperationRecord.from_dict(d))
                except Exception as e:
                    logger.warning("Failed to load operation record %s: %s", f.name, e)
        return records
