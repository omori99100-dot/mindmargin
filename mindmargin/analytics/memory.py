"""Content memory: SQLite store for performance data, best practices, history."""

import json
import logging
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from mindmargin.config import settings

logger = logging.getLogger(__name__)

_local = threading.local()


def _get_db() -> sqlite3.Connection:
    if not hasattr(_local, "conn") or _local.conn is None:
        db_dir = Path(settings.storage.output_root).parent / "data"
        db_dir.mkdir(parents=True, exist_ok=True)
        db_path = db_dir / "mindmargin.db"
        _local.conn = sqlite3.connect(str(db_path))
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _local.conn.execute("PRAGMA busy_timeout=5000")
        _init_schema(_local.conn)
    return _local.conn


def _init_schema(conn: sqlite3.Connection):
    # Add views/age_days columns to existing video_classifications table
    for col, col_type in [("views", "INTEGER DEFAULT 0"), ("age_days", "REAL DEFAULT 0")]:
        try:
            conn.execute(f"ALTER TABLE video_classifications ADD COLUMN {col} {col_type}")
        except sqlite3.OperationalError:
            pass  # column already exists

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS pipelines (
            id TEXT PRIMARY KEY,
            topic TEXT NOT NULL,
            mode TEXT DEFAULT 'documentary',
            status TEXT DEFAULT 'completed',
            word_count INTEGER DEFAULT 0,
            video_duration_s REAL DEFAULT 0,
            video_path TEXT DEFAULT '',
            thumbnail_path TEXT DEFAULT '',
            youtube_video_id TEXT DEFAULT '',
            youtube_url TEXT DEFAULT '',
            youtube_status TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now')),
            published_at TEXT
        );
        CREATE TABLE IF NOT EXISTS titles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pipeline_id TEXT NOT NULL,
            title TEXT NOT NULL,
            rank INTEGER DEFAULT 0,
            used INTEGER DEFAULT 0,
            ctr REAL,
            views INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (pipeline_id) REFERENCES pipelines(id)
        );
        CREATE TABLE IF NOT EXISTS hooks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pipeline_id TEXT NOT NULL,
            hook_text TEXT NOT NULL,
            archetype TEXT DEFAULT '',
            ctr_score REAL DEFAULT 0,
            retention_score REAL DEFAULT 0,
            used INTEGER DEFAULT 0,
            actual_ctr REAL,
            actual_retention REAL,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (pipeline_id) REFERENCES pipelines(id)
        );
        CREATE TABLE IF NOT EXISTS thumbnails (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pipeline_id TEXT NOT NULL,
            path TEXT NOT NULL,
            style TEXT DEFAULT '',
            text_overlay TEXT DEFAULT '',
            used INTEGER DEFAULT 0,
            actual_ctr REAL,
            impressions INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (pipeline_id) REFERENCES pipelines(id)
        );
        CREATE TABLE IF NOT EXISTS analytics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pipeline_id TEXT NOT NULL,
            video_id TEXT NOT NULL,
            views INTEGER DEFAULT 0,
            likes INTEGER DEFAULT 0,
            comments INTEGER DEFAULT 0,
            shares INTEGER DEFAULT 0,
            avg_view_duration_s REAL DEFAULT 0,
            subscribers_gained INTEGER DEFAULT 0,
            collected_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (pipeline_id) REFERENCES pipelines(id)
        );
        CREATE TABLE IF NOT EXISTS best_practices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            score REAL DEFAULT 0,
            sample_size INTEGER DEFAULT 1,
            updated_at TEXT DEFAULT (datetime('now')),
            UNIQUE(category, key)
        );
        CREATE TABLE IF NOT EXISTS ab_tests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pipeline_id TEXT NOT NULL,
            video_id TEXT NOT NULL,
            variant_type TEXT NOT NULL,
            variant_index INTEGER NOT NULL,
            variant_value TEXT NOT NULL,
            test_phase TEXT DEFAULT 'pending',
            test_start_time TEXT,
            test_end_time TEXT,
            impressions INTEGER DEFAULT 0,
            ctr REAL DEFAULT 0,
            watch_time_s REAL DEFAULT 0,
            winner_flag INTEGER DEFAULT 0,
            restored INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (pipeline_id) REFERENCES pipelines(id)
        );
        CREATE TABLE IF NOT EXISTS performance_drift (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_date TEXT NOT NULL,
            metric TEXT NOT NULL,
            current_value REAL DEFAULT 0,
            previous_value REAL DEFAULT 0,
            pct_change REAL DEFAULT 0,
            drift_classification TEXT DEFAULT 'neutral',
            confidence REAL DEFAULT 0,
            sample_size_current INTEGER DEFAULT 0,
            sample_size_previous INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        );
        -- Selection Pressure / Evolution Memory
        CREATE TABLE IF NOT EXISTS video_classifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            pipeline_id TEXT NOT NULL,
            video_id TEXT NOT NULL,
            classification TEXT NOT NULL,
            confidence REAL DEFAULT 0,
            ctr REAL DEFAULT 0,
            retention REAL DEFAULT 0,
            watch_time_s REAL DEFAULT 0,
            impressions INTEGER DEFAULT 0,
            engagement_rate REAL DEFAULT 0,
            velocity REAL DEFAULT 0,
            views INTEGER DEFAULT 0,
            age_days REAL DEFAULT 0,
            classified_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (pipeline_id) REFERENCES pipelines(id)
        );
        CREATE TABLE IF NOT EXISTS reinforced_patterns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            selection_score REAL DEFAULT 0,
            reinforcement_count INTEGER DEFAULT 1,
            confidence REAL DEFAULT 0,
            source_pipeline_id TEXT DEFAULT '',
            performance_class TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now')),
            UNIQUE(category, key)
        );
        CREATE TABLE IF NOT EXISTS suppressed_patterns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            original_score REAL DEFAULT 0,
            current_decay REAL DEFAULT 1.0,
            suppression_count INTEGER DEFAULT 1,
            reason TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now')),
            UNIQUE(category, key)
        );
        CREATE TABLE IF NOT EXISTS dead_patterns (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            final_score REAL DEFAULT 0,
            suppression_count INTEGER DEFAULT 0,
            archived_at TEXT DEFAULT (datetime('now')),
            UNIQUE(category, key)
        );
        CREATE TABLE IF NOT EXISTS dominant_archetypes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            archetype TEXT NOT NULL,
            dominance_pct REAL DEFAULT 0,
            sample_size INTEGER DEFAULT 0,
            recorded_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS topic_lineages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            parent_topic TEXT NOT NULL,
            child_topic TEXT NOT NULL,
            confidence REAL DEFAULT 0,
            performance_inheritance REAL DEFAULT 0,
            is_published INTEGER DEFAULT 0,
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


