import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from mindmargin.config import settings
from mindmargin.core.hardening import utcnow
from mindmargin.channel.models import ContentItem, ContentState

logger = logging.getLogger(__name__)


class ContentLifecycle:
    def __init__(self, persist_dir: str = ""):
        root = Path(persist_dir or settings.storage.temp_root)
        self._items_dir = root / "channel" / "content"
        self._items_dir.mkdir(parents=True, exist_ok=True)

    def create_item(self, topic: str, fmt: str, category: str,
                    priority: int = 5, confidence: float = 0.0,
                    opportunity_score: float = 0.0,
                    metadata: Optional[dict] = None) -> ContentItem:
        content_id = f"ch_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S_%f')}_{uuid.uuid4().hex[:6]}"
        from mindmargin.channel.models import ContentFormat
        item = ContentItem(
            content_id=content_id,
            topic=topic,
            format=ContentFormat(fmt) if isinstance(fmt, str) else fmt,
            category=category,
            state=ContentState.PLANNED,
            priority=priority,
            confidence=confidence,
            opportunity_score=opportunity_score,
            created_at=utcnow(),
            updated_at=utcnow(),
            metadata=metadata or {},
        )
        self._save(item)
        logger.info("Created content item '%s' (id=%s)", topic, content_id)
        return item

    def transition_to(self, content_id: str, new_state: ContentState) -> bool:
        item = self.get(content_id)
        if not item:
            logger.warning("Content item '%s' not found", content_id)
            return False
        if not item.can_transition_to(new_state):
            logger.warning("Cannot transition '%s' from %s to %s",
                           content_id, item.state.value, new_state.value)
            return False
        old_state = item.state
        item.state = new_state
        item.updated_at = utcnow()
        if new_state == ContentState.SCHEDULED and not item.scheduled_at:
            item.scheduled_at = utcnow()
        self._save(item)
        logger.info("Content '%s': %s -> %s", content_id, old_state.value, new_state.value)
        return True

    def get(self, content_id: str) -> Optional[ContentItem]:
        p = self._path_for(content_id)
        if not p.exists():
            return None
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            return ContentItem.from_dict(d)
        except Exception as e:
            logger.warning("Failed to load content item '%s': %s", content_id, e)
            return None

    def list_by_state(self, state: ContentState) -> list[ContentItem]:
        return [item for item in self.list_all() if item.state == state]

    def list_by_states(self, states: list[ContentState]) -> list[ContentItem]:
        state_set = set(states)
        return [item for item in self.list_all() if item.state in state_set]

    def list_all(self) -> list[ContentItem]:
        items = []
        for f in sorted(self._items_dir.glob("*.json"), reverse=True):
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
                items.append(ContentItem.from_dict(d))
            except Exception as e:
                logger.warning("Failed to load content file '%s': %s", f.name, e)
        return items

    def search_by_topic(self, topic: str) -> list[ContentItem]:
        lower = topic.lower()
        return [item for item in self.list_all() if lower in item.topic.lower()]

    def update_item(self, content_id: str, **kwargs) -> bool:
        item = self.get(content_id)
        if not item:
            return False
        for key, value in kwargs.items():
            if hasattr(item, key):
                setattr(item, key, value)
        item.updated_at = utcnow()
        self._save(item)
        return True

    def delete(self, content_id: str) -> bool:
        p = self._path_for(content_id)
        if p.exists():
            p.unlink()
            return True
        return False

    def count_by_state(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in self.list_all():
            s = item.state.value
            counts[s] = counts.get(s, 0) + 1
        return counts

    def _path_for(self, content_id: str) -> Path:
        return self._items_dir / f"{content_id}.json"

    def _save(self, item: ContentItem):
        self._path_for(item.content_id).write_text(
            json.dumps(item.to_dict(), indent=2), encoding="utf-8",
        )
