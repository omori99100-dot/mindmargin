"""Tests for Feedback Engine (intelligence/feedback_engine.py)."""

from unittest.mock import patch, MagicMock
from mindmargin.intelligence.feedback_engine import FeedbackEngine, run_feedback_cycle


class TestComputeActualScore:
    def test_high_performance_video(self):
        pipeline = {
            "views": 5000, "likes": 300, "comments": 50,
            "ctr": 8.0, "average_view_percentage": 65.0,
            "watch_time_minutes": 12000, "avg_view_duration_s": 144,
        }
        engine = FeedbackEngine()
        score = engine._compute_actual_score(pipeline)
        assert 50 <= score <= 100

    def test_low_performance_video(self):
        pipeline = {
            "views": 10, "likes": 0, "comments": 0,
            "ctr": 0.5, "average_view_percentage": 10.0,
            "watch_time_minutes": 5, "avg_view_duration_s": 30,
        }
        engine = FeedbackEngine()
        score = engine._compute_actual_score(pipeline)
        assert 0 <= score <= 30

    def test_minimal_data_defaults(self):
        pipeline = {"views": 0, "likes": 0, "comments": 0}
        engine = FeedbackEngine()
        score = engine._compute_actual_score(pipeline)
        assert 0 <= score <= 50

    def test_ctr_differentiation(self):
        engine = FeedbackEngine()
        high = engine._compute_actual_score({"views": 100, "likes": 10, "comments": 2,
                                              "ctr": 8.0, "average_view_percentage": 50.0,
                                              "watch_time_minutes": 100})
        low = engine._compute_actual_score({"views": 100, "likes": 10, "comments": 2,
                                             "ctr": 0.5, "average_view_percentage": 50.0,
                                             "watch_time_minutes": 100})
        assert high > low


class TestEngagementRate:
    def test_normal_engagement(self):
        engine = FeedbackEngine()
        rate = engine._engagement_rate({"likes": 10, "comments": 2, "views": 200})
        assert rate == 0.06

    def test_zero_views(self):
        engine = FeedbackEngine()
        rate = engine._engagement_rate({"likes": 0, "comments": 0, "views": 0})
        assert rate == 0.0


class TestCollectOutcomes:
    def test_no_matching_opportunities(self):
        engine = FeedbackEngine()
        with patch("mindmargin.analytics.memory.get_pipeline_history") as mock_hist, \
             patch("mindmargin.analytics.memory.get_opportunities") as mock_opps:
            mock_hist.return_value = [{"topic": "Some Topic", "id": "abc",
                                       "views": 100, "likes": 5, "comments": 1}]
            mock_opps.return_value = []
            outcomes = engine.collect_outcomes()
            assert outcomes == []

    def test_matches_opportunities(self):
        engine = FeedbackEngine()
        with patch("mindmargin.analytics.memory.get_pipeline_history") as mock_hist, \
             patch("mindmargin.analytics.memory.get_opportunities") as mock_opps, \
             patch("mindmargin.analytics.memory.save_outcome") as mock_save, \
             patch("mindmargin.analytics.memory.get_scoring_weights") as mock_w, \
             patch.object(engine, "_save_component_errors") as mock_save_err:
            mock_hist.return_value = [{"topic": "AI History", "id": "p1",
                                       "views": 200, "likes": 15, "comments": 3,
                                       "ctr": 5.0, "average_view_percentage": 40.0,
                                       "watch_time_minutes": 300}]
            mock_opps.return_value = [{"topic": "AI History", "opportunity_score": 70.0,
                                       "source": "test", "scored_at": ""}]
            mock_save.return_value = 1
            mock_w.return_value = {}

            outcomes = engine.collect_outcomes()
            assert len(outcomes) >= 1

    def test_negative_score_opportunity_skipped(self):
        engine = FeedbackEngine()
        with patch("mindmargin.analytics.memory.get_pipeline_history") as mock_hist, \
             patch("mindmargin.analytics.memory.get_opportunities") as mock_opps, \
             patch("mindmargin.analytics.memory.save_outcome") as mock_save:
            mock_hist.return_value = [{"topic": "Bad", "id": "p1", "views": 100,
                                       "likes": 5, "comments": 1}]
            mock_opps.return_value = [{"topic": "Bad", "opportunity_score": 0,
                                       "source": "test", "scored_at": ""}]
            mock_save.return_value = 1
            outcomes = engine.collect_outcomes()
            assert outcomes == []


class TestSaveComponentErrors:
    def test_saves_all_components(self):
        engine = FeedbackEngine()
        with patch("mindmargin.analytics.memory.save_prediction_error") as mock_save, \
             patch("mindmargin.analytics.memory.get_scoring_weights") as mock_w:
            mock_w.return_value = {}
            engine._save_component_errors(1, {"topic": "T", "opportunity_score": 60,
                                               "trend_score": 0.8, "novelty": 0.6,
                                               "audience_match": 0.7, "evergreen_score": 0.5,
                                               "competition": 0.3, "historical_performance": 0.4,
                                               "seasonality": 0.2}, 50, 60)
            assert mock_save.call_count == 7


class TestUpdateWeights:
    def test_no_errors_no_change(self):
        engine = FeedbackEngine()
        with patch("mindmargin.analytics.memory.get_prediction_errors") as mock_err, \
             patch("mindmargin.analytics.memory.get_scoring_weights") as mock_w, \
             patch("mindmargin.intelligence.feedback_engine.WEIGHTS", {
                 "trend_score": 0.25, "novelty": 0.20,
             }), \
             patch("mindmargin.analytics.memory.reset_scoring_weights") as mock_reset:
            mock_err.return_value = []
            mock_w.return_value = {}
            weights = engine.update_weights(min_samples=1)
            mock_reset.assert_not_called()

    def test_underpredicted_increases_weight(self):
        engine = FeedbackEngine(learning_rate=0.5)
        with patch("mindmargin.analytics.memory.get_prediction_errors") as mock_err, \
             patch("mindmargin.analytics.memory.get_scoring_weights") as mock_w, \
             patch.object(engine, "COMPONENTS", ["trend_score"]), \
             patch("mindmargin.intelligence.feedback_engine.WEIGHTS", {
                 "trend_score": 0.25,
             }), \
             patch("mindmargin.analytics.memory.reset_scoring_weights") as mock_reset:
            mock_err.return_value = [{"error": 15.0}, {"error": 12.0}, {"error": 18.0}]
            mock_w.return_value = {}
            weights = engine.update_weights(min_samples=1)
            assert weights["trend_score"] > 0.25
            mock_reset.assert_called_once()


class TestRunFeedbackCycle:
    def test_full_cycle(self):
        engine = FeedbackEngine()
        with patch.object(engine, "collect_outcomes") as mock_collect, \
             patch.object(engine, "update_weights") as mock_weights:
            mock_collect.return_value = [{"topic": "T", "predicted": 70, "actual": 80, "error": 10}]
            mock_weights.return_value = {"trend_score": 0.26}
            result = engine.run_feedback_cycle()
            assert result["outcomes_collected"] == 1
            assert result["weights_changed"] >= 0

    def test_convenience_function(self):
        with patch.object(FeedbackEngine, "run_feedback_cycle") as mock_run:
            mock_run.return_value = {"status": "ok"}
            result = run_feedback_cycle()
            assert result["status"] == "ok"
            mock_run.assert_called_once()
