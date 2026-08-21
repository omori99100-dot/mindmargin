"""Decision Executor — closes the loop between intelligence and action.

Orchestrates the autonomous cycle:
  Channel Brain → Growth Engine → Topic Selection → Pipeline → Publish → Log
"""
import logging
import sys
import uuid
from pathlib import Path
from datetime import datetime

from mindmargin.config import settings
from mindmargin.core.pipeline import Pipeline
from mindmargin.analytics.memory import (
    save_pipeline, save_pipeline_result, save_execution_log,
    save_titles, save_hooks, save_thumbnails,
    get_pipeline_history, get_topic_lineages, mark_topic_published,
    get_execution_log, is_successful_publish,
)

logger = logging.getLogger(__name__)

MAX_CONSECUTIVE_FAILURES = 3
MIN_CONFIDENCE = 0.50
MIN_CHANNEL_HEALTH = 4.0
MAX_DAILY_PUBLISH = 1

_CIRCUIT_BREAKER_TRIPPED = False

_TOPIC_DOMAINS = [
    "business failure", "corruption", "political scandal",
    "financial crisis", "startup failure", "tech disruption",
    "fraud", "class action", "regulatory failure",
    "industry disruption", "cultural phenomenon",
]


def select_topic(brain_report: dict, growth_report: dict, pipeline_id: str = "") -> str:
    """Select and persist the highest-ranked actionable topic decision.

    The return type remains ``str`` for backward compatibility. Phase B records
    the real alternatives, scores, evidence, rationale, and selected option in
    the lineage ledger without invoking another model or changing ranking logic.
    """
    from mindmargin.intelligence.instrumentation import record_decision, record_event

    candidates: list[dict] = []

    def choose(topic: str, source: str, rationale: str, confidence: float = 0.0) -> str:
        options = candidates or [{"option": topic, "score": 0.0, "source": source}]
        decision = record_decision(
            "topic_selection",
            pipeline_id=pipeline_id,
            context={"selection_source": source},
            options=options,
            selected_option=topic,
            rationale=rationale,
            confidence=float(confidence or 0.0),
            evidence=[{"source": option.get("source", source), "score": option.get("score", 0)} for option in options],
            expected_outcome={"metric": "retention_3s", "direction": "increase"} if confidence else None,
            source="agents.decision_executor.select_topic",
            correlation_id=pipeline_id,
        )
        record_event("decision.topic_selected", pipeline_id, stage="topic_selection", reason=rationale, decision_id=decision.get("decision_id", ""), metadata={"selected_option": topic})
        return topic

    # Step 1: intelligence opportunities
    try:
        from mindmargin.analytics.memory import get_top_opportunities, get_execution_log
        opportunities = get_top_opportunities(20)
        published_topics = {
            (log.get("topic") or "").strip().lower()
            for log in get_execution_log(100) if not log.get("error", "") and log.get("topic")
        }
        candidates = [
            {"option": (opp.get("topic") or "").strip(), "score": opp.get("opportunity_score", 0),
             "confidence": opp.get("confidence", 0), "source": "opportunity_scores"}
            for opp in opportunities if (opp.get("topic") or "").strip()
        ]
        for option in candidates:
            if option["option"].lower() not in published_topics:
                logger.info("Topic from intelligence: '%s' (score=%.1f)", option["option"], option["score"])
                return choose(option["option"], "opportunity_scores", "highest scored unpublished opportunity", option.get("confidence", 0))
    except Exception as exc:
        logger.warning("Intelligence topic selection failed: %s", exc)

    topic = (brain_report.get("top_topic") or "").strip()
    if topic:
        candidates = [{"option": topic, "score": brain_report.get("topic_score", 0), "source": "channel_brain"}]
        return choose(topic, "channel_brain", "brain top topic fallback", brain_report.get("confidence", 0))

    top_recs = growth_report.get("top_recommendations") or []
    if top_recs:
        topic = (top_recs[0] or "").strip()
        if topic:
            candidates = [{"option": item, "score": len(top_recs) - index, "source": "growth_engine"} for index, item in enumerate(top_recs) if item]
            return choose(topic, "growth_engine", "top growth recommendation fallback")

    lineages = get_topic_lineages(limit=50)
    unpublished = [lineage for lineage in lineages if not lineage.get("is_published")]
    if unpublished:
        best = max(unpublished, key=lambda item: item.get("performance_inheritance", 0) or 0)
        topic = (best.get("child_topic") or "").strip()
        if topic:
            candidates = [{"option": item.get("child_topic", ""), "score": item.get("performance_inheritance", 0), "source": "topic_lineage"} for item in unpublished]
            return choose(topic, "topic_lineage", "highest performance inheritance among unpublished descendants", best.get("performance_inheritance", 0))

    topic = _TOPIC_DOMAINS[0]
    return choose(topic, "fallback_domain", "no scored unpublished candidate was available")


