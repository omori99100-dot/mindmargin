import json
import logging
import uuid
from pathlib import Path
from typing import Optional

from mindmargin.config import settings
from mindmargin.youtube_intelligence.models import (
    CompetitionReport, CompetitorChannel, CompetitionGap, utcnow,
)

logger = logging.getLogger(__name__)


class CompetitionIntelligence:
    def __init__(self, persist_dir: str = ""):
        root = Path(persist_dir or settings.storage.temp_root)
        self._dir = root / "youtube_intelligence" / "competition"
        self._dir.mkdir(parents=True, exist_ok=True)
        self._competitors_file = self._dir / "competitors.json"

    def _load_competitors(self) -> list[CompetitorChannel]:
        if not self._competitors_file.exists():
            return []
        try:
            data = json.loads(self._competitors_file.read_text(encoding="utf-8"))
            return [CompetitorChannel.from_dict(c) for c in data]
        except Exception:
            return []

    def _save_competitors(self, competitors: list[CompetitorChannel]):
        self._competitors_file.write_text(
            json.dumps([c.to_dict() for c in competitors], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def _save_report(self, report: CompetitionReport):
        path = self._dir / f"{report.report_id}.json"
        path.write_text(json.dumps(report.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

    def add_competitor(self, channel_id: str, channel_name: str = "",
                       subscriber_count: int = 0) -> CompetitorChannel:
        competitors = self._load_competitors()
        existing = next((c for c in competitors if c.channel_id == channel_id), None)
        if existing:
            existing.channel_name = channel_name or existing.channel_name
            existing.subscriber_count = subscriber_count or existing.subscriber_count
            existing.last_analyzed = utcnow()
        else:
            existing = CompetitorChannel(
                channel_id=channel_id,
                channel_name=channel_name,
                subscriber_count=subscriber_count,
                last_analyzed=utcnow(),
            )
            competitors.append(existing)
        self._save_competitors(competitors)
        return existing

    def remove_competitor(self, channel_id: str) -> bool:
        competitors = self._load_competitors()
        before = len(competitors)
        competitors = [c for c in competitors if c.channel_id != channel_id]
        if len(competitors) < before:
            self._save_competitors(competitors)
            return True
        return False

    def list_competitors(self) -> list[CompetitorChannel]:
        return self._load_competitors()

    def update_competitor_metrics(self, channel_id: str, metrics: dict) -> Optional[CompetitorChannel]:
        competitors = self._load_competitors()
        comp = next((c for c in competitors if c.channel_id == channel_id), None)
        if not comp:
            return None
        comp.avg_views = metrics.get("avg_views", comp.avg_views)
        comp.upload_frequency = metrics.get("upload_frequency", comp.upload_frequency)
        comp.topic_overlap_score = metrics.get("topic_overlap_score", comp.topic_overlap_score)
        comp.estimated_growth_rate = metrics.get("estimated_growth_rate", comp.estimated_growth_rate)
        comp.strengths = metrics.get("strengths", comp.strengths)
        comp.weaknesses = metrics.get("weaknesses", comp.weaknesses)
        comp.content_gaps = metrics.get("content_gaps", comp.content_gaps)
        comp.last_analyzed = utcnow()
        self._save_competitors(competitors)
        return comp

    def compare_frequency(self, your_frequency: float) -> dict:
        competitors = self._load_competitors()
        if not competitors:
            return {"your_frequency": your_frequency, "avg_competitor": 0, "status": "no_data"}
        avg_freq = sum(c.upload_frequency for c in competitors) / len(competitors)
        if your_frequency >= avg_freq * 1.2:
            status = "above_average"
        elif your_frequency >= avg_freq * 0.8:
            status = "on_track"
        else:
            status = "below_average"
        return {
            "your_frequency": your_frequency,
            "avg_competitor": round(avg_freq, 2),
            "status": status,
            "difference_pct": round(((your_frequency - avg_freq) / avg_freq * 100) if avg_freq > 0 else 0, 1),
        }

    def compare_growth(self, your_growth_rate: float) -> dict:
        competitors = self._load_competitors()
        if not competitors:
            return {"your_growth": your_growth_rate, "avg_competitor_growth": 0, "status": "no_data"}
        avg_growth = sum(c.estimated_growth_rate for c in competitors) / len(competitors)
        if your_growth_rate >= avg_growth * 1.2:
            status = "outperforming"
        elif your_growth_rate >= avg_growth * 0.8:
            status = "on_track"
        else:
            status = "underperforming"
        return {
            "your_growth": your_growth_rate,
            "avg_competitor_growth": round(avg_growth, 2),
            "status": status,
        }

    def find_topic_gaps(self, your_topics: list[str]) -> list[dict]:
        competitors = self._load_competitors()
        gaps = []
        for comp in competitors:
            comp_topics = [t.lower() for t in comp.content_gaps if isinstance(t, str)]
            for topic in comp_topics:
                if topic not in [t.lower() for t in your_topics]:
                    gaps.append({
                        "topic": topic,
                        "competitor": comp.channel_name,
                        "gap_type": CompetitionGap.UNCOVERED_TOPIC.value,
                    })
        seen = set()
        unique = []
        for g in gaps:
            key = g["topic"].lower()
            if key not in seen:
                seen.add(key)
                unique.append(g)
        return unique

    def generate_recommendations(self, your_channel: dict, report: CompetitionReport) -> list[str]:
        recs = []
        freq = self.compare_frequency(your_channel.get("upload_frequency", 1))
        if freq.get("status") == "below_average":
            recs.append(f"Your upload frequency ({freq['your_frequency']:.1f}/week) is below competitor average ({freq['avg_competitor']:.1f}/week).")
        growth = self.compare_growth(your_channel.get("growth_rate", 0))
        if growth.get("status") == "underperforming":
            recs.append("Competitors are growing faster. Analyze their top content for topic and format insights.")
        if report.topic_gaps:
            top_gaps = report.topic_gaps[:3]
            for gap in top_gaps:
                recs.append(f"Topic gap opportunity: '{gap.get('topic', '')}' (covered by {gap.get('competitor', 'competitor')}).")
        if not recs:
            recs.append("You are competitive with tracked channels. Continue current strategy.")
        return recs

    def generate_report(self, your_channel: dict) -> CompetitionReport:
        competitors = self._load_competitors()
        your_topics = your_channel.get("topics", [])
        gaps = self.find_topic_gaps(your_topics)

        avg_freq = sum(c.upload_frequency for c in competitors) / len(competitors) if competitors else 0
        avg_growth = sum(c.estimated_growth_rate for c in competitors) / len(competitors) if competitors else 0

        report = CompetitionReport(
            report_id=f"comp_{uuid.uuid4().hex[:10]}",
            competitors=competitors,
            your_channel_summary={
                "subscribers": your_channel.get("subscribers", 0),
                "upload_frequency": your_channel.get("upload_frequency", 0),
                "growth_rate": your_channel.get("growth_rate", 0),
                "topics": your_channel.get("topics", []),
            },
            avg_competitor_frequency=round(avg_freq, 2),
            avg_competitor_growth=round(avg_growth, 2),
            topic_gaps=gaps,
            generated_at=utcnow(),
        )
        report.recommendations = self.generate_recommendations(your_channel, report)
        self._save_report(report)
        return report

    def get_latest(self) -> Optional[CompetitionReport]:
        files = sorted(self._dir.glob("comp_*.json"), reverse=True)
        if not files:
            return None
        try:
            data = json.loads(files[0].read_text(encoding="utf-8"))
            return CompetitionReport.from_dict(data)
        except Exception:
            return None
