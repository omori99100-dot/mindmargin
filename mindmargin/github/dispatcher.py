import json
import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from mindmargin.config import settings
from mindmargin.github.controller import GitHubController
from mindmargin.github.state import WorkflowRun, WorkflowRunState
from mindmargin.github.workflows import (
    WorkflowDefinition, WorkflowPriority, WorkflowRegistry, WorkflowTrigger,
)

logger = logging.getLogger(__name__)


@dataclass
class DispatchResult:
    dispatched: bool = False
    run_id: str = ""
    workflow_id: str = ""
    workflow_name: str = ""
    reason: str = ""
    timestamp: str = ""

    def to_dict(self) -> dict:
        return {
            "dispatched": self.dispatched,
            "run_id": self.run_id,
            "workflow_id": self.workflow_id,
            "workflow_name": self.workflow_name,
            "reason": self.reason,
            "timestamp": self.timestamp,
        }


class WorkflowDispatcher:
    def __init__(self, controller: GitHubController):
        self._controller = controller
        self._registry = controller.registry
        self._dispatch_log: list[DispatchResult] = []
        self._lock = threading.RLock()
        self._persist_dir = Path(settings.storage.temp_root) / "github" / "dispatcher"
        self._persist_dir.mkdir(parents=True, exist_ok=True)
        self._load_log()

    def _load_log(self):
        log_path = self._persist_dir / "dispatch_log.json"
        if log_path.exists():
            try:
                data = json.loads(log_path.read_text(encoding="utf-8"))
                self._dispatch_log = [DispatchResult(**d) for d in data]
            except Exception:
                pass

    def _save_log(self):
        log_path = self._persist_dir / "dispatch_log.json"
        log_path.write_text(
            json.dumps([d.to_dict() for d in self._dispatch_log[-500:]], indent=2),
            encoding="utf-8",
        )

    def _record_dispatch(self, result: DispatchResult):
        with self._lock:
            self._dispatch_log.append(result)
            self._save_log()

    def dispatch(self, workflow_id: str, trigger: str = "manual",
                 params: dict = None, priority: str = "") -> DispatchResult:
        now = datetime.now(timezone.utc).isoformat()
        definition = self._registry.get(workflow_id)
        if not definition:
            return DispatchResult(
                reason=f"Workflow '{workflow_id}' not found",
                timestamp=now,
            )

        if not definition.enabled:
            return DispatchResult(
                workflow_id=workflow_id,
                workflow_name=definition.name,
                reason="Workflow is disabled",
                timestamp=now,
            )

        result = self._controller.start_workflow(workflow_id, trigger, params)
        dispatch_result = DispatchResult(
            dispatched=result.get("status") == "started",
            run_id=result.get("run_id", ""),
            workflow_id=workflow_id,
            workflow_name=definition.name,
            reason=result.get("error", "OK"),
            timestamp=now,
        )

        self._record_dispatch(dispatch_result)
        return dispatch_result

    def dispatch_event(self, event_type: str, event_data: dict = None) -> list[DispatchResult]:
        results = []
        definitions = self._registry.list_all(enabled_only=True)

        for defn in definitions:
            if defn.trigger == WorkflowTrigger.EVENT:
                should_dispatch = self._match_event(defn, event_type, event_data or {})
                if should_dispatch:
                    result = self.dispatch(defn.workflow_id, trigger=f"event:{event_type}",
                                          params=event_data)
                    results.append(result)

        return results

    def _match_event(self, definition: WorkflowDefinition, event_type: str,
                     event_data: dict) -> bool:
        metadata = definition.metadata
        listening_events = metadata.get("listen_events", [])
        if not listening_events:
            return False
        return event_type in listening_events

    def dispatch_scheduled(self) -> list[DispatchResult]:
        results = []
        scheduled = self._registry.get_scheduled_workflows()

        for defn in scheduled:
            if self._should_run_now(defn):
                result = self.dispatch(defn.workflow_id, trigger="schedule")
                results.append(result)

        return results

    def _should_run_now(self, definition: WorkflowDefinition) -> bool:
        if not definition.cron:
            return False
        now = datetime.now(timezone.utc)
        return self._cron_matches_now(definition.cron, now)

    def _cron_matches_now(self, cron_expr: str, now: datetime) -> bool:
        parts = cron_expr.strip().split()
        if len(parts) < 5:
            return False
        minute, hour, day, month, dow = parts[:5]

        if minute != "*" and not self._cron_field_matches(now.minute, minute):
            return False
        if hour != "*" and not self._cron_field_matches(now.hour, hour):
            return False
        if day != "*" and not self._cron_field_matches(now.day, day):
            return False
        if month != "*" and not self._cron_field_matches(now.month, month):
            return False
        if dow != "*" and not self._cron_field_matches(now.weekday(), dow):
            return False
        return True

    def _cron_field_matches(self, actual: int, pattern: str) -> bool:
        if pattern == "*":
            return True
        if pattern.isdigit():
            return actual == int(pattern)
        if "/" in pattern:
            base, step = pattern.split("/", 1)
            step = int(step)
            if base == "*":
                return actual % step == 0
            return actual >= int(base) and (actual - int(base)) % step == 0
        if "-" in pattern:
            start, end = pattern.split("-", 1)
            return int(start) <= actual <= int(end)
        if "," in pattern:
            return actual in [int(x) for x in pattern.split(",")]
        return False

    def dispatch_by_priority(self, priority: str = "high") -> list[DispatchResult]:
        results = []
        try:
            prio = WorkflowPriority(priority)
        except ValueError:
            return results

        definitions = self._registry.list_by_priority(prio)
        for defn in definitions:
            result = self.dispatch(defn.workflow_id, trigger=f"priority:{priority}")
            results.append(result)

        return results

    def dispatch_chain(self, chain_id: str) -> dict:
        chain = self._registry.get_chain(chain_id)
        if not chain:
            return {"status": "failed", "error": f"Chain '{chain_id}' not found"}

        results = []
        for wf_id in chain.workflow_ids:
            result = self.dispatch(wf_id, trigger="chain")
            results.append(result.to_dict())

        chain.state = "dispatched"
        return {
            "status": "dispatched",
            "chain_id": chain_id,
            "workflow_count": len(chain.workflow_ids),
            "results": results,
        }

    def get_dispatch_log(self, limit: int = 50) -> list[dict]:
        with self._lock:
            log = self._dispatch_log
        return [d.to_dict() for d in log[-limit:]]

    def get_dispatch_stats(self) -> dict:
        with self._lock:
            log = self._dispatch_log
        by_trigger = {}
        for d in log:
            trigger = d.reason if d.dispatched else "failed"
            by_trigger[trigger] = by_trigger.get(trigger, 0) + 1

        return {
            "total_dispatches": len(log),
            "successful": sum(1 for d in log if d.dispatched),
            "failed": sum(1 for d in log if not d.dispatched),
            "by_trigger": by_trigger,
        }
