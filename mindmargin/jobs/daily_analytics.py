"""Daily analytics collection job: polls YouTube for all published videos, updates best practices."""

import logging
import time
from datetime import datetime, timedelta
from typing import Optional

from mindmargin.analytics.memory import (
    get_pipeline_history, save_analytics, save_best_practice,
    get_best_practices,
)
from mindmargin.analytics.patterns import full_pattern_analysis
from mindmargin.analytics.feedback import collect_analytics
from mindmargin.config import settings

logger = logging.getLogger(__name__)


def collect_all_analytics() -> dict:
    """Collect analytics for every published video in the database."""
    history = get_pipeline_history(200)
    published = [p for p in history if p.get("youtube_video_id")]

    if not published:
        logger.info("No published videos found to collect analytics for")
        return {"status": "skipped", "videos_collected": 0}

    results = []
    errors = []
    for p in published:
        video_id = p["youtube_video_id"]
        pipeline_id = p["id"]
        try:
            stats = collect_analytics(pipeline_id, video_id)
            if stats.get("status") == "completed":
                results.append({
                    "pipeline_id": pipeline_id,
                    "video_id": video_id,
                    "views": stats.get("views", 0),
                })
                logger.info(f"Collected: {p['topic']} ({stats.get('views', 0)} views)")
            else:
                errors.append({"video_id": video_id, "error": stats.get("error", "unknown")})
        except Exception as e:
            errors.append({"video_id": video_id, "error": str(e)})
            logger.warning(f"Failed to collect analytics for {video_id}: {e}")

        # Rate limit: 1 request per second
        time.sleep(1.0)

    summary = {
        "status": "completed",
        "videos_collected": len(results),
        "errors": len(errors),
        "error_details": errors[:5],
        "results": results,
        "collected_at": datetime.utcnow().isoformat(),
    }
    logger.info(f"Analytics collection: {len(results)} videos, {len(errors)} errors")
    return summary


