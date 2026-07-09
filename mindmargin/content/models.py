import json
import logging
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class AssetType(str, Enum):
    VIDEO = "video"
    THUMBNAIL = "thumbnail"
    SCRIPT = "script"
    VOICE = "voice"
    METADATA = "metadata"
    TITLE = "title"
    DESCRIPTION = "description"
    TAGS = "tags"
    SHORT = "short"
    ARTICLE = "article"
    NEWSLETTER = "newsletter"
    SOCIAL_POST = "social_post"
    PODCAST_OUTLINE = "podcast_outline"
    COMMUNITY_POST = "community_post"


class ContentLifecycleState(str, Enum):
    DRAFT = "draft"
    PLANNED = "planned"
    PRODUCED = "produced"
    PUBLISHED = "published"
    GROWING = "growing"
    EVERGREEN = "evergreen"
    DECLINING = "declining"
    REFRESHING = "refreshing"
    REPUBLISHED = "republished"
    ARCHIVED = "archived"


class OptimizationCategory(str, Enum):
    BEST_PERFORMING = "best_performing"
    UNDERPERFORMING = "underperforming"
    FORGOTTEN = "forgotten"
    SEASONAL = "seasonal"
    VIRAL = "viral"
    EVERGREEN = "evergreen"
    DECAYING = "decaying"
    OPPORTUNITY = "opportunity"


class RepurposeFormat(str, Enum):
    SHORT = "short"
    TWITTER = "twitter"
    LINKEDIN = "linkedin"
    FACEBOOK = "facebook"
    TELEGRAM = "telegram"
    BLOG = "blog"
    NEWSLETTER = "newsletter"
    PODCAST_OUTLINE = "podcast_outline"
    COMMUNITY_POST = "community_post"
    PLAYLIST_UPDATE = "playlist_update"
    INTERNAL_LINK = "internal_link"


class RecommendationType(str, Enum):
    TITLE_REFRESH = "title_refresh"
    THUMBNAIL_REPLACE = "thumbnail_replace"
    SEO_UPDATE = "seo_update"
    REPURPOSE = "repurpose"
    REPUBLISH = "republish"
    RECYCLE = "recycle"
    ARCHIVE = "archive"
    CREATE_SHORT = "create_short"
    CREATE_ARTICLE = "create_article"
    GENERATE_NEWSLETTER = "generate_newsletter"
    SOCIAL_SNIPPET = "social_snippet"
    COMMUNITY_POST = "community_post"
    PLAYLIST_UPDATE = "playlist_update"
    INTERNAL_LINKING = "internal_linking"
    DUPLICATE_DETECTION = "duplicate_detection"
    KEYWORD_OVERLAP = "keyword_overlap"


@dataclass
class ContentAsset:
    asset_id: str
    content_id: str
    asset_type: AssetType
    path: str = ""
    data: dict = field(default_factory=dict)
    version: int = 1
    checksum: str = ""
    created_at: str = ""
    updated_at: str = ""
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["asset_type"] = self.asset_type.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "ContentAsset":
        d["asset_type"] = AssetType(d["asset_type"]) if isinstance(d.get("asset_type"), str) else d.get("asset_type", AssetType.VIDEO)
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class ContentVersion:
    version_id: str
    content_id: str
    version_number: int
    topic: str = ""
    title: str = ""
    description: str = ""
    tags: list[str] = field(default_factory=list)
    thumbnail_path: str = ""
    video_path: str = ""
    script_text: str = ""
    metadata: dict = field(default_factory=dict)
    created_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ContentVersion":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class ContentRelationship:
    source_id: str
    target_id: str
    relationship_type: str
    strength: float = 0.0
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ContentItem:
    content_id: str
    topic: str
    lifecycle_state: ContentLifecycleState = ContentLifecycleState.DRAFT
    published_at: str = ""
    last_analyzed_at: str = ""
    last_refreshed_at: str = ""
    pipeline_id: str = ""
    video_id: str = ""
    category: str = ""
    keywords: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    title: str = ""
    description: str = ""
    thumbnail_path: str = ""
    video_path: str = ""
    script_path: str = ""
    voice_path: str = ""
    assets: list[str] = field(default_factory=list)
    versions: list[str] = field(default_factory=list)
    relationships: list[dict] = field(default_factory=list)
    reuse_history: list[dict] = field(default_factory=list)
    analytics_snapshot: dict = field(default_factory=dict)
    optimization_score: float = 0.0
    optimization_category: str = ""
    seo_score: float = 0.0
    freshness_score: float = 0.0
    evergreen_score: float = 0.0
    repurpose_potential: float = 0.0
    decay_rate: float = 0.0
    view_velocity: float = 0.0
    engagement_rate: float = 0.0
    ctr: float = 0.0
    avg_view_duration_s: float = 0.0
    total_views: int = 0
    total_likes: int = 0
    total_comments: int = 0
    total_shares: int = 0
    subscribers_gained: int = 0
    metadata: dict = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["lifecycle_state"] = self.lifecycle_state.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "ContentItem":
        d["lifecycle_state"] = ContentLifecycleState(d["lifecycle_state"]) if isinstance(d.get("lifecycle_state"), str) else d.get("lifecycle_state", ContentLifecycleState.DRAFT)
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class Recommendation:
    recommendation_id: str
    content_id: str
    recommendation_type: RecommendationType
    priority: int = 5
    confidence: float = 0.0
    title: str = ""
    description: str = ""
    rationale: str = ""
    estimated_impact: float = 0.0
    action_data: dict = field(default_factory=dict)
    status: str = "pending"
    created_at: str = ""
    acted_at: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["recommendation_type"] = self.recommendation_type.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Recommendation":
        d["recommendation_type"] = RecommendationType(d["recommendation_type"]) if isinstance(d.get("recommendation_type"), str) else d.get("recommendation_type", RecommendationType.TITLE_REFRESH)
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class RepurposeSuggestion:
    suggestion_id: str
    source_content_id: str
    target_format: RepurposeFormat
    confidence: float = 0.0
    title: str = ""
    outline: str = ""
    estimated_effort: str = ""
    estimated_impact: float = 0.0
    status: str = "pending"
    created_at: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["target_format"] = self.target_format.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "RepurposeSuggestion":
        d["target_format"] = RepurposeFormat(d["target_format"]) if isinstance(d.get("target_format"), str) else d.get("target_format", RepurposeFormat.SHORT)
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class LibraryReport:
    total_items: int = 0
    by_state: dict = field(default_factory=dict)
    by_category: dict = field(default_factory=dict)
    by_optimization: dict = field(default_factory=dict)
    avg_seo_score: float = 0.0
    avg_freshness: float = 0.0
    avg_evergreen: float = 0.0
    total_recommendations: int = 0
    pending_recommendations: int = 0
    total_repurpose_suggestions: int = 0
    items_needing_refresh: int = 0
    items_archivable: int = 0

    def to_dict(self) -> dict:
        return asdict(self)


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