def execute_pipeline(topic: str, quick: bool = False,
                     editing_timeout: int | None = None, pipeline_id: str | None = None) -> dict:
    """Run the content generation pipeline for a given topic."""
    scale = 0.1 if quick else 1.0
    pipeline_kwargs = {"topic": topic, "duration_scale": scale, "editing_timeout": editing_timeout}
    if pipeline_id is not None:
        pipeline_kwargs["pipeline_id"] = pipeline_id
    pipe = Pipeline(**pipeline_kwargs)
    result = pipe.run()
    return result


def publish_video(topic: str, pipeline_id: str, result: dict,
                  privacy: str = "unlisted", playlist_id: str | None = None) -> dict:
    """Publish a completed pipeline's video to YouTube."""
    import time as _time
    from mindmargin.integrations.youtube import check_credentials, upload_video
    from mindmargin.agents.thumbnail import ThumbnailAgent, pick_best_thumbnail
    from mindmargin.agents.metadata import MetadataAgent
    from mindmargin.core.storage import project_dir
    from mindmargin.analytics.memory import _get_db
    import json as _json

    _pub_start = _time.time()
    from mindmargin.intelligence.instrumentation import record_decision, record_event

    def publish_decision(status: str, rationale: str, *, selected: str = "", evidence: list[dict] | None = None, failure_reason: str = "", video_id: str = "", publish_id: str = "", actual_outcome: dict | None = None):
        return record_decision(
            "publish_eligibility" if status in {"blocked", "skipped"} else "publish",
            pipeline_id=pipeline_id,
            context={"privacy": privacy, "topic": topic, "status": status},
            options=[{"option": "publish"}, {"option": "skip"}, {"option": "retry"}],
            selected_option=selected or status,
            rationale=rationale,
            confidence=1.0 if status in {"completed", "blocked", "skipped"} else 0.0,
            evidence=evidence or [],
            actual_outcome=actual_outcome or {},
            video_id=video_id,
            publish_id=pipeline_id,
            source="agents.decision_executor.publish_video",
            status="failed" if failure_reason else "completed",
            failure_reason=failure_reason,
            idempotency_key=f"{pipeline_id}:publish:{status}:{failure_reason or selected or status}",
            correlation_id=pipeline_id,
        )

    # ── Fast-fail: validate YouTube credentials before any work ──
    creds = check_credentials()
    if not creds.get("authenticated"):
        error_msg = creds.get("error", "YouTube authentication required")
        logger.error(
            f" YouTube upload blocked: {error_msg}\n"
            f"   Fix: Ensure client_secrets.json and youtube_token.pickle exist.\n"
            f"   See: GITHUB_SETUP.md for OAuth setup instructions."
        )
        publish_decision("blocked", "YouTube credentials are not authenticated", selected="skip", failure_reason=error_msg)
        record_event("publish.blocked", pipeline_id, stage="publish", reason=error_msg)
        return {"status": "failed", "error": f"YouTube auth failed: {error_msg}"}

    # ── Duplicate publish protection ──
    if settings.production.enable_duplicate_detection:
        try:
            conn = _get_db()
            existing = conn.execute(
                "SELECT youtube_video_id, youtube_url FROM pipelines WHERE id = ? AND youtube_video_id != ''",
                (pipeline_id,)
            ).fetchone()
            if existing:
                logger.info(f"Duplicate protection: pipeline {pipeline_id} already published as "
                           f"{existing['youtube_video_id']}, skipping upload")
                publish_decision("skipped", "existing durable YouTube video found; duplicate upload prevented", selected="skip", video_id=existing["youtube_video_id"], publish_id=pipeline_id)
                record_event("publish.duplicate_skipped", pipeline_id, stage="publish", reason="existing_video", video_id=existing["youtube_video_id"], publish_id=pipeline_id)
                return {
                    "status": "completed",
                    "video_id": existing["youtube_video_id"],
                    "url": existing["youtube_url"],
                    "duplicate_skipped": True,
                    "error": "duplicate_skipped",
                }
        except Exception as e:
            logger.warning(f"Duplicate detection check failed: {e}")

    out_dir = Path(result.get("output_dir", ""))
    if not out_dir.exists():
        reason = f"Output directory not found: {out_dir}"
        publish_decision("failed", "publish input validation failed", selected="fail", failure_reason=reason)
        return {"status": "failed", "error": reason}

    script_path = out_dir / "script" / "script.json"
    if not script_path.exists():
        reason = f"script.json not found at {script_path}"
        publish_decision("failed", "publish input validation failed", selected="fail", failure_reason=reason)
        return {"status": "failed", "error": reason}

    script_data = _json.loads(script_path.read_text(encoding="utf-8"))

    # Thumbnails — check for pre-generated (parallel Phase 5D)
    thumb_result = {"thumbnails": {"variants": []}}
    thumbnail_path = None
    existing_thumbs = sorted((out_dir / "thumbnails").glob("*.png")) if (out_dir / "thumbnails").exists() else []
    if existing_thumbs:
        thumbnail_path = str(existing_thumbs[0])
        thumb_result["thumbnails"]["variants"] = [{"path": str(p)} for p in existing_thumbs]
        record_decision(
            "thumbnail_selection", pipeline_id=pipeline_id,
            context={"topic": topic},
            options=[{"option": str(p), "rank": index} for index, p in enumerate(existing_thumbs)],
            selected_option=thumbnail_path,
            rationale="first pre-generated thumbnail selected by existing pipeline policy",
            confidence=1.0,
            source="agents.decision_executor.publish_video",
            idempotency_key=f"{pipeline_id}:thumbnail_selection:{thumbnail_path}",
            correlation_id=pipeline_id,
        )
        logger.info(f"Thumbnails: {len(existing_thumbs)} existing variants (parallel gen)")
    else:
        logger.info("Generating thumbnails (no pre-generated found)...")
        thumb_agent = ThumbnailAgent()
        thumb_result = thumb_agent.run(topic, pipeline_id, script_data)
        thumbnail_path = pick_best_thumbnail(thumb_result.get("thumbnails", {}))
        variants = thumb_result.get("thumbnails", {}).get("variants", [])
        record_decision(
            "thumbnail_selection", pipeline_id=pipeline_id,
            context={"topic": topic},
            options=[{"option": item.get("path", ""), "style": item.get("style", ""), "rank": index} for index, item in enumerate(variants)],
            selected_option=thumbnail_path or "",
            rationale="existing thumbnail scoring policy selected the best generated variant",
            confidence=1.0 if thumbnail_path else 0.0,
            source="agents.decision_executor.publish_video",
            status="completed" if thumbnail_path else "failed",
            failure_reason="no thumbnail selected" if not thumbnail_path else "",
            idempotency_key=f"{pipeline_id}:thumbnail_selection:{thumbnail_path or 'none'}",
            correlation_id=pipeline_id,
        )

    # Metadata
    logger.info("Generating metadata...")
    meta_agent = MetadataAgent()
    meta_result = meta_agent.run(topic, pipeline_id, script_data)
    meta = meta_result.get("metadata", {})

    # Find video
    video_candidates = list(out_dir.glob("video/*_final.mp4"))
    if not video_candidates:
        reason = "No final MP4 found"
        publish_decision("failed", "publish input validation failed", selected="fail", failure_reason=reason)
        return {"status": "failed", "error": reason}
    video_path = str(video_candidates[0])

    best_title = meta.get("best_title", topic)
    record_decision(
        "title_selection", pipeline_id=pipeline_id,
        context={"topic": topic},
        options=[{"option": title, "rank": index} for index, title in enumerate(meta.get("all_titles", []) or [best_title])],
        selected_option=best_title,
        rationale="metadata agent selected best_title from generated title candidates",
        confidence=1.0 if best_title else 0.0,
        source="agents.decision_executor.publish_video",
        idempotency_key=f"{pipeline_id}:title_selection:{best_title}",
        correlation_id=pipeline_id,
    )
    description = meta.get("description", "")
    tags = meta.get("tags", [])

    logger.info(f"Publishing: '{best_title}' ({privacy})")
    up_result = upload_video(
        video_path=video_path,
        title=best_title,
        description=description,
        tags=tags,
        category_id=meta.get("category_id", "27"),
        privacy_status=privacy,
        playlist_id=playlist_id,
        thumbnail_path=thumbnail_path,
        pipeline_id=pipeline_id,
    )

    if up_result.get("status") == "completed":
        vid = up_result["video_id"]
        url = up_result["url"]
        save_pipeline(
            pipeline_id=pipeline_id, topic=topic,
            word_count=script_data.get("word_count", 0),
            video_path=video_path,
            thumbnail_path=thumbnail_path or "",
            youtube_video_id=vid,
            youtube_url=url,
        )
        save_titles(pipeline_id, meta.get("all_titles", []))
        save_hooks(pipeline_id, script_data.get("hooks", []))
        save_thumbnails(pipeline_id,
                        thumb_result.get("thumbnails", {}).get("variants", []))
        try:
            from mindmargin.analytics.ab_testing import seed_variants
            seed_variants(pipeline_id, vid)
        except Exception as e:
            logger.warning(f"AB seeding skipped: {e}")
        logger.info(f"Published: {url}")
        decision = publish_decision("completed", "YouTube upload completed", selected="publish", video_id=vid, publish_id=pipeline_id, actual_outcome={"status": "completed", "video_id": vid, "url": url})
        record_event("publish.completed", pipeline_id, stage="publish", decision_id=decision.get("decision_id", ""), reason="upload_completed", video_id=vid, publish_id=pipeline_id)

    # Record publish runtime
    _pub_duration = _time.time() - _pub_start
    try:
        from mindmargin.analytics.monitoring import record_event as record_metric_event
        record_metric_event("publish_runtime_seconds", pipeline_id, round(_pub_duration, 2),
                     metadata={"topic": topic, "video_id": up_result.get("video_id", "")})
    except Exception:
        pass

    if up_result.get("status") == "completed":
        return {"status": "completed", "video_id": vid, "url": url}
    reason = up_result.get("error", "upload failed")
    decision = publish_decision("failed", "YouTube upload did not complete", selected="fail", failure_reason=reason, actual_outcome={"status": "failed", "error": reason})
    record_event("publish.failed", pipeline_id, stage="publish", decision_id=decision.get("decision_id", ""), reason=reason, publish_id=pipeline_id)
    return {"status": "failed", "error": reason}


