import logging
from typing import Optional

from mindmargin.business.models import (
    BusinessGoal, RevenueEntry, CostEntry, Campaign, Product,
    RevenueType, utcnow,
)
from mindmargin.business.revenue import RevenueEngine
from mindmargin.business.budget import BudgetManager
from mindmargin.business.campaigns import CampaignManager
from mindmargin.business.goals import GoalEngine
from mindmargin.business.kpis import KPIEngine
from mindmargin.business.optimizer import BusinessOptimizer

logger = logging.getLogger(__name__)


class BusinessPortfolio:
    def __init__(self, persist_dir: str = ""):
        self.revenue = RevenueEngine(persist_dir=persist_dir)
        self.budget = BudgetManager(persist_dir=persist_dir)
        self.campaigns = CampaignManager(persist_dir=persist_dir)
        self.goals = GoalEngine(persist_dir=persist_dir)
        self.kpis = KPIEngine(persist_dir=persist_dir)
        self.optimizer = BusinessOptimizer()

    def get_business_status(self) -> dict:
        now = utcnow()[:10]
        from datetime import datetime, timedelta
        d30 = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        d90 = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
        d365 = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")

        rev_30d = self.revenue.get_total_revenue(start_date=d30)
        rev_90d = self.revenue.get_total_revenue(start_date=d90)
        rev_365d = self.revenue.get_total_revenue(start_date=d365)
        cost_30d = self.budget.get_total_costs(start_date=d30)
        cost_90d = self.budget.get_total_costs(start_date=d90)

        profit_30d = rev_30d - cost_30d
        profit_90d = rev_90d - cost_90d
        roi_30d = self.optimizer.compute_roi(rev_30d, cost_30d)
        roi_90d = self.optimizer.compute_roi(rev_90d, cost_90d)

        goals = self.goals.list_goals(enabled_only=True)
        achieved = sum(1 for g in goals if g.is_achieved)

        active_campaigns = len(self.campaigns.get_active_campaigns())
        budget_summary = self.budget.get_budget_summary()

        return {
            "total_revenue_30d": rev_30d,
            "total_revenue_90d": rev_90d,
            "total_revenue_365d": rev_365d,
            "total_costs_30d": cost_30d,
            "total_costs_90d": cost_90d,
            "profit_30d": round(profit_30d, 2),
            "profit_90d": round(profit_90d, 2),
            "roi_30d": roi_30d,
            "roi_90d": roi_90d,
            "rpm": self.kpis.compute_rpm(rev_30d, 10000),
            "active_campaigns": active_campaigns,
            "goals_achieved": achieved,
            "goals_total": len(goals),
            "budget_utilization_pct": budget_summary["utilization_pct"],
            "revenue_by_type": self.revenue.get_revenue_by_type(start_date=d30),
            "costs_by_category": self.budget.get_costs_by_category(start_date=d30),
        }

    def get_full_report(self) -> dict:
        status = self.get_business_status()
        goals = self.goals.list_goals()
        goal_progress = self.goals.get_overall_progress()
        weighted_score = self.goals.get_weighted_score()
        campaigns = self.campaigns.list_campaigns()
        budget_summary = self.budget.get_budget_summary()
        monthly_revenue = self.revenue.get_monthly_revenue(6)
        monthly_costs = self.budget.get_monthly_costs(6)

        return {
            "status": status,
            "goals": [g.to_dict() for g in goals],
            "goal_progress": goal_progress,
            "weighted_score": weighted_score,
            "campaigns": [c.to_dict() for c in campaigns],
            "budget": budget_summary,
            "monthly_revenue": monthly_revenue,
            "monthly_costs": monthly_costs,
        }
