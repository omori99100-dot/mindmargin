import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Optional

from mindmargin.core.events import publish

logger = logging.getLogger(__name__)


class WorkflowPriority(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class WorkflowTrigger(str, Enum):
    MANUAL = "manual"
    SCHEDULE = "schedule"
    EVENT = "event"
    DISPATCH = "dispatch"
    CHAIN = "chain"


@dataclass
class WorkflowStepDef:
    step_id: str
    name: str
    handler_name: str = ""
    dependencies: list[str] = field(default_factory=list)
    timeout_s: float = 600
    max_retries: int = 2
    continue_on_failure: bool = False
    condition: str = ""
    params: dict = field(default_factory=dict)
    priority: int = 0

    def to_dict(self) -> dict:
        return {
            "step_id": self.step_id,
            "name": self.name,
            "handler_name": self.handler_name,
            "dependencies": self.dependencies,
            "timeout_s": self.timeout_s,
            "max_retries": self.max_retries,
            "continue_on_failure": self.continue_on_failure,
            "condition": self.condition,
            "params": self.params,
            "priority": self.priority,
        }


@dataclass
class WorkflowDefinition:
    workflow_id: str
    name: str
    description: str = ""
    steps: list[WorkflowStepDef] = field(default_factory=list)
    priority: WorkflowPriority = WorkflowPriority.MEDIUM
    trigger: WorkflowTrigger = WorkflowTrigger.MANUAL
    cron: str = ""
    timeout_s: float = 3600
    max_concurrent: int = 1
    required_secrets: list[str] = field(default_factory=list)
    required_env: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    enabled: bool = True

    def to_dict(self) -> dict:
        return {
            "workflow_id": self.workflow_id,
            "name": self.name,
            "description": self.description,
            "steps": [s.to_dict() for s in self.steps],
            "priority": self.priority.value,
            "trigger": self.trigger.value,
            "cron": self.cron,
            "timeout_s": self.timeout_s,
            "max_concurrent": self.max_concurrent,
            "required_secrets": self.required_secrets,
            "required_env": self.required_env,
            "tags": self.tags,
            "metadata": self.metadata,
            "enabled": self.enabled,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "WorkflowDefinition":
        d = dict(d)
        d["priority"] = WorkflowPriority(d.get("priority", "medium"))
        d["trigger"] = WorkflowTrigger(d.get("trigger", "manual"))
        d["steps"] = [WorkflowStepDef(**s) for s in d.get("steps", [])]
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class WorkflowChain:
    chain_id: str
    name: str
    workflow_ids: list[str] = field(default_factory=list)
    current_index: int = 0
    state: str = "pending"
    created_at: str = ""
    completed_at: str = ""
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "chain_id": self.chain_id,
            "name": self.name,
            "workflow_ids": self.workflow_ids,
            "current_index": self.current_index,
            "state": self.state,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "WorkflowChain":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class WorkflowRegistry:
    def __init__(self):
        self._definitions: dict[str, WorkflowDefinition] = {}
        self._chains: dict[str, WorkflowChain] = {}
        self._handlers: dict[str, Callable] = {}
        self._register_defaults()

    def _register_defaults(self):
        self.register(WorkflowDefinition(
            workflow_id="daily_pipeline",
            name="Daily Content Pipeline",
            description="Full content generation pipeline from idea to publish",
            steps=[
                WorkflowStepDef("scoring", "Topic Scoring", "score_topics", priority=1),
                WorkflowStepDef("planning", "Content Planning", "plan_content",
                               dependencies=["scoring"], priority=2),
                WorkflowStepDef("generation", "Content Generation", "generate_content",
                               dependencies=["planning"], priority=3, timeout_s=1800),
                WorkflowStepDef("rendering", "Video Rendering", "render_video",
                               dependencies=["generation"], priority=4, timeout_s=2400),
                WorkflowStepDef("publishing", "Publishing", "publish_video",
                               dependencies=["rendering"], priority=5),
                WorkflowStepDef("analytics", "Analytics Collection", "collect_analytics",
                               dependencies=["publishing"], priority=6),
            ],
            priority=WorkflowPriority.HIGH,
            trigger=WorkflowTrigger.SCHEDULE,
            cron="0 8 * * *",
            timeout_s=7200,
            required_secrets=["YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN"],
            tags=["daily", "pipeline"],
        ))

        self.register(WorkflowDefinition(
            workflow_id="analytics_only",
            name="Analytics Collection",
            description="Collect and analyze video performance metrics",
            steps=[
                WorkflowStepDef("fetch", "Fetch Analytics", "fetch_analytics", priority=1),
                WorkflowStepDef("analyze", "Analyze Data", "analyze_metrics",
                               dependencies=["fetch"], priority=2),
                WorkflowStepDef("report", "Generate Report", "generate_report",
                               dependencies=["analyze"], priority=3),
            ],
            priority=WorkflowPriority.MEDIUM,
            trigger=WorkflowTrigger.SCHEDULE,
            cron="0 6 * * *",
            tags=["analytics"],
        ))

        self.register(WorkflowDefinition(
            workflow_id="intelligence_cycle",
            name="Intelligence Cycle",
            description="Run daily intelligence analysis and decision making",
            steps=[
                WorkflowStepDef("observe", "Observe Platform", "observe_platform", priority=1),
                WorkflowStepDef("analyze", "Analyze Patterns", "analyze_patterns",
                               dependencies=["observe"], priority=2),
                WorkflowStepDef("decide", "Make Decisions", "make_decisions",
                               dependencies=["analyze"], priority=3),
                WorkflowStepDef("execute", "Execute Actions", "execute_actions",
                               dependencies=["decide"], priority=4),
            ],
            priority=WorkflowPriority.HIGH,
            trigger=WorkflowTrigger.SCHEDULE,
            cron="30 7 * * *",
            tags=["intelligence"],
        ))

        self.register(WorkflowDefinition(
            workflow_id="experiment_cycle",
            name="A/B Experiment Cycle",
            description="Run A/B testing experiments and analyze results",
            steps=[
                WorkflowStepDef("setup", "Setup Experiments", "setup_experiments", priority=1),
                WorkflowStepDef("run", "Run Experiments", "run_experiments",
                               dependencies=["setup"], priority=2),
                WorkflowStepDef("analyze", "Analyze Results", "analyze_experiment_results",
                               dependencies=["run"], priority=3),
            ],
            priority=WorkflowPriority.MEDIUM,
            trigger=WorkflowTrigger.SCHEDULE,
            cron="0 9 * * 1",
            tags=["experiments"],
        ))

        self.register(WorkflowDefinition(
            workflow_id="recovery",
            name="System Recovery",
            description="Automatic failure recovery and system health restoration",
            steps=[
                WorkflowStepDef("diagnose", "Diagnose Failures", "diagnose_failures", priority=1),
                WorkflowStepDef("recover", "Recover State", "recover_state",
                               dependencies=["diagnose"], priority=2),
                WorkflowStepDef("validate", "Validate Recovery", "validate_recovery",
                               dependencies=["recover"], priority=3),
            ],
            priority=WorkflowPriority.CRITICAL,
            trigger=WorkflowTrigger.EVENT,
            tags=["recovery"],
        ))

        self.register(WorkflowDefinition(
            workflow_id="weekly_plan",
            name="Weekly Planning",
            description="Generate weekly content plan and schedule",
            steps=[
                WorkflowStepDef("analyze", "Analyze Trends", "analyze_weekly_trends", priority=1),
                WorkflowStepDef("plan", "Create Plan", "create_weekly_plan",
                               dependencies=["analyze"], priority=2),
                WorkflowStepDef("schedule", "Schedule Content", "schedule_weekly_content",
                               dependencies=["plan"], priority=3),
            ],
            priority=WorkflowPriority.MEDIUM,
            trigger=WorkflowTrigger.SCHEDULE,
            cron="0 7 * * 0",
            tags=["planning"],
        ))

    def register(self, definition: WorkflowDefinition):
        self._definitions[definition.workflow_id] = definition
        publish("github.workflow_registered", data={"workflow_id": definition.workflow_id,
                                                     "name": definition.name}, source="github")

    def get(self, workflow_id: str) -> Optional[WorkflowDefinition]:
        return self._definitions.get(workflow_id)

    def list_all(self, enabled_only: bool = False) -> list[WorkflowDefinition]:
        defs = list(self._definitions.values())
        if enabled_only:
            defs = [d for d in defs if d.enabled]
        return defs

    def list_by_tag(self, tag: str) -> list[WorkflowDefinition]:
        return [d for d in self._definitions.values() if tag in d.tags and d.enabled]

    def list_by_priority(self, priority: WorkflowPriority) -> list[WorkflowDefinition]:
        return [d for d in self._definitions.values()
                if d.priority == priority and d.enabled]

    def disable(self, workflow_id: str) -> bool:
        d = self._definitions.get(workflow_id)
        if d:
            d.enabled = False
            return True
        return False

    def enable(self, workflow_id: str) -> bool:
        d = self._definitions.get(workflow_id)
        if d:
            d.enabled = True
            return True
        return False

    def register_handler(self, handler_name: str, handler: Callable):
        self._handlers[handler_name] = handler

    def get_handler(self, handler_name: str) -> Optional[Callable]:
        return self._handlers.get(handler_name)

    def create_chain(self, name: str, workflow_ids: list[str]) -> WorkflowChain:
        chain_id = f"chain_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
        chain = WorkflowChain(
            chain_id=chain_id,
            name=name,
            workflow_ids=workflow_ids,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        self._chains[chain_id] = chain
        return chain

    def get_chain(self, chain_id: str) -> Optional[WorkflowChain]:
        return self._chains.get(chain_id)

    def list_chains(self) -> list[WorkflowChain]:
        return list(self._chains.values())

    def get_scheduled_workflows(self) -> list[WorkflowDefinition]:
        return [d for d in self._definitions.values()
                if d.enabled and d.trigger == WorkflowTrigger.SCHEDULE and d.cron]

    def select_workflow(self, context: dict = None) -> Optional[WorkflowDefinition]:
        ctx = context or {}
        tag = ctx.get("tag", "")
        priority = ctx.get("priority", "")
        candidates = [d for d in self._definitions.values() if d.enabled]
        if tag:
            candidates = [d for d in candidates if tag in d.tags]
        if priority:
            candidates = [d for d in candidates if d.priority.value == priority]
        if not candidates:
            return None
        candidates.sort(key=lambda d: (
            {"critical": 0, "high": 1, "medium": 2, "low": 3}[d.priority.value],
            d.name,
        ))
        return candidates[0]
