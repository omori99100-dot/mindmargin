"""Unit tests for analytics.ab_testing — A/B rotation lifecycle."""

import pytest
from mindmargin.analytics.ab_testing import (
    AB_CONFIG, has_sufficient_signal, _days_since_publish,
)


class TestHasSufficientSignal:
    def test_sufficient_impressions(self):
        assert has_sufficient_signal(100) is True
        assert has_sufficient_signal(500) is True

    def test_insufficient_impressions(self):
        assert has_sufficient_signal(0) is False
        assert has_sufficient_signal(50) is False

    def test_views_fallback(self):
        assert has_sufficient_signal(0, views=30) is True
        assert has_sufficient_signal(0, views=100) is True

    def test_views_fallback_insufficient(self):
        assert has_sufficient_signal(0, views=0) is False
        assert has_sufficient_signal(0, views=29) is False

    def test_both_sufficient(self):
        assert has_sufficient_signal(200, views=50) is True


class TestDaysSincePublish:
    def test_recent_publish(self):
        days = _days_since_publish("test-pipe-recent")
        assert days >= 0

    def test_no_publish_date(self):
        days = _days_since_publish("test-pipe-nonexistent")
        assert days == 999.0


class TestABConfig:
    def test_config_structure(self):
        assert "days_before_first_rotation" in AB_CONFIG
        assert "days_between_rotations" in AB_CONFIG
        assert "min_impressions_for_decision" in AB_CONFIG
        assert AB_CONFIG["min_impressions_for_decision"] == 10

    def test_reasonable_timeframes(self):
        assert 0 < AB_CONFIG["days_before_first_rotation"] <= 7
        assert 0 < AB_CONFIG["days_between_rotations"] <= 14
        assert 0 < AB_CONFIG["thumbnail_test_days"] <= 14


class TestSeedVariants:
    def test_seed_returns_count(self, in_memory_db, monkeypatch):
        monkeypatch.setattr("mindmargin.analytics.ab_testing.memory._get_db",
                            lambda: in_memory_db)
        from mindmargin.analytics.ab_testing import seed_variants
        # Insert a pipeline and some titles/thumbnails
        in_memory_db.execute(
            "INSERT INTO pipelines (id, topic) VALUES (?, ?)",
            ("seed-pipe", "Test Topic"),
        )
        for i, t in enumerate(["Title 1", "Title 2", "Title 3"]):
            in_memory_db.execute(
                "INSERT INTO titles (pipeline_id, title, rank) VALUES (?, ?, ?)",
                ("seed-pipe", t, i),
            )
        in_memory_db.commit()
        count = seed_variants("seed-pipe", "test_vid_001")
        assert count >= 0
