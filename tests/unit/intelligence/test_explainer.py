"""Tests for Explainable Decisions (intelligence/explainer.py)."""

from mindmargin.intelligence.explainer import (
    DecisionExplainer, explain_decision, format_explanation_markdown,
)


class TestDecisionExplainer:
    def test_explain_returns_structure(self):
        explainer = DecisionExplainer()
        selected = {
            "topic": "AI Revolution",
            "opportunity_score": 91,
            "confidence": 74,
            "trend_score": 85,
            "novelty": 70,
            "audience_match": 80,
            "evergreen_score": 60,
            "competition": 0.2,
            "historical_performance": 75,
            "seasonality": 50,
        }
        alternatives = [
            {"topic": "Old Topic", "opportunity_score": 45, "confidence": 30,
             "trend_score": 30, "novelty": 20, "audience_match": 40,
             "evergreen_score": 50, "competition": 0.6, "historical_performance": 35},
            {"topic": "Medium Topic", "opportunity_score": 70, "confidence": 55,
             "trend_score": 65, "novelty": 50, "audience_match": 60,
             "evergreen_score": 55, "competition": 0.4, "historical_performance": 60},
        ]

        result = explainer.explain(selected, alternatives)

        assert result["selected_topic"] == "AI Revolution"
        assert result["opportunity_score"] == 91
        assert result["confidence"] == 74
        assert len(result["positive_factors"]) > 0
        assert len(result["alternative_candidates"]) == 2

    def test_negative_factors_present(self):
        explainer = DecisionExplainer()
        selected = {
            "topic": "Risky Topic",
            "trend_score": 20, "novelty": 15,
            "audience_match": 25, "evergreen_score": 30,
            "competition": 0.8, "seasonality": 10,
        }
        neg = explainer._negative_factors(selected)
        assert len(neg) > 0

    def test_why_lost(self):
        explainer = DecisionExplainer()
        winner = {"topic": "A", "opportunity_score": 90, "confidence": 80,
                  "trend_score": 90, "audience_match": 85, "evergreen_score": 80}
        loser = {"topic": "B", "opportunity_score": 50, "confidence": 30,
                 "trend_score": 40, "audience_match": 35, "evergreen_score": 30}
        reasons = explainer._why_lost(winner, loser)
        assert len(reasons) > 0

    def test_to_markdown(self):
        explainer = DecisionExplainer()
        explanation = {
            "selected_topic": "AI Future",
            "opportunity_score": 85,
            "confidence": 70,
            "positive_factors": ["Strong trend acceleration (80/100)", "High audience similarity (75/100)"],
            "negative_factors": ["Low novelty (25/100)"],
            "alternative_candidates": [
                {"topic": "Old Topic", "opportunity_score": 40, "confidence": 25,
                 "why_lost": ["Lower Trend Score"]}
            ],
        }
        md = explainer.to_markdown(explanation)
        assert "AI Future" in md
        assert "Strong trend acceleration" in md
        assert "Old Topic" in md


class TestConvenience:
    def test_explain_decision(self):
        result = explain_decision(
            {"topic": "T", "opportunity_score": 80},
            [{"topic": "A", "opportunity_score": 50}],
        )
        assert result["selected_topic"] == "T"

    def test_format_explanation_markdown(self):
        explanation = {
            "selected_topic": "Test",
            "opportunity_score": 90,
            "confidence": 80,
            "positive_factors": ["Factor 1"],
            "negative_factors": [],
            "alternative_candidates": [],
        }
        md = format_explanation_markdown(explanation)
        assert "Test" in md
        assert "90" in md