def log_execution(pipeline_id: str, topic: str,
                  decision_domain: str = "", decision_action: str = "",
                  decision_confidence: float = 0,
                  pipeline_status: str = "completed",
                  video_id: str = "", video_url: str = "",
                  error: str = "") -> None:
    """Save an execution record to the database.

    Only marks topic as published when pipeline completed AND a real video ID
    was returned (not duplicate_skipped).  Failed pipelines, skipped publishes,
    and duplicate detections never increment the daily publish counter.
    """
    save_execution_log(
        pipeline_id=pipeline_id, topic=topic,
        decision_domain=decision_domain, decision_action=decision_action,
        decision_confidence=decision_confidence,
        pipeline_status=pipeline_status,
        video_id=video_id, video_url=video_url,
        error=error,
    )
    # Only mark as published after a genuine successful YouTube upload.
    # Uses is_successful_publish() as the single source of truth.
    if is_successful_publish({
        "pipeline_status": pipeline_status,
        "video_id": video_id,
        "error": error,
    }):
        mark_topic_published(topic)
        logger.debug(f"Topic '{topic}' marked as published (video_id={video_id})")
    else:
        logger.debug(f"Topic '{topic}' NOT marked as published "
                     f"(status={pipeline_status}, video_id={video_id!r}, error={error!r})")