def save_pipeline(pipeline_id: str, topic: str, mode: str = "documentary",
                  word_count: int = 0, video_duration_s: float = 0,
                  video_path: str = "", thumbnail_path: str = "",
                  youtube_video_id: str = "", youtube_url: str = "") -> None:
    conn = _get_db()
    conn.execute("""
        INSERT INTO pipelines (id, topic, mode, word_count, video_duration_s,
                               video_path, thumbnail_path, youtube_video_id, youtube_url)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            topic=excluded.topic, mode=excluded.mode,
            word_count=excluded.word_count, video_duration_s=excluded.video_duration_s,
            video_path=excluded.video_path, thumbnail_path=excluded.thumbnail_path,
            youtube_video_id=excluded.youtube_video_id, youtube_url=excluded.youtube_url
    """, (pipeline_id, topic, mode, word_count, video_duration_s,
          video_path, thumbnail_path, youtube_video_id, youtube_url))
    conn.commit()


def save_pipeline_result(pipeline_id: str, result: dict) -> None:
    """Save pipeline result from pipeline.run() summary output."""
    video_path = result.get("video_path", "")
    save_pipeline(
        pipeline_id=pipeline_id,
        topic=result.get("topic", ""),
        mode=result.get("mode", "documentary"),
        video_duration_s=result.get("video_duration_s", 0),
        video_path=video_path,
    )


def save_titles(pipeline_id: str, titles: list[str]) -> None:
    conn = _get_db()
    for i, title in enumerate(titles):
        conn.execute(
            "INSERT INTO titles (pipeline_id, title, rank) VALUES (?, ?, ?)",
            (pipeline_id, title, i),
        )
    conn.commit()


