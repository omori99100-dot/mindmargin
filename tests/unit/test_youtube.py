"""Unit tests for integrations.youtube -- stubbed, no real API calls."""

import pytest


def test_get_video_stats_auth_failure(monkeypatch):
    import mindmargin.integrations.youtube as yt
    monkeypatch.setattr(yt, "_get_authenticated_service", lambda: None)
    result = yt.get_video_stats("test_vid")
    assert result["status"] == "failed"


def test_upload_video_auth_failure(monkeypatch):
    import mindmargin.integrations.youtube as yt
    monkeypatch.setattr(yt, "_get_authenticated_service", lambda: None)
    result = yt.upload_video("C:\\nonexistent\\video.mp4", "Test")
    assert result["status"] == "failed"


def test_update_metadata_auth_failure(monkeypatch):
    import mindmargin.integrations.youtube as yt
    monkeypatch.setattr(yt, "_get_authenticated_service", lambda: None)
    result = yt.update_video_metadata("test_vid", title="New Title")
    assert result["status"] == "failed"


def test_get_video_stats_estimates_impressions(monkeypatch):
    import mindmargin.integrations.youtube as yt

    class MockVideosList:
        def execute(self):
            return {"items": [{"statistics": {"viewCount": "1500", "likeCount": "80", "commentCount": "15"},
                               "snippet": {"publishedAt": "2026-05-01T12:00:00Z", "title": "Test"}}]}

    class MockVideos:
        def list(self, part, id):
            return MockVideosList()

    class MockYT:
        def videos(self):
            return MockVideos()

    monkeypatch.setattr(yt, "_get_authenticated_service", lambda: MockYT())
    result = yt.get_video_stats("test_vid")
    assert result["status"] == "completed"
    assert result["views"] == 1500
    assert result["impressions"] >= 1500


def test_get_analytics_auth_failure(monkeypatch):
    import mindmargin.integrations.youtube as yt
    monkeypatch.setattr(yt, "_get_authenticated_service", lambda: None)
    monkeypatch.setattr(yt, "_get_analytics_service", lambda: None)
    result = yt.get_analytics("test_vid")
    assert result["status"] == "failed"


def test_list_playlists_auth_failure(monkeypatch):
    import mindmargin.integrations.youtube as yt
    monkeypatch.setattr(yt, "_get_authenticated_service", lambda: None)
    result = yt.list_playlists()
    assert result == []


def test_create_playlist_auth_failure(monkeypatch):
    import mindmargin.integrations.youtube as yt
    monkeypatch.setattr(yt, "_get_authenticated_service", lambda: None)
    result = yt.create_playlist("Test")
    assert result is None


def test_post_comment_auth_failure(monkeypatch):
    import mindmargin.integrations.youtube as yt
    monkeypatch.setattr(yt, "_get_authenticated_service", lambda: None)
    result = yt.post_comment("test_vid", "Hello")
    assert result is None
