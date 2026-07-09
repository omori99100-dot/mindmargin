"""Unit tests for decision_executor — autonomous execution cycle."""

import pytest
from unittest.mock import MagicMock, patch
from mindmargin.agents.decision_executor import (
    select_topic, execute_pipeline, publish_video, log_execution,
    execute_top_decision, format_execution_report, reset_circuit_breaker,
)
from mindmargin.analytics.memory import save_execution_log, get_execution_log


def _fake_lineages(*items):
    """Build a list of lineage dicts for mocking get_topic_lineages."""
    return [
        {
            "parent_topic": p, "child_topic": c,
            "confidence": conf, "performance_inheritance": pi,
            "is_published": pub,
        }
        for p, c, conf, pi, pub in items
    ]


class TestSelectTopic:
    @pytest.fixture(autouse=True)
    def _mock_intelligence(self):
        with patch("mindmargin.analytics.memory.get_top_opportunities") as mock_opps, \
             patch("mindmargin.analytics.memory.get_execution_log") as mock_log:
            mock_opps.return_value = []
            mock_log.return_value = []
            yield

    def test_from_brain(self):
        assert select_topic({"top_topic": "Brain Picked Topic"}, {}) == "Brain Picked Topic"

    def test_from_growth_fallback(self):
        assert select_topic({}, {"top_recommendations": ["Growth Topic"]}) == "Growth Topic"

    @patch("mindmargin.agents.decision_executor.get_topic_lineages")
    def test_from_lineage_fallback(self, mock_lineages):
        mock_lineages.return_value = _fake_lineages(
            ("parent", "Lineage Topic", 0.8, 0.75, 0),
        )
        assert select_topic({}, {}) == "Lineage Topic"

    @patch("mindmargin.agents.decision_executor.get_topic_lineages")
    def test_from_domain_fallback(self, mock_lineages):
        mock_lineages.return_value = []
        assert select_topic({}, {}) == "business failure"

    @patch("mindmargin.agents.decision_executor.get_topic_lineages")
    def test_skips_published_lineages(self, mock_lineages):
        mock_lineages.return_value = _fake_lineages(
            ("parent", "Already Done", 0.9, 0.85, 1),
        )
        assert select_topic({}, {}) == "business failure"

    @patch("mindmargin.agents.decision_executor.get_topic_lineages")
    def test_prefers_highest_confidence_lineage(self, mock_lineages):
        mock_lineages.return_value = _fake_lineages(
            ("p1", "Low Inheritance", 0.9, 0.2, 0),
            ("p2", "High Inheritance", 0.7, 0.95, 0),
        )
        assert select_topic({}, {}) == "High Inheritance"

    def test_brain_overrides_growth(self):
        assert select_topic(
            {"top_topic": "From Brain"},
            {"top_recommendations": ["From Growth"]},
        ) == "From Brain"

    @patch("mindmargin.agents.decision_executor.get_topic_lineages")
    def test_empty_strings_in_brain(self, mock_lineages):
        mock_lineages.return_value = []
        assert select_topic({"top_topic": ""}, {}) == "business failure"

    @patch("mindmargin.agents.decision_executor.get_topic_lineages")
    def test_empty_strings_in_growth(self, mock_lineages):
        mock_lineages.return_value = []
        assert select_topic({}, {"top_recommendations": [""]}) == "business failure"

    def test_picks_intelligence_over_brain(self):
        with patch("mindmargin.analytics.memory.get_top_opportunities") as mock_opps, \
             patch("mindmargin.analytics.memory.get_execution_log") as mock_log:
            mock_opps.return_value = [{"topic": "AI Picked", "opportunity_score": 85.0}]
            mock_log.return_value = []
            result = select_topic({"top_topic": "Brain Topic"}, {})
            assert result == "AI Picked"

    def test_skips_published_intelligence_topics(self):
        with patch("mindmargin.analytics.memory.get_top_opportunities") as mock_opps, \
             patch("mindmargin.analytics.memory.get_execution_log") as mock_log:
            mock_opps.return_value = [
                {"topic": "Already Published", "opportunity_score": 90.0},
                {"topic": "Fresh Topic", "opportunity_score": 80.0},
            ]
            mock_log.return_value = [{"topic": "Already Published", "pipeline_status": "completed", "error": ""}]
            result = select_topic({}, {"top_recommendations": ["Brain Topic"]})
            assert result == "Fresh Topic"


