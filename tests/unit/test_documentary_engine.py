"""Unit tests for Phase 21 — Documentary Production Engine.

Tests cover:
- Documentary section structure
- Quality gates
- Scene planning
- Scene plan validation
- Hook optimization
- Title generation
- Thumbnail concepts
- Production reports
- Research expansion
"""
import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from mindmargin.agents.script import (
    ScriptAgent, DOCUMENTARY_SECTIONS, MIN_WORD_COUNT,
    MIN_SECTION_WORD_COUNT, QUALITY_PASS_THRESHOLD,
    _estimate_duration_minutes, validate_scene_plan,
)
from mindmargin.agents.research import (
    ResearchAgent, score_topic, build_research,
    EXPANDED_RESEARCH_CATEGORIES,
)
from mindmargin.prompts.base import (
    DOCUMENTARY_SECTION_PROMPTS, SCRIPT_SYSTEM,
    HOOK_SYSTEM, TITLE_SYSTEM, QUALITY_SYSTEM,
    SCENE_PLANNING_SYSTEM, THUMBNAIL_SYSTEM,
    PRODUCTION_REPORT_SYSTEM, GENERATION_MODES,
)


class TestDocumentarySections:
    """Test the documentary section structure."""

    def test_has_10_sections(self):
        assert len(DOCUMENTARY_SECTIONS) == 10

    def test_section_names(self):
        names = [s[0] for s in DOCUMENTARY_SECTIONS]
        expected = [
            "hook", "context", "historical_background", "growth_story",
            "critical_decisions", "main_mistakes", "collapse",
            "consequences", "lessons_learned", "closing",
        ]
        assert names == expected

    def test_section_prompts_match_sections(self):
        """Every section must have a corresponding prompt."""
        for name, _, _ in DOCUMENTARY_SECTIONS:
            assert name in DOCUMENTARY_SECTION_PROMPTS, f"Missing prompt for section: {name}"

    def test_section_durations_sum_to_reasonable_length(self):
        total = sum(s[2] for s in DOCUMENTARY_SECTIONS)
        # Should be 15-50 minutes total (documentary format)
        assert 900 <= total <= 3000

    def test_hook_section_is_shortest(self):
        hook_dur = DOCUMENTARY_SECTIONS[0][2]
        for name, _, dur in DOCUMENTARY_SECTIONS[1:]:
            assert dur >= hook_dur

    def test_closing_section_is_shortest(self):
        closing_dur = DOCUMENTARY_SECTIONS[-1][2]
        for name, _, dur in DOCUMENTARY_SECTIONS[:-1]:
            assert dur >= closing_dur


class TestQualityGates:
    """Test quality gate logic."""

    def test_min_word_count_constant(self):
        assert MIN_WORD_COUNT == 1500

    def test_min_section_word_count(self):
        assert MIN_SECTION_WORD_COUNT == 100

    def test_quality_pass_threshold(self):
        assert QUALITY_PASS_THRESHOLD == 60

    def test_quality_gate_passes_with_sufficient_words(self):
        agent = ScriptAgent(use_templates=True)
        sections = [
            {"name": f"section_{i}", "title": f"Section {i}",
             "text": "word " * 200, "word_count": 200,
             "duration_target_s": 120, "mode": "documentary"}
            for i in range(10)
        ]
        result = agent._quality_gate(sections, "test topic")
        assert len(result) == 10

    def test_duration_estimate(self):
        # 250 words at 2.5 words/sec = 100 seconds = ~1.7 minutes
        assert _estimate_duration_minutes(250) == 1.7

    def test_duration_estimate_long(self):
        # 2500 words = ~16.7 minutes
        assert _estimate_duration_minutes(2500) == 16.7


class TestResearchExpansion:
    """Test expanded research collection."""

    def test_score_topic_with_keywords(self):
        result = score_topic("The Collapse of Nokia in the Smartphone War")
        assert result["trend_score"] > 40
        assert "collapse" in result["matched_keywords"]

    def test_score_topic_no_keywords(self):
        result = score_topic("A story about umbrellas")
        assert result["trend_score"] == 40

    def test_build_research_has_all_categories(self):
        research = build_research("Test Topic")
        categories = [c["category"] for c in research["categories"]]
        for cat in EXPANDED_RESEARCH_CATEGORIES:
            assert cat in categories

    def test_build_research_version(self):
        research = build_research("Test Topic")
        assert research["version"] == "2.0"

    def test_research_has_17_categories(self):
        research = build_research("Test Topic")
        assert len(research["categories"]) == 17

    @patch("mindmargin.agents.research.ResearchAgent._get_llm")
    def test_research_agent_completes(self, mock_get_llm):
        mock_get_llm.return_value = None
        agent = ResearchAgent()
        with patch("mindmargin.agents.research.ensure_dirs") as mock_dirs, \
             patch("mindmargin.agents.research.write_text"):
            from pathlib import Path
            mock_dirs.return_value = {"research": Path("/tmp/test")}
            result = agent.run("Test Topic", "test-001")
            assert result["status"] == "completed"
            assert "research" in result


