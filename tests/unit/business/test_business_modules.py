import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from mindmargin.business.models import (
    BusinessGoal, KPIRecord, RevenueEntry, CostEntry, Campaign, Product,
    ForecastPoint, ForecastResult, BudgetAllocation, BusinessRecommendation,
    BusinessGoalType, RevenueType, CampaignType, CampaignStatus,
    ProductType, ForecastWindow, utcnow,
)


# ── Models ──

class TestBusinessGoal:
    def test_create(self):
        g = BusinessGoal(goal_id="g1", goal_type=BusinessGoalType.MAXIMIZE_REVENUE,
                         name="Revenue", target_value=1000, current_value=500)
        assert g.progress_pct == 50.0
        assert not g.is_achieved

    def test_achieved(self):
        g = BusinessGoal(goal_id="g2", goal_type=BusinessGoalType.MAXIMIZE_REVENUE,
                         name="Revenue", target_value=100, current_value=100)
        assert g.is_achieved

    def test_to_dict_roundtrip(self):
        g = BusinessGoal(goal_id="g3", goal_type=BusinessGoalType.MAXIMIZE_SUBSCRIBERS,
                         name="Subs", target_value=10000, weight=0.8)
        d = g.to_dict()
        assert d["goal_type"] == "maximize_subscribers"
        g2 = BusinessGoal.from_dict(d)
        assert g2.weight == 0.8


class TestRevenueEntry:
    def test_create(self):
        e = RevenueEntry(entry_id="r1", revenue_type=RevenueType.AD_REVENUE, amount=100.0)
        assert e.amount == 100.0

    def test_to_dict_roundtrip(self):
        e = RevenueEntry(entry_id="r2", revenue_type=RevenueType.AFFILIATE_REVENUE, amount=50.0)
        d = e.to_dict()
        assert d["revenue_type"] == "affiliate_revenue"
        e2 = RevenueEntry.from_dict(d)
        assert e2.amount == 50.0


class TestCampaign:
    def test_roi(self):
        c = Campaign(campaign_id="c1", campaign_type=CampaignType.AFFILIATE,
                     name="Test", budget=100, spent=50, revenue=200)
        assert c.roi == 300.0

    def test_budget_utilization(self):
        c = Campaign(campaign_id="c2", campaign_type=CampaignType.SPONSOR,
                     name="Test", budget=100, spent=75)
        assert c.budget_utilization_pct == 75.0

    def test_to_dict_roundtrip(self):
        c = Campaign(campaign_id="c3", campaign_type=CampaignType.PRODUCT_LAUNCH,
                     name="Launch", budget=500, status=CampaignStatus.ACTIVE)
        d = c.to_dict()
        assert d["campaign_type"] == "product_launch"
        assert d["status"] == "active"


class TestProduct:
    def test_margin(self):
        p = Product(product_id="p1", product_type=ProductType.COURSE,
                    name="Course", price=100, cost=30)
        assert p.margin_pct == 70.0

    def test_to_dict_roundtrip(self):
        p = Product(product_id="p2", product_type=ProductType.EBOOK,
                    name="Book", price=20, cost=5)
        d = p.to_dict()
        assert d["product_type"] == "ebook"
        p2 = Product.from_dict(d)
        assert p2.margin_pct == 75.0


class TestForecastResult:
    def test_create(self):
        f = ForecastResult(forecast_id="f1", window="30d", points=[], summary={"total": 100})
        assert f.window == "30d"


class TestBudgetAllocation:
    def test_remaining(self):
        a = BudgetAllocation(category="api", limit=1000, spent=300)
        assert a.remaining == 700.0

    def test_utilization(self):
        a = BudgetAllocation(category="llm", limit=500, spent=250)
        assert a.utilization_pct == 50.0


# ── Goal Engine ──

