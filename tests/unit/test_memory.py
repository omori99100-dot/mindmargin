"""Unit tests for analytics.memory — SQLite persistence layer."""

import sqlite3
import pytest
from datetime import datetime

from mindmargin.analytics.memory import (
    save_pipeline, save_pipeline_result, get_pipeline_history,
    save_titles, save_hooks, save_thumbnails, save_analytics,
    save_best_practice, get_best_practices,
    get_top_performers, get_best_hooks, get_best_titles, get_pipeline_stats,
    save_classification, get_all_classifications, get_classification_for_video,
    get_classification_counts,
    save_reinforced_pattern, get_reinforced_patterns,
    save_suppressed_pattern, get_suppressed_patterns,
    archive_dead_pattern, get_dead_patterns,
    record_dominant_archetype, get_dominant_archetypes,
    save_topic_lineage, get_topic_lineages, mark_topic_published,
    save_ab_variant, get_ab_variants, get_pending_ab_tests, get_active_ab_tests,
    activate_ab_variant, complete_ab_variant, update_ab_metrics,
    set_ab_winner, set_ab_restored, get_ab_winner_for_pipeline,
    get_ab_winning_titles, get_ab_winning_thumbnails, get_ab_evolution_history,
    get_ab_win_loss_counts, get_ab_active_summary, get_all_completed_ab_tests,
    save_drift_snapshot, get_drift_history, get_latest_drift, get_analytics_by_week,
    close,
)


def test_save_and_get_pipeline(in_memory_db, monkeypatch):
    monkeypatch.setattr("mindmargin.analytics.memory._get_db", lambda: in_memory_db)
    save_pipeline("p1", "Enron", mode="documentary", word_count=500)
    rows = get_pipeline_history(10)
    ids = [r["id"] for r in rows]
    assert "p1" in ids


def test_save_pipeline_result(in_memory_db, monkeypatch):
    monkeypatch.setattr("mindmargin.analytics.memory._get_db", lambda: in_memory_db)
    result = {"topic": "Theranos", "mode": "dark", "video_duration_s": 600.0,
              "video_path": "/out/video.mp4"}
    save_pipeline_result("p2", result)
    rows = get_pipeline_history(10)
    p = next(r for r in rows if r["id"] == "p2")
    assert p["topic"] == "Theranos"
    assert p["mode"] == "dark"


def test_save_titles(in_memory_db, monkeypatch):
    monkeypatch.setattr("mindmargin.analytics.memory._get_db", lambda: in_memory_db)
    save_pipeline("p3", "FTX")
    save_titles("p3", ["Title A", "Title B", "Title C"])
    best = get_best_titles(5)
    assert len(best) >= 2


def test_save_hooks(in_memory_db, monkeypatch):
    monkeypatch.setattr("mindmargin.analytics.memory._get_db", lambda: in_memory_db)
    save_pipeline("p4", "WeWork")
    hooks = [
        {"hook_text": "What if everything...", "archetype": "curiosity_gap",
         "ctr_score": 88, "retention_score": 75},
        {"hook_text": "The warning signs...", "archetype": "fear_based",
         "ctr_score": 85, "retention_score": 70},
    ]
    save_hooks("p4", hooks)
    best = get_best_hooks(5)
    assert len(best) >= 1


def test_save_thumbnails(in_memory_db, monkeypatch):
    monkeypatch.setattr("mindmargin.analytics.memory._get_db", lambda: in_memory_db)
    save_pipeline("p5", "Enron")
    thumbs = [
        {"path": "/thumb/1.jpg", "style": "split_dark_light", "text": "The Truth"},
        {"path": "/thumb/2.jpg", "style": "bottom_bar", "text": "Exposed"},
    ]
    save_thumbnails("p5", thumbs)


def test_save_analytics(in_memory_db, monkeypatch):
    monkeypatch.setattr("mindmargin.analytics.memory._get_db", lambda: in_memory_db)
    save_pipeline("p6", "Lehman")
    save_analytics("p6", "vid_001", {
        "views": 5000, "likes": 300, "comments": 50,
        "shares": 100, "averageViewDuration": 420, "subscribersGained": 25,
    })
    tops = get_top_performers("views", 5)
    assert len(tops) >= 1