class TestScriptAgentDocumentary:
    """Test ScriptAgent documentary mode."""

    def test_documentary_sections_constant(self):
        from mindmargin.agents.script import DOCUMENTARY_SECTIONS
        assert len(DOCUMENTARY_SECTIONS) == 10

    def test_template_sections(self):
        agent = ScriptAgent(use_templates=True)
        research = {"categories": []}
        sections = agent._template_sections("Test Topic", research)
        assert len(sections) == 10
        for sec in sections:
            assert "section_id" in sec
            assert "name" in sec
            assert "text" in sec
            assert "word_count" in sec

    def test_template_seo(self):
        agent = ScriptAgent(use_templates=True)
        seo = agent._template_seo("Test Topic")
        assert "description" in seo
        assert "tags" in seo
        assert "category" in seo

    def test_validate_scene_plan_valid(self):
        plan = [{
            "scene_description": "Test scene",
            "broll_suggestion": "Test footage",
            "footage_keywords": ["test"],
            "camera_movement": "static",
            "on_screen_text": "Hello",
            "visual_elements": [],
            "duration_s": 30,
            "emotion": "neutral",
        }]
        clean, reason = validate_scene_plan(plan)
        assert reason == ""
        assert len(clean) == 1
        assert clean[0]["emotion"] == "neutral"

    def test_validate_scene_plan_multiple_valid(self):
        plan = [
            {"scene_description": "A", "broll_suggestion": "B", "footage_keywords": ["k"],
             "camera_movement": "pan_left", "on_screen_text": "", "visual_elements": [],
             "duration_s": 10, "emotion": "neutral"},
            {"scene_description": "C", "broll_suggestion": "D", "footage_keywords": ["k2"],
             "camera_movement": "zoom_in", "on_screen_text": "text", "visual_elements": ["chart"],
             "duration_s": 20, "emotion": "sad"},
        ]
        clean, reason = validate_scene_plan(plan)
        assert reason == ""
        assert len(clean) == 2

    def test_validate_scene_plan_none(self):
        clean, reason = validate_scene_plan(None)
        assert reason != ""
        assert "None" in reason
        assert len(clean) == 1
        assert clean[0]["camera_movement"] == "static"

    def test_validate_scene_plan_not_list(self):
        clean, reason = validate_scene_plan("not a list")
        assert reason != ""
        assert "str" in reason
        assert len(clean) == 1
        assert clean[0]["camera_movement"] == "static"

    def test_validate_scene_plan_empty_list(self):
        clean, reason = validate_scene_plan([])
        assert reason == ""
        assert clean == []

    def test_validate_scene_plan_element_is_string(self):
        plan = [
            "this is a string, not a dict",
            {"scene_description": "A", "broll_suggestion": "B", "footage_keywords": ["k"],
             "camera_movement": "static", "on_screen_text": "", "visual_elements": [],
             "duration_s": 10, "emotion": "neutral"},
        ]
        clean, reason = validate_scene_plan(plan)
        assert reason != ""
        assert "0" in reason
        assert len(clean) == 1
        assert clean[0]["scene_description"] == "A"

    def test_validate_scene_plan_all_strings(self):
        plan = ["string1", "string2", "string3"]
        clean, reason = validate_scene_plan(plan)
        assert reason != ""
        assert "0,1,2" in reason
        assert len(clean) == 1
        assert clean[0]["camera_movement"] == "static"

    def test_validate_scene_plan_missing_keys(self):
        plan = [{"scene_description": "incomplete", "broll_suggestion": "missing many keys"}]
        clean, reason = validate_scene_plan(plan)
        assert reason != ""
        assert "0" in reason
        assert len(clean) == 1
        assert clean[0]["camera_movement"] == "static"

    def test_validate_scene_plan_partial_missing_keys(self):
        plan = [
            {"scene_description": "A", "broll_suggestion": "B", "footage_keywords": ["k"],
             "camera_movement": "static", "on_screen_text": "", "visual_elements": [],
             "duration_s": 10, "emotion": "neutral"},
            {"broll_suggestion": "missing everything else"},
        ]
        clean, reason = validate_scene_plan(plan)
        assert reason != ""
        assert "1" in reason
        assert len(clean) == 1

    def test_validate_scene_plan_all_keys_null_values(self):
        plan = [{
            "scene_description": None, "broll_suggestion": None,
            "footage_keywords": None, "camera_movement": None,
            "on_screen_text": None, "visual_elements": None,
            "duration_s": None, "emotion": None,
        }]
        clean, reason = validate_scene_plan(plan)
        assert reason == ""
        assert len(clean) == 1

    def test_validate_scene_plan_mixed_types_in_list(self):
        plan = [
            {"scene_description": "A", "broll_suggestion": "B", "footage_keywords": ["k"],
             "camera_movement": "static", "on_screen_text": "", "visual_elements": [],
             "duration_s": 10, "emotion": "neutral"},
            42,
            {"scene_description": "C", "broll_suggestion": "D", "footage_keywords": ["k2"],
             "camera_movement": "zoom", "on_screen_text": "txt", "visual_elements": [],
             "duration_s": 20, "emotion": "happy"},
            "bad string",
        ]
        clean, reason = validate_scene_plan(plan)
        assert reason != ""
        assert "1,3" in reason
        assert len(clean) == 2

    def test_validate_scene_plan_strips_invalid_keeps_valid(self):
        plan = [
            {"scene_description": "A", "broll_suggestion": "B", "footage_keywords": ["k"],
             "camera_movement": "static", "on_screen_text": "", "visual_elements": [],
             "duration_s": 10, "emotion": "neutral"},
            ["not", "a", "dict"],
        ]
        clean, reason = validate_scene_plan(plan)
        assert reason != ""
        assert len(clean) == 1
        assert clean[0]["scene_description"] == "A"

    def test_validate_scene_plan_extra_keys_allowed(self):
        plan = [{
            "scene_description": "A", "broll_suggestion": "B", "footage_keywords": ["k"],
            "camera_movement": "static", "on_screen_text": "", "visual_elements": [],
            "duration_s": 10, "emotion": "neutral",
            "extra_key": "this is fine",
        }]
        clean, reason = validate_scene_plan(plan)
        assert reason == ""
        assert len(clean) == 1

    def test_validate_scene_plan_returns_fallback_on_empty(self):
        from mindmargin.agents.script import _fallback_scene_plan
        fb = _fallback_scene_plan()
        assert isinstance(fb, list)
        assert len(fb) == 1
        assert isinstance(fb[0], dict)
        assert "scene_description" in fb[0]

    def test_default_scene_plan(self):
        agent = ScriptAgent(use_templates=True)
        section = {"name": "hook", "title": "The Hook", "duration_target_s": 120}
        plan = agent._default_scene_plan(section)
        assert len(plan) == 1
        assert "scene_description" in plan[0]
        assert "broll_suggestion" in plan[0]

    def test_default_thumbnail_concepts(self):
        agent = ScriptAgent(use_templates=True)
        concepts = agent._default_thumbnail_concepts("Nokia Collapse")
        assert len(concepts) == 1
        assert "emotion_score" in concepts[0]
        assert "curiosity_score" in concepts[0]

    def test_default_scores(self):
        agent = ScriptAgent(use_templates=True)
        scores = agent._default_scores()
        assert "narrative_arc" in scores
        assert "overall_score" in scores
        assert all(v == 50 for k, v in scores.items() if isinstance(v, int))

    def test_generation_modes_exist(self):
        assert "documentary" in GENERATION_MODES
        assert "dark" in GENERATION_MODES
        assert "educational" in GENERATION_MODES
        assert "motivational" in GENERATION_MODES
        assert "viral_shorts" in GENERATION_MODES

    def test_documentary_mode_has_system_prompt(self):
        assert "system" in GENERATION_MODES["documentary"]
        assert len(GENERATION_MODES["documentary"]["system"]) > 50


