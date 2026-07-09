import tempfile
from pathlib import Path

import pytest

from mindmargin.executive.agent import ExecutiveAgent
from mindmargin.executive.policy import PolicyType


class TestExecutiveAgent:
    @pytest.fixture
    def agent(self):
        a = ExecutiveAgent()
        yield a

    def test_create(self, agent):
        assert agent is not None

    def test_run_once(self, agent):
        result = agent.run_once()
        assert result["status"] == "completed"
        assert result["cycle"] == 1
        assert isinstance(result["actions_executed"], list)

    def test_run_once_increments_cycle(self, agent):
        agent.run_once()
        result = agent.run_once()
        assert result["cycle"] == 2

    def test_get_status(self, agent):
        data = agent.get_status()
        assert "running" in data
        assert "cycle_count" in data
        assert "policy" in data
        assert "memory" in data

    def test_get_plan_initial(self, agent):
        data = agent.get_plan()
        assert "actions" in data

    def test_get_history(self, agent):
        agent.run_once()
        history = agent.get_history()
        assert isinstance(history, list)

    def test_get_memory(self, agent):
        data = agent.get_memory()
        assert "total" in data

    def test_get_policy(self, agent):
        data = agent.get_policy()
        assert "policy_type" in data

    def test_set_policy(self, agent):
        result = agent.set_policy("aggressive")
        assert result["status"] == "ok"
        assert agent.get_policy()["policy_type"] == "aggressive"

    def test_set_policy_invalid(self, agent):
        with pytest.raises(ValueError):
            agent.set_policy("invalid_policy")

    def test_custom_policy_type(self):
        agent = ExecutiveAgent(policy_type=PolicyType.GROWTH)
        assert agent.get_policy()["policy_type"] == "growth"

    def test_memory_records_after_cycle(self, agent):
        agent.run_once()
        memory_data = agent.get_memory()
        assert memory_data["total"] >= 1

    def test_start_stop_loop(self, agent):
        agent.start_loop()
        assert agent.get_status()["running"] is True
        agent.stop_loop(timeout_s=2.0)
        assert agent.get_status()["running"] is False

    def test_start_loop_idempotent(self, agent):
        agent.start_loop()
        agent.start_loop()
        agent.stop_loop(timeout_s=2.0)
        assert True
