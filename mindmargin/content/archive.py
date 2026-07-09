import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from mindmargin.config import settings
from mindmargin.content.models import (
    ContentItem, ContentLifecycleState, utcnow,
)

logger = logging.getLogger(__name__)


class ContentArchiver:
    def __init__(self, persist_dir: str = ""):
        root = Path(persist_dir or settings.storage.temp_root)
        self._archive_dir = root / "content" / "archive"
        self._archive_dir.mkdir(parents=True, exist_ok=True)

    def archive_item(self, item: ContentItem, reason: str = "") -> ContentItem:
        item.lifecycle_state = ContentLifecycleState.ARCHIVED
        item.metadata["archived_at"] = utcnow()
        item.metadata["archive_reason"] = reason
        item.updated_at = utcnow()

        archive_record = {
            "content_id": item.content_id,
            "topic": item.topic,
            "pipeline_id": item.pipeline_id,
            "video_id": item.video_id,
            "published_at": item.published_at,
            "total_views": item.total_views,
            "total_likes": item.total_likes,
            "total_comments": item.total_comments,
            "total_shares": item.total_shares,
            "ctr": item.ctr,
            "avg_view_duration_s": item.avg_view_duration_s,
            "optimization_category": item.optimization_category,
            "archived_at": utcnow(),
            "reason": reason,
        }
        path = self._archive_dir / f"{item.content_id}.json"
        path.write_text(json.dumps(archive_record, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info("Archived content %s: %s", item.content_id, reason)
        return item

    def restore_item(self, item: ContentItem) -> ContentItem:
        item.lifecycle_state = ContentLifecycleState.PUBLISHED
        item.metadata.pop("archived_at", None)
        item.metadata.pop("archive_reason", None)
        item.updated_at = utcnow()

        path = self._archive_dir / f"{item.content_id}.json"
        if path.exists():
            path.unlink()
        logger.info("Restored content %s from archive", item.content_id)
        return item

    def get_archive_records(self, limit: int = 100) -> list[dict]:
        records = []
        for p in sorted(self._archive_dir.glob("*.json"), reverse=True):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                records.append(data)
                if len(records) >= limit:
                    break
            except Exception:
                continue
        return records

    def get_archive_stats(self) -> dict:
        records = self.get_archive_records(limit=1000)
        total_views = sum(r.get("total_views", 0) for r in records)
        total_likes = sum(r.get("total_likes", 0) for r in records)
        reasons = {}
        for r in records:
            reason = r.get("reason", "unknown")
            reasons[reason] = reasons.get(reason, 0) + 1
        return {
            "total_archived": len(records),
            "total_views_when_archived": total_views,
            "total_likes_when_archived": total_likes,
            "archive_reasons": reasons,
        }

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
        if item.decay_rate > 0.8 and item.evergreen_score < 0.2:
            return True
        return False
