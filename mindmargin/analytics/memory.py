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

    conn.execute("DELETE FROM video_classifications WHERE id NOT IN (SELECT MIN(id) FROM video_classifications GROUP BY pipeline_id, video_id)")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_vc_pipeline_video ON video_classifications(pipeline_id, video_id)")

    # ── Intelligence Engine schema ──
    for sql in _INTELLIGENCE_SCHEMA:
        try:
            conn.execute(sql)
        except sqlite3.OperationalError as e:
            if "already exists" not in str(e):
                logger.warning(f"Schema: {e}")

    # ── Outcome Tracking schema ──
    for sql in _OUTCOME_SCHEMA:
        try:
            conn.execute(sql)
        except sqlite3.OperationalError as e:
            if "already exists" not in str(e):
                logger.warning(f"Schema: {e}")

    # ── Experiment Engine schema ──
    for sql in _EXPERIMENT_SCHEMA:
        try:
            conn.execute(sql)
        except sqlite3.OperationalError as e:
            if "already exists" not in str(e):
                logger.warning(f"Schema: {e}")

    # ── Weekly Planner schema ──
    for sql in _WEEKLY_PLAN_SCHEMA:
        try:
            conn.execute(sql)
        except sqlite3.OperationalError as e:
            if "already exists" not in str(e):
                logger.warning(f"Schema: {e}")

    # ── Knowledge Graph schema ──
    for sql in _KNOWLEDGE_GRAPH_SCHEMA:
        try:
            conn.execute(sql)
        except sqlite3.OperationalError as e:
            if "already exists" not in str(e):
                logger.warning(f"Schema: {e}")

    # ── Prediction Horizon schema ──
    for sql in _PREDICTION_SCHEMA:
        try:
            conn.execute(sql)
        except sqlite3.OperationalError as e:
            if "already exists" not in str(e):
                logger.warning(f"Schema: {e}")


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


def update_hook_title_performance(pipeline_id: str, stats: dict) -> None:
    """Update hooks and titles tables with actual CTR/retention from analytics.

    Called after analytics collection to close the learning loop.
    This is an approximation — all hooks for the pipeline get the same
    actual metrics since we cannot distinguish which hook was seen by each viewer.
    """
    conn = _get_db()
    views = stats.get("views", 0) or 0
    impressions = stats.get("impressions", 0) or 0
    ctr_raw = stats.get("ctr", None)

    if ctr_raw is not None:
        ctr_val = ctr_raw if ctr_raw <= 1 else ctr_raw / 100
    elif impressions > 0:
        ctr_val = views / impressions
    else:
        ctr_val = 0.0

    avg_view_pct = stats.get("averageViewPercentage", None)
    if avg_view_pct is not None and avg_view_pct > 0:
        retention = round(avg_view_pct / 100, 4)
    else:
        retention = 0.0

    actual_ctr = round(ctr_val, 4)

    conn.execute(
        "UPDATE hooks SET actual_ctr=?, actual_retention=?, used=1 WHERE pipeline_id=?",
        (actual_ctr, retention, pipeline_id),
    )
    conn.execute(
        "UPDATE titles SET ctr=?, views=?, used=1 WHERE pipeline_id=? AND rank=0",
        (actual_ctr, views, pipeline_id),
    )
    conn.commit()


