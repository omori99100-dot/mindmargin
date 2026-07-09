"""Regression test: cold-start bootstrap publish path.

Verifies that a fresh channel with 0 published videos can publish its first
video without being blocked by the channel health gate or confidence gate.
"""
import pytest
from mindmargin.agents.decision_executor import (
    _check_channel_health,
    _check_daily_publish_cap,
    MIN_CONFIDENCE,
    MIN_CHANNEL_HEALTH,
)


class TestChannelHealthBootstrap:
    """_check_channel_health() must allow the first publishes through."""

    def _patch_brain(self, total_videos, score, monkeypatch):
        """Helper: monkeypatch run_brain_cycle at import site."""
        import mindmargin.analytics.channel_brain as cb
        monkeypatch.setattr(
            cb, "run_brain_cycle",
            lambda: {
                "status": "completed",
                "channel_health": {
                    "overall_score": score,
                    "score": score,
                    "total_videos": total_videos,
                    "dimensions": {},
                },
            }
        )

    def test_bootstrap_zero_videos_not_blocked(self, monkeypatch):
        """0 videos: health ~2.25 < 4.0 but bootstrap must bypass."""
        self._patch_brain(total_videos=0, score=2.2, monkeypatch=monkeypatch)
        blocked, reason = _check_channel_health()
        assert not blocked, (
            f"Bootstrap (0 videos) must bypass health gate, got: {reason}"
        )

    def test_bootstrap_one_video_not_blocked(self, monkeypatch):
        """1 video: still in bootstrap, must not block."""
        self._patch_brain(total_videos=1, score=3.0, monkeypatch=monkeypatch)
        blocked, reason = _check_channel_health()
        assert not blocked, (
            f"Bootstrap (1 video) must bypass health gate, got: {reason}"
        )

    def test_bootstrap_three_videos_not_blocked(self, monkeypatch):
        """3 videos: bootstrap threshold (< 4), must not block."""
        self._patch_brain(total_videos=3, score=3.5, monkeypatch=monkeypatch)
        blocked, reason = _check_channel_health()
        assert not blocked, (
            f"Bootstrap (3 videos) must bypass health gate, got: {reason}"
        )

    def test_normal_gate_enforces_after_four_videos(self, monkeypatch):
        """4+ videos: bootstrap ends, health gate enforces normally."""
        self._patch_brain(total_videos=4, score=3.5, monkeypatch=monkeypatch)
        blocked, reason = _check_channel_health()
        assert blocked, (
            "After bootstrap (4 videos), low health should block, "
            f"got: blocked={blocked}, reason={reason}"
        )

    def test_exception_during_bootstrap_does_not_block(self, monkeypatch):
        """Exceptions in health check should not block during bootstrap."""
        import mindmargin.analytics.channel_brain as cb
        monkeypatch.setattr(cb, "run_brain_cycle", lambda: (_ for _ in ()).throw(RuntimeError("Brain crash")))
        blocked, reason = _check_channel_health()
        assert not blocked, (
            "Exception in health check must not block, "
            f"got: blocked={blocked}, reason={reason}"
        )


class TestConfidenceGateBootstrap:
    """MIN_CONFIDENCE must not block the brain's bootstrap confidence."""

    def test_min_confidence_leq_brain_bootstrap_confidence(self):
        """Brain produces 0.55 confidence for fresh domains.
        MIN_CONFIDENCE must be ≤ 0.55 so bootstrap publishes pass."""
        brain_bootstrap_confidence = 0.55
        assert MIN_CONFIDENCE <= brain_bootstrap_confidence, (
            f"MIN_CONFIDENCE={MIN_CONFIDENCE} > {brain_bootstrap_confidence} "
            f"blocks bootstrap publishes"
        )

    def test_min_confidence_leq_brain_fallback_confidence(self):
        """Brain produces 0.50 confidence as absolute fallback.
        MIN_CONFIDENCE must be ≤ 0.50 so fallback publishes pass."""
        brain_fallback_confidence = 0.50
        assert MIN_CONFIDENCE <= brain_fallback_confidence, (
            f"MIN_CONFIDENCE={MIN_CONFIDENCE} > {brain_fallback_confidence} "
            f"blocks fallback publishes"
        )


class TestLogExecutionBlockedPublish:
    """log_execution must not record an error when publish is blocked."""

    def test_blocked_publish_has_empty_error(self, monkeypatch):
        """When publish blocked, log_error must be ""."""
        calls = []

        def fake_save(**kwargs):
            calls.append(kwargs)

        import mindmargin.agents.decision_executor as de
        monkeypatch.setattr(de, "save_execution_log", fake_save)
        monkeypatch.setattr(de, "mark_topic_published", lambda _: None)

        from mindmargin.agents.decision_executor import log_execution

        log_execution(
            pipeline_id="test_pipe",
            topic="business failure",
            pipeline_status="completed",
            video_id="",
            video_url="",
            error="",
        )

        assert len(calls) == 1, f"save_execution_log called {len(calls)} times"
        recorded_error = calls[0].get("error", "MISSING")
        assert recorded_error == "", (
            f"Blocked publish must record error='', got: '{recorded_error}'"
        )


class TestDailyPublishCap:
    """Daily publish cap must not count blocked publishes."""

    def test_blocked_publish_not_counted_in_cap(self, monkeypatch):
        """Execution log entries with error != '' must not count toward cap."""
        monkeypatch.setattr(
            "mindmargin.agents.decision_executor.get_execution_log",
            lambda limit=50: [
                {
                    "pipeline_id": "p1",
                    "topic": "test",
                    "error": "pipeline failed",
                    "executed_at": "2026-07-04T21:00:00",
                    "video_id": "",
                }
            ]
        )
        blocked, reason = _check_daily_publish_cap()
        assert not blocked, (
            "Blocked publish (error != '') must not count toward daily cap, "
            f"got: {reason}"
        )