def test_best_practices_crud(in_memory_db, monkeypatch):
    monkeypatch.setattr("mindmargin.analytics.memory._get_db", lambda: in_memory_db)
    save_best_practice("hook_archetype", "curiosity_gap",
                       "Curiosity gap scores 88", 88.0)
    save_best_practice("hook_archetype", "fear_based",
                       "Fear based scores 85", 85.0)
    rows = get_best_practices("hook_archetype")
    assert len(rows) == 2
    # Rolling average
    save_best_practice("hook_archetype", "curiosity_gap",
                       "Updated curiosity gap", 90.0)
    rows = get_best_practices("hook_archetype")
    cp = next(r for r in rows if r["key"] == "curiosity_gap")
    assert cp["sample_size"] == 2
    assert 88.0 < cp["score"] < 90.0


def test_classification_save_and_read(in_memory_db, monkeypatch):
    monkeypatch.setattr("mindmargin.analytics.memory._get_db", lambda: in_memory_db)
    save_pipeline("p7", "Madoff")
    save_classification("p7", "vid_madoff", "winner_candidate", 0.85,
                        ctr=12.5, retention=0.65, watch_time_s=5000,
                        impressions=50000, engagement_rate=8.5, velocity=25.0,
                        views=6000, age_days=30)
    rows = get_all_classifications(10)
    assert len(rows) >= 1
    found = get_classification_for_video("vid_madoff")
    assert found is not None
    assert found["classification"] == "winner_candidate"


def test_classification_counts(in_memory_db, monkeypatch, sample_classifications):
    monkeypatch.setattr("mindmargin.analytics.memory._get_db", lambda: in_memory_db)
    counts = get_classification_counts()
    assert counts["winner_candidate"] >= 1
    assert counts["keep_testing"] >= 1
    assert counts["stable_equivalent"] >= 1
    assert counts["weak_signal"] >= 1
    assert counts["insufficient_signal"] >= 1


def test_reinforced_patterns(in_memory_db, monkeypatch):
    monkeypatch.setattr("mindmargin.analytics.memory._get_db", lambda: in_memory_db)
    save_reinforced_pattern("hook_archetype", "curiosity_gap",
                            "Curiosity gap wins", 9.5, 0.9,
                            source_pipeline_id="p1", performance_class="winner_candidate")
    save_reinforced_pattern("title", "numbers_in_title",
                            "Numbers boost CTR", 8.0, 0.7)
    rows = get_reinforced_patterns("hook_archetype")
    assert len(rows) == 1
    rows_all = get_reinforced_patterns()
    assert len(rows_all) == 2
    # Rolling average on second save
    save_reinforced_pattern("hook_archetype", "curiosity_gap",
                            "Updated", 8.0, 0.8)
    rows = get_reinforced_patterns("hook_archetype")
    assert rows[0]["reinforcement_count"] == 2


def test_suppressed_patterns(in_memory_db, monkeypatch):
    monkeypatch.setattr("mindmargin.analytics.memory._get_db", lambda: in_memory_db)
    save_suppressed_pattern("hook_archetype", "shock_value",
                            "Shock value underperforms", 5.0, decay=1.0,
                            reason="low CTR")
    rows = get_suppressed_patterns()
    assert len(rows) == 1
    assert rows[0]["current_decay"] == 1.0
    # Second suppression triggers decay
    save_suppressed_pattern("hook_archetype", "shock_value",
                            "Still underperforms", 5.0, reason="still low")
    rows = get_suppressed_patterns()
    assert rows[0]["suppression_count"] == 2
    assert rows[0]["current_decay"] < 1.0


def test_dead_pattern_archive(in_memory_db, monkeypatch):
    monkeypatch.setattr("mindmargin.analytics.memory._get_db", lambda: in_memory_db)
    save_suppressed_pattern("hook_archetype", "shock_value",
                            "Shock value bad", 5.0)
    archive_dead_pattern("hook_archetype", "shock_value",
                         "Shock value dead", 5.0, 3)
    dead = get_dead_patterns()
    assert len(dead) == 1
    assert dead[0]["final_score"] == 5.0
    # Should be removed from suppressed
    suppressed = get_suppressed_patterns()
    assert len(suppressed) == 0


def test_dominant_archetypes(in_memory_db, monkeypatch):
    monkeypatch.setattr("mindmargin.analytics.memory._get_db", lambda: in_memory_db)
    record_dominant_archetype("hook_archetype", "curiosity_gap", 45.0, 10)
    record_dominant_archetype("hook_archetype", "fear_based", 30.0, 10)
    rows = get_dominant_archetypes("hook_archetype")
    assert len(rows) == 2


