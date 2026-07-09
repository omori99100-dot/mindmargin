"""Phase 6 — Autonomous Weekly Planner.

Generates a multi-format publishing schedule:
Long-form, Shorts, Community posts, Articles, Social snippets.
Optimizes for diversity, freshness, and audience interest.
"""

import json
import logging
import math
from datetime import datetime, timedelta
from typing import Optional

from mindmargin.config import settings

logger = logging.getLogger(__name__)

FORMATS = [
    {"name": "long_form",    "label": "Long-form Video",     "weight": 0.30, "max_per_week": 3},
    {"name": "short",        "label": "Short",               "weight": 0.25, "max_per_week": 4},
    {"name": "community",    "label": "Community Post",      "weight": 0.15, "max_per_week": 3},
    {"name": "article",      "label": "Article",             "weight": 0.15, "max_per_week": 2},
    {"name": "snippet",      "label": "Social Snippet",      "weight": 0.15, "max_per_week": 3},
]

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


class WeeklyPlanner:
    """Generates a full-week publishing schedule from opportunity data."""

    def __init__(self):
        self.week_start = self._next_monday()

    def plan_week(self) -> dict:
        """Generate the full weekly schedule."""
        from mindmargin.analytics.memory import (
            get_top_opportunities, get_pipeline_history,
            get_suppressed_patterns, get_intelligence_rules,
            save_weekly_plan,
        )

        opportunities = get_top_opportunities(30)
        history = get_pipeline_history(100)
        suppressed = get_suppressed_patterns()
        rules = get_intelligence_rules()

        if not opportunities:
            logger.warning("Weekly planner: no opportunities available")
            empty = self._empty_plan()
            save_weekly_plan(self.week_start, empty)
            return empty

        scored = self._score_for_planning(opportunities, history, suppressed)

        schedule = self._build_schedule(scored)

        summary = self._summarize(schedule, scored)

        plan = {
            "week_start": self.week_start,
            "week_end": self._week_end(),
            "total_opportunities": len(opportunities),
            "ranked_count": len(scored),
            "schedule": schedule,
            "summary": summary,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
        }

        save_weekly_plan(self.week_start, plan)
        logger.info(f"Weekly planner: {len(schedule)} slots filled from {len(scored)} candidates")
        return plan

    def _next_monday(self) -> str:
        today = datetime.now()
        days_ahead = 0 - today.weekday()
        if days_ahead <= 0:
            days_ahead += 7
        monday = today + timedelta(days=days_ahead)
        return monday.strftime("%Y-%m-%d")

    def _week_end(self) -> str:
        start = datetime.strptime(self.week_start, "%Y-%m-%d")
        end = start + timedelta(days=6)
        return end.strftime("%Y-%m-%d")

    def _score_for_planning(self, opportunities: list[dict],
                             history: list[dict],
                             suppressed: list[dict]) -> list[dict]:
        """Score and rank opportunities for weekly planning.

        Applies freshness bonus, recency penalty, and diversity incentives.
        """
        published_topics = {p.get("topic", "") for p in history if p.get("topic")}
        suppressed_topics = {s.get("value", "") for s in suppressed}

        ranked = []
        for opp in opportunities:
            topic = opp.get("topic", "")
            score = opp.get("opportunity_score", 0) or 0

            if topic in published_topics:
                score *= 0.3
            if topic in suppressed_topics:
                score *= 0.5

            freshness = opp.get("scored_at", "")
            if freshness:
                try:
                    if "T" in freshness:
                        dt = datetime.fromisoformat(freshness)
                    else:
                        dt = datetime.strptime(freshness, "%Y-%m-%d %H:%M:%S")
                    hours_ago = (datetime.now() - dt).total_seconds() / 3600
                    freshness_bonus = max(0, 20 - hours_ago / 24 * 2)
                    score += freshness_bonus
                except (ValueError, TypeError):
                    pass

            ranked.append({**opp, "planning_score": round(score, 1)})

        ranked.sort(key=lambda x: x["planning_score"], reverse=True)
        return ranked

    def _build_schedule(self, ranked: list[dict]) -> list[dict]:
        """Assign topics to days and formats, optimizing diversity."""
        schedule = []
        used_topics = set()
        format_counts = {f["name"]: 0 for f in FORMATS}

        format_pool = []
        for f in FORMATS:
            for _ in range(f["max_per_week"]):
                format_pool.append(f["name"])

        idx = 0
        for day_offset in range(7):
            day = WEEKDAYS[day_offset]
            date = (datetime.strptime(self.week_start, "%Y-%m-%d")
                    + timedelta(days=day_offset)).strftime("%Y-%m-%d")

            day_format_count = max(1, len(ranked) // 7 + 1)
            for slot in range(day_format_count):
                if idx >= len(ranked):
                    break

                fmt_name = self._pick_format(day, slot, format_counts, ranked, idx)

                candidate = ranked[idx]
                topic = candidate.get("topic", "")
                while topic in used_topics and idx < len(ranked) - 1:
                    idx += 1
                    candidate = ranked[idx]
                    topic = candidate.get("topic", "")

                used_topics.add(topic)
                format_counts[fmt_name] = format_counts.get(fmt_name, 0) + 1
                idx += 1

                schedule.append({
                    "day": day,
                    "date": date,
                    "format": fmt_name,
                    "format_label": next(f["label"] for f in FORMATS if f["name"] == fmt_name),
                    "topic": topic,
                    "opportunity_score": candidate.get("opportunity_score", 0),
                    "planning_score": candidate.get("planning_score", 0),
                    "confidence": candidate.get("confidence", 0),
                })

        return schedule

    def _pick_format(self, day: str, slot: int,
                      format_counts: dict[str, int],
                      ranked: list[dict], idx: int) -> str:
        """Pick the best format for this slot, preferring under-utilized ones."""
        from mindmargin.analytics.memory import get_intelligence_rules
        rules = get_intelligence_rules()

        preferred_format = None
        for rule in rules:
            if rule.get("category") == "format_preference":
                preferred_format = rule.get("key")

        sorted_formats = sorted(FORMATS, key=lambda f: f["weight"], reverse=True)

        for f in sorted_formats:
            if format_counts.get(f["name"], 0) < f["max_per_week"]:
                if preferred_format and f["name"] == preferred_format and slot == 0:
                    return f["name"]
                return f["name"]

        return "long_form"

    def _summarize(self, schedule: list[dict], ranked: list[dict]) -> dict:
        """Generate summary stats for the weekly plan."""
        format_counts = {}
        for entry in schedule:
            fmt = entry["format"]
            format_counts[fmt] = format_counts.get(fmt, 0) + 1

        avg_score = 0
        if schedule:
            avg_score = sum(e.get("opportunity_score", 0) for e in schedule) / len(schedule)

        return {
            "total_items": len(schedule),
            "format_distribution": format_counts,
            "average_opportunity_score": round(avg_score, 1),
            "topics_covered": len(set(e["topic"] for e in schedule)),
            "days_active": len(set(e["day"] for e in schedule)),
        }

    def _empty_plan(self) -> dict:
        return {
            "week_start": self.week_start,
            "week_end": self._week_end(),
            "total_opportunities": 0,
            "ranked_count": 0,
            "schedule": [],
            "summary": {
                "total_items": 0,
                "format_distribution": {},
                "average_opportunity_score": 0,
                "topics_covered": 0,
                "days_active": 0,
            },
            "generated_at": datetime.now().isoformat(timespec="seconds"),
        }


def plan_week() -> dict:
    """Convenience entry point for weekly planning."""
    planner = WeeklyPlanner()
    return planner.plan_week()
