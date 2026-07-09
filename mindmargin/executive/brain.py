import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from mindmargin.executive.memory import ExecutiveMemory
from mindmargin.executive.observer import Observer, PlatformSnapshot
from mindmargin.executive.planner import ActionPlan, ActionType, ActionPriority, Planner
from mindmargin.executive.policy import PolicyConfig, PolicyEngine, PolicyType

logger = logging.getLogger(__name__)


@dataclass
class DecisionRationale:
    selected_action: str
    priority: str
    reason: str
    alternatives: list[str] = field(default_factory=list)
    snapshot_summary: str = ""
    policy_applied: str = ""
    timestamp: str = ""

    def to_dict(self) -> dict:
        return {
            "selected_action": self.selected_action,
            "priority": self.priority,
            "reason": self.reason,
            "alternatives": self.alternatives,
            "snapshot_summary": self.snapshot_summary,
            "policy_applied": self.policy_applied,
            "timestamp": self.timestamp,
        }


class Brain:
    def __init__(self, memory: Optional[ExecutiveMemory] = None,
                 policy_engine: Optional[PolicyEngine] = None):
        self._memory = memory or ExecutiveMemory()
        self._policy = policy_engine or PolicyEngine()
        self._observer = Observer()
        self._planner = Planner()

    @property
    def memory(self) -> ExecutiveMemory:
        return self._memory

    @property
    def policy_engine(self) -> PolicyEngine:
        return self._policy

    def think(self) -> tuple[PlatformSnapshot, ActionPlan, Optional[DecisionRationale]]:
        snapshot = self._observer.observe_all()
        config = self._policy.get_config()
        plan = self._planner.build_plan(snapshot, config)
        decision = self._decide(plan, snapshot, config)
        return snapshot, plan, decision

    def _decide(self, plan: ActionPlan, snapshot: PlatformSnapshot,
                config: PolicyConfig) -> Optional[DecisionRationale]:
        action = self._planner.pick_top_action(plan)
        if not action:
            return None

        alternatives = [a.action_type.value for a in plan.actions[1:5]]

        rationale = DecisionRationale(
            selected_action=action.action_type.value,
            priority=action.priority.value,
            reason=action.reason,
            alternatives=alternatives,
            snapshot_summary=plan.snapshot_summary,
            policy_applied=config.policy_type.value,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        self._memory.record(
            category="decision_rationale",
            key=action.action_type.value,
            value=rationale.to_dict(),
            score=action.estimated_impact,
        )

        return rationale

    def record_outcome(self, action_type: str, success: bool, detail: dict):
        category = "strategy_success" if success else "strategy_failure"
        self._memory.record(
            category=category,
            key=action_type,
            value=detail,
            score=1.0 if success else 0.0,
        )

    def record_lesson(self, lesson: str, context: dict):
        self._memory.record(
            category="lesson_learned",
            key=lesson[:80],
            value=context,
        )

    def record_provider_health(self, provider: str, healthy: bool):
        self._memory.record(
            category="provider_reliability",
            key=provider,
            value={"success": healthy, "provider": provider},
        )

    def record_seasonality(self, pattern: str, detail: dict):
        self._memory.record(
            category="seasonality",
            key=pattern,
            value=detail,
        )

    def record_content_fatigue(self, topic: str, fatigue_score: float):
        self._memory.record(
            category="content_fatigue",
            key=topic,
            value={"topic": topic, "fatigue": fatigue_score},
            score=fatigue_score,
        )

    def get_stats(self) -> dict:
        memory_stats = self._memory.to_dict()
        config = self._policy.get_config()
        return {
            "policy": config.policy_type.value,
            "memory": memory_stats,
            "lessons_count": len(self._memory.get_lessons()),
            "successful_strategies": len(self._memory.get_successful_strategies()),
            "failed_strategies": len(self._memory.get_failed_strategies()),
        }
