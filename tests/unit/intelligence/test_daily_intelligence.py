"""Tests for daily_intelligence job (jobs/daily_intelligence.py)."""

from unittest.mock import patch, MagicMock
from mindmargin.jobs.daily_intelligence import run_intelligence_cycle, run_daily_intelligence_job


class TestRunIntelligenceCycle:
    @patch("mindmargin.intelligence.scoring.run_opportunity_scoring")
    @patch("mindmargin.intelligence.performance.run_performance_analysis")
    @patch("mindmargin.intelligence.learning.run_learning_cycle")
    @patch("mindmargin.intelligence.channel_memory.update_channel_memory_from_history")
    @patch("mindmargin.intelligence.strategy.run_daily_planning")
    def test_full_cycle(self, mock_strategy, mock_memory, mock_learning,
                        mock_perf, mock_scoring):
        mock_scoring.return_value = [{"topic": "T1"}, {"topic": "T2"}]
        mock_perf.return_value = [{"category": "hook", "key": "question", "score": 70}]
        mock_learning.return_value = [{"category": "title", "key": "how", "score": 80}]
        mock_memory.return_value = 3
        mock_strategy.return_value = {
            "recommended_topic": "Best Topic",
            "ranked_count": 5,
        }

        result = run_intelligence_cycle()

        assert result["status"] == "completed"
        assert result["stages"]["scoring"]["status"] == "completed"
        assert result["stages"]["performance"]["status"] == "completed"
        assert result["stages"]["learning"]["status"] == "completed"
        assert result["stages"]["memory"]["status"] == "completed"
        assert result["stages"]["strategy"]["status"] == "completed"
        assert result["stages"]["weekly_report"]["status"] == "skipped"

    @patch("mindmargin.intelligence.scoring.run_opportunity_scoring")
    def test_scoring_failure(self, mock_scoring):
        mock_scoring.side_effect = ValueError("scoring failed")

        with patch("mindmargin.intelligence.performance.run_performance_analysis") as mock_perf, \
             patch("mindmargin.intelligence.learning.run_learning_cycle") as mock_learn, \
             patch("mindmargin.intelligence.channel_memory.update_channel_memory_from_history") as mock_mem, \
             patch("mindmargin.intelligence.strategy.run_daily_planning") as mock_strat:
            mock_perf.return_value = []
            mock_learn.return_value = []
            mock_mem.return_value = 0
            mock_strat.return_value = {"recommended_topic": "", "ranked_count": 0}

            result = run_intelligence_cycle()
            assert result["stages"]["scoring"]["status"] == "failed"


class TestRunDailyIntelligenceJob:
    def test_entry_point_success(self):
        with patch("mindmargin.jobs.daily_intelligence.run_intelligence_cycle") as mock_cycle:
            mock_cycle.return_value = {"status": "completed", "stages": {}}
            result = run_daily_intelligence_job()
            assert result["status"] == "completed"

    def test_entry_point_failure(self):
        with patch("mindmargin.jobs.daily_intelligence.run_intelligence_cycle") as mock_cycle:
            mock_cycle.side_effect = RuntimeError("catastrophic failure")
            result = run_daily_intelligence_job()
            assert result["status"] == "failed"
            assert "catastrophic" in result["error"]
