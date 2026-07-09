from unittest.mock import patch, MagicMock

import pytest

from mindmargin.executive.executor import ExecutiveExecutor, ExecutionResult, ACTION_HANDLERS
from mindmargin.executive.planner import Action, ActionType, ActionPriority


class TestExecutionResult:
    def test_create(self):
        result = ExecutionResult(action_type="test", status="completed")
        assert result.action_type == "test"
        assert result.status == "completed"

    def test_to_dict(self):
        result = ExecutionResult(
            action_type="run_decision",
            status="completed",
            duration_s=1.5,
        )
        d = result.to_dict()
        assert d["action_type"] == "run_decision"
        assert d["duration_s"] == 1.5


class TestExecutiveExecutor:
    @pytest.fixture
    def executor(self):
        return ExecutiveExecutor()

    def test_create(self, executor):
        assert executor is not None
        assert len(executor.get_history()) == 0

    def test_execute_observe(self, executor):
        action = Action(
            action_id="act_001",
            action_type=ActionType.OBSERVE_PLATFORM,
            priority=ActionPriority.LOW,
            reason="test",
        )
        result = executor.execute(action)
        assert result.status == "completed"
        assert "channel_health" in result.result

    def test_execute_recover(self, executor):
        action = Action(
            action_id="act_002",
            action_type=ActionType.RECOVER_FAILED,
            priority=ActionPriority.CRITICAL,
            reason="test",
        )
        result = executor.execute(action)
        assert result.status == "completed"
        assert "recovered" in result.result

    def test_execute_health_check(self, executor):
        action = Action(
            action_id="act_003",
            action_type=ActionType.HEALTH_CHECK,
            priority=ActionPriority.MEDIUM,
            reason="test",
        )
        result = executor.execute(action)
        assert result.status == "completed"

    def test_execute_unknown_action(self, executor):
        action = Action(
            action_id="act_004",
            action_type=ActionType.RECORD_LESSON,
            priority=ActionPriority.LOW,
            reason="test",
        )
        result = executor.execute(action)
        assert result.status == "completed"

    def test_execute_schedule(self, executor):
        action = Action(
            action_id="act_005",
            action_type=ActionType.SCHEDULE_OPERATIONS,
            priority=ActionPriority.LOW,
            reason="test",
        )
        result = executor.execute(action)
        assert result.status == "completed"

    def test_history_tracked(self, executor):
        for i in range(3):
            action = Action(
                action_id=f"act_{i}",
                action_type=ActionType.OBSERVE_PLATFORM,
                priority=ActionPriority.LOW,
                reason="test",
            )
            executor.execute(action)
        assert len(executor.get_history()) == 3

    def test_all_handlers_registered(self):
        for at in ActionType:
            assert at in ACTION_HANDLERS
