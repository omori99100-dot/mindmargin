"""Unit tests for analytics.channel_brain — executive orchestration."""

import pytest
from mindmargin.analytics.channel_brain import (
    BrainDecision, assess_channel_health, run_brain_cycle,
)


class TestBrainDecision:
    def test_minimal_creation(self):
        d = BrainDecision(domain="test", action="do_something",
                          rationale="because", confidence=0.8, priority=1)
        assert d.domain == "test"
        assert d.action == "do_something"
        assert d.priority == 1
        assert d.parameters == {}

    def test_with_parameters(self):
        d = BrainDecision("pub", "go", "test", 0.9, 2, {"speed": "fast"})
        assert d.parameters["speed"] == "fast"


class TestAssessChannelHealth:
    def test_returns_health_dict(self):
        health = assess_channel_health()
        assert health["status"] == "completed"
        assert "overall_score" in health
        assert "overall_label" in health
        assert "dimensions" in health
        assert "content_volume" in health["dimensions"]
        assert "performance_quality" in health["dimensions"]
        assert "system_reliability" in health["dimensions"]
        assert "evolution_maturity" in health["dimensions"]

    def test_score_in_range(self):
        health = assess_channel_health()
        assert 0 <= health["overall_score"] <= 10

    def test_label_valid(self):
        health = assess_channel_health()
        assert health["overall_label"] in (
            "excellent", "good", "fair", "needs_attention"
        )


class TestRunBrainCycle:
    def test_returns_complete_report(self):
        result = run_brain_cycle()
        assert result["status"] == "completed"
        assert "channel_health" in result
        assert "decisions" in result
        assert "top_action" in result

    def test_decisions_list(self):
        result = run_brain_cycle()
        assert len(result["decisions"]) == 5

    def test_decision_structure(self):
        result = run_brain_cycle()
        for d in result["decisions"]:
            assert "domain" in d
            assert "action" in d
            assert "rationale" in d
            assert "confidence" in d
            assert "priority" in d

    def test_decisions_sorted_by_priority(self):
        result = run_brain_cycle()
        priorities = [d["priority"] for d in result["decisions"]]
        assert priorities == sorted(priorities)
