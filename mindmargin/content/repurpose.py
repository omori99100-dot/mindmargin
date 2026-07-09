import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from mindmargin.config import settings
from mindmargin.content.models import (
    ContentItem, RepurposeSuggestion, RepurposeFormat, utcnow,
)

logger = logging.getLogger(__name__)

REPURPOSE_RULES = [
    {
        "source_condition": {"min_duration_s": 300, "min_views": 500},
        "target_format": RepurposeFormat.SHORT,
        "confidence": 0.8,
        "effort": "low",
        "description": "Extract 30-60s highlight clips from long-form video",
    },
    {
        "source_condition": {"has_script": True, "min_word_count": 500},
        "target_format": RepurposeFormat.BLOG,
        "confidence": 0.7,
        "effort": "medium",
        "description": "Convert script to blog post with SEO optimization",
    },
    {
        "source_condition": {"has_script": True, "min_word_count": 300},
        "target_format": RepurposeFormat.NEWSLETTER,
        "confidence": 0.6,
        "effort": "low",
        "description": "Generate newsletter digest from script content",
    },
    {
        "source_condition": {"min_views": 1000, "min_likes": 50},
        "target_format": RepurposeFormat.TWITTER,
        "confidence": 0.7,
        "effort": "low",
        "description": "Create Twitter/X thread from key insights",
    },
    {
        "source_condition": {"min_views": 500, "category": "educational"},
        "target_format": RepurposeFormat.LINKEDIN,
        "confidence": 0.6,
        "effort": "medium",
        "description": "Adapt content for LinkedIn professional audience",
    },
    {
        "source_condition": {"min_views": 500},
        "target_format": RepurposeFormat.FACEBOOK,
        "confidence": 0.5,
        "effort": "low",
        "description": "Create Facebook post with video link",
    },
    {
        "source_condition": {"min_views": 200},
        "target_format": RepurposeFormat.TELEGRAM,
        "confidence": 0.5,
        "effort": "low",
        "description": "Create Telegram channel post",
    },
    {
        "source_condition": {"has_script": True, "min_word_count": 800},
        "target_format": RepurposeFormat.PODCAST_OUTLINE,
        "confidence": 0.5,
        "effort": "medium",
        "description": "Generate podcast outline from video script",
    },
    {
        "source_condition": {"min_views": 300, "engagement_rate": 0.03},
        "target_format": RepurposeFormat.COMMUNITY_POST,
        "confidence": 0.6,
        "effort": "low",
        "description": "Create community post to drive engagement",
    },
]


class ContentRepurposer:
    def __init__(self, persist_dir: str = ""):
        root = Path(persist_dir or settings.storage.temp_root)
        self._suggestions_dir = root / "content" / "repurpose"
        self._suggestions_dir.mkdir(parents=True, exist_ok=True)

    def generate_suggestions(self, item: ContentItem) -> list[RepurposeSuggestion]:
        suggestions = []
        for rule in REPURPOSE_RULES:
            if self._matches_condition(item, rule["source_condition"]):
                suggestion = RepurposeSuggestion(
                    suggestion_id=f"rps_{uuid.uuid4().hex[:10]}",
                    source_content_id=item.content_id,
                    target_format=rule["target_format"],
                    confidence=rule["confidence"],
                    title=self._generate_title(item, rule["target_format"]),
                    outline=rule["description"],
                    estimated_effort=rule["effort"],
                    estimated_impact=rule["confidence"] * 0.8,
                    created_at=utcnow(),
                )
                suggestions.append(suggestion)
        logger.info("Repurposer: generated %d suggestions for %s",
                     len(suggestions), item.content_id)
        return suggestions

    def save_suggestions(self, suggestions: list[RepurposeSuggestion]):
        for s in suggestions:
            path = self._suggestions_dir / f"{s.suggestion_id}.json"
            path.write_text(json.dumps(s.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

    def get_suggestions(self, content_id: Optional[str] = None,
                        target_format: Optional[RepurposeFormat] = None,
                        limit: int = 50) -> list[RepurposeSuggestion]:
        results = []
        for p in sorted(self._suggestions_dir.glob("*.json")):
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                s = RepurposeSuggestion.from_dict(data)
                if content_id and s.source_content_id != content_id:
                    continue
                if target_format and s.target_format != target_format:
                    continue
                results.append(s)
                if len(results) >= limit:
                    break
            except Exception:
                continue
        return results

    def get_suggestion(self, suggestion_id: str) -> Optional[RepurposeSuggestion]:
        path = self._suggestions_dir / f"{suggestion_id}.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return RepurposeSuggestion.from_dict(data)
        except Exception:
            return None

    def mark_actioned(self, suggestion_id: str, status: str = "actioned") -> bool:
        s = self.get_suggestion(suggestion_id)
        if not s:
            return False
        s.status = status
        path = self._suggestions_dir / f"{suggestion_id}.json"
        path.write_text(json.dumps(s.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
        return True

    def _matches_condition(self, item: ContentItem, condition: dict) -> bool:
        if "min_duration_s" in condition:
            duration = item.metadata.get("video_duration_s", 0)
            if duration < condition["min_duration_s"]:
                return False
        if "min_views" in condition:
            if item.total_views < condition["min_views"]:
                return False
        if "min_likes" in condition:
            if item.total_likes < condition["min_likes"]:
                return False
        if "has_script" in condition:
            if not item.script_path:
                return False
        if "min_word_count" in condition:
            word_count = item.metadata.get("word_count", 0)
            if word_count < condition["min_word_count"]:
                return False
        if "category" in condition:
            if item.category.lower() != condition["category"].lower():
                return False
        if "engagement_rate" in condition:
            if item.engagement_rate < condition["engagement_rate"]:
                return False
        return True

    def _generate_title(self, item: ContentItem, fmt: RepurposeFormat) -> str:
        topic = item.title or item.topic
        fmt_labels = {
            RepurposeFormat.SHORT: f"Short: {topic}",
            RepurposeFormat.TWITTER: f"Thread: {topic}",
            RepurposeFormat.LINKEDIN: f"LinkedIn: {topic}",
            RepurposeFormat.FACEBOOK: f"FB Post: {topic}",
            RepurposeFormat.TELEGRAM: f"TG Post: {topic}",
            RepurposeFormat.BLOG: f"Blog: {topic}",
            RepurposeFormat.NEWSLETTER: f"Newsletter: {topic}",
            RepurposeFormat.PODCAST_OUTLINE: f"Podcast: {topic}",
            RepurposeFormat.COMMUNITY_POST: f"Community: {topic}",
        }
        return fmt_labels.get(fmt, f"Repurpose: {topic}")
