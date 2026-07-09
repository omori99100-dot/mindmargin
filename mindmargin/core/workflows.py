import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Optional

from mindmargin.config import settings
from mindmargin.core.events import publish
from mindmargin.core.hardening import generate_correlation_id, get_correlation_id, utcnow

logger = logging.getLogger(__name__)


class WorkflowState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIAL = "partial"
    CANCELLED = "cancelled"


class StepState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


@dataclass
class WorkflowStep:
    step_id: str
    name: str
    handler: Optional[Callable] = None
    dependencies: list[str] = field(default_factory=list)
    state: StepState = StepState.PENDING
    result: dict = field(default_factory=dict)
    error: str = ""
    retry_count: int = 0
    max_retries: int = 0
    timeout_s: float = 300
    started_at: str = ""
    completed_at: str = ""
    metadata: dict = field(default_factory=dict)

    @property
    def is_terminal(self) -> bool:
        return self.state in (StepState.COMPLETED, StepState.FAILED, StepState.SKIPPED, StepState.CANCELLED)


@dataclass
class Workflow:
    workflow_id: str
    name: str
    steps: dict[str, WorkflowStep] = field(default_factory=dict)
    state: WorkflowState = WorkflowState.PENDING
    created_at: str = ""
    started_at: str = ""
    completed_at: str = ""
    correlation_id: str = ""
    metadata: dict = field(default_factory=dict)

    @property
    def is_terminal(self) -> bool:
        return self.state in (WorkflowState.COMPLETED, WorkflowState.FAILED, WorkflowState.CANCELLED)

    def to_dict(self) -> dict:
        return {
            "workflow_id": self.workflow_id,
            "name": self.name,
            "state": self.state.value,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "correlation_id": self.correlation_id,
            "metadata": self.metadata,
            "steps": {sid: {
                "step_id": s.step_id,
                "name": s.name,
                "dependencies": s.dependencies,
                "state": s.state.value,
                "result": s.result,
                "error": s.error,
                "retry_count": s.retry_count,
                "max_retries": s.max_retries,
                "timeout_s": s.timeout_s,
                "started_at": s.started_at,
                "completed_at": s.completed_at,
                "metadata": s.metadata,
            } for sid, s in self.steps.items()},
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Workflow":
        steps = {}
        for sid, sd in d.get("steps", {}).items():
            sd["state"] = StepState(sd["state"])
            steps[sid] = WorkflowStep(**sd)
        d["state"] = WorkflowState(d["state"])
        d["steps"] = steps
        return cls(**{k: v for k, v in d.items() if k != "_event_handlers"})


def _deps_met(wf: Workflow, step: WorkflowStep) -> bool:
    return all(
        wf.steps.get(d, WorkflowStep(step_id="", name="")).state == StepState.COMPLETED
        for d in step.dependencies
    )


class WorkflowEngine:
    def __init__(self, persist_dir: str = ""):
        self._workflows: dict[str, Workflow] = {}
        self._lock = threading.RLock()
        root = Path(persist_dir or settings.storage.temp_root)
        self._persist_dir = root / "workflows"
        self._persist_dir.mkdir(parents=True, exist_ok=True)

    def create(self, name: str, steps: list[dict],
               metadata: Optional[dict] = None) -> str:
        wid = f"wf_{name}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')}_{uuid.uuid4().hex[:6]}"
        workflow_steps = {}
        for s in steps:
            sid = s.get("step_id", f"step_{len(workflow_steps)}")
            workflow_steps[sid] = WorkflowStep(
                step_id=sid,
                name=s.get("name", sid),
                handler=None,
                dependencies=s.get("dependencies", []),
                max_retries=s.get("max_retries", 0),
                timeout_s=s.get("timeout_s", 300),
                metadata=s.get("metadata", {}),
            )
        wf = Workflow(
            workflow_id=wid,
            name=name,
            steps=workflow_steps,
            created_at=utcnow(),
            correlation_id=get_correlation_id(),
            metadata=metadata or {},
        )
        with self._lock:
            self._workflows[wid] = wf
            self._save(wf)
        publish("workflow.created", data={"workflow_id": wid, "name": name}, source="workflow")
        return wid

    def register_step_handler(self, workflow_id: str, step_id: str, handler: Callable):
        with self._lock:
            wf = self._workflows.get(workflow_id)
            if not wf:
                raise ValueError(f"Workflow '{workflow_id}' not found")
            step = wf.steps.get(step_id)
            if not step:
                raise ValueError(f"Step '{step_id}' not found in workflow '{workflow_id}'")
            step.handler = handler

    def start(self, workflow_id: str) -> bool:
        with self._lock:
            wf = self._workflows.get(workflow_id)
            if not wf or wf.state != WorkflowState.PENDING:
                return False
            wf.state = WorkflowState.RUNNING
            wf.started_at = utcnow()
            self._save(wf)
        publish("workflow.started", data={"workflow_id": workflow_id}, source="workflow")
        threading.Thread(target=self._execute_ready, args=(workflow_id,), daemon=True).start()
        return True

    def get(self, workflow_id: str) -> Optional[Workflow]:
        with self._lock:
            wf = self._workflows.get(workflow_id)
            if wf:
                return wf
            return None

    def list_all(self) -> list[Workflow]:
        with self._lock:
            return list(self._workflows.values())

    def list_by_state(self, state: WorkflowState) -> list[Workflow]:
        return [wf for wf in self.list_all() if wf.state == state]

    def cancel(self, workflow_id: str) -> bool:
        with self._lock:
            wf = self._workflows.get(workflow_id)
            if not wf or wf.is_terminal:
                return False
            wf.state = WorkflowState.CANCELLED
            wf.completed_at = utcnow()
            for step in wf.steps.values():
                if not step.is_terminal:
                    step.state = StepState.CANCELLED
            self._save(wf)
        publish("workflow.cancelled", data={"workflow_id": workflow_id}, source="workflow")
        return True

    def resume(self, workflow_id: str) -> bool:
        with self._lock:
            wf = self._workflows.get(workflow_id)
            if not wf:
                return False
            if wf.state not in (WorkflowState.FAILED, WorkflowState.PARTIAL):
                return False
            for step in wf.steps.values():
                if step.state in (StepState.FAILED, StepState.CANCELLED):
                    step.state = StepState.PENDING
                    step.error = ""
                    step.retry_count = 0
            wf.state = WorkflowState.RUNNING
            self._save(wf)
        threading.Thread(target=self._execute_ready, args=(workflow_id,), daemon=True).start()
        return True

    def _execute_ready(self, workflow_id: str):
        wid = workflow_id

        def _execute():
            while True:
                ready = self._ready_steps(wid)
                if not ready:
                    break
                threads = []
                for step in ready:
                    t = threading.Thread(target=self._execute_step, args=(wid, step.step_id), daemon=True)
                    t.start()
                    threads.append(t)
                for t in threads:
                    t.join(timeout=10)
            with self._lock:
                current = self._workflows.get(wid)
                if not current:
                    return
                if current.state != WorkflowState.CANCELLED:
                    all_done = all(s.is_terminal for s in current.steps.values())
                    any_failed = any(s.state == StepState.FAILED for s in current.steps.values())
                    blocked = any(
                        s.state == StepState.PENDING for s in current.steps.values()
                        if not _deps_met(current, s)
                    )
                    if all_done:
                        current.state = WorkflowState.PARTIAL if any_failed else WorkflowState.COMPLETED
                        current.completed_at = utcnow()
                        self._save(current)
                        if any_failed:
                            publish("workflow.partial", data={"workflow_id": wid}, source="workflow")
                        else:
                            publish("workflow.completed", data={"workflow_id": wid}, source="workflow")
                    elif blocked:
                        current.state = WorkflowState.PARTIAL
                        current.completed_at = utcnow()
                        self._save(current)
                        publish("workflow.partial", data={"workflow_id": wid}, source="workflow")

        t = threading.Thread(target=_execute, daemon=True)
        t.start()

    def _ready_steps(self, workflow_id: str) -> list[WorkflowStep]:
        with self._lock:
            wf = self._workflows.get(workflow_id)
            if not wf or wf.state != WorkflowState.RUNNING:
                return []
            ready = []
            for step in wf.steps.values():
                if step.state != StepState.PENDING:
                    continue
                deps_met = all(
                    wf.steps.get(d, WorkflowStep(step_id="", name="")).state == StepState.COMPLETED
                    for d in step.dependencies
                )
                if deps_met:
                    ready.append(step)
            return ready

    def _execute_step(self, workflow_id: str, step_id: str):
        with self._lock:
            wf = self._workflows.get(workflow_id)
            step = wf.steps.get(step_id) if wf else None
            if not step or step.state != StepState.PENDING:
                return
            step.state = StepState.RUNNING
            step.started_at = utcnow()
            self._save(wf)

        handler = step.handler
        if not handler:
            self._complete_step(workflow_id, step_id, {})
            return

        try:
            if step.timeout_s > 0:
                result = [None]
                error = [None]

                def _run():
                    try:
                        result[0] = handler(step.metadata)
                    except Exception as e:
                        error[0] = e

                t = threading.Thread(target=_run, daemon=True)
                t.start()
                t.join(timeout=step.timeout_s)
                if t.is_alive():
                    raise TimeoutError(f"Step '{step.name}' timed out after {step.timeout_s}s")
                if error[0]:
                    raise error[0]
                self._complete_step(workflow_id, step_id, result[0] or {})
            else:
                res = handler(step.metadata)
                self._complete_step(workflow_id, step_id, res or {})
        except Exception as e:
            self._fail_step(workflow_id, step_id, str(e))

    def _complete_step(self, workflow_id: str, step_id: str, result: dict):
        with self._lock:
            wf = self._workflows.get(workflow_id)
            step = wf.steps.get(step_id) if wf else None
            if not step:
                return
            step.state = StepState.COMPLETED
            step.result = result
            step.completed_at = utcnow()
            self._save(wf)
        publish("workflow.step_completed", data={"workflow_id": workflow_id, "step_id": step_id},
                source="workflow")

    def _fail_step(self, workflow_id: str, step_id: str, error: str):
        should_retry = False
        with self._lock:
            wf = self._workflows.get(workflow_id)
            step = wf.steps.get(step_id) if wf else None
            if not step:
                return
            step.error = error
            if step.retry_count < step.max_retries:
                step.retry_count += 1
                step.state = StepState.PENDING
                logger.info("Retrying step '%s' (attempt %d/%d)", step.name, step.retry_count, step.max_retries)
                self._save(wf)
                should_retry = True
            else:
                step.state = StepState.FAILED
                step.completed_at = utcnow()
                self._save(wf)
                publish("workflow.step_failed", data={"workflow_id": workflow_id, "step_id": step_id, "error": error},
                        source="workflow")
        if should_retry:
            threading.Thread(target=self._execute_step, args=(workflow_id, step_id), daemon=True).start()

    @property
    def workflows(self) -> dict[str, Workflow]:
        return self._workflows

    def _path_for(self, wf: Workflow) -> Path:
        return self._persist_dir / f"{wf.workflow_id}.json"

    def _save(self, wf: Workflow):
        self._path_for(wf).write_text(json.dumps(wf.to_dict(), indent=2), encoding="utf-8")

    def _delete(self, wf: Workflow):
        p = self._path_for(wf)
        if p.exists():
            p.unlink()

    def recover(self) -> int:
        count = 0
        for f in sorted(self._persist_dir.glob("*.json")):
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
                wf = Workflow.from_dict(d)
                if wf.state == WorkflowState.RUNNING:
                    for step in wf.steps.values():
                        if step.state == StepState.RUNNING:
                            step.state = StepState.PENDING
                    wf.state = WorkflowState.PENDING
                if not wf.is_terminal:
                    self._workflows[wf.workflow_id] = wf
                    count += 1
            except Exception as e:
                logger.warning("Failed to recover workflow %s: %s", f.name, e)
        return count