def get_analytics_history(limit: int = 200) -> list[dict]:
    """Return recent analytics entries across all videos."""
    conn = _get_db()
    rows = conn.execute(
        "SELECT * FROM analytics ORDER BY collected_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


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
        ON CONFLICT(pipeline_id, video_id) DO UPDATE SET
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


def is_successful_publish(log: dict) -> bool:
    """Canonical single source of truth: did this execution_log entry represent a real YouTube upload?

    Returns True only when ALL three conditions hold:
      1. pipeline_status == 'completed'   (the pipeline actually ran)
      2. video_id is non-empty            (a real YouTube video was produced)
      3. error is empty                   (no failure occurred)

    Every call site in the codebase that needs to count a successful publish
    MUST use this function.  Direct checks of log.get('error') == '' or
    bool(log.get('video_id')) outside this function are forbidden unless
    explicitly documented with a reason.
    """
    vid = log.get("video_id")
    return (log.get("pipeline_status") == "completed"
            and bool(vid.strip() if isinstance(vid, str) else vid)
            and not log.get("error"))


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


# ════════════════════════════════════════════════════════════════
# Intelligence Engine Schema & Memory Functions
# ════════════════════════════════════════════════════════════════

_EXPERIMENT_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS experiments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        experiment_id TEXT UNIQUE NOT NULL,
        hypothesis TEXT NOT NULL,
        experiment_type TEXT NOT NULL,
        topic TEXT NOT NULL,
        variant_a TEXT NOT NULL,
        variant_b TEXT NOT NULL,
        expected_gain REAL DEFAULT 0,
        affected_metric TEXT DEFAULT 'views',
        confidence REAL DEFAULT 0,
        status TEXT DEFAULT 'draft',
        control_pipeline_id TEXT DEFAULT '',
        treatment_pipeline_id TEXT DEFAULT '',
        control_metric REAL DEFAULT 0,
        treatment_metric REAL DEFAULT 0,
        winner TEXT DEFAULT '',
        statistical_confidence REAL DEFAULT 0,
        sample_size INTEGER DEFAULT 0,
        recommendation TEXT DEFAULT '',
        created_at TEXT DEFAULT (datetime('now')),
        completed_at TEXT
    )""",
]

_WEEKLY_PLAN_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS weekly_plans (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        week_start TEXT NOT NULL,
        data TEXT NOT NULL,
        created_at TEXT DEFAULT (datetime('now'))
    )""",
]

_KNOWLEDGE_GRAPH_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS topic_keywords (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        topic TEXT NOT NULL,
        keyword TEXT NOT NULL,
        weight REAL DEFAULT 1.0,
        created_at TEXT DEFAULT (datetime('now')),
        UNIQUE(topic, keyword)
    )""",
    """CREATE TABLE IF NOT EXISTS topic_relationships (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_topic TEXT NOT NULL,
        target_topic TEXT NOT NULL,
        relationship_type TEXT DEFAULT 'related',
        strength REAL DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now')),
        UNIQUE(source_topic, target_topic)
    )""",
    """CREATE TABLE IF NOT EXISTS audience_topics (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        topic TEXT NOT NULL,
        audience_overlap REAL DEFAULT 0,
        engagement_affinity REAL DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now')),
        UNIQUE(topic)
    )""",
]

_PREDICTION_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS prediction_forecasts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        topic TEXT NOT NULL,
        forecast_date TEXT NOT NULL,
        window_days INTEGER NOT NULL,
        expected_score REAL DEFAULT 0,
        confidence REAL DEFAULT 0,
        uncertainty REAL DEFAULT 0,
        trend_momentum REAL DEFAULT 0,
        base_score REAL DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now')),
        UNIQUE(topic, forecast_date, window_days)
    )""",
]

