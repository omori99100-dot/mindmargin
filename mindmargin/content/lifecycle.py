import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from mindmargin.content.models import (
    ContentItem, ContentLifecycleState, OptimizationCategory, utcnow,
)

logger = logging.getLogger(__name__)

LIFECYCLE_TRANSITIONS = {
    ContentLifecycleState.DRAFT: [ContentLifecycleState.PLANNED, ContentLifecycleState.ARCHIVED],
    ContentLifecycleState.PLANNED: [ContentLifecycleState.PRODUCED, ContentLifecycleState.ARCHIVED],
    ContentLifecycleState.PRODUCED: [ContentLifecycleState.PUBLISHED, ContentLifecycleState.ARCHIVED],
    ContentLifecycleState.PUBLISHED: [ContentLifecycleState.GROWING, ContentLifecycleState.DECLINING, ContentLifecycleState.ARCHIVED],
    ContentLifecycleState.GROWING: [ContentLifecycleState.EVERGREEN, ContentLifecycleState.DECLINING, ContentLifecycleState.REFRESHING],
    ContentLifecycleState.EVERGREEN: [ContentLifecycleState.REFRESHING, ContentLifecycleState.DECLINING, ContentLifecycleState.ARCHIVED],
    ContentLifecycleState.DECLINING: [ContentLifecycleState.REFRESHING, ContentLifecycleState.ARCHIVED],
    ContentLifecycleState.REFRESHING: [ContentLifecycleState.REPUBLISHED, ContentLifecycleState.PUBLISHED],
    ContentLifecycleState.REPUBLISHED: [ContentLifecycleState.GROWING, ContentLifecycleState.DECLINING],
    ContentLifecycleState.ARCHIVED: [],
}

DECAY_THRESHOLD_DAYS = 30
DECAY_VIEW_DROP_PCT = 0.3
EVERGREEN_MIN_DAYS = 60
EVERGREEN_STABLE_VIEW_PCT = 0.7
GROWING_VIEW_INCREASE_PCT = 0.1
STALE_ANALYSIS_DAYS = 14


