import json
import logging
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

from mindmargin.config import settings

logger = logging.getLogger(__name__)


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class BusinessGoalType(str, Enum):
    MAXIMIZE_WATCH_TIME = "maximize_watch_time"
    MAXIMIZE_SUBSCRIBERS = "maximize_subscribers"
    MAXIMIZE_REVENUE = "maximize_revenue"
    MAXIMIZE_ENGAGEMENT = "maximize_engagement"
    MAXIMIZE_RETENTION = "maximize_retention"
    BRAND_GROWTH = "brand_growth"
    EDUCATIONAL_IMPACT = "educational_impact"
    CUSTOM_WEIGHTED = "custom_weighted"


class RevenueType(str, Enum):
    AD_REVENUE = "ad_revenue"
    AFFILIATE_REVENUE = "affiliate_revenue"
    SPONSORSHIP_REVENUE = "sponsorship_revenue"
    MEMBERSHIP_REVENUE = "membership_revenue"
    COURSE_REVENUE = "course_revenue"
    DIGITAL_PRODUCT_REVENUE = "digital_product_revenue"
    MERCHANDISE_REVENUE = "merchandise_revenue"
    DONATION_REVENUE = "donation_revenue"


class CampaignType(str, Enum):
    AFFILIATE = "affiliate"
    SPONSOR = "sponsor"
    PRODUCT_LAUNCH = "product_launch"
    EDUCATIONAL_SERIES = "educational_series"
    SEASONAL = "seasonal"
    BRAND_AWARENESS = "brand_awareness"


class CampaignStatus(str, Enum):
    PLANNED = "planned"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class ProductType(str, Enum):
    COURSE = "course"
    EBOOK = "ebook"
    TEMPLATE = "template"
    TOOL = "tool"
    COMMUNITY = "community"
    CONSULTING = "consulting"


class ForecastWindow(str, Enum):
    DAYS_30 = "30d"
    DAYS_90 = "90d"
    DAYS_180 = "180d"
    DAYS_365 = "365d"


