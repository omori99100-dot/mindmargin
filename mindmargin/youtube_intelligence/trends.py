import json
import logging
import uuid
from pathlib import Path
from typing import Optional

from mindmargin.config import settings
from mindmargin.youtube_intelligence.models import (
    TrendReport, TrendRecord, TrendDirection, utcnow,
)

logger = logging.getLogger(__name__)


class TrendsEngine:
    def __init__(self, persist_dir: str = ""):
        root = Path(persist_dir or settings.storage.temp_root)
        self._dir = root / "youtube_intelligence" / "trends"
        self._dir.mkdir(parents=True, exist_ok=True)

    def _save(self, report: TrendReport):
        path = self._dir / f"{report.report_id}.json"
        path.write_text(json.dumps(report.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

    def classify_trend(self, current_volume: int, previous_volume: int,
                       window_days: int = 30) -> TrendDirection:
        if previous_volume <= 0:
            return TrendDirection.RISING
        change = ((current_volume - previous_volume) / previous_volume) * 100
        if change > 10:
            return TrendDirection.RISING
        if change < -10:
            return TrendDirection.DECLINING
        return TrendDirection.STABLE

    def compute_velocity(self, volumes: list[int]) -> float:
        if len(volumes) < 2:
            return 0.0
        growth_rates = []
        for i in range(1, len(volumes)):
            if volumes[i - 1] > 0:
                growth_rates.append((volumes[i] - volumes[i - 1]) / volumes[i - 1])
        return round(sum(growth_rates) / len(growth_rates), 4) if growth_rates else 0.0

    def compute_relevance(self, topic: str, your_topics: list[str]) -> float:
        topic_lower = topic.lower()
        your_lower = [t.lower() for t in your_topics]
        if topic_lower in your_lower:
            return 1.0
        for yt in your_lower:
            if topic_lower in yt or yt in topic_lower:
                return 0.7
        return 0.3

    def analyze_trends(self, trend_data: list[dict], your_topics: list[str] = None) -> TrendReport:
        your_topics = your_topics or []
        records = []
        for td in trend_data:
            direction = self.classify_trend(
                td.get("current_volume", 0),
                td.get("previous_volume", 0),
            )
            velocity = self.compute_velocity(td.get("volumes", []))
            relevance = self.compute_relevance(td.get("topic", ""), your_topics)
            record = TrendRecord(
                trend_id=f"trend_{uuid.uuid4().hex[:8]}",
                topic=td.get("topic", ""),
                direction=direction,
                velocity=velocity,
                volume=td.get("current_volume", 0),
                competition=td.get("competition", 0.5),
                relevance_score=relevance,
                detected_at=utcnow(),
                metadata=td,
            )
            records.append(record)

        rising = [r.to_dict() for r in records if r.direction == TrendDirection.RISING]
        declining = [r.to_dict() for r in records if r.direction == TrendDirection.DECLINING]
        stable = [r.to_dict() for r in records if r.direction == TrendDirection.STABLE]
        niche = [r.to_dict() for r in records if r.competition < 0.3 and r.relevance_score > 0.5]

        report = TrendReport(
            report_id=f"trends_{uuid.uuid4().hex[:10]}",
            trends=records,
            rising_topics=rising,
            declining_topics=declining,
            stable_topics=stable,
            niche_opportunities=niche,
            summary=f"Analyzed {len(records)} trends: {len(rising)} rising, {len(declining)} declining, {len(niche)} niche opportunities.",
            generated_at=utcnow(),
        )
        self._save(report)
        return report

    def get_latest(self) -> Optional[TrendReport]:
        files = sorted(self._dir.glob("trends_*.json"), reverse=True)
        if not files:
            return None
        try:
            data = json.loads(files[0].read_text(encoding="utf-8"))
            return TrendReport.from_dict(data)
        except Exception:
            return None

    def list_reports(self, limit: int = 10) -> list[TrendReport]:
        reports = []
        for f in sorted(self._dir.glob("trends_*.json"), reverse=True)[:limit]:
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                reports.append(TrendReport.from_dict(data))
            except Exception:
                continue
        return reports
