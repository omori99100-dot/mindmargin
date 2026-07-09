"""Shared fixtures for MindMargin test suite."""

import os
import sys
import pytest
import sqlite3
import tempfile
from pathlib import Path
from typing import Generator

# Ensure project root is on sys.path
_proj_root = Path(__file__).resolve().parent.parent
if str(_proj_root) not in sys.path:
    sys.path.insert(0, str(_proj_root))


@pytest.fixture(autouse=True)
def _clean_env():
    """Prevent accidental real YouTube/API calls during tests."""
    os.environ.setdefault("MINDMARGIN_TESTING", "1")
    yield


@pytest.fixture
def tmp_db_path() -> Generator[str, None, None]:
    """Provide a temporary SQLite database path and clean up after."""
    fh, path = tempfile.mkstemp(suffix=".db")
    os.close(fh)
    yield path
    try:
        os.unlink(path)
    except OSError:
        pass


@pytest.fixture
def in_memory_db() -> Generator[sqlite3.Connection, None, None]:
    """Create an in-memory SQLite database with the full MindMargin schema."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=MEMORY")
    _seed_schema(conn)
    yield conn
    conn.close()


def _seed_schema(conn: sqlite3.Connection):
    """Create all MindMargin tables (mirrors memory._init_schema)."""
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS pipelines (
            id TEXT PRIMARY KEY, topic TEXT NOT NULL, mode TEXT DEFAULT 'documentary',
            status TEXT DEFAULT 'completed', word_count INTEGER DEFAULT 0,
            video_duration_s REAL DEFAULT 0, video_path TEXT DEFAULT '',
            thumbnail_path TEXT DEFAULT '', youtube_video_id TEXT DEFAULT '',
            youtube_url TEXT DEFAULT '', youtube_status TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now')), published_at TEXT
        );
        CREATE TABLE IF NOT EXISTS titles (
            id INTEGER PRIMARY KEY AUTOINCREMENT, pipeline_id TEXT NOT NULL,
            title TEXT NOT NULL, rank INTEGER DEFAULT 0, used INTEGER DEFAULT 0,
            ctr REAL, views INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (pipeline_id) REFERENCES pipelines(id)
        );
        CREATE TABLE IF NOT EXISTS hooks (
            id INTEGER PRIMARY KEY AUTOINCREMENT, pipeline_id TEXT NOT NULL,
            hook_text TEXT NOT NULL, archetype TEXT DEFAULT '',
            ctr_score REAL DEFAULT 0, retention_score REAL DEFAULT 0,
            used INTEGER DEFAULT 0, actual_ctr REAL, actual_retention REAL,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (pipeline_id) REFERENCES pipelines(id)
        );
        CREATE TABLE IF NOT EXISTS thumbnails (
            id INTEGER PRIMARY KEY AUTOINCREMENT, pipeline_id TEXT NOT NULL,
            path TEXT NOT NULL, style TEXT DEFAULT '', text_overlay TEXT DEFAULT '',
            used INTEGER DEFAULT 0, actual_ctr REAL, impressions INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (pipeline_id) REFERENCES pipelines(id)
        );
        CREATE TABLE IF NOT EXISTS analytics (
            id INTEGER PRIMARY KEY AUTOINCREMENT, pipeline_id TEXT NOT NULL,
            video_id TEXT NOT NULL, views INTEGER DEFAULT 0, likes INTEGER DEFAULT 0,
            comments INTEGER DEFAULT 0, shares INTEGER DEFAULT 0,
            avg_view_duration_s REAL DEFAULT 0, subscribers_gained INTEGER DEFAULT 0,
            collected_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (pipeline_id) REFERENCES pipelines(id)
        );
        CREATE TABLE IF NOT EXISTS best_practices (
            id INTEGER PRIMARY KEY AUTOINCREMENT, category TEXT NOT NULL,
            key TEXT NOT NULL, value TEXT NOT NULL, score REAL DEFAULT 0,
            sample_size INTEGER DEFAULT 1, updated_at TEXT DEFAULT (datetime('now')),
            UNIQUE(category, key)
        );
        CREATE TABLE IF NOT EXISTS ab_tests (
            id INTEGER PRIMARY KEY AUTOINCREMENT, pipeline_id TEXT NOT NULL,
            video_id TEXT NOT NULL, variant_type TEXT NOT NULL,
            variant_index INTEGER NOT NULL, variant_value TEXT NOT NULL,
            test_phase TEXT DEFAULT 'pending', test_start_time TEXT,
            test_end_time TEXT, impressions INTEGER DEFAULT 0, ctr REAL DEFAULT 0,
            watch_time_s REAL DEFAULT 0, winner_flag INTEGER DEFAULT 0,
            restored INTEGER DEFAULT 0, created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (pipeline_id) REFERENCES pipelines(id)
        );
        CREATE TABLE IF NOT EXISTS performance_drift (
            id INTEGER PRIMARY KEY AUTOINCREMENT, snapshot_date TEXT NOT NULL,
            metric TEXT NOT NULL, current_value REAL DEFAULT 0,
            previous_value REAL DEFAULT 0, pct_change REAL DEFAULT 0,
            drift_classification TEXT DEFAULT 'neutral', confidence REAL DEFAULT 0,
            sample_size_current INTEGER DEFAULT 0, sample_size_previous INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS video_classifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT, pipeline_id TEXT NOT NULL,
            video_id TEXT NOT NULL, classification TEXT NOT NULL,
            confidence REAL DEFAULT 0, ctr REAL DEFAULT 0, retention REAL DEFAULT 0,
            watch_time_s REAL DEFAULT 0, impressions INTEGER DEFAULT 0,
            engagement_rate REAL DEFAULT 0, velocity REAL DEFAULT 0,
            views INTEGER DEFAULT 0, age_days REAL DEFAULT 0,
            classified_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (pipeline_id) REFERENCES pipelines(id)
        );
        CREATE TABLE IF NOT EXISTS reinforced_patterns (
            id INTEGER PRIMARY KEY AUTOINCREMENT, category TEXT NOT NULL,
            key TEXT NOT NULL, value TEXT NOT NULL, selection_score REAL DEFAULT 0,
            reinforcement_count INTEGER DEFAULT 1, confidence REAL DEFAULT 0,
            source_pipeline_id TEXT DEFAULT '', performance_class TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now')),
            UNIQUE(category, key)
        );
        CREATE TABLE IF NOT EXISTS suppressed_patterns (
            id INTEGER PRIMARY KEY AUTOINCREMENT, category TEXT NOT NULL,
            key TEXT NOT NULL, value TEXT NOT NULL, original_score REAL DEFAULT 0,
            current_decay REAL DEFAULT 1.0, suppression_count INTEGER DEFAULT 1,
            reason TEXT DEFAULT '', created_at TEXT DEFAULT (datetime('now')),
            UNIQUE(category, key)
        );
        CREATE TABLE IF NOT EXISTS dead_patterns (
            id INTEGER PRIMARY KEY AUTOINCREMENT, category TEXT NOT NULL,
            key TEXT NOT NULL, value TEXT NOT NULL, final_score REAL DEFAULT 0,
            suppression_count INTEGER DEFAULT 0, archived_at TEXT DEFAULT (datetime('now')),
            UNIQUE(category, key)
        );
        CREATE TABLE IF NOT EXISTS dominant_archetypes (
            id INTEGER PRIMARY KEY AUTOINCREMENT, category TEXT NOT NULL,
            archetype TEXT NOT NULL, dominance_pct REAL DEFAULT 0,
            sample_size INTEGER DEFAULT 0, recorded_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS topic_lineages (
            id INTEGER PRIMARY KEY AUTOINCREMENT, parent_topic TEXT NOT NULL,
            child_topic TEXT NOT NULL, confidence REAL DEFAULT 0,
            performance_inheritance REAL DEFAULT 0, is_published INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            UNIQUE(parent_topic, child_topic)
        );
        CREATE TABLE IF NOT EXISTS execution_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pipeline_id TEXT NOT NULL,
            topic TEXT NOT NULL,
            decision_domain TEXT DEFAULT '',
            decision_action TEXT DEFAULT '',
            decision_confidence REAL DEFAULT 0,
            pipeline_status TEXT DEFAULT 'completed',
            video_id TEXT DEFAULT '',
            video_url TEXT DEFAULT '',
            error TEXT DEFAULT '',
            executed_at TEXT DEFAULT (datetime('now'))
        );
    """)
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_vc_pipeline_video ON video_classifications(pipeline_id, video_id)")