_OUTCOME_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS decision_outcomes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        topic TEXT NOT NULL,
        pipeline_id TEXT NOT NULL,
        opportunity_score REAL DEFAULT 0,
        actual_score REAL DEFAULT 0,
        prediction_error REAL DEFAULT 0,
        views INTEGER DEFAULT 0,
        ctr REAL DEFAULT 0,
        watch_time_s REAL DEFAULT 0,
        retention REAL DEFAULT 0,
        engagement_rate REAL DEFAULT 0,
        source TEXT DEFAULT '',
        scored_at TEXT,
        outcome_at TEXT,
        created_at TEXT DEFAULT (datetime('now')),
        UNIQUE(topic, pipeline_id)
    )""",
    """CREATE TABLE IF NOT EXISTS prediction_errors (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        outcome_id INTEGER NOT NULL,
        component TEXT NOT NULL,
        weight REAL DEFAULT 0,
        component_score REAL DEFAULT 0,
        actual_contribution REAL DEFAULT 0,
        error REAL DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now')),
        FOREIGN KEY (outcome_id) REFERENCES decision_outcomes(id)
    )""",
    """CREATE TABLE IF NOT EXISTS scoring_weights (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        component TEXT UNIQUE NOT NULL,
        weight REAL NOT NULL,
        updated_at TEXT DEFAULT (datetime('now'))
    )""",
]

_INTELLIGENCE_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS trend_sources (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source TEXT NOT NULL,
        topic TEXT NOT NULL,
        trend_score REAL DEFAULT 0,
        competition REAL DEFAULT 0,
        novelty REAL DEFAULT 0,
        seasonality REAL DEFAULT 0,
        confidence REAL DEFAULT 0,
        raw_data TEXT DEFAULT '',
        collected_at TEXT DEFAULT (datetime('now')),
        UNIQUE(source, topic)
    )""",
    """CREATE TABLE IF NOT EXISTS channel_memory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        pipeline_id TEXT NOT NULL,
        topic TEXT NOT NULL,
        topic_hash TEXT NOT NULL,
        title TEXT DEFAULT '',
        hook TEXT DEFAULT '',
        thumbnail_style TEXT DEFAULT '',
        narrative_style TEXT DEFAULT '',
        keywords TEXT DEFAULT '',
        performance_score REAL DEFAULT 0,
        created_at TEXT DEFAULT (datetime('now')),
        UNIQUE(pipeline_id)
    )""",
    """CREATE TABLE IF NOT EXISTS intelligence_rules (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        category TEXT NOT NULL,
        key TEXT NOT NULL,
        value TEXT NOT NULL,
        score REAL DEFAULT 0,
        sample_size INTEGER DEFAULT 1,
        confidence REAL DEFAULT 0,
        dynamic INTEGER DEFAULT 1,
        updated_at TEXT DEFAULT (datetime('now')),
        UNIQUE(category, key)
    )""",
    """CREATE TABLE IF NOT EXISTS daily_strategies (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        strategy_date TEXT NOT NULL,
        data TEXT NOT NULL,
        created_at TEXT DEFAULT (datetime('now'))
    )""",
    """CREATE TABLE IF NOT EXISTS weekly_reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        week_start TEXT NOT NULL,
        week_end TEXT NOT NULL,
        data TEXT NOT NULL,
        created_at TEXT DEFAULT (datetime('now'))
    )""",
    """CREATE TABLE IF NOT EXISTS opportunity_scores (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        topic TEXT UNIQUE NOT NULL,
        source TEXT DEFAULT '',
        opportunity_score REAL DEFAULT 0,
        trend_score REAL DEFAULT 0,
        competition REAL DEFAULT 0,
        novelty REAL DEFAULT 0,
        seasonality REAL DEFAULT 0,
        audience_match REAL DEFAULT 0,
        evergreen_score REAL DEFAULT 0,
        historical_performance REAL DEFAULT 0,
        confidence REAL DEFAULT 0,
        scored_at TEXT DEFAULT (datetime('now'))
    )""",
]


# ── Trend Sources ──

def save_trend_source(source: str, topic: str, trend_score: float = 0,
                       competition: float = 0, novelty: float = 0,
                       seasonality: float = 0, confidence: float = 0,
                       raw_data: str = "") -> None:
    conn = _get_db()
    conn.execute("""
        INSERT INTO trend_sources (source, topic, trend_score, competition, novelty,
                                    seasonality, confidence, raw_data)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(source, topic) DO UPDATE SET
            trend_score=excluded.trend_score, competition=excluded.competition,
            novelty=excluded.novelty, seasonality=excluded.seasonality,
            confidence=excluded.confidence, raw_data=excluded.raw_data,
            collected_at=datetime('now')
    """, (source, topic, trend_score, competition, novelty,
          seasonality, confidence, raw_data))
    conn.commit()


def get_trend_sources(limit: int = 50, min_confidence: float = 0.0) -> list[dict]:
    conn = _get_db()
    rows = conn.execute("""
        SELECT * FROM trend_sources
        WHERE confidence >= ?
        ORDER BY trend_score DESC
        LIMIT ?
    """, (min_confidence, limit)).fetchall()
    return [dict(r) for r in rows]


# ── Channel Memory ──

