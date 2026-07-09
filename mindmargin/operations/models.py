import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

from mindmargin.config import settings

logger = logging.getLogger(__name__)


class OperationType(str, Enum):
    DAILY_ANALYTICS = "daily_analytics"
    DAILY_INTELLIGENCE = "daily_intelligence"
    DECISION_EXECUTOR = "decision_executor"
    FEEDBACK_CYCLE = "feedback_cycle"
    EXPERIMENT_CYCLE = "experiment_cycle"
    KNOWLEDGE_GRAPH = "knowledge_graph"
    FORECAST = "forecast"
    WEEKLY_PLAN = "weekly_plan"
    WEEKLY_REPORT = "weekly_report"
    SELECTION_PRESSURE = "selection_pressure"
    AB_ROTATION = "ab_rotation"
    DISTRIBUTION = "distribution"


class OperationStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    BLOCKED = "blocked"
    DISABLED = "disabled"


OPERATION_CRON_DEFAULTS: dict[OperationType, str] = {
    OperationType.DAILY_ANALYTICS: "0 6 * * *",
    OperationType.DAILY_INTELLIGENCE: "30 6 * * *",
    OperationType.DECISION_EXECUTOR: "0 7 * * *",
    OperationType.FEEDBACK_CYCLE: "0 */6 * * *",
    OperationType.EXPERIMENT_CYCLE: "0 8 * * *",
    OperationType.KNOWLEDGE_GRAPH: "0 9 * * *",
    OperationType.FORECAST: "0 10 * * *",
    OperationType.WEEKLY_PLAN: "0 7 * * MON",
    OperationType.WEEKLY_REPORT: "0 8 * * SUN",
    OperationType.SELECTION_PRESSURE: "0 */12 * * *",
    OperationType.AB_ROTATION: "0 */4 * * *",
    OperationType.DISTRIBUTION: "0 11 * * *",
}


OPERATION_TIMEOUT_DEFAULTS: dict[OperationType, float] = {
    OperationType.DAILY_ANALYTICS: 1200,
    OperationType.DAILY_INTELLIGENCE: 1800,
    OperationType.DECISION_EXECUTOR: 3600,
    OperationType.FEEDBACK_CYCLE: 300,
    OperationType.EXPERIMENT_CYCLE: 600,
    OperationType.KNOWLEDGE_GRAPH: 600,
    OperationType.FORECAST: 300,
    OperationType.WEEKLY_PLAN: 300,
    OperationType.WEEKLY_REPORT: 300,
    OperationType.SELECTION_PRESSURE: 600,
    OperationType.AB_ROTATION: 300,
    OperationType.DISTRIBUTION: 600,
}


@dataclass
class OperationRecord:
    operation_id: str
    operation_type: OperationType
    status: OperationStatus
    started_at: str = ""
    completed_at: str = ""
    workflow_id: str = ""
    schedule_id: str = ""
    result: dict = field(default_factory=dict)
    error: str = ""
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "operation_id": self.operation_id,
            "operation_type": self.operation_type.value if isinstance(self.operation_type, OperationType) else self.operation_type,
            "status": self.status.value if isinstance(self.status, OperationStatus) else self.status,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "workflow_id": self.workflow_id,
            "schedule_id": self.schedule_id,
            "result": self.result,
            "error": self.error,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "OperationRecord":
        return cls(
            operation_id=d["operation_id"],
            operation_type=OperationType(d["operation_type"]),
            status=OperationStatus(d["status"]),
            started_at=d.get("started_at", ""),
            completed_at=d.get("completed_at", ""),
            workflow_id=d.get("workflow_id", ""),
            schedule_id=d.get("schedule_id", ""),
            result=d.get("result", {}),
            error=d.get("error", ""),
            metadata=d.get("metadata", {}),
        )


@dataclass
class OperationReport:
    status: str
    active_operations: int
    completed_today: int
    failed_today: int
    scheduled: int
    records: list[OperationRecord]
