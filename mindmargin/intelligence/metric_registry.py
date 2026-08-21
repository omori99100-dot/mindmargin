"""Small versioned registry for metrics already emitted by MindMargin."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class MetricDefinition:
    name: str
    unit: str
    aggregation: str
    supported_source: tuple[str, ...]
    timestamp_semantics: str
    freshness_policy_seconds: Optional[int]
    description: str
    registry_version: str = "c1-1"


class MetricRegistry:
    def __init__(self, definitions: Optional[list[MetricDefinition]] = None, version: str = "c1-1"):
        self.version = version
        self._definitions = {item.name: item for item in (definitions or DEFAULT_METRICS)}

    def get(self, name: str) -> Optional[MetricDefinition]:
        return self._definitions.get(name)

    def require(self, name: str) -> MetricDefinition:
        definition = self.get(name)
        if definition is None:
            raise ValueError(f"Unsupported metric: {name}")
        return definition

    def all(self) -> list[MetricDefinition]:
        return list(self._definitions.values())


DEFAULT_METRICS = [
    MetricDefinition("impressions", "count", "count", ("youtube_metric", "ab_result", "sqlite_metric"), "window_end", 86400, "Video impressions."),
    MetricDefinition("views", "count", "count", ("youtube_metric", "sqlite_metric"), "window_end", 86400, "Video views."),
    MetricDefinition("ctr", "percent", "mean", ("youtube_metric", "ab_result", "sqlite_metric"), "window_end", 86400, "Click-through rate."),
    MetricDefinition("watch_time_s", "seconds", "sum", ("youtube_metric", "ab_result", "sqlite_metric"), "window_end", 86400, "Watch time in seconds."),
    MetricDefinition("pipeline_duration_s", "seconds", "point", ("phase_b_event", "sqlite_metric"), "observed_at", 3600, "Observed pipeline duration."),
    MetricDefinition("lifecycle_status", "categorical", "categorical", ("phase_b_event",), "occurred_at", 3600, "Pipeline lifecycle state."),
]


__all__ = ["MetricDefinition", "MetricRegistry", "DEFAULT_METRICS"]
