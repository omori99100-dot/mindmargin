import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Optional

from mindmargin.core.hardening import utcnow

logger = logging.getLogger(__name__)


class HealthState(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    FAILURE = "failure"


@dataclass
class HealthCheckResult:
    name: str
    state: HealthState
    message: str = ""
    last_check: str = ""
    response_time_s: float = 0.0
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "state": self.state.value,
            "message": self.message,
            "last_check": self.last_check,
            "response_time_s": self.response_time_s,
            "details": self.details,
        }


@dataclass
class HealthReport:
    state: HealthState = HealthState.HEALTHY
    checks: list[HealthCheckResult] = field(default_factory=list)
    timestamp: str = ""
    summary: str = ""

    def to_dict(self) -> dict:
        return {
            "state": self.state.value,
            "checks": [c.to_dict() for c in self.checks],
            "timestamp": self.timestamp,
            "summary": self.summary,
        }


class HealthMonitor:
    def __init__(self):
        self._checks: dict[str, Callable[[], HealthCheckResult]] = {}
        self._results: dict[str, HealthCheckResult] = {}
        self._lock = threading.RLock()
        self._running = False
        self._worker: Optional[threading.Thread] = None
        self._interval_s: float = 60.0

    def register(self, name: str, check_fn: Callable[[], HealthCheckResult]):
        with self._lock:
            self._checks[name] = check_fn

    def unregister(self, name: str):
        with self._lock:
            self._checks.pop(name, None)
            self._results.pop(name, None)

    def run_check(self, name: str) -> Optional[HealthCheckResult]:
        with self._lock:
            fn = self._checks.get(name)
        if not fn:
            return None
        start = time.time()
        try:
            result = fn()
            result.response_time_s = time.time() - start
            result.last_check = utcnow()
        except Exception as e:
            result = HealthCheckResult(
                name=name,
                state=HealthState.FAILURE,
                message=str(e),
                last_check=utcnow(),
                response_time_s=time.time() - start,
            )
        with self._lock:
            self._results[name] = result
        return result

    def run_all(self) -> HealthReport:
        results = []
        names = list(self._checks.keys())
        for name in names:
            result = self.run_check(name)
            if result:
                results.append(result)
        return self._aggregate(results)

    def get_result(self, name: str) -> Optional[HealthCheckResult]:
        with self._lock:
            return self._results.get(name)

    def get_report(self) -> HealthReport:
        with self._lock:
            results = list(self._results.values())
        return self._aggregate(results)

    def _aggregate(self, results: list[HealthCheckResult]) -> HealthReport:
        if not results:
            return HealthReport(state=HealthState.HEALTHY, timestamp=utcnow(), summary="No checks registered")
        states = [r.state for r in results]
        if all(s == HealthState.HEALTHY for s in states):
            overall = HealthState.HEALTHY
            summary = "All checks passed"
        elif any(s == HealthState.FAILURE for s in states):
            overall = HealthState.FAILURE
            failed = [r.name for r in results if r.state == HealthState.FAILURE]
            summary = f"Failed checks: {', '.join(failed)}"
        else:
            overall = HealthState.DEGRADED
            degraded = [r.name for r in results if r.state == HealthState.DEGRADED]
            summary = f"Degraded checks: {', '.join(degraded)}"
        return HealthReport(
            state=overall,
            checks=results,
            timestamp=utcnow(),
            summary=summary,
        )

    def start_periodic(self, interval_s: float = 60.0):
        self._interval_s = interval_s
        self._running = True
        self._worker = threading.Thread(target=self._periodic_loop, daemon=True)
        self._worker.start()
        logger.info("Health monitor started (interval=%ds)", interval_s)

    def stop_periodic(self):
        self._running = False
        if self._worker and self._worker.is_alive():
            self._worker.join(timeout=5)

    def _periodic_loop(self):
        while self._running:
            self.run_all()
            time.sleep(self._interval_s)

    @property
    def registered_checks(self) -> list[str]:
        with self._lock:
            return list(self._checks.keys())
