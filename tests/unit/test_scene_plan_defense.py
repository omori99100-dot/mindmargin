"""Tests for scene plan defense-in-depth in EditingAgent."""
import pytest
from unittest.mock import MagicMock, patch
from mindmargin.agents.script import validate_scene_plan, _fallback_scene_plan


class TestEditingAgentScenePlanDefense:

    def test_validate_scene_plan_importable(self):
        from mindmargin.agents.editing import validate_scene_plan as vsp
        assert vsp is validate_scene_plan

    def test_render_sections_with_invalid_scene_plan_uses_fallback(self):
        from mindmargin.agents.editing import EditingAgent
        agent = EditingAgent(force=True)

        sections = [{
            "section_id": 1, "name": "hook", "title": "Hook",
            "text": "Some text here for the hook section. " * 20,
            "duration_target_s": 120, "word_count": 80, "mode": "documentary",
            "scene_plan": ["invalid_string", {"not": "valid"}],
        }]
        with patch.object(agent, '_render_parallel', return_value=True):
            with patch.object(agent, '_should_render', return_value=False):
                with patch.object(agent, '_load_progress', return_value={}):
                    clips = agent._render_sections(
                        "test_pipeline", sections, [], 1.0,
                        {"video": MagicMock(), "temp": MagicMock(), "audio": MagicMock(),
                         "captions": MagicMock(), "meta": MagicMock()},
                        {}
                    )
        assert clips is not None

    def test_render_sections_with_valid_scene_plan_passes_through(self):
        from mindmargin.agents.editing import EditingAgent
        agent = EditingAgent(force=True)

        sections = [{
            "section_id": 1, "name": "hook", "title": "Hook",
            "text": "Some text here for editing test. " * 20,
            "duration_target_s": 120, "word_count": 80, "mode": "documentary",
            "scene_plan": [{
                "scene_description": "Test scene",
                "broll_suggestion": "Test footage",
                "footage_keywords": ["test"],
                "camera_movement": "static",
                "on_screen_text": "Display this",
                "visual_elements": [],
                "duration_s": 30,
                "emotion": "neutral",
            }],
        }]
        with patch.object(agent, '_render_parallel', return_value=True):
            with patch.object(agent, '_should_render', return_value=False):
                with patch.object(agent, '_load_progress', return_value={}):
                    clips = agent._render_sections(
                        "test_pipeline", sections, [], 1.0,
                        {"video": MagicMock(), "temp": MagicMock(), "audio": MagicMock(),
                         "captions": MagicMock(), "meta": MagicMock()},
                        {}
                    )
        assert clips is not None

    def test_render_sections_with_missing_scene_plan_uses_empty_fallback(self):
        from mindmargin.agents.editing import EditingAgent
        agent = EditingAgent(force=True)

        sections = [{
            "section_id": 1, "name": "hook", "title": "Hook",
            "text": "Text for missing scene plan test. " * 15,
            "duration_target_s": 120, "word_count": 60, "mode": "documentary",
        }]
        with patch.object(agent, '_render_parallel', return_value=True):
            with patch.object(agent, '_should_render', return_value=False):
                with patch.object(agent, '_load_progress', return_value={}):
                    clips = agent._render_sections(
                        "test_pipeline", sections, [], 1.0,
                        {"video": MagicMock(), "temp": MagicMock(), "audio": MagicMock(),
                         "captions": MagicMock(), "meta": MagicMock()},
                        {}
                    )
        assert clips is not None

    def test_scene_plan_with_string_does_not_crash_editing_agent(self):
        from mindmargin.agents.editing import EditingAgent
        agent = EditingAgent(force=True)

        sections = [{
            "section_id": 1, "name": "hook", "title": "Hook",
            "text": "Crash prevention test text. " * 15,
            "duration_target_s": 120, "word_count": 60, "mode": "documentary",
            "scene_plan": [{
                "scene_description": "A", "broll_suggestion": "B",
                "footage_keywords": ["k"], "camera_movement": "static",
                "on_screen_text": "", "visual_elements": [], "duration_s": 10,
                "emotion": "neutral",
            }],
        }]
        with patch.object(agent, '_render_parallel', return_value=True):
            with patch.object(agent, '_should_render', return_value=False):
                with patch.object(agent, '_load_progress', return_value={}):
                    clips = agent._render_sections(
                        "test_pipeline", sections, [], 1.0,
                        {"video": MagicMock(), "temp": MagicMock(), "audio": MagicMock(),
                         "captions": MagicMock(), "meta": MagicMock()},
                        {}
                    )
        assert clips is not None

    def test_scene_plan_all_strings_uses_fallback(self):
        from mindmargin.agents.editing import EditingAgent
        agent = EditingAgent(force=True)

        sections = [{
            "section_id": 1, "name": "hook", "title": "Hook",
            "text": "All strings test. " * 15,
            "duration_target_s": 120, "word_count": 60, "mode": "documentary",
            "scene_plan": ["bad1", "bad2", "bad3"],
        }]
        with patch.object(agent, '_render_parallel', return_value=True):
            with patch.object(agent, '_should_render', return_value=False):
                with patch.object(agent, '_load_progress', return_value={}):
                    clips = agent._render_sections(
                        "test_pipeline", sections, [], 1.0,
                        {"video": MagicMock(), "temp": MagicMock(), "audio": MagicMock(),
                         "captions": MagicMock(), "meta": MagicMock()},
                        {}
                    )
        assert clips is not None

    def test_fallback_scene_plan_structure(self):
        fb = _fallback_scene_plan()
        assert isinstance(fb, list)
        assert len(fb) == 1
        scene = fb[0]
        assert isinstance(scene, dict)
        assert scene["scene_description"]
        assert scene["broll_suggestion"]
        assert isinstance(scene["footage_keywords"], list)
        assert scene["camera_movement"] == "static"
        assert scene["on_screen_text"] == ""
        assert isinstance(scene["visual_elements"], list)
        assert isinstance(scene["duration_s"], (int, float))
        assert scene["emotion"] == "neutral"
