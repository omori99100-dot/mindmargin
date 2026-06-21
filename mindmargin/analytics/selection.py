"""Selection Pressure System: classify, reinforce, suppress, expand, score.

Drives natural selection of content strategy based on real audience response.
Integrates incrementally into existing analytics pipeline.
"""

import logging
from datetime import datetime, timedelta
from typing import Any

from mindmargin.analytics.memory import (
    get_pipeline_history, get_best_practices, get_best_hooks, get_best_titles,
    get_top_performers, save_best_practice,
    save_classification, get_all_classifications, get_classification_counts,
    save_reinforced_pattern, get_reinforced_patterns,
    save_suppressed_pattern, get_suppressed_patterns,
    archive_dead_pattern, get_dead_patterns,
    record_dominant_archetype, get_dominant_archetypes,
    save_topic_lineage, get_topic_lineages, mark_topic_published,
    save_analytics,
)

logger = logging.getLogger(__name__)

# ── Topic expansion map (parent → likely child topics) ──
_TOPIC_EXPANSION_MAP: dict[str, list[str]] = {
    "ftx": ["binance collapse", "celsius network", "terra luna crash",
            "three arrows capital", "crypto scams documentary",
            "the fall of sam bankman-fried", "voyager digital bankruptcy"],
    "theranos": ["elizabeth holmes trial", "bad blood silicon valley fraud",
                 "medical startup scams", "wirecard scandal",
                 "theranos whistleblower story"],
    "wework": ["adam neumann story", "softbank losses", "startup valuation fraud",
               "wet lab startup failures", "the cult of wework"],
    "enron": ["worldcom scandal", "tyco international", "accounting fraud cases",
              "the smartest guys in the room", "andrew fastow enron"],
    "bernie madoff": ["ponzi schemes explained", "wall street fraud cases",
                      "SEC failures", "victims of madoff"],
    "lehman brothers": ["2008 financial crisis", "bear stearns collapse",
                        "aig bailout", "subprime mortgage crisis",
                        "too big to fail banks"],
    "silicon valley bank": ["bank run documentary", "regional bank crisis",
                            "svb collapse explained", "signature bank failure",
                            "credit suisse downfall"],
    "uber": ["tech startup toxic culture", "weinstein effect in tech",
             "gig economy exploitation", "travis kalanick story"],
    "nokia": ["blackberry failure", "kodak digital failure", "blockbuster netflix",
              "why companies fail to adapt", "disruption case studies"],
    "myspace": ["facebook vs myspace", "why social networks die",
                "tom anderson myspace", "the rise of social media"],
    "yahoo": ["marissa mayer yahoo", "google vs yahoo", "failed tech acquisitions",
              "silicon valley graveyard"],
    "blackberry": ["iphone vs blackberry", "rim downfall", "why blackberry failed",
                   "mobile industry disruption"],
    "kodak": ["polaroid failure", "disruption ignored", "innovators dilemma cases"],
    "blockbuster": ["netflix vs blockbuster", "redbox story",
                    "why blockbuster failed", "video rental history"],
    "gamestop": ["wallstreetbets story", "meme stocks explained",
                 "robinhood gamestop", "short squeeze documentary"],
    "cambridge analytica": ["facebook data scandal", "election interference",
                            "data privacy breaches", "carole cadwalladr story"],
}

_KNOWN_TOPIC_ALIASES: dict[str, str] = {
    "the collapse of silicon valley bank": "silicon valley bank",
    "the story of bernie madoff's ponzi scheme": "bernie madoff",
    "the collapse of lehman brothers": "lehman brothers",
    "the untold story of uber's toxic culture": "uber",
    "how blackberry lost everything": "blackberry",
    "how myspace lost to facebook": "myspace",
    "the fall of yahoo": "yahoo",
    "inside the 2022 bitcoin crash": "ftx",
    "why nokia lost the smartphone war": "nokia",
    "the story behind the gamestop stock frenzy": "gamestop",
    "the rise and fall of blockbuster": "blockbuster",
    "how they invented digital and still failed": "kodak",
    "cambridge analytica": "cambridge analytica",
    "the complete untold story": "",
}


def _normalize_topic(topic: str) -> str:
    """Normalize topic for map lookup by lowering and checking aliases."""
    lower = topic.lower()
    # Check exact match first
    if lower in _TOPIC_EXPANSION_MAP:
        return lower
    # Check aliases
    if lower in _KNOWN_TOPIC_ALIASES:
        return _KNOWN_TOPIC_ALIASES[lower]
    # Partial match: try to find a known topic within the string
    for known in _TOPIC_EXPANSION_MAP:
        if known in lower:
            return known
    return lower