class TestGoalEngine:
    def test_defaults_exist(self, tmp_path):
        from mindmargin.business.goals import GoalEngine
        engine = GoalEngine(persist_dir=str(tmp_path))
        goals = engine.list_goals()
        assert len(goals) >= 5

    def test_create_goal(self, tmp_path):
        from mindmargin.business.goals import GoalEngine
        engine = GoalEngine(persist_dir=str(tmp_path))
        g = engine.create_goal(BusinessGoalType.MAXIMIZE_REVENUE, "Test Goal", 5000, "USD")
        assert g.target_value == 5000

    def test_set_goal_value(self, tmp_path):
        from mindmargin.business.goals import GoalEngine
        engine = GoalEngine(persist_dir=str(tmp_path))
        g = engine.set_goal_value("goal_revenue", 5000)
        assert g is not None
        assert g.current_value == 5000

    def test_overall_progress(self, tmp_path):
        from mindmargin.business.goals import GoalEngine
        engine = GoalEngine(persist_dir=str(tmp_path))
        progress = engine.get_overall_progress()
        assert progress["total"] >= 5

    def test_weighted_score(self, tmp_path):
        from mindmargin.business.goals import GoalEngine
        engine = GoalEngine(persist_dir=str(tmp_path))
        score = engine.get_weighted_score()
        assert 0 <= score <= 100

    def test_delete_goal(self, tmp_path):
        from mindmargin.business.goals import GoalEngine
        engine = GoalEngine(persist_dir=str(tmp_path))
        g = engine.create_goal(BusinessGoalType.BRAND_GROWTH, "Del", 100)
        assert engine.delete_goal(g.goal_id) is True


# ── KPI Engine ──

class TestKPIEngine:
    def test_record_kpi(self, tmp_path):
        from mindmargin.business.kpis import KPIEngine
        engine = KPIEngine(persist_dir=str(tmp_path))
        kpi = engine.record_kpi("views", 1000, previous_value=800, unit="count")
        assert kpi.value == 1000
        assert kpi.change_pct == 25.0

    def test_get_latest(self, tmp_path):
        from mindmargin.business.kpis import KPIEngine
        engine = KPIEngine(persist_dir=str(tmp_path))
        engine.record_kpi("subs", 100)
        import time; time.sleep(0.01)
        engine.record_kpi("subs", 150)
        latest = engine.get_latest_kpi("subs")
        assert latest is not None
        assert latest.name == "subs"
        assert latest.kpi_id is not None

    def test_compute_rpm(self, tmp_path):
        from mindmargin.business.kpis import KPIEngine
        engine = KPIEngine(persist_dir=str(tmp_path))
        rpm = engine.compute_rpm(50.0, 10000)
        assert rpm == 5.0

    def test_compute_cpm(self, tmp_path):
        from mindmargin.business.kpis import KPIEngine
        engine = KPIEngine(persist_dir=str(tmp_path))
        cpm = engine.compute_cpm(100.0, 50000)
        assert cpm == 2.0

    def test_compute_ctr(self, tmp_path):
        from mindmargin.business.kpis import KPIEngine
        engine = KPIEngine(persist_dir=str(tmp_path))
        ctr = engine.compute_ctr(50, 1000)
        assert ctr == 5.0

    def test_kpi_summary(self, tmp_path):
        from mindmargin.business.kpis import KPIEngine
        engine = KPIEngine(persist_dir=str(tmp_path))
        engine.record_kpi("test", 1, category="cat1")
        summary = engine.get_kpi_summary()
        assert summary["total_kpis"] >= 1


# ── Revenue Engine ──

class TestRevenueEngine:
    def test_record_revenue(self, tmp_path):
        from mindmargin.business.revenue import RevenueEngine
        engine = RevenueEngine(persist_dir=str(tmp_path))
        entry = engine.record_revenue(RevenueType.AD_REVENUE, 100.0, source="youtube")
        assert entry.amount == 100.0

    def test_total_revenue(self, tmp_path):
        from mindmargin.business.revenue import RevenueEngine
        engine = RevenueEngine(persist_dir=str(tmp_path))
        engine.record_revenue(RevenueType.AD_REVENUE, 100.0)
        engine.record_revenue(RevenueType.AFFILIATE_REVENUE, 50.0)
        total = engine.get_total_revenue()
        assert total == 150.0

    def test_revenue_by_type(self, tmp_path):
        from mindmargin.business.revenue import RevenueEngine
        engine = RevenueEngine(persist_dir=str(tmp_path))
        engine.record_revenue(RevenueType.AD_REVENUE, 100.0)
        engine.record_revenue(RevenueType.AD_REVENUE, 50.0)
        by_type = engine.get_revenue_by_type()
        assert by_type.get("ad_revenue", 0) == 150.0