@dataclass
class BusinessGoal:
    goal_id: str
    goal_type: BusinessGoalType
    name: str
    target_value: float = 0.0
    current_value: float = 0.0
    unit: str = ""
    weight: float = 1.0
    deadline: str = ""
    enabled: bool = True
    metadata: dict = field(default_factory=dict)

    @property
    def progress_pct(self) -> float:
        if self.target_value <= 0:
            return 0.0
        return min((self.current_value / self.target_value) * 100, 100.0)

    @property
    def is_achieved(self) -> bool:
        return self.current_value >= self.target_value if self.target_value > 0 else False

    def to_dict(self) -> dict:
        d = asdict(self)
        d["goal_type"] = self.goal_type.value
        d["progress_pct"] = round(self.progress_pct, 1)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "BusinessGoal":
        d["goal_type"] = BusinessGoalType(d["goal_type"]) if isinstance(d.get("goal_type"), str) else d.get("goal_type", BusinessGoalType.MAXIMIZE_REVENUE)
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class KPIRecord:
    kpi_id: str
    name: str
    value: float = 0.0
    previous_value: float = 0.0
    target_value: float = 0.0
    unit: str = ""
    category: str = ""
    period: str = ""
    timestamp: str = ""

    @property
    def change_pct(self) -> float:
        if self.previous_value == 0:
            return 0.0
        return ((self.value - self.previous_value) / abs(self.previous_value)) * 100

    @property
    def target_achievement_pct(self) -> float:
        if self.target_value <= 0:
            return 0.0
        return (self.value / self.target_value) * 100

    def to_dict(self) -> dict:
        d = asdict(self)
        d["change_pct"] = round(self.change_pct, 2)
        d["target_achievement_pct"] = round(self.target_achievement_pct, 1)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "KPIRecord":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class RevenueEntry:
    entry_id: str
    revenue_type: RevenueType
    amount: float = 0.0
    date: str = ""
    source: str = ""
    description: str = ""
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["revenue_type"] = self.revenue_type.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "RevenueEntry":
        d["revenue_type"] = RevenueType(d["revenue_type"]) if isinstance(d.get("revenue_type"), str) else d.get("revenue_type", RevenueType.AD_REVENUE)
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class CostEntry:
    entry_id: str
    category: str = ""
    amount: float = 0.0
    date: str = ""
    description: str = ""
    is_recurring: bool = False
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "CostEntry":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class Campaign:
    campaign_id: str
    campaign_type: CampaignType
    name: str
    status: CampaignStatus = CampaignStatus.PLANNED
    budget: float = 0.0
    spent: float = 0.0
    revenue: float = 0.0
    start_date: str = ""
    end_date: str = ""
    target_audience: str = ""
    content_ids: list[str] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)
    metadata: dict = field(default_factory=dict)

    @property
    def roi(self) -> float:
        if self.spent <= 0:
            return 0.0
        return ((self.revenue - self.spent) / self.spent) * 100

    @property
    def budget_utilization_pct(self) -> float:
        if self.budget <= 0:
            return 0.0
        return (self.spent / self.budget) * 100

    def to_dict(self) -> dict:
        d = asdict(self)
        d["campaign_type"] = self.campaign_type.value
        d["status"] = self.status.value
        d["roi"] = round(self.roi, 1)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Campaign":
        d["campaign_type"] = CampaignType(d["campaign_type"]) if isinstance(d.get("campaign_type"), str) else d.get("campaign_type", CampaignType.AFFILIATE)
        d["status"] = CampaignStatus(d["status"]) if isinstance(d.get("status"), str) else d.get("status", CampaignStatus.PLANNED)
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class Product:
    product_id: str
    product_type: ProductType
    name: str
    price: float = 0.0
    cost: float = 0.0
    sales_count: int = 0
    total_revenue: float = 0.0
    description: str = ""
    landing_page_url: str = ""
    content_ids: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    @property
    def margin_pct(self) -> float:
        if self.price <= 0:
            return 0.0
        return ((self.price - self.cost) / self.price) * 100

    def to_dict(self) -> dict:
        d = asdict(self)
        d["product_type"] = self.product_type.value
        d["margin_pct"] = round(self.margin_pct, 1)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Product":
        d["product_type"] = ProductType(d["product_type"]) if isinstance(d.get("product_type"), str) else d.get("product_type", ProductType.COURSE)
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class ForecastPoint:
    date: str = ""
    revenue: float = 0.0
    subscribers: int = 0
    views: int = 0
    expenses: float = 0.0
    roi: float = 0.0
    confidence: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ForecastPoint":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class ForecastResult:
    forecast_id: str = ""
    window: str = "30d"
    generated_at: str = ""
    points: list[dict] = field(default_factory=list)
    summary: dict = field(default_factory=dict)
    assumptions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "ForecastResult":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class BudgetAllocation:
    category: str = ""
    allocated: float = 0.0
    spent: float = 0.0
    limit: float = 0.0

    @property
    def remaining(self) -> float:
        return max(self.limit - self.spent, 0.0)

    @property
    def utilization_pct(self) -> float:
        if self.limit <= 0:
            return 0.0
        return (self.spent / self.limit) * 100

    def to_dict(self) -> dict:
        d = asdict(self)
        d["remaining"] = round(self.remaining, 2)
        d["utilization_pct"] = round(self.utilization_pct, 1)
        return d


@dataclass
class BusinessStatus:
    total_revenue_30d: float = 0.0
    total_revenue_90d: float = 0.0
    total_revenue_365d: float = 0.0
    total_costs_30d: float = 0.0
    total_costs_90d: float = 0.0
    profit_30d: float = 0.0
    profit_90d: float = 0.0
    roi_30d: float = 0.0
    roi_90d: float = 0.0
    rpm: float = 0.0
    cpm: float = 0.0
    active_campaigns: int = 0
    active_products: int = 0
    goals_achieved: int = 0
    goals_total: int = 0
    budget_utilization_pct: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class BusinessRecommendation:
    recommendation_id: str
    recommendation_type: str
    priority: int = 5
    confidence: float = 0.0
    title: str = ""
    description: str = ""
    estimated_impact: float = 0.0
    action_data: dict = field(default_factory=dict)
    status: str = "pending"
    created_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "BusinessRecommendation":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})
