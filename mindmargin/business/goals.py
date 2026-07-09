import json
import logging
import uuid
from pathlib import Path
from typing import Optional

from mindmargin.config import settings
from mindmargin.business.models import (
    BusinessGoal, BusinessGoalType, utcnow,
)

logger = logging.getLogger(__name__)

DEFAULT_GOALS = [
    BusinessGoal(
        goal_id="goal_revenue",
        goal_type=BusinessGoalType.MAXIMIZE_REVENUE,
        name="Maximize Revenue",
        target_value=10000.0,
        unit="USD",
        weight=1.0,
    ),
    BusinessGoal(
        goal_id="goal_subscribers",
        goal_type=BusinessGoalType.MAXIMIZE_SUBSCRIBERS,
        name="Grow Subscribers",
        target_value=10000,
        unit="subscribers",
        weight=0.8,
    ),
    BusinessGoal(
        goal_id="goal_watchtime",
        goal_type=BusinessGoalType.MAXIMIZE_WATCH_TIME,
        name="Maximize Watch Time",
        target_value=100000,
        unit="hours",
        weight=0.7,
    ),
    BusinessGoal(
        goal_id="goal_engagement",
        goal_type=BusinessGoalType.MAXIMIZE_ENGAGEMENT,
        name="Maximize Engagement",
        target_value=0.05,
        unit="rate",
        weight=0.6,
    ),
    BusinessGoal(
        goal_id="goal_retention",
        goal_type=BusinessGoalType.MAXIMIZE_RETENTION,
        name="Maximize Audience Retention",
        target_value=0.5,
        unit="rate",
        weight=0.5,
    ),
    BusinessGoal(
        goal_id="goal_brand",
        goal_type=BusinessGoalType.BRAND_GROWTH,
        name="Brand Growth",
        target_value=1000,
        unit="mentions",
        weight=0.4,
    ),
]


class GoalEngine:
    def __init__(self, persist_dir: str = ""):
        root = Path(persist_dir or settings.storage.temp_root)
        self._goals_dir = root / "business" / "goals"
        self._goals_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_defaults()

    def _ensure_defaults(self):
        for goal in DEFAULT_GOALS:
            path = self._goals_dir / f"{goal.goal_id}.json"
            if not path.exists():
                self._save(goal)

    def _path_for(self, goal_id: str) -> Path:
        return self._goals_dir / f"{goal_id}.json"

    def _save(self, goal: BusinessGoal):
        path = self._path_for(goal.goal_id)
        path.write_text(json.dumps(goal.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

    def get_goal(self, goal_id: str) -> Optional[BusinessGoal]:
        path = self._path_for(goal_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return BusinessGoal.from_dict(data)
        except Exception:
            return None

    def list_goals(self, enabled_only: bool = False) -> list[BusinessGoal]:
        goals = []
        for p in sorted(self._goals_dir.glob("*.json")):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                goal = BusinessGoal.from_dict(data)
                if enabled_only and not goal.enabled:
                    continue
                goals.append(goal)
            except Exception:
                continue
        return goals

    def update_goal(self, goal: BusinessGoal) -> BusinessGoal:
        self._save(goal)
        return goal

    def set_goal_value(self, goal_id: str, current_value: float) -> Optional[BusinessGoal]:
        goal = self.get_goal(goal_id)
        if not goal:
            return None
        goal.current_value = current_value
        self._save(goal)
        return goal

    def create_goal(self, goal_type: BusinessGoalType, name: str,
                    target_value: float, unit: str = "", weight: float = 1.0) -> BusinessGoal:
        goal = BusinessGoal(
            goal_id=f"goal_{uuid.uuid4().hex[:10]}",
            goal_type=goal_type,
            name=name,
            target_value=target_value,
            unit=unit,
            weight=weight,
            enabled=True,
        )
        self._save(goal)
        return goal

    def delete_goal(self, goal_id: str) -> bool:
        path = self._path_for(goal_id)
        if path.exists():
            path.unlink()
            return True
        return False

    def get_overall_progress(self) -> dict:
        goals = self.list_goals(enabled_only=True)
        if not goals:
            return {"total": 0, "achieved": 0, "progress_pct": 0.0}
        achieved = sum(1 for g in goals if g.is_achieved)
        total_progress = sum(g.progress_pct for g in goals)
        return {
            "total": len(goals),
            "achieved": achieved,
            "progress_pct": round(total_progress / len(goals), 1),
        }

    def get_weighted_score(self) -> float:
        goals = self.list_goals(enabled_only=True)
        if not goals:
            return 0.0
        total_weight = sum(g.weight for g in goals)
        if total_weight == 0:
            return 0.0
        weighted_sum = sum(g.progress_pct * g.weight for g in goals)
        return round(weighted_sum / total_weight, 2)