def save_hooks(pipeline_id: str, hooks: list[dict]) -> None:
    conn = _get_db()
    for h in hooks:
        arch = h.get("archetype", "")
        if isinstance(arch, list):
            arch = ", ".join(arch)
        conn.execute(
            "INSERT INTO hooks (pipeline_id, hook_text, archetype, ctr_score, retention_score) "
            "VALUES (?, ?, ?, ?, ?)",
            (pipeline_id, h.get("hook_text", ""), arch,
             h.get("ctr_score", 0), h.get("retention_score", 0)),
        )
    conn.commit()


def save_thumbnails(pipeline_id: str, thumbnails: list[dict]) -> None:
    conn = _get_db()
    for t in thumbnails:
        conn.execute(
            "INSERT INTO thumbnails (pipeline_id, path, style, text_overlay) "
            "VALUES (?, ?, ?, ?)",
            (pipeline_id, t.get("path", ""), t.get("style", ""), t.get("text", "")),
        )
    conn.commit()


def get_video_analytics_from_db(video_id: str) -> dict | None:
    conn = _get_db()
    rows = conn.execute(
        "SELECT * FROM analytics WHERE video_id=? ORDER BY collected_at DESC LIMIT 1",
        (video_id,),
    ).fetchall()
    return dict(rows[0]) if rows else None


def save_analytics(pipeline_id: str, video_id: str, stats: dict) -> None:
    conn = _get_db()
    for col, col_type in [("impressions", "INTEGER DEFAULT 0"),
                          ("ctr", "REAL DEFAULT 0"),
                          ("watch_time_minutes", "REAL DEFAULT 0"),
                          ("average_view_percentage", "REAL DEFAULT 0")]:
        try:
            conn.execute(f"ALTER TABLE analytics ADD COLUMN {col} {col_type}")
        except sqlite3.OperationalError:
            pass
    conn.execute("""
        INSERT INTO analytics (pipeline_id, video_id, views, likes, comments,
                               shares, avg_view_duration_s, subscribers_gained,
                               impressions, ctr,
                               watch_time_minutes, average_view_percentage)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (pipeline_id, video_id,
          stats.get("views", 0), stats.get("likes", 0),
          stats.get("comments", 0), stats.get("shares", 0),
          stats.get("averageViewDuration", 0),
          stats.get("subscribersGained", 0),
          stats.get("impressions", 0),
          stats.get("ctr", 0),
          stats.get("estimatedMinutesWatched", 0),
          stats.get("averageViewPercentage", 0)))
    conn.commit()


def save_best_practice(category: str, key: str, value: str, score: float) -> None:
    conn = _get_db()
    conn.execute("""
        INSERT INTO best_practices (category, key, value, score, sample_size)
        VALUES (?, ?, ?, ?, 1)
        ON CONFLICT(category, key) DO UPDATE SET
            value=excluded.value,
            score=(score * sample_size + excluded.score) / (sample_size + 1),
            sample_size=sample_size + 1,
            updated_at=datetime('now')
    """, (category, key, value, score))
    conn.commit()


def get_best_practices(category: Optional[str] = None) -> list[dict]:
    conn = _get_db()
    if category:
        rows = conn.execute(
            "SELECT * FROM best_practices WHERE category=? ORDER BY score DESC LIMIT 20",
            (category,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM best_practices ORDER BY score DESC LIMIT 50"
        ).fetchall()
    return [dict(r) for r in rows]


def get_pipeline_history(limit: int = 20) -> list[dict]:
    conn = _get_db()
    rows = conn.execute(
        "SELECT * FROM pipelines ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(r) for r in rows]


def get_top_performers(metric: str = "views", limit: int = 10) -> list[dict]:
    conn = _get_db()
    allowed = {"views", "likes", "comments", "avg_view_duration_s"}
    col = metric if metric in allowed else "views"
    rows = conn.execute(f"""
        SELECT p.id, p.topic, p.youtube_url, a.views, a.likes, a.comments,
               a.avg_view_duration_s, a.collected_at
        FROM pipelines p
        JOIN analytics a ON a.pipeline_id = p.id
        ORDER BY a.{col} DESC LIMIT ?
    """, (limit,)).fetchall()
    return [dict(r) for r in rows]


def get_best_hooks(limit: int = 5) -> list[dict]:
    conn = _get_db()
    rows = conn.execute("""
        SELECT hook_text, archetype, ctr_score, actual_ctr, actual_retention, COUNT(*) as used_count
        FROM hooks
        GROUP BY hook_text
        ORDER BY COALESCE(actual_ctr, ctr_score) DESC
        LIMIT ?
    """, (limit,)).fetchall()
    return [dict(r) for r in rows]


def get_best_titles(limit: int = 5) -> list[dict]:
    conn = _get_db()
    rows = conn.execute("""
        SELECT title, ctr, views, COUNT(*) as used_count
        FROM titles
        GROUP BY title
        ORDER BY COALESCE(ctr, 0) DESC
        LIMIT ?
    """, (limit,)).fetchall()
    return [dict(r) for r in rows]


def get_pipeline_stats() -> dict:
    conn = _get_db()
    total = conn.execute("SELECT COUNT(*) as c FROM pipelines").fetchone()["c"]
    published = conn.execute(
        "SELECT COUNT(*) as c FROM pipelines WHERE youtube_video_id != ''"
    ).fetchone()["c"]
    total_views = conn.execute(
        "SELECT COALESCE(SUM(views), 0) as v FROM analytics"
    ).fetchone()["v"]
    total_likes = conn.execute(
        "SELECT COALESCE(SUM(likes), 0) as l FROM analytics"
    ).fetchone()["l"]
    return {
        "total_pipelines": total,
        "published_videos": published,
        "total_views": total_views,
        "total_likes": total_likes,
        "best_hooks": get_best_hooks(3),
        "best_titles": get_best_titles(3),
    }


# ──────────────────────────────────────────────
# Performance Drift Tracking
# ──────────────────────────────────────────────

def save_drift_snapshot(snapshot_date: str, metric: str,
                        current_value: float, previous_value: float,
                        pct_change: float, drift_classification: str,
                        confidence: float,
                        sample_size_current: int = 0,
                        sample_size_previous: int = 0) -> None:
    conn = _get_db()
    conn.execute("""
        INSERT INTO performance_drift
            (snapshot_date, metric, current_value, previous_value,
             pct_change, drift_classification, confidence,
             sample_size_current, sample_size_previous)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (snapshot_date, metric, current_value, previous_value,
          pct_change, drift_classification, confidence,
          sample_size_current, sample_size_previous))
    conn.commit()


