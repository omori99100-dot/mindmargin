import json
import logging
import uuid
from pathlib import Path
from typing import Optional

from mindmargin.config import settings
from mindmargin.business.models import BusinessRecommendation, utcnow
from mindmargin.business.portfolio import BusinessPortfolio

logger = logging.getLogger(__name__)


class BusinessRecommendationEngine:
    def __init__(self, persist_dir: str = ""):
        root = Path(persist_dir or settings.storage.temp_root)
        self._recs_dir = root / "business" / "recommendations"
        self._recs_dir.mkdir(parents=True, exist_ok=True)
        self._portfolio = BusinessPortfolio(persist_dir=persist_dir)

    def _save(self, rec: BusinessRecommendation):
        path = self._recs_dir / f"{rec.recommendation_id}.json"
        path.write_text(json.dumps(rec.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

    def generate_recommendations(self) -> list[BusinessRecommendation]:
        recs = []
        status = self._portfolio.get_business_status()

        if status["roi_30d"] < 50:
            recs.append(BusinessRecommendation(
                recommendation_id=f"brec_{uuid.uuid4().hex[:8]}",
                recommendation_type="cost_optimization",
                priority=8,
                confidence=0.8,
                title="Optimize costs — ROI below 50%",
                description=f"Current 30-day ROI is {status['roi_30d']:.1f}%. Review spending.",
                estimated_impact=status["total_costs_30d"] * 0.2,
                created_at=utcnow(),
            ))

        if status["profit_30d"] < 0:
            recs.append(BusinessRecommendation(
                recommendation_id=f"brec_{uuid.uuid4().hex[:8]}",
                recommendation_type="revenue_increase",
                priority=9,
                confidence=0.9,
                title="Increase revenue — currently operating at a loss",
                description=f"30-day loss: ${abs(status['profit_30d']):.2f}",
                estimated_impact=abs(status["profit_30d"]) * 2,
                created_at=utcnow(),
            ))

        rev_by_type = status.get("revenue_by_type", {})
        if len(rev_by_type) <= 1:
            recs.append(BusinessRecommendation(
                recommendation_id=f"brec_{uuid.uuid4().hex[:8]}",
                recommendation_type="diversify_revenue",
                priority=7,
                confidence=0.7,
                title="Diversify revenue streams",
                description="Revenue depends on too few sources",
                estimated_impact=status["total_revenue_30d"] * 0.3,
                created_at=utcnow(),
            ))

        if status["active_campaigns"] == 0:
            recs.append(BusinessRecommendation(
                recommendation_id=f"brec_{uuid.uuid4().hex[:8]}",
                recommendation_type="launch_campaign",
                priority=6,
                confidence=0.6,
                title="Launch a marketing campaign",
                description="No active campaigns — growth may stall",
                estimated_impact=1000.0,
                created_at=utcnow(),
            ))

        if status["goals_total"] > 0 and status["goals_achieved"] < status["goals_total"] * 0.5:
            recs.append(BusinessRecommendation(
                recommendation_id=f"brec_{uuid.uuid4().hex[:8]}",
                recommendation_type="focus_goals",
                priority=6,
                confidence=0.7,
                title="Focus on business goals",
                description=f"{status['goals_achieved']}/{status['goals_total']} goals achieved",
                estimated_impact=500.0,
                created_at=utcnow(),
            ))

        recs.sort(key=lambda r: (r.priority, r.confidence), reverse=True)
        for rec in recs:
            self._save(rec)
        logger.info("BusinessRecommendationEngine: generated %d recommendations", len(recs))
        return recs

    def get_recommendations(self, status: Optional[str] = None,
                            limit: int = 50) -> list[BusinessRecommendation]:
        results = []
        for p in sorted(self._recs_dir.glob("*.json"), reverse=True):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                rec = BusinessRecommendation.from_dict(data)
                if status and rec.status != status:
                    continue
                results.append(rec)
                if len(results) >= limit:
                    break
            except Exception:
                continue
        return results

    def mark_actioned(self, recommendation_id: str, new_status: str = "actioned") -> bool:
        for p in self._recs_dir.glob("*.json"):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                rec = BusinessRecommendation.from_dict(data)
                if rec.recommendation_id == recommendation_id:
                    rec.status = new_status
                    p.write_text(json.dumps(rec.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
                    return True
            except Exception:
                continue
        return False