def _check_circuit_breaker() -> bool:
    """Check if the circuit breaker is tripped (MAX_CONSECUTIVE_FAILURES reached).

    Reads the last N execution logs. Only counts PIPELINE crashes as failures
    (pipeline_status != 'completed').  Blocked publishes (safety gate blocks)
    and transient upload API errors do NOT trip the breaker — they are expected
    to resolve on the next scheduled run.

    Returns True if the executor should block (circuit open).
    """
    global _CIRCUIT_BREAKER_TRIPPED
    if _CIRCUIT_BREAKER_TRIPPED:
        return True

    logs = get_execution_log(limit=MAX_CONSECUTIVE_FAILURES)
    if len(logs) < MAX_CONSECUTIVE_FAILURES:
        return False

    # Only pipeline crashes count — gate blocks and upload errors do not
    if all(l.get("pipeline_status") != "completed" for l in logs):
        _CIRCUIT_BREAKER_TRIPPED = True
        logger.critical(
            f"CIRCUIT BREAKER TRIPPED: {MAX_CONSECUTIVE_FAILURES} consecutive "
            f"pipeline failures detected. Decision executor disabled."
        )
        lasterr = logs[0].get("error", "unknown")
        lasts = logs[0].get("pipeline_status", "?")
        logger.critical(f"  Last: status={lasts} error={lasterr!r} topic={logs[0].get('topic', '')!r}")
        try:
            from mindmargin.analytics.monitoring import record_event
            record_event(
                category="executor",
                label="circuit_breaker_tripped",
                metadata={"reason": f"{MAX_CONSECUTIVE_FAILURES} consecutive pipeline crashes",
                          "last_error": lasterr,
                          "last_topic": logs[0].get("topic", "")},
            )
        except Exception:
            logger.warning("Failed to record circuit breaker metric")
        return True

    return False