def get_drift_history(metric: str | None = None,
                      limit: int = 20) -> list[dict]:
    conn = _get_db()
    if metric:
        rows = conn.execute("""
            SELECT * FROM performance_drift
            WHERE metric=? ORDER BY snapshot_date DESC LIMIT ?
        """, (metric, limit)).fetchall()
    else:
        rows = conn.execute("""
            SELECT * FROM performance_drift
            ORDER BY snapshot_date DESC LIMIT ?
        """, (limit,)).fetchall()
    return [dict(r) for r in rows]


def get_latest_drift(metric: str) -> dict | None:
    conn = _get_db()
    row = conn.execute("""
        SELECT * FROM performance_drift
        WHERE metric=? ORDER BY snapshot_date DESC LIMIT 1
    """, (metric,)).fetchone()
    return dict(row) if row else None


def get_analytics_by_week() -> list[dict]:
    """Aggregate analytics by ISO week for trend computation."""
    conn = _get_db()
    rows = conn.execute("""
        SELECT
            strftime('%Y-W%W', collected_at) AS week,
            COUNT(*) AS video_count,
            AVG(views) AS avg_views,
            AVG(likes) AS avg_likes,
            AVG(comments) AS avg_comments,
            AVG(avg_view_duration_s) AS avg_retention_s,
            SUM(views) AS total_views,
            SUM(subscribers_gained) AS total_subs
        FROM analytics
        WHERE collected_at IS NOT NULL
        GROUP BY week
        ORDER BY week ASC
    """).fetchall()
    return [dict(r) for r in rows]


