"""Tests for Daily Strategy Planner (intelligence/strategy.py)."""

from unittest.mock import patch, MagicMock
from mindmargin.intelligence.strategy import DailyPlanner, run_daily_planning


class TestDailyPlanner:
    def test_plan_with_opportunities(self):
        planner = DailyPlanner()
        with patch("mindmargin.intelligence.strategy.get_top_opportunities") as mock_opps, \
             patch("mindmargin.intelligence.strategy.get_pipeline_history") as mock_hist, \
             patch("mindmargin.intelligence.strategy.get_intelligence_rules") as mock_rules, \
             patch("mindmargin.intelligence.strategy.get_execution_log") as mock_log, \
             patch("mindmargin.intelligence.strategy.save_daily_strategy") as mock_save:
            mock_opps.return_value = [
                {"topic": "Best Topic", "opportunity_score": 85.0, "source": "test",
                 "confidence": 0.8, "scored_at": ""},
                {"topic": "Second Topic", "opportunity_score": 70.0, "source": "test",
                 "confidence": 0.7, "scored_at": ""},
            ]
            mock_hist.return_value = []
            mock_rules.return_value = []
            mock_log.return_value = []
            mock_save.return_value = None

            result = planner.plan()

            assert result["total_opportunities"] == 2
            assert result["ranked_count"] == 2
            assert result["top_pick"]["topic"] == "Best Topic"
            assert result["recommended_topic"] == "Best Topic"

    def test_plan_with_empty_opportunities(self):
        planner = DailyPlanner()
        with patch("mindmargin.intelligence.strategy.get_top_opportunities") as mock_opps, \
             patch("mindmargin.intelligence.strategy.save_daily_strategy") as mock_save:
            mock_opps.return_value = []
            mock_save.return_value = None

            result = planner.plan()

            assert result["total_opportunities"] == 0
            assert result["ranked_count"] == 0
            assert result["top_pick"] is None
            assert result["recommended_topic"] == ""

    def test_plan_skips_published_today(self):
        planner = DailyPlanner()
        today = planner.strategy_date
        with patch("mindmargin.intelligence.strategy.get_top_opportunities") as mock_opps, \
             patch("mindmargin.intelligence.strategy.get_pipeline_history") as mock_hist, \
             patch("mindmargin.intelligence.strategy.get_intelligence_rules") as mock_rules, \
             patch("mindmargin.intelligence.strategy.get_execution_log") as mock_log, \
             patch("mindmargin.intelligence.strategy.save_daily_strategy") as mock_save:
            mock_opps.return_value = [
                {"topic": "Just Published", "opportunity_score": 80.0, "source": "test",
                 "confidence": 0.8, "scored_at": ""},
                {"topic": "Fresh Topic", "opportunity_score": 75.0, "source": "test",
                 "confidence": 0.7, "scored_at": ""},
            ]
            mock_hist.return_value = []
            mock_rules.return_value = []
            mock_log.return_value = [
                {"topic": "Just Published", "executed_at": today + " 12:00:00",
                 "pipeline_status": "completed", "error": ""}
            ]
            mock_save.return_value = None

            result = planner.plan()

            assert result["ranked_count"] == 1
            assert result["top_pick"]["topic"] == "Fresh Topic"


class TestRunDailyPlanning:
    def test_run_daily_planning(self):
        with patch.object(DailyPlanner, "plan") as mock_plan:
            mock_plan.return_value = {"status": "completed", "ranked_count": 5}
            result = run_daily_planning()
            assert result["status"] == "completed"
            mock_plan.assert_called_once()
