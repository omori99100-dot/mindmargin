"""Unit tests for analytics.patterns — performance pattern analysis."""

import pytest
from mindmargin.analytics.patterns import (
    analyze_retention_patterns, analyze_hook_performance,
    analyze_pacing_patterns, analyze_topic_performance,
    full_pattern_analysis, generate_script_guidance,
    compute_weekly_trends, compute_drift, generate_drift_report,
    _compute_metric_averages, DRIFT_THRESHOLD_PCT, MIN_CONFIDENCE_SAMPLES,
)


def test_analyze_retention_patterns_insufficient_data():
    result = analyze_retention_patterns()
    assert result["status"] in ("completed", "insufficient_data")


def test_analyze_hook_performance_insufficient_data():
    result = analyze_hook_performance()
    assert result["status"] in ("completed", "insufficient_data")


def test_analyze_pacing_patterns_insufficient_data():
    result = analyze_pacing_patterns()
    assert result["status"] in ("completed", "insufficient_data")


def test_analyze_topic_performance_insufficient_data():
    result = analyze_topic_performance()
    assert result["status"] in ("completed", "insufficient_data")


def test_full_pattern_analysis():
    result = full_pattern_analysis()
    assert result["status"] == "completed"
    assert "retention" in result
    assert "hooks" in result
    assert "pacing" in result
    assert "topics" in result
    assert "best_practices_count" in result
    assert "analyzed_at" in result


def test_generate_script_guidance():
    guidance = generate_script_guidance()
    assert "recommended_hook_archetype" in guidance
    assert "archetype_rankings" in guidance
    assert "pacing_insights" in guidance
    assert "retention_benchmark_s" in guidance


def test_compute_weekly_trends_insufficient():
    result = compute_weekly_trends()
    assert result["status"] in ("completed", "insufficient_data")


def test_compute_drift_insufficient():
    result = compute_drift()
    assert result["status"] in ("completed", "insufficient_data")


def test_generate_drift_report():
    report = generate_drift_report()
    assert "trends" in report
    assert "drift" in report
    assert "historical_drifts" in report


def test_compute_metric_averages():
    weeks = _compute_metric_averages()
    for w in weeks:
        assert "estimated_ctr_pct" in w
        assert "engagement_per_view" in w
        assert "retention_rate_pct" in w


def test_drift_constants():
    assert DRIFT_THRESHOLD_PCT == 5.0
    assert MIN_CONFIDENCE_SAMPLES == 3
