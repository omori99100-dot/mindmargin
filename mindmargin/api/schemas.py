from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


# ── Pipeline ──

class PipelineRequest(BaseModel):
    topic: str
    publish: bool = False
    quick: bool = False
    mode: str = "documentary"
    privacy: str = "private"
    playlist: str = ""


class PipelineResponse(BaseModel):
    pipeline_id: str
    topic: str
    status: str
    completed_agents: list[str] = []
    errors: list[dict] = []
    output_dir: str = ""
    message: str = ""
    timing_s: Optional[float] = None
    video_path: str = ""
    youtube_url: str = ""


# ── Health ──

class CheckerResult(BaseModel):
    checker: str
    status: str
    value: float
    detail: str = ""


class HealthReport(BaseModel):
    status: str
    environment: str
    timestamp: str
    checkers: list[CheckerResult] = []
    failed_count: int = 0
    warning_count: int = 0
    pass_count: int = 0


# ── Job Management ──

class JobResponse(BaseModel):
    job_id: str
    job_type: str
    state: str
    created_at: str
    started_at: str = ""
    completed_at: str = ""
    result: dict = {}
    error: str = ""
    retry_count: int = 0
    max_retries: int = 3
    metadata: dict = {}


class JobListResponse(BaseModel):
    jobs: list[JobResponse]
    total: int


# ── Analytics & Dashboard ──

class PipelineStats(BaseModel):
    total_pipelines: int
    published_videos: int
    total_views: int
    total_likes: int
    total_comments: int
    total_shares: int
    avg_view_duration_s: float = 0
    best_hooks: list[dict] = []
    best_titles: list[dict] = []


class AnalyticsResponse(BaseModel):
    video_id: str
    status: str
    views: int = 0
    likes: int = 0
    comments: int = 0
    shares: int = 0
    avg_view_duration_s: float = 0
    subscribers_gained: int = 0
    error: str = ""


class DriftReportResponse(BaseModel):
    status: str
    drift: dict = {}
    trends: dict = {}
    generated_at: str = ""


# ── A/B Testing ──

class ABTestSummary(BaseModel):
    title_wins: int = 0
    title_losses: int = 0
    thumb_wins: int = 0
    thumb_losses: int = 0
    active_tests: int = 0
    pending_tests: int = 0
    evolution_history_count: int = 0


class ABTestResponse(BaseModel):
    status: str
    actions_taken: int = 0
    active_tests: int = 0
    actions: list[str] = []


# ── Intelligence: Experiments ──

class ExperimentResponse(BaseModel):
    experiment_id: str
    hypothesis: str
    experiment_type: str
    topic: str
    status: str
    variant_a: str = ""
    variant_b: str = ""
    expected_gain: float = 0
    affected_metric: str = ""
    confidence: float = 0
    winner: str = ""
    created_at: str = ""
    evaluated_at: str = ""


class ExperimentCycleResponse(BaseModel):
    new_hypotheses: int
    experiments_completed: int
    total_active: int = 0
    timestamp: str


# ── Intelligence: Forecasts ──

class ForecastResponse(BaseModel):
    topic: str
    window_days: int
    forecast_score: float
    confidence: float
    uncertainty: float
    lower_bound: float = 0
    upper_bound: float = 0
    forecast_date: str


# ── Intelligence: Weekly Plan ──

class WeeklyPlanEntry(BaseModel):
    day: str
    format_label: str
    topic: str
    opportunity_score: float = 0
    confidence: float = 0


class WeeklyPlanResponse(BaseModel):
    week_start: str
    week_end: str = ""
    total_opportunities: int = 0
    ranked_count: int = 0
    schedule: list[WeeklyPlanEntry] = []
    summary: dict = {}
    generated_at: str


# ── Intelligence: Knowledge Graph ──

class GraphBuildResponse(BaseModel):
    topics_found: int
    keywords_extracted: int
    relationships_created: int
    status: str = "completed"


class AdjacentTopic(BaseModel):
    topic: str
    relationship: str = "related"
    strength: float = 0


class ExpansionOpportunity(BaseModel):
    topic: str
    source_topic: str
    strength: float
    relationship: str = "related"
    already_scored: bool = False


class DuplicateCheckResponse(BaseModel):
    is_duplicate: bool
    duplicate_of: str = ""
    similarity: float = 0


# ── Intelligence: Scoring ──

class ScoredCandidate(BaseModel):
    topic: str
    opportunity_score: float
    confidence: float
    trend_score: float = 0
    novelty: float = 0
    seasonality: float = 0
    audience_match: float = 0
    evergreen_score: float = 0
    competition: float = 0
    historical_performance: float = 0
    source: str = ""


# ── Decisions & Explainability ──

