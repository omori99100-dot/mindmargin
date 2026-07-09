"""Tests for Confidence Estimation (intelligence/confidence.py)."""

from unittest.mock import patch
from mindmargin.intelligence.confidence import (
    ConfidenceEstimator, estimate_confidence, enrich_opportunities,
)


class TestConfidenceEstimator:
    def test_estimate_with_opportunity(self):
        estimator = ConfidenceEstimator()
        with patch("mindmargin.analytics.memory.get_pipeline_history") as mock_hist, \
             patch("mindmargin.analytics.memory.get_outcomes") as mock_out, \
             patch("mindmargin.analytics.memory.get_trend_sources") as mock_src, \
             patch("mindmargin.analytics.memory.get_top_performers") as mock_perf:
            mock_hist.return_value = [{"topic": "T1"}, {"topic": "T2"}]
            mock_out.return_value = [{"prediction_error": 5}, {"prediction_error": -3}]
            mock_src.return_value = [{"topic": "AI Future", "source": "historical", "confidence": 0.8}]
            mock_perf.return_value = [{"topic": "AI History", "views": 5000}]

            opp = {
                "topic": "AI Future",
                "trend_score": 80, "novelty": 60,
                "audience_match": 70, "evergreen_score": 50,
                "historical_performance": 65, "competition": 0.3,
                "scored_at": "",
            }
            confidence = estimator.estimate(opp)
            assert 0 <= confidence <= 100

    def test_freshness_recent(self):
        estimator = ConfidenceEstimator()
        opp = {"scored_at": "2025-01-01 00:00:00"}
        factor = estimator._freshness_factor(opp)
        assert factor <= 100

    def test_freshness_no_date(self):
        estimator = ConfidenceEstimator()
        factor = estimator._freshness_factor({})
        assert factor == 50.0

    def test_source_agreement_no_sources(self):
        estimator = ConfidenceEstimator()
        with patch("mindmargin.analytics.memory.get_trend_sources") as mock_src:
            mock_src.return_value = []
            factor = estimator._source_agreement_factor({"topic": "Test"})
            assert factor <= 50

    def test_variance_factor_uniform(self):
        estimator = ConfidenceEstimator()
        opp = {"trend_score": 80, "novelty": 80, "audience_match": 80,
               "evergreen_score": 80, "historical_performance": 80}
        factor = estimator._score_variance_factor(opp)
        assert factor >= 90

    def test_variance_factor_diverse(self):
        estimator = ConfidenceEstimator()
        opp = {"trend_score": 90, "novelty": 10, "audience_match": 90,
               "evergreen_score": 10, "historical_performance": 90}
        factor = estimator._score_variance_factor(opp)
        assert factor < 90

    def test_prediction_consistency_few_outcomes(self):
        estimator = ConfidenceEstimator()
        with patch("mindmargin.analytics.memory.get_outcomes") as mock_out:
            mock_out.return_value = []
            factor = estimator._prediction_consistency({})
            assert factor == 50.0


class TestEnrichOpportunities:
    def test_enrich_empty(self):
        result = enrich_opportunities([])
        assert result == []

    def test_enrich_adds_confidence(self):
        with patch("mindmargin.analytics.memory.get_pipeline_history") as mock_hist, \
             patch("mindmargin.analytics.memory.get_outcomes") as mock_out, \
             patch("mindmargin.analytics.memory.get_trend_sources") as mock_src, \
             patch("mindmargin.analytics.memory.get_top_performers") as mock_perf:
            mock_hist.return_value = [{"topic": "T1"}]
            mock_out.return_value = []
            mock_src.return_value = []
            mock_perf.return_value = []

            opps = [{"topic": "Test Topic", "trend_score": 50, "novelty": 50,
                     "audience_match": 50, "evergreen_score": 50,
                     "historical_performance": 50, "competition": 0.5, "scored_at": ""}]
            result = enrich_opportunities(opps)
            assert result[0].get("confidence", 0) > 0


class TestEstimateConfidence:
    def test_convenience(self):
        with patch.object(ConfidenceEstimator, "estimate") as mock_est:
            mock_est.return_value = 75.0
            result = estimate_confidence({"topic": "Test"})
            assert result == 75.0
