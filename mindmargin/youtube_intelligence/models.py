import json
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Optional


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ── Enums ──

class HealthFactor(str, Enum):
    VIEWS = "views"
    WATCH_TIME = "watch_time"
    CTR = "ctr"
    AVG_VIEW_DURATION = "avg_view_duration"
    RETENTION = "retention"
    SUBSCRIBERS = "subscribers"
    RETURNING_VIEWERS = "returning_viewers"
    NEW_VIEWERS = "new_viewers"
    TRAFFIC_SOURCES = "traffic_sources"
    IMPRESSIONS = "impressions"
    RPM = "rpm"
    CPM = "cpm"
    UPLOAD_CONSISTENCY = "upload_consistency"
    CHANNEL_VELOCITY = "channel_velocity"


class GrowthSignal(str, Enum):
    FAST_GROWING_TOPIC = "fast_growing_topic"
    DECLINING_TOPIC = "declining_topic"
    EVERGREEN_OPPORTUNITY = "evergreen_opportunity"
    MISSED_OPPORTUNITY = "missed_opportunity"
    AUDIENCE_FATIGUE = "audience_fatigue"
    CONTENT_SATURATION = "content_saturation"
    GROWTH_BOTTLENECK = "growth_bottleneck"


class RetentionPattern(str, Enum):
    STRONG_HOOK = "strong_hook"
    WEAK_INTRO = "weak_intro"
    GRADUAL_DROP = "gradual_drop"
    SUDDEN_DROP = "sudden_drop"
    RECOVERY = "recovery"
    STRONG_ENDING = "strong_ending"
    FLAT = "flat"


class BenchmarkCategory(str, Enum):
    BEST_CTR = "best_ctr"
    BEST_WATCH_TIME = "best_watch_time"
    BEST_RETENTION = "best_retention"
    BEST_PUBLISHING_TIME = "best_publishing_time"
    BEST_TOPIC_CATEGORY = "best_topic_category"
    BEST_THUMBNAIL_STYLE = "best_thumbnail_style"
    BEST_SCRIPT_LENGTH = "best_script_length"
    BEST_TITLE_PATTERN = "best_title_pattern"


class CompetitionGap(str, Enum):
    UNCOVERED_TOPIC = "uncovered_topic"
    UNDERSERVED_FORMAT = "underserved_format"
    QUALITY_GAP = "quality_gap"
    FREQUENCY_GAP = "frequency_gap"
    AUDIENCE_GAP = "audience_gap"


class RecommendationType(str, Enum):
    CONTENT = "content"
    PUBLISHING = "publishing"
    OPTIMIZATION = "optimization"
    GROWTH = "growth"
    AUDIENCE = "audience"
    MONETIZATION = "monetization"


class TrendDirection(str, Enum):
    RISING = "rising"
    STABLE = "stable"
    DECLINING = "declining"


# ── Data Models ──