# ── Forecast Engine ──

class TestForecastEngine:
    def test_generate_forecast(self, tmp_path):
        from mindmargin.business.forecast import ForecastEngine
        engine = ForecastEngine(persist_dir=str(tmp_path))
        from mindmargin.business.models import RevenueEntry, CostEntry
        rev = [RevenueEntry(entry_id="r1", revenue_type=RevenueType.AD_REVENUE,
                            amount=100.0, date="2026-07-01")]
        costs = [CostEntry(entry_id="c1", category="api", amount=50.0, date="2026-07-01")]
        forecast = engine.generate_forecast(rev, costs, ForecastWindow.DAYS_30)
        assert len(forecast.points) == 30
        assert forecast.summary["total_revenue"] > 0

    def test_list_forecasts(self, tmp_path):
        from mindmargin.business.forecast import ForecastEngine
        engine = ForecastEngine(persist_dir=str(tmp_path))
        from mindmargin.business.models import RevenueEntry, CostEntry
        engine.generate_forecast([], [], ForecastWindow.DAYS_30)
        forecasts = engine.list_forecasts()
        assert len(forecasts) >= 1


# ── Campaign Manager ──

class TestCampaignManager:
    def test_create_campaign(self, tmp_path):
        from mindmargin.business.campaigns import CampaignManager
        mgr = CampaignManager(persist_dir=str(tmp_path))
        c = mgr.create_campaign(CampaignType.AFFILIATE, "Test Campaign", budget=1000)
        assert c.budget == 1000

    def test_start_campaign(self, tmp_path):
        from mindmargin.business.campaigns import CampaignManager
        mgr = CampaignManager(persist_dir=str(tmp_path))
        c = mgr.create_campaign(CampaignType.SPONSOR, "Sponsor Deal")
        started = mgr.start_campaign(c.campaign_id)
        assert started.status == CampaignStatus.ACTIVE

    def test_record_spend_and_revenue(self, tmp_path):
        from mindmargin.business.campaigns import CampaignManager
        mgr = CampaignManager(persist_dir=str(tmp_path))
        c = mgr.create_campaign(CampaignType.AFFILIATE, "Aff", budget=500)
        mgr.record_spend(c.campaign_id, 200)
        mgr.record_revenue(c.campaign_id, 800)
        updated = mgr.get_campaign(c.campaign_id)
        assert updated.spent == 200
        assert updated.revenue == 800
        assert updated.roi == 300.0

    def test_overall_roi(self, tmp_path):
        from mindmargin.business.campaigns import CampaignManager
        mgr = CampaignManager(persist_dir=str(tmp_path))
        c = mgr.create_campaign(CampaignType.AFFILIATE, "Test", budget=100)
        mgr.record_spend(c.campaign_id, 100)
        mgr.record_revenue(c.campaign_id, 250)
        assert mgr.get_overall_roi() == 150.0


# ── Budget Manager ──

class TestBudgetManager:
    def test_record_cost(self, tmp_path):
        from mindmargin.business.budget import BudgetManager
        mgr = BudgetManager(persist_dir=str(tmp_path))
        entry = mgr.record_cost("api", 25.0, "Ollama API")
        assert entry.amount == 25.0

    def test_total_costs(self, tmp_path):
        from mindmargin.business.budget import BudgetManager
        mgr = BudgetManager(persist_dir=str(tmp_path))
        mgr.record_cost("api", 100.0)
        mgr.record_cost("llm", 50.0)
        total = mgr.get_total_costs()
        assert total == 150.0

    def test_costs_by_category(self, tmp_path):
        from mindmargin.business.budget import BudgetManager
        mgr = BudgetManager(persist_dir=str(tmp_path))
        mgr.record_cost("api", 100.0)
        mgr.record_cost("api", 50.0)
        mgr.record_cost("llm", 30.0)
        by_cat = mgr.get_costs_by_category()
        assert by_cat.get("api", 0) == 150.0

    def test_budget_summary(self, tmp_path):
        from mindmargin.business.budget import BudgetManager
        mgr = BudgetManager(persist_dir=str(tmp_path))
        summary = mgr.get_budget_summary()
        assert "total_limit" in summary


