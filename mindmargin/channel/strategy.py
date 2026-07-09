import logging
from datetime import datetime, timezone
from typing import Optional

from mindmargin.analytics.memory import (
    get_pipeline_history,
    get_top_opportunities,
    get_execution_log,
)
from mindmargin.channel.models import ContentFormat, ContentItem, ContentState
from mindmargin.channel.lifecycle import ContentLifecycle

logger = logging.getLogger(__name__)

CATEGORIES = [
    "business_failure",
    "corruption",
    "financial_crisis",
    "startup_failure",
    "tech_disruption",
    "fraud",
    "regulatory_failure",
    "industry_disruption",
    "cultural_phenomenon",
    "legal_battle",
    "scandal",
    "market_collapse",
]

FORMAT_WEIGHTS = {
    ContentFormat.SHORT: 0.3,
    ContentFormat.LONG: 0.7,
}


class ChannelStrategy:
    def __init__(self, lifecycle: Optional[ContentLifecycle] = None):
        self._lifecycle = lifecycle or ContentLifecycle()

    def select_topics(self, limit: int = 20) -> list[dict]:
        try:
            opportunities = get_top_opportunities(n=limit)
            if opportunities:
                return opportunities
        except Exception as e:
            logger.warning("Failed to get opportunities: %s", e)
        return []

    def detect_duplicates(self, topic: str) -> list[dict]:
        lower = topic.lower()
        duplicates = []
        try:
            for pipe in get_pipeline_history(100):
                existing = (pipe.get("topic") or "").lower()
                if existing and (lower in existing or existing in lower):
                    duplicates.append({"topic": pipe.get("topic", ""), "source": "pipeline_history"})
        except Exception as e:
            logger.warning("Failed to check pipeline duplicates: %s", e)
        try:
            for log in get_execution_log(100):
                existing = (log.get("topic") or "").lower()
                if existing and (lower in existing or existing in lower):
                    duplicates.append({"topic": log.get("topic", ""), "source": "execution_log"})
        except Exception as e:
            logger.warning("Failed to check execution log duplicates: %s", e)
        planned = self._lifecycle.search_by_topic(topic)
        for item in planned:
            if item.state != ContentState.ARCHIVED:
                duplicates.append({"topic": item.topic, "source": "planned_content"})
        return duplicates

    def balance_formats(self, items: list[ContentItem]) -> list[ContentItem]:
        if not items:
            return items
        all_items = [item for item in self._lifecycle.list_all() if item.state != ContentState.ARCHIVED]
        current_shorts = sum(1 for i in all_items if i.format == ContentFormat.SHORT)
        current_long = sum(1 for i in all_items if i.format == ContentFormat.LONG)
        total = current_shorts + current_long or 1
        short_ratio = current_shorts / total

        target_short = FORMAT_WEIGHTS.get(ContentFormat.SHORT, 0.3)
        shorts = [i for i in items if i.format == ContentFormat.SHORT]
        longs = [i for i in items if i.format == ContentFormat.LONG]

        if short_ratio >= target_short:
            shorts = shorts[:max(1, len(items) // 4)]
        else:
            longs = longs[:max(1, len(items) // 2)]

        result = shorts + longs
        result.sort(key=lambda x: x.opportunity_score, reverse=True)
        return result

    def rotate_categories(self, items: list[ContentItem]) -> list[ContentItem]:
        if not items:
            return items
        all_items = self._lifecycle.list_all()
        published_categories = {}
        for item in all_items:
            if item.is_published:
                published_categories[item.category] = published_categories.get(item.category, 0) + 1

        if not published_categories:
            return items

        sorted_cats = sorted(published_categories.items(), key=lambda x: x[1])

        def category_score(item: ContentItem) -> float:
            count = published_categories.get(item.category, 0)
            return -count

        items.sort(key=category_score)
        return items

    def estimate_format(self, opportunity: dict) -> ContentFormat:
        opportunity_score = opportunity.get("opportunity_score", 0) or 0
        evergreen_score = opportunity.get("evergreen_score", 0) or 0
        confidence = opportunity.get("confidence", 0) or 0
        novelty = opportunity.get("novelty", 0) or 0

        composite = (evergreen_score * 0.3 + confidence * 0.3 + novelty * 0.2 + opportunity_score / 100 * 0.2)
        return ContentFormat.LONG if composite > 0.5 else ContentFormat.SHORT

    def assign_category(self, topic: str) -> str:
        lower = topic.lower()
        for cat in CATEGORIES:
            words = cat.replace("_", " ")
            if any(w in lower for w in words.split()):
                return cat
        import hashlib
        idx = int(hashlib.md5(topic.encode()).hexdigest(), 16) % len(CATEGORIES)
        return CATEGORIES[idx]

    def build_content_plan(self, opportunities: list[dict]) -> list[ContentItem]:
        items = []
        for opp in opportunities:
            topic = opp.get("topic", "").strip()
            if not topic:
                continue
            duplicates = self.detect_duplicates(topic)
            if any(d["source"] != "planned_content" for d in duplicates):
                continue
            fmt = self.estimate_format(opp)
            category = self.assign_category(topic)
            confidence = opp.get("confidence", 0) or 0
            opportunity_score = opp.get("opportunity_score", 0) or 0
            priority = max(1, min(10, int(opportunity_score / 10)))
            try:
                item = self._lifecycle.create_item(
                    topic=topic, fmt=fmt.value, category=category,
                    priority=priority, confidence=confidence,
                    opportunity_score=opportunity_score,
                    metadata={"source": opp.get("source", "intelligence"), "strategy": "automated"},
                )
                items.append(item)
            except Exception as e:
                logger.warning("Failed to create content item for '%s': %s", topic, e)
        return items
