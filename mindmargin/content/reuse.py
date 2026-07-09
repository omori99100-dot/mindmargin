import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from mindmargin.content.models import (
    ContentItem, Recommendation, RecommendationType, utcnow,
)

logger = logging.getLogger(__name__)

KEYWORD_SIMILARITY_THRESHOLD = 0.5
TOPIC_SIMILARITY_THRESHOLD = 0.6
REUSE_COOLDOWN_DAYS = 30


class ContentReuseDetector:
    def __init__(self):
        pass

    def detect_duplicate_topics(self, items: list[ContentItem]) -> list[dict]:
        topic_groups: dict[str, list[ContentItem]] = {}
        for item in items:
            normalized = self._normalize_topic(item.topic)
            topic_groups.setdefault(normalized, []).append(item)

        duplicates = []
        for normalized_topic, group in topic_groups.items():
            if len(group) > 1:
                content_ids = [it.content_id for it in group]
                duplicates.append({
                    "topic": normalized_topic,
                    "content_ids": content_ids,
                    "count": len(content_ids),
                    "type": "duplicate_topic",
                })
        return duplicates

    def detect_keyword_overlap(self, items: list[ContentItem]) -> list[dict]:
        keyword_to_items: dict[str, list[str]] = {}
        for item in items:
            for kw in item.keywords:
                kw_lower = kw.lower().strip()
                keyword_to_items.setdefault(kw_lower, []).append(item.content_id)

        overlaps = []
        for kw, cids in keyword_to_items.items():
            unique_cids = list(set(cids))
            if len(unique_cids) > 1:
                overlaps.append({
                    "keyword": kw,
                    "content_ids": unique_cids,
                    "count": len(unique_cids),
                    "type": "keyword_overlap",
                })
        overlaps.sort(key=lambda x: x["count"], reverse=True)
        return overlaps

    def detect_reuse_opportunities(self, items: list[ContentItem]) -> list[Recommendation]:
        recommendations = []
        published = [it for it in items
                     if it.lifecycle_state.value in ("published", "growing", "evergreen")
                     and it.total_views > 200]

        for item in published:
            rec = self._check_reuse(item, items)
            if rec:
                recommendations.append(rec)
        return recommendations

    def detect_republish_candidates(self, items: list[ContentItem]) -> list[ContentItem]:
        candidates = []
        now = datetime.now(timezone.utc)
        for item in items:
            if item.lifecycle_state.value not in ("published", "declining"):
                continue
            if item.evergreen_score > 0.5 and item.view_velocity < 0:
                if item.last_refreshed_at:
                    try:
                        refresh_dt = datetime.fromisoformat(item.last_refreshed_at.replace("Z", "+00:00"))
                        if (now - refresh_dt).days >= REUSE_COOLDOWN_DAYS:
                            candidates.append(item)
                    except (ValueError, TypeError):
                        candidates.append(item)
                else:
                    candidates.append(item)
        return candidates

    def detect_playlist_update_needed(self, items: list[ContentItem]) -> list[Recommendation]:
        recommendations = []
        categories: dict[str, list[ContentItem]] = {}
        for item in items:
            if item.category:
                categories.setdefault(item.category, []).append(item)

        for cat, cat_items in categories.items():
            published = [it for it in cat_items if it.lifecycle_state.value in ("published", "growing", "evergreen")]
            if len(published) >= 3:
                recommendations.append(Recommendation(
                    recommendation_id=f"rec_reuse_{cat[:10]}",
                    content_id=published[0].content_id,
                    recommendation_type=RecommendationType.PLAYLIST_UPDATE,
                    priority=4,
                    confidence=0.7,
                    title=f"Update playlist for '{cat}'",
                    description=f"{len(published)} videos in '{cat}' could be organized into a playlist",
                    rationale="Multiple videos in same category suggest playlist opportunity",
                    estimated_impact=0.3,
                    action_data={"category": cat, "video_count": len(published)},
                    created_at=utcnow(),
                ))
        return recommendations

    def detect_internal_linking(self, items: list[ContentItem]) -> list[Recommendation]:
        recommendations = []
        keyword_items: dict[str, list[ContentItem]] = {}
        for item in items:
            for kw in item.keywords:
                keyword_items.setdefault(kw.lower(), []).append(item)

        for kw, related_items in keyword_items.items():
            if len(related_items) < 2:
                continue
            for item in related_items:
                other_ids = [it.content_id for it in related_items if it.content_id != item.content_id]
                if other_ids and not item.relationships:
                    recommendations.append(Recommendation(
                        recommendation_id=f"rec_link_{item.content_id[:8]}_{kw[:8]}",
                        content_id=item.content_id,
                        recommendation_type=RecommendationType.INTERNAL_LINKING,
                        priority=3,
                        confidence=0.5,
                        title=f"Add internal links for '{kw}'",
                        description=f"Link '{item.topic}' to {len(other_ids)} related content items",
                        rationale=f"Shared keyword '{kw}' indicates related content",
                        estimated_impact=0.2,
                        action_data={"keyword": kw, "related_content_ids": other_ids},
                        created_at=utcnow(),
                    ))
        return recommendations

    def _check_reuse(self, item: ContentItem, all_items: list[ContentItem]) -> Optional[Recommendation]:
        if item.reuse_history:
            last_reuse = item.reuse_history[-1]
            try:
                last_date = datetime.fromisoformat(last_reuse.get("date", "").replace("Z", "+00:00"))
                if (datetime.now(timezone.utc) - last_date).days < REUSE_COOLDOWN_DAYS:
                    return None
            except (ValueError, TypeError):
                pass

        if item.evergreen_score > 0.6 and item.total_views > 500:
            return Recommendation(
                recommendation_id=f"rec_reuse_{item.content_id[:10]}",
                content_id=item.content_id,
                recommendation_type=RecommendationType.RECYCLE,
                priority=6,
                confidence=0.7,
                title=f"Recycle '{item.topic}'",
                description=f"Evergreen content (score={item.evergreen_score:.2f}) with {item.total_views} views",
                rationale="High evergreen score and proven audience interest",
                estimated_impact=0.5,
                action_data={"evergreen_score": item.evergreen_score, "views": item.total_views},
                created_at=utcnow(),
            )
        return None

    def _normalize_topic(self, topic: str) -> str:
        return topic.lower().strip().replace("  ", " ")
