import tempfile
from pathlib import Path

import pytest

from mindmargin.executive.brain import Brain, DecisionRationale
from mindmargin.executive.memory import ExecutiveMemory
from mindmargin.executive.observer import PlatformSnapshot
from mindmargin.executive.policy import PolicyEngine, PolicyType


class TestDecisionRationale:
    def test_create(self):
        r = DecisionRationale(
            selected_action="run_decision",
            priority="high",
            reason="Opportunities available",
        )
        assert r.selected_action == "run_decision"
        assert r.priority == "high"

    def test_to_dict(self):
        r = DecisionRationale(
            selected_action="run_decision",
            priority="high",
            reason="test",
            policy_applied="balanced",
        )
        d = r.to_dict()
        assert d["policy_applied"] == "balanced"


class TestBrain:
    @pytest.fixture
    def brain(self):
        tmpdir = tempfile.mkdtemp()
        memory = ExecutiveMemory(persist_dir=tmpdir)
        policy = PolicyEngine(persist_dir=tmpdir)
        b = Brain(memory=memory, policy_engine=policy)
        yield b
        import shutil
        try:
            shutil.rmtree(tmpdir, ignore_errors=True)
        except Exception:
            pass

    def test_create(self, brain):
        assert brain is not None

    def test_think(self, brain):
        snapshot, plan, decision = brain.think()
        assert snapshot is not None
        assert plan is not None
        assert snapshot.timestamp != ""

    def test_think_returns_decision(self, brain):
        snapshot, plan, decision = brain.think()
        if decision:
            assert decision.selected_action != ""
            assert decision.policy_applied == "balanced"

    def test_record_outcome_success(self, brain):
        brain.record_outcome("run_decision", True, {"status": "completed"})
        entries = brain.memory.get_successful_strategies()
        assert len(entries) == 1

    def test_record_outcome_failure(self, brain):
        brain.record_outcome("run_decision", False, {"error": "timeout"})
        entries = brain.memory.get_failed_strategies()
        assert len(entries) == 1

    def test_record_lesson(self, brain):
        brain.record_lesson("Always check health first", {"importance": "high"})
        lessons = brain.memory.get_lessons()
        assert len(lessons) == 1

    def test_record_provider_health(self, brain):
        brain.record_provider_health("ollama", True)
        rel = brain.memory.get_provider_reliability("ollama")
        assert rel["reliability"] == 1.0

    def test_record_seasonality(self, brain):
        brain.record_seasonality("friday_evening", {"trend": "up"})
        patterns = brain.memory.get_seasonality()
        assert "friday_evening" in patterns

    def test_record_content_fatigue(self, brain):
        brain.record_content_fatigue("python_tutorials", 0.6)
        fatigue = brain.memory.get_content_fatigue("python_tutorials")
        assert fatigue == 0.6

    def test_get_stats(self, brain):
        brain.record_outcome("test", True, {})
        stats = brain.get_stats()
        assert stats["policy"] == "balanced"
        assert stats["memory"]["total"] == 1
