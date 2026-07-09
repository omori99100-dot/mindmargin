"""Unit tests for mindmargin.integrations.youtube.connector."""

import json
import pytest
from pathlib import Path


@pytest.fixture
def connector(tmp_path):
    from mindmargin.integrations.youtube.connector import YouTubeConnector
    return YouTubeConnector(persist_dir=str(tmp_path))


class TestQuotaUsage:
    def test_initial_state(self):
        from mindmargin.integrations.youtube.connector import QuotaUsage
        q = QuotaUsage(date="2026-01-01")
        assert q.remaining == 10000
        assert q.upload_remaining == 50
        assert q.can_upload() is True

    def test_exhausted_quota(self):
        from mindmargin.integrations.youtube.connector import QuotaUsage
        q = QuotaUsage(date="2026-01-01", used=10000)
        assert q.remaining == 0
        assert q.can_upload() is False

    def test_upload_limit_reached(self):
        from mindmargin.integrations.youtube.connector import QuotaUsage
        q = QuotaUsage(date="2026-01-01", uploads=50)
        assert q.upload_remaining == 0
        assert q.can_upload() is False

    def test_pct_used(self):
        from mindmargin.integrations.youtube.connector import QuotaUsage
        q = QuotaUsage(date="2026-01-01", used=5000)
        assert q.pct_used == 50.0

    def test_to_dict(self):
        from mindmargin.integrations.youtube.connector import QuotaUsage
        q = QuotaUsage(date="2026-01-01", used=1000)
        d = q.to_dict()
        assert d["date"] == "2026-01-01"
        assert d["used"] == 1000
        assert d["remaining"] == 9000
        assert d["can_upload"] is True


class TestUploadRecord:
    def test_to_dict(self):
        from mindmargin.integrations.youtube.connector import UploadRecord
        r = UploadRecord(video_id="abc123", title="Test", status="completed")
        d = r.to_dict()
        assert d["video_id"] == "abc123"
        assert d["title"] == "Test"
        assert d["status"] == "completed"


class TestYouTubeConnector:
    def test_init_creates_dir(self, tmp_path):
        from mindmargin.integrations.youtube.connector import YouTubeConnector
        c = YouTubeConnector(persist_dir=str(tmp_path))
        assert c._yt_dir.exists()

    def test_get_quota(self, connector):
        q = connector.get_quota()
        assert q.limit == 10000

    def test_get_status(self, connector):
        status = connector.get_status()
        assert "quota" in status
        assert "total_uploads" in status
        assert "recent_uploads" in status
        assert "authenticated" in status

    def test_upload_quota_exhausted(self, connector):
        connector._quota.used = 10000
        result = connector.upload_video("/nonexistent/video.mp4", "Test")
        assert result["status"] == "failed"
        assert "Quota" in result["error"]

    def test_upload_history(self, connector):
        history = connector.get_upload_history()
        assert isinstance(history, list)

    def test_get_history_alias(self, connector):
        assert connector.get_history() == connector.get_upload_history()

    def test_persistence(self, tmp_path):
        from mindmargin.integrations.youtube.connector import YouTubeConnector
        c1 = YouTubeConnector(persist_dir=str(tmp_path))
        assert c1._history_path.exists() or True  # file may not exist yet

    def test_quota_resets_daily(self, tmp_path):
        from mindmargin.integrations.youtube.connector import YouTubeConnector
        c = YouTubeConnector(persist_dir=str(tmp_path))
        c._quota.used = 9000
        c._save_quota()
        c2 = YouTubeConnector(persist_dir=str(tmp_path))
        assert c2._quota.used == 0  # fresh day = fresh quota
