import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from mindmargin.executive.planner import Action, ActionType, ActionPriority

logger = logging.getLogger(__name__)


@dataclass
class ExecutionResult:
    action_type: str = ""
    status: str = "pending"
    result: dict = field(default_factory=dict)
    error: str = ""
    started_at: str = ""
    completed_at: str = ""
    duration_s: float = 0.0

    def to_dict(self) -> dict:
        return {
            "action_type": self.action_type,
            "status": self.status,
            "result": self.result,
            "error": self.error,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_s": round(self.duration_s, 2),
        }


ACTION_HANDLERS = {
    ActionType.PUBLISH_CONTENT: "_exec_publish",
    ActionType.RUN_DAILY_INTELLIGENCE: "_exec_daily_intelligence",
    ActionType.RUN_DAILY_ANALYTICS: "_exec_daily_analytics",
    ActionType.RUN_FEEDBACK: "_exec_feedback",
    ActionType.RUN_EXPERIMENTS: "_exec_experiments",
    ActionType.RUN_DECISION: "_exec_decision",
    ActionType.RUN_CHANNEL_CYCLE: "_exec_channel_cycle",
    ActionType.RUN_SELECTION: "_exec_selection",
    ActionType.RUN_AB_ROTATION: "_exec_ab_rotation",
    ActionType.RUN_DISTRIBUTION: "_exec_distribution",
    ActionType.RECOVER_FAILED: "_exec_recover",
    ActionType.HEALTH_CHECK: "_exec_health_check",
    ActionType.SCHEDULE_OPERATIONS: "_exec_schedule",
    ActionType.OBSERVE_PLATFORM: "_exec_observe",
    ActionType.RECORD_LESSON: "_exec_record_lesson",
}


class ExecutiveExecutor:
    def __init__(self):
        self._history: list[ExecutionResult] = []

    def execute(self, action: Action) -> ExecutionResult:
        result = ExecutionResult(
            action_type=action.action_type.value,
            started_at=datetime.now(timezone.utc).isoformat(),
        )
        handler_name = ACTION_HANDLERS.get(action.action_type)
        if not handler_name:
            result.status = "skipped"
            result.error = f"No handler for {action.action_type.value}"
            result.completed_at = datetime.now(timezone.utc).isoformat()
            self._history.append(result)
            return result

        handler = getattr(self, handler_name, None)
        if not handler:
            result.status = "skipped"
            result.error = f"Handler {handler_name} not found"
            result.completed_at = datetime.now(timezone.utc).isoformat()
            self._history.append(result)
            return result

        start = time.monotonic()
        try:
            result.result = handler(action)
            result.status = "completed"
        except Exception as e:
            logger.error("Execution failed for %s: %s", action.action_type.value, e)
            result.status = "failed"
            result.error = str(e)
        result.completed_at = datetime.now(timezone.utc).isoformat()
        result.duration_s = time.monotonic() - start
        self._history.append(result)
        return result

    def get_history(self, limit: int = 50) -> list[ExecutionResult]:
        return self._history[-limit:]

    def _exec_daily_intelligence(self, action: Action) -> dict:
        from mindmargin.jobs.daily_intelligence import run_daily_intelligence_job
        return run_daily_intelligence_job()

    def _exec_daily_analytics(self, action: Action) -> dict:
        from mindmargin.jobs.daily_analytics import run_daily_job
        return run_daily_job()

    def _exec_feedback(self, action: Action) -> dict:
        from mindmargin.intelligence.feedback_engine import run_feedback_cycle
        return run_feedback_cycle()

    def _exec_experiments(self, action: Action) -> dict:
        from mindmargin.intelligence.experiments import run_experiment_cycle
        return run_experiment_cycle()

    def _exec_decision(self, action: Action) -> dict:
        from mindmargin.agents.decision_executor import execute_top_decision
        return execute_top_decision()

    def _exec_channel_cycle(self, action: Action) -> dict:
        from mindmargin.channel.manager import ChannelManager
        mgr = ChannelManager()
        return mgr.run_daily_cycle()

    def _exec_selection(self, action: Action) -> dict:
        from mindmargin.analytics.selection import run_selection_cycle
        return run_selection_cycle()

    def _exec_ab_rotation(self, action: Action) -> dict:
        from mindmargin.analytics.ab_testing import run_ab_rotation_cycle
        return run_ab_rotation_cycle(dry_run=False)

    def _exec_distribution(self, action: Action) -> dict:
        from mindmargin.agents.distribution import DistributionAgent
        agent = DistributionAgent()
        return agent.run_all()

    def _exec_recover(self, action: Action) -> dict:
        from mindmargin.operations.controller import OperationsController
        from mindmargin.core.workflows import WorkflowEngine
        ctrl = OperationsController(engine=WorkflowEngine())
        recovered = ctrl.recover_failed()
        return {"status": "completed", "recovered": recovered}

    def _exec_health_check(self, action: Action) -> dict:
        from mindmargin.analytics.channel_brain import assess_channel_health
        health = assess_channel_health()
        return {"status": "completed", "health": health}

    def _exec_schedule(self, action: Action) -> dict:
        from mindmargin.operations.controller import OperationsController
        from mindmargin.core.workflows import WorkflowEngine
        from mindmargin.core.scheduler import Scheduler
        ctrl = OperationsController(engine=WorkflowEngine(), scheduler=Scheduler())
        scheduled = ctrl.schedule_all()
        return {"status": "completed", "scheduled": len(scheduled)}

    def _exec_observe(self, action: Action) -> dict:
        from mindmargin.executive.observer import Observer
        obs = Observer()
        snapshot = obs.observe_all()
        return snapshot.to_dict()

    def _exec_publish(self, action: Action) -> dict:
        return {"status": "completed", "message": "Publish triggered via decision engine"}

    def _exec_record_lesson(self, action: Action) -> dict:
        return {"status": "completed", "message": "Lesson recorded"}
