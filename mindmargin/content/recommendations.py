import json
import logging
import uuid
from pathlib import Path
from typing import Optional

from mindmargin.config import settings
from mindmargin.content.models import (
    ContentItem, Recommendation, RecommendationType,
    ContentLifecycleState, utcnow,
)
from mindmargin.content.lifecycle import ContentLifecycleManager
from mindmargin.content.optimizer import ContentOptimizer
from mindmargin.content.seo_refresh import SEORefreshEngine
from mindmargin.content.reuse import ContentReuseDetector
from mindmargin.content.archive import ContentArchiver

logger = logging.getLogger(__name__)


class RecommendationEngine:
    def __init__(self, persist_dir: str = ""):
        root = Path(persist_dir or settings.storage.temp_root)
        self._recs_dir = root / "content" / "recommendations"
        self._recs_dir.mkdir(parents=True, exist_ok=True)

        self.lifecycle = ContentLifecycleManager()
        self.optimizer = ContentOptimizer()
        self.seo = SEORefreshEngine(persist_dir=persist_dir)
        self.reuse = ContentReuseDetector()
        self.archiver = ContentArchiver(persist_dir=persist_dir)

    def generate_all_recommendations(self, items: list[ContentItem]) -> list[Recommendation]:
        all_recs: list[Recommendation] = []

        for item in items:
            item_recs = self._generate_for_item(item)
            all_recs.extend(item_recs)

        cross_recs = self._generate_cross_item_recommendations(items)
        all_recs.extend(cross_recs)

        all_recs.sort(key=lambda r: (r.priority, r.confidence), reverse=True)
        self._save_recommendations(all_recs)
        logger.info("RecommendationEngine: generated %d total recommendations", len(all_recs))
        return all_recs

    def _generate_for_item(self, item: ContentItem) -> list[Recommendation]:
        recs = []

        title_rec = self.seo.detect_title_refresh_needed(item)
        if title_rec:
            recs.append(title_rec)

        thumb_rec = self.seo.detect_thumbnail_refresh_needed(item)
        if thumb_rec:
            recs.append(thumb_rec)

        seo_rec = self.seo.detect_seo_update_needed(item)
        if seo_rec:
            recs.append(seo_rec)

        freshness_rec = self.seo.detect_freshness_refresh_needed(item)
        if freshness_rec:
            recs.append(freshness_rec)

        if self.lifecycle.detect_needs_refresh(item):
            recs.append(Recommendation(
                recommendation_id=f"rec_{uuid.uuid4().hex[:10]}",
                content_id=item.content_id,
                recommendation_type=RecommendationType.REPURPOSE,
                priority=5,
                confidence=0.6,
                title=f"Refresh content: '{item.topic}'",
                description="Content needs updating based on freshness and velocity analysis",
                rationale="Combination of declining metrics and stale analysis",
                estimated_impact=0.4,
                created_at=utcnow(),
            ))

        if self.archiver.detect_archivable([item]):
            recs.append(Recommendation(
                recommendation_id=f"rec_{uuid.uuid4().hex[:10]}",
                content_id=item.content_id,
                recommendation_type=RecommendationType.ARCHIVE,
                priority=3,
                confidence=0.7,
                title=f"Archive '{item.topic}'",
                description="Content meets archival criteria (zero views + old, or severe decay)",
                rationale="Content is not providing value and should be archived",
                estimated_impact=0.1,
                created_at=utcnow(),
            ))

        if item.video_path and item.metadata.get("video_duration_s", 0) > 300:
            recs.append(Recommendation(
                recommendation_id=f"rec_{uuid.uuid4().hex[:10]}",
                content_id=item.content_id,
                recommendation_type=RecommendationType.CREATE_SHORT,
                priority=5,
                confidence=0.7,
                title=f"Create Short from '{item.topic}'",
                description="Long-form video can be repurposed into Shorts",
                rationale="Videos over 5 minutes are good candidates for Short extraction",
                estimated_impact=0.5,
                action_data={"duration_s": item.metadata.get("video_duration_s", 0)},
                created_at=utcnow(),
            ))

        if item.script_path and item.metadata.get("word_count", 0) > 500:
            recs.append(Recommendation(
                recommendation_id=f"rec_{uuid.uuid4().hex[:10]}",
                content_id=item.content_id,
                recommendation_type=RecommendationType.CREATE_ARTICLE,
                priority=4,
                confidence=0.6,
                title=f"Create article from '{item.topic}'",
                description="Script has enough content for a blog article",
                rationale="Script word count supports article generation",
                estimated_impact=0.3,
                action_data={"word_count": item.metadata.get("word_count", 0)},
                created_at=utcnow(),
            ))

        if item.total_views > 500:
            recs.append(Recommendation(
                recommendation_id=f"rec_{uuid.uuid4().hex[:10]}",
                content_id=item.content_id,
                recommendation_type=RecommendationType.GENERATE_NEWSLETTER,
                priority=3,
                confidence=0.5,
                title=f"Generate newsletter from '{item.topic}'",
                description=f"Content has {item.total_views} views, suitable for newsletter",
                rationale="Popular content performs well in newsletters",
                estimated_impact=0.2,
                created_at=utcnow(),
            ))

        if item.total_views > 300 and item.engagement_rate > 0.03:
            recs.append(Recommendation(
                recommendation_id=f"rec_{uuid.uuid4().hex[:10]}",
                content_id=item.content_id,
                recommendation_type=RecommendationType.SOCIAL_SNIPPET,
                priority=4,
                confidence=0.6,
                title=f"Create social snippets for '{item.topic}'",
                description="High engagement content suitable for social media",
                rationale="Strong engagement indicates shareable content",
                estimated_impact=0.3,
                created_at=utcnow(),
            ))

        if item.total_views > 200 and item.engagement_rate > 0.02:
            recs.append(Recommendation(
                recommendation_id=f"rec_{uuid.uuid4().hex[:10]}",
                content_id=item.content_id,
                recommendation_type=RecommendationType.COMMUNITY_POST,
                priority=3,
                confidence=0.5,
                title=f"Create community post for '{item.topic}'",
                description="Engaging content can drive community interaction",
                rationale="Community posts boost channel engagement",
                estimated_impact=0.2,
                created_at=utcnow(),
            ))

        return recs

    def _generate_cross_item_recommendations(self, items: list[ContentItem]) -> list[Recommendation]:
        recs = []

        dupes = self.reuse.detect_duplicate_topics(items)
        for dupe in dupes:
            recs.append(Recommendation(
                recommendation_id=f"rec_dup_{uuid.uuid4().hex[:8]}",
                content_id=dupe["content_ids"][0],
                recommendation_type=RecommendationType.DUPLICATE_DETECTION,
                priority=6,
                confidence=0.8,
                title=f"Duplicate topic detected: '{dupe['topic']}'",
                description=f"{dupe['count']} items share the same topic",
                rationale="Duplicate topics may cannibalize each other's performance",
                estimated_impact=0.4,
                action_data=dupe,
                created_at=utcnow(),
            ))

        overlaps = self.seo.find_keyword_overlap(items)
        for overlap in overlaps[:10]:
            if overlap["count"] > 2:
                recs.append(Recommendation(
                    recommendation_id=f"rec_kw_{uuid.uuid4().hex[:8]}",
                    content_id=overlap["content_ids"][0],
                    recommendation_type=RecommendationType.KEYWORD_OVERLAP,
                    priority=5,
                    confidence=0.7,
                    title=f"Keyword overlap: '{overlap['keyword']}'",
                    description=f"{overlap['count']} items target the same keyword",
                    rationale="Keyword overlap may cause internal competition",
                    estimated_impact=0.3,
                    action_data=overlap,
                    created_at=utcnow(),
                ))

        playlist_recs = self.reuse.detect_playlist_update_needed(items)
        recs.extend(playlist_recs)

        linking_recs = self.reuse.detect_internal_linking(items)
        recs.extend(linking_recs)

        return recs

    def get_recommendations(self, content_id: Optional[str] = None,
                            rec_type: Optional[RecommendationType] = None,
                            status: str = "pending",
                            limit: int = 50) -> list[Recommendation]:
        results = []
        for p in sorted(self._recs_dir.glob("*.json"), reverse=True):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                rec = Recommendation.from_dict(data)
                if content_id and rec.content_id != content_id:
                    continue
                if rec_type and rec.recommendation_type != rec_type:
                    continue
                if status and rec.status != status:
                    continue
                results.append(rec)
                if len(results) >= limit:
                    break
            except Exception:
                continue
        return results

    def get_recommendation(self, recommendation_id: str) -> Optional[Recommendation]:
        for p in self._recs_dir.glob("*.json"):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                rec = Recommendation.from_dict(data)
                if rec.recommendation_id == recommendation_id:
                    return rec
            except Exception:
                continue
        return None

    def mark_actioned(self, recommendation_id: str, status: str = "actioned") -> bool:
        for p in self._recs_dir.glob("*.json"):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                rec = Recommendation.from_dict(data)
                if rec.recommendation_id == recommendation_id:
                    rec.status = status
                    rec.acted_at = utcnow()
                    p.write_text(json.dumps(rec.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
                    return True
            except Exception:
                continue
        return False

    def get_recommendation_stats(self) -> dict:
        all_recs = self.get_recommendations(status=None, limit=1000)
        by_type: dict[str, int] = {}
        by_status: dict[str, int] = {}
        for rec in all_recs:
            t = rec.recommendation_type.value
            by_type[t] = by_type.get(t, 0) + 1
            by_status[rec.status] = by_status.get(rec.status, 0) + 1

        return {
            "total": len(all_recs),
            "by_type": by_type,
            "by_status": by_status,
            "pending": by_status.get("pending", 0),
            "actioned": by_status.get("actioned", 0),
        }

    def _save_recommendations(self, recs: list[Recommendation]):
        for rec in recs:
            path = self._recs_dir / f"{rec.recommendation_id}.json"
            path.write_text(json.dumps(rec.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
