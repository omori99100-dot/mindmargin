"""Content Intelligence Engine — autonomous decision layer for YouTube growth."""

from .c1 import EvidenceBuilder, EvidenceValidator, ObservationCollector, assess_freshness
from .contracts import EvidenceRecord, ObservationRecord
from .metric_registry import MetricDefinition, MetricRegistry

__all__ = [
    "EvidenceBuilder",
    "EvidenceValidator",
    "ObservationCollector",
    "ObservationRecord",
    "EvidenceRecord",
    "MetricDefinition",
    "MetricRegistry",
    "assess_freshness",
]