class ContentLifecycleManager:
    def __init__(self):
        pass

    def can_transition(self, item: ContentItem, new_state: ContentLifecycleState) -> bool:
        allowed = LIFECYCLE_TRANSITIONS.get(item.lifecycle_state, [])
        return new_state in allowed

    def transition(self, item: ContentItem, new_state: ContentLifecycleState) -> ContentItem:
        if not self.can_transition(item, new_state):
            logger.warning("Cannot transition %s from %s to %s",
                           item.content_id, item.lifecycle_state.value, new_state.value)
            return item
        old = item.lifecycle_state
        item.lifecycle_state = new_state
        item.updated_at = utcnow()
        if new_state == ContentLifecycleState.REFRESHING:
            item.last_refreshed_at = utcnow()
        logger.info("Content %s: %s -> %s", item.content_id, old.value, new_state.value)
        return item

    def classify_lifecycle(self, item: ContentItem) -> ContentLifecycleState:
        if item.lifecycle_state in (ContentLifecycleState.DRAFT, ContentLifecycleState.PLANNED,
                                    ContentLifecycleState.PRODUCED, ContentLifecycleState.ARCHIVED):
            return item.lifecycle_state

        if not item.published_at:
            return item.lifecycle_state

        now = datetime.now(timezone.utc)
        try:
            pub_dt = datetime.fromisoformat(item.published_at.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return item.lifecycle_state

        age_days = (now - pub_dt).days

        if item.total_views == 0 and age_days > 7:
            return ContentLifecycleState.DECLINING

        if item.view_velocity > GROWING_VIEW_INCREASE_PCT:
            return ContentLifecycleState.GROWING

        if age_days >= EVERGREEN_MIN_DAYS and item.view_velocity >= -EVERGREEN_STABLE_VIEW_PCT:
            return ContentLifecycleState.EVERGREEN

        if age_days >= DECAY_THRESHOLD_DAYS and item.view_velocity < -DECAY_VIEW_DROP_PCT:
            return ContentLifecycleState.DECLINING

        return item.lifecycle_state

    def compute_freshness_score(self, item: ContentItem) -> float:
        if not item.published_at:
            return 1.0
        try:
            now = datetime.now(timezone.utc)
            pub_dt = datetime.fromisoformat(item.published_at.replace("Z", "+00:00"))
            age_days = (now - pub_dt).days
            if age_days <= 7:
                return 1.0
            elif age_days <= 30:
                return 0.8
            elif age_days <= 90:
                return 0.5
            elif age_days <= 180:
                return 0.3
            else:
                return 0.1
        except (ValueError, TypeError):
            return 0.5

    def compute_evergreen_score(self, item: ContentItem) -> float:
        if not item.published_at:
            return 0.0
        try:
            now = datetime.now(timezone.utc)
            pub_dt = datetime.fromisoformat(item.published_at.replace("Z", "+00:00"))
            age_days = (now - pub_dt).days
            if age_days < 14:
                return 0.0

            view_stability = max(0, 1.0 + item.view_velocity)
            age_bonus = min(age_days / 180, 1.0) * 0.3
            score = (view_stability * 0.7) + age_bonus
            return min(max(score, 0.0), 1.0)
        except (ValueError, TypeError):
            return 0.0

    def compute_decay_rate(self, item: ContentItem) -> float:
        if not item.published_at or item.total_views == 0:
            return 0.0
        try:
            now = datetime.now(timezone.utc)
            pub_dt = datetime.fromisoformat(item.published_at.replace("Z", "+00:00"))
            age_days = max((now - pub_dt).days, 1)
            views_per_day = item.total_views / age_days
            if views_per_day == 0:
                return 1.0
            recent_velocity = item.view_velocity
            if recent_velocity < 0:
                return min(abs(recent_velocity), 1.0)
            return 0.0
        except (ValueError, TypeError):
            return 0.0

    def compute_optimization_category(self, item: ContentItem) -> OptimizationCategory:
        if item.total_views == 0:
            return OptimizationCategory.FORGOTTEN

        if item.view_velocity > 0.5:
            return OptimizationCategory.VIRAL

        if item.evergreen_score > 0.6:
            return OptimizationCategory.EVERGREEN

        if item.view_velocity < -0.3:
            return OptimizationCategory.DECAYING

        if item.total_views > 1000 and item.ctr > 0.05:
            return OptimizationCategory.BEST_PERFORMING

        if item.total_views < 100 and item.published_at:
            try:
                now = datetime.now(timezone.utc)
                pub_dt = datetime.fromisoformat(item.published_at.replace("Z", "+00:00"))
                if (now - pub_dt).days > 30:
                    return OptimizationCategory.FORGOTTEN
            except (ValueError, TypeError):
                pass

        return OptimizationCategory.OPPORTUNITY

    def detect_needs_refresh(self, item: ContentItem) -> bool:
        if item.lifecycle_state in (ContentLifecycleState.DRAFT, ContentLifecycleState.PLANNED,
                                    ContentLifecycleState.ARCHIVED):
            return False
        freshness = self.compute_freshness_score(item)
        if freshness < 0.3:
            return True
        if item.last_analyzed_at:
            try:
                now = datetime.now(timezone.utc)
                analyzed = datetime.fromisoformat(item.last_analyzed_at.replace("Z", "+00:00"))
                if (now - analyzed).days > STALE_ANALYSIS_DAYS:
                    return True
            except (ValueError, TypeError):
                pass
        if item.view_velocity < -0.5:
            return True
        return False

    def detect_archivable(self, items: list[ContentItem]) -> list[ContentItem]:
        archivable = []
        for item in items:
            if item.lifecycle_state == ContentLifecycleState.ARCHIVED:
                continue
            if self._should_archive(item):
                archivable.append(item)
        return archivable

    def _should_archive(self, item: ContentItem) -> bool:
        if item.total_views == 0 and item.published_at:
            try:
                now = datetime.now(timezone.utc)
                pub_dt = datetime.fromisoformat(item.published_at.replace("Z", "+00:00"))
                if (now - pub_dt).days > 90:
                    return True
            except (ValueError, TypeError):
                pass
        if item.view_velocity < -0.8 and item.freshness_score < 0.2:
            return True
        return False

    def update_item_scores(self, item: ContentItem) -> ContentItem:
        item.freshness_score = self.compute_freshness_score(item)
        item.evergreen_score = self.compute_evergreen_score(item)
        item.decay_rate = self.compute_decay_rate(item)
        item.optimization_category = self.compute_optimization_category(item).value
        item.updated_at = utcnow()
        return item
