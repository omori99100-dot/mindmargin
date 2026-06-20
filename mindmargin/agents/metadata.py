"""Metadata Engine: generate SEO titles, descriptions, tags, hashtags, chapters."""

import json
import logging
from datetime import datetime

from mindmargin.config import settings
from mindmargin.core.storage import ensure_dirs, write_text
from mindmargin.prompts import (
    TITLE_SYSTEM, TITLE_PROMPT,
    SEO_SYSTEM, SEO_PROMPT,
)

logger = logging.getLogger(__name__)

SECTION_NAMES = [
    ("hook", "The Hook", 0),
    ("rise", "The Rise", 1),
    ("first_crack", "The First Crack", 2),
    ("overconfidence_loop", "The Overconfidence Loop", 3),
    ("escalation", "Escalation", 4),
    ("collapse", "The Collapse", 5),
    ("twist", "The Twist", 6),
    ("lesson", "The Lesson", 7),
    ("close", "The Close", 8),
]


class MetadataAgent:
    """Generates full YouTube metadata package for a completed pipeline."""

    def __init__(self):
        self.name = "metadata"

    def run(self, topic: str, pipeline_id: str, script: dict) -> dict:
        logger.info(f"MetadataAgent: generating metadata for '{topic}'")

        sections = script.get("sections", [])
        titles = script.get("titles", [])
        hooks = script.get("hooks", [])
        best_title = titles[0] if titles else topic
        word_count = script.get("word_count", 0)
        seo = script.get("seo", {})

        # Build chapters from sections
        chapters = self._build_chapters(sections)

        # Build pinned comment with chapters
        pinned_comment = self._build_pinned_comment(topic, chapters)

        # Build hashtags
        hashtags = self._build_hashtags(topic)

        # Build description
        description = self._build_description(topic, best_title, seo, chapters, hashtags)

        # Enhance tags
        tags = list(dict.fromkeys(
            seo.get("tags", []) + [topic.lower().replace(" ", "")]
        ))

        metadata = {
            "topic": topic,
            "pipeline_id": pipeline_id,
            "best_title": best_title,
            "all_titles": titles[:5],
            "description": description,
            "tags": tags[:500],
            "hashtags": hashtags,
            "chapters": chapters,
            "pinned_comment": pinned_comment,
            "category_id": "27",
            "category_name": "Education",
            "privacy_status": "private",
            "generated_at": datetime.utcnow().isoformat(),
            "word_count": word_count,
        }

        dirs = ensure_dirs(topic, pipeline_id)
        write_text(dirs["script"] / "metadata.json", json.dumps(metadata, indent=2))

        return {
            "agent": self.name,
            "status": "completed",
            "metadata": metadata,
        }

    def _build_chapters(self, sections: list[dict]) -> list[dict]:
        """Build YouTube chapters from section timing."""
        chapters = []
        current_time = 0.0
        for sec in sections:
            dur = sec.get("duration_target_s", 60)
            title = sec.get("title", sec.get("name", ""))
            m, s = divmod(int(current_time), 60)
            timestamp = f"{m:02d}:{s:02d}"
            chapters.append({
                "timestamp": timestamp,
                "time_s": current_time,
                "title": title,
                "section_id": sec.get("section_id", 0),
            })
            current_time += dur
        return chapters

    def _build_pinned_comment(self, topic: str, chapters: list[dict]) -> str:
        """Build pinned comment with chapter markers."""
        lines = [f"{topic} - Chapter List:", ""]
        for ch in chapters:
            lines.append(f"{ch['timestamp']} - {ch['title']}")
        lines.append("")
        lines.append("Which section was most eye-opening? Let me know in the comments.")
        lines.append("")
        lines.append("#behavioraleconomics #businessautopsy")
        return "\n".join(lines)

    def _build_hashtags(self, topic: str) -> list[str]:
        tag = topic.lower().replace(" ", "").replace("-", "")[:30]
        base = [
            f"#{tag}",
            "#behavioraleconomics",
            "#businessautopsy",
            "#cognitivebiases",
            "#businessstory",
            "#documentary",
        ]
        return base

    def _build_description(self, topic: str, title: str, seo: dict,
                           chapters: list[dict], hashtags: list[str]) -> str:
        """Build SEO-optimized description with chapters and keywords."""
        desc_lines = [title, ""]
        # Existing SEO description
        existing = seo.get("description", "").strip()
        if existing:
            desc_lines.append(existing)
            desc_lines.append("")

        # Chapters
        desc_lines.append("⏱ CHAPTERS:")
        for ch in chapters:
            desc_lines.append(f"  {ch['timestamp']} - {ch['title']}")
        desc_lines.append("")

        # CTA
        desc_lines.append(
            "If you found this valuable, please like, subscribe, and hit the bell "
            "for more behavioral economics deep dives every week."
        )
        desc_lines.append("")

        # Hashtags
        desc_lines.append(" ".join(hashtags))

        return "\n".join(desc_lines)