# ──────────────────────────────────────────────
# 1. VIDEO PERFORMANCE CLASSIFICATION
# ──────────────────────────────────────────────


def is_phase2_active(impressions: int, views: int = 0) -> bool:
    """Phase 2 (audience signal) is active when impressions >= 100.

    Falls back to views >= 30 when the YouTube API does not provide
    impression data (YouTube Data API v3 statistics part does not
    include impressions — only Analytics API v2 does).
    """
    return impressions >= 100 or views >= 30


def normalize_ctr(ctr: float) -> float:
    """Normalize CTR to 0-1 scale regardless of input format."""
    if ctr > 1:
        return ctr / 100  # was percentage
    return ctr  # already 0-1 ratio


def normalize(metrics) -> tuple:
    ctr = metrics.ctr  # 0 - 1
    retention = metrics.avg_watch_time / metrics.video_length
    velocity = metrics.views_per_hour
    return ctr, retention, velocity


def compute_score(ctr: float, retention: float, velocity: float) -> float:
    return (
        0.45 * ctr +
        0.40 * retention +
        0.15 * min(velocity / 10, 1.0)
    )


def map_score_to_label(score: float) -> str:
    if score >= 0.35:
        return "winner_candidate"
    elif score >= 0.20:
        return "keep_testing"
    elif score >= 0.10:
        return "stable_equivalent"
    else:
        return "weak_signal"


