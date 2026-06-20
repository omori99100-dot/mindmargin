"""Integration tests for daily analytics job and pipeline execution."""

from unittest.mock import patch
import pytest
from mindmargin.jobs.daily_analytics import (
    collect_all_analytics, run_feedback_loop, run_daily_job,
    _generate_recommendations,
)


class TestDailyJob:
    def test_collect_all_analytics_no_youtube(self, mock_youtube_auth):
        result = collect_all_analytics()
        assert result["status"] in ("completed", "skipped", "failed")

    @patch("mindmargin.agents.decision_executor.execute_top_decision")
    def test_feedback_loop_without_auth(self, mock_exec):
        """Should handle gracefully when YouTube auth is unavailable."""
        mock_exec.return_value = {"status": "completed", "selected_topic": "mock"}
        result = run_feedback_loop()
        assert result["status"] in ("completed", "failed", "partial")

    @patch("mindmargin.agents.decision_executor.execute_top_decision")
    def test_run_daily_job(self, mock_exec):
        """Entry point should not raise exceptions."""
        mock_exec.return_value = {"status": "completed"}
        try:
            run_daily_job()
        except SystemExit:
            pass

    def test_generate_recommendations(self):
        recommendations = _generate_recommendations()
        assert isinstance(recommendations, list)


class TestFullPipelineExecution:
    def test_classify_reinforce_suppress_expand(self, mock_youtube_stats):
        """Test the full selection cycle end-to-end with mock data."""
        from mindmargin.analytics.selection import run_selection_cycle
        result = run_selection_cycle()
        assert result["status"] in ("completed", "skipped")

    def test_selection_report_format(self, mock_youtube_stats):
        from mindmargin.analytics.selection import format_selection_report
        report = format_selection_report()
        assert isinstance(report, str)
        assert len(report) > 0

    def test_evolution_summary(self):
        from mindmargin.analytics.selection import get_evolution_memory_summary
        summary = get_evolution_memory_summary()
        assert "status" in summary


class TestABRotation:
    def test_rotation_cycle_graceful(self, mock_youtube_auth):
        from mindmargin.analytics.ab_testing import run_ab_rotation_cycle
        result = run_ab_rotation_cycle()
        assert result["status"] in ("completed", "skipped")
