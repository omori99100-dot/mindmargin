"""Unit tests for mindmargin.integrations.notifications.manager."""

import pytest
from pathlib import Path


@pytest.fixture
def nm(tmp_path):
    from mindmargin.integrations.notifications.manager import NotificationManager
    return NotificationManager(persist_dir=str(tmp_path))


class TestNotificationRecord:
    def test_to_dict(self):
        from mindmargin.integrations.notifications.manager import NotificationRecord
        r = NotificationRecord(channel="telegram", subject="Hi", message="Hello", status="sent")
        d = r.to_dict()
        assert d["channel"] == "telegram"
        assert d["subject"] == "Hi"
        assert d["status"] == "sent"
        assert len(d["message"]) <= 200


class TestNotificationManager:
    def test_init_creates_dir(self, tmp_path):
        from mindmargin.integrations.notifications.manager import NotificationManager
        nm = NotificationManager(persist_dir=str(tmp_path))
        assert nm._notif_dir.exists()

    def test_notify_unknown_channel(self, nm):
        result = nm.notify("unknown_channel", "Subj", "Msg")
        assert result["status"] == "failed"
        assert "Unknown channel" in result["error"]

    def test_history_starts_empty(self, nm):
        assert nm.get_history() == []

    def test_get_status(self, nm):
        status = nm.get_status()
        assert "active_channels" in status
        assert "total_notifications" in status
        assert status["total_notifications"] == 0

    def test_notify_persists_record(self, nm):
        nm.notify("unknown_channel", "Subj", "Msg")
        history = nm.get_history()
        assert len(history) == 1
        assert history[0]["channel"] == "unknown_channel"

    def test_notify_workflow_completed(self, nm):
        result = nm.notify_workflow_completed("daily_job", "completed")
        assert isinstance(result, list)

    def test_notify_workflow_failed(self, nm):
        result = nm.notify_workflow_failed("daily_job", "error msg")
        assert isinstance(result, list)

    def test_notify_video_published(self, nm):
        result = nm.notify_video_published("My Video", "https://youtu.be/abc")
        assert isinstance(result, list)

    def test_notify_experiment_finished(self, nm):
        result = nm.notify_experiment_finished("exp_001", "winner: A")
        assert isinstance(result, list)

    def test_notify_critical_alert(self, nm):
        result = nm.notify_critical_alert("Disk full")
        assert isinstance(result, list)

    def test_notify_provider_failure(self, nm):
        result = nm.notify_provider_failure("openai", "rate limit")
        assert isinstance(result, list)

    def test_notify_executive_decision(self, nm):
        result = nm.notify_executive_decision("pause_uploads", "quota low")
        assert isinstance(result, list)

    def test_persistence(self, tmp_path):
        from mindmargin.integrations.notifications.manager import NotificationManager
        nm1 = NotificationManager(persist_dir=str(tmp_path))
        nm1.notify("unknown_channel", "Test", "Body")
        nm2 = NotificationManager(persist_dir=str(tmp_path))
        assert len(nm2.get_history()) == 1

    def test_history_limit(self, nm):
        for i in range(5):
            nm.notify("unknown_channel", f"Subj {i}", f"Msg {i}")
        assert len(nm.get_history(limit=3)) == 3
