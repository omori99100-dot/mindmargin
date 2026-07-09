import time

import pytest

from mindmargin.core.health import HealthMonitor, HealthCheckResult, HealthState


@pytest.fixture
def monitor():
    return HealthMonitor()


class TestHealthCheckResult:
    def test_to_dict(self):
        r = HealthCheckResult(
            name="test",
            state=HealthState.HEALTHY,
            message="all good",
            last_check="2026-01-01T00:00:00",
            response_time_s=0.05,
        )
        d = r.to_dict()
        assert d["name"] == "test"
        assert d["state"] == "healthy"
        assert d["message"] == "all good"


class TestHealthMonitor:
    def test_register_check(self, monitor):
        monitor.register("disk", lambda: HealthCheckResult(name="disk", state=HealthState.HEALTHY))
        assert "disk" in monitor.registered_checks

    def test_unregister_check(self, monitor):
        monitor.register("mem", lambda: HealthCheckResult(name="mem", state=HealthState.HEALTHY))
        monitor.unregister("mem")
        assert "mem" not in monitor.registered_checks

    def test_run_check_healthy(self, monitor):
        monitor.register("db", lambda: HealthCheckResult(name="db", state=HealthState.HEALTHY))
        result = monitor.run_check("db")
        assert result.state == HealthState.HEALTHY
        assert result.response_time_s >= 0

    def test_run_check_unknown(self, monitor):
        assert monitor.run_check("unknown") is None

    def test_run_check_failure(self, monitor):
        def failing():
            raise ConnectionError("cannot connect")

        monitor.register("api", failing)
        result = monitor.run_check("api")
        assert result.state == HealthState.FAILURE
        assert "cannot connect" in result.message

    def test_get_result(self, monitor):
        monitor.register("cache", lambda: HealthCheckResult(name="cache", state=HealthState.HEALTHY))
        monitor.run_check("cache")
        result = monitor.get_result("cache")
        assert result is not None
        assert result.name == "cache"

    def test_get_result_none(self, monitor):
        assert monitor.get_result("nonexistent") is None


class TestHealthAggregation:
    def test_all_healthy(self, monitor):
        monitor.register("a", lambda: HealthCheckResult(name="a", state=HealthState.HEALTHY))
        monitor.register("b", lambda: HealthCheckResult(name="b", state=HealthState.HEALTHY))
        report = monitor.run_all()
        assert report.state == HealthState.HEALTHY
        assert "passed" in report.summary

    def test_any_failure(self, monitor):
        monitor.register("a", lambda: HealthCheckResult(name="a", state=HealthState.HEALTHY))
        monitor.register("b", lambda: HealthCheckResult(name="b", state=HealthState.FAILURE, message="down"))
        report = monitor.run_all()
        assert report.state == HealthState.FAILURE
        assert "b" in report.summary

    def test_degraded(self, monitor):
        monitor.register("a", lambda: HealthCheckResult(name="a", state=HealthState.DEGRADED))
        monitor.register("b", lambda: HealthCheckResult(name="b", state=HealthState.HEALTHY))
        report = monitor.run_all()
        assert report.state == HealthState.DEGRADED
        assert "a" in report.summary

    def test_no_checks(self, monitor):
        report = monitor.run_all()
        assert report.state == HealthState.HEALTHY
        assert "No checks" in report.summary

    def test_failure_overrides_degraded(self, monitor):
        monitor.register("a", lambda: HealthCheckResult(name="a", state=HealthState.DEGRADED))
        monitor.register("b", lambda: HealthCheckResult(name="b", state=HealthState.FAILURE))
        report = monitor.run_all()
        assert report.state == HealthState.FAILURE


class TestHealthReport:
    def test_get_report(self, monitor):
        monitor.register("x", lambda: HealthCheckResult(name="x", state=HealthState.HEALTHY))
        monitor.run_check("x")
        report = monitor.get_report()
        assert report.state == HealthState.HEALTHY
        assert len(report.checks) == 1

    def test_report_to_dict(self, monitor):
        monitor.register("y", lambda: HealthCheckResult(name="y", state=HealthState.FAILURE, message="err"))
        monitor.run_check("y")
        report = monitor.get_report()
        d = report.to_dict()
        assert d["state"] == "failure"
        assert len(d["checks"]) == 1
        assert "err" in d["checks"][0]["message"]


class TestPeriodic:
    def test_start_stop(self, monitor):
        monitor.register("p", lambda: HealthCheckResult(name="p", state=HealthState.HEALTHY))
        monitor.start_periodic(interval_s=0.1)
        time.sleep(0.25)
        monitor.stop_periodic()
        result = monitor.get_result("p")
        assert result is not None