# ── Business Optimizer ──

class TestBusinessOptimizer:
    def test_compute_roi(self):
        from mindmargin.business.optimizer import BusinessOptimizer
        opt = BusinessOptimizer()
        assert opt.compute_roi(200, 100) == 100.0

    def test_compute_profit_margin(self):
        from mindmargin.business.optimizer import BusinessOptimizer
        opt = BusinessOptimizer()
        assert opt.compute_profit_margin(200, 100) == 50.0

    def test_compute_rpm(self):
        from mindmargin.business.optimizer import BusinessOptimizer
        opt = BusinessOptimizer()
        assert opt.compute_rpm(50, 10000) == 5.0

    def test_optimize_pricing(self):
        from mindmargin.business.optimizer import BusinessOptimizer
        opt = BusinessOptimizer()
        result = opt.optimize_pricing(100, 0.02, competitor_price=90)
        assert result["optimal_price"] < 100

    def test_health_score(self):
        from mindmargin.business.optimizer import BusinessOptimizer
        opt = BusinessOptimizer()
        score = opt.get_business_health_score(1000, 500, 75, 3)
        assert 0 <= score <= 100


# ── Product Manager ──

class TestProductManager:
    def test_create_product(self, tmp_path):
        from mindmargin.business.products import ProductManager
        mgr = ProductManager(persist_dir=str(tmp_path))
        p = mgr.create_product(ProductType.COURSE, "Python Course", 99.0, 30.0)
        assert p.price == 99.0

    def test_record_sale(self, tmp_path):
        from mindmargin.business.products import ProductManager
        mgr = ProductManager(persist_dir=str(tmp_path))
        p = mgr.create_product(ProductType.EBOOK, "Guide", 19.99)
        mgr.record_sale(p.product_id, 10)
        updated = mgr.get_product(p.product_id)
        assert updated.sales_count == 10
        assert updated.total_revenue == round(19.99 * 10, 2)


# ── Sponsorship Manager ──

class TestSponsorshipManager:
    def test_create_sponsorship(self, tmp_path):
        from mindmargin.business.sponsorships import SponsorshipManager
        mgr = SponsorshipManager(persist_dir=str(tmp_path))
        s = mgr.create_sponsorship("Acme Corp", 5000, deliverables=["2 videos"])
        assert s["deal_value"] == 5000

    def test_record_payment(self, tmp_path):
        from mindmargin.business.sponsorships import SponsorshipManager
        mgr = SponsorshipManager(persist_dir=str(tmp_path))
        s = mgr.create_sponsorship("TechCo", 3000)
        mgr.record_payment(s["sponsorship_id"], 1500)
        updated = mgr.get_sponsorship(s["sponsorship_id"])
        assert updated["payments_received"] == 1500


# ── Affiliate Manager ──

class TestAffiliateManager:
    def test_create_program(self, tmp_path):
        from mindmargin.business.affiliate import AffiliateManager
        mgr = AffiliateManager(persist_dir=str(tmp_path))
        p = mgr.create_affiliate_program("Amazon", 0.10)
        assert p["commission_rate"] == 0.10

    def test_record_conversion(self, tmp_path):
        from mindmargin.business.affiliate import AffiliateManager
        mgr = AffiliateManager(persist_dir=str(tmp_path))
        p = mgr.create_affiliate_program("Amazon", 0.10)
        mgr.record_conversion(p["affiliate_id"], 100.0)
        updated = mgr.get_program(p["affiliate_id"])
        assert updated["total_commission"] == 10.0


# ── Pricing Engine ──