# ──────────────────────────────────────────────
# A/B Test Tracking
# ──────────────────────────────────────────────

def save_ab_variant(pipeline_id: str, video_id: str, variant_type: str,
                    variant_index: int, variant_value: str) -> None:
    conn = _get_db()
    conn.execute("""
        INSERT OR IGNORE INTO ab_tests
            (pipeline_id, video_id, variant_type, variant_index, variant_value)
        VALUES (?, ?, ?, ?, ?)
    """, (pipeline_id, video_id, variant_type, variant_index, variant_value))
    conn.commit()


def get_ab_variants(pipeline_id: str, variant_type: str) -> list[dict]:
    conn = _get_db()
    rows = conn.execute("""
        SELECT * FROM ab_tests
        WHERE pipeline_id=? AND variant_type=?
        ORDER BY variant_index ASC
    """, (pipeline_id, variant_type)).fetchall()
    return [dict(r) for r in rows]


def get_pending_ab_tests() -> list[dict]:
    """Get AB tests ready for the next rotation phase."""
    conn = _get_db()
    rows = conn.execute("""
        SELECT * FROM ab_tests
        WHERE test_phase = 'pending'
        ORDER BY created_at ASC
    """).fetchall()
    return [dict(r) for r in rows]


def get_active_ab_tests() -> list[dict]:
    """Get AB tests currently in the active (in-test) phase."""
    conn = _get_db()
    rows = conn.execute("""
        SELECT * FROM ab_tests
        WHERE test_phase = 'active'
        ORDER BY test_start_time ASC
    """).fetchall()
    return [dict(r) for r in rows]


def activate_ab_variant(test_id: int) -> None:
    conn = _get_db()
    conn.execute("""
        UPDATE ab_tests
        SET test_phase = 'active', test_start_time = datetime('now')
        WHERE id = ?
    """, (test_id,))
    conn.commit()


def complete_ab_variant(test_id: int) -> None:
    conn = _get_db()
    conn.execute("""
        UPDATE ab_tests
        SET test_phase = 'completed', test_end_time = datetime('now')
        WHERE id = ?
    """, (test_id,))
    conn.commit()


def update_ab_metrics(test_id: int, impressions: int, ctr: float,
                      watch_time_s: float) -> None:
    conn = _get_db()
    conn.execute("""
        UPDATE ab_tests
        SET impressions = ?, ctr = ?, watch_time_s = ?
        WHERE id = ?
    """, (impressions, ctr, watch_time_s, test_id))
    conn.commit()


def set_ab_winner(test_id: int) -> None:
    conn = _get_db()
    conn.execute("""
        UPDATE ab_tests SET winner_flag = 1 WHERE id = ?
    """, (test_id,))
    conn.commit()


def set_ab_restored(test_id: int) -> None:
    conn = _get_db()
    conn.execute("""
        UPDATE ab_tests SET restored = 1 WHERE id = ?
    """, (test_id,))
    conn.commit()


def get_ab_winner_for_pipeline(pipeline_id: str, variant_type: str) -> dict | None:
    """Get the winning variant (if any) for a given pipeline + type."""
    conn = _get_db()
    row = conn.execute("""
        SELECT * FROM ab_tests
        WHERE pipeline_id=? AND variant_type=? AND winner_flag=1
        ORDER BY ctr DESC LIMIT 1
    """, (pipeline_id, variant_type)).fetchone()
    return dict(row) if row else None


# ──────────────────────────────────────────────
# Evolution Dashboard Queries
# ──────────────────────────────────────────────

def get_ab_winning_titles(limit: int = 10) -> list[dict]:
    """Best-performing title variants from A/B tests."""
    conn = _get_db()
    rows = conn.execute("""
        SELECT at.*, p.topic FROM ab_tests at
        JOIN pipelines p ON p.id = at.pipeline_id
        WHERE at.variant_type='title' AND at.winner_flag=1
        ORDER BY at.ctr DESC LIMIT ?
    """, (limit,)).fetchall()
    return [dict(r) for r in rows]


