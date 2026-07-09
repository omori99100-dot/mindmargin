import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from mindmargin.content.models import (
    ContentItem, ContentLifecycleState, OptimizationCategory,
    Recommendation, RecommendationType, utcnow,
)

logger = logging.getLogger(__name__)

BEST_PERFORMING_VIEW_THRESHOLD = 1000
BEST_PERFORMING_CTR_THRESHOLD = 0.05
UNDERPERFORMING_VIEW_THRESHOLD = 100
UNDERPERFORMING_AGE_DAYS = 30
FORGOTTEN_AGE_DAYS = 60
FORGOTTEN_VIEW_THRESHOLD = 50
SEASONAL_LOOKBACK_DAYS = 365
VIRAL_VELOCITY_THRESHOLD = 0.5
DECAY_VELOCITY_THRESHOLD = -0.3


class ContentOptimizer:
    def __init__(self):
        pass

    def classify_item(self, item: ContentItem) -> OptimizationCategory:
        if item.total_views == 0:
            if item.published_at and self._age_days(item) > FORGOTTEN_AGE_DAYS:
                return OptimizationCategory.FORGOTTEN
            return OptimizationCategory.OPPORTUNITY

        if item.view_velocity > VIRAL_VELOCITY_THRESHOLD:
            return OptimizationCategory.VIRAL

        if item.evergreen_score > 0.6:
            return OptimizationCategory.EVERGREEN

        if item.view_velocity < DECAY_VELOCITY_THRESHOLD:
            return OptimizationCategory.DECAYING

        if (item.total_views > BEST_PERFORMING_VIEW_THRESHOLD
                and item.ctr > BEST_PERFORMING_CTR_THRESHOLD):
            return OptimizationCategory.BEST_PERFORMING

        if (item.total_views < UNDERPERFORMING_VIEW_THRESHOLD
                and self._age_days(item) > UNDERPERFORMING_AGE_DAYS):
            return OptimizationCategory.UNDERPERFORMING

        return OptimizationCategory.OPPORTUNITY

    def find_best_performing(self, items: list[ContentItem], limit: int = 10) -> list[ContentItem]:
        scored = [(self._performance_score(it), it) for it in items]
        scored.sort(key=lambda x: x[0], reverse=True)
        return [it for _, it in scored[:limit]]

    def find_underperforming(self, items: list[ContentItem], limit: int = 10) -> list[ContentItem]:
        candidates = []
        for it in items:
            if it.total_views == 0:
                continue
            if self._age_days(it) < UNDERPERFORMING_AGE_DAYS:
                continue
            perf = self._performance_score(it)
            if perf < 0.3:
                candidates.append((perf, it))
        candidates.sort(key=lambda x: x[0])
        return [it for _, it in candidates[:limit]]

    def find_forgotten(self, items: list[ContentItem], limit: int = 10) -> list[ContentItem]:
        forgotten = []
        for it in items:
            if it.total_views < FORGOTTEN_VIEW_THRESHOLD and self._age_days(it) > FORGOTTEN_AGE_DAYS:
                forgotten.append(it)
        forgotten.sort(key=lambda it: it.total_views)
        return forgotten[:limit]

    def find_seasonal(self, items: list[ContentItem], current_month: int = None) -> list[ContentItem]:
        if current_month is None:
            current_month = datetime.now(timezone.utc).month
        seasonal = []
        for it in items:
            if not it.published_at:
                continue
            try:
                pub_dt = datetime.fromisoformat(it.published_at.replace("Z", "+00:00"))
                if pub_dt.month == current_month and it.total_views > 500:
                    seasonal.append(it)
            except (ValueError, TypeError):
                continue
        return seasonal

    def find_viral(self, items: list[ContentItem], limit: int = 10) -> list[ContentItem]:
        viral = [it for it in items if it.view_velocity > VIRAL_VELOCITY_THRESHOLD]
        viral.sort(key=lambda it: it.view_velocity, reverse=True)
        return viral[:limit]

    def find_evergreen(self, items: list[ContentItem], limit: int = 10) -> list[ContentItem]:
        eg = [it for it in items if it.evergreen_score > 0.5]
        eg.sort(key=lambda it: it.evergreen_score, reverse=True)
        return eg[:limit]

    def find_decaying(self, items: list[ContentItem], limit: int = 10) -> list[ContentItem]:
        decaying = [it for it in items if it.view_velocity < DECAY_VELOCITY_THRESHOLD]
        decaying.sort(key=lambda it: it.view_velocity)
        return decaying[:limit]

    def get_optimization_report(self, items: list[ContentItem]) -> dict:
        categories = {}
        for it in items:
            cat = self.classify_item(it).value
            categories.setdefault(cat, []).append(it.content_id)

        return {
            "total_items": len(items),
            "categories": {k: len(v) for k, v in categories.items()},
            "best_performing_count": len(categories.get("best_performing", [])),
            "underperforming_count": len(categories.get("underperforming", [])),
            "forgotten_count": len(categories.get("forgotten", [])),
            "viral_count": len(categories.get("viral", [])),
            "evergreen_count": len(categories.get("evergreen", [])),
            "decaying_count": len(categories.get("decaying", [])),
            "opportunity_count": len(categories.get("opportunity", [])),
        }

    def _performance_score(self, item: ContentItem) -> float:
        view_score = min(item.total_views / 10000, 1.0) * 0.4
        ctr_score = min(item.ctr / 0.1, 1.0) * 0.3
        retention_score = min(item.avg_view_duration_s / 300, 1.0) * 0.2
        velocity_score = max(min(item.view_velocity + 1, 2.0) / 2.0, 0.0) * 0.1
        return view_score + ctr_score + retention_score + velocity_score

    def _age_days(self, item: ContentItem) -> int:
        if not item.published_at:
            return 0
        try:
            now = datetime.now(timezone.utc)
            pub_dt = datetime.fromisoformat(item.published_at.replace("Z", "+00:00"))
            return (now - pub_dt).days
        except (ValueError, TypeError):
            return 0
