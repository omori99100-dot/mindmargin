"""A/B Evolution Layer: multi-phase title/thumbnail testing with winner selection.

Implements the A/B rotation lifecycle:
  Hatch → Seed → Active → Collect → Judge → Restore → Learn

Each published video gets:
  - 3 alternative titles (from existing title generation)
  - 3 alternative thumbnail styles (from existing thumbnail generation)

The rotation engine progressively swaps metadata variants, collects
analytics, and restores the statistically winning combination.
"""

import logging
import time
from datetime import datetime, timedelta
from typing import Optional

from mindmargin.analytics import memory
from mindmargin.analytics.memory import (
    get_pipeline_history, save_best_practice,
    get_ab_variants, save_ab_variant, get_pending_ab_tests,
    get_active_ab_tests, activate_ab_variant, complete_ab_variant,
    update_ab_metrics, set_ab_winner, set_ab_restored,
    get_ab_winner_for_pipeline, get_all_completed_ab_tests,
)
from mindmargin.integrations.youtube import update_video_metadata, _get_authenticated_service

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────

AB_CONFIG = {
    "days_before_first_rotation": 1,
    "days_between_rotations": 2,
    "min_impressions_for_decision": 10,
    "min_ctr_lead_to_declare_winner": 0.5,
    "max_active_tests_per_video": 3,
    "thumbnail_test_days": 3,
}

# ──────────────────────────────────────────────
# Step 1: Seed variants into the database
# ──────────────────────────────────────────────

def seed_variants(pipeline_id: str, video_id: str) -> int:
    """Seed A/B test variants from published titles and thumbnails.

    Pulls from the existing titles and thumbnails tables which were
    populated during publish. The original published title/thumbnail
    is variant_index=0; generated alternatives are 1-3.
    """
    from mindmargin.analytics.memory import _get_db
    conn = _get_db()
    seeded = 0

    # Grab up to 3 alternative titles (rank>0 excludes the published original)
    title_rows = conn.execute("""
        SELECT title FROM titles
        WHERE pipeline_id = ? AND rank > 0
        ORDER BY rank ASC LIMIT 3
    """, (pipeline_id,)).fetchall()

    for i, row in enumerate(title_rows, start=1):
        save_ab_variant(pipeline_id, video_id, "title", i, row["title"])
        seeded += 1

    # Grab alternative thumbnail styles (skip first style = the one uploaded)
    thumb_rows = conn.execute("""
        SELECT style, text_overlay FROM thumbnails
        WHERE pipeline_id = ?
        ORDER BY id ASC
    """, (pipeline_id,)).fetchall()

    for i, row in enumerate(thumb_rows[1:4], start=1):
        value = f"{row['style']}|{row['text_overlay']}"
        save_ab_variant(pipeline_id, video_id, "thumbnail", i, value)
        seeded += 1

    if seeded:
        logger.info(f"Seed: {seeded} AB variants for {pipeline_id} ({video_id})")
    return seeded


# ──────────────────────────────────────────────
# Step 2-3: Rotation engine
# ──────────────────────────────────────────────

