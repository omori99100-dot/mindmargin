import pytest

from mindmargin.executive.planner import (
    Action, ActionPlan, ActionType, ActionPriority, Planner,
    PRIORITY_ORDER,
)
from mindmargin.executive.observer import PlatformSnapshot


class TestActionPriority:
    def test_ordering(self):
        assert PRIORITY_ORDER[ActionPriority.CRITICAL] < PRIORITY_ORDER[ActionPriority.HIGH]
        assert PRIORITY_ORDER[ActionPriority.HIGH] < PRIORITY_ORDER[ActionPriority.MEDIUM]
        assert PRIORITY_ORDER[ActionPriority.MEDIUM] < PRIORITY_ORDER[ActionPriority.LOW]


class TestAction:
    def test_create(self):
        action = Action(
            action_id="act_001",
            action_type=ActionType.RUN_DECISION,
            priority=ActionPriority.HIGH,
            reason="Opportunities available",
        )
        assert action.action_id == "act_001"
        assert action.priority == ActionPriority.HIGH

    def test_to_dict(self):
        action = Action(
            action_id="act_002",
            action_type=ActionType.PUBLISH_CONTENT,
            priority=ActionPriority.MEDIUM,
            reason="Content ready",
            estimated_impact=0.7,
        )
        d = action.to_dict()
        assert d["action_type"] == "publish_content"
        assert d["estimated_impact"] == 0.7


class TestActionPlan:
    def test_create(self):
        plan = ActionPlan(actions=[], snapshot_summary="test")
        assert plan.snapshot_summary == "test"

    def test_to_dict(self):
        plan = ActionPlan(
            actions=[
                Action("act_001", ActionType.RUN_DECISION, ActionPriority.HIGH, "test"),
            ],
            snapshot_summary="summary",
        )
        d = plan.to_dict()
        assert d["total"] == 1


class TestPlanner:
    @pytest.fixture
    def planner(self):
        return Planner()

    def test_create(self, planner):
        assert planner is not None

    def test_build_plan_critical_failures(self, planner):
        snap = PlatformSnapshot(failed_workflows=10, failed_queue=10)
        plan = planner.build_plan(snap)
        assert len(plan.actions) >= 1
        assert plan.actions[0].priority == ActionPriority.CRITICAL

    def test_build_plan_content_ready(self, planner):
        snap = PlatformSnapshot(active_content=3, scheduled_count=0)
        plan = planner.build_plan(snap)
        priorities = [a.priority for a in plan.actions]
        assert ActionPriority.HIGH in priorities

    def test_build_plan_opportunities(self, planner):
        snap = PlatformSnapshot(opportunities_count=5, published_today=0)
        plan = planner.build_plan(snap)
        action_types = [a.action_type for a in plan.actions]
        assert ActionType.RUN_DECISION in action_types

    def test_build_plan_no_experiments(self, planner):
        snap = PlatformSnapshot(experiments_active=0)
        plan = planner.build_plan(snap)
        action_types = [a.action_type for a in plan.actions]
        assert ActionType.RUN_EXPERIMENTS in action_types

    def test_build_plan_always_has_medium_actions(self, planner):
        snap = PlatformSnapshot()
        plan = planner.build_plan(snap)
        assert len(plan.actions) >= 3

    def test_pick_top_action(self, planner):
        snap = PlatformSnapshot(failed_workflows=10)
        plan = planner.build_plan(snap)
        top = planner.pick_top_action(plan)
        assert top is not None
        assert top.priority == ActionPriority.CRITICAL

    def test_pick_top_action_empty(self, planner):
        plan = ActionPlan(actions=[])
        top = planner.pick_top_action(plan)
        assert top is None

    def test_actions_sorted_by_priority(self, planner):
        snap = PlatformSnapshot(failed_workflows=10, active_content=3, published_today=0,
                                experiments_active=0, scheduler_active=0)
        plan = planner.build_plan(snap)
        priorities = [PRIORITY_ORDER[a.priority] for a in plan.actions]
        assert priorities == sorted(priorities)
