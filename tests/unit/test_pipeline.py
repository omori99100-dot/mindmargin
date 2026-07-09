"""Tests for core/pipeline.py — Pipeline class."""

import json
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from mindmargin.core.pipeline import Pipeline, hash_dict


@pytest.fixture
def mock_env(tmp_path):
    """Configure all external mocks for isolated Pipeline testing."""
    mock_settings = MagicMock()
    mock_settings.storage = MagicMock()
    mock_settings.storage.output_root = str(tmp_path)
    mock_settings.production = MagicMock()
    mock_settings.production.enable_structured_logs = True
    mock_settings.production.enable_cache_hash = True

    with patch("mindmargin.core.pipeline.settings", mock_settings), \
         patch("mindmargin.core.state._safe_base", return_value=tmp_path), \
         patch("mindmargin.core.cache._safe_base", return_value=tmp_path), \
         patch("mindmargin.core.pipeline_logger._safe_base", return_value=tmp_path), \
         patch("mindmargin.core.storage._safe_base", return_value=tmp_path), \
         patch("mindmargin.core.metrics._safe_base", return_value=tmp_path), \
         patch("mindmargin.core.pipeline.AGENTS", ["research", "script"]), \
         patch("mindmargin.core.pipeline.ensure_dirs", return_value={}), \
         patch("mindmargin.core.pipeline.project_dir") as mock_pd, \
         patch("mindmargin.core.pipeline.hash_dict", return_value="mock_hash"), \
         patch("mindmargin.core.pipeline.Pipeline._start_thumbnail_thread"), \
         patch("time.sleep"):

        mock_pd.return_value = tmp_path / "project"

        yield {
            "settings": mock_settings,
            "project_dir": mock_pd,
            "tmp_path": tmp_path,
        }

    # After yield: patches are cleaned up


@pytest.fixture
def pipeline(mock_env):
    """Create a basic Pipeline instance with all mocks active."""
    return Pipeline(topic="test topic")


@pytest.fixture
def pipeline_with_agents(mock_env, tmp_path):
    """Set up Pipeline with mocked agent classes."""
    with patch("mindmargin.core.pipeline.ResearchAgent") as mock_ra, \
         patch("mindmargin.core.pipeline.ScriptAgent") as mock_sa, \
         patch("mindmargin.core.pipeline.VoiceAgent"), \
         patch("mindmargin.core.pipeline.EditingAgent"):

        res_inst = MagicMock()
        res_inst.run.return_value = {
            "status": "ok",
            "research": {"content": "research data"},
        }
        mock_ra.return_value = res_inst

        scr_inst = MagicMock()
        scr_inst.run.return_value = {
            "status": "ok",
            "script": {"sections": [{"title": "sec1"}], "content": "script content"},
        }
        mock_sa.return_value = scr_inst

        p = Pipeline(topic="test topic")

        yield {
            "pipeline": p,
            "research_inst": res_inst,
            "script_inst": scr_inst,
            "mock_research_cls": mock_ra,
            "mock_script_cls": mock_sa,
        }


# ── Tests ──

class TestPipelineInit:
    def test_initialization(self, pipeline):
        assert pipeline.topic == "test topic"
        assert pipeline.status == "initialized"
        assert pipeline.state == {}
        assert pipeline.errors == []
        assert pipeline.pipeline_id.startswith("pipe_")
        assert pipeline._pstate is not None
        assert pipeline._plog is not None
        assert pipeline._cache is not None
        assert pipeline._metrics is not None
        assert pipeline.timer is not None

    def test_initialization_with_id(self, mock_env):
        tmp = mock_env["tmp_path"]
        ckpt_dir = tmp / "checkpoints"
        ckpt_dir.mkdir(parents=True, exist_ok=True)
        slug = "test_topic"
        ckpt = ckpt_dir / f"pipe_001_{slug}__pipeline_state.json"
        ckpt.write_text(json.dumps({"state": "SCRIPTING", "metadata": {"prev": True}}))

        p = Pipeline(topic="test topic", pipeline_id="pipe_001")
        assert p.pipeline_id == "pipe_001"
        assert p._pstate is not None