class TestExecutePipeline:
    @patch("mindmargin.agents.decision_executor.Pipeline")
    def test_calls_pipeline_run(self, MockPipeline):
        mock_pipe = MagicMock()
        mock_pipe.run.return_value = {"status": "completed", "pipeline_id": "pid-123", "timing_s": 42.0}
        MockPipeline.return_value = mock_pipe

        result = execute_pipeline("Test Topic", quick=False)
        MockPipeline.assert_called_once_with(topic="Test Topic", duration_scale=1.0, editing_timeout=None)
        mock_pipe.run.assert_called_once()
        assert result["status"] == "completed"
        assert result["pipeline_id"] == "pid-123"

    @patch("mindmargin.agents.decision_executor.Pipeline")
    def test_quick_mode_reduces_scale(self, MockPipeline):
        mock_pipe = MagicMock()
        mock_pipe.run.return_value = {"status": "completed"}
        MockPipeline.return_value = mock_pipe

        execute_pipeline("Quick Topic", quick=True)
        MockPipeline.assert_called_once_with(topic="Quick Topic", duration_scale=0.1, editing_timeout=None)

    @patch("mindmargin.agents.decision_executor.Pipeline")
    def test_pipeline_failure_returns_status(self, MockPipeline):
        mock_pipe = MagicMock()
        mock_pipe.run.return_value = {"status": "failed", "error": "something broke"}
        MockPipeline.return_value = mock_pipe

        result = execute_pipeline("Failing Topic")
        assert result["status"] == "failed"


class TestLogExecution:
    def test_saves_to_db(self):
        with patch("mindmargin.agents.decision_executor.save_execution_log") as mock_save, \
             patch("mindmargin.agents.decision_executor.mark_topic_published") as mock_mark:
            log_execution(
                pipeline_id="pipe-001", topic="Test Topic",
                decision_domain="topic", decision_action="produce",
                decision_confidence=0.85, pipeline_status="completed",
                video_id="vid_001", video_url="https://youtu.be/vid_001",
            )
            mock_save.assert_called_once_with(
                pipeline_id="pipe-001", topic="Test Topic",
                decision_domain="topic", decision_action="produce",
                decision_confidence=0.85, pipeline_status="completed",
                video_id="vid_001", video_url="https://youtu.be/vid_001",
                error="",
            )
            mock_mark.assert_called_once_with("Test Topic")

    def test_with_error_does_not_mark_published(self):
        with patch("mindmargin.agents.decision_executor.save_execution_log") as mock_save, \
             patch("mindmargin.agents.decision_executor.mark_topic_published") as mock_mark:
            log_execution(
                pipeline_id="pipe-fail", topic="Bad Topic",
                pipeline_status="failed", error="pipeline crashed",
            )
            mock_save.assert_called_once_with(
                pipeline_id="pipe-fail", topic="Bad Topic",
                decision_domain="", decision_action="",
                decision_confidence=0, pipeline_status="failed",
                video_id="", video_url="",
                error="pipeline crashed",
            )
            mock_mark.assert_not_called()

    def test_defaults(self):
        with patch("mindmargin.agents.decision_executor.save_execution_log") as mock_save, \
             patch("mindmargin.agents.decision_executor.mark_topic_published"):
            log_execution("pid", "topic")
            args, kwargs = mock_save.call_args
            assert kwargs["pipeline_id"] == "pid"
            assert kwargs["topic"] == "topic"
            assert kwargs["decision_domain"] == ""
            assert kwargs["decision_action"] == ""
            assert kwargs["decision_confidence"] == 0
            assert kwargs["pipeline_status"] == "completed"
            assert kwargs["error"] == ""