def get_ab_winning_thumbnails(limit: int = 10) -> list[dict]:
    """Best-performing thumbnail styles from A/B tests."""
    conn = _get_db()
    rows = conn.execute("""
        SELECT at.*, p.topic FROM ab_tests at
        JOIN pipelines p ON p.id = at.pipeline_id
        WHERE at.variant_type='thumbnail' AND at.winner_flag=1
        ORDER BY at.ctr DESC LIMIT ?
    """, (limit,)).fetchall()
    return [dict(r) for r in rows]


def get_ab_evolution_history(limit: int = 20) -> list[dict]:
    """All completed A/B tests ordered by time, with topic."""
    conn = _get_db()
    rows = conn.execute("""
        SELECT at.*, p.topic FROM ab_tests at
        JOIN pipelines p ON p.id = at.pipeline_id
        WHERE at.test_phase='completed' OR at.winner_flag=1
        ORDER BY at.test_end_time DESC, at.created_at DESC LIMIT ?
    """, (limit,)).fetchall()
    return [dict(r) for r in rows]


def get_ab_win_loss_counts() -> dict:
    """Count winners vs losers per variant type."""
    conn = _get_db()
    rows = conn.execute("""
        SELECT variant_type, winner_flag, COUNT(*) as count
        FROM ab_tests
        WHERE test_phase='completed'
        GROUP BY variant_type, winner_flag
    """).fetchall()
    result = {"title_wins": 0, "title_losses": 0,
              "thumb_wins": 0, "thumb_losses": 0}
    for r in rows:
        d = dict(r)
        key = "title" if d["variant_type"] == "title" else "thumb"
        if d["winner_flag"]:
            result[f"{key}_wins"] = d["count"]
        else:
            result[f"{key}_losses"] = d["count"]
    return result


def get_ab_active_summary() -> list[dict]:
    """Active A/B tests with topic and elapsed time."""
    conn = _get_db()
    rows = conn.execute("""
        SELECT at.*, p.topic FROM ab_tests at
        JOIN pipelines p ON p.id = at.pipeline_id
        WHERE at.test_phase='active'
        ORDER BY at.test_start_time ASC
    """).fetchall()
    return [dict(r) for r in rows]


def get_all_completed_ab_tests(limit: int = 50) -> list[dict]:
    """Get all completed A/B tests for learning feedback."""
    conn = _get_db()
    rows = conn.execute("""
        SELECT at.*, p.topic as topic
        FROM ab_tests at
        JOIN pipelines p ON p.id = at.pipeline_id
        WHERE at.winner_flag = 1
        ORDER BY at.ctr DESC
        LIMIT ?
    """, (limit,)).fetchall()
    return [dict(r) for r in rows]


# ──────────────────────────────────────────────
# Selection Pressure / Evolution Memory
# ──────────────────────────────────────────────

def save_classification(pipeline_id: str, video_id: str, classification: str,
                        confidence: float, ctr: float = 0, retention: float = 0,
                        watch_time_s: float = 0, impressions: int = 0,
                        engagement_rate: float = 0, velocity: float = 0,
                        views: int = 0, age_days: float = 0) -> None:
    conn = _get_db()
    conn.execute("""
        INSERT INTO video_classifications
            (pipeline_id, video_id, classification, confidence,
             ctr, retention, watch_time_s, impressions,
             engagement_rate, velocity, views, age_days)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(rowid) DO UPDATE SET
            classification=excluded.classification,
            confidence=excluded.confidence,
            ctr=excluded.ctr, retention=excluded.retention,
            watch_time_s=excluded.watch_time_s,
            impressions=excluded.impressions,
            engagement_rate=excluded.engagement_rate,
            velocity=excluded.velocity,
            views=excluded.views,
            age_days=excluded.age_days,
            classified_at=datetime('now')
    """, (pipeline_id, video_id, classification, confidence,
          ctr, retention, watch_time_s, impressions,
          engagement_rate, velocity, views, age_days))
    conn.commit()


def get_all_classifications(limit: int = 100) -> list[dict]:
    conn = _get_db()
    rows = conn.execute("""
        SELECT vc.*, p.topic FROM video_classifications vc
        JOIN pipelines p ON p.id = vc.pipeline_id
        ORDER BY vc.classified_at DESC LIMIT ?
    """, (limit,)).fetchall()
    return [dict(r) for r in rows]