def classify_video(pipeline_id: str, video_id: str, topic: str,
                   video_duration_s: float = 0) -> dict:
    """Classify a single video's performance using real Analytics API metrics.

    Priority order (Tier 1 → Tier 3):
      Tier 1: Real Analytics API data (ctr, averageViewPercentage, impressions)
      Tier 2: Derived metrics from Data API stats (velocity-based fallback)
      Tier 3: DB cache / cold start

    Returns dict with classification, confidence, and all computed metrics.
    """
    from mindmargin.integrations.youtube import get_video_stats, get_analytics
    from mindmargin.analytics.memory import get_video_analytics_from_db

    # ── Fetch data: Tier 1 = Analytics API, Tier 2 = Data API, Tier 3 = DB cache ──
    stats = get_video_stats(video_id)
    has_analytics_api = False
    if stats.get("status") == "completed":
        advanced = get_analytics(video_id)
        if advanced.get("status") == "completed" and advanced.get("data"):
            stats.update({k: v for k, v in advanced["data"].items()
                          if k not in ("status", "video_id", "error")})
            has_analytics_api = True

    # Tier 3: DB cache fallback
    if stats.get("status") != "completed":
        db_row = get_video_analytics_from_db(video_id)
        if db_row:
            views = db_row.get("views", 0) or 0
            stats = {
                "status": "completed",
                "video_id": video_id,
                "views": views,
                "likes": db_row.get("likes", 0) or 0,
                "comments": db_row.get("comments", 0) or 0,
                "shares": db_row.get("shares", 0) or 0,
                "averageViewDuration": db_row.get("avg_view_duration_s", 0) or 0,
                "averageViewPercentage": db_row.get("average_view_percentage", 0) or 0,
                "impressions": db_row.get("impressions", 0) or 0,
                "ctr": db_row.get("ctr", 0) or 0,
                "estimatedMinutesWatched": db_row.get("watch_time_minutes", 0) or 0,
            }
        else:
            return {"status": "insufficient_data", "video_id": video_id,
                    "error": stats.get("error", "unknown")}

    # ── Extract raw metrics ──
    views = stats.get("views", 0) or 0
    likes = stats.get("likes", 0) or 0
    comments = stats.get("comments", 0) or 0
    shares = stats.get("shares", 0) or 0
    avg_duration = stats.get("averageViewDuration", 0) or 0
    impressions_val = stats.get("impressions", 0) or 0
    ctr_raw = stats.get("ctr", None)      # real CTR from Analytics API (0-1 ratio)
    avg_view_pct = stats.get("averageViewPercentage", None)  # avg % viewed
    watch_time_minutes = stats.get("estimatedMinutesWatched", 0) or 0

    # ── Save analytics to memory first ──
    save_analytics(pipeline_id, video_id, stats)

    # ── Derived metrics ──
    has_impressions = impressions_val > 0
    # Compute CTR percentage for display, use real CTR ratio when available
    if ctr_raw is not None and ctr_raw > 0:
        ctr_ratio = ctr_raw if ctr_raw <= 1 else ctr_raw / 100
        ctr_pct = ctr_ratio * 100
    elif has_impressions:
        ctr_pct = (views / impressions_val) * 100
        ctr_ratio = ctr_pct / 100
    else:
        ctr_pct = 0.0
        ctr_ratio = 0.0

    # Retention: prefer averageViewPercentage from Analytics API
    if avg_view_pct is not None and avg_view_pct > 0:
        retention = avg_view_pct / 100  # API returns 0-100 percentage
    elif video_duration_s > 0 and avg_duration > 0:
        retention = avg_duration / video_duration_s  # derived fallback
    else:
        retention = 0.0

    watch_time_s = avg_duration * views
    engagement_rate = ((likes + comments) / max(views, 1)) * 100 if views > 0 else 0

    # ── Velocity: views per hour since publish ──
    pipe_rows = get_pipeline_history(200)
    pub_time = None
    for p in pipe_rows:
        if p["id"] == pipeline_id:
            pub_time = p.get("published_at") or p.get("created_at")
            break
    hours_since = 999.0
    if pub_time:
        try:
            pub_dt = datetime.strptime(pub_time[:19], "%Y-%m-%d %H:%M:%S")
            hours_since = max((datetime.utcnow() - pub_dt).total_seconds() / 3600, 1)
            velocity = views / hours_since
        except (ValueError, TypeError):
            velocity = views / max(1, len(pipe_rows))
    else:
        velocity = views / max(1, len(pipe_rows))

    # ── Classification logic ──
    # Tier 1: Cold start (phase 2 not active)
    if not is_phase2_active(impressions_val, views):
        classification = "insufficient_signal"
        confidence = 0.0
        result = {
            "video_id": video_id,
            "classification": classification,
            "confidence": confidence,
            "ctr_pct": round(ctr_pct, 2),
            "ctr_ratio": round(ctr_ratio, 4),
            "retention": round(retention, 3),
            "watch_time_s": round(watch_time_s, 1),
            "watch_time_minutes": round(watch_time_minutes, 1),
            "impressions": impressions_val,
            "engagement_rate": round(engagement_rate, 2),
            "velocity": round(velocity, 3),
            "topic": topic,
            "reason": "cold_start_locked",
            "data_source": "insufficient",
        }
        save_classification(
            pipeline_id, video_id, classification, confidence,
            ctr_pct, retention, watch_time_s, impressions_val,
            engagement_rate, velocity,
            views, hours_since / 24,
        )
        logger.info(f"Classified '{topic}': insufficient_signal "
                    f"(impressions={impressions_val}, ctr={ctr_pct:.1f}%, retention={retention:.1%})")
        return result

    # Tier 2: Analytics API data available → CTR + retention driven
    if has_analytics_api and ctr_ratio > 0 and retention > 0.01:
        metrics_score = compute_score(ctr_ratio, retention, velocity)
        classification = map_score_to_label(metrics_score)
        confidence = min(metrics_score + 0.15, 1.0)
        data_source = "analytics_api"
        logger.info(f"Analytics-driven classify for '{topic}': "
                    f"CTR={ctr_pct:.1f}%, retention={retention:.1%}, "
                    f"score={metrics_score:.3f} -> {classification}")

    # Tier 3: Velocity-only fallback when Analytics API data is unavailable
    elif retention <= 0.01 or not has_analytics_api:
        data_source = "velocity_only"
        if velocity >= 50:
            classification = "winner_candidate"
            confidence = 0.55
        elif velocity >= 20:
            classification = "keep_testing"
            confidence = 0.40
        elif velocity >= 5:
            classification = "stable_equivalent"
            confidence = 0.25
        else:
            classification = "weak_signal"
            confidence = 0.15
        logger.info(f"Velocity fallback for '{topic}': vel={velocity:.1f}/hr -> {classification}")

    # Tier 4: Score-based with derived metrics (has impressions but no analytics API)
    else:
        metrics_score = compute_score(ctr_ratio, retention, velocity)
        classification = map_score_to_label(metrics_score)
        confidence = min(metrics_score + 0.15, 1.0)
        data_source = "derived"
        logger.info(f"Derived-score classify for '{topic}': "
                    f"CTR={ctr_pct:.1f}%, retention={retention:.1%}, "
                    f"score={metrics_score:.3f} -> {classification}")

    result = {
        "video_id": video_id,
        "classification": classification,
        "confidence": round(confidence, 3),
        "ctr_pct": round(ctr_pct, 2),
        "ctr_ratio": round(ctr_ratio, 4),
        "retention": round(retention, 3),
        "watch_time_s": round(watch_time_s, 1),
        "watch_time_minutes": round(watch_time_minutes, 1),
        "impressions": impressions_val,
        "engagement_rate": round(engagement_rate, 2),
        "velocity": round(velocity, 3),
        "topic": topic,
        "data_source": data_source,
    }

    # Persist
    save_classification(
        pipeline_id, video_id, classification, confidence,
        ctr_pct, retention, watch_time_s, impressions_val,
        engagement_rate, velocity,
        views, hours_since / 24,
    )

    logger.info(f"Classified '{topic}': {classification} "
                f"(source={data_source}, CTR={ctr_pct:.1f}%, "
                f"retention={retention:.1%}, "
                f"velocity={velocity:.1f}/hr)")

    return result