class TestExecuteTopDecision:
    @patch("mindmargin.analytics.channel_brain.run_brain_cycle")
    @patch("mindmargin.analytics.growth_engine.run_growth_analysis")
    @patch("mindmargin.analytics.memory.get_top_opportunities")
    @patch("mindmargin.intelligence.scoring.run_opportunity_scoring")
    @patch("mindmargin.agents.decision_executor.execute_pipeline")
    @patch("mindmargin.agents.decision_executor.publish_video")
    @patch("mindmargin.agents.decision_executor.save_pipeline_result")
    @patch("mindmargin.agents.decision_executor.log_execution")
    @patch("mindmargin.agents.decision_executor._check_channel_health")
    @patch("mindmargin.agents.decision_executor._check_daily_publish_cap")
    def test_full_success(self, mock_cap, mock_health, mock_log, mock_save_pr, mock_pub, mock_pipe, mock_scoring, mock_opps, mock_growth, mock_brain):
        mock_opps.return_value = []
        mock_health.return_value = (False, "")
        mock_cap.return_value = (False, "")
        mock_brain.return_value = {
            "top_topic": "Autonomous Topic",
            "decisions": [{"domain": "topic", "action": "produce", "confidence": 0.9}],
        }
        mock_growth.return_value = {"opportunities": ["something"]}
        mock_pipe.return_value = {
            "status": "completed", "pipeline_id": "auto-001", "timing_s": 30.0,
            "output_dir": "C:\\tmp\\out",
        }
        mock_pub.return_value = {"status": "completed", "video_id": "vid_auto", "url": "https://youtu.be/vid_auto"}

        result = execute_top_decision(quick=False, auto_publish=True)

        assert result["status"] == "completed"
        assert result["selected_topic"] == "Autonomous Topic"
        assert result["pipeline_id"] == "auto-001"
        assert result["pipeline_status"] == "completed"
        assert result["publish_status"] == "completed"
        assert result["video_id"] == "vid_auto"
        assert result["steps"]["brain"]["status"] == "completed"
        assert result["steps"]["growth"]["status"] == "completed"
        assert result["steps"]["pipeline"]["status"] == "completed"
        assert result["steps"]["publish"]["status"] == "completed"
        mock_pub.assert_called_once()
        mock_log.assert_called_once()

    @patch("mindmargin.analytics.channel_brain.run_brain_cycle")
    @patch("mindmargin.analytics.growth_engine.run_growth_analysis")
    @patch("mindmargin.agents.decision_executor.execute_pipeline")
    @patch("mindmargin.agents.decision_executor.publish_video")
    @patch("mindmargin.agents.decision_executor.save_pipeline_result")
    @patch("mindmargin.agents.decision_executor.log_execution")
    def test_respects_no_publish(self, mock_log, mock_save_pr, mock_pub, mock_pipe, mock_growth, mock_brain):
        mock_brain.return_value = {
            "top_topic": "No Pub Topic",
            "decisions": [{"domain": "topic", "action": "produce", "confidence": 0.85}],
        }
        mock_growth.return_value = {}
        mock_pipe.return_value = {
            "status": "completed", "pipeline_id": "no-pub-001", "timing_s": 15.0,
        }

        result = execute_top_decision(quick=True, auto_publish=False)

        assert result["status"] == "completed"
        assert result["publish_status"] == "skipped"
        mock_pub.assert_not_called()
        mock_log.assert_called_once()

    @patch("mindmargin.analytics.channel_brain.run_brain_cycle")
    @patch("mindmargin.analytics.growth_engine.run_growth_analysis")
    @patch("mindmargin.agents.decision_executor.execute_pipeline")
    @patch("mindmargin.agents.decision_executor.log_execution")
    def test_handles_pipeline_failure(self, mock_log, mock_pipe, mock_growth, mock_brain):
        mock_brain.return_value = {
            "top_topic": "Failing Topic",
            "decisions": [{"domain": "topic", "action": "produce", "confidence": 0.85}],
        }
        mock_growth.return_value = {}
        mock_pipe.side_effect = RuntimeError("pipeline crashed hard")

        result = execute_top_decision()

        assert result["status"] == "failed"
        assert "pipeline crashed hard" in result["error"]
        mock_log.assert_called_once()

    @patch("mindmargin.analytics.channel_brain.run_brain_cycle")
    @patch("mindmargin.analytics.growth_engine.run_growth_analysis")
    @patch("mindmargin.agents.decision_executor.execute_pipeline")
    @patch("mindmargin.agents.decision_executor.log_execution")
    def test_handles_brain_failure(self, mock_log, mock_pipe, mock_growth, mock_brain):
        mock_brain.side_effect = ValueError("brain error")
        mock_growth.return_value = {"top_recommendations": ["Growth Topic"]}
        mock_pipe.return_value = {"status": "completed", "pipeline_id": "g-001"}

        result = execute_top_decision()

        assert result["status"] == "skipped"
        assert result["reason"] == "low_confidence"

    @patch("mindmargin.analytics.channel_brain.run_brain_cycle")
    @patch("mindmargin.analytics.growth_engine.run_growth_analysis")
    @patch("mindmargin.agents.decision_executor.execute_pipeline")
    @patch("mindmargin.agents.decision_executor.log_execution")
    @patch("mindmargin.agents.decision_executor.select_topic")
    def test_no_topic_selected(self, mock_sel, mock_log, mock_pipe, mock_growth, mock_brain):
        mock_brain.return_value = {}
        mock_growth.return_value = {}
        mock_sel.return_value = ""
        mock_pipe.return_value = {"status": "completed"}

        result = execute_top_decision()

        assert result["status"] == "failed"
        assert "No topic" in result["error"]

    @patch("mindmargin.analytics.channel_brain.run_brain_cycle")
    @patch("mindmargin.analytics.growth_engine.run_growth_analysis")
    def test_returns_cycle_structure(self, mock_growth, mock_brain):
        mock_brain.return_value = {
            "top_topic": "Structure Test",
            "decisions": [{"domain": "topic", "action": "produce", "confidence": 0.85}],
        }
        mock_growth.return_value = {}
        with patch("mindmargin.agents.decision_executor.execute_pipeline") as mp:
            mp.return_value = {"status": "completed", "pipeline_id": "s-001"}
            with patch("mindmargin.agents.decision_executor.log_execution"), \
                 patch("mindmargin.agents.decision_executor.save_pipeline_result"):
                result = execute_top_decision()

        assert "status" in result
        assert "started_at" in result
        assert "steps" in result
        assert "brain" in result["steps"]
        assert "growth" in result["steps"]
        assert "pipeline" in result["steps"]