def reset_circuit_breaker() -> None:
    """Manually reset the circuit breaker after resolving the underlying issue."""
    global _CIRCUIT_BREAKER_TRIPPED
    _CIRCUIT_BREAKER_TRIPPED = False
    logger.info("Circuit breaker manually reset")


def _check_channel_health() -> tuple[bool, str]:
    """Check if channel health meets the minimum threshold for publishing.

    Returns (blocked: bool, reason: str).
    """
    try:
        from mindmargin.analytics.channel_brain import run_brain_cycle
        brain = run_brain_cycle()
        health = brain.get("channel_health", {}).get("score", 10)
        total_videos = brain.get("channel_health", {}).get("total_videos", 0)
        # Bootstrap: allow publishing while building the initial catalog.
        # With 0 classified videos the health score is ~2.25, but
        # content_volume grows by 2 per publish. After 4 publishes
        # (total_videos=4), content_volume=8 gives health=4.25 >= 4.0.
        if total_videos < 4:
            logger.info(
                f"Bootstrap mode: {total_videos} videos, health={health}, "
                f"allowing publish"
            )
            return False, ""
        if health < MIN_CHANNEL_HEALTH:
            return True, f"channel_health {health:.1f} < {MIN_CHANNEL_HEALTH}"
        return False, ""
    except Exception as e:
        logger.warning(f"Channel health check failed: {e}")
        return False, ""


def _check_daily_publish_cap() -> tuple[bool, str]:
    """Check if the daily publish limit has been reached.

    Returns (blocked: bool, reason: str).
    Uses is_successful_publish() as the single source of truth —
    only real YouTube uploads (pipeline completed + video_id present + no error)
    count toward the daily cap.
    """
    try:
        from mindmargin.analytics.memory import get_execution_log
        from datetime import datetime, timedelta
        cutoff = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
        logs = get_execution_log(limit=50)
        recent = [l for l in logs
                  if l.get("executed_at", "") >= cutoff
                  and is_successful_publish(l)]
        logger.debug(
            f"Daily cap check: cutoff={cutoff}, total_logs={len(logs)}, "
            f"recent_successful={len(recent)}, cap={MAX_DAILY_PUBLISH}"
        )
        if recent:
            for l in recent:
                logger.debug(
                    f"  counting: pipeline={l.get('pipeline_id', '?')} "
                    f"topic={l.get('topic', '?')!r} "
                    f"video_id={l.get('video_id', '')!r} "
                    f"executed_at={l.get('executed_at', '?')}"
                )
        if len(recent) >= MAX_DAILY_PUBLISH:
            return True, f"daily cap {MAX_DAILY_PUBLISH} reached ({len(recent)} published today)"
        return False, ""
    except Exception as e:
        logger.warning(f"Daily cap check failed: {e}")
        return False, ""