def recalculate_all_classifications() -> dict:
    """Reclassify all published videos and return summary."""
    history = get_pipeline_history(200)
    published = [p for p in history if p.get("youtube_video_id")]

    if not published:
        return {"status": "skipped", "count": 0, "classifications": {}}

    counts: dict[str, int] = {"winner_candidate": 0, "keep_testing": 0,
                              "stable_equivalent": 0, "weak_signal": 0, "insufficient_signal": 0}
    for p in published:
        try:
            result = classify_video(
                p["id"], p["youtube_video_id"], p.get("topic", ""),
                video_duration_s=p.get("video_duration_s", 0),
            )
            cls = result.get("classification")
            if cls in counts:
                counts[cls] += 1
        except Exception as e:
            logger.warning(f"Classification failed for {p['id']}: {e}")

    # Record dominant archetypes
    _record_archetype_dominance()

    logger.info(f"Classification cycle: {counts}")
    return {"status": "completed", "count": sum(counts.values()),
            "classifications": counts}


def _record_archetype_dominance() -> None:
    """Record current dominance percentages for hook archetypes."""
    hooks = get_best_hooks(50)
    if not hooks:
        return
    total = len(hooks)
    arch_counts: dict[str, int] = {}
    for h in hooks:
        arch = h.get("archetype", "unknown")
        arch_counts[arch] = arch_counts.get(arch, 0) + 1
    for arch, cnt in arch_counts.items():
        dominance = (cnt / total) * 100
        record_dominant_archetype("hook_archetype", arch,
                                  round(dominance, 1), cnt)


# ──────────────────────────────────────────────
# 2. PATTERN REINFORCEMENT ENGINE
# ──────────────────────────────────────────────

def _performance_weight(classification: str) -> float:
    return {"winner_candidate": 1.0, "keep_testing": 0.6,
            "stable_equivalent": 0.4, "weak_signal": 0.05,
            "insufficient_signal": 0.0}.get(classification, 0.1)


def _engagement_quality(stats: dict) -> float:
    likes = stats.get("likes", 0) or 0
    comments = stats.get("comments", 0) or 0
    views = stats.get("views", 1) or 1
    rate = (likes + comments) / max(views, 1)
    return min(rate * 20, 1.0)  # 5% engagement → 1.0


def calculate_selection_score(classification: str, consistency: float = 1.0,
                              retention: float = 0, ctr: float = 0,
                              repeat_success_factor: float = 1.0) -> float:
    """Unified SELECTION_SCORE for reinforcement strength.

    SELECTION_SCORE =
        performance_weight *
        consistency *
        retention_weight *
        ctr_weight *
        repeat_success_factor
    """
    pw = _performance_weight(classification)
    retention_w = min(retention / 0.5, 1.0)  # 50% retention → 1.0
    ctr_w = min(ctr / 10.0, 1.0)  # 10% CTR → 1.0
    score = pw * consistency * max(retention_w, 0.1) * max(ctr_w, 0.1) * repeat_success_factor
    return round(score, 4)


