from fastapi import APIRouter, Query
from typing import Optional

from mindmargin.business.portfolio import BusinessPortfolio
from mindmargin.business.goals import GoalEngine
from mindmargin.business.kpis import KPIEngine
from mindmargin.business.forecast import ForecastEngine
from mindmargin.business.revenue import RevenueEngine
from mindmargin.business.budget import BudgetManager
from mindmargin.business.campaigns import CampaignManager
from mindmargin.business.optimizer import BusinessOptimizer
from mindmargin.business.recommendations import BusinessRecommendationEngine
from mindmargin.business.models import (
    BusinessGoalType, RevenueType, CampaignType, ForecastWindow, utcnow,
)

router = APIRouter(prefix="/api/v1/business", tags=["business"])


@router.get("/status")
def business_status():
    portfolio = BusinessPortfolio()
    return portfolio.get_business_status()


@router.get("/report")
def business_report():
    portfolio = BusinessPortfolio()
    return portfolio.get_full_report()


@router.get("/goals")
def list_goals():
    engine = GoalEngine()
    goals = engine.list_goals()
    progress = engine.get_overall_progress()
    weighted = engine.get_weighted_score()
    return {
        "goals": [g.to_dict() for g in goals],
        "progress": progress,
        "weighted_score": weighted,
    }


@router.post("/goals")
def create_goal(goal_type: str, name: str, target_value: float,
                unit: str = "", weight: float = 1.0):
    engine = GoalEngine()
    gt = BusinessGoalType(goal_type)
    goal = engine.create_goal(gt, name, target_value, unit, weight)
    return goal.to_dict()


@router.put("/goals/{goal_id}")
def update_goal_value(goal_id: str, current_value: float):
    engine = GoalEngine()
    goal = engine.set_goal_value(goal_id, current_value)
    if not goal:
        return {"error": "Goal not found"}
    return goal.to_dict()


@router.get("/revenue")
def revenue_summary(start_date: str = "", end_date: str = ""):
    engine = RevenueEngine()
    return {
        "total": engine.get_total_revenue(start_date=start_date, end_date=end_date),
        "by_type": engine.get_revenue_by_type(start_date=start_date, end_date=end_date),
        "by_source": engine.get_revenue_by_source(start_date=start_date, end_date=end_date),
        "monthly": engine.get_monthly_revenue(12),
    }


@router.post("/revenue")
def record_revenue(revenue_type: str, amount: float, source: str = "",
                   description: str = "", date: str = ""):
    engine = RevenueEngine()
    rt = RevenueType(revenue_type)
    entry = engine.record_revenue(rt, amount, source, description, date)
    return entry.to_dict()


@router.get("/budget")
def budget_summary():
    manager = BudgetManager()
    return manager.get_budget_summary()


@router.post("/budget/cost")
def record_cost(category: str, amount: float, description: str = "",
                is_recurring: bool = False, date: str = ""):
    manager = BudgetManager()
    entry = manager.record_cost(category, amount, description, is_recurring, date)
    return entry.to_dict()


@router.get("/forecast")
def forecast_summary():
    engine = ForecastEngine()
    forecasts = engine.list_forecasts(limit=5)
    return {
        "forecasts": [f.to_dict() for f in forecasts],
    }


@router.post("/forecast/generate")
def generate_forecast(window: str = "30d", growth_rate: float = 0.05,
                      subscriber_count: int = 1000,
                      avg_views_per_video: int = 500, rpm: float = 5.0):
    engine = ForecastEngine()
    fw = ForecastWindow(window)
    rev_engine = RevenueEngine()
    budget = BudgetManager()
    revenue_entries = rev_engine.list_entries(limit=100)
    cost_entries = budget.list_costs(limit=100)
    forecast = engine.generate_forecast(
        revenue_entries, cost_entries, fw, growth_rate,
        subscriber_count, avg_views_per_video, rpm,
    )
    return forecast.to_dict()


@router.get("/campaigns")
def list_campaigns(status: Optional[str] = None, limit: int = Query(50, ge=1, le=200)):
    mgr = CampaignManager()
    cs = CampaignType(status) if status else None
    campaigns = mgr.list_campaigns(limit=limit)
    return {
        "total": len(campaigns),
        "campaigns": [c.to_dict() for c in campaigns],
        "total_budget": mgr.get_total_budget(),
        "total_spent": mgr.get_total_spent(),
        "total_revenue": mgr.get_total_revenue(),
        "overall_roi": mgr.get_overall_roi(),
    }


@router.post("/campaigns")
def create_campaign(campaign_type: str, name: str, budget: float = 0.0,
                    start_date: str = "", end_date: str = "",
                    target_audience: str = ""):
    mgr = CampaignManager()
    ct = CampaignType(campaign_type)
    campaign = mgr.create_campaign(ct, name, budget, start_date, end_date, target_audience)
    return campaign.to_dict()


@router.put("/campaigns/{campaign_id}/start")
def start_campaign(campaign_id: str):
    mgr = CampaignManager()
    c = mgr.start_campaign(campaign_id)
    if not c:
        return {"error": "Campaign not found"}
    return c.to_dict()


@router.get("/optimize")
def business_optimize():
    optimizer = BusinessOptimizer()
    portfolio = BusinessPortfolio()
    status = portfolio.get_business_status()
    goals = portfolio.goals.list_goals(enabled_only=True)
    campaigns = portfolio.campaigns.list_campaigns()
    health = optimizer.get_business_health_score(
        status["total_revenue_30d"], status["total_costs_30d"],
        portfolio.goals.get_overall_progress()["progress_pct"],
        status["active_campaigns"],
    )
    return {
        "health_score": health,
        "goal_priorities": optimizer.prioritize_goals(goals),
        "high_value_opportunities": optimizer.identify_high_value_opportunities(
            portfolio.revenue.list_entries(limit=100), campaigns,
        ),
    }


@router.get("/recommendations")
def business_recommendations(limit: int = Query(20, ge=1, le=100)):
    engine = BusinessRecommendationEngine()
    recs = engine.get_recommendations(limit=limit)
    return {
        "total": len(recs),
        "recommendations": [r.to_dict() for r in recs],
    }


@router.post("/recommendations/generate")
def generate_recommendations():
    engine = BusinessRecommendationEngine()
    recs = engine.generate_recommendations()
    return {
        "generated": len(recs),
    }


@router.put("/recommendations/{rec_id}/action")
def action_recommendation(rec_id: str, status: str = "actioned"):
    engine = BusinessRecommendationEngine()
    ok = engine.mark_actioned(rec_id, status)
    if not ok:
        return {"error": "Recommendation not found"}
    return {"status": "ok", "recommendation_id": rec_id}


@router.get("/kpis")
def kpi_summary():
    engine = KPIEngine()
    return engine.get_kpi_summary()
