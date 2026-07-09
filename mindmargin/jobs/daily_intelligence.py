"""Daily intelligence job: complete intelligence pipeline.

Full cycle:
  1. Trend Collection + Opportunity Scoring (with confidence — Phase 4)
  2. Performance Analysis
  3. Self-Learning Cycle
  4. Channel Memory Update
  5. Daily Strategy Planning
  6. Feedback Cycle (Phases 1+2)
  7. Experiment Engine (Phase 3)
  8. Knowledge Graph Build (Phase 7)
  9. Prediction Horizon (Phase 8)
 10. Weekly Planner (Phase 6) — Mondays
 11. Weekly Report — Sundays
"""

import logging
from datetime import datetime as _datetime

from mindmargin.config import settings

logger = logging.getLogger(__name__)


def run_intelligence_cycle() -> dict:
    """Run the full daily intelligence cycle.

    Returns:
        dict with status and per-stage results.
    """
    logger.info("=" * 55)
    logger.info("  DAILY INTELLIGENCE CYCLE Starting")
    logger.info("=" * 55)

    cycle = {
        "status": "running",
            "started_at": _datetime.utcnow().isoformat(),
        "stages": {},
    }

    # Stage 1: Trend Collection + Opportunity Scoring (+ Phase 4 confidence)
    logger.info("Stage 1/11: Collecting trends, scoring, estimating confidence...")
    try:
        from mindmargin.intelligence.scoring import run_opportunity_scoring
        scored = run_opportunity_scoring()
        cycle["stages"]["scoring"] = {
            "status": "completed",
            "candidates": len(scored),
        }
        logger.info(f"Scoring: {len(scored)} opportunities with confidence")
    except Exception as e:
        logger.error(f"Scoring failed: {e}")
        cycle["stages"]["scoring"] = {"status": "failed", "error": str(e)}

    # Stage 2: Performance Analysis
    logger.info("Stage 2/11: Analyzing content performance...")
    try:
        from mindmargin.intelligence.performance import run_performance_analysis
        insights = run_performance_analysis()
        cycle["stages"]["performance"] = {
            "status": "completed",
            "insights": len(insights),
        }
        logger.info(f"Performance: {len(insights)} insights")
    except Exception as e:
        logger.error(f"Performance analysis failed: {e}")
        cycle["stages"]["performance"] = {"status": "failed", "error": str(e)}

    # Stage 3: Self-Learning Cycle
    logger.info("Stage 3/11: Running self-learning cycle...")
    try:
        from mindmargin.intelligence.learning import run_learning_cycle
        rules = run_learning_cycle()
        cycle["stages"]["learning"] = {
            "status": "completed",
            "rules": len(rules),
        }
        logger.info(f"Learning: {len(rules)} rules")
    except Exception as e:
        logger.error(f"Learning cycle failed: {e}")
        cycle["stages"]["learning"] = {"status": "failed", "error": str(e)}

    # Stage 4: Channel Memory Update
    logger.info("Stage 4/11: Updating channel memory...")
    try:
        from mindmargin.intelligence.channel_memory import update_channel_memory_from_history
        new_entries = update_channel_memory_from_history()
        cycle["stages"]["memory"] = {
            "status": "completed",
            "new_entries": new_entries,
        }
        logger.info(f"Memory: {new_entries} new entries")
    except Exception as e:
        logger.error(f"Channel memory update failed: {e}")
        cycle["stages"]["memory"] = {"status": "failed", "error": str(e)}

    # Stage 5: Daily Strategy Planning
    logger.info("Stage 5/11: Generating daily strategy...")
    try:
        from mindmargin.intelligence.strategy import run_daily_planning
        strategy = run_daily_planning()
        cycle["stages"]["strategy"] = {
            "status": "completed",
            "top_pick": strategy.get("recommended_topic", ""),
            "ranked": strategy.get("ranked_count", 0),
        }
        logger.info(f"Strategy: top={strategy.get('recommended_topic', '')}")
    except Exception as e:
        logger.error(f"Strategy planning failed: {e}")
        cycle["stages"]["strategy"] = {"status": "failed", "error": str(e)}

    # Stage 6: Feedback Cycle — outcome tracking + weight learning (Phases 1+2)
    logger.info("Stage 6/11: Running feedback cycle...")
    try:
        from mindmargin.intelligence.feedback_engine import run_feedback_cycle
        feedback = run_feedback_cycle()
        cycle["stages"]["feedback"] = {
            "status": "completed",
            "outcomes_collected": feedback.get("outcomes_collected", 0),
            "weights_changed": feedback.get("weights_changed", 0),
        }
        logger.info(f"Feedback: {feedback.get('outcomes_collected', 0)} outcomes, "
                    f"{feedback.get('weights_changed', 0)} weights changed")
    except Exception as e:
        logger.error(f"Feedback cycle failed: {e}")
        cycle["stages"]["feedback"] = {"status": "failed", "error": str(e)}

    # Stage 7: Experiment Engine (Phase 3)
    logger.info("Stage 7/11: Running experiment engine...")
    try:
        from mindmargin.intelligence.experiments import run_experiment_cycle
        exp_result = run_experiment_cycle()
        cycle["stages"]["experiments"] = {
            "status": "completed",
            "new_hypotheses": exp_result.get("new_hypotheses", 0),
            "completed": exp_result.get("experiments_completed", 0),
        }
        logger.info(f"Experiments: {exp_result.get('new_hypotheses', 0)} new, "
                    f"{exp_result.get('experiments_completed', 0)} evaluated")
    except Exception as e:
        logger.error(f"Experiment engine failed: {e}")
        cycle["stages"]["experiments"] = {"status": "failed", "error": str(e)}

    # Stage 8: Knowledge Graph Build (Phase 7)
    logger.info("Stage 8/11: Building knowledge graph...")
    try:
        from mindmargin.intelligence.knowledge_graph import build_knowledge_graph
        kg_result = build_knowledge_graph()
        cycle["stages"]["knowledge_graph"] = {
            "status": "completed",
            "topics": kg_result.get("topics_found", 0),
            "relationships": kg_result.get("relationships_created", 0),
        }
        logger.info(f"Knowledge graph: {kg_result.get('topics_found', 0)} topics, "
                    f"{kg_result.get('relationships_created', 0)} relationships")
    except Exception as e:
        logger.error(f"Knowledge graph build failed: {e}")
        cycle["stages"]["knowledge_graph"] = {"status": "failed", "error": str(e)}

    # Stage 9: Prediction Horizon (Phase 8)
    logger.info("Stage 9/11: Generating prediction forecasts...")
    try:
        from mindmargin.intelligence.horizon import forecast_all
        forecasts = forecast_all()
        cycle["stages"]["forecasts"] = {
            "status": "completed",
            "forecasts": len(forecasts),
        }
        logger.info(f"Forecasts: {len(forecasts)} generated across 5 windows")
    except Exception as e:
        logger.error(f"Prediction horizon failed: {e}")
        cycle["stages"]["forecasts"] = {"status": "failed", "error": str(e)}

    # Stage 10: Weekly Planner (Phase 6) — runs on Mondays
    if _datetime.utcnow().weekday() == 0:
        logger.info("Stage 10/11: Generating weekly plan (Monday)...")
        try:
            from mindmargin.intelligence.planner import plan_week
            plan = plan_week()
            cycle["stages"]["weekly_plan"] = {
                "status": "completed",
                "items": plan.get("summary", {}).get("total_items", 0),
            }
        except Exception as e:
            logger.error(f"Weekly planner failed: {e}")
            cycle["stages"]["weekly_plan"] = {"status": "failed", "error": str(e)}
    else:
        cycle["stages"]["weekly_plan"] = {"status": "skipped", "reason": "not_monday"}
        logger.info("Stage 10/11: Skipping weekly plan (not Monday)")

    # Stage 11: Weekly Report — runs on Sundays
    if _datetime.utcnow().weekday() == 6:
        logger.info("Stage 11/11: Generating weekly report (Sunday)...")
        try:
            from mindmargin.intelligence.reports import run_weekly_report
            report = run_weekly_report()
            cycle["stages"]["weekly_report"] = {
                "status": "completed",
                "week": f"{report.get('week_start', '')} to {report.get('week_end', '')}",
            }
        except Exception as e:
            logger.error(f"Weekly report failed: {e}")
            cycle["stages"]["weekly_report"] = {"status": "failed", "error": str(e)}
    else:
        cycle["stages"]["weekly_report"] = {"status": "skipped", "reason": "not_sunday"}
        logger.info("Stage 11/11: Skipping weekly report (not Sunday)")

    cycle["status"] = "completed"
    cycle["completed_at"] = _datetime.utcnow().isoformat()

    logger.info("=" * 55)
    logger.info("  DAILY INTELLIGENCE CYCLE Complete")
    logger.info("=" * 55)

    return cycle


def run_daily_intelligence_job() -> dict:
    """Entry point for daily intelligence job."""
    try:
        return run_intelligence_cycle()
    except Exception as e:
        logger.error(f"Daily intelligence job failed: {e}")
        return {
            "status": "failed",
            "error": str(e),
            "completed_at": _datetime.utcnow().isoformat(),
        }
