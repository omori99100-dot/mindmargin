"""Tests for Weekly Intelligence Report (intelligence/reports.py)."""

from unittest.mock import patch, MagicMock
from mindmargin.intelligence.reports import WeeklyReportGenerator, run_weekly_report


class TestWeeklyReportGenerator:
    def test_generate_with_data(self):
        with patch("mindmargin.intelligence.reports.get_pipeline_history") as mock_hist, \
             patch("mindmargin.intelligence.reports.get_analytics_history") as mock_analytics, \
             patch("mindmargin.intelligence.reports.get_all_intelligence_rules") as mock_rules, \
             patch("mindmargin.intelligence.reports.get_opportunities") as mock_opps, \
             patch("mindmargin.intelligence.reports.save_weekly_report") as mock_save:
            mock_hist.return_value = [
                {"id": "p1", "topic": "Enron", "youtube_video_id": "vid1",
                 "views": 500, "created_at": "2026-06-28 10:00:00"},
                {"id": "p2", "topic": "FTX", "youtube_video_id": "vid2",
                 "views": 300, "created_at": "2026-06-25 10:00:00"},
            ]
            mock_analytics.return_value = [
                {"ctr": 0.05, "views": 500, "likes": 20, "comments": 5},
                {"ctr": 0.03, "views": 300, "likes": 10, "comments": 2},
            ]
            mock_rules.return_value = [
                {"category": "title_format", "confidence": 0.8, "score": 70, "value": "good"},
            ]
            mock_opps.return_value = [
                {"source": "historical_anniversaries", "opportunity_score": 65},
            ]
            mock_save.return_value = None

            generator = WeeklyReportGenerator()
            result = generator.generate()

            assert "week_start" in result
            assert "week_end" in result
            assert result["top_topics"] == [
                {"topic": "Enron", "views": 500},
                {"topic": "FTX", "views": 300},
            ]
            assert result["worst_topics"] == [
                {"topic": "FTX", "views": 300},
                {"topic": "Enron", "views": 500},
            ]
            assert result["trend_changes"] == [
                {"source": "historical_anniversaries", "avg_score": 65.0, "count": 1},
            ]
            assert result["growth_rate"]["rate"] != 0

    def test_generate_without_data(self):
        with patch("mindmargin.intelligence.reports.get_pipeline_history") as mock_hist, \
             patch("mindmargin.intelligence.reports.get_analytics_history") as mock_analytics, \
             patch("mindmargin.intelligence.reports.get_all_intelligence_rules") as mock_rules, \
             patch("mindmargin.intelligence.reports.get_opportunities") as mock_opps, \
             patch("mindmargin.intelligence.reports.save_weekly_report") as mock_save:
            mock_hist.return_value = []
            mock_analytics.return_value = []
            mock_rules.return_value = []
            mock_opps.return_value = []
            mock_save.return_value = None

            generator = WeeklyReportGenerator()
            result = generator.generate()

            assert "week_start" in result
            assert result["top_topics"] == []
            assert result["growth_rate"]["rate"] == 0
            assert result["growth_rate"]["trend"] == "insufficient_data"
            assert result["engagement_changes"]["ctr_trend"] == "unknown"

    def test_growth_rate_computation(self):
        with patch("mindmargin.intelligence.reports.get_pipeline_history") as mock_hist, \
             patch("mindmargin.intelligence.reports.get_analytics_history") as mock_analytics, \
             patch("mindmargin.intelligence.reports.get_all_intelligence_rules") as mock_rules, \
             patch("mindmargin.intelligence.reports.get_opportunities") as mock_opps, \
             patch("mindmargin.intelligence.reports.save_weekly_report") as mock_save:
            mock_hist.return_value = [
                {"id": f"p{i}", "topic": f"Topic {i}", "youtube_video_id": f"vid{i}",
                 "views": 100 * i, "created_at": "2026-06-28 10:00:00"}
                for i in range(1, 5)
            ]
            mock_analytics.return_value = []
            mock_rules.return_value = []
            mock_opps.return_value = []
            mock_save.return_value = None

            generator = WeeklyReportGenerator()
            result = generator.generate()
            # First half: 100+200=300, Second half: 300+400=700, growth: (700-300)/300*100 = 133.3%
            assert result["growth_rate"]["trend"] == "growing"

    def test_improvements_suggested(self):
        with patch("mindmargin.intelligence.reports.get_pipeline_history") as mock_hist, \
             patch("mindmargin.intelligence.reports.get_analytics_history") as mock_analytics, \
             patch("mindmargin.intelligence.reports.get_all_intelligence_rules") as mock_rules, \
             patch("mindmargin.intelligence.reports.get_opportunities") as mock_opps, \
             patch("mindmargin.intelligence.reports.save_weekly_report") as mock_save:
            mock_hist.return_value = []
            mock_analytics.return_value = [{"ctr": 0.01}]
            mock_rules.return_value = []
            mock_opps.return_value = []
            mock_save.return_value = None

            generator = WeeklyReportGenerator()
            result = generator.generate()
            assert len(result["improvements"]) >= 1


class TestRunWeeklyReport:
    def test_run_weekly_report(self):
        with patch.object(WeeklyReportGenerator, "generate") as mock_gen:
            mock_gen.return_value = {"status": "completed", "week_start": "2026-06-22"}
            result = run_weekly_report()
            assert result["status"] == "completed"
            mock_gen.assert_called_once()
