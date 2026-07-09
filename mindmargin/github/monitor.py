import json
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from mindmargin.config import settings

logger = logging.getLogger(__name__)


@dataclass
class MetricEntry:
    name: str = ""
    value: float = 0
    unit: str = ""
    labels: dict = field(default_factory=dict)
    timestamp: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "value": self.value,
            "unit": self.unit,
            "labels": self.labels,
            "timestamp": self.timestamp,
        }


@dataclass
class GitHubMonitorReport:
    timestamp: str = ""
    workflow_metrics: dict = field(default_factory=dict)
    job_metrics: dict = field(default_factory=dict)
    runner_metrics: dict = field(default_factory=dict)
    artifact_metrics: dict = field(default_factory=dict)
    cost_metrics: dict = field(default_factory=dict)
    health_score: float = 100.0
    alerts: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "workflow_metrics": self.workflow_metrics,
            "job_metrics": self.job_metrics,
            "runner_metrics": self.runner_metrics,
            "artifact_metrics": self.artifact_metrics,
            "cost_metrics": self.cost_metrics,
            "health_score": round(self.health_score, 1),
            "alerts": self.alerts,
        }


class GitHubMonitor:
    def __init__(self, persist_dir: str = ""):
        root = Path(persist_dir or settings.storage.temp_root)
        self._mon_dir = root / "github" / "monitor"
        self._mon_dir.mkdir(parents=True, exist_ok=True)
        self._metrics: list[MetricEntry] = []
        self._alerts: list[dict] = []
        self._lock = threading.RLock()
        self._counters: dict[str, float] = {}
        self._timers: dict[str, float] = {}
        self._load()

    def _load(self):
        metrics_path = self._mon_dir / "metrics.json"
        if metrics_path.exists():
            try:
                data = json.loads(metrics_path.read_text(encoding="utf-8"))
                self._metrics = [MetricEntry(**m) for m in data]
            except Exception:
                pass
        alerts_path = self._mon_dir / "alerts.json"
        if alerts_path.exists():
            try:
                self._alerts = json.loads(alerts_path.read_text(encoding="utf-8"))
            except Exception:
                pass

    def _save(self):
        metrics_path = self._mon_dir / "metrics.json"
        metrics_path.write_text(
            json.dumps([m.to_dict() for m in self._metrics[-5000:]], indent=2),
            encoding="utf-8",
        )
        alerts_path = self._mon_dir / "alerts.json"
        alerts_path.write_text(
            json.dumps(self._alerts[-500:], indent=2), encoding="utf-8"
        )

    def record_metric(self, name: str, value: float, unit: str = "",
                      labels: dict = None):
        entry = MetricEntry(
            name=name, value=value, unit=unit,
            labels=labels or {},
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        with self._lock:
            self._metrics.append(entry)
            self._save()

    def increment(self, name: str, labels: dict = None):
        key = f"{name}:{json.dumps(labels or {}, sort_keys=True)}"
        with self._lock:
            self._counters[key] = self._counters.get(key, 0) + 1
        self.record_metric(name, self._counters[key], "count", labels)

    def gauge(self, name: str, value: float, labels: dict = None):
        self.record_metric(name, value, "gauge", labels)

    def histogram(self, name: str, value: float, labels: dict = None):
        self.record_metric(name, value, "histogram", labels)

    def start_timer(self, name: str):
        self._timers[name] = time.monotonic()

    def stop_timer(self, name: str, labels: dict = None) -> float:
        start = self._timers.pop(name, None)
        if start is not None:
            duration = time.monotonic() - start
            self.record_metric(name, round(duration, 3), "seconds", labels)
            return duration
        return 0.0

    def alert(self, severity: str, message: str, source: str = "",
              metadata: dict = None):
        entry = {
            "severity": severity,
            "message": message,
            "source": source,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "metadata": metadata or {},
        }
        with self._lock:
            self._alerts.append(entry)
            self._save()
        logger.log(
            logging.CRITICAL if severity == "critical" else logging.WARNING,
            "[%s] %s: %s", severity.upper(), source, message,
        )

    def record_workflow_started(self, workflow_name: str):
        self.increment("workflows.started", {"workflow": workflow_name})

    def record_workflow_completed(self, workflow_name: str, duration_s: float):
        self.increment("workflows.completed", {"workflow": workflow_name})
        self.histogram("workflows.duration", duration_s, {"workflow": workflow_name})

    def record_workflow_failed(self, workflow_name: str, error: str):
        self.increment("workflows.failed", {"workflow": workflow_name})
        self.alert("warning", f"Workflow failed: {workflow_name} - {error}",
                   source="github_monitor")

    def record_job_started(self, workflow_name: str, job_name: str):
        self.increment("jobs.started", {"workflow": workflow_name, "job": job_name})

    def record_job_completed(self, workflow_name: str, job_name: str, duration_s: float):
        self.increment("jobs.completed", {"workflow": workflow_name, "job": job_name})
        self.histogram("jobs.duration", duration_s, {"workflow": workflow_name, "job": job_name})

    def record_job_failed(self, workflow_name: str, job_name: str, error: str):
        self.increment("jobs.failed", {"workflow": workflow_name, "job": job_name})

    def record_retry(self, workflow_name: str, job_name: str):
        self.increment("retries.total", {"workflow": workflow_name, "job": job_name})

    def record_artifact_stored(self, artifact_type: str, size_bytes: int):
        self.increment("artifacts.stored", {"type": artifact_type})
        self.histogram("artifacts.size", size_bytes, {"type": artifact_type})

    def record_dispatch(self, workflow_name: str, trigger: str):
        self.increment("dispatches.total", {"workflow": workflow_name, "trigger": trigger})

    def record_publish(self, video_id: str, duration_s: float):
        self.increment("publishes.total")
        self.histogram("publishes.duration", duration_s)

    def record_queue_time(self, workflow_name: str, queue_s: float):
        self.histogram("queue.time", queue_s, {"workflow": workflow_name})

    def record_runner_availability(self, available: int, total: int):
        self.gauge("runners.available", available)
        self.gauge("runners.total", total)

    def record_execution_cost(self, cost_usd: float, workflow_name: str = ""):
        self.histogram("cost.execution", cost_usd, {"workflow": workflow_name})

    def get_metrics(self, name: str = "", limit: int = 200) -> list[dict]:
        with self._lock:
            metrics = self._metrics
        if name:
            metrics = [m for m in metrics if m.name == name]
        return [m.to_dict() for m in metrics[-limit:]]

    def get_alerts(self, severity: str = "", limit: int = 50) -> list[dict]:
        with self._lock:
            alerts = self._alerts
        if severity:
            alerts = [a for a in alerts if a["severity"] == severity]
        return alerts[-limit:]

    def get_health_report(self) -> dict:
        with self._lock:
            recent_alerts = [a for a in self._alerts[-50:]
                            if a["severity"] in ("critical", "error")]
            error_count = len(recent_alerts)

        health_score = max(0, 100 - (error_count * 5))
        status = "healthy" if health_score >= 80 else "degraded" if health_score >= 50 else "critical"

        return {
            "status": status,
            "health_score": health_score,
            "total_metrics": len(self._metrics),
            "total_alerts": len(self._alerts),
            "recent_critical_alerts": error_count,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def get_summary(self) -> dict:
        with self._lock:
            counters = dict(self._counters)
        return {
            "counters": counters,
            "total_metrics": len(self._metrics),
            "total_alerts": len(self._alerts),
            "health": self.get_health_report(),
        }

    def clear(self):
        with self._lock:
            self._metrics.clear()
            self._alerts.clear()
            self._counters.clear()
            self._timers.clear()
            self._save()