class TestCreateExecutionRecord:
    def test_log_appears_in_get_execution_log(self, in_memory_db, monkeypatch):
        import mindmargin.analytics.memory as mem
        monkeypatch.setattr(mem, "_get_db", lambda: in_memory_db)
        save_execution_log(
            pipeline_id="record-001", topic="Record Topic",
            decision_domain="topic", decision_action="produce",
            decision_confidence=0.88, pipeline_status="completed",
            video_id="vid_rec", video_url="https://youtu.be/vid_rec",
        )
        logs = get_execution_log(limit=10)
        assert any(l["pipeline_id"] == "record-001" for l in logs)
        matching = [l for l in logs if l["pipeline_id"] == "record-001"][0]
        assert matching["topic"] == "Record Topic"
        assert matching["pipeline_status"] == "completed"
        assert matching["video_id"] == "vid_rec"

    def test_log_with_error(self, in_memory_db, monkeypatch):
        import mindmargin.analytics.memory as mem
        monkeypatch.setattr(mem, "_get_db", lambda: in_memory_db)
        save_execution_log(
            pipeline_id="record-002", topic="Failed Record",
            pipeline_status="failed", error="something went wrong",
        )
        logs = get_execution_log(limit=10)
        matching = [l for l in logs if l["pipeline_id"] == "record-002"][0]
        assert matching["error"] == "something went wrong"
        assert matching["pipeline_status"] == "failed"

    def test_multiple_logs_respected(self, in_memory_db, monkeypatch):
        import mindmargin.analytics.memory as mem
        monkeypatch.setattr(mem, "_get_db", lambda: in_memory_db)
        for i in range(3):
            save_execution_log(
                pipeline_id=f"multi-{i}", topic=f"Topic {i}",
            )
        logs = get_execution_log(limit=2)
        assert len(logs) <= 2