@dataclass
class HealthMetric:
    factor: HealthFactor
    value: float
    score: float
    weight: float = 1.0
    trend: TrendDirection = TrendDirection.STABLE
    benchmark: float = 0.0
    delta_from_benchmark: float = 0.0
    metadata: dict = field(default_factory=dict)

    @property
    def is_above_benchmark(self) -> bool:
        return self.value > self.benchmark if self.benchmark > 0 else True

    def to_dict(self) -> dict:
        d = asdict(self)
        d["factor"] = self.factor.value
        d["trend"] = self.trend.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "HealthMetric":
        d["factor"] = HealthFactor(d["factor"]) if isinstance(d.get("factor"), str) else d.get("factor", HealthFactor.VIEWS)
        d["trend"] = TrendDirection(d["trend"]) if isinstance(d.get("trend"), str) else d.get("trend", TrendDirection.STABLE)
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class ChannelHealthReport:
    report_id: str
    overall_score: float = 0.0
    metrics: list[HealthMetric] = field(default_factory=list)
    grade: str = ""
    summary: str = ""
    top_strengths: list[str] = field(default_factory=list)
    top_weaknesses: list[str] = field(default_factory=list)
    generated_at: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["metrics"] = [m.to_dict() for m in self.metrics]
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "ChannelHealthReport":
        d["metrics"] = [HealthMetric.from_dict(m) for m in d.get("metrics", [])]
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class AudienceInsight:
    insight_id: str
    category: str
    metric_name: str
    metric_value: str
    confidence: float = 0.0
    sample_size: int = 0
    trend: TrendDirection = TrendDirection.STABLE
    recommendation: str = ""
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["trend"] = self.trend.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "AudienceInsight":
        d["trend"] = TrendDirection(d["trend"]) if isinstance(d.get("trend"), str) else d.get("trend", TrendDirection.STABLE)
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class AudienceProfile:
    profile_id: str
    best_upload_time: str = ""
    best_upload_day: str = ""
    top_geographies: list[dict] = field(default_factory=list)
    top_languages: list[dict] = field(default_factory=list)
    device_breakdown: list[dict] = field(default_factory=list)
    returning_viewer_pct: float = 0.0
    subscriber_view_pct: float = 0.0
    avg_session_duration: float = 0.0
    audience_overlap_score: float = 0.0
    loyal_segments: list[dict] = field(default_factory=list)
    insights: list[AudienceInsight] = field(default_factory=list)
    generated_at: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["insights"] = [i.to_dict() for i in self.insights]
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "AudienceProfile":
        d["insights"] = [AudienceInsight.from_dict(i) for i in d.get("insights", [])]
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class GrowthSignalRecord:
    signal_id: str
    signal_type: GrowthSignal
    topic: str
    strength: float = 0.0
    evidence: list[str] = field(default_factory=list)
    first_detected: str = ""
    last_updated: str = ""
    action_required: bool = False
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["signal_type"] = self.signal_type.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "GrowthSignalRecord":
        d["signal_type"] = GrowthSignal(d["signal_type"]) if isinstance(d.get("signal_type"), str) else d.get("signal_type", GrowthSignal.FAST_GROWING_TOPIC)
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class GrowthReport:
    report_id: str
    signals: list[GrowthSignalRecord] = field(default_factory=list)
    fast_growing_topics: list[dict] = field(default_factory=list)
    declining_topics: list[dict] = field(default_factory=list)
    evergreen_opportunities: list[dict] = field(default_factory=list)
    missed_opportunities: list[dict] = field(default_factory=list)
    bottlenecks: list[dict] = field(default_factory=list)
    overall_growth_score: float = 0.0
    summary: str = ""
    generated_at: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["signals"] = [s.to_dict() for s in self.signals]
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "GrowthReport":
        d["signals"] = [GrowthSignalRecord.from_dict(s) for s in d.get("signals", [])]
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class RetentionDataPoint:
    timestamp_pct: float
    retention_pct: float
    label: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "RetentionDataPoint":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class RetentionAnalysis:
    analysis_id: str
    video_id: str = ""
    video_title: str = ""
    data_points: list[RetentionDataPoint] = field(default_factory=list)
    patterns: list[RetentionPattern] = field(default_factory=list)
    drop_off_points: list[dict] = field(default_factory=list)
    strong_hooks: list[dict] = field(default_factory=list)
    strong_endings: list[dict] = field(default_factory=list)
    optimal_length_seconds: float = 0.0
    avg_retention_pct: float = 0.0
    hook_strength_score: float = 0.0
    ending_strength_score: float = 0.0
    script_recommendations: list[str] = field(default_factory=list)
    generated_at: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["data_points"] = [p.to_dict() for p in self.data_points]
        d["patterns"] = [p.value for p in self.patterns]
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "RetentionAnalysis":
        d["data_points"] = [RetentionDataPoint.from_dict(p) for p in d.get("data_points", [])]
        d["patterns"] = [RetentionPattern(p) for p in d.get("patterns", []) if isinstance(p, str)]
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class CTRDataPoint:
    video_id: str
    title: str = ""
    impressions: int = 0
    clicks: int = 0
    ctr_pct: float = 0.0
    thumbnail_style: str = ""
    title_pattern: str = ""
    topic_category: str = ""
    publish_time: str = ""
    metadata_effectiveness: float = 0.0
    predicted_ctr: float = 0.0
    created_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "CTRDataPoint":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class CTRReport:
    report_id: str
    data_points: list[CTRDataPoint] = field(default_factory=list)
    avg_ctr: float = 0.0
    best_ctr: float = 0.0
    worst_ctr: float = 0.0
    title_effectiveness: dict = field(default_factory=dict)
    thumbnail_effectiveness: dict = field(default_factory=dict)
    keyword_effectiveness: dict = field(default_factory=dict)
    recommendations: list[str] = field(default_factory=list)
    generated_at: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["data_points"] = [p.to_dict() for p in self.data_points]
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "CTRReport":
        d["data_points"] = [CTRDataPoint.from_dict(p) for p in d.get("data_points", [])]
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class CompetitorChannel:
    channel_id: str
    channel_name: str = ""
    subscriber_count: int = 0
    avg_views: float = 0.0
    upload_frequency: float = 0.0
    topic_overlap_score: float = 0.0
    estimated_growth_rate: float = 0.0
    content_gaps: list[dict] = field(default_factory=list)
    strengths: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)
    last_analyzed: str = ""
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "CompetitorChannel":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class CompetitionReport:
    report_id: str
    competitors: list[CompetitorChannel] = field(default_factory=list)
    your_channel_summary: dict = field(default_factory=dict)
    avg_competitor_frequency: float = 0.0
    avg_competitor_growth: float = 0.0
    topic_gaps: list[dict] = field(default_factory=list)
    opportunities: list[dict] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)
    generated_at: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["competitors"] = [c.to_dict() for c in self.competitors]
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "CompetitionReport":
        d["competitors"] = [CompetitorChannel.from_dict(c) for c in d.get("competitors", [])]
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class BenchmarkEntry:
    entry_id: str
    category: BenchmarkCategory
    metric_name: str
    metric_value: float = 0.0
    context: str = ""
    source_video_id: str = ""
    recorded_at: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["category"] = self.category.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "BenchmarkEntry":
        d["category"] = BenchmarkCategory(d["category"]) if isinstance(d.get("category"), str) else d.get("category", BenchmarkCategory.BEST_CTR)
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class BenchmarkReport:
    report_id: str
    entries: list[BenchmarkEntry] = field(default_factory=list)
    by_category: dict = field(default_factory=dict)
    summary: str = ""
    generated_at: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["entries"] = [e.to_dict() for e in self.entries]
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "BenchmarkReport":
        d["entries"] = [BenchmarkEntry.from_dict(e) for e in d.get("entries", [])]
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class YouTubeRecommendation:
    recommendation_id: str
    recommendation_type: RecommendationType
    priority: int = 5
    confidence: float = 0.0
    title: str = ""
    description: str = ""
    estimated_impact: str = ""
    action_data: dict = field(default_factory=dict)
    source_module: str = ""
    status: str = "pending"
    created_at: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["recommendation_type"] = self.recommendation_type.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "YouTubeRecommendation":
        d["recommendation_type"] = RecommendationType(d["recommendation_type"]) if isinstance(d.get("recommendation_type"), str) else d.get("recommendation_type", RecommendationType.CONTENT)
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class TrendRecord:
    trend_id: str
    topic: str
    direction: TrendDirection = TrendDirection.STABLE
    velocity: float = 0.0
    volume: int = 0
    competition: float = 0.0
    relevance_score: float = 0.0
    detected_at: str = ""
    expires_at: str = ""
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["direction"] = self.direction.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "TrendRecord":
        d["direction"] = TrendDirection(d["direction"]) if isinstance(d.get("direction"), str) else d.get("direction", TrendDirection.STABLE)
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class TrendReport:
    report_id: str
    trends: list[TrendRecord] = field(default_factory=list)
    rising_topics: list[dict] = field(default_factory=list)
    declining_topics: list[dict] = field(default_factory=list)
    stable_topics: list[dict] = field(default_factory=list)
    niche_opportunities: list[dict] = field(default_factory=list)
    summary: str = ""
    generated_at: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["trends"] = [t.to_dict() for t in self.trends]
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "TrendReport":
        d["trends"] = [TrendRecord.from_dict(t) for t in d.get("trends", [])]
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class YouTubeIntelligenceStatus:
    health_score: float = 0.0
    growth_score: float = 0.0
    audience_segments: int = 0
    active_signals: int = 0
    retention_analyses: int = 0
    ctr_analyses: int = 0
    competitors_tracked: int = 0
    benchmarks_recorded: int = 0
    recommendations_pending: int = 0
    trends_tracked: int = 0
    last_health_check: str = ""
    last_growth_analysis: str = ""
    generated_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "YouTubeIntelligenceStatus":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})
