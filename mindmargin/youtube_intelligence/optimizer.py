import logging
from typing import Optional

from mindmargin.youtube_intelligence.channel_health import ChannelHealthMonitor
from mindmargin.youtube_intelligence.growth import GrowthEngine
from mindmargin.youtube_intelligence.audience import AudienceIntelligence
from mindmargin.youtube_intelligence.retention import RetentionAnalyzer
from mindmargin.youtube_intelligence.ctr import CTROptimizer
from mindmargin.youtube_intelligence.competition import CompetitionIntelligence
from mindmargin.youtube_intelligence.trends import TrendsEngine
from mindmargin.youtube_intelligence.benchmark import BenchmarkEngine
from mindmargin.youtube_intelligence.models import (
    YouTubeIntelligenceStatus, ChannelHealthReport, GrowthReport,
    AudienceProfile, CTRReport, CompetitionReport, BenchmarkReport,
    TrendReport, utcnow,
)

logger = logging.getLogger(__name__)


class YouTubeOptimizer:
    def __init__(self, persist_dir: str = ""):
        self.health = ChannelHealthMonitor(persist_dir)
        self.growth = GrowthEngine(persist_dir)
        self.audience = AudienceIntelligence(persist_dir)
        self.retention = RetentionAnalyzer(persist_dir)
        self.ctr = CTROptimizer(persist_dir)
        self.competition = CompetitionIntelligence(persist_dir)
        self.trends = TrendsEngine(persist_dir)
        self.benchmark = BenchmarkEngine(persist_dir)

    def get_status(self) -> YouTubeIntelligenceStatus:
        health = self.health.get_latest()
        growth_reports = self.growth.list_reports(1)
        audience = self.audience.get_latest()
        ctr = self.ctr.get_latest()
        comp = self.competition.get_latest()
        bench_entries = self.benchmark._load_entries()
        trends = self.trends.list_reports(1)
        from mindmargin.youtube_intelligence.models import YouTubeRecommendation
        return YouTubeIntelligenceStatus(
            health_score=float(health.overall_score) if health else 0.0,
            growth_score=float(growth_reports[0].overall_growth_score) if growth_reports else 0.0,
            audience_segments=len(audience.loyal_segments) if audience else 0,
            active_signals=len(growth_reports[0].signals) if growth_reports else 0,
            ctr_analyses=len(ctr.data_points) if ctr else 0,
            competitors_tracked=len(comp.competitors) if comp else 0,
            benchmarks_recorded=len(bench_entries),
            trends_tracked=len(trends[0].trends) if trends else 0,
            last_health_check=health.generated_at if health else "",
            last_growth_analysis=growth_reports[0].generated_at if growth_reports else "",
            generated_at=utcnow(),
        )

    def run_full_analysis(self, channel_data: dict,
                          topic_data: list[dict] = None,
                          content_history: list[dict] = None,
                          video_data: list[dict] = None,
                          competitor_channels: list[dict] = None) -> dict:
        topic_data = topic_data or []
        content_history = content_history or []
        video_data = video_data or []
        competitor_channels = competitor_channels or []

        results = {}

        results["health"] = self.health.compute_health(channel_data).to_dict()

        results["growth"] = self.growth.analyze_growth(
            channel_data, topic_data, content_history).to_dict()

        results["audience"] = self.audience.build_profile(channel_data).to_dict()

        if video_data:
            results["ctr"] = self.ctr.generate_report(video_data).to_dict()
            for vd in video_data:
                self.benchmark.record_from_video_data(vd)

        if competitor_channels:
            for cc in competitor_channels:
                self.competition.add_competitor(cc.get("channel_id", ""),
                                                 cc.get("channel_name", ""),
                                                 cc.get("subscriber_count", 0))
            results["competition"] = self.competition.generate_report(channel_data).to_dict()

        results["benchmarks"] = self.benchmark.generate_report().to_dict()

        results["trends"] = self.trends.analyze_trends(
            topic_data, channel_data.get("topics", [])).to_dict()

        results["status"] = self.get_status().to_dict()
        return results

    def get_optimization_priorities(self) -> list[dict]:
        priorities = []
        health = self.health.get_latest()
        if health:
            for weakness in health.top_weaknesses:
                priorities.append({
                    "area": "health",
                    "metric": weakness,
                    "priority": "high",
                    "reason": f"Channel health weakness: {weakness}",
                })
        growth_reports = self.growth.list_reports(1)
        if growth_reports:
            for bottleneck in growth_reports[0].bottlenecks:
                priorities.append({
                    "area": "growth",
                    "metric": bottleneck.get("topic", ""),
                    "priority": "high",
                    "reason": f"Growth bottleneck: {bottleneck.get('topic', '')}",
                })
        ctr = self.ctr.get_latest()
        if ctr and ctr.avg_ctr < 5:
            priorities.append({
                "area": "ctr",
                "metric": "avg_ctr",
                "priority": "medium",
                "reason": f"CTR below 5% ({ctr.avg_ctr:.1f}%). Improve titles and thumbnails.",
            })
        priorities.sort(key=lambda x: {"high": 0, "medium": 1, "low": 2}.get(x["priority"], 3))
        return priorities