def reinforce_winners() -> dict:
    """Reinforce winning patterns from high-performing videos.

    Increases optimizer weights for:
    - hook archetypes
    - title structures
    - thumbnail styles
    - pacing profiles
    - topic categories
    """
    classifications = get_all_classifications(100)
    top_videos = [c for c in classifications
                  if c["classification"] in ("winner_candidate",)]

    if not top_videos:
        logger.info("No winning videos to reinforce from")
        return {"status": "skipped", "patterns_reinforced": 0}

    reinforced = 0

    # Group by classification for consistency factor
    cls_count = len(top_videos)
    total = len(classifications)
    consistency = cls_count / max(total, 1)

    for v in top_videos:
        topic = v.get("topic", "")
        cls = v["classification"]
        ctr = v.get("ctr", 0) or 0
        retention = v.get("retention", 0) or 0
        pw = _performance_weight(cls)
        score = calculate_selection_score(
            cls, consistency, retention, ctr,
            repeat_success_factor=1.0,
        )

        # 1. Reinforce topic category
        save_reinforced_pattern(
            "topic", topic.lower(), f"Topic: {topic}",
            score, min(ctr / 10 + retention, 1.0),
            source_pipeline_id=v.get("pipeline_id", ""),
            performance_class=cls,
        )
        reinforced += 1

        # 2. Try to find and reinforce matching hook archetypes
        hooks = get_best_hooks(20)
        for h in hooks:
            if h.get("archetype") and h.get("archetype") != "unknown":
                archetype = h["archetype"]
                h_ctr = h.get("actual_ctr") or h.get("ctr_score", 0) or 0
                save_reinforced_pattern(
                    "hook_archetype", archetype,
                    f"Hook archetype '{archetype}' scores {h_ctr:.0f}",
                    score * min(h_ctr / 80, 1.0),
                    min(h_ctr / 100, 1.0),
                    performance_class=cls,
                )
                reinforced += 1

        # 3. Reinforce title structure (first video's title pattern)
        titles = get_best_titles(10)
        for t in titles[:3]:
            title_text = t.get("title", "")
            if title_text:
                t_ctr = t.get("ctr", 0) or 0
                save_reinforced_pattern(
                    "title", title_text[:60],
                    f"Title structure: {title_text[:50]} (CTR: {t_ctr:.1f}%)",
                    score * min(t_ctr / 10, 1.0),
                    min(t_ctr / 15, 1.0),
                    performance_class=cls,
                )
                reinforced += 1

    # 4. Best practices sync: write reinforced patterns as best_practices
    reinforced_hooks = get_reinforced_patterns("hook_archetype", 5)
    for rh in reinforced_hooks[:3]:
        save_best_practice(
            "hook_archetype_selection", rh["key"],
            rh["value"], rh["selection_score"] * 100,
        )

    reinforced_titles = get_reinforced_patterns("title", 5)
    for rt in reinforced_titles[:3]:
        save_best_practice(
            "title_selection", rt["key"],
            rt["value"], rt["selection_score"] * 100,
        )

    # 5. Record dominant archetypes
    _record_archetype_dominance()

    logger.info(f"Reinforced {reinforced} patterns from {len(top_videos)} winning videos")
    return {"status": "completed", "patterns_reinforced": reinforced,
            "winners_used": len(top_videos)}


# ──────────────────────────────────────────────
# 3. FAILURE SUPPRESSION
# ──────────────────────────────────────────────

def _decay_score(pattern: dict, base: float = 0.7) -> float:
    """Gradual multiplicative decay — never reaches zero."""
    return base ** pattern.get("suppression_count", 1)


