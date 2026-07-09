"""Tests for Prediction Horizon (intelligence/horizon.py)."""

from unittest.mock import patch
from mindmargin.intelligence.horizon import (
    PredictionHorizon, forecast_all, FORECAST_WINDOWS,
)


class TestPredictionHorizon:
    def test_forecast_all_with_opportunities(self):
        horizon = PredictionHorizon()
        with patch("mindmargin.analytics.memory.get_top_opportunities") as mock_opps, \
             patch("mindmargin.analytics.memory.save_forecast") as mock_save, \
             patch("mindmargin.analytics.memory.get_trend_sources") as mock_src, \
             patch("mindmargin.analytics.memory.get_outcomes") as mock_out, \
             patch("mindmargin.analytics.memory.get_pipeline_history") as mock_hist:
            mock_opps.return_value = [
                {"topic": "AI Future", "opportunity_score": 85, "confidence": 70,
                 "trend_score": 80, "novelty": 60, "audience_match": 70,
                 "evergreen_score": 50, "historical_performance": 65,
                 "competition": 0.3, "seasonality": 40,
                 "scored_at": ""},
            ]
            mock_save.return_value = None
            mock_src.return_value = []
            mock_out.return_value = []
            mock_hist.return_value = [{"topic": "Past Video"}]

            forecasts = horizon.forecast_all()
            assert len(forecasts) == len(FORECAST_WINDOWS)
            for f in forecasts:
                assert f["window_days"] in FORECAST_WINDOWS
                assert 0 <= f["expected_score"] <= 100
                assert "confidence" in f
                assert "uncertainty" in f

    def test_forecast_all_no_opportunities(self):
        horizon = PredictionHorizon()
        forecasts = horizon.forecast_all([])
        assert forecasts == []

    def test_forecast_longer_window_more_uncertainty(self):
        horizon = PredictionHorizon()
        with patch("mindmargin.analytics.memory.save_forecast") as mock_save, \
             patch("mindmargin.analytics.memory.get_trend_sources") as mock_src, \
             patch("mindmargin.analytics.memory.get_outcomes") as mock_out, \
             patch("mindmargin.analytics.memory.get_pipeline_history") as mock_hist:
            mock_save.return_value = None
            mock_src.return_value = []
            mock_out.return_value = []
            mock_hist.return_value = []

            opp = {"topic": "Test", "opportunity_score": 80, "confidence": 70,
                   "trend_score": 70, "novelty": 50, "audience_match": 60,
                   "evergreen_score": 50, "historical_performance": 55,
                   "competition": 0.4, "seasonality": 30, "scored_at": ""}

            fc1 = horizon._forecast_single("Test", 1, 80, 70, 70, 55, 30, 50, 0.4)
            fc30 = horizon._forecast_single("Test", 30, 80, 70, 70, 55, 30, 50, 0.4)

            assert fc30["uncertainty"] >= fc1["uncertainty"]

    def test_trend_momentum_flat(self):
        horizon = PredictionHorizon()
        with patch("mindmargin.analytics.memory.get_trend_sources") as mock_src:
            mock_src.return_value = []
            momentum = horizon._compute_trend_momentum("Any Topic")
            assert momentum == 0.0

    def test_trend_momentum_positive(self):
        horizon = PredictionHorizon()
        with patch("mindmargin.analytics.memory.get_trend_sources") as mock_src:
            mock_src.return_value = [
                {"topic": "Rising Topic", "trend_score": 40,
                 "collected_at": "2025-01-01 00:00:00"},
                {"topic": "Rising Topic", "trend_score": 80,
                 "collected_at": "2025-01-08 00:00:00"},
            ]
            momentum = horizon._compute_trend_momentum("Rising Topic")
            assert momentum > 0


class TestForecastAll:
    def test_convenience(self):
        with patch.object(PredictionHorizon, "forecast_all") as mock_fc:
            mock_fc.return_value = [{"topic": "T", "window_days": 7}]
            result = forecast_all()
            assert len(result) == 1
