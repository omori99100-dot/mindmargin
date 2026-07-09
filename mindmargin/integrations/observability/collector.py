import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from mindmargin.config import settings

logger = logging.getLogger(__name__)


@dataclass
class MetricPoint:
    name: str
    value: float
    labels: dict = field(default_factory=dict)
    timestamp: str = ""
    metric_type: str = "gauge"

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "value": self.value,
            "labels": self.labels,
            "timestamp": self.timestamp,
            "metric_type": self.metric_type,
        }


@dataclass
class TraceSpan:
    trace_id: str = ""
    span_id: str = ""
    name: str = ""
    start_time: str = ""
    end_time: str = ""
    duration_ms: float = 0
    status: str = "ok"
    attributes: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "name": self.name,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_ms": round(self.duration_ms, 2),
            "status": self.status,
            "attributes": self.attributes,
        }


class MetricsCollector:
    def __init__(self, persist_dir: str = ""):
        root = Path(persist_dir or settings.storage.temp_root)
        self._obs_dir = root / "integrations" / "observability"
        self._obs_dir.mkdir(parents=True, exist_ok=True)
        self._metrics: list[MetricPoint] = []
        self._traces: list[TraceSpan] = []
        self._logs: list[dict] = []

    def record_metric(self, name: str, value: float, labels: dict = None,
                      metric_type: str = "gauge"):
        point = MetricPoint(
            name=name,
            value=value,
            labels=labels or {},
            timestamp=datetime.now(timezone.utc).isoformat(),
            metric_type=metric_type,
        )
        self._metrics.append(point)
        if len(self._metrics) > 10000:
            self._metrics = self._metrics[-5000:]

    def increment(self, name: str, labels: dict = None):
        existing = [m for m in self._metrics if m.name == name and m.labels == (labels or {})]
        if existing:
            existing[-1].value += 1
        else:
            self.record_metric(name, 1, labels, "counter")

    def gauge(self, name: str, value: float, labels: dict = None):
        self.record_metric(name, value, labels, "gauge")

    def histogram(self, name: str, value: float, labels: dict = None):
        self.record_metric(name, value, labels, "histogram")

    def start_trace(self, name: str, attributes: dict = None) -> str:
        import uuid
        trace_id = uuid.uuid4().hex[:16]
        span = TraceSpan(
            trace_id=trace_id,
            span_id=uuid.uuid4().hex[:8],
            name=name,
            start_time=datetime.now(timezone.utc).isoformat(),
            attributes=attributes or {},
        )
        self._traces.append(span)
        return trace_id

    def end_trace(self, trace_id: str, status: str = "ok"):
        for span in self._traces:
            if span.trace_id == trace_id and not span.end_time:
                span.end_time = datetime.now(timezone.utc).isoformat()
                start = datetime.fromisoformat(span.start_time)
                end = datetime.fromisoformat(span.end_time)
                span.duration_ms = (end - start).total_seconds() * 1000
                span.status = status
                break

    def log_event(self, level: str, message: str, source: str = "", attributes: dict = None):
        entry = {
            "level": level,
            "message": message,
            "source": source,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "attributes": attributes or {},
        }
        self._logs.append(entry)
        if len(self._logs) > 5000:
            self._logs = self._logs[-2500:]

    def info(self, message: str, source: str = "", **kwargs):
        self.log_event("info", message, source, kwargs)

    def warning(self, message: str, source: str = "", **kwargs):
        self.log_event("warning", message, source, kwargs)

    def error(self, message: str, source: str = "", **kwargs):
        self.log_event("error", message, source, kwargs)

    def get_metrics(self, name: str = "", limit: int = 100) -> list[dict]:
        results = self._metrics
        if name:
            results = [m for m in results if m.name == name]
        return [m.to_dict() for m in results[-limit:]]

    def get_traces(self, limit: int = 100) -> list[dict]:
        return [t.to_dict() for t in self._traces[-limit:]]

    def get_logs(self, level: str = "", limit: int = 100) -> list[dict]:
        results = self._logs
        if level:
            results = [l for l in results if l["level"] == level]
        return results[-limit:]

    def get_health_report(self) -> dict:
        recent_errors = [l for l in self._logs[-100:] if l["level"] == "error"]
        recent_traces = self._traces[-20:]
        avg_duration = 0
        if recent_traces:
            durations = [t.duration_ms for t in recent_traces if t.duration_ms > 0]
            avg_duration = sum(durations) / len(durations) if durations else 0
        return {
            "total_metrics": len(self._metrics),
            "total_traces": len(self._traces),
            "total_logs": len(self._logs),
            "recent_errors": len(recent_errors),
            "avg_trace_duration_ms": round(avg_duration, 2),
            "status": "healthy" if len(recent_errors) < 10 else "degraded",
        }

    def export_prometheus(self) -> str:
        lines = []
        for m in self._metrics[-200:]:
            labels = ",".join(f'{k}="{v}"' for k, v in m.labels.items())
            label_str = f"{{{labels}}}" if labels else ""
            lines.append(f"{m.name}{label_str} {m.value}")
        return "\n".join(lines)

    def export_json(self) -> dict:
        return {
            "metrics": [m.to_dict() for m in self._metrics[-100:]],
            "traces": [t.to_dict() for t in self._traces[-50:]],
            "logs": self._logs[-100:],
        }

    def clear(self):
        self._metrics.clear()
        self._traces.clear()
        self._logs.clear()