def test_topic_lineages(in_memory_db, monkeypatch):
    monkeypatch.setattr("mindmargin.analytics.memory._get_db", lambda: in_memory_db)
    save_topic_lineage("enron", "worldcom scandal", 0.8, 0.6)
    save_topic_lineage("enron", "tyco international", 0.7, 0.5)
    rows = get_topic_lineages("enron")
    assert len(rows) == 2
    mark_topic_published("worldcom scandal")
    rows = get_topic_lineages("enron")
    pub = next(r for r in rows if r["child_topic"] == "worldcom scandal")
    assert pub["is_published"] == 1


def test_ab_variants(in_memory_db, monkeypatch):
    monkeypatch.setattr("mindmargin.analytics.memory._get_db", lambda: in_memory_db)
    save_pipeline("p8", "Test")
    save_ab_variant("p8", "vid_001", "title", 1, "Title Variant A")
    save_ab_variant("p8", "vid_001", "title", 2, "Title Variant B")
    variants = get_ab_variants("p8", "title")
    assert len(variants) == 2


def test_ab_lifecycle(in_memory_db, monkeypatch):
    monkeypatch.setattr("mindmargin.analytics.memory._get_db", lambda: in_memory_db)
    save_pipeline("p9", "Test AB")
    save_ab_variant("p9", "vid_002", "title", 1, "Best Title")
    pending = get_pending_ab_tests()
    assert len(pending) >= 1
    activate_ab_variant(pending[0]["id"])
    active = get_active_ab_tests()
    assert len(active) >= 1
    update_ab_metrics(active[0]["id"], impressions=500, ctr=8.5, watch_time_s=300)
    complete_ab_variant(active[0]["id"])
    set_ab_winner(active[0]["id"])
    winner = get_ab_winner_for_pipeline("p9", "title")
    assert winner is not None
    assert winner["winner_flag"] == 1
    set_ab_restored(winner["id"])


def test_ab_dashboard_queries(in_memory_db, monkeypatch):
    monkeypatch.setattr("mindmargin.analytics.memory._get_db", lambda: in_memory_db)
    save_pipeline("pa", "Enron Analytics")
    save_pipeline("pb", "FTX Analytics")
    save_ab_variant("pa", "v1", "title", 1, "Win Title")
    save_ab_variant("pb", "v2", "thumbnail", 1, "Win Thumb")
    # Manually set winner flags
    conn = in_memory_db
    conn.execute("UPDATE ab_tests SET winner_flag=1, test_phase='completed', "
                 "test_end_time=datetime('now') WHERE pipeline_id='pa'")
    conn.execute("UPDATE ab_tests SET winner_flag=1, test_phase='completed', "
                 "test_end_time=datetime('now') WHERE pipeline_id='pb'")
    conn.commit()
    titles = get_ab_winning_titles()
    thumbs = get_ab_winning_thumbnails()
    history = get_ab_evolution_history()
    counts = get_ab_win_loss_counts()
    all_comp = get_all_completed_ab_tests()
    assert len(titles) >= 1
    assert len(thumbs) >= 1


def test_pipeline_stats(in_memory_db, monkeypatch):
    monkeypatch.setattr("mindmargin.analytics.memory._get_db", lambda: in_memory_db)
    save_pipeline("ps1", "Topic 1")
    save_pipeline("ps2", "Topic 2")
    stats = get_pipeline_stats()
    assert stats["total_pipelines"] >= 2


def test_drift_snapshot(in_memory_db, monkeypatch):
    monkeypatch.setattr("mindmargin.analytics.memory._get_db", lambda: in_memory_db)
    save_drift_snapshot("2026-06-01", "estimated_ctr", 5.2, 4.8, 8.3,
                        "positive", 0.75, 10, 8)
    save_drift_snapshot("2026-05-25", "estimated_ctr", 4.8, 5.0, -4.0,
                        "neutral", 0.6, 8, 7)
    history = get_drift_history("estimated_ctr")
    assert len(history) == 2
    latest = get_latest_drift("estimated_ctr")
    assert latest is not None
    assert latest["snapshot_date"] == "2026-06-01"


def test_analytics_by_week(in_memory_db, monkeypatch):
    monkeypatch.setattr("mindmargin.analytics.memory._get_db", lambda: in_memory_db)
    save_pipeline("pw1", "Week Topic")
    save_analytics("pw1", "vid_w1", {"views": 100, "likes": 10, "comments": 2,
                                       "shares": 5, "averageViewDuration": 300,
                                       "subscribersGained": 3})
    weeks = get_analytics_by_week()
    assert len(weeks) >= 1


def test_close_does_not_raise(in_memory_db, monkeypatch):
    monkeypatch.setattr("mindmargin.analytics.memory._get_db", lambda: in_memory_db)
    close()