def suppress_losers() -> dict:
    """Suppress patterns from repeatedly failing videos.

    Gradually decreases weights for:
    - low CTR hooks/titles
    - poor thumbnail styles
    - low retention pacing

    Never instantly deletes. Uses gradual multiplicative decay.
    Skips videos with insufficient_signal — no data is not bad data.
    """
    classifications = get_all_classifications(100)
    weak_vids = [c for c in classifications
                 if c["classification"] in ("weak_signal",)]

    # FREEZE: skip videos where phase 2 is not active
    weak_vids = [v for v in weak_vids if is_phase2_active(
        v.get("impressions", 0) or 0,
        v.get("views", 0) or 0,
    )]

    # Suppression override: stable_equivalent with poor score at high impressions
    stable_extra = [c for c in classifications
                    if c["classification"] == "stable_equivalent"
                    and (c.get("impressions", 0) or 0) > 300
                    and compute_score(
                        normalize_ctr(c.get("ctr", 0) or 0),
                        c.get("retention", 0) or 0,
                        c.get("velocity", 0) or 0,
                    ) < 0.25]
    weak_vids = weak_vids + stable_extra

    if not weak_vids:
        logger.info("No losing videos with sufficient signal to suppress from")
        return {"status": "skipped", "patterns_suppressed": 0}

    suppressed = 0

    for v in weak_vids:
        topic = v.get("topic", "")
        cls = v["classification"]
        ctr = v.get("ctr", 0) or 0
        retention = v.get("retention", 0) or 0

        # 1. Suppress topic if repeatedly weak
        save_suppressed_pattern(
            "topic", topic.lower(), f"Weak topic: {topic}",
            ctr, decay=0.7,
            reason=f"Classified as {cls} (CTR={ctr:.1f}%, retention={retention:.1%})",
        )
        suppressed += 1

        # 2. Suppress low-CTR hook archetypes
        hooks = get_best_hooks(20)
        for h in hooks:
            arch = h.get("archetype", "")
            if arch and arch != "unknown":
                h_ctr = h.get("actual_ctr") or h.get("ctr_score", 0) or 0
                if h_ctr < 40:  # Low performing archetype
                    save_suppressed_pattern(
                        "hook_archetype", arch,
                        f"Low-CTR hook: {arch} ({h_ctr:.0f})",
                        h_ctr, decay=0.8,
                        reason=f"Consistently low CTR ({h_ctr:.0f})",
                    )
                    suppressed += 1

    # 3. Archive deeply suppressed patterns with dead pattern protection
    # A pattern may only become dead if:
    #   - minimum_videos >= 3 (suppression_count >= 3)
    #   - sufficient_signal == True (already filtered above)
    #   - suppression_cycles >= 3
    #   - average_impressions >= 50
    deeply = get_suppressed_patterns(limit=50)
    archived = 0
    for sp in deeply:
        if sp.get("suppression_count", 0) >= 3 and sp.get("current_decay", 1.0) < 0.35:
            # Compute average impressions from the weak videos that triggered suppression
            avg_impressions = 0
            matched = [v for v in weak_vids if _normalize_topic(v.get("topic", "")) == sp["key"]]
            if matched:
                avg_impressions = sum(v.get("impressions", 0) or 0 for v in matched) / len(matched)

            if avg_impressions >= 50:
                archive_dead_pattern(
                    sp["category"], sp["key"], sp["value"],
                    sp["original_score"], sp["suppression_count"],
                )
                archived += 1
            else:
                logger.info(f"Dead pattern protection: {sp['key']} avg_impressions={avg_impressions:.0f} < 50")

    logger.info(f"Suppressed {suppressed} patterns, archived {archived}")
    return {"status": "completed", "patterns_suppressed": suppressed,
            "archived": archived, "weak_videos_used": len(weak_vids)}


# ──────────────────────────────────────────────
# 4. TOPIC EXPANSION LOGIC
# ──────────────────────────────────────────────

def expand_topics() -> dict:
    """Generate related topic opportunities from strong performers.

    Uses static expansion map, scored by parent's performance inheritance.
    """
    classifications = get_all_classifications(100)
    strong = [c for c in classifications
              if c["classification"] in ("winner_candidate",)]

    if not strong:
        logger.info("No strong topics to expand from")
        return {"status": "skipped", "children_generated": 0}

    generated = 0
    existing_lineages = get_topic_lineages(limit=100)
    existing_children = {l["child_topic"].lower() for l in existing_lineages}

    # Get topics already published
    history = get_pipeline_history(200)
    published_topics = {p["topic"].lower() for p in history
                        if p.get("youtube_video_id")}

    for v in strong:
        topic = v.get("topic", "")
        normalized = _normalize_topic(topic)
        children = _TOPIC_EXPANSION_MAP.get(normalized, [])

        if not children:
            continue

        ctr = v.get("ctr", 0) or 0
        retention = v.get("retention", 0) or 0
        pw = _performance_weight(v["classification"])
        inheritance = round(min(pw * (ctr / 10) * (retention + 0.5), 1.0), 3)
        confidence = min(0.7 + (ctr / 20), 0.95)

        for child in children:
            child_lower = child.lower()
            if child_lower in existing_children:
                continue  # already in lineage
            if child_lower in published_topics:
                continue  # already published

            save_topic_lineage(topic, child, confidence, inheritance)
            generated += 1

    logger.info(f"Generated {generated} new topic suggestions")
    return {"status": "completed", "children_generated": generated}


# ──────────────────────────────────────────────
# 6. EVOLUTION MEMORY SUMMARY
# ──────────────────────────────────────────────