class AlternativeCandidate(BaseModel):
    topic: str
    opportunity_score: float
    confidence: float
    why_lost: list[str] = []


class DecisionExplanation(BaseModel):
    selected_topic: str
    opportunity_score: float
    confidence: float
    positive_factors: list[str] = []
    negative_factors: list[str] = []
    alternative_candidates: list[AlternativeCandidate] = []
    timestamp: str
    markdown: str = ""


class ExecuteDecisionResponse(BaseModel):
    status: str
    topic: str
    pipeline_id: str = ""
    video_id: str = ""
    video_url: str = ""
    explanation: Optional[DecisionExplanation] = None
    error: str = ""


# ── Feedback ──

class FeedbackCycleResponse(BaseModel):
    outcomes_collected: int
    weights_changed: int
    weight_deltas: dict = {}
    timestamp: str


# ── Selection Pressure ──

class SelectionStatusResponse(BaseModel):
    classifications: dict = {}
    total_classified: int = 0
    reinforced_count: int = 0
    suppressed_count: int = 0
    dead_count: int = 0
    dominant_archetypes: list[dict] = []
    topic_suggestions: list[dict] = []


# ── Operations Hub ──

class OperationStatusResponse(BaseModel):
    status: str
    active_operations: int
    completed_today: int
    failed_today: int
    scheduled: int
    records: list[dict] = []


class OperationRunRequest(BaseModel):
    operation_type: str
    quick: bool = False
    auto_publish: bool = True
    privacy: str = "unlisted"


class OperationRunResponse(BaseModel):
    operation_id: str = ""
    operation_type: str
    status: str
    result: dict = {}
    error: str = ""


class OperationHistoryResponse(BaseModel):
    records: list[dict]
    total: int


class OperationScheduleRequest(BaseModel):
    operation_type: str
    cron: str = ""
    interval_s: float = 0
    enabled: bool = True


class OperationRecoverResponse(BaseModel):
    recovered: int
    total_failed: int


# ── Channel Manager ──

class ChannelStatusResponse(BaseModel):
    status: str
    active_content: int = 0
    published_today: int = 0
    scheduled_count: int = 0
    health_score: float = 10.0
    total_items: int = 0
    state_breakdown: dict = {}
    recent_items: list[dict] = []
    calendar_7day: int = 0
    calendar_30day: int = 0
    calendar_90day: int = 0
    governance_rules_active: int = 0
    format_balance: dict = {}


class CalendarResponse(BaseModel):
    entries: list[dict]
    total: int
    days: int


class ContentListResponse(BaseModel):
    items: list[dict]
    total: int


class ContentAdvanceRequest(BaseModel):
    target_state: str


class ContentAdvanceResponse(BaseModel):
    content_id: str
    status: str
    previous_state: str = ""
    new_state: str = ""


class GovernanceRuleResponse(BaseModel):
    rules: list[dict]
    total: int


class GovernanceToggleResponse(BaseModel):
    rule_id: str
    enabled: bool
    status: str


class DailyCycleResponse(BaseModel):
    status: str
    started_at: str
    completed_at: str = ""
    steps: dict = {}


# ── Executive Agent ──

class ExecutiveStatusResponse(BaseModel):
    running: bool = False
    cycle_count: int = 0
    policy: str = "balanced"
    policy_config: dict = {}
    memory: dict = {}
    last_snapshot: Optional[dict] = None
    last_plan: Optional[dict] = None
    last_decision: Optional[dict] = None
    recent_executions: list[dict] = []


class ExecutivePlanResponse(BaseModel):
    actions: list[dict] = []
    snapshot_summary: str = ""
    generated_at: str = ""
    total: int = 0


class ExecutiveHistoryResponse(BaseModel):
    records: list[dict]
    total: int


class ExecutivePolicyResponse(BaseModel):
    policy_type: str = "balanced"
    publishing_frequency_hours: int = 24
    risk_tolerance: float = 0.5
    experiment_frequency_hours: int = 168
    budget_usage_pct: float = 50.0
    auto_approve_threshold: float = 0.7
    max_concurrent_workflows: int = 3
    enable_auto_publish: bool = True
    enable_auto_experiments: bool = True
    description: str = ""


class ExecutivePolicySetRequest(BaseModel):
    policy_type: str


class ExecutiveMemoryResponse(BaseModel):
    total: int = 0
    categories: dict = {}
    oldest: str = ""
    newest: str = ""


class ExecutiveRunResponse(BaseModel):
    status: str
    cycle: int = 0
    started_at: str = ""
    completed_at: str = ""
    problems: list[str] = []
    opportunities: list[str] = []
    decision: Optional[dict] = None
    actions_executed: list[dict] = []
    total_actions: int = 0


# ── Error ──

class ErrorResponse(BaseModel):
    detail: str
    error_code: str = ""
