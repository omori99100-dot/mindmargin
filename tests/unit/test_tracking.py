"""Tests for token usage tracking, cost estimation, and latency metrics."""

from mindmargin.integrations.tracking import (
    UsageTracker,
    estimate_tokens,
    compute_cost,
    get_tracker,
)


class TestEstimateTokens:
    def test_empty_string(self):
        assert estimate_tokens("") >= 1

    def test_simple_text(self):
        tokens = estimate_tokens("hello world")
        assert tokens > 0

    def test_longer_text(self):
        tokens = estimate_tokens("word " * 100)
        assert tokens >= 100


class TestComputeCost:
    def test_ollama_is_free(self):
        cost = compute_cost("ollama/llama3", 1000, 500)
        assert cost == 0.0

    def test_openai_cost_nonzero(self):
        cost = compute_cost("openai/gpt-4o-mini", 1000, 500)
        assert cost > 0

    def test_unknown_provider_uses_fallback(self):
        cost = compute_cost("unknown/model", 1000, 1000)
        assert cost > 0

    def test_zero_tokens(self):
        cost = compute_cost("openai/gpt-4o", 0, 0)
        assert cost >= 0


class TestUsageTracker:
    def test_empty_summary(self):
        t = UsageTracker()
        summary = t.summary()
        assert summary["total_calls"] == 0

    def test_single_record(self):
        t = UsageTracker()
        t.record("ollama", "llama3", "test", 100, 50, 500.0, success=True)
        summary = t.summary()
        assert summary["total_calls"] == 1
        assert summary["total_tokens"] == 150
        assert summary["successes"] == 1
        assert summary["failures"] == 0

    def test_failure_record(self):
        t = UsageTracker()
        t.record("openai", "gpt-4o", "test", 0, 0, 100.0, success=False)
        summary = t.summary()
        assert summary["total_calls"] == 1
        assert summary["failures"] == 1

    def test_by_task(self):
        t = UsageTracker()
        t.record("ollama", "llama3", "title", 50, 100, 200.0)
        t.record("ollama", "llama3", "hook", 30, 60, 150.0)
        t.record("ollama", "llama3", "title", 40, 80, 180.0)
        titles = t.by_task("title")
        assert len(titles) == 2
        hooks = t.by_task("hook")
        assert len(hooks) == 1

    def test_by_provider_summary(self):
        t = UsageTracker()
        t.record("ollama", "llama3", "test", 100, 50, 500.0)
        t.record("openai", "gpt-4o-mini", "test", 200, 100, 300.0)
        summary = t.summary()
        assert "ollama" in summary["by_provider"]
        assert "openai" in summary["by_provider"]

    def test_reset(self):
        t = UsageTracker()
        t.record("ollama", "llama3", "test", 10, 5, 50.0)
        assert t.summary()["total_calls"] == 1
        t.reset()
        assert t.summary()["total_calls"] == 0

    def test_cached_flag(self):
        t = UsageTracker()
        t.record("ollama", "llama3", "test", 0, 0, 0.0, cached=True)
        assert t._records[0].cached is True

    def test_global_tracker_is_singleton(self):
        t1 = get_tracker()
        t2 = get_tracker()
        assert t1 is t2
