import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

logger = logging.getLogger(__name__)


class ContentFormat(str, Enum):
    SHORT = "short"
    LONG = "long"


class ContentState(str, Enum):
    PLANNED = "planned"
    RESEARCHING = "researching"
    WRITING = "writing"
    PRODUCING = "producing"
    REVIEWING = "reviewing"
    SCHEDULED = "scheduled"
    PUBLISHED = "published"
    ANALYZING = "analyzing"
    LEARNING = "learning"
    ARCHIVED = "archived"


CONTENT_STATE_TRANSITIONS: dict[ContentState, list[ContentState]] = {
    ContentState.PLANNED: [ContentState.RESEARCHING, ContentState.ARCHIVED],
    ContentState.RESEARCHING: [ContentState.WRITING, ContentState.PLANNED, ContentState.ARCHIVED],
    ContentState.WRITING: [ContentState.PRODUCING, ContentState.RESEARCHING, ContentState.ARCHIVED],
    ContentState.PRODUCING: [ContentState.REVIEWING, ContentState.WRITING, ContentState.ARCHIVED],
    ContentState.REVIEWING: [ContentState.SCHEDULED, ContentState.PRODUCING, ContentState.ARCHIVED],
    ContentState.SCHEDULED: [ContentState.PUBLISHED, ContentState.PLANNED, ContentState.ARCHIVED],
    ContentState.PUBLISHED: [ContentState.ANALYZING, ContentState.ARCHIVED],
    ContentState.ANALYZING: [ContentState.LEARNING, ContentState.ARCHIVED],
    ContentState.LEARNING: [ContentState.ARCHIVED, ContentState.PLANNED],
    ContentState.ARCHIVED: [],
}


@dataclass
class ContentItem:
    content_id: str
    topic: str
    format: ContentFormat
    category: str
    state: ContentState
    priority: int = 5
    confidence: float = 0.0
    opportunity_score: float = 0.0
    estimated_publish_at: str = ""
    scheduled_at: str = ""
    published_at: str = ""
    workflow_id: str = ""
    pipeline_id: str = ""
    video_id: str = ""
    playlist_ids: list[str] = field(default_factory=list)
    series_id: str = ""
    asset_requirements: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    review_notes: str = ""
    governance_blocked: bool = False
    governance_block_reason: str = ""
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["format"] = self.format.value if isinstance(self.format, ContentFormat) else self.format
        d["state"] = self.state.value if isinstance(self.state, ContentState) else self.state
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "ContentItem":
        d["format"] = ContentFormat(d["format"]) if isinstance(d.get("format"), str) else d.get("format", ContentFormat.LONG)
        d["state"] = ContentState(d["state"]) if isinstance(d.get("state"), str) else d.get("state", ContentState.PLANNED)
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    def can_transition_to(self, new_state: ContentState) -> bool:
        allowed = CONTENT_STATE_TRANSITIONS.get(self.state, [])
        return new_state in allowed

    @property
    def is_terminal(self) -> bool:
        return self.state == ContentState.ARCHIVED

    @property
    def is_published(self) -> bool:
        return self.state in (ContentState.PUBLISHED, ContentState.ANALYZING, ContentState.LEARNING, ContentState.ARCHIVED)


@dataclass
class CalendarEntry:
    topic: str
    format: ContentFormat
    priority: int
    publish_time: str
    estimated_confidence: float
    estimated_opportunity: float
    required_assets: list[str] = field(default_factory=list)
    workflow_id: str = ""
    category: str = ""
    content_id: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["format"] = self.format.value if isinstance(self.format, ContentFormat) else self.format
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "CalendarEntry":
        d["format"] = ContentFormat(d["format"]) if isinstance(d.get("format"), str) else d.get("format", ContentFormat.LONG)
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


class GovernanceRuleType(str, Enum):
    MAX_DAILY_UPLOADS = "max_daily_uploads"
    MIN_SPACING_HOURS = "min_spacing_hours"
    AVOID_SIMILAR_TITLES = "avoid_similar_titles"
    AVOID_REPEATED_KEYWORDS = "avoid_repeated_keywords"
    EXPERIMENT_COOLDOWN = "experiment_cooldown"
    MANUAL_LOCK = "manual_lock"
    CHANNEL_HEALTH_MIN = "channel_health_min"
    MAX_SHORTS_PERCENT = "max_shorts_percent"
    MIN_CATEGORY_ROTATION = "min_category_rotation"


@dataclass
class GovernanceRule:
    rule_id: str
    rule_type: GovernanceRuleType
    name: str
    enabled: bool = True
    config: dict = field(default_factory=dict)
    description: str = ""

    def to_dict(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "rule_type": self.rule_type.value if isinstance(self.rule_type, GovernanceRuleType) else self.rule_type,
            "name": self.name,
            "enabled": self.enabled,
            "config": self.config,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "GovernanceRule":
        d["rule_type"] = GovernanceRuleType(d["rule_type"]) if isinstance(d.get("rule_type"), str) else d.get("rule_type")
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class GovernanceResult:
    allowed: bool
    rule_id: str = ""
    rule_name: str = ""
    reason: str = ""
    details: dict = field(default_factory=dict)


@dataclass
class ChannelReport:
    status: str
    active_content: int
    published_today: int
    scheduled_count: int
    health_score: float
    total_items: int
    state_breakdown: dict = field(default_factory=dict)
    recent_items: list[dict] = field(default_factory=list)
    calendar_7day: int = 0
    calendar_30day: int = 0
    calendar_90day: int = 0
    governance_rules_active: int = 0
    format_balance: dict = field(default_factory=dict)
