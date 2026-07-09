import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from mindmargin.config import settings
from mindmargin.content.models import (
    ContentItem, Recommendation, RecommendationType, utcnow,
)

logger = logging.getLogger(__name__)

SEO_FRESHNESS_DAYS = 60
SEO_DECAY_VELOCITY = -0.2
TITLE_REFRESH_CTR_THRESHOLD = 0.03
THUMBNAIL_REFRESH_CTR_THRESHOLD = 0.02
KEYWORD_OVERLAP_THRESHOLD = 0.5


class SEORefreshEngine:
    def __init__(self, persist_dir: str = ""):
        root = Path(persist_dir or settings.storage.temp_root)
        self._seo_dir = root / "content" / "seo"
        self._seo_dir.mkdir(parents=True, exist_ok=True)

    def analyze_seo_score(self, item: ContentItem) -> float:
        score = 0.0
        if item.title:
            score += 0.2
        if item.description:
            score += 0.2
        if item.keywords:
            score += min(len(item.keywords) / 10, 0.2)
        if item.tags:
            score += min(len(item.tags) / 15, 0.15)
        if item.total_views > 0:
            ctr_score = min(item.ctr / 0.05, 0.15)
            score += ctr_score
        freshness = item.freshness_score
        score += freshness * 0.1
        return min(score, 1.0)

    def detect_title_refresh_needed(self, item: ContentItem) -> Optional[Recommendation]:
        if item.ctr > 0 and item.ctr < TITLE_REFRESH_CTR_THRESHOLD:
            return Recommendation(
                recommendation_id=f"rec_{uuid.uuid4().hex[:10]}",
                content_id=item.content_id,
                recommendation_type=RecommendationType.TITLE_REFRESH,
                priority=7,
                confidence=0.8,
                title=f"Refresh title for '{item.topic}'",
                description=f"CTR is {item.ctr:.1%}, below {TITLE_REFRESH_CTR_THRESHOLD:.1%} threshold",
                rationale="Low CTR indicates title may not be compelling enough",
                estimated_impact=0.6,
                action_data={"current_ctr": item.ctr, "current_title": item.title},
                created_at=utcnow(),
            )
        return None

    def detect_thumbnail_refresh_needed(self, item: ContentItem) -> Optional[Recommendation]:
        if item.ctr > 0 and item.ctr < THUMBNAIL_REFRESH_CTR_THRESHOLD:
            return Recommendation(
                recommendation_id=f"rec_{uuid.uuid4().hex[:10]}",
                content_id=item.content_id,
                recommendation_type=RecommendationType.THUMBNAIL_REPLACE,
                priority=7,
                confidence=0.7,
                title=f"Replace thumbnail for '{item.topic}'",
                description=f"CTR is {item.ctr:.1%}, below {THUMBNAIL_REFRESH_CTR_THRESHOLD:.1%} threshold",
                rationale="Low CTR may indicate thumbnail is not attracting clicks",
                estimated_impact=0.5,
                action_data={"current_ctr": item.ctr, "thumbnail_path": item.thumbnail_path},
                created_at=utcnow(),
            )
        return None

    def detect_seo_update_needed(self, item: ContentItem) -> Optional[Recommendation]:
        seo_score = self.analyze_seo_score(item)
        if seo_score < 0.4:
            return Recommendation(
                recommendation_id=f"rec_{uuid.uuid4().hex[:10]}",
                content_id=item.content_id,
                recommendation_type=RecommendationType.SEO_UPDATE,
                priority=6,
                confidence=0.7,
                title=f"Update SEO for '{item.topic}'",
                description=f"SEO score is {seo_score:.2f}, below 0.4 threshold",
                rationale="Content lacks basic SEO elements (title, description, keywords, tags)",
                estimated_impact=0.4,
                action_data={"current_seo_score": seo_score},
                created_at=utcnow(),
            )
        return None

    def detect_freshness_refresh_needed(self, item: ContentItem) -> Optional[Recommendation]:
        if item.freshness_score < 0.3 and item.lifecycle_state.value in ("published", "growing", "declining"):
            return Recommendation(
                recommendation_id=f"rec_{uuid.uuid4().hex[:10]}",
                content_id=item.content_id,
                recommendation_type=RecommendationType.SEO_UPDATE,
                priority=5,
                confidence=0.6,
                title=f"Refresh content freshness for '{item.topic}'",
                description=f"Freshness score is {item.freshness_score:.2f}, content may be outdated",
                rationale="Content is aging and may benefit from updated information",
                estimated_impact=0.3,
                action_data={"current_freshness": item.freshness_score},
                created_at=utcnow(),
            )
        return None

    def find_keyword_overlap(self, items: list[ContentItem]) -> list[dict]:
        keyword_to_items: dict[str, list[str]] = {}
        for item in items:
            for kw in item.keywords:
                kw_lower = kw.lower()
                keyword_to_items.setdefault(kw_lower, []).append(item.content_id)

        overlaps = []
        for kw, cids in keyword_to_items.items():
            if len(cids) > 1:
                overlaps.append({
                    "keyword": kw,
                    "content_ids": cids,
                    "count": len(cids),
                })
        overlaps.sort(key=lambda x: x["count"], reverse=True)
        return overlaps

    def find_duplicate_topics(self, items: list[ContentItem]) -> list[dict]:
        topic_map: dict[str, list[str]] = {}
        for item in items:
            normalized = item.topic.lower().strip()
            topic_map.setdefault(normalized, []).append(item.content_id)

        duplicates = []
        for topic, cids in topic_map.items():
            if len(cids) > 1:
                duplicates.append({
                    "topic": topic,
                    "content_ids": cids,
                    "count": len(cids),
                })
        return duplicates

    def generate_seo_report(self, items: list[ContentItem]) -> dict:
        scores = [self.analyze_seo_score(it) for it in items]
        avg_seo = sum(scores) / len(scores) if scores else 0
        low_seo = sum(1 for s in scores if s < 0.4)
        keyword_overlaps = self.find_keyword_overlap(items)
        duplicate_topics = self.find_duplicate_topics(items)

        return {
            "total_items": len(items),
            "avg_seo_score": round(avg_seo, 3),
            "low_seo_count": low_seo,
            "keyword_overlaps": len(keyword_overlaps),
            "duplicate_topics": len(duplicate_topics),
            "top_keyword_overlaps": keyword_overlaps[:10],
            "top_duplicate_topics": duplicate_topics[:10],
        }

    def _save_seo_data(self, content_id: str, data: dict):
        path = self._seo_dir / f"{content_id}.json"
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
