"""Unit tests for analytics.comparison — decision comparison engine."""

import pytest
from mindmargin.analytics.comparison import (
    normalize, phase2_decision, compare_decision, run_comparison_cycle,
)


class TestNormalize:
    def test_typical_values(self):
        c, r, v = normalize(5.0, 0.65, 10.0)
        assert 0.0 <= c <= 1.0
        assert 0.0 <= r <= 1.0
        assert 0.0 <= v <= 1.0

    def test_boundary(self):
        c, r, v = normalize(0.0, 0.0, 0.0)
        assert c == 0.0
        assert r == 0.0
        assert v == 0.0

    def test_capped_values(self):
        c, r, v = normalize(100.0, 2.0, 100.0)
        assert c <= 1.0
        assert r == 1.0
        assert v == 1.0


class TestPhase2Decision:
    def test_high_performance(self):
        d = phase2_decision(30.0, 0.85, 50.0)  # CTR 30%, retention 85%, velocity 50/hr
        assert d["phase2_label"] in ("winner_candidate", "keep_testing", "stable_equivalent")
        assert d["phase2_score"] > 0.3

    def test_low_performance(self):
        d = phase2_decision(0.5, 0.05, 0.1)
        assert d["phase2_score"] < 0.35
        assert d["phase2_score"] >= 0.0

    def test_structure(self):
        d = phase2_decision(5.0, 0.5, 5.0)
        assert "phase2_score" in d
        assert "phase2_label" in d
        assert "phase2_confidence" in d
        assert "phase2_ctr_norm" in d
        assert "phase2_retention_norm" in d
        assert "phase2_velocity_norm" in d


class TestCompareDecision:
    def test_agreement(self):
        prod = {"classification": "winner_candidate", "confidence": 0.85}
        p2 = {"phase2_label": "winner_candidate", "phase2_score": 0.82, "phase2_confidence": 0.85}
        comp = compare_decision(prod, p2)
        assert comp["agreement"] is True

    def test_disagreement(self):
        prod = {"classification": "weak_signal", "confidence": 0.3}
        p2 = {"phase2_label": "winner_candidate", "phase2_score": 0.85, "phase2_confidence": 0.9}
        comp = compare_decision(prod, p2)
        assert comp["agreement"] is False
        assert comp["score_delta"] > 0

    def test_missing_keys(self):
        prod = {"classification": "keep_testing"}
        p2 = {"phase2_label": "weak_signal", "phase2_score": 0.3, "phase2_confidence": 0.4}
        comp = compare_decision(prod, p2)
        assert comp["agreement"] is False

    def test_result_structure(self):
        prod = {"classification": "stable_equivalent", "confidence": 0.55}
        p2 = {"phase2_label": "keep_testing", "phase2_score": 0.65, "phase2_confidence": 0.7}
        comp = compare_decision(prod, p2)
        assert "agreement" in comp
        assert "production_label" in comp
        assert "phase2_label" in comp
        assert "score_delta" in comp


class TestComparisonCycle:
    def test_run_returns_report(self):
        report = run_comparison_cycle()
        assert report["status"] in ("completed", "skipped")
        assert "agreement_rate" in report
        assert "disagreement_rate" in report
        assert "total_videos" in report
        assert "false_positives" in report
        assert "false_negatives" in report
