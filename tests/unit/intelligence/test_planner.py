"""Tests for Weekly Planner (intelligence/planner.py)."""

from unittest.mock import patch
from mindmargin.intelligence.planner import WeeklyPlanner, plan_week


class TestWeeklyPlanner:
    def test_plan_week_with_opportunities(self):
        planner = WeeklyPlanner()
        with patch("mindmargin.analytics.memory.get_top_opportunities") as mock_opps, \
             patch("mindmargin.analytics.memory.get_pipeline_history") as mock_hist, \
             patch("mindmargin.analytics.memory.get_suppressed_patterns") as mock_supp, \
             patch("mindmargin.analytics.memory.get_intelligence_rules") as mock_rules, \
             patch("mindmargin.analytics.memory.save_weekly_plan") as mock_save:
            mock_opps.return_value = [
                {"topic": "Topic A", "opportunity_score": 85, "confidence": 70,
                 "trend_score": 80, "novelty": 60, "audience_match": 70,
                 "evergreen_score": 50, "historical_performance": 65,
                 "competition": 0.3, "seasonality": 40, "scored_at": ""},
                {"topic": "Topic B", "opportunity_score": 75, "confidence": 65,
                 "trend_score": 70, "novelty": 55, "audience_match": 60,
                 "evergreen_score": 55, "historical_performance": 60,
                 "competition": 0.4, "seasonality": 35, "scored_at": ""},
            ]
            mock_hist.return_value = []
            mock_supp.return_value = []
            mock_rules.return_value = []
            mock_save.return_value = None

            plan = planner.plan_week()

            assert plan["total_opportunities"] == 2
            assert plan["summary"]["total_items"] > 0
            assert len(plan["schedule"]) > 0

    def test_plan_week_empty(self):
        planner = WeeklyPlanner()
        with patch("mindmargin.analytics.memory.get_top_opportunities") as mock_opps, \
             patch("mindmargin.analytics.memory.save_weekly_plan") as mock_save:
            mock_opps.return_value = []
            mock_save.return_value = None

            plan = planner.plan_week()

            assert plan["total_opportunities"] == 0
            assert plan["summary"]["total_items"] == 0

    def test_schedule_format_distribution(self):
        planner = WeeklyPlanner()
        with patch("mindmargin.analytics.memory.get_top_opportunities") as mock_opps, \
             patch("mindmargin.analytics.memory.get_pipeline_history") as mock_hist, \
             patch("mindmargin.analytics.memory.get_suppressed_patterns") as mock_supp, \
             patch("mindmargin.analytics.memory.get_intelligence_rules") as mock_rules, \
             patch("mindmargin.analytics.memory.save_weekly_plan") as mock_save:
            mock_opps.return_value = [
                {"topic": f"Topic {i}", "opportunity_score": 80 - i,
                 "confidence": 60, "trend_score": 70, "novelty": 50,
                 "audience_match": 60, "evergreen_score": 50,
                 "historical_performance": 55, "competition": 0.4,
                 "seasonality": 30, "scored_at": ""}
                for i in range(15)
            ]
            mock_hist.return_value = []
            mock_supp.return_value = []
            mock_rules.return_value = []
            mock_save.return_value = None

            plan = planner.plan_week()
            formats_in_use = set(e["format"] for e in plan["schedule"])
            assert len(formats_in_use) > 0
            assert plan["summary"]["days_active"] > 0

    def test_score_for_planning_deduplicates(self):
        planner = WeeklyPlanner()
        opps = [
            {"topic": "Published Topic", "opportunity_score": 90, "scored_at": ""},
            {"topic": "Fresh Topic", "opportunity_score": 80, "scored_at": ""},
        ]
        history = [{"topic": "Published Topic"}]
        suppressed = []

        ranked = planner._score_for_planning(opps, history, suppressed)
        assert len(ranked) == 2
        pub_score = next(r["planning_score"] for r in ranked if r["topic"] == "Published Topic")
        fresh_score = next(r["planning_score"] for r in ranked if r["topic"] == "Fresh Topic")
        assert pub_score < fresh_score


class TestPlanWeek:
    def test_convenience(self):
        with patch.object(WeeklyPlanner, "plan_week") as mock_plan:
            mock_plan.return_value = {"week_start": "2025-01-06", "summary": {"total_items": 5}}
            result = plan_week()
            assert result["summary"]["total_items"] == 5
