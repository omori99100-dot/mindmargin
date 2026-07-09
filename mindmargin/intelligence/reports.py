"""Module 9 — Weekly Intelligence Report generator."""

import json
import logging
from collections import defaultdict
from datetime import datetime, timedelta

from mindmargin.analytics.memory import (
    get_pipeline_history, get_analytics_history,
    get_all_intelligence_rules, save_weekly_report,
    get_opportunities, get_trend_sources,
)

logger = logging.getLogger(__name__)


class WeeklyReportGenerator:
    """Generate a weekly intelligence report with trends, performance, and recommendations."""

    def __init__(self):
        today = datetime.utcnow()
        self.week_start = (today - timedelta(days=today.weekday() + 7)).strftime("%Y-%m-%d")
        self.week_end = (today - timedelta(days=today.weekday() + 1)).strftime("%Y-%m-%d")

    def generate(self) -> dict:
        history = get_pipeline_history(200)
        analytics = get_analytics_history(200)
        rules = get_all_intelligence_rules()
        opportunities = get_opportunities(min_score=30, limit=50)

        this_week = [
            p for p in history
            if p.get("created_at", "").startswith(tuple(
                f"2026-{m:02d}-" for m in range(1, 13)
            ))
        ]
        this_week = [
            p for p in history
            if self.week_start <= (p.get("created_at", "")[:10] or "") <= self.week_end
        ]

        report = {
            "week_start": self.week_start,
            "week_end": self.week_end,
            "generated_at": datetime.utcnow().isoformat(),
            "summary": self._generate_summary(history, analytics, rules),
            "top_topics": self._find_top_topics(history),
            "worst_topics": self._find_worst_topics(history),
            "trend_changes": self._detect_trend_changes(opportunities),
            "growth_rate": self._compute_growth_rate(history),
            "engagement_changes": self._engagement_trend(analytics),
            "experiment_results": self._get_experiment_results(rules),
            "improvements": self._suggest_improvements(rules, analytics),
        }

        save_weekly_report(self.week_start, self.week_end, json.dumps(report))
        logger.info(f"Weekly report: {self.week_start} to {self.week_end}")
        return report

    def _generate_summary(self, history: list[dict], analytics: list[dict],
                          rules: list[dict]) -> str:
        published = [p for p in history if p.get("youtube_video_id")]
        total_views = sum(p.get("views", 0) or 0 for p in published)
        total_videos = len(published)

        high_conf_rules = [r for r in rules if r.get("confidence", 0) >= 0.7]
        lines = [
            f"Weekly Report: {self.week_start} to {self.week_end}",
            f"",
            f"Published videos: {total_videos}",
            f"Total views: {total_views}",
            f"Active intelligence rules: {len(high_conf_rules)}",
        ]
        return "\n".join(lines)

    def _find_top_topics(self, history: list[dict]) -> list[dict]:
        published = [p for p in history if p.get("youtube_video_id") and (p.get("views", 0) or 0) > 0]
        published.sort(key=lambda p: p.get("views", 0) or 0, reverse=True)
        return [
            {"topic": p["topic"], "views": p.get("views", 0)}
            for p in published[:5]
        ]

    def _find_worst_topics(self, history: list[dict]) -> list[dict]:
        published = [p for p in history if p.get("youtube_video_id") and (p.get("views", 0) or 0) > 0]
        published.sort(key=lambda p: p.get("views", 0) or 0)
        return [
            {"topic": p["topic"], "views": p.get("views", 0)}
            for p in published[:3]
        ]

    def _detect_trend_changes(self, opportunities: list[dict]) -> list[dict]:
        if not opportunities:
            return []
        by_source: dict[str, list[float]] = defaultdict(list)
        for opp in opportunities:
            src = opp.get("source", "unknown")
            score = opp.get("opportunity_score", 0) or 0
            by_source[src].append(score)
        return [
            {"source": src, "avg_score": round(sum(scores) / len(scores), 1), "count": len(scores)}
            for src, scores in by_source.items()
        ]

    def _compute_growth_rate(self, history: list[dict]) -> dict:
        published = [p for p in history if p.get("youtube_video_id")]
        if len(published) < 2:
            return {"rate": 0, "trend": "insufficient_data"}
        mid = len(published) // 2
        first_half = sum(p.get("views", 0) or 0 for p in published[:mid])
        second_half = sum(p.get("views", 0) or 0 for p in published[mid:])
        if first_half == 0:
            return {"rate": 0, "trend": "stable"}
        rate = ((second_half - first_half) / first_half) * 100
        trend = "growing" if rate > 10 else "declining" if rate < -10 else "stable"
        return {"rate": round(rate, 1), "trend": trend}

    def _engagement_trend(self, analytics: list[dict]) -> dict:
        if not analytics:
            return {"ctr_trend": "unknown", "retention_trend": "unknown"}
        mid = len(analytics) // 2
        if mid == 0:
            return {"ctr_trend": "unknown", "retention_trend": "unknown"}
        early = analytics[:mid]
        late = analytics[mid:]
        early_ctr = sum(a.get("ctr", 0) or 0 for a in early) / max(len(early), 1)
        late_ctr = sum(a.get("ctr", 0) or 0 for a in late) / max(len(late), 1)
        return {
            "ctr_trend": "improving" if late_ctr > early_ctr else "declining",
            "early_ctr": round(early_ctr, 3),
            "late_ctr": round(late_ctr, 3),
        }

    def _get_experiment_results(self, rules: list[dict]) -> list[dict]:
        winner_rules = [r for r in rules if r.get("category") in ("ab_title_winner", "ab_thumbnail_winner")]
        return [
            {"category": r["category"], "value": r.get("value", ""), "score": r.get("score", 0)}
            for r in winner_rules[:5]
        ]

    def _suggest_improvements(self, rules: list[dict], analytics: list[dict]) -> list[str]:
        suggestions = []
        high_conf = [r for r in rules if r.get("confidence", 0) >= 0.7]
        if not high_conf:
            suggestions.append("Collect more data to generate high-confidence rules")
        if analytics:
            avg_ctr = sum(a.get("ctr", 0) or 0 for a in analytics) / len(analytics)
            if avg_ctr < 0.03:
                suggestions.append("CTR is low. Consider improving thumbnail contrast and hook strength")
        title_rules = [r for r in rules if r.get("category") == "title_format"]
        if not title_rules:
            suggestions.append("No title patterns learned yet. Try different title formats")
        return suggestions[:5]


def run_weekly_report() -> dict:
    generator = WeeklyReportGenerator()
    return generator.generate()