@pytest.fixture
def sample_pipeline(in_memory_db) -> dict:
    """Insert a sample pipeline and return its id."""
    pid = "test-pipe-001"
    in_memory_db.execute(
        "INSERT INTO pipelines (id, topic, mode, youtube_video_id) VALUES (?, ?, ?, ?)",
        (pid, "Test Topic", "documentary", "test_vid_001"),
    )
    in_memory_db.commit()
    return {"id": pid, "topic": "Test Topic", "video_id": "test_vid_001"}


@pytest.fixture
def sample_classifications(in_memory_db, sample_pipeline) -> list[dict]:
    """Insert sample video_classifications across all labels."""
    rows = [
        ("pipe-w-001", "vid_w_001", "winner_candidate", 0.85, 0.12, 0.65, 5000, 50.0, 0.45),
        ("pipe-k-002", "vid_k_002", "keep_testing", 0.65, 0.08, 0.45, 2000, 30.0, 0.28),
        ("pipe-s-003", "vid_s_003", "stable_equivalent", 0.50, 0.05, 0.35, 800, 15.0, 0.15),
        ("pipe-wk-004", "vid_wk_004", "weak_signal", 0.30, 0.02, 0.20, 100, 5.0, 0.05),
        ("pipe-i-005", "vid_i_005", "insufficient_signal", 0.0, 0.0, 0.0, 0, 0.0, 0.0),
    ]
    for pid, vid, cls, conf, ctr, ret, imp, vel, eng in rows:
        in_memory_db.execute("""
            INSERT INTO video_classifications
                (pipeline_id, video_id, classification, confidence,
                 ctr, retention, impressions, velocity, engagement_rate)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (pid, vid, cls, conf, ctr, ret, imp, vel, eng))
    in_memory_db.commit()
    return [
        {"pipeline_id": r[0], "video_id": r[1], "classification": r[2],
         "confidence": r[3], "ctr": r[4], "retention": r[5],
         "impressions": r[6], "velocity": r[7], "engagement_rate": r[8]}
        for r in rows
    ]


@pytest.fixture
def mock_youtube_stats(monkeypatch):
    """Mock get_video_stats and get_analytics to avoid real YouTube API calls."""
    def _mock_stats(video_id: str) -> dict:
        return {
            "status": "completed",
            "video_id": video_id,
            "views": 1500,
            "likes": 80,
            "comments": 15,
            "impressions": 12000,
            "impressions_source": "estimated",
            "published_at": "2026-05-01T12:00:00Z",
            "title": "Test Video",
        }
    def _mock_analytics(video_id: str, **kwargs) -> dict:
        return {
            "status": "completed",
            "video_id": video_id,
            "data": {
                "views": 1500,
                "likes": 80,
                "comments": 15,
                "averageViewDuration": 320.0,
                "averageViewPercentage": 45.0,
                "estimatedMinutesWatched": 8000,
                "shares": 50,
                "subscribersGained": 12,
            },
        }
    import mindmargin.integrations.youtube as yt_mod
    monkeypatch.setattr(yt_mod, "get_video_stats", _mock_stats)
    monkeypatch.setattr(yt_mod, "get_analytics", _mock_analytics)


@pytest.fixture
def mock_youtube_auth(monkeypatch):
    """Mock YouTube authentication to prevent real OAuth flow."""
    def _mock_service(*args, **kwargs):
        return None
    import mindmargin.integrations.youtube.client as yt_client
    monkeypatch.setattr(yt_client, "_get_authenticated_service", _mock_service)
    monkeypatch.setattr(yt_client, "_get_analytics_service", lambda: None)