class TestFormatReport:
    def test_successful_cycle(self):
        cycle = {
            "status": "completed",
            "selected_topic": "My Topic",
            "pipeline_id": "pipe-001",
            "pipeline_status": "completed",
            "publish_status": "completed",
            "video_url": "https://youtu.be/abc123",
            "steps": {
                "brain": {"status": "completed", "decisions": 5},
                "growth": {"status": "completed", "opportunities": 18},
                "pipeline": {"status": "completed", "timing_s": 42.5},
                "publish": {"status": "completed", "video_id": "abc123"},
            },
        }
        report = format_execution_report(cycle)
        assert "MY TOPIC" in report.upper()
        assert "COMPLETED" in report.upper()
        assert "5 decisions" in report
        assert "18 opportunities" in report
        assert "42.5" in report
        assert "abc123" in report

    def test_failed_cycle(self):
        cycle = {
            "status": "failed",
            "selected_topic": "Bad Topic",
            "pipeline_id": "pipe-fail",
            "pipeline_status": "failed",
            "error": "pipeline crashed",
            "steps": {
                "brain": {"status": "failed", "error": "no decisions", "decisions": 0},
                "growth": {"status": "completed", "opportunities": 0},
            },
        }
        report = format_execution_report(cycle)
        assert "FAILED" in report.upper()
        assert "pipeline crashed" in report
        assert "0 decisions" in report

    def test_minimal_cycle(self):
        cycle = {"status": "running", "steps": {}}
        report = format_execution_report(cycle)
        assert "RUNNING" in report.upper()

    def test_disabled_cycle(self):
        cycle = {
            "status": "disabled",
            "error": "Circuit breaker open: 3 consecutive pipeline failures",
        }
        report = format_execution_report(cycle)
        assert "DISABLED" in report.upper()
        assert "Circuit breaker open" in report


class TestCircuitBreaker:
    def _reset(self):
        import mindmargin.agents.decision_executor as de
        de._CIRCUIT_BREAKER_TRIPPED = False

    @patch("mindmargin.agents.decision_executor.get_execution_log")
    def test_not_tripped_insufficient_logs(self, mock_log):
        self._reset()
        mock_log.return_value = [
            {"pipeline_status": "failed", "error": "err"},
            {"pipeline_status": "failed", "error": "err"},
        ]
        from mindmargin.agents.decision_executor import _check_circuit_breaker
        assert _check_circuit_breaker() is False

    @patch("mindmargin.agents.decision_executor.get_execution_log")
    def test_not_tripped_all_success(self, mock_log):
        self._reset()
        mock_log.return_value = [
            {"pipeline_status": "completed", "error": ""},
            {"pipeline_status": "completed", "error": ""},
            {"pipeline_status": "completed", "error": ""},
        ]
        from mindmargin.agents.decision_executor import _check_circuit_breaker
        assert _check_circuit_breaker() is False

    @patch("mindmargin.agents.decision_executor.get_execution_log")
    def test_tripped_three_failures(self, mock_log):
        self._reset()
        mock_log.return_value = [
            {"pipeline_status": "failed", "error": "err", "topic": "t1"},
            {"pipeline_status": "failed", "error": "err", "topic": "t2"},
            {"pipeline_status": "failed", "error": "err", "topic": "t3"},
        ]
        from mindmargin.agents.decision_executor import _check_circuit_breaker
        assert _check_circuit_breaker() is True

    @patch("mindmargin.agents.decision_executor.get_execution_log")
    def test_resets_after_one_success(self, mock_log):
        self._reset()
        mock_log.return_value = [
            {"pipeline_status": "completed", "error": ""},
            {"pipeline_status": "failed", "error": "err"},
            {"pipeline_status": "failed", "error": "err"},
        ]
        from mindmargin.agents.decision_executor import _check_circuit_breaker
        assert _check_circuit_breaker() is False

    def test_reset_circuit_breaker(self):
        import mindmargin.agents.decision_executor as de
        de._CIRCUIT_BREAKER_TRIPPED = True
        de.reset_circuit_breaker()
        assert de._CIRCUIT_BREAKER_TRIPPED is False

    @patch("mindmargin.agents.decision_executor.get_execution_log")
    def test_executor_returns_disabled_on_trip(self, mock_log):
        self._reset()
        mock_log.return_value = [
            {"pipeline_status": "failed", "error": "err", "topic": "t1"},
            {"pipeline_status": "failed", "error": "err", "topic": "t2"},
            {"pipeline_status": "failed", "error": "err", "topic": "t3"},
        ]
        result = execute_top_decision()
        assert result["status"] == "disabled"
        assert "Circuit breaker" in result["error"]
        assert "consecutive" in result["error"]

    def test_global_state_persists(self):
        import mindmargin.agents.decision_executor as de
        de._CIRCUIT_BREAKER_TRIPPED = True
        result = execute_top_decision()
        assert result["status"] == "disabled"
        de._CIRCUIT_BREAKER_TRIPPED = False


