import hashlib
import json
import logging
import uuid
from pathlib import Path
from typing import Optional

from mindmargin.config import settings
from mindmargin.content.models import (
    ContentAsset, ContentItem, ContentVersion, AssetType,
    ContentLifecycleState, utcnow,
)

logger = logging.getLogger(__name__)


class ContentLibrary:
    def __init__(self, persist_dir: str = ""):
        root = Path(persist_dir or settings.storage.temp_root)
        self._lib_dir = root / "content" / "library"
        self._lib_dir.mkdir(parents=True, exist_ok=True)

    def _path_for(self, content_id: str) -> Path:
        safe = content_id.replace("/", "_").replace("\\", "_")
        return self._lib_dir / f"{safe}.json"

    def add_item(self, item: ContentItem) -> ContentItem:
        if not item.created_at:
            item.created_at = utcnow()
        item.updated_at = utcnow()
        self._save(item)
        logger.info("Library: added item '%s' (id=%s)", item.topic, item.content_id)
        return item

    def get_item(self, content_id: str) -> Optional[ContentItem]:
        path = self._path_for(content_id)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return ContentItem.from_dict(data)
        except Exception as e:
            logger.warning("Library: failed to load %s: %s", content_id, e)
            return None

    def update_item(self, item: ContentItem) -> ContentItem:
        item.updated_at = utcnow()
        self._save(item)
        return item

    def delete_item(self, content_id: str) -> bool:
        path = self._path_for(content_id)
        if path.exists():
            path.unlink()
            logger.info("Library: deleted item %s", content_id)
            return True
        return False

    def list_items(self, state: Optional[ContentLifecycleState] = None,
                   category: Optional[str] = None,
                   limit: int = 100) -> list[ContentItem]:
        items = []
        for p in sorted(self._lib_dir.glob("*.json")):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                item = ContentItem.from_dict(data)
                if state and item.lifecycle_state != state:
                    continue
                if category and item.category != category:
                    continue
                items.append(item)
                if len(items) >= limit:
                    break
            except Exception:
                continue
        return items

    def search_items(self, query: str, limit: int = 20) -> list[ContentItem]:
        q = query.lower()
        results = []
        for p in sorted(self._lib_dir.glob("*.json")):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                item = ContentItem.from_dict(data)
                if (q in item.topic.lower() or q in item.title.lower()
                        or q in item.description.lower()
                        or any(q in kw.lower() for kw in item.keywords)):
                    results.append(item)
                    if len(results) >= limit:
                        break
            except Exception:
                continue
        return results

    def count_by_state(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for p in self._lib_dir.glob("*.json"):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                state = data.get("lifecycle_state", "draft")
                counts[state] = counts.get(state, 0) + 1
            except Exception:
                continue
        return counts

    def count_by_category(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for p in self._lib_dir.glob("*.json"):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                cat = data.get("category", "uncategorized")
                counts[cat] = counts.get(cat, 0) + 1
            except Exception:
                continue
        return counts

    def get_all_keywords(self) -> dict[str, list[str]]:
        kw_map: dict[str, list[str]] = {}
        for p in self._lib_dir.glob("*.json"):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                cid = data.get("content_id", "")
                keywords = data.get("keywords", [])
                if cid and keywords:
                    kw_map[cid] = keywords
            except Exception:
                continue
        return kw_map

    def get_total_count(self) -> int:
        return len(list(self._lib_dir.glob("*.json")))

    def get_items_published_before(self, date_str: str) -> list[ContentItem]:
        items = []
        for p in sorted(self._lib_dir.glob("*.json")):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                item = ContentItem.from_dict(data)
                if item.published_at and item.published_at < date_str:
                    items.append(item)
            except Exception:
                continue
        return items

    def _save(self, item: ContentItem):
        path = self._path_for(item.content_id)
        path.write_text(json.dumps(item.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

    def import_from_pipeline(self, pipeline_id: str, topic: str, video_id: str = "",
                             title: str = "", description: str = "", tags: list[str] = None,
                             keywords: list[str] = None, category: str = "",
                             thumbnail_path: str = "", video_path: str = "",
                             script_path: str = "", analytics: dict = None) -> ContentItem:
        content_id = f"ci_{uuid.uuid4().hex[:12]}"
        item = ContentItem(
            content_id=content_id,
            topic=topic,
            lifecycle_state=ContentLifecycleState.PUBLISHED,
            published_at=utcnow(),
            last_analyzed_at=utcnow(),
            pipeline_id=pipeline_id,
            video_id=video_id,
            category=category,
            keywords=keywords or [],
            tags=tags or [],
            title=title or topic,
            description=description,
            thumbnail_path=thumbnail_path,
            video_path=video_path,
            script_path=script_path,
            analytics_snapshot=analytics or {},
            created_at=utcnow(),
            updated_at=utcnow(),
        )
        if analytics:
            item.total_views = analytics.get("views", 0)
            item.total_likes = analytics.get("likes", 0)
            item.total_comments = analytics.get("comments", 0)
            item.total_shares = analytics.get("shares", 0)
            item.ctr = analytics.get("ctr", 0.0)
            item.avg_view_duration_s = analytics.get("avg_view_duration_s", 0.0)
        self._save(item)
        logger.info("Library: imported pipeline %s as content %s", pipeline_id, content_id)
        return item