def get_evolution_memory_summary() -> dict:
    """Snapshot of all evolution memory for dashboard / optimizer."""
    reinforced = get_reinforced_patterns()
    suppressed = get_suppressed_patterns()
    dead = get_dead_patterns()
    classifications = get_classification_counts()
    archs = get_dominant_archetypes("hook_archetype", 5)
    lineages = get_topic_lineages(limit=20)

    return {
        "reinforced_count": len(reinforced),
        "suppressed_count": len(suppressed),
        "dead_count": len(dead),
        "classifications": classifications,
        "total_classified": sum(classifications.values()),
        "dominant_archetypes": archs[:3],
        "topic_suggestions": [l for l in lineages if not l["is_published"]],
        "lineage_count": len(lineages),
    }


# ──────────────────────────────────────────────
# 8. DAILY EVOLUTION CYCLE
# ──────────────────────────────────────────────

def run_selection_cycle() -> dict:
    """Full evolution cycle: classify → reinforce → suppress → expand → log.

    Intended to run as part of --run-daily-job (Step 5).
    """
    logger.info("=== Selection Pressure Cycle Starting ===")

    # Step 1: Recalculate classifications
    logger.info("  [1/4] Classifying videos...")
    classes = recalculate_all_classifications()

    # Step 2: Reinforce winners
    logger.info("  [2/4] Reinforcing winning patterns...")
    reinforced = reinforce_winners()

    # Step 3: Suppress losers
    logger.info("  [3/4] Suppressing losing patterns...")
    suppressed = suppress_losers()

    # Step 4: Expand topics
    logger.info("  [4/4] Expanding strong topics...")
    expanded = expand_topics()

    summary = get_evolution_memory_summary()

    result = {
        "status": "completed",
        "classifications": classes,
        "reinforced": reinforced,
        "suppressed": suppressed,
        "expanded": expanded,
        "memory": summary,
        "completed_at": datetime.utcnow().isoformat(),
    }

    logger.info(f"=== Selection Cycle Complete ===")
    logger.info(f"  Classified: {classes.get('count', 0)} videos")
    logger.info(f"  Reinforced: {reinforced.get('patterns_reinforced', 0)} patterns")
    logger.info(f"  Suppressed: {suppressed.get('patterns_suppressed', 0)} patterns")
    logger.info(f"  Archived:   {suppressed.get('archived', 0)} dead patterns")
    logger.info(f"  Expanded:   {expanded.get('children_generated', 0)} topics")

    return result


# ──────────────────────────────────────────────
# 9. VALIDATION REPORT (old vs analytics-driven)
# ──────────────────────────────────────────────