class TestPromptTemplates:
    """Test that all prompt templates are well-formed."""

    def test_script_system_not_empty(self):
        assert len(SCRIPT_SYSTEM) > 100

    def test_all_section_prompts_have_format_placeholders(self):
        for name, prompt in DOCUMENTARY_SECTION_PROMPTS.items():
            assert "{topic}" in prompt, f"Section {name} missing {{topic}} placeholder"

    def test_hook_system_not_empty(self):
        assert len(HOOK_SYSTEM) > 50

    def test_title_system_not_empty(self):
        assert len(TITLE_SYSTEM) > 50

    def test_quality_system_not_empty(self):
        assert len(QUALITY_SYSTEM) > 50

    def test_scene_planning_system_not_empty(self):
        assert len(SCENE_PLANNING_SYSTEM) > 50

    def test_thumbnail_system_not_empty(self):
        assert len(THUMBNAIL_SYSTEM) > 50

    def test_production_report_system_not_empty(self):
        assert len(PRODUCTION_REPORT_SYSTEM) > 50


class TestBackwardCompatibility:
    """Test that old code still works with new prompts."""

    def test_section_prompts_alias(self):
        from mindmargin.prompts.base import SECTION_PROMPTS
        assert SECTION_PROMPTS is DOCUMENTARY_SECTION_PROMPTS

    def test_legacy_section_names_defined(self):
        from mindmargin.agents.script import LEGACY_SECTION_NAMES
        assert len(LEGACY_SECTION_NAMES) == 9

    def test_title_templates_still_work(self):
        from mindmargin.agents.script import TITLE_TEMPLATES
        for t in TITLE_TEMPLATES:
            assert "{topic}" in t

    def test_hook_templates_still_work(self):
        from mindmargin.agents.script import HOOK_TEMPLATES
        for a, h, s in HOOK_TEMPLATES:
            assert "{topic}" in h
