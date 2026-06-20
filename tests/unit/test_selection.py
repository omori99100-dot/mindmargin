"""Unit tests for analytics.selection — classification, scoring, reinforcement, suppression."""

import pytest
from mindmargin.analytics.selection import (
    is_phase2_active, normalize_ctr, compute_score, map_score_to_label,
    _normalize_topic, _decay_score,
)


class TestIsPhase2Active:
    def test_impressions_sufficient(self):
        assert is_phase2_active(100) is True
        assert is_phase2_active(500) is True

    def test_impressions_insufficient(self):
        assert is_phase2_active(0) is False
        assert is_phase2_active(50) is False

    def test_views_fallback_activates_phase2(self):
        assert is_phase2_active(0, views=30) is True
        assert is_phase2_active(0, views=100) is True

    def test_views_fallback_insufficient(self):
        assert is_phase2_active(0, views=0) is False
        assert is_phase2_active(0, views=29) is False

    def test_impressions_takes_priority(self):
        assert is_phase2_active(0, views=50) is True
        assert is_phase2_active(200, views=0) is True


class TestNormalizeCtr:
    def test_ratio_input(self):
        assert normalize_ctr(0.05) == 0.05
        assert normalize_ctr(0.5) == 0.5

    def test_percentage_input(self):
        assert normalize_ctr(5.0) == 0.05
        assert normalize_ctr(50.0) == 0.5
        assert normalize_ctr(100.0) == 1.0

    def test_edge_cases(self):
        assert normalize_ctr(0.0) == 0.0
        assert normalize_ctr(1.0) == 1.0  # ambiguous, treated as ratio
        assert normalize_ctr(1.5) == 0.015  # > 1, treated as percentage


class TestComputeScore:
    def test_perfect_score(self):
        score = compute_score(1.0, 1.0, 100.0)
        assert score == pytest.approx(1.0, abs=0.01)

    def test_zero_score(self):
        score = compute_score(0.0, 0.0, 0.0)
        assert score == 0.0

    def test_velocity_capped(self):
        score = compute_score(0.5, 0.5, 50.0)
        capped = compute_score(0.5, 0.5, 10.0)
        assert score == capped  # both cap at 1.0

    def test_mid_range(self):
        score = compute_score(0.05, 0.5, 5.0)
        assert 0.2 < score < 0.6

    def test_weight_distribution(self):
        score = compute_score(0.0, 1.0, 0.0)
        assert score == pytest.approx(0.40, abs=0.01)
        score = compute_score(1.0, 0.0, 0.0)
        assert score == pytest.approx(0.45, abs=0.01)
        score = compute_score(0.0, 0.0, 10.0)
        assert score == pytest.approx(0.15, abs=0.01)


class TestMapScoreToLabel:
    def test_winner_candidate(self):
        assert map_score_to_label(0.35) == "winner_candidate"
        assert map_score_to_label(0.50) == "winner_candidate"
        assert map_score_to_label(1.0) == "winner_candidate"

    def test_keep_testing(self):
        assert map_score_to_label(0.20) == "keep_testing"
        assert map_score_to_label(0.34) == "keep_testing"
        assert map_score_to_label(0.25) == "keep_testing"

    def test_stable_equivalent(self):
        assert map_score_to_label(0.10) == "stable_equivalent"
        assert map_score_to_label(0.19) == "stable_equivalent"
        assert map_score_to_label(0.15) == "stable_equivalent"

    def test_weak_signal(self):
        assert map_score_to_label(0.0) == "weak_signal"
        assert map_score_to_label(0.09) == "weak_signal"
        assert map_score_to_label(0.05) == "weak_signal"


class TestNormalizeTopic:
    def test_exact_match(self):
        assert _normalize_topic("ftx") == "ftx"
        assert _normalize_topic("enron") == "enron"

    def test_alias_resolution(self):
        assert _normalize_topic("the collapse of silicon valley bank") == "silicon valley bank"
        assert _normalize_topic("inside the 2022 bitcoin crash") == "ftx"
        assert _normalize_topic("the untold story of uber's toxic culture") == "uber"

    def test_case_insensitive(self):
        assert _normalize_topic("FTX") == "ftx"
        assert _normalize_topic("Enron") == "enron"

    def test_partial_match(self):
        assert _normalize_topic("the fall of ftx") == "ftx"
        assert _normalize_topic("enron scandal explained") == "enron"

    def test_unknown_topic(self):
        assert _normalize_topic("quantum_computing") == "quantum_computing"


class TestDecayScore:
    def test_initial_decay(self):
        assert _decay_score({"suppression_count": 0}, 0.7) == 1.0

    def test_multiplicative_decay(self):
        d1 = _decay_score({"suppression_count": 1}, 0.7)
        d2 = _decay_score({"suppression_count": 2}, 0.7)
        d3 = _decay_score({"suppression_count": 3}, 0.7)
        assert d1 > d2 > d3 > 0

    def test_never_reaches_zero(self):
        d = _decay_score({"suppression_count": 100}, 0.7)
        assert d > 0.0  # never reaches EXACTLY zero

    def test_no_suppression(self):
        assert _decay_score({"suppression_count": 0}, 0.5) == 1.0

    def test_custom_base(self):
        assert _decay_score({"suppression_count": 1}, 0.5) == 0.5
        assert _decay_score({"suppression_count": 2}, 0.5) == 0.25


class TestClassifyVideoIntegration:
    """Integration-light tests — uses mocked YouTube API."""

    def test_classify_with_sufficient_signal(self, mock_youtube_stats):
        from mindmargin.analytics.selection import classify_video
        result = classify_video("p1", "vid_001", "Enron", video_duration_s=600)
        assert "classification" in result
        assert result["classification"] != "insufficient_signal"

    def test_classify_insufficient_signal(self, monkeypatch):
        """When views=0 and impressions=0, should remain cold."""
        def _empty_stats(video_id):
            return {"status": "completed", "video_id": video_id, "views": 0,
                    "likes": 0, "comments": 0, "impressions": 0}
        import mindmargin.integrations.youtube as yt_mod
        monkeypatch.setattr(yt_mod, "get_video_stats", _empty_stats)
        from mindmargin.analytics.selection import classify_video
        result = classify_video("p2", "vid_no_data", "Unknown", video_duration_s=600)
        assert result["classification"] == "insufficient_signal"

    def test_recalculate_all(self, mock_youtube_stats):
        from mindmargin.analytics.selection import recalculate_all_classifications
        result = recalculate_all_classifications()
        assert result["status"] in ("completed", "skipped")