def save_channel_memory(pipeline_id: str, topic: str, topic_hash: str,
                         title: str = "", hook: str = "",
                         thumbnail_style: str = "", narrative_style: str = "",
                         keywords: str = "", performance_score: float = 0) -> None:
    conn = _get_db()
    conn.execute("""
        INSERT INTO channel_memory (pipeline_id, topic, topic_hash, title, hook,
                                     thumbnail_style, narrative_style, keywords,
                                     performance_score)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(pipeline_id) DO UPDATE SET
            topic=excluded.topic, topic_hash=excluded.topic_hash,
            title=excluded.title, hook=excluded.hook,
            thumbnail_style=excluded.thumbnail_style,
            narrative_style=excluded.narrative_style,
            keywords=excluded.keywords,
            performance_score=excluded.performance_score
    """, (pipeline_id, topic, topic_hash, title, hook,
          thumbnail_style, narrative_style, keywords, performance_score))
    conn.commit()


def get_channel_memory(limit: int = 100) -> list[dict]:
    conn = _get_db()
    rows = conn.execute("""
        SELECT * FROM channel_memory ORDER BY created_at DESC LIMIT ?
    """, (limit,)).fetchall()
    return [dict(r) for r in rows]


def get_memory_topic_hashes() -> set[str]:
    conn = _get_db()
    rows = conn.execute("SELECT topic_hash FROM channel_memory").fetchall()
    return {r["topic_hash"] for r in rows}


# ── Intelligence Rules ──

def save_intelligence_rule(category: str, key: str, value: str,
                            score: float = 0, sample_size: int = 1,
                            confidence: float = 0, dynamic: bool = True) -> None:
    conn = _get_db()
    conn.execute("""
        INSERT INTO intelligence_rules (category, key, value, score, sample_size,
                                         confidence, dynamic)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(category, key) DO UPDATE SET
            value=excluded.value, score=excluded.score,
            sample_size=excluded.sample_size, confidence=excluded.confidence,
            dynamic=excluded.dynamic, updated_at=datetime('now')
    """, (category, key, value, score, sample_size, confidence, int(dynamic)))
    conn.commit()


def get_intelligence_rules(category: str = "", min_confidence: float = 0) -> list[dict]:
    conn = _get_db()
    if category:
        rows = conn.execute("""
            SELECT * FROM intelligence_rules
            WHERE category = ? AND confidence >= ?
            ORDER BY score DESC
        """, (category, min_confidence)).fetchall()
    else:
        rows = conn.execute("""
            SELECT * FROM intelligence_rules WHERE confidence >= ?
            ORDER BY score DESC
        """, (min_confidence,)).fetchall()
    return [dict(r) for r in rows]


def get_all_intelligence_rules() -> list[dict]:
    conn = _get_db()
    rows = conn.execute(
        "SELECT * FROM intelligence_rules ORDER BY category, score DESC"
    ).fetchall()
    return [dict(r) for r in rows]


# ── Daily Strategies ──

def save_daily_strategy(strategy_date: str, data: dict) -> None:
    conn = _get_db()
    conn.execute(
        "INSERT INTO daily_strategies (strategy_date, data) VALUES (?, ?)",
        (strategy_date, json.dumps(data, default=str))
    )
    conn.commit()


