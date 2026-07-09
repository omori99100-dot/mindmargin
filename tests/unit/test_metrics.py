"""Tests for core/metrics.py — Health Report and Metrics."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from mindmargin.core.metrics import PipelineMetrics


@pytest.fixture
def mock_base(tmp_path):
    with patch("mindmargin.core.metrics._safe_base", return_value=tmp_path):
        yield tmp_path


def test_metrics_initialization():
    pm = PipelineMetrics("pipe_001", "test topic")
    assert pm.pipeline_id == "pipe_001"
    assert pm.topic == "test topic"
    assert pm.data["stages"] == {}


def test_record_stage():
    pm = PipelineMetrics("pipe_002")
    pm.record_stage("research", 12.5)
    pm.record_stage("script", 45.2, {"note": "3 retries"})
    assert pm.data["stages"]["research"]["duration_s"] == 12.5
    assert pm.data["stages"]["script"]["duration_s"] == 45.2
    assert pm.data["stages"]["script"]["note"] == "3 retries"


def test_record_cache():
    pm = PipelineMetrics("pipe_003")
    pm.record_cache(10, 2)
    assert pm.data["cache"]["hits"] == 10
    assert pm.data["cache"]["misses"] == 2
    assert pm.data["cache"]["ratio"] == pytest.approx(0.833, rel=0.01)


def test_record_publish():
    pm = PipelineMetrics("pipe_004")
    pm.record_publish("completed", "abc123")
    assert pm.data["publish_status"] == "completed"
    assert pm.data["youtube_video_id"] == "abc123"


def test_record_final_status():
    pm = PipelineMetrics("pipe_005")
    pm.record_final_status("completed")
    assert pm.data["final_status"] == "completed"


def test_save_generates_files(tmp_path):
    pm = PipelineMetrics("pipe_save", "test")
    pm.record_stage("research", 1.0)
    pm.record_stage("editing", 30.5)
    pm.record_cache(5, 1)
    pm.record_encoder("h264_qsv")
    pm.record_publish("completed", "vid123")
    pm.record_final_status("completed")

    pm.save(output_dir=tmp_path)

    # Check metrics.json
    metrics_path = tmp_path / "metrics.json"
    assert metrics_path.exists()
    data = json.loads(metrics_path.read_text(encoding="utf-8"))
    assert data["pipeline_id"] == "pipe_save"
    assert data["publish_status"] == "completed"
    assert data["youtube_video_id"] == "vid123"

    # Check health report
    report_path = tmp_path / "pipeline_health_report.md"
    assert report_path.exists()
    content = report_path.read_text(encoding="utf-8")
    assert "# Pipeline Health Report" in content
    assert "pipe_save" in content
    assert "Stage Timing" in content
    assert "Cache Efficiency" in content
    assert "Publishing" in content


def test_markdown_report_structure(tmp_path):
    pm = PipelineMetrics("pipe_md", "topic")
    pm.record_stage("research", 2.0)
    pm.record_cache(0, 0)
    pm.record_final_status("failed")
    pm.save(output_dir=tmp_path)

    content = (tmp_path / "pipeline_health_report.md").read_text()
    assert "Cache Efficiency" in content
    assert "Hit Ratio" in content
    assert "0.0%" in content


def test_no_publish_section_when_empty(tmp_path):
    pm = PipelineMetrics("pipe_no_pub")
    pm.record_final_status("completed")
    pm.save(output_dir=tmp_path)

    content = (tmp_path / "pipeline_health_report.md").read_text()
    assert "Publishing" not in content


class TestMetricsEdgeCases:
    def test_record_retries(self):
        pm = PipelineMetrics("pipe_ret")
        pm.record_retries(3)
        assert pm.data["retries"] == 3

    def test_record_skipped_clips(self):
        pm = PipelineMetrics("pipe_skip")
        pm.record_skipped_clips(5)
        assert pm.data["skipped_clips"] == 5

    def test_save_no_output_dir(self, mock_base):
        pm = PipelineMetrics("pipe_nodef", "test")
        pm.record_stage("research", 1.0)
        pm.record_final_status("completed")
        from mindmargin.core.metrics import project_dir
        with patch("mindmargin.core.metrics.project_dir", return_value=mock_base / "pipe_nodef_test"):
            pm.save()
        metrics_path = mock_base / "pipe_nodef_test" / "metrics.json"
        assert metrics_path.exists()

    def test_gather_resource_usage_import_error(self):
        import sys
        with patch.dict("sys.modules", {"psutil": None}):
            pm = PipelineMetrics("pipe_psutil")
            pm._gather_resource_usage()
            assert "cpu_percent" not in pm.data

    def test_markdown_retries_section(self, tmp_path):
        pm = PipelineMetrics("pipe_md_ret", "topic")
        pm.record_stage("research", 1.0)
        pm.record_retries(2)
        pm.record_final_status("completed")
        pm.save(output_dir=tmp_path)
        content = (tmp_path / "pipeline_health_report.md").read_text()
        assert "Retries" in content
        assert "2" in content
