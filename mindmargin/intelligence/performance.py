"""Module 4 — Performance Intelligence: enriched analytics + automated insights."""

import json
import logging
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Optional

from mindmargin.analytics.memory import (
    get_pipeline_history, get_analytics_history,
    get_best_practices, save_best_practice,
    get_all_intelligence_rules, save_intelligence_rule,
)

logger = logging.getLogger(__name__)


class PerformanceAnalyzer:
    """Analyze video performance and generate actionable insights."""

    def __init__(self):
        self.insights: list[dict] = []

    def analyze_all(self) -> list[dict]:
        """Run all performance analyses and return insights."""
        history = get_pipeline_history(200)
        analytics = get_analytics_history(200)

        if not analytics:
            logger.info("Performance analysis: insufficient data")
            return []

        self._analyze_thumbnails(analytics)
        self._analyze_hooks(analytics)
        self._analyze_publish_time(analytics)
        self._analyze_video_length(analytics)
        self._analyze_topic_clusters(analytics)
        self._analyze_engagement(analytics)

        logger.info(f"Performance analysis: {len(self.insights)} insights generated")
        return self.insights

    def _add_insight(self, category: str, key: str, value: str,
                      score: float, confidence: float = 0.5):
        self.insights.append({
            "category": category,
            "key": key,
            "value": value,
            "score": round(score, 1),
            "confidence": round(confidence, 2),
        })
        save_intelligence_rule(category, key, value, score=score,
                                confidence=confidence, dynamic=True)

    def _analyze_thumbnails(self, analytics: list[dict]):
        """Analyze thumbnail performance patterns."""
        high_ctr = [a for a in analytics if (a.get("ctr", 0) or 0) > 0.05]
        low_ctr = [a for a in analytics if (a.get("ctr", 0) or 0) < 0.01]
        if high_ctr and low_ctr:
            ratio = len(high_ctr) / max(len(high_ctr) + len(low_ctr), 1)
            self._add_insight("thumbnail", "ctr_pattern",
                              f"High-CTR videos outperform low-CTR by {ratio:.1f}x",
                              score=ratio * 100, confidence=min(ratio, 0.9))

    def _analyze_hooks(self, analytics: list[dict]):
        """Analyze hook performance patterns."""
        from mindmargin.analytics.memory import get_best_hooks
        hooks = get_best_hooks(10)
        archetype_counts: dict[str, list[float]] = defaultdict(list)
        for h in hooks:
            arch = h.get("archetype", "unknown")
            ctr = h.get("ctr_score", 0) or 0
            archetype_counts[arch].append(ctr)

        for arch, scores in archetype_counts.items():
            if scores:
                avg = sum(scores) / len(scores)
                self._add_insight("hook", f"archetype_{arch}",
                                  f"Hook archetype '{arch}' avg CTR {avg:.1f}",
                                  score=avg, confidence=min(len(scores) / 10, 0.9))

    def _analyze_publish_time(self, analytics: list[dict]):
        """Analyze best publishing times."""
        day_perf: dict[str, list[float]] = defaultdict(list)
        for a in analytics:
            collected = a.get("collected_at", "")
            views = a.get("views", 0) or 0
            if collected and views > 0:
                try:
                    dt = datetime.strptime(collected[:10], "%Y-%m-%d")
                    day = dt.strftime("%A")
                    day_perf[day].append(views)
                except ValueError:
                    pass

        if day_perf:
            best_day = max(day_perf, key=lambda d: sum(day_perf[d]) / len(day_perf[d]))
            avg_views = sum(day_perf[best_day]) / len(day_perf[best_day])
            self._add_insight("publish_time", "best_day",
                              f"Best publishing day: {best_day} (avg {avg_views:.0f} views)",
                              score=min(avg_views, 100), confidence=min(len(day_perf[best_day]) / 5, 0.9))

    def _analyze_video_length(self, analytics: list[dict]):
        """Analyze optimal video length."""
        from mindmargin.analytics.memory import get_pipeline_history
        history = get_pipeline_history(200)
        length_views: list[tuple[float, int]] = []
        for p in history:
            dur = p.get("video_duration_s", 0) or 0
            views = p.get("views", 0) or 0
            if dur > 0:
                length_views.append((dur, views))

        if len(length_views) >= 5:
            length_views.sort(key=lambda x: x[1], reverse=True)
            top_durs = [lv[0] for lv in length_views[:5]]
            avg_top = sum(top_durs) / len(top_durs)
            self._add_insight("video_length", "optimal_duration",
                              f"Optimal video length: ~{avg_top:.0f}s ({avg_top/60:.1f}min)",
                              score=min(avg_top / 60 * 10, 100),
                              confidence=min(len(length_views) / 20, 0.9))

    def _analyze_topic_clusters(self, analytics: list[dict]):
        """Analyze which topic clusters perform best."""
        from mindmargin.analytics.memory import get_pipeline_history
        history = get_pipeline_history(200)
        cluster_perf: dict[str, list[int]] = defaultdict(list)
        cluster_keywords = {
            "financial_fraud": ["enron", "madoff", "ftx", "wirecard", "ponzi"],
            "startup_failure": ["theranos", "wework", "uber", "nokia"],
            "corruption": ["corruption", "scandal", "fraud", "bribery"],
            "bankruptcy": ["bankruptcy", "collapse", "fall of", "decline"],
            "tech_disruption": ["disruption", "how * lost", "why * failed"],
        }

        for p in history:
            topic = p.get("topic", "").lower()
            views = p.get("views", 0) or 0
            for cluster, kws in cluster_keywords.items():
                if any(kw.lower() in topic for kw in kws):
                    cluster_perf[cluster].append(views)

        for cluster, views_list in cluster_perf.items():
            if views_list:
                avg = sum(views_list) / len(views_list)
                self._add_insight("topic_cluster", cluster,
                                  f"Cluster '{cluster}': avg {avg:.0f} views ({len(views_list)} videos)",
                                  score=min(avg, 100),
                                  confidence=min(len(views_list) / 10, 0.9))

    def _analyze_engagement(self, analytics: list[dict]):
        """Analyze engagement patterns."""
        rates = []
        for a in analytics:
            views = a.get("views", 0) or 0
            likes = a.get("likes", 0) or 0
            comments = a.get("comments", 0) or 0
            if views > 0:
                rate = (likes + comments) / views * 100
                rates.append(rate)

        if rates:
            avg_rate = sum(rates) / len(rates)
            self._add_insight("engagement", "avg_engagement_rate",
                              f"Average engagement rate: {avg_rate:.1f}%",
                              score=min(avg_rate * 10, 100),
                              confidence=min(len(rates) / 20, 0.9))


def run_performance_analysis() -> list[dict]:
    analyzer = PerformanceAnalyzer()
    return analyzer.analyze_all()
