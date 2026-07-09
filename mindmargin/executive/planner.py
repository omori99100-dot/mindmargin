import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from mindmargin.executive.observer import PlatformSnapshot

logger = logging.getLogger(__name__)


class ActionPriority(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ActionType(str, Enum):
    PUBLISH_CONTENT = "publish_content"
    RUN_DAILY_INTELLIGENCE = "run_daily_intelligence"
    RUN_DAILY_ANALYTICS = "run_daily_analytics"
    RUN_FEEDBACK = "run_feedback"
    RUN_EXPERIMENTS = "run_experiments"
    RUN_DECISION = "run_decision"
    RUN_CHANNEL_CYCLE = "run_channel_cycle"
    RUN_SELECTION = "run_selection"
    RUN_AB_ROTATION = "run_ab_rotation"
    RUN_DISTRIBUTION = "run_distribution"
    RECOVER_FAILED = "recover_failed"
    HEALTH_CHECK = "health_check"
    SCHEDULE_OPERATIONS = "schedule_operations"
    OBSERVE_PLATFORM = "observe_platform"
    RECORD_LESSON = "record_lesson"


@dataclass
class Action:
    action_id: str = ""
    action_type: ActionType = ActionType.OBSERVE_PLATFORM
    priority: ActionPriority = ActionPriority.MEDIUM
    reason: str = ""
    estimated_impact: float = 0.5
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "action_id": self.action_id,
            "action_type": self.action_type.value,
            "priority": self.priority.value,
            "reason": self.reason,
            "estimated_impact": self.estimated_impact,
            "metadata": self.metadata,
        }


@dataclass
class ActionPlan:
    actions: list[Action] = field(default_factory=list)
    snapshot_summary: str = ""
    generated_at: str = ""

    def to_dict(self) -> dict:
        return {
            "actions": [a.to_dict() for a in self.actions],
            "snapshot_summary": self.snapshot_summary,
            "generated_at": self.generated_at,
            "total": len(self.actions),
        }


PRIORITY_ORDER = {
    ActionPriority.CRITICAL: 0,
    ActionPriority.HIGH: 1,
    ActionPriority.MEDIUM: 2,
    ActionPriority.LOW: 3,
}


class Planner:
    def __init__(self):
        self._action_counter = 0

    def _next_id(self) -> str:
        self._action_counter += 1
        return f"act_{self._action_counter:04d}"

    def build_plan(self, snapshot: PlatformSnapshot, policy_config=None) -> ActionPlan:
        actions = []

        # Critical: recover failures
        if snapshot.failed_workflows > 3 or snapshot.failed_queue > 5:
            actions.append(Action(
                action_id=self._next_id(),
                action_type=ActionType.RECOVER_FAILED,
                priority=ActionPriority.CRITICAL,
                reason=f"Failed workflows={snapshot.failed_workflows}, dead letters={snapshot.failed_queue}",
                estimated_impact=0.9,
            ))

        # High: channel cycle if content ready
        if snapshot.active_content > 0 and snapshot.scheduled_count == 0:
            actions.append(Action(
                action_id=self._next_id(),
                action_type=ActionType.RUN_CHANNEL_CYCLE,
                priority=ActionPriority.HIGH,
                reason="Content ready but nothing scheduled",
                estimated_impact=0.8,
            ))

        # High: run decision if opportunities exist
        if snapshot.opportunities_count > 0 and snapshot.published_today == 0:
            actions.append(Action(
                action_id=self._next_id(),
                action_type=ActionType.RUN_DECISION,
                priority=ActionPriority.HIGH,
                reason=f"{snapshot.opportunities_count} opportunities, no publish today",
                estimated_impact=0.85,
            ))

        # Medium: daily intelligence
        actions.append(Action(
            action_id=self._next_id(),
            action_type=ActionType.RUN_DAILY_INTELLIGENCE,
            priority=ActionPriority.MEDIUM,
            reason="Periodic intelligence refresh",
            estimated_impact=0.6,
        ))

        # Medium: daily analytics
        actions.append(Action(
            action_id=self._next_id(),
            action_type=ActionType.RUN_DAILY_ANALYTICS,
            priority=ActionPriority.MEDIUM,
            reason="Periodic analytics collection",
            estimated_impact=0.5,
        ))

        # Medium: experiments if none active
        if snapshot.experiments_active == 0:
            actions.append(Action(
                action_id=self._next_id(),
                action_type=ActionType.RUN_EXPERIMENTS,
                priority=ActionPriority.MEDIUM,
                reason="No active experiments",
                estimated_impact=0.55,
            ))

        # Medium: feedback cycle
        actions.append(Action(
            action_id=self._next_id(),
            action_type=ActionType.RUN_FEEDBACK,
            priority=ActionPriority.MEDIUM,
            reason="Periodic feedback loop",
            estimated_impact=0.45,
        ))

        # Low: distribution
        if snapshot.active_content > 3:
            actions.append(Action(
                action_id=self._next_id(),
                action_type=ActionType.RUN_DISTRIBUTION,
                priority=ActionPriority.LOW,
                reason=f"Multiple active content ({snapshot.active_content}) — optimize distribution",
                estimated_impact=0.35,
            ))

        # Low: schedule operations if not running
        if snapshot.scheduler_active == 0:
            actions.append(Action(
                action_id=self._next_id(),
                action_type=ActionType.SCHEDULE_OPERATIONS,
                priority=ActionPriority.LOW,
                reason="No active scheduler entries",
                estimated_impact=0.3,
            ))

        # Sort by priority
        actions.sort(key=lambda a: PRIORITY_ORDER.get(a.priority, 99))

        summary = f"{len(actions)} actions planned. "
        if snapshot.problems:
            summary += f"Problems: {len(snapshot.problems)}. "
        if snapshot.opportunities:
            summary += f"Opportunities: {len(snapshot.opportunities)}."

        return ActionPlan(
            actions=actions,
            snapshot_summary=summary,
            generated_at=datetime.now(timezone.utc).isoformat(),
        )

    def pick_top_action(self, plan: ActionPlan) -> Optional[Action]:
        if plan.actions:
            return plan.actions[0]
        return None