def get_daily_strategies(limit: int = 7) -> list[dict]:
    conn = _get_db()
    rows = conn.execute(
        "SELECT * FROM daily_strategies ORDER BY strategy_date DESC LIMIT ?",
        (limit,)
    ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        try:
            d["data"] = json.loads(d["data"])
        except (json.JSONDecodeError, TypeError):
            pass
        result.append(d)
    return result


# ── Weekly Reports ──

def save_weekly_report(week_start: str, week_end: str, data: dict) -> None:
    conn = _get_db()
    conn.execute(
        "INSERT INTO weekly_reports (week_start, week_end, data) VALUES (?, ?, ?)",
        (week_start, week_end, json.dumps(data, default=str))
    )
    conn.commit()


def get_weekly_reports(limit: int = 4) -> list[dict]:
    conn = _get_db()
    rows = conn.execute(
        "SELECT * FROM weekly_reports ORDER BY week_start DESC LIMIT ?", (limit,)
    ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        try:
            d["data"] = json.loads(d["data"])
        except (json.JSONDecodeError, TypeError):
            pass
        result.append(d)
    return result


# ── Opportunity Scores ──

def save_opportunity(topic: str, source: str = "", opportunity_score: float = 0,
                      trend_score: float = 0, competition: float = 0,
                      novelty: float = 0, seasonality: float = 0,
                      audience_match: float = 0, evergreen_score: float = 0,
                      historical_performance: float = 0, confidence: float = 0) -> None:
    conn = _get_db()
    conn.execute("""
        INSERT INTO opportunity_scores (topic, source, opportunity_score, trend_score,
                                         competition, novelty, seasonality,
                                         audience_match, evergreen_score,
                                         historical_performance, confidence)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(topic) DO UPDATE SET
            source=excluded.source, opportunity_score=excluded.opportunity_score,
            trend_score=excluded.trend_score, competition=excluded.competition,
            novelty=excluded.novelty, seasonality=excluded.seasonality,
            audience_match=excluded.audience_match,
            evergreen_score=excluded.evergreen_score,
            historical_performance=excluded.historical_performance,
            confidence=excluded.confidence,
            scored_at=datetime('now')
    """, (topic, source, opportunity_score, trend_score, competition,
          novelty, seasonality, audience_match, evergreen_score,
          historical_performance, confidence))
    conn.commit()


def get_opportunities(min_score: float = 0, limit: int = 50) -> list[dict]:
    conn = _get_db()
    rows = conn.execute("""
        SELECT * FROM opportunity_scores
        WHERE opportunity_score >= ?
        ORDER BY opportunity_score DESC
        LIMIT ?
    """, (min_score, limit)).fetchall()
    return [dict(r) for r in rows]


def get_top_opportunities(n: int = 20) -> list[dict]:
    return get_opportunities(min_score=0, limit=n)


# ── Outcome Tracking ──

def save_outcome(topic: str, pipeline_id: str, opportunity_score: float,
                 actual_score: float, prediction_error: float,
                 views: int = 0, ctr: float = 0, watch_time_s: float = 0,
                 retention: float = 0, engagement_rate: float = 0,
                 source: str = "", scored_at: str = "",
                 outcome_at: str = "") -> int:
    conn = _get_db()
    cur = conn.execute("""
        INSERT INTO decision_outcomes
            (topic, pipeline_id, opportunity_score, actual_score, prediction_error,
             views, ctr, watch_time_s, retention, engagement_rate,
             source, scored_at, outcome_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(topic, pipeline_id) DO UPDATE SET
            actual_score=excluded.actual_score,
            prediction_error=excluded.prediction_error,
            views=excluded.views, ctr=excluded.ctr,
            watch_time_s=excluded.watch_time_s, retention=excluded.retention,
            engagement_rate=excluded.engagement_rate,
            outcome_at=excluded.outcome_at
    """, (topic, pipeline_id, opportunity_score, actual_score, prediction_error,
          views, ctr, watch_time_s, retention, engagement_rate,
          source, scored_at, outcome_at))
    conn.commit()
    return cur.lastrowid or 0


def get_outcomes(limit: int = 100, min_error: float | None = None) -> list[dict]:
    conn = _get_db()
    query = "SELECT * FROM decision_outcomes"
    params: list = []
    if min_error is not None:
        query += " WHERE ABS(prediction_error) >= ?"
        params.append(min_error)
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def save_prediction_error(outcome_id: int, component: str, weight: float,
                           component_score: float, actual_contribution: float,
                           error: float) -> None:
    conn = _get_db()
    conn.execute("""
        INSERT INTO prediction_errors
            (outcome_id, component, weight, component_score,
             actual_contribution, error)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (outcome_id, component, weight, component_score,
          actual_contribution, error))
    conn.commit()


def get_prediction_errors(outcome_id: int | None = None,
                           component: str | None = None,
                           limit: int = 500) -> list[dict]:
    conn = _get_db()
    clauses = []
    params: list = []
    if outcome_id is not None:
        clauses.append("outcome_id=?")
        params.append(outcome_id)
    if component is not None:
        clauses.append("component=?")
        params.append(component)
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    rows = conn.execute(
        f"SELECT * FROM prediction_errors {where} ORDER BY created_at DESC LIMIT ?",
        [*params, limit],
    ).fetchall()
    return [dict(r) for r in rows]


# ── Dynamic Scoring Weights ──

def get_scoring_weights() -> dict[str, float]:
    conn = _get_db()
    rows = conn.execute("SELECT component, weight FROM scoring_weights").fetchall()
    return {r["component"]: r["weight"] for r in rows}


def set_scoring_weight(component: str, weight: float) -> None:
    conn = _get_db()
    conn.execute("""
        INSERT INTO scoring_weights (component, weight, updated_at)
        VALUES (?, ?, datetime('now'))
        ON CONFLICT(component) DO UPDATE SET
            weight=excluded.weight, updated_at=datetime('now')
    """, (component, weight))
    conn.commit()


def reset_scoring_weights(weights: dict[str, float]) -> None:
    conn = _get_db()
    for component, weight in weights.items():
        conn.execute("""
            INSERT INTO scoring_weights (component, weight, updated_at)
            VALUES (?, ?, datetime('now'))
            ON CONFLICT(component) DO UPDATE SET
                weight=excluded.weight, updated_at=datetime('now')
        """, (component, weight))
    conn.commit()


def get_weight_history(limit: int = 50) -> list[dict]:
    conn = _get_db()
    rows = conn.execute(
        "SELECT * FROM scoring_weights ORDER BY updated_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


# ── Experiment Engine (Phase 3) ──

def save_experiment(experiment_id: str, hypothesis: str, experiment_type: str,
                     topic: str, variant_a: str, variant_b: str,
                     expected_gain: float = 0, affected_metric: str = "views",
                     confidence: float = 0) -> None:
    conn = _get_db()
    conn.execute("""
        INSERT OR REPLACE INTO experiments
            (experiment_id, hypothesis, experiment_type, topic,
             variant_a, variant_b, expected_gain, affected_metric, confidence)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (experiment_id, hypothesis, experiment_type, topic,
          variant_a, variant_b, expected_gain, affected_metric, confidence))
    conn.commit()


def get_experiment(experiment_id: str) -> dict | None:
    conn = _get_db()
    rows = conn.execute(
        "SELECT * FROM experiments WHERE experiment_id=?",
        (experiment_id,),
    ).fetchall()
    return dict(rows[0]) if rows else None


def get_experiments(experiment_type: str = "", status: str = "",
                     limit: int = 50) -> list[dict]:
    conn = _get_db()
    clauses = []
    params: list = []
    if experiment_type:
        clauses.append("experiment_type=?")
        params.append(experiment_type)
    if status:
        clauses.append("status=?")
        params.append(status)
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    rows = conn.execute(
        f"SELECT * FROM experiments {where} ORDER BY created_at DESC LIMIT ?",
        [*params, limit],
    ).fetchall()
    return [dict(r) for r in rows]


def complete_experiment(experiment_id: str, winner: str,
                         statistical_confidence: float = 0,
                         sample_size: int = 0, recommendation: str = "",
                         control_metric: float = 0,
                         treatment_metric: float = 0) -> None:
    conn = _get_db()
    conn.execute("""
        UPDATE experiments SET status='completed', winner=?, statistical_confidence=?,
            sample_size=?, recommendation=?, control_metric=?, treatment_metric=?,
            completed_at=datetime('now')
        WHERE experiment_id=?
    """, (winner, statistical_confidence, sample_size, recommendation,
          control_metric, treatment_metric, experiment_id))
    conn.commit()


def activate_experiment(experiment_id: str, control_pipeline_id: str,
                         treatment_pipeline_id: str) -> None:
    conn = _get_db()
    conn.execute("""
        UPDATE experiments SET status='active',
            control_pipeline_id=?, treatment_pipeline_id=?
        WHERE experiment_id=?
    """, (control_pipeline_id, treatment_pipeline_id, experiment_id))
    conn.commit()


def get_active_experiments(limit: int = 20) -> list[dict]:
    return get_experiments(status="active", limit=limit)


# ── Weekly Planner (Phase 6) ──

def save_weekly_plan(week_start: str, data: dict) -> None:
    conn = _get_db()
    conn.execute("""
        INSERT OR REPLACE INTO weekly_plans (week_start, data)
        VALUES (?, ?)
    """, (week_start, json.dumps(data)))
    conn.commit()


def get_weekly_plans(limit: int = 4) -> list[dict]:
    conn = _get_db()
    rows = conn.execute(
        "SELECT * FROM weekly_plans ORDER BY week_start DESC LIMIT ?",
        (limit,),
    ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        try:
            d["data"] = json.loads(d["data"])
        except (json.JSONDecodeError, TypeError):
            pass
        result.append(d)
    return result


# ── Knowledge Graph (Phase 7) ──

def save_topic_keyword(topic: str, keyword: str, weight: float = 1.0) -> None:
    conn = _get_db()
    conn.execute("""
        INSERT OR REPLACE INTO topic_keywords (topic, keyword, weight)
        VALUES (?, ?, ?)
    """, (topic, keyword, weight))
    conn.commit()


def get_topic_keywords(topic: str = "", limit: int = 100) -> list[dict]:
    conn = _get_db()
    if topic:
        rows = conn.execute(
            "SELECT * FROM topic_keywords WHERE topic=? ORDER BY weight DESC LIMIT ?",
            (topic, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM topic_keywords ORDER BY weight DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def save_topic_relationship(source_topic: str, target_topic: str,
                             relationship_type: str = "related",
                             strength: float = 0) -> None:
    conn = _get_db()
    conn.execute("""
        INSERT OR REPLACE INTO topic_relationships
            (source_topic, target_topic, relationship_type, strength)
        VALUES (?, ?, ?, ?)
    """, (source_topic, target_topic, relationship_type, strength))
    conn.commit()


def get_topic_relationships(topic: str = "", relationship_type: str = "",
                             limit: int = 100) -> list[dict]:
    conn = _get_db()
    clauses = []
    params: list = []
    if topic:
        clauses.append("(source_topic=? OR target_topic=?)")
        params.extend([topic, topic])
    if relationship_type:
        clauses.append("relationship_type=?")
        params.append(relationship_type)
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    rows = conn.execute(
        f"SELECT * FROM topic_relationships {where} ORDER BY strength DESC LIMIT ?",
        [*params, limit],
    ).fetchall()
    return [dict(r) for r in rows]


def save_audience_topic(topic: str, audience_overlap: float = 0,
                         engagement_affinity: float = 0) -> None:
    conn = _get_db()
    conn.execute("""
        INSERT OR REPLACE INTO audience_topics
            (topic, audience_overlap, engagement_affinity)
        VALUES (?, ?, ?)
    """, (topic, audience_overlap, engagement_affinity))
    conn.commit()


def get_audience_topics(limit: int = 100) -> list[dict]:
    conn = _get_db()
    rows = conn.execute(
        "SELECT * FROM audience_topics ORDER BY engagement_affinity DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


# ── Prediction Horizon (Phase 8) ──

def save_forecast(topic: str, forecast_date: str, window_days: int,
                   expected_score: float, confidence: float = 0,
                   uncertainty: float = 0, trend_momentum: float = 0,
                   base_score: float = 0) -> None:
    conn = _get_db()
    conn.execute("""
        INSERT OR REPLACE INTO prediction_forecasts
            (topic, forecast_date, window_days, expected_score, confidence,
             uncertainty, trend_momentum, base_score)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (topic, forecast_date, window_days, expected_score, confidence,
          uncertainty, trend_momentum, base_score))
    conn.commit()


def get_forecasts(topic: str = "", window_days: int = 0,
                   limit: int = 100) -> list[dict]:
    conn = _get_db()
    clauses = []
    params: list = []
    if topic:
        clauses.append("topic=?")
        params.append(topic)
    if window_days > 0:
        clauses.append("window_days=?")
        params.append(window_days)
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    rows = conn.execute(
        f"SELECT * FROM prediction_forecasts {where} ORDER BY created_at DESC LIMIT ?",
        [*params, limit],
    ).fetchall()
    return [dict(r) for r in rows]


def get_latest_forecasts(window_days: int = 7) -> list[dict]:
    conn = _get_db()
    rows = conn.execute("""
        SELECT * FROM prediction_forecasts
        WHERE window_days=? AND forecast_date=date('now')
        ORDER BY expected_score DESC LIMIT 20
    """, (window_days,)).fetchall()
    return [dict(r) for r in rows]