class TestPipelineRun:
    def test_run_completes_successfully(self, pipeline_with_agents):
        p = pipeline_with_agents["pipeline"]
        result = p.run()

        assert result["status"] == "completed"
        assert "research" in result["completed_agents"]
        assert "script" in result["completed_agents"]
        assert result["errors"] == []

    def test_run_with_terminal_state(self, mock_env):
        with patch("mindmargin.core.pipeline.PipelineState") as MockPState:
            mock_ps = MagicMock()
            mock_ps.is_terminal = True
            mock_ps.state = "COMPLETED"
            MockPState.return_value = mock_ps

            p = Pipeline(topic="test topic")
            result = p.run()

            assert result["status"] == "running"  # set before terminal check

    def test_run_agent_failure(self, pipeline_with_agents):
        p = pipeline_with_agents["pipeline"]
        pipeline_with_agents["research_inst"].run.side_effect = ValueError("API error")

        result = p.run()

        assert result["status"] == "failed"
        assert len(result["errors"]) == 1
        assert result["errors"][0]["agent"] == "research"
        assert "API error" in result["errors"][0]["error"]

    def test_run_with_retry_success(self, pipeline_with_agents):
        p = pipeline_with_agents["pipeline"]
        inst = pipeline_with_agents["research_inst"]
        inst.run.side_effect = [
            ValueError("temp error"),
            {"status": "ok", "research": {"content": "retried"}},
        ]

        result = p.run()

        assert result["status"] == "completed"
        assert inst.run.call_count == 2

    def test_run_with_retry_exhausted(self, pipeline_with_agents):
        p = pipeline_with_agents["pipeline"]
        inst = pipeline_with_agents["research_inst"]
        inst.run.side_effect = ValueError("persistent error")

        result = p.run()

        assert result["status"] == "failed"
        assert len(result["errors"]) == 1
        assert "persistent error" in result["errors"][0]["error"]

    def test_checkpoint_skips_completed_stage(self, mock_env):
        tmp = mock_env["tmp_path"]
        with patch("mindmargin.core.pipeline.AGENTS", ["research", "script"]), \
             patch("mindmargin.core.pipeline.ResearchAgent") as mock_ra, \
             patch("mindmargin.core.pipeline.ScriptAgent") as mock_sa:

            scr_inst = MagicMock()
            scr_inst.run.return_value = {
                "status": "ok",
                "script": {"sections": [{"title": "s1"}], "content": "data"},
            }
            mock_sa.return_value = scr_inst

            ckpt_dir = tmp / "checkpoints"
            ckpt_dir.mkdir(parents=True, exist_ok=True)
            slug = "test_topic"
            ckpt_path = ckpt_dir / f"pipe_ck_{slug}_research.json"
            ckpt_path.write_text(
                json.dumps({"status": "ok", "research": {"content": "cached"}})
            )

            p = Pipeline(topic="test topic", pipeline_id="pipe_ck")
            result = p.run()

            assert result["status"] == "completed"
            assert "research" in result["completed_agents"]
            assert p.state["research"]["research"]["content"] == "cached"
            mock_ra.return_value.run.assert_not_called()

    def test_cache_skips_voice(self, mock_env):
        tmp = mock_env["tmp_path"]
        with patch("mindmargin.core.pipeline.AGENTS", ["research", "script", "voice"]), \
             patch("mindmargin.core.pipeline.hash_dict", return_value="same_hash"), \
             patch("mindmargin.core.pipeline.VoiceAgent") as MockVoice, \
             patch("mindmargin.core.pipeline.ResearchAgent") as mock_ra, \
             patch("mindmargin.core.pipeline.ScriptAgent") as mock_sa:

            res_inst = MagicMock()
            res_inst.run.return_value = {
                "status": "ok",
                "research": {"content": "research data"},
            }
            mock_ra.return_value = res_inst

            scr_inst = MagicMock()
            scr_inst.run.return_value = {
                "status": "ok",
                "script": {"sections": [{"title": "sec1"}], "content": "script content"},
            }
            mock_sa.return_value = scr_inst

            # Create checkpoint files so research and script stages are skipped
            ckpt_dir = tmp / "checkpoints"
            ckpt_dir.mkdir(parents=True, exist_ok=True)
            slug = "test_topic"
            (ckpt_dir / f"pipe_cv_{slug}_research.json").write_text(
                json.dumps({"status": "ok", "research": {"content": "cached"}})
            )
            (ckpt_dir / f"pipe_cv_{slug}_script.json").write_text(
                json.dumps({"status": "ok", "script": {"sections": [{"title": "s1"}], "content": "cached"}})
            )

            p = Pipeline(topic="test topic", pipeline_id="pipe_cv")
            # Pre-populate cache so voice_script key exists with matching hash
            if p._cache:
                p._cache.update("voice_script", "same_hash")

            result = p.run()

            assert "voice" in result["completed_agents"]
            MockVoice.return_value.run.assert_not_called()

    def test_background_thumbnail(self, pipeline_with_agents):
        p = pipeline_with_agents["pipeline"]
        with patch.object(p, "_start_thumbnail_thread") as mock_thumb:
            result = p.run()
            assert result["status"] == "completed"
            mock_thumb.assert_called_once()


class TestPipelineInternals:
    def test_summary(self, pipeline):
        pipeline.state = {"research": {"status": "ok"}, "script": {"status": "ok"}}
        pipeline.status = "completed"
        summary = pipeline._summary()

        assert summary["pipeline_id"] == pipeline.pipeline_id
        assert summary["topic"] == "test topic"
        assert summary["status"] == "completed"
        assert "research" in summary["completed_agents"]
        assert "script" in summary["completed_agents"]
        assert summary["errors"] == []
        assert "output_dir" in summary
        assert "timing_s" in summary
        assert "video_path" in summary

    def test_hash_dict(self):
        d1 = {"a": 1, "b": 2}
        d2 = {"b": 2, "a": 1}
        assert hash_dict(d1) == hash_dict(d2)
        d3 = {"a": 1, "b": 3}
        assert hash_dict(d1) != hash_dict(d3)

    def test_checkpoint_path(self, pipeline):
        path = pipeline._checkpoint_path("research")
        assert pipeline.pipeline_id in str(path)
        assert "research" in str(path)
        assert str(path).endswith(".json")
        assert "test_topic" in str(path)

    def test_log_calls(self, pipeline_with_agents):
        p = pipeline_with_agents["pipeline"]
        with patch.object(p._plog, "log") as mock_log:
            p.run()

            expected_calls = [
                call("pipeline_started", stage="pipeline", status="info", duration=None, metadata=None),
                call("stage_started", stage="research", status="info", duration=None, metadata=None),
                call("stage_started", stage="script", status="info", duration=None, metadata=None),
            ]
            for expected in expected_calls:
                assert expected in mock_log.call_args_list, f"Missing: {expected}"