def run_feedback_loop() -> dict:
    """Run full feedback loop: collect analytics, analyze patterns, update best practices."""
    logger.info("=== Daily Analytics Job Starting ===")

    # Step 1: Collect fresh analytics
    logger.info("Step 1/6: Collecting analytics from YouTube...")
    try:
        analytics_result = collect_all_analytics()
    except Exception as e:
        logger.warning(f"Analytics collection failed: {e}")
        analytics_result = {"status": "failed", "videos_collected": 0, "errors": 1}

    # Step 2: Run pattern analysis
    logger.info("Step 2/6: Running pattern analysis...")
    try:
        patterns = full_pattern_analysis()
    except Exception as e:
        logger.warning(f"Pattern analysis failed: {e}")
        patterns = {"retention": {"status": "failed"}, "hooks": {"status": "failed"},
                    "pacing": {"status": "failed"}, "topics": {"status": "failed"}}

    # Step 3: Generate adaptive recommendations
    logger.info("Step 3/6: Generating adaptive recommendations...")
    try:
        recommendations = _generate_recommendations()
    except Exception as e:
        logger.warning(f"Recommendation generation failed: {e}")
        recommendations = []

    # Step 4: Run A/B rotation cycle
    logger.info("Step 4/6: Running A/B rotation cycle...")
    try:
        from mindmargin.analytics.ab_testing import run_ab_rotation_cycle
        ab_result = run_ab_rotation_cycle(dry_run=False)
        logger.info(f"AB rotation: {ab_result.get('actions_taken', 0)} actions, "
                    f"{ab_result.get('active_tests', 0)} active tests")
    except Exception as e:
        logger.warning(f"AB rotation failed: {e}")
        ab_result = {"status": "failed", "error": str(e)}

    # Step 5: Run Selection Pressure cycle (classify → reinforce → suppress → expand)
    logger.info("Step 5/6: Running selection pressure cycle...")
    try:
        from mindmargin.analytics.selection import run_selection_cycle
        selection_result = run_selection_cycle()
        sel_memory = selection_result.get("memory", {})
        logger.info(f"Selection cycle: "
                    f"{sel_memory.get('reinforced_count', 0)} reinforced, "
                    f"{sel_memory.get('suppressed_count', 0)} suppressed, "
                    f"{sel_memory.get('dead_count', 0)} dead patterns")
    except Exception as e:
        logger.warning(f"Selection cycle failed: {e}")
        selection_result = {"status": "failed", "error": str(e),
                            "memory": {}}

    # Step 6: Run Decision Executor (brain -> pipeline -> publish)
    logger.info("Step 6/6: Running decision executor cycle...")
    try:
        from mindmargin.agents.decision_executor import execute_top_decision
        exec_result = execute_top_decision(auto_publish=True)
        logger.info(f"Executor cycle: topic='{exec_result.get('selected_topic', '')}' "
                    f"status={exec_result.get('status', '?')} "
                    f"publish={exec_result.get('publish_status', '?')}")
    except Exception as e:
        logger.warning(f"Decision executor failed: {e}")
        exec_result = {"status": "failed", "error": str(e)}

    total_best_practices = len(get_best_practices())

    sel_memory = selection_result.get("memory", {})
    result = {
        "status": "completed",
        "analytics_collected": analytics_result.get("videos_collected", 0),
        "analytics_errors": analytics_result.get("errors", 0),
        "patterns": {
            "retention": patterns["retention"]["status"],
            "hooks": patterns["hooks"]["status"],
            "pacing": patterns["pacing"]["status"],
            "topics": patterns["topics"]["status"],
        },
        "total_best_practices": total_best_practices,
        "recommendations": recommendations,
        "ab_rotation": {
            "actions_taken": ab_result.get("actions_taken", 0),
            "active_tests": ab_result.get("active_tests", 0),
        },
        "selection_pressure": {
            "reinforced": sel_memory.get("reinforced_count", 0),
            "suppressed": sel_memory.get("suppressed_count", 0),
            "dead": sel_memory.get("dead_count", 0),
            "classified": sel_memory.get("total_classified", 0),
            "topic_suggestions": len([l for l in sel_memory.get("topic_suggestions", [])
                                       if not l.get("is_published")]),
        },
        "decision_executor": {
            "status": exec_result.get("status", "skipped"),
            "topic": exec_result.get("selected_topic", ""),
            "pipeline_status": exec_result.get("pipeline_status", ""),
            "publish_status": exec_result.get("publish_status", ""),
        },
        "completed_at": datetime.utcnow().isoformat(),
    }

    logger.info(f"=== Daily Analytics Job Complete ===")
    logger.info(f"  Videos collected: {result['analytics_collected']}")
    logger.info(f"  Best practices: {total_best_practices}")
    logger.info(f"  Recommendations: {len(recommendations)}")
    logger.info(f"  AB rotations: {result['ab_rotation']['actions_taken']}")
    logger.info(f"  Selection: {result['selection_pressure']['reinforced']} reinforced, "
                f"{result['selection_pressure']['suppressed']} suppressed, "
                f"{result['selection_pressure']['dead']} dead")

    return result


def _generate_recommendations() -> list[dict]:
    """Generate adaptive content recommendations from all stored data."""
    practices = get_best_practices()
    recs = []

    # Hook recommendations
    hook_practices = [p for p in practices if p["category"] == "hook_archetype"]
    if hook_practices:
        best_hook = max(hook_practices, key=lambda x: x["score"])
        recs.append({
            "category": "hooks",
            "recommendation": f"Use '{best_hook['key']}' hook archetype (score: {best_hook['score']:.0f})",
            "confidence": min(best_hook["score"] / 100, 1.0),
        })

    # Engagement recommendations
    eng_practices = [p for p in practices if p["category"] == "engagement"]
    for p in eng_practices:
        recs.append({
            "category": "engagement",
            "recommendation": p["value"],
            "confidence": min(p["score"] / 100, 1.0),
        })

    # Retention recommendations
    ret_practices = [p for p in practices if p["category"] == "retention"]
    if ret_practices:
        best_ret = max(ret_practices, key=lambda x: x["score"])
        recs.append({
            "category": "retention",
            "recommendation": best_ret["value"],
            "confidence": min(best_ret["score"] / 100, 1.0),
        })

    # Pacing recommendations
    pac_practices = [p for p in practices if p["category"] == "pacing"]
    if pac_practices:
        best_pac = max(pac_practices, key=lambda x: x["score"])
        recs.append({
            "category": "pacing",
            "recommendation": best_pac["value"],
            "confidence": min(best_pac["score"] / 100, 1.0),
        })

    return recs


def run_daily_job() -> dict:
    """Entry point for daily analytics job. Can be called from CLI or scheduler."""
    try:
        return run_feedback_loop()
    except Exception as e:
        logger.error(f"Daily analytics job failed: {e}")
        return {
            "status": "failed",
            "error": str(e),
            "completed_at": datetime.utcnow().isoformat(),
        }
