"""Integration tests for selection cycle, A/B, and pattern analysis working together."""

import pytest


class TestSelectionWithMemory:
    def test_classify_then_reinforce(self, in_memory_db, monkeypatch, mock_youtube_stats):
        monkeypatch.setattr("mindmargin.analytics.selection.get_pipeline_history",
                            lambda limit=200: [{"id": "p1", "youtube_video_id": "vid_001",
                                                "topic": "Enron", "video_duration_s": 600,
                                                "published_at": "2026-05-01 12:00:00"}])
        from mindmargin.analytics.selection import classify_video
        result = classify_video("p1", "vid_001", "Enron", video_duration_s=600)
        assert result["classification"] != "failed"
        assert result["classification"] != "insufficient_signal"

    def test_suppress_losers_requires_classifications(self, in_memory_db, monkeypatch):
        monkeypatch.setattr("mindmargin.analytics.selection._get_db",
                            lambda: in_memory_db)
        from mindmargin.analytics.selection import suppress_losers
        result = suppress_losers()
        assert result["status"] in ("skipped", "completed")

    def test_expand_topics_requires_classifications(self, in_memory_db, monkeypatch):
        monkeypatch.setattr("mindmargin.analytics.selection._get_db",
                            lambda: in_memory_db)
        from mindmargin.analytics.selection import expand_topics
        result = expand_topics()
        assert result["status"] in ("completed", "skipped")

    def test_reinforce_winners_requires_classifications(self, in_memory_db, monkeypatch):
        monkeypatch.setattr("mindmargin.analytics.selection._get_db",
                            lambda: in_memory_db)
        from mindmargin.analytics.selection import reinforce_winners
        result = reinforce_winners()
        assert result["status"] in ("completed", "skipped")


class TestAnalyticsAndPatterns:
    def test_analytics_collection_then_analysis(self, in_memory_db, monkeypatch):
        monkeypatch.setattr("mindmargin.analytics.memory._get_db",
                            lambda: in_memory_db)
        from mindmargin.analytics.memory import save_analytics, save_pipeline
        save_pipeline("int_p1", "Integration Topic")
        save_analytics("int_p1", "int_vid_001", {
            "views": 500, "likes": 30, "comments": 10,
            "shares": 5, "averageViewDuration": 360, "subscribersGained": 5,
        })
        from mindmargin.analytics.patterns import full_pattern_analysis
        analysis = full_pattern_analysis()
        assert analysis["status"] == "completed"

    def test_drift_from_analytics(self, in_memory_db, monkeypatch):
        monkeypatch.setattr("mindmargin.analytics.memory._get_db",
                            lambda: in_memory_db)
        from mindmargin.analytics.memory import save_analytics, save_pipeline, get_analytics_by_week
        from mindmargin.analytics.patterns import compute_drift
        # Insert analytics with explicit past dates
        conn = in_memory_db
        now = "2026-06-03 12:00:00"
        conn.execute("""INSERT INTO pipelines (id, topic, created_at)
                        VALUES (?, ?, ?)""", ("drift_p1", "Drift Topic", now))
        conn.execute("""INSERT INTO analytics (pipeline_id, video_id, views, likes, comments,
                        avg_view_duration_s, subscribers_gained, collected_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                     ("drift_p1", "drift_v1", 1000, 50, 10, 300, 5, now))
        conn.commit()
        drift = compute_drift()
        assert drift["status"] in ("completed", "insufficient_data")
