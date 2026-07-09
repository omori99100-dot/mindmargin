"""Tests for core/state.py — Pipeline State Machine."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from mindmargin.core.state import PipelineState, CREATED, RESEARCHING, COMPLETED, FAILED, CANCELLED


@pytest.fixture
def mock_base(tmp_path):
    with patch("mindmargin.core.state._safe_base", return_value=tmp_path):
        yield tmp_path


def test_initial_state(mock_base):
    ps = PipelineState("pipe_001", "test topic")
    assert ps.state == CREATED
    assert ps.pipeline_id == "pipe_001"
    assert not ps.is_terminal


def test_state_transitions(mock_base):
    ps = PipelineState("pipe_002")
    ps.mark_started()
    assert ps.state == CREATED

    ps.state = RESEARCHING
    assert ps.state == RESEARCHING

    ps.state = COMPLETED
    assert ps.is_terminal
    assert ps.state == COMPLETED


def test_state_persistence(mock_base):
    ps1 = PipelineState("pipe_003")
    ps1.mark_started()
    ps1.state = RESEARCHING
    ps1.current_clip = "02_rise_content"

    ps2 = PipelineState("pipe_003")
    assert ps2.state == RESEARCHING
    assert ps2.current_clip == "02_rise_content"


def test_list_unfinished(mock_base):
    ps1 = PipelineState("pipe_finished")
    ps1.state = COMPLETED

    ps2 = PipelineState("pipe_running")
    ps2.state = RESEARCHING

    unfinished = PipelineState.list_unfinished()
    ids = [ps.pipeline_id for ps in unfinished]
    assert "pipe_running" in ids
    assert "pipe_finished" not in ids


def test_fail_state(mock_base):
    ps = PipelineState("pipe_fail")
    ps.mark_started()
    ps.mark_failed("something broke")
    assert ps.state == FAILED
    assert ps.is_terminal
    assert ps.get_metadata("error") == "something broke"


def test_cancel_state(mock_base):
    ps = PipelineState("pipe_cancel")
    ps.mark_started()
    ps.mark_cancelled("user request")
    assert ps.state == CANCELLED
    assert ps.is_terminal


def test_invalid_state_raises(mock_base):
    ps = PipelineState("pipe_invalid")
    with pytest.raises(ValueError):
        ps.state = "INVALID_STATE"


def test_metadata(mock_base):
    ps = PipelineState("pipe_meta")
    ps.set_metadata("key1", "value1")
    ps.set_metadata("key2", 42)
    assert ps.get_metadata("key1") == "value1"
    assert ps.get_metadata("key2") == 42
    assert ps.get_metadata("nonexistent", "default") == "default"


def test_to_dict(mock_base):
    ps = PipelineState("pipe_dict", "test")
    ps.mark_started()
    d = ps.to_dict()
    assert d["pipeline_id"] == "pipe_dict"
    assert d["topic"] == "test"
    assert d["state"] == CREATED


def test_corrupt_state_file(mock_base):
    state_dir = mock_base / "pipeline_state"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "pipe_corrupt.json").write_text("not valid json")

    ps = PipelineState("pipe_corrupt")
    assert ps.state == CREATED  # falls back to default


def test_all_pipelines(mock_base):
    PipelineState("pipe_a").mark_started()
    PipelineState("pipe_b").mark_started()
    ps_c = PipelineState("pipe_c")
    ps_c.state = COMPLETED

    all_p = PipelineState.all_pipelines()
    assert len(all_p) == 3


class TestStateEdgeCases:
    def test_started_at_property(self, mock_base):
        ps = PipelineState("pipe_sa")
        assert ps.started_at == ""
        ps.mark_started()
        assert ps.started_at is not None

    def test_updated_at_property(self, mock_base):
        ps = PipelineState("pipe_ua")
        assert ps.updated_at is not None

    def test_is_cancelled(self, mock_base):
        ps = PipelineState("pipe_ic")
        assert not ps.is_cancelled
        ps.mark_cancelled("cancel")
        assert ps.is_cancelled

    def test_list_unfinished_no_dir(self):
        with patch("mindmargin.core.state._safe_base", return_value=Path(tempfile.mkdtemp() + "/nonexistent")):
            result = PipelineState.list_unfinished()
            assert result == []

    def test_all_pipelines_no_dir(self):
        with patch("mindmargin.core.state._safe_base", return_value=Path(tempfile.mkdtemp() + "/nonexistent2")):
            result = PipelineState.all_pipelines()
            assert result == []

    def test_all_pipelines_skips_corrupt(self, mock_base):
        state_dir = mock_base / "pipeline_state"
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "good.json").write_text('{"pipeline_id": "good", "state": "COMPLETED"}')
        (state_dir / "bad.json").write_text("not json")
        results = PipelineState.all_pipelines()
        assert len(results) == 1
        assert results[0]["pipeline_id"] == "good"