def _days_since_publish(pipeline_id: str) -> float:
    """Calculate days since the pipeline's video was published."""
    from mindmargin.analytics.memory import _get_db
    conn = _get_db()
    row = conn.execute("""
        SELECT published_at, created_at FROM pipelines WHERE id = ?
    """, (pipeline_id,)).fetchone()
    if not row:
        return 999.0
    ts = row["published_at"] or row["created_at"]
    if not ts:
        return 999.0
    try:
        dt = datetime.strptime(ts[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return 999.0
    return (datetime.utcnow() - dt).total_seconds() / 86400.0


def _fetch_video_analytics(video_id: str) -> dict:
    """Fetch current CTR, impressions, watch time via public + analytics APIs."""
    from mindmargin.integrations.youtube import get_video_stats, get_analytics
    stats = get_video_stats(video_id)
    if stats.get("status") != "completed":
        return {"impressions": 0, "ctr": 0.0, "watch_time_s": 0.0, "views": 0}

    views = stats.get("views", 0)
    likes = stats.get("likes", 0)
    impressions_val = stats.get("impressions", 0) or 0

    # Try analytics API for deeper metrics
    deep = get_analytics(video_id,
                         metrics=["views", "averageViewDuration", "likes", "shares"])
    watch_time = 0.0
    if deep.get("status") == "completed" and deep.get("data"):
        watch_time = deep["data"].get("averageViewDuration", 0) or 0
        impressions_val = deep["data"].get("impressions", impressions_val) or impressions_val

    return {
        "impressions": impressions_val,
        "ctr": (likes / max(views, 1)) * 100.0,
        "watch_time_s": watch_time,
        "views": views,
    }


def has_sufficient_signal(impressions: int, views: int = 0) -> bool:
    """Check if an A/B variant has enough signal for evaluation.

    Requires impressions >= 100 OR views >= 30 for statistically meaningful
    CTR data.  The views fallback handles the case where YouTube Data API
    v3 does not expose impressions.
    """
    return impressions >= 100 or views >= 30


def _find_thumbnail_path(pipeline_id: str, style: str) -> Optional[str]:
    """Find a thumbnail file path from the DB, checking if file still exists."""
    conn = memory._get_db()
    rows = conn.execute("""
        SELECT path FROM thumbnails
        WHERE pipeline_id = ? AND style = ?
        ORDER BY id ASC LIMIT 5
    """, (pipeline_id, style)).fetchall()
    from os.path import exists
    for r in rows:
        p = r["path"]
        if p and exists(p):
            return p
    return None


def _regenerate_thumbnail(pipeline_id: str, style: str, video_id: str) -> bool:
    """Regenerate a single thumbnail variant if original file is gone."""
    try:
        from mindmargin.agents.thumbnail import ThumbnailAgent
        from pathlib import Path
        import json

        # Look up pipeline info from DB
        conn = memory._get_db()
        row = conn.execute("""
            SELECT topic, video_path FROM pipelines WHERE id = ?
        """, (pipeline_id,)).fetchone()
        if not row:
            return False
        topic = row["topic"]
        video_path = row["video_path"]
        if not video_path:
            return False

        # Derive output directory from video_path
        out_dir = Path(video_path).parent.parent
        script_path = out_dir / "script" / "script.json"
        if not script_path.exists():
            return False
        script_data = json.loads(script_path.read_text(encoding="utf-8"))
        if not script_data.get("titles"):
            script_data["titles"] = [topic]
        if not script_data.get("seo"):
            script_data["seo"] = {"thumbnail_text": topic[:60]}

        agent = ThumbnailAgent()
        agent.run(topic, pipeline_id, script_data)

        regenerated = _find_thumbnail_path(pipeline_id, style)
        if regenerated:
            yt = _get_authenticated_service()
            if yt:
                yt.thumbnails().set(
                    videoId=video_id, media_body=regenerated
                ).execute()
                logger.info(f"Regenerated thumbnail {style} for {video_id}")
                return True
    except Exception as e:
        logger.warning(f"Thumbnail regeneration failed: {e}")
    return False


def _rotate_metadata(video_id: str, variant: dict) -> bool:
    """Swap a video's metadata to a specific test variant.

    Only rotates title or thumbnail. Description and tags are never
    modified to avoid spam signals.
    """
    vtype = variant["variant_type"]
    vvalue = variant["variant_value"]

    try:
        if vtype == "title":
            result = update_video_metadata(
                video_id=video_id,
                title=vvalue[:100],
            )
            if result.get("status") == "completed":
                logger.info(f"Rotated title -> '{vvalue[:60]}' for {video_id}")
                return True
            logger.warning(f"Title rotation failed for {video_id}: {result}")
            return False

        elif vtype == "thumbnail":
            style = vvalue.split("|")[0] if "|" in vvalue else vvalue
            thumb_path = _find_thumbnail_path(variant["pipeline_id"], style)
            if thumb_path:
                yt = _get_authenticated_service()
                if yt:
                    yt.thumbnails().set(
                        videoId=video_id, media_body=thumb_path
                    ).execute()
                    logger.info(f"Rotated thumbnail -> {style} for {video_id}")
                    return True
            # Fallback: try to regenerate thumbnail
            if _regenerate_thumbnail(variant["pipeline_id"], style, video_id):
                return True
            logger.warning(f"Thumbnail unavailable for {video_id} style={style}")
            return False

    except Exception as e:
        logger.error(f"Rotation failed for {video_id}: {e}")
        return False


# ──────────────────────────────────────────────
# Step 4: Winner selection
# ──────────────────────────────────────────────

def _select_winner(candidates: list[dict]) -> Optional[dict]:
    """Deterministic winner selection.

    PRIMARY: CTR (higher wins)
    SECONDARY: Watch time (higher breaks ties)
    TIE: First deployed wins
    """
    if not candidates:
        return None

    scored = []
    for c in candidates:
        ctr = c.get("ctr", 0) or 0
        wt = c.get("watch_time_s", 0) or 0
        scored.append((ctr, wt, c["variant_index"], c))

    scored.sort(key=lambda x: (-x[0], -x[1], x[2]))
    return scored[0][3]


# ──────────────────────────────────────────────
# Step 5: Learning feedback
# ──────────────────────────────────────────────

def _feed_winner_back(winner: dict) -> None:
    """Feed winning variants back into best_practices + OptimizationEngine."""
    vtype = winner["variant_type"]
    vvalue = winner["variant_value"]
    ctr = winner.get("ctr", 0) or 0
    wt = winner.get("watch_time_s", 0) or 0

    if vtype == "title":
        save_best_practice(
            "ab_title_winner",
            vvalue[:80],
            f"AB-winning title (CTR: {ctr:.1f}%, watch: {wt:.0f}s)",
            ctr * 10,
        )
        logger.info(f"Learned title winner: '{vvalue[:60]}' CTR={ctr:.1f}")

    elif vtype == "thumbnail":
        style = vvalue.split("|")[0] if "|" in vvalue else vvalue
        save_best_practice(
            "ab_thumbnail_winner",
            style,
            f"AB-winning thumbnail style '{style}' (CTR: {ctr:.1f}%)",
            ctr * 10,
        )
        logger.info(f"Learned thumbnail winner: {style} CTR={ctr:.1f}")


# ──────────────────────────────────────────────
# Main rotation cycle
# ──────────────────────────────────────────────

def run_ab_rotation_cycle(dry_run: bool = False) -> dict:
    """Execute one full A/B rotation cycle across all eligible pipelines.

    Steps:
      1. Collect active test analytics
      2. Check if active tests are ready to complete
      3. Select winners for completed tests
      4. Restore winning variants
      5. Feed winners back into learning
      6. Activate next pending variants

    Returns summary dict.
    """
    actions = []

    # ── Collect analytics for active tests ──
    active = get_active_ab_tests()
    for test in active:
        metrics = _fetch_video_analytics(test["video_id"])
        update_ab_metrics(test["id"],
                          metrics["impressions"],
                          metrics["ctr"],
                          metrics["watch_time_s"])

        # Check if test has run long enough
        start = test.get("test_start_time")
        if start:
            try:
                started = datetime.strptime(start[:19], "%Y-%m-%d %H:%M:%S")
                elapsed_days = (datetime.utcnow() - started).total_seconds() / 86400.0
            except ValueError:
                elapsed_days = 0.0
        else:
            elapsed_days = 0.0

        required_days = (
            AB_CONFIG["days_between_rotations"]
            if test["variant_type"] == "title"
            else AB_CONFIG["thumbnail_test_days"]
        )

        enough_time = elapsed_days >= required_days
        age = _days_since_publish(test["pipeline_id"])
        signal_ok = has_sufficient_signal(metrics["impressions"], metrics.get("views", 0))

        if enough_time and signal_ok:
            complete_ab_variant(test["id"])
            actions.append(f"completed {test['variant_type']} variant #{test['variant_index']}")
        elif enough_time:
            logger.info(f"Test #{test['id']} waiting for signal: "
                        f"impressions={metrics['impressions']}, views={metrics['views']}, age={age:.1f}d")

    # ── Select winners and restore ──
    conn = memory._get_db()
    rows = conn.execute("""
        SELECT * FROM ab_tests
        WHERE test_phase = 'completed' AND winner_flag = 0 AND restored = 0
        ORDER BY pipeline_id, variant_type, variant_index
    """).fetchall()
    completed_no_dec = [dict(r) for r in rows]

    # Group by pipeline + type
    groups = {}
    for t in completed_no_dec:
        key = (t["pipeline_id"], t["variant_type"])
        groups.setdefault(key, []).append(t)

    for (pid, vtype), group in groups.items():
        # A/B results are invalid unless impressions >= 100
        metrics = _fetch_video_analytics(group[0]["video_id"])
        if metrics["impressions"] < 100:
            logger.info(f"A/B results invalid for {pid}/{vtype}: "
                        f"impressions={metrics['impressions']} < 100 — keeping all variants active")
            continue

        # Include the original (variant_index=0) if it was tested
        originals = [t for t in group if t["variant_index"] == 0]
        alternatives = [t for t in group if t["variant_index"] > 0]

        winner = _select_winner(group)
        if winner:
            set_ab_winner(winner["id"])
            actions.append(f"winner declared: {vtype} #{winner['variant_index']} "
                           f"(CTR={winner.get('ctr', 0):.1f}%)")

            # Restore winner
            if not dry_run:
                if vtype == "title":
                    update_video_metadata(
                        video_id=winner["video_id"],
                        title=winner["variant_value"][:100],
                    )
                    set_ab_restored(winner["id"])
                    actions.append(f"restored winning title for {winner['video_id']}")
                elif vtype == "thumbnail":
                    style = winner["variant_value"].split("|")[0]
                    trow = conn.execute("""
                        SELECT path FROM thumbnails
                        WHERE pipeline_id = ? AND style = ? LIMIT 1
                    """, (pid, style)).fetchone()
                    if trow:
                        yt = _get_authenticated_service()
                        if yt:
                            yt.thumbnails().set(
                                videoId=winner["video_id"],
                                media_body=trow["path"]
                            ).execute()
                            set_ab_restored(winner["id"])
                            actions.append(f"restored winning thumbnail for {winner['video_id']}")

            # Feed back into learning
            _feed_winner_back(winner)

    # ── Activate pending tests ──
    published = get_pipeline_history(200)
    published_ids = {p["id"] for p in published if p.get("youtube_video_id")}

    for pid in published_ids:
        days = _days_since_publish(pid)
        if days < AB_CONFIG["days_before_first_rotation"]:
            continue

        # Seed variants if not already done
        existing = get_ab_variants(pid, "title")
        if not existing:
            pipe = next((p for p in published if p["id"] == pid), None)
            if pipe and pipe.get("youtube_video_id"):
                seeded = seed_variants(pid, pipe["youtube_video_id"])
                if seeded and not dry_run:
                    actions.append(f"seeded {seeded} variants for {pid}")

        # Activate next pending variant per type
        for vtype in ("title", "thumbnail"):
            pending = [t for t in get_pending_ab_tests()
                       if t["pipeline_id"] == pid and t["variant_type"] == vtype]
            if pending and not dry_run:
                next_variant = pending[0]
                swapped = _rotate_metadata(next_variant["video_id"], next_variant)
                if swapped:
                    activate_ab_variant(next_variant["id"])
                    actions.append(f"activated {vtype} #{next_variant['variant_index']} for {pid}")
                    time.sleep(1.0)

    return {
        "status": "completed",
        "dry_run": dry_run,
        "actions_taken": len(actions),
        "actions": actions[:20],
        "active_tests": len(active),
        "completed_this_cycle": len(completed_no_dec),
    }