def execute_top_decision(quick: bool = False, privacy: str = "unlisted",
                         auto_publish: bool = True) -> dict:
    """Run one complete autonomous cycle: brain -> topic -> pipeline -> publish -> log.

    This is the single entry point that closes the feedback loop.

    Args:
        quick: If True, use 0.1x duration scale for fast testing.
        privacy: YouTube privacy status for publishing.
        auto_publish: If True, publish after pipeline completes.

    Returns:
        dict with full execution report.
    """
    logger.info("=" * 55)
    logger.info("  DECISION EXECUTOR — Autonomous Cycle Starting")
    logger.info("=" * 55)

    planned_pipeline_id = f"pipe_{datetime.utcnow().strftime('%Y%m%d_%H%M%S_%f')}_{uuid.uuid4().hex[:6]}"
    cycle = {
        "status": "running",
        "started_at": datetime.utcnow().isoformat(),
        "pipeline_id": planned_pipeline_id,
        "steps": {},
    }

    # Circuit breaker: block if MAX_CONSECUTIVE_FAILURES reached
    if _check_circuit_breaker():
        cycle["status"] = "disabled"
        cycle["error"] = (
            f"Circuit breaker open: {MAX_CONSECUTIVE_FAILURES} consecutive "
            f"pipeline failures. Call reset_circuit_breaker() after fixing."
        )
        logger.critical(f"Decision executor blocked: {cycle['error']}")
        return cycle

    # Step 1: Run channel brain
    logger.info("Step 1/4: Running Channel Brain...")
    try:
        from mindmargin.analytics.channel_brain import run_brain_cycle
        brain = run_brain_cycle()
        cycle["steps"]["brain"] = {"status": "completed", "decisions": len(brain.get("decisions", []))}
    except Exception as e:
        logger.error(f"Brain cycle failed: {e}")
        cycle["steps"]["brain"] = {"status": "failed", "error": str(e)}
        brain = {}

    # Step 2: Run growth analysis for topic selection fallback
    logger.info("Step 2/4: Running Growth Analysis...")
    try:
        from mindmargin.analytics.growth_engine import run_growth_analysis
        growth = run_growth_analysis()
        cycle["steps"]["growth"] = {"status": "completed", "opportunities": len(growth.get("opportunities", []))}
    except Exception as e:
        logger.error(f"Growth analysis failed: {e}")
        cycle["steps"]["growth"] = {"status": "failed", "error": str(e)}
        growth = {}

    # Step 2.5: Bootstrap intelligence if no opportunities exist yet
    try:
        from mindmargin.analytics.memory import get_top_opportunities
        if not get_top_opportunities(1):
            logger.info("No intelligence opportunities found — running on-demand scoring...")
            from mindmargin.intelligence.scoring import run_opportunity_scoring
            run_opportunity_scoring()
    except Exception as e:
        logger.warning(f"Intelligence bootstrap failed: {e}")

    # Step 3: Select topic
    logger.info("Selecting topic...")
    topic = select_topic(brain, growth, pipeline_id=planned_pipeline_id)
    if not topic:
        cycle["status"] = "failed"
        cycle["error"] = "No topic could be selected"
        return cycle

    # Extract decision info for logging
    decision_domain = ""
    decision_action = ""
    decision_confidence = 0
    for d in brain.get("decisions", []):
        if d.get("domain") == "topic":
            decision_domain = d["domain"]
            decision_action = d["action"]
            decision_confidence = d.get("confidence", 0)
            break

    cycle["selected_topic"] = topic
    logger.info(f"Selected topic: '{topic}'")

    # Confidence gate: skip if brain decision confidence is too low
    # Bypass when the autonomous system has never completed a pipeline (bootstrap)
    from mindmargin.analytics.memory import get_execution_log
    if not get_execution_log(limit=1):
        logger.info("Confidence gate bypassed: no execution history (bootstrap mode)")
    elif decision_confidence < MIN_CONFIDENCE:
        logger.warning(
            f"Confidence gate: decision confidence {decision_confidence:.2f} < "
            f"{MIN_CONFIDENCE:.2f}. Skipping execution."
        )
        cycle["status"] = "skipped"
        cycle["reason"] = "low_confidence"
        cycle["decision_confidence"] = decision_confidence
        cycle["min_confidence"] = MIN_CONFIDENCE
        return cycle

    # Phase 5: Generate explanation for this decision
    try:
        from mindmargin.intelligence.explainer import explain_decision, format_explanation_markdown
        from mindmargin.analytics.memory import get_top_opportunities
        all_opps = get_top_opportunities(20)
        selected_opp = next((o for o in all_opps if o.get("topic", "").lower() == topic.lower()), {})
        alternatives = [o for o in all_opps if o.get("topic", "").lower() != topic.lower()]
        explanation = explain_decision(selected_opp or {"topic": topic, "opportunity_score": 0, "confidence": 0}, alternatives[:5])
        cycle["explanation"] = explanation
        explanation_md = format_explanation_markdown(explanation)
        logger.info(f"Decision explanation:\n{explanation_md}")
    except Exception as e:
        logger.warning(f"Explanation generation failed: {e}")

    # Step 4: Run content pipeline
    logger.info("Step 3/4: Running Content Pipeline...")
    try:
        pipe_result = execute_pipeline(topic, quick=quick, pipeline_id=planned_pipeline_id)
        pipeline_status = pipe_result.get("status", "failed")
        pipeline_id = pipe_result.get("pipeline_id", planned_pipeline_id)
        cycle["steps"]["pipeline"] = {
            "status": pipeline_status,
            "pipeline_id": pipeline_id,
            "timing_s": pipe_result.get("timing_s", 0),
        }
    except Exception as e:
        pipeline_status = "failed"
        pipeline_id = f"pipe_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
        cycle["steps"]["pipeline"] = {"status": "failed", "error": str(e)}
        log_execution(pipeline_id, topic, decision_domain, decision_action,
                      decision_confidence, "failed", error=str(e))
        cycle["status"] = "failed"
        cycle["error"] = str(e)
        return cycle

    if pipeline_status != "completed":
        log_execution(pipeline_id, topic, decision_domain, decision_action,
                      decision_confidence, pipeline_status, error="pipeline failed")
        cycle["status"] = "failed"
        cycle["error"] = f"Pipeline {pipeline_status}"
        return cycle

    # Save pipeline result to memory
    save_pipeline_result(pipeline_id, pipe_result)

    # Step 5: Publish (optional)
    from mindmargin.intelligence.instrumentation import record_decision, record_event
    pub_status = "skipped"
    pub_video_id = ""
    pub_url = ""
    if auto_publish:
        logger.info("Publish gate checks starting...")
        # Channel health gate
        health_blocked, health_reason = _check_channel_health()
        if health_blocked:
            logger.warning(f"Channel health gate BLOCKED: {health_reason}")
            record_decision("publish_eligibility", pipeline_id=pipeline_id, context={"gate": "channel_health"}, options=[{"option": "publish"}, {"option": "skip"}], selected_option="skip", rationale="channel health policy blocked publication", confidence=1.0, evidence=[{"gate": "channel_health", "reason": health_reason}], source="agents.decision_executor.execute_top_decision", status="completed", idempotency_key=f"{pipeline_id}:eligibility:channel_health:{health_reason}", correlation_id=pipeline_id)
            record_event("publish.blocked", pipeline_id, stage="eligibility", reason=health_reason)
            cycle["steps"]["publish"] = {"status": "blocked", "reason": health_reason}
        else:
            logger.info("Channel health gate: PASSED")
            # Daily publish cap
            cap_blocked, cap_reason = _check_daily_publish_cap()
            if cap_blocked:
                logger.warning(f"Daily publish cap BLOCKED: {cap_reason}")
                record_decision("publish_eligibility", pipeline_id=pipeline_id, context={"gate": "daily_cap"}, options=[{"option": "publish"}, {"option": "skip"}], selected_option="skip", rationale="daily publish cap blocked publication", confidence=1.0, evidence=[{"gate": "daily_cap", "reason": cap_reason}], source="agents.decision_executor.execute_top_decision", status="completed", idempotency_key=f"{pipeline_id}:eligibility:daily_cap:{cap_reason}", correlation_id=pipeline_id)
                record_event("publish.blocked", pipeline_id, stage="eligibility", reason=cap_reason)
                cycle["steps"]["publish"] = {"status": "blocked", "reason": cap_reason}
            else:
                logger.info("Daily publish cap: PASSED")
                logger.info("Step 4/4: Publishing to YouTube...")
                try:
                    pub_result = publish_video(topic, pipeline_id, pipe_result, privacy=privacy)
                    pub_status = pub_result.get("status", "failed")
                    pub_video_id = pub_result.get("video_id", "")
                    pub_url = pub_result.get("url", "")
                    cycle["steps"]["publish"] = {"status": pub_status, "video_id": pub_video_id}
                    if pub_status != "completed":
                        logger.warning(f"Publish: {pub_status} — {pub_result.get('error', '')}")
                except Exception as e:
                    pub_status = "failed"
                    cycle["steps"]["publish"] = {"status": "failed", "error": str(e)}
                    logger.error(f"Publish failed: {e}")

    if not auto_publish:
        record_decision("publish_eligibility", pipeline_id=pipeline_id, context={"auto_publish": False}, options=[{"option": "publish"}, {"option": "skip"}], selected_option="skip", rationale="caller disabled automatic publication", confidence=1.0, source="agents.decision_executor.execute_top_decision", idempotency_key=f"{pipeline_id}:eligibility:auto_publish:false", correlation_id=pipeline_id)
        record_event("publish.skipped", pipeline_id, stage="eligibility", reason="auto_publish_false")

    # Log execution with accurate error — only empty when a real upload occurred.
    # is_successful_publish() checks bool(video_id), so blocked/skipped publishes
    # are never counted toward the daily cap regardless of the error value.
    log_error = "" if pub_video_id else (
        "pipeline failed" if pipeline_status != "completed" else
        "publish skipped (auto_publish=False)" if not auto_publish else
        cycle["steps"].get("publish", {}).get("reason")
        or cycle["steps"].get("publish", {}).get("error", "publish blocked or failed")
    )
    logger.info(
        f"Logging execution: pipeline_id={pipeline_id} topic={topic!r} "
        f"pipeline_status={pipeline_status} pub_video_id={pub_video_id!r} "
        f"log_error={log_error!r}"
    )
    log_execution(
        pipeline_id, topic,
        decision_domain, decision_action, decision_confidence,
        pipeline_status, pub_video_id, pub_url,
        error=log_error,
    )

    cycle["status"] = "completed"
    cycle["pipeline_id"] = pipeline_id
    cycle["pipeline_status"] = pipeline_status
    cycle["publish_status"] = pub_status
    cycle["video_id"] = pub_video_id
    cycle["video_url"] = pub_url
    cycle["completed_at"] = datetime.utcnow().isoformat()

    logger.info("=" * 55)
    logger.info(f"  Cycle complete: topic='{topic}' status={pipeline_status} publish={pub_status}")
    if pub_url:
        logger.info(f"  Published: {pub_url}")
    logger.info("=" * 55)

    return cycle


