import json
import logging
import uuid
from pathlib import Path
from typing import Optional

from mindmargin.config import settings
from mindmargin.youtube_intelligence.models import (
    YouTubeRecommendation, RecommendationType, utcnow,
)

logger = logging.getLogger(__name__)


class YouTubeRecommendationEngine:
    def __init__(self, persist_dir: str = ""):
        root = Path(persist_dir or settings.storage.temp_root)
        self._dir = root / "youtube_intelligence" / "recommendations"
        self._dir.mkdir(parents=True, exist_ok=True)

    def _save(self, rec: YouTubeRecommendation):
        path = self._dir / f"{rec.recommendation_id}.json"
        path.write_text(json.dumps(rec.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

    def _load(self) -> list[YouTubeRecommendation]:
        recs = []
        for f in sorted(self._dir.glob("rec_*.json"), reverse=True):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                recs.append(YouTubeRecommendation.from_dict(data))
            except Exception:
                continue
        return recs

    def generate_from_health(self, health_report: dict) -> list[YouTubeRecommendation]:
        recs = []
        weaknesses = health_report.get("top_weaknesses", [])
        for w in weaknesses:
            recs.append(YouTubeRecommendation(
                recommendation_id=f"rec_{uuid.uuid4().hex[:8]}",
                recommendation_type=RecommendationType.OPTIMIZATION,
                priority=2,
                confidence=0.8,
                title=f"Improve {w}",
                description=f"Channel health metric '{w}' is below target. Focus on improving this area.",
                estimated_impact="Medium to high impact on overall channel health.",
                source_module="channel_health",
                created_at=utcnow(),
            ))
        for rec in recs:
            self._save(rec)
        return recs

    def generate_from_growth(self, growth_report: dict) -> list[YouTubeRecommendation]:
        recs = []
        for signal in growth_report.get("fast_growing_topics", []):
            recs.append(YouTubeRecommendation(
                recommendation_id=f"rec_{uuid.uuid4().hex[:8]}",
                recommendation_type=RecommendationType.GROWTH,
                priority=2,
                confidence=0.75,
                title=f"Capitalize on growing topic: {signal.get('topic', '')}",
                description=f"Topic '{signal.get('topic', '')}' is trending up. Create content now.",
                estimated_impact="High — riding early trends boosts views.",
                action_data={"topic": signal.get("topic", "")},
                source_module="growth",
                created_at=utcnow(),
            ))
        for bottleneck in growth_report.get("bottlenecks", []):
            recs.append(YouTubeRecommendation(
                recommendation_id=f"rec_{uuid.uuid4().hex[:8]}",
                recommendation_type=RecommendationType.OPTIMIZATION,
                priority=1,
                confidence=0.85,
                title=f"Fix bottleneck: {bottleneck.get('topic', '')}",
                description=bottleneck.get("topic", ""),
                estimated_impact="Critical — removing bottlenecks unlocks growth.",
                source_module="growth",
                created_at=utcnow(),
            ))
        for rec in recs:
            self._save(rec)
        return recs

    def generate_from_ctr(self, ctr_report: dict) -> list[YouTubeRecommendation]:
        recs = []
        for rec_text in ctr_report.get("recommendations", []):
            recs.append(YouTubeRecommendation(
                recommendation_id=f"rec_{uuid.uuid4().hex[:8]}",
                recommendation_type=RecommendationType.CONTENT,
                priority=3,
                confidence=0.7,
                title="CTR optimization",
                description=rec_text,
                estimated_impact="Medium — better CTR means more views per impression.",
                source_module="ctr",
                created_at=utcnow(),
            ))
        return recs

    def generate_from_audience(self, audience_profile: dict) -> list[YouTubeRecommendation]:
        recs = []
        best_time = audience_profile.get("best_upload_time", "")
        best_day = audience_profile.get("best_upload_day", "")
        if best_time:
            recs.append(YouTubeRecommendation(
                recommendation_id=f"rec_{uuid.uuid4().hex[:8]}",
                recommendation_type=RecommendationType.PUBLISHING,
                priority=3,
                confidence=0.75,
                title=f"Optimize publish time to {best_time}",
                description=f"Data shows {best_time} on {best_day}s gives best initial viewership.",
                estimated_impact="Low to medium — timing helps first 48h performance.",
                source_module="audience",
                created_at=utcnow(),
            ))
        return recs

    def generate_from_benchmarks(self, benchmark_report: dict) -> list[YouTubeRecommendation]:
        recs = []
        by_cat = benchmark_report.get("by_category", {})
        for cat, data in by_cat.items():
            if data.get("sample_count", 0) >= 3:
                recs.append(YouTubeRecommendation(
                    recommendation_id=f"rec_{uuid.uuid4().hex[:8]}",
                    recommendation_type=RecommendationType.CONTENT,
                    priority=4,
                    confidence=0.65,
                    title=f"Benchmark: {cat}",
                    description=f"Best {cat}: {data.get('best_value', 0)} (avg: {data.get('avg_value', 0)}).",
                    estimated_impact="Low — maintain consistency with proven patterns.",
                    source_module="benchmark",
                    created_at=utcnow(),
                ))
        return recs

    def generate_all(self, health: dict = None, growth: dict = None,
                     ctr: dict = None, audience: dict = None,
                     benchmarks: dict = None) -> list[YouTubeRecommendation]:
        recs = []
        if health:
            recs.extend(self.generate_from_health(health))
        if growth:
            recs.extend(self.generate_from_growth(growth))
        if ctr:
            recs.extend(self.generate_from_ctr(ctr))
        if audience:
            recs.extend(self.generate_from_audience(audience))
        if benchmarks:
            recs.extend(self.generate_from_benchmarks(benchmarks))
        recs.sort(key=lambda r: r.priority)
        for rec in recs:
            self._save(rec)
        return recs

    def list_recommendations(self, status: str = None, limit: int = 50) -> list[YouTubeRecommendation]:
        recs = self._load()
        if status:
            recs = [r for r in recs if r.status == status]
        return recs[:limit]

    def mark_actioned(self, recommendation_id: str) -> bool:
        for f in self._dir.glob(f"{recommendation_id}.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                rec = YouTubeRecommendation.from_dict(data)
                rec.status = "actioned"
                f.write_text(json.dumps(rec.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
                return True
            except Exception:
                continue
        return False

    def get_pending(self, limit: int = 20) -> list[YouTubeRecommendation]:
        return self.list_recommendations(status="pending", limit=limit)

    def get_stats(self) -> dict:
        all_recs = self._load()
        return {
            "total": len(all_recs),
            "pending": len([r for r in all_recs if r.status == "pending"]),
            "actioned": len([r for r in all_recs if r.status == "actioned"]),
            "by_type": {},
            "avg_confidence": round(sum(r.confidence for r in all_recs) / len(all_recs), 2) if all_recs else 0,
        }