def get_classification_for_video(video_id: str) -> dict | None:
    conn = _get_db()
    row = conn.execute("""
        SELECT vc.*, p.topic FROM video_classifications vc
        JOIN pipelines p ON p.id = vc.pipeline_id
        WHERE vc.video_id=? ORDER BY vc.classified_at DESC LIMIT 1
    """, (video_id,)).fetchone()
    return dict(row) if row else None


def get_classification_counts() -> dict:
    conn = _get_db()
    rows = conn.execute("""
        SELECT classification, COUNT(*) as count
        FROM video_classifications
        WHERE classified_at = (SELECT MAX(classified_at) FROM video_classifications vc2
                               WHERE vc2.pipeline_id = video_classifications.pipeline_id)
        GROUP BY classification
    """).fetchall()
    result = {"winner_candidate": 0, "keep_testing": 0, "stable_equivalent": 0, "weak_signal": 0, "insufficient_signal": 0}
    for r in rows:
        d = dict(r)
        result[d["classification"]] = d["count"]
    return result


def save_reinforced_pattern(category: str, key: str, value: str,
                            selection_score: float, confidence: float,
                            source_pipeline_id: str = "",
                            performance_class: str = "") -> None:
    conn = _get_db()
    existing = conn.execute(
        "SELECT * FROM reinforced_patterns WHERE category=? AND key=?",
        (category, key)
    ).fetchone()
    if existing:
        conn.execute("""
            UPDATE reinforced_patterns SET
                selection_score = (selection_score * reinforcement_count + ?) / (reinforcement_count + 1),
                reinforcement_count = reinforcement_count + 1,
                confidence = (confidence * ?) / ?,
                source_pipeline_id = ?,
                performance_class = ?
            WHERE category=? AND key=?
        """, (selection_score, confidence, max(existing["reinforcement_count"], 1),
              source_pipeline_id, performance_class, category, key))
    else:
        conn.execute("""
            INSERT INTO reinforced_patterns
                (category, key, value, selection_score, confidence,
                 source_pipeline_id, performance_class)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (category, key, value, selection_score, confidence,
              source_pipeline_id, performance_class))
    conn.commit()


def get_reinforced_patterns(category: str | None = None,
                            limit: int = 30) -> list[dict]:
    conn = _get_db()
    if category:
        rows = conn.execute("""
            SELECT * FROM reinforced_patterns
            WHERE category=? ORDER BY selection_score DESC LIMIT ?
        """, (category, limit)).fetchall()
    else:
        rows = conn.execute("""
            SELECT * FROM reinforced_patterns
            ORDER BY selection_score DESC LIMIT ?
        """, (limit,)).fetchall()
    return [dict(r) for r in rows]


def save_suppressed_pattern(category: str, key: str, value: str,
                            original_score: float, decay: float = 1.0,
                            reason: str = "") -> None:
    conn = _get_db()
    existing = conn.execute(
        "SELECT * FROM suppressed_patterns WHERE category=? AND key=?",
        (category, key)
    ).fetchone()
    if existing:
        new_decay = existing["current_decay"] * 0.7  # multiplicative decay
        conn.execute("""
            UPDATE suppressed_patterns SET
                current_decay=?,
                suppression_count=suppression_count + 1,
                reason=?
            WHERE category=? AND key=?
        """, (new_decay, reason, category, key))
    else:
        conn.execute("""
            INSERT INTO suppressed_patterns
                (category, key, value, original_score, current_decay, reason)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (category, key, value, original_score, decay, reason))
    conn.commit()


def get_suppressed_patterns(category: str | None = None,
                            limit: int = 30) -> list[dict]:
    conn = _get_db()
    if category:
        rows = conn.execute("""
            SELECT * FROM suppressed_patterns
            WHERE category=? ORDER BY current_decay ASC LIMIT ?
        """, (category, limit)).fetchall()
    else:
        rows = conn.execute("""
            SELECT * FROM suppressed_patterns
            ORDER BY current_decay ASC LIMIT ?
        """, (limit,)).fetchall()
    return [dict(r) for r in rows]


