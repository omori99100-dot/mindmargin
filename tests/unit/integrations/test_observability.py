"""Unit tests for mindmargin.integrations.observability.collector."""

import pytest


@pytest.fixture
def collector(tmp_path):
    from mindmargin.integrations.observability.collector import MetricsCollector
    return MetricsCollector(persist_dir=str(tmp_path / "integrations"))


class TestMetricPoint:
    def test_to_dict(self):
        from mindmargin.integrations.observability.collector import MetricPoint
        m = MetricPoint(name="cpu", value=75.5, labels={"host": "a"}, metric_type="gauge")
        d = m.to_dict()
        assert d["name"] == "cpu"
        assert d["value"] == 75.5
        assert d["labels"] == {"host": "a"}


class TestTraceSpan:
    def test_to_dict(self):
        from mindmargin.integrations.observability.collector import TraceSpan
        t = TraceSpan(trace_id="abc", span_id="def", name="upload", duration_ms=123.45)
        d = t.to_dict()
        assert d["trace_id"] == "abc"
        assert d["duration_ms"] == 123.45


class TestMetricsCollector:
    def test_record_metric(self, collector):
        collector.record_metric("requests", 42)
        metrics = collector.get_metrics("requests")
        assert len(metrics) == 1
        assert metrics[0]["value"] == 42

    def test_increment(self, collector):
        collector.increment("hits")
        collector.increment("hits")
        metrics = collector.get_metrics("hits")
        assert len(metrics) == 1
        assert metrics[0]["value"] == 2

    def test_gauge(self, collector):
        collector.gauge("memory", 1024.0)
        metrics = collector.get_metrics("memory")
        assert metrics[0]["metric_type"] == "gauge"

    def test_histogram(self, collector):
        collector.histogram("latency", 50.0)
        metrics = collector.get_metrics("latency")
        assert metrics[0]["metric_type"] == "histogram"

    def test_start_and_end_trace(self, collector):
        tid = collector.start_trace("upload")
        assert len(tid) == 16
        collector.end_trace(tid, "ok")
        traces = collector.get_traces()
        assert len(traces) == 1
        assert traces[0]["status"] == "ok"
        assert traces[0]["duration_ms"] >= 0

    def test_end_trace_not_found(self, collector):
        collector.end_trace("nonexistent")  # no error

    def test_log_event(self, collector):
        collector.log_event("info", "started", source="test")
        logs = collector.get_logs()
        assert len(logs) == 1
        assert logs[0]["level"] == "info"

    def test_info_warning_error(self, collector):
        collector.info("msg1")
        collector.warning("msg2")
        collector.error("msg3")
        assert len(collector.get_logs("info")) == 1
        assert len(collector.get_logs("warning")) == 1
        assert len(collector.get_logs("error")) == 1

    def test_get_health_report(self, tmp_path):
        from mindmargin.integrations.observability.collector import MetricsCollector
        c = MetricsCollector(persist_dir=str(tmp_path / "obs"))
        for _ in range(15):
            c.error("err")
        report = c.get_health_report()
        assert report["recent_errors"] == 15
        assert report["status"] == "degraded"

    def test_get_health_report_healthy(self, collector):
        report = collector.get_health_report()
        assert report["status"] == "healthy"

    def test_export_prometheus(self, collector):
        collector.gauge("test_metric", 99.0)
        output = collector.export_prometheus()
        assert "test_metric 99.0" in output

    def test_export_json(self, collector):
        collector.record_metric("m", 1.0)
        data = collector.export_json()
        assert "metrics" in data
        assert "traces" in data
        assert "logs" in data

    def test_clear(self, collector):
        collector.record_metric("m", 1.0)
        collector.start_trace("t")
        collector.info("l")
        collector.clear()
        assert collector.get_metrics() == []
        assert collector.get_traces() == []
        assert collector.get_logs() == []

    def test_metrics_rollover(self, collector):
        for i in range(11000):
            collector.record_metric("m", float(i))
        assert len(collector._metrics) <= 10000

    def test_logs_rollover(self, collector):
        for i in range(6000):
            collector.info(f"msg{i}")
        assert len(collector._logs) <= 5000

    def test_traces_with_attributes(self, collector):
        tid = collector.start_trace("op", attributes={"key": "val"})
        collector.end_trace(tid)
        traces = collector.get_traces()
        assert traces[0]["attributes"] == {"key": "val"}

    def test_metric_labels(self, collector):
        collector.gauge("cpu", 50.0, labels={"core": "0"})
        m = collector.get_metrics("cpu")[0]
        assert m["labels"] == {"core": "0"}