# ═══════════════════════════════════════════════════════════════════
#  Regression tests: Daily publish cap & topic publish state
# ═══════════════════════════════════════════════════════════════════

class TestDailyPublishCapRegression:
    """Regression tests ensuring the daily publish cap only counts genuine
    successful YouTube uploads and never blocks on failed/skipped/duplicate
    executions."""

    def test_failed_publish_does_not_increment_cap(self):
        """A pipeline that failed should NOT count toward the daily cap."""
        with patch("mindmargin.agents.decision_executor.save_execution_log"), \
             patch("mindmargin.agents.decision_executor.mark_topic_published") as mock_mark:
            log_execution(
                pipeline_id="pipe-fail-1", topic="Failed Topic",
                pipeline_status="failed", error="pipeline crashed",
            )
            mock_mark.assert_not_called()

        with patch("mindmargin.analytics.memory.get_execution_log") as mock_log:
            mock_log.return_value = [
                {"executed_at": "2099-01-01 12:00:00", "error": "pipeline crashed",
                 "pipeline_status": "failed", "topic": "Failed Topic"},
            ]
            from mindmargin.agents.decision_executor import _check_daily_publish_cap
            blocked, reason = _check_daily_publish_cap()
            assert not blocked
            assert "published today" not in reason

    def test_skipped_publish_does_not_increment_cap(self):
        """auto_publish=False should NOT count toward the daily cap."""
        with patch("mindmargin.analytics.memory.get_execution_log") as mock_log:
            mock_log.return_value = [
                {"executed_at": "2099-01-01 12:00:00", "error": "pipeline failed",
                 "pipeline_status": "completed", "topic": "Skipped Topic",
                 "video_id": ""},
            ]
            from mindmargin.agents.decision_executor import _check_daily_publish_cap
            blocked, reason = _check_daily_publish_cap()
            assert not blocked

    def test_duplicate_detection_does_not_increment_cap(self):
        """Duplicate detection returning video_id but error='duplicate_skipped'
        should NOT count toward the daily cap."""
        with patch("mindmargin.analytics.memory.get_execution_log") as mock_log:
            mock_log.return_value = [
                {"executed_at": "2099-01-01 12:00:00", "error": "duplicate_skipped",
                 "pipeline_status": "completed", "topic": "Dup Topic",
                 "video_id": "existing_vid"},
            ]
            from mindmargin.agents.decision_executor import _check_daily_publish_cap
            blocked, reason = _check_daily_publish_cap()
            assert not blocked

    def test_successful_upload_increments_cap_exactly_once(self):
        """A genuine successful upload (error='' and video_id non-empty)
        should count exactly once toward the daily cap."""
        with patch("mindmargin.analytics.memory.get_execution_log") as mock_log:
            mock_log.return_value = [
                {"executed_at": "2099-01-01 12:00:00", "error": "",
                 "pipeline_status": "completed", "topic": "Good Topic",
                 "video_id": "real_vid_123"},
            ]
            from mindmargin.agents.decision_executor import _check_daily_publish_cap
            blocked, reason = _check_daily_publish_cap()
            assert blocked
            assert "daily cap 1 reached (1 published today)" in reason

    def test_daily_cap_resets_after_24_hours(self):
        """Execution logs older than 24h should NOT count toward the cap."""
        from datetime import datetime, timedelta
        old_cutoff = (datetime.utcnow() - timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S")
        with patch("mindmargin.analytics.memory.get_execution_log") as mock_log:
            mock_log.return_value = [
                {"executed_at": old_cutoff, "error": "",
                 "pipeline_status": "completed", "topic": "Old Topic",
                 "video_id": "old_vid"},
            ]
            from mindmargin.agents.decision_executor import _check_daily_publish_cap
            blocked, reason = _check_daily_publish_cap()
            assert not blocked

    def test_retry_after_failure_not_blocked(self):
        """After a failed execution, the same topic should be retryable."""
        with patch("mindmargin.analytics.memory.get_top_opportunities") as mock_opps, \
             patch("mindmargin.analytics.memory.get_execution_log") as mock_log:
            mock_opps.return_value = [
                {"topic": "Retry Topic", "opportunity_score": 90.0},
            ]
            # Previous attempt failed
            mock_log.return_value = [
                {"topic": "Retry Topic", "pipeline_status": "failed",
                 "error": "something broke", "executed_at": "2099-01-01 12:00:00"},
            ]
            result = select_topic({"top_topic": "Brain Topic"}, {})
            assert result == "Retry Topic"

    def test_recovery_after_restart_not_blocked(self):
        """After a restart with old execution logs, daily cap should not block."""
        from datetime import datetime, timedelta
        old_time = (datetime.utcnow() - timedelta(hours=25)).strftime("%Y-%m-%d %H:%M:%S")
        with patch("mindmargin.analytics.memory.get_execution_log") as mock_log:
            mock_log.return_value = [
                {"executed_at": old_time, "error": "",
                 "pipeline_status": "completed", "topic": "Restart Topic",
                 "video_id": "restart_vid"},
            ]
            from mindmargin.agents.decision_executor import _check_daily_publish_cap
            blocked, reason = _check_daily_publish_cap()
            assert not blocked

    def test_repeated_execution_no_false_publish_records(self):
        """Executing the same workflow twice should not create false publish
        records if the second execution is a duplicate."""
        with patch("mindmargin.agents.decision_executor.save_execution_log"), \
             patch("mindmargin.agents.decision_executor.mark_topic_published") as mock_mark:
            # First execution: successful
            log_execution(
                pipeline_id="pipe-dup-1", topic="Dup Topic",
                pipeline_status="completed", video_id="vid_123",
                video_url="https://youtu.be/vid_123",
            )
            assert mock_mark.call_count == 1

            # Second execution: duplicate detection
            mock_mark.reset_mock()
            log_execution(
                pipeline_id="pipe-dup-1", topic="Dup Topic",
                pipeline_status="completed", video_id="vid_123",
                video_url="https://youtu.be/vid_123",
                error="duplicate_skipped",
            )
            mock_mark.assert_not_called()

    def test_mixed_results_count_only_successes(self):
        """With a mix of failed, skipped, duplicate, and successful executions,
        only genuine successes should count toward the cap."""
        with patch("mindmargin.analytics.memory.get_execution_log") as mock_log:
            mock_log.return_value = [
                {"executed_at": "2099-01-01 10:00:00", "error": "",
                 "pipeline_status": "completed", "topic": "Success",
                 "video_id": "vid_success"},
                {"executed_at": "2099-01-01 11:00:00", "error": "pipeline crashed",
                 "pipeline_status": "failed", "topic": "Failed",
                 "video_id": ""},
                {"executed_at": "2099-01-01 12:00:00", "error": "duplicate_skipped",
                 "pipeline_status": "completed", "topic": "Duplicate",
                 "video_id": "existing_vid"},
                {"executed_at": "2099-01-01 13:00:00", "error": "pipeline failed",
                 "pipeline_status": "completed", "topic": "Skipped",
                 "video_id": ""},
            ]
            from mindmargin.agents.decision_executor import _check_daily_publish_cap
            blocked, reason = _check_daily_publish_cap()
            assert blocked
            assert "1 published today" in reason


class TestLogExecutionPublishState:
    """Tests that mark_topic_published is only called after genuine uploads."""

    def test_successful_upload_marks_published(self):
        with patch("mindmargin.agents.decision_executor.save_execution_log"), \
             patch("mindmargin.agents.decision_executor.mark_topic_published") as mock_mark:
            log_execution(
                pipeline_id="pipe-ok", topic="Good Topic",
                pipeline_status="completed", video_id="vid_real",
            )
            mock_mark.assert_called_once_with("Good Topic")

    def test_failed_pipeline_does_not_mark_published(self):
        with patch("mindmargin.agents.decision_executor.save_execution_log"), \
             patch("mindmargin.agents.decision_executor.mark_topic_published") as mock_mark:
            log_execution(
                pipeline_id="pipe-fail", topic="Bad Topic",
                pipeline_status="failed", error="crash",
            )
            mock_mark.assert_not_called()

    def test_completed_without_video_id_does_not_mark_published(self):
        with patch("mindmargin.agents.decision_executor.save_execution_log"), \
             patch("mindmargin.agents.decision_executor.mark_topic_published") as mock_mark:
            log_execution(
                pipeline_id="pipe-novid", topic="No Vid Topic",
                pipeline_status="completed", video_id="",
            )
            mock_mark.assert_not_called()

    def test_duplicate_error_does_not_mark_published(self):
        with patch("mindmargin.agents.decision_executor.save_execution_log"), \
             patch("mindmargin.agents.decision_executor.mark_topic_published") as mock_mark:
            log_execution(
                pipeline_id="pipe-dup", topic="Dup Topic",
                pipeline_status="completed", video_id="existing_vid",
                error="duplicate_skipped",
            )
            mock_mark.assert_not_called()

    def test_skipped_publish_does_not_mark_published(self):
        with patch("mindmargin.agents.decision_executor.save_execution_log"), \
             patch("mindmargin.agents.decision_executor.mark_topic_published") as mock_mark:
            log_execution(
                pipeline_id="pipe-skip", topic="Skip Topic",
                pipeline_status="completed", video_id="",
                error="pipeline failed",
            )
            mock_mark.assert_not_called()


class TestSelectTopicRetryBehavior:
    """Tests that select_topic allows retry of failed topics."""

    @pytest.fixture(autouse=True)
    def _mock_intelligence(self):
        with patch("mindmargin.analytics.memory.get_top_opportunities") as mock_opps, \
             patch("mindmargin.analytics.memory.get_execution_log") as mock_log:
            mock_opps.return_value = []
            mock_log.return_value = []
            yield

    def test_failed_topic_not_in_published_set(self):
        with patch("mindmargin.analytics.memory.get_top_opportunities") as mock_opps, \
             patch("mindmargin.analytics.memory.get_execution_log") as mock_log:
            mock_opps.return_value = [
                {"topic": "Failed Before", "opportunity_score": 90.0},
            ]
            mock_log.return_value = [
                {"topic": "Failed Before", "error": "crash",
                 "pipeline_status": "failed"},
            ]
            result = select_topic({}, {})
            assert result == "Failed Before"

    def test_successful_topic_in_published_set(self):
        with patch("mindmargin.analytics.memory.get_top_opportunities") as mock_opps, \
             patch("mindmargin.analytics.memory.get_execution_log") as mock_log:
            mock_opps.return_value = [
                {"topic": "Already Done", "opportunity_score": 90.0},
                {"topic": "Fresh One", "opportunity_score": 80.0},
            ]
            mock_log.return_value = [
                {"topic": "Already Done", "error": "",
                 "pipeline_status": "completed"},
            ]
            result = select_topic({}, {})
            assert result == "Fresh One"

    def test_duplicate_skipped_topic_not_in_published_set(self):
        with patch("mindmargin.analytics.memory.get_top_opportunities") as mock_opps, \
             patch("mindmargin.analytics.memory.get_execution_log") as mock_log:
            mock_opps.return_value = [
                {"topic": "Dup Skipped", "opportunity_score": 90.0},
            ]
            mock_log.return_value = [
                {"topic": "Dup Skipped", "error": "duplicate_skipped",
                 "pipeline_status": "completed", "video_id": "old_vid"},
            ]
            result = select_topic({}, {})
            assert result == "Dup Skipped"