def archive_dead_pattern(category: str, key: str, value: str,
                         final_score: float, suppression_count: int) -> None:
    conn = _get_db()
    conn.execute("""
        INSERT OR IGNORE INTO dead_patterns
            (category, key, value, final_score, suppression_count)
        VALUES (?, ?, ?, ?, ?)
    """, (category, key, value, final_score, suppression_count))
    # Clean up from suppressed patterns once archived
    conn.execute(
        "DELETE FROM suppressed_patterns WHERE category=? AND key=?",
        (category, key)
    )
    conn.commit()


def get_dead_patterns(category: str | None = None, limit: int = 30) -> list[dict]:
    conn = _get_db()
    if category:
        rows = conn.execute("""
            SELECT * FROM dead_patterns
            WHERE category=? ORDER BY archived_at DESC LIMIT ?
        """, (category, limit)).fetchall()
    else:
        rows = conn.execute("""
            SELECT * FROM dead_patterns
            ORDER BY archived_at DESC LIMIT ?
        """, (limit,)).fetchall()
    return [dict(r) for r in rows]


def record_dominant_archetype(category: str, archetype: str,
                              dominance_pct: float, sample_size: int) -> None:
    conn = _get_db()
    conn.execute("""
        INSERT INTO dominant_archetypes
            (category, archetype, dominance_pct, sample_size)
        VALUES (?, ?, ?, ?)
    """, (category, archetype, dominance_pct, sample_size))
    conn.commit()


def get_dominant_archetypes(category: str | None = None,
                            limit: int = 20) -> list[dict]:
    conn = _get_db()
    if category:
        rows = conn.execute("""
            SELECT * FROM dominant_archetypes
            WHERE category=? ORDER BY recorded_at DESC LIMIT ?
        """, (category, limit)).fetchall()
    else:
        rows = conn.execute("""
            SELECT * FROM dominant_archetypes
            ORDER BY recorded_at DESC LIMIT ?
        """, (limit,)).fetchall()
    return [dict(r) for r in rows]


def save_topic_lineage(parent_topic: str, child_topic: str,
                       confidence: float, performance_inheritance: float) -> None:
    conn = _get_db()
    conn.execute("""
        INSERT INTO topic_lineages
            (parent_topic, child_topic, confidence, performance_inheritance)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(parent_topic, child_topic) DO UPDATE SET
            confidence = (confidence + excluded.confidence) / 2,
            performance_inheritance = (performance_inheritance + excluded.performance_inheritance) / 2
    """, (parent_topic, child_topic, confidence, performance_inheritance))
    conn.commit()


def get_topic_lineages(parent_topic: str | None = None,
                       limit: int = 30) -> list[dict]:
    conn = _get_db()
    if parent_topic:
        rows = conn.execute("""
            SELECT * FROM topic_lineages
            WHERE parent_topic=? ORDER BY performance_inheritance DESC LIMIT ?
        """, (parent_topic, limit)).fetchall()
    else:
        rows = conn.execute("""
            SELECT * FROM topic_lineages
            ORDER BY performance_inheritance DESC LIMIT ?
        """, (limit,)).fetchall()
    return [dict(r) for r in rows]


def save_execution_log(pipeline_id: str, topic: str,
                       decision_domain: str = "",
                       decision_action: str = "",
                       decision_confidence: float = 0,
                       pipeline_status: str = "completed",
                       video_id: str = "",
                       video_url: str = "",
                       error: str = "") -> None:
    conn = _get_db()
    conn.execute("""
        INSERT INTO execution_log
            (pipeline_id, topic, decision_domain, decision_action,
             decision_confidence, pipeline_status, video_id, video_url, error)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (pipeline_id, topic, decision_domain, decision_action,
          decision_confidence, pipeline_status, video_id, video_url, error))
    conn.commit()


def get_execution_log(limit: int = 20) -> list[dict]:
    conn = _get_db()
    rows = conn.execute(
        "SELECT * FROM execution_log ORDER BY executed_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


def mark_topic_published(child_topic: str) -> None:
    conn = _get_db()
    conn.execute(
        "UPDATE topic_lineages SET is_published=1 WHERE child_topic=?",
        (child_topic,)
    )
    conn.commit()


def close():
    if hasattr(_local, "conn") and _local.conn:
        _local.conn.close()
        _local.conn = None
