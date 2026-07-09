"""Tests for core/pipeline_logger.py — Structured Logging."""

import json
from unittest.mock import patch

import pytest

from mindmargin.core.pipeline_logger import PipelineLogger


@pytest.fixture
def mock_base(tmp_path):
    with patch("mindmargin.core.pipeline_logger._safe_base", return_value=tmp_path):
        yield tmp_path


def test_log_entry(mock_base):
    pl = PipelineLogger("pipe_log_001")
    pl.log("test_event", stage="testing", status="info",
           duration=1.5, metadata={"key": "value"})

    entries = pl.read_entries(10)
    assert len(entries) == 1
    e = entries[0]
    assert e["event"] == "test_event"
    assert e["stage"] == "testing"
    assert e["pipeline_id"] == "pipe_log_001"
    assert e["duration"] == 1.5
    assert e["key"] == "value"


def test_multiple_entries(mock_base):
    pl = PipelineLogger("pipe_multi")
    pl.log("event1", stage="a")
    pl.log("event2", stage="b")
    pl.log("event3", stage="c")

    entries = pl.read_entries(10)
    assert len(entries) == 3


def test_read_limit(mock_base):
    pl = PipelineLogger("pipe_limit")
    for i in range(20):
        pl.log(f"event_{i}", stage="test")

    entries = pl.read_entries(5)
    assert len(entries) == 5


def test_log_clip_rendered(mock_base):
    pl = PipelineLogger("pipe_clip")
    pl.clip_rendered("02_rise_content", 18.4, encoder="h264_qsv", retry=1)

    entries = pl.read_entries(1)
    e = entries[0]
    assert e["event"] == "clip_rendered"
    assert e["clip"] == "02_rise_content"
    assert e["encoder"] == "h264_qsv"
    assert e["retry"] == 1


def test_stage_methods(mock_base):
    pl = PipelineLogger("pipe_stage")
    pl.stage_started("editing")
    pl.stage_completed("editing", 42.5)
    pl.stage_failed("publishing", "auth error")

    entries = pl.read_entries(3)
    assert entries[2]["event"] == "stage_started"
    assert entries[1]["event"] == "stage_completed"
    assert entries[0]["event"] == "stage_failed"


def test_cache_methods(mock_base):
    pl = PipelineLogger("pipe_cache")
    pl.cache_hit("voice_script", "script.json")
    pl.cache_miss("render_hash", "video.mp4")

    entries = pl.read_entries(2)
    assert entries[1]["event"] == "cache_hit"
    assert entries[0]["event"] == "cache_miss"


def test_publish_attempt(mock_base):
    pl = PipelineLogger("pipe_pub")
    pl.publish_attempt("success", video_id="abc123")
    pl.publish_attempt("failed", error="quota exceeded")

    entries = pl.read_entries(2)
    assert entries[1]["status"] == "success"
    assert entries[1]["video_id"] == "abc123"
    assert entries[0]["status"] == "failed"
    assert entries[0]["error"] == "quota exceeded"


def test_no_entries_for_empty_log(mock_base):
    pl = PipelineLogger("pipe_empty")
    assert pl.read_entries(10) == []


def test_jsonl_format(mock_base):
    pl = PipelineLogger("pipe_jsonl")
    pl.log("test", stage="s")
    raw = (pl._base_dir / f"{pl.pipeline_id}.jsonl").read_text()
    assert raw.endswith("\n")
    json.loads(raw.strip())  # valid JSON


class TestPipelineLoggerEdgeCases:
    def test_read_entries_skips_corrupt_line(self, mock_base):
        pl = PipelineLogger("pipe_corrupt_line")
        pl.log("good", stage="test")
        log_file = pl._base_dir / f"{pl.pipeline_id}.jsonl"
        with log_file.open("a") as f:
            f.write("not valid json\n")
        entries = pl.read_entries(10)
        assert len(entries) == 1
        assert entries[0]["event"] == "good"