def generate_validation_report() -> dict:
    """Compare old (velocity-only) classification vs analytics-driven classification.

    Applies both systems to all published videos and reports:
    - Classification counts for each system
    - Confusion matrix between the two
    - Shift analysis: which videos change classification and why
    """
    history = get_pipeline_history(200)
    published = [p for p in history if p.get("youtube_video_id")]

    if not published:
        return {"status": "skipped", "total_videos": 0,
                "message": "No published videos to classify"}

    old_results = []
    new_results = []

    for p in published:
        pid = p["id"]
        vid = p["youtube_video_id"]
        topic = p.get("topic", "")
        dur = p.get("video_duration_s", 0)

        # Get analytics data for this video
        from mindmargin.integrations.youtube import get_video_stats, get_analytics
        stats = get_video_stats(vid)
        has_analytics = False
        if stats.get("status") == "completed":
            advanced = get_analytics(vid)
            if advanced.get("status") == "completed" and advanced.get("data"):
                stats.update(advanced["data"])
                has_analytics = True

        views = stats.get("views", 0) or 0
        impressions_val = stats.get("impressions", 0) or 0
        avg_duration = stats.get("averageViewDuration", 0) or 0
        ctr_raw = stats.get("ctr", None)
        avg_view_pct = stats.get("averageViewPercentage", None)

        # Simulate old system
        has_impressions = impressions_val > 0
        ctr_old = (views / impressions_val) * 100 if has_impressions else 0.0
        retention_old = avg_duration / max(dur, 1) if dur > 0 else 0

        # Old scoring (velocity-based when no retention)
        if retention_old <= 0.005:
            velocity_approx = views / 24  # approx per hour
            if velocity_approx >= 50:
                old_cls = "winner_candidate"
            elif velocity_approx >= 20:
                old_cls = "keep_testing"
            elif velocity_approx >= 5:
                old_cls = "stable_equivalent"
            else:
                old_cls = "weak_signal"
        else:
            old_score = compute_score(normalize_ctr(ctr_old), retention_old, velocity_approx)
            old_cls = "winner_candidate" if old_score >= 0.8 else (
                "keep_testing" if old_score >= 0.6 else (
                    "stable_equivalent" if old_score >= 0.4 else "weak_signal"))

        # New system
        if not is_phase2_active(impressions_val, views):
            new_cls = "insufficient_signal"
        elif has_analytics and ctr_raw and ctr_raw > 0 and avg_view_pct and avg_view_pct > 1:
            ctr_ratio = ctr_raw if ctr_raw <= 1 else ctr_raw / 100
            retention_new = avg_view_pct / 100
            new_score = compute_score(ctr_ratio, retention_new, velocity_approx)
            new_cls = map_score_to_label(new_score)
        else:
            if velocity_approx >= 50:
                new_cls = "winner_candidate"
            elif velocity_approx >= 20:
                new_cls = "keep_testing"
            elif velocity_approx >= 5:
                new_cls = "stable_equivalent"
            else:
                new_cls = "weak_signal"

        if old_cls != new_cls:
            old_results.append({
                "pipeline_id": pid, "topic": topic,
                "old_classification": old_cls, "new_classification": new_cls,
                "has_analytics_api": has_analytics,
                "ctr_pct": round(ctr_old, 1),
                "retention_pct": round(retention_old * 100, 1),
            })
        new_results.append(new_cls)

    old_counts = {}
    new_counts = {}
    for label in ("winner_candidate", "keep_testing", "stable_equivalent", "weak_signal", "insufficient_signal"):
        old_counts[label] = 0
        new_counts[label] = 0

    for r in old_results:
        old_counts[r["old_classification"]] = old_counts.get(r["old_classification"], 0) + 1
        new_counts[r["new_classification"]] = new_counts.get(r["new_classification"], 0) + 1

    return {
        "status": "completed",
        "total_videos": len(published),
        "old_system_counts": old_counts,
        "new_system_counts": new_counts,
        "classification_shifts": old_results,
        "shift_count": len(old_results),
        "analytics_api_available": sum(1 for r in old_results if r.get("has_analytics_api")),
        "summary": (
            f"Old system classified {len(published)} videos. "
            f"New system reclassified with analytics-driven CTR+retention. "
            f"{len(old_results)} videos changed classification."
        ),
    }


def format_selection_report(result: dict) -> str:
    """Format selection cycle result as human-readable string."""
    classes = result.get("classifications", {})
    reinforced = result.get("reinforced", {})
    suppressed = result.get("suppressed", {})
    expanded = result.get("expanded", {})
    memory = result.get("memory", {})

    lines = [
        "=" * 55,
        "  SELECTION PRESSURE CYCLE REPORT",
        "=" * 55,
    ]

    cls = classes.get("classifications", {})
    if cls:
        lines.append(f"\n  Video classifications:")
        for c in ("winner_candidate", "keep_testing", "stable_equivalent", "weak_signal", "insufficient_signal"):
            count = cls.get(c, 0)
            lines.append(f"    {c:22s}: {count}")
    else:
        lines.append(f"\n  Classifications: {classes.get('count', 0)} videos")

    lines.append(f"\n  Reinforcement: {reinforced.get('patterns_reinforced', 0)} patterns "
                 f"from {reinforced.get('winners_used', 0)} winners")
    lines.append(f"  Suppression:   {suppressed.get('patterns_suppressed', 0)} patterns, "
                 f"{suppressed.get('archived', 0)} archived")
    lines.append(f"  Topic expansion: {expanded.get('children_generated', 0)} new suggestions")

    memory_data = result.get("memory", {})
    if memory_data.get("dominant_archetypes"):
        lines.append(f"\n  Dominant archetypes:")
        for a in memory_data["dominant_archetypes"]:
            lines.append(f"    {a['archetype']:20s} "
                         f"{a['dominance_pct']:.0f}% ({a['sample_size']} samples)")

    unsuggested = [l for l in memory_data.get("topic_suggestions", [])
                   if not l.get("is_published")][:5]
    if unsuggested:
        lines.append(f"\n  Suggested topics (inherit from strong performers):")
        for s in unsuggested:
            lines.append(f"    -> {s['child_topic'][:45]} "
                         f"(confidence: {s['confidence']:.0%}, "
                         f"inheritance: {s['performance_inheritance']:.1f})")

    lines.extend([
        "",
        "=" * 55,
    ])
    return "\n".join(lines)