def format_execution_report(cycle: dict) -> str:
    """Format the execution cycle result as a human-readable report."""
    lines = [
        "=" * 55,
        "  AUTONOMOUS CYCLE REPORT",
        "=" * 55,
        f"  Status:      {cycle.get('status', 'unknown')}",
    ]
    if cycle.get("status") == "disabled":
        lines.append(f"  Error:       {cycle.get('error', 'Circuit breaker open')}")
    elif cycle.get("status") == "skipped":
        lines.append(f"  Reason:      {cycle.get('reason', 'unknown')}")
        lines.append(f"  Confidence:  {cycle.get('decision_confidence', 'N/A')}")
        lines.append(f"  Min allowed: {cycle.get('min_confidence', 'N/A')}")
    else:
        lines.append(f"  Topic:       {cycle.get('selected_topic', 'N/A')}")
        lines.append(f"  Pipeline:    {cycle.get('pipeline_id', 'N/A')}")
        lines.append(f"  Pipeline:    {cycle.get('pipeline_status', 'N/A')}")
        lines.append(f"  Publish:     {cycle.get('publish_status', 'N/A')}")
        if cycle.get("video_url"):
            lines.append(f"  URL:         {cycle['video_url']}")
        if cycle.get("error"):
            lines.append(f"  Error:       {cycle['error']}")

        steps = cycle.get("steps", {})
        lines.append("")
        lines.append("  Steps:")
        for name, info in steps.items():
            status = info.get("status", "?")
            detail = ""
            if name == "brain":
                detail = f" ({info.get('decisions', 0)} decisions)"
            elif name == "growth":
                detail = f" ({info.get('opportunities', 0)} opportunities)"
            elif name == "pipeline":
                detail = f" ({info.get('timing_s', 0)}s)"
            elif name == "publish":
                detail = f" ({info.get('video_id', '')[:8]})" if info.get("video_id") else ""
            lines.append(f"    {name:10s}: {status}{detail}")

    lines.extend(["", "=" * 55])
    return "\n".join(lines)
