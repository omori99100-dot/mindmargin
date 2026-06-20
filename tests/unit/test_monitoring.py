"""Unit tests for analytics.monitoring — observability layer."""

import pytest
from datetime import datetime, timedelta
from mindmargin.analytics.monitoring import (
    record_event, get_metrics, record_runtime, get_runtime_stats,
    get_system_health, generate_daily_health_report,
    generate_weekly_system_report, check_alerts, ALERT_THRESHOLDS,
)


class TestMetricsStore:
    def test_record_and_retrieve(self):
        record_event("test_cat", "test_event", 1)
        items = get_metrics("test_cat")
        assert len(items) >= 1
        assert items[0]["category"] == "test_cat"
        assert items[0]["label"] == "test_event"

    def test_record_with_metadata(self):
        record_event("upload", "upload_success", 1, {"views": 500, "video_id": "v1"})
        items = get_metrics("upload")
        uploads = [i for i in items if i["label"] == "upload_success"]
        assert len(uploads) >= 1
        assert uploads[0]["metadata"].get("views") == 500

    def test_get_metrics_since_filter(self):
        old = datetime.utcnow() - timedelta(days=365)
        items = get_metrics(since=old)
        assert isinstance(items, list)

    def test_get_metrics_limit(self):
        items = get_metrics(limit=5)
        assert len(items) <= 5


class TestRuntimeTracking:
    def test_record_and_stats(self):
        record_runtime("pipe_test_1", 120.5)
        record_runtime("pipe_test_2", 240.0)
        stats = get_runtime_stats()
        assert stats["count"] >= 2
        assert stats["avg_s"] > 0
        assert stats["min_s"] <= stats["max_s"]


class TestSystemHealth:
    def test_health_returns_defaults(self):
        health = get_system_health()
        assert hasattr(health, "pipeline_status")
        assert hasattr(health, "total_uploads")
        assert hasattr(health, "summary")

    def test_health_status_is_valid(self):
        health = get_system_health()
        assert health.pipeline_status in ("healthy", "stable_with_errors", "degraded", "unknown")


class TestReports:
    def test_daily_report_structure(self):
        report = generate_daily_health_report()
        assert report["report_type"] == "daily"
        assert "system_status" in report
        assert "uploads" in report
        assert "failures" in report

    def test_weekly_report_structure(self):
        report = generate_weekly_system_report()
        assert report["report_type"] == "weekly"
        assert "uploads" in report
        assert "failures" in report
        assert "evolution" in report


class TestAlerts:
    def test_check_alerts_returns_list(self):
        alerts = check_alerts()
        assert isinstance(alerts, list)

    def test_alert_thresholds_present(self):
        assert "max_failures_per_hour" in ALERT_THRESHOLDS
        assert "max_retries_per_hour" in ALERT_THRESHOLDS
        assert "min_uploads_per_week" in ALERT_THRESHOLDS
