"""Unit tests for prompts.optimizer -- ruleset engine, scoring, prompt injection."""

import pytest
from mindmargin.prompts.optimizer import (
    ScoredPattern, OptimizationRuleset, OptimizationEngine,
    build_optimized_hook_prompt, build_optimized_title_prompt,
    build_optimized_section_prompt, build_optimized_seo_prompt,
    build_optimization_context,
)


class TestScoredPattern:
    def test_passes_threshold_high(self):
        sp = ScoredPattern("test", "hook_archetype", "value",
                           impact=8.0, confidence=0.8, frequency=5,
                           engagement_weight=0.9, final_score=9.0)
        assert sp.passes_threshold is True

    def test_fails_threshold_low(self):
        sp = ScoredPattern("test", "hook_archetype", "value",
                           impact=3.0, confidence=0.3, frequency=1,
                           engagement_weight=0.5, final_score=2.0)
        assert sp.passes_threshold is False

    def test_boundary_threshold(self):
        sp = ScoredPattern("test", "hook_archetype", "value",
                           impact=5.0, confidence=0.5, frequency=3,
                           engagement_weight=0.7, final_score=7.0)
        assert sp.passes_threshold is True

    def test_source_default(self):
        sp = ScoredPattern("test", "hook_archetype", "value",
                           impact=5.0, confidence=0.5, frequency=1,
                           engagement_weight=0.5, final_score=5.0)
        assert sp.source == "default"


class TestOptimizationRuleset:
    def test_default_values(self):
        rs = OptimizationRuleset()
        assert rs.hook_rules == []
        assert rs.title_rules == []
        assert rs.retention_drop_pct == 70.0
        assert rs.pacing_wpm == 150.0
        assert rs.ruleset_source == "default"

    def test_add_rules(self):
        rs = OptimizationRuleset()
        rs.hook_rules.append("Use curiosity_gap")
        assert len(rs.hook_rules) == 1

    def test_filtered_patterns(self):
        rs = OptimizationRuleset(filtered_patterns=[
            {"key": "bad", "score": 3.0, "reason": "below threshold"}
        ])
        assert len(rs.filtered_patterns) == 1


class TestOptimizationEngine:
    def test_build_returns_ruleset(self):
        engine = OptimizationEngine()
        ruleset = engine.build()
        assert isinstance(ruleset, OptimizationRuleset)
        # Should always have some rules (cold-start defaults)
        assert len(ruleset.hook_rules) >= 1
        assert len(ruleset.title_rules) >= 1
        assert len(ruleset.retention_rules) >= 1
        assert len(ruleset.pacing_rules) >= 1

    def test_build_caches(self):
        engine = OptimizationEngine()
        rs1 = engine.build()
        rs2 = engine.build()
        assert rs1 is rs2  # same cached object

    def test_force_refresh(self):
        engine = OptimizationEngine()
        rs1 = engine.build()
        rs2 = engine.build(force_refresh=True)
        # rs2 may be same if no data changed, should not error

    def test_ruleset_has_source(self):
        engine = OptimizationEngine()
        rs = engine.build()
        assert rs.ruleset_source in ("data", "default")


class TestPromptBuilders:
    @pytest.fixture
    def ruleset(self):
        return OptimizationRuleset(
            hook_rules=["Use curiosity_gap"],
            title_rules=["Keep under 50 chars"],
            retention_rules=["First 30s critical"],
            pacing_rules=["Aim for 150 wpm"],
            avoid_rules=["No passive openings"],
            hook_archetype_ranking=[
                {"archetype": "curiosity_gap", "avg_score": 88.0,
                 "count": 5, "final_score": 88.0}
            ],
            best_hook_examples=[
                {"archetype": "curiosity_gap",
                 "hook_text": "What if everything you know is wrong?",
                 "ctr_score": 88}
            ],
            best_title_examples=[
                {"title": "The Fall of Enron", "ctr": 15.0, "used_count": 3}
            ],
            pacing_wpm=150.0,
            retention_drop_pct=70.0,
        )

    def test_build_hook_prompt(self, ruleset):
        prompt = build_optimized_hook_prompt("Enron", ruleset)
        assert "Enron" in prompt
        assert "curiosity_gap" in prompt
        assert "OPTIMIZATION RULESET" in prompt

    def test_build_title_prompt(self, ruleset):
        prompt = build_optimized_title_prompt("FTX", ruleset)
        assert "FTX" in prompt
        assert "title optimization rules" in prompt.lower()

    def test_build_section_prompt(self, ruleset):
        prompt = build_optimized_section_prompt(
            "hook", "Enron", "The Rise and Fall", 60, ruleset
        )
        assert "Enron" in prompt
        assert "HOOK" in prompt or "hook" in prompt

    def test_build_seo_prompt(self, ruleset):
        prompt = build_optimized_seo_prompt("Enron", "The Fall of Enron", ruleset)
        assert "Enron" in prompt
        assert "description" in prompt.lower()

    def test_all_section_types_exist(self, ruleset):
        sections = ["hook", "rise", "first_crack", "overconfidence_loop",
                     "escalation", "collapse", "twist", "lesson", "close"]
        for sec in sections:
            prompt = build_optimized_section_prompt(
                sec, "Enron", sec.title(), 60, ruleset
            )
            assert len(prompt) > 50


class TestBuildOptimizationContext:
    def test_returns_tuple(self):
        ctx = build_optimization_context("Enron")
        assert len(ctx) == 2
        ruleset, prompts = ctx
        assert isinstance(ruleset, OptimizationRuleset)
        assert isinstance(prompts, dict)
        assert "hook" in prompts
        assert "title" in prompts
        assert "seo" in prompts