class TestPricingEngine:
    def test_get_price(self):
        from mindmargin.business.pricing import PricingEngine
        engine = PricingEngine()
        result = engine.get_price("course")
        assert result["base_price"] == 99.0

    def test_volume_discount(self):
        from mindmargin.business.pricing import PricingEngine
        engine = PricingEngine()
        result = engine.get_price("template", quantity=5)
        assert result["discount_applied"] > 0

    def test_bundle_price(self):
        from mindmargin.business.pricing import PricingEngine
        engine = PricingEngine()
        result = engine.get_bundle_price(["course", "ebook"])
        assert result["total_final"] < result["total_base"]

    def test_suggest_price(self):
        from mindmargin.business.pricing import PricingEngine
        engine = PricingEngine()
        result = engine.suggest_price("course", competitor_price=120)
        assert result["suggested_price"] < 120


# ── Membership Manager ──

class TestMembershipManager:
    def test_create_tier(self, tmp_path):
        from mindmargin.business.memberships import MembershipManager
        mgr = MembershipManager(persist_dir=str(tmp_path))
        t = mgr.create_tier("Gold", 9.99, benefits=["Exclusive content"])
        assert t["price_monthly"] == 9.99

    def test_record_join(self, tmp_path):
        from mindmargin.business.memberships import MembershipManager
        mgr = MembershipManager(persist_dir=str(tmp_path))
        t = mgr.create_tier("Silver", 4.99)
        mgr.record_member_join(t["membership_id"])
        mgr.record_member_join(t["membership_id"])
        assert mgr.get_total_members() == 2
        assert mgr.get_mrr() == 9.98


# ── Business Portfolio ──

class TestBusinessPortfolio:
    def test_get_status(self, tmp_path):
        from mindmargin.business.portfolio import BusinessPortfolio
        portfolio = BusinessPortfolio(persist_dir=str(tmp_path))
        status = portfolio.get_business_status()
        assert "total_revenue_30d" in status
        assert "roi_30d" in status

    def test_get_report(self, tmp_path):
        from mindmargin.business.portfolio import BusinessPortfolio
        portfolio = BusinessPortfolio(persist_dir=str(tmp_path))
        report = portfolio.get_full_report()
        assert "status" in report
        assert "goals" in report


# ── Business Recommendation Engine ──

class TestBusinessRecommendationEngine:
    def test_generate(self, tmp_path):
        from mindmargin.business.recommendations import BusinessRecommendationEngine
        engine = BusinessRecommendationEngine(persist_dir=str(tmp_path))
        recs = engine.generate_recommendations()
        assert len(recs) > 0

    def test_mark_actioned(self, tmp_path):
        from mindmargin.business.recommendations import BusinessRecommendationEngine
        engine = BusinessRecommendationEngine(persist_dir=str(tmp_path))
        recs = engine.generate_recommendations()
        ok = engine.mark_actioned(recs[0].recommendation_id)
        assert ok is True


# ── REST API ──

class TestBusinessAPI:
    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from mindmargin.api.server import app
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c

    def test_status(self, client):
        resp = client.get("/api/v1/business/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_revenue_30d" in data

    def test_goals(self, client):
        resp = client.get("/api/v1/business/goals")
        assert resp.status_code == 200
        data = resp.json()
        assert "goals" in data

    def test_revenue(self, client):
        resp = client.get("/api/v1/business/revenue")
        assert resp.status_code == 200

    def test_budget(self, client):
        resp = client.get("/api/v1/business/budget")
        assert resp.status_code == 200

    def test_forecast(self, client):
        resp = client.get("/api/v1/business/forecast")
        assert resp.status_code == 200

    def test_campaigns(self, client):
        resp = client.get("/api/v1/business/campaigns")
        assert resp.status_code == 200

    def test_optimize(self, client):
        resp = client.get("/api/v1/business/optimize")
        assert resp.status_code == 200

    def test_recommendations(self, client):
        resp = client.get("/api/v1/business/recommendations")
        assert resp.status_code == 200

    def test_report(self, client):
        resp = client.get("/api/v1/business/report")
        assert resp.status_code == 200

    def test_kpis(self, client):
        resp = client.get("/api/v1/business/kpis")
        assert resp.status_code == 200
