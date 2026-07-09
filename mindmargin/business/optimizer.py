import logging
from datetime import datetime, timezone
from typing import Optional

from mindmargin.business.models import (
    BusinessGoal, RevenueEntry, CostEntry, Campaign,
    RevenueType, utcnow,
)

logger = logging.getLogger(__name__)


class BusinessOptimizer:
    def __init__(self):
        pass

    def compute_roi(self, revenue: float, costs: float) -> float:
        if costs <= 0:
            return 0.0
        return round(((revenue - costs) / costs) * 100, 1)

    def compute_profit_margin(self, revenue: float, costs: float) -> float:
        if revenue <= 0:
            return 0.0
        return round(((revenue - costs) / revenue) * 100, 1)

    def compute_rpm(self, revenue: float, views: int) -> float:
        if views == 0:
            return 0.0
        return round((revenue / views) * 1000, 2)

    def compute_cpm(self, ad_revenue: float, impressions: int) -> float:
        if impressions == 0:
            return 0.0
        return round((ad_revenue / impressions) * 1000, 2)

    def optimize_pricing(self, current_price: float, conversion_rate: float,
                         competitor_price: float = 0.0) -> dict:
        if competitor_price > 0:
            optimal = competitor_price * 0.95
        else:
            optimal = current_price * (1 + max(0.05 - conversion_rate, 0))
        return {
            "current_price": current_price,
            "optimal_price": round(optimal, 2),
            "expected_change_pct": round(((optimal - current_price) / max(current_price, 1)) * 100, 1),
        }

    def optimize_budget_allocation(self, campaigns: list[Campaign],
                                   total_budget: float) -> list[dict]:
        if not campaigns:
            return []
        scored = []
        for c in campaigns:
            roi = c.roi if c.spent > 0 else 50.0
            score = roi * 0.6 + (100 - c.budget_utilization_pct) * 0.4
            scored.append((score, c))
        scored.sort(key=lambda x: x[0], reverse=True)
        total_score = sum(s for s, _ in scored)
        allocations = []
        for score, c in scored:
            share = (score / max(total_score, 1)) * total_budget
            allocations.append({
                "campaign_id": c.campaign_id,
                "campaign_name": c.name,
                "score": round(score, 1),
                "recommended_budget": round(share, 2),
                "current_budget": c.budget,
                "roi": c.roi,
            })
        return allocations

    def prioritize_goals(self, goals: list[BusinessGoal]) -> list[dict]:
        scored = []
        for g in goals:
            priority_score = g.weight * 0.5 + (g.progress_pct / 100) * 0.3 + (1 - g.progress_pct / 100) * 0.2
            scored.append({
                "goal_id": g.goal_id,
                "name": g.name,
                "priority_score": round(priority_score, 3),
                "progress_pct": g.progress_pct,
                "weight": g.weight,
                "needs_attention": g.progress_pct < 50,
            })
        scored.sort(key=lambda x: x["priority_score"], reverse=True)
        return scored

    def identify_high_value_opportunities(self, revenue_entries: list[RevenueEntry],
                                          campaigns: list[Campaign]) -> list[dict]:
        opportunities = []

        by_type: dict[str, float] = {}
        for e in revenue_entries:
            t = e.revenue_type.value
            by_type[t] = by_type.get(t, 0) + e.amount
        if by_type:
            best_type = max(by_type, key=by_type.get)
            opportunities.append({
                "type": "double_down",
                "description": f"Increase {best_type} — highest revenue source",
                "estimated_impact": by_type[best_type] * 0.3,
            })

        for c in campaigns:
            if c.roi > 100 and c.budget_utilization_pct < 80:
                opportunities.append({
                    "type": "scale_campaign",
                    "description": f"Scale '{c.name}' — {c.roi:.0f}% ROI, {c.budget_utilization_pct:.0f}% budget used",
                    "estimated_impact": c.revenue * 0.2,
                })

        return opportunities

    def get_business_health_score(self, revenue_30d: float, costs_30d: float,
                                   goals_progress: float,
                                   active_campaigns: int) -> float:
        roi_score = min(self.compute_roi(revenue_30d, costs_30d) / 100, 1.0) * 0.4
        profit_score = min(self.compute_profit_margin(revenue_30d, costs_30d) / 100, 1.0) * 0.3
        goal_score = (goals_progress / 100) * 0.2
        activity_score = min(active_campaigns / 5, 1.0) * 0.1
        return round((roi_score + profit_score + goal_score + activity_score) * 100, 1)
