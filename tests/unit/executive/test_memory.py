import tempfile
from pathlib import Path

import pytest

from mindmargin.executive.memory import ExecutiveMemory, MAX_MEMORY_ENTRIES, MEMORY_CATEGORIES


class TestExecutiveMemory:
    @pytest.fixture
    def memory(self):
        tmpdir = tempfile.mkdtemp()
        m = ExecutiveMemory(persist_dir=tmpdir)
        yield m
        import shutil
        try:
            shutil.rmtree(tmpdir, ignore_errors=True)
        except Exception:
            pass

    def test_create(self, memory):
        assert memory is not None
        assert memory.count() == 0

    def test_record_and_query(self, memory):
        memory.record("strategy_success", "publish_daily", {"success": True}, score=0.9)
        assert memory.count() == 1
        results = memory.query(category="strategy_success")
        assert len(results) == 1
        assert results[0]["key"] == "publish_daily"

    def test_query_by_key(self, memory):
        memory.record("execution_history", "daily_analytics", {"status": "ok"})
        memory.record("execution_history", "daily_intelligence", {"status": "ok"})
        memory.record("strategy_success", "publish_daily", {})
        results = memory.query(key="daily")
        assert len(results) == 3

    def test_query_limit(self, memory):
        for i in range(100):
            memory.record("execution_history", f"action_{i}", {"i": i})
        results = memory.query(limit=10)
        assert len(results) == 10

    def test_get_successful_strategies(self, memory):
        memory.record("strategy_success", "fast_publish", {"time": 300})
        memory.record("strategy_success", "batch_analytics", {"count": 5})
        results = memory.get_successful_strategies()
        assert len(results) == 2

    def test_get_failed_strategies(self, memory):
        memory.record("strategy_failure", "wrong_topic", {"reason": "low_interest"})
        results = memory.get_failed_strategies()
        assert len(results) == 1

    def test_get_lessons(self, memory):
        memory.record("lesson_learned", "always_check_health_before_publish", {"importance": "high"})
        lessons = memory.get_lessons()
        assert len(lessons) == 1

    def test_get_execution_history(self, memory):
        memory.record("execution_history", "run_analytics", {"status": "ok"})
        history = memory.get_execution_history()
        assert len(history) == 1

    def test_get_provider_reliability(self, memory):
        for i in range(5):
            memory.record("provider_reliability", "ollama", {"success": True})
        memory.record("provider_reliability", "ollama", {"success": False})
        rel = memory.get_provider_reliability("ollama")
        assert rel["provider"] == "ollama"
        assert rel["reliability"] < 1.0

    def test_get_provider_reliability_unknown(self, memory):
        rel = memory.get_provider_reliability("unknown")
        assert rel["reliability"] == 1.0

    def test_get_seasonality(self, memory):
        memory.record("seasonality", "friday_evening", {"trend": "up"})
        patterns = memory.get_seasonality()
        assert "friday_evening" in patterns

    def test_get_content_fatigue(self, memory):
        memory.record("content_fatigue", "python_tutorials", {}, score=0.7)
        fatigue = memory.get_content_fatigue("python_tutorials")
        assert fatigue == 0.7

    def test_get_content_fatigue_unknown(self, memory):
        fatigue = memory.get_content_fatigue("unknown_topic")
        assert fatigue == 0.0

    def test_get_decision_rationales(self, memory):
        memory.record("decision_rationale", "run_decision", {"reason": "high_opportunity"})
        rationales = memory.get_decision_rationales()
        assert len(rationales) == 1

    def test_clear_category(self, memory):
        memory.record("strategy_success", "a", {})
        memory.record("strategy_failure", "b", {})
        memory.clear_category("strategy_success")
        assert memory.count() == 1

    def test_clear_all(self, memory):
        memory.record("strategy_success", "a", {})
        memory.record("strategy_failure", "b", {})
        memory.clear_all()
        assert memory.count() == 0

    def test_to_dict(self, memory):
        memory.record("strategy_success", "a", {})
        memory.record("strategy_failure", "b", {})
        d = memory.to_dict()
        assert d["total"] == 2
        assert d["categories"]["strategy_success"] == 1

    def test_persistence(self):
        tmpdir = tempfile.mkdtemp()
        try:
            m1 = ExecutiveMemory(persist_dir=tmpdir)
            m1.record("strategy_success", "test", {"data": 1})
            m2 = ExecutiveMemory(persist_dir=tmpdir)
            assert m2.count() == 1
        finally:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_max_entries_trimmed(self, memory):
        for i in range(MAX_MEMORY_ENTRIES + 50):
            memory.record("execution_history", f"e_{i}", {"i": i})
        assert memory.count() <= MAX_MEMORY_ENTRIES
