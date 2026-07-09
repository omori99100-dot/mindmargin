"""Thumbnail pipeline: auto-generate CTR-optimized thumbnail variants from video frames."""

import logging
import os
import random
import shutil
from pathlib import Path
from typing import Optional

from mindmargin.config import settings
from mindmargin.utils import ffmpeg

logger = logging.getLogger(__name__)

THUMBNAIL_STYLES = {
    "split_dark_light": {
        "bg_color": "#1a1a2e",
        "accent_color": "#e94560",
        "text_color": "white",
        "font_size": 48,
        "box": True,
    },
    "bottom_bar": {
        "bg_color": "#16213e",
        "accent_color": "#f5a623",
        "text_color": "white",
        "font_size": 42,
        "box": True,
    },
    "minimal": {
        "bg_color": "#0f0f0f",
        "accent_color": "#ffffff",
        "text_color": "white",
        "font_size": 56,
        "box": False,
    },
    "contrast_split": {
        "bg_color": "#2d2d2d",
        "accent_color": "#ff6b35",
        "text_color": "white",
        "font_size": 44,
        "box": True,
    },
}

FALLBACK_BG = (
    "color=c=#1a1a2e:s=1920x1080:d=0.1,"
    "drawbox=x=0:y=ih/2:w=iw:h=ih/2:c=#e94560:t=fill"
)


class ThumbnailAgent:
    """Generates CTR-optimized thumbnail variants using FFmpeg drawtext."""

    def __init__(self):
        self.name = "thumbnail"

    def run(self, topic: str, pipeline_id: str, script_data: dict) -> dict:
        from mindmargin.core.storage import ensure_dirs
        dirs = ensure_dirs(topic, pipeline_id)
        thumb_dir = dirs["thumbnails"]
        thumb_dir.mkdir(parents=True, exist_ok=True)

        best_title = script_data.get("best_title", topic)
        titles = script_data.get("titles", [best_title])
        variants = []

        # Use best_title as primary text — ensures topic consistency
        base_text = best_title

        for style_name, style in THUMBNAIL_STYLES.items():
            try:
                path = self._render_thumbnail(
                    thumb_dir, style_name, style, base_text, topic,
                )
                if path:
                    variants.append({
                        "path": str(path),
                        "style": style_name,
                        "text": base_text,
                    })
            except Exception as e:
                logger.warning(f"Thumbnail variant {style_name} failed: {e}")

        # Generate title-based variants using actual titles from script (first 3)
        for i, title in enumerate(titles[:3]):
            if title == base_text:
                continue  # skip duplicate of primary
            for style_name in ["minimal", "contrast_split"]:
                style = THUMBNAIL_STYLES[style_name]
                try:
                    path = self._render_thumbnail(
                        thumb_dir, f"{style_name}_t{i+1}", style, title, topic,
                    )
                    if path:
                        variants.append({
                            "path": str(path),
                            "style": f"{style_name}_t{i+1}",
                            "text": title,
                        })
                except Exception as e:
                    logger.warning(f"Thumbnail title variant {i} failed: {e}")

        # Score and rank variants using thumbnail_concepts if available
        thumbnail_concepts = script_data.get("thumbnail_concepts", [])
        if thumbnail_concepts:
            best_concept = max(
                thumbnail_concepts,
                key=lambda c: (c.get("emotion_score", 0) + c.get("curiosity_score", 0)) / 2
            )
            logger.info(f"Best thumbnail concept: emotion={best_concept.get('emotion_score')}, "
                       f"curiosity={best_concept.get('curiosity_score')}")

        manifest = {
            "topic": topic,
            "pipeline_id": pipeline_id,
            "variants_count": len(variants),
            "variants": variants,
            "primary": variants[0] if variants else {},
        }
        from mindmargin.core.storage import write_text
        import json
        write_text(thumb_dir / "thumbnail_manifest.json",
                   json.dumps(manifest, indent=2))

        logger.info(f"ThumbnailAgent: generated {len(variants)} variants, primary text: '{base_text[:50]}'")
        return {
            "agent": self.name,
            "status": "completed" if variants else "failed",
            "thumbnails": manifest,
        }

    def _render_thumbnail(
        self,
        output_dir: Path,
        style_name: str,
        style: dict,
        text: str,
        topic: str,
    ) -> Optional[Path]:
        text_short = text[:120].replace("'", "").replace(":", " ")
        safe_topic = "".join(c if c.isalnum() else "_" for c in topic)[:20]
        out_path = output_dir / f"thumb_{style_name}_{safe_topic}.png"

        w = settings.video.width
        h = settings.video.height
        bg = style["bg_color"]
        accent = style["accent_color"]
        font_color = style["text_color"]
        font_size = style["font_size"]
        use_box = style["box"]

        # Build the filter chain (applied to the color source input)
        filters = []

        if style_name == "split_dark_light":
            filters.append(
                f"drawbox=x=0:y={h//2}:w={w}:h={h//2}:c={accent}:t=fill"
            )
        elif style_name == "bottom_bar":
            filters.append(
                f"drawbox=x=0:y={h-120}:w={w}:h=120:c={accent}:t=fill"
            )

        # Draw the main text centered
        boxcolor = f"{accent}@0.5" if use_box else "black@0"
        text_filter = (
            f"drawtext=text='{text_short}':"
            f"fontcolor={font_color}:fontsize={font_size}:"
            f"x=(w-text_w)/2:y=(h-text_h)/2-40:"
            f"shadowcolor=black:shadowx=3:shadowy=3:"
            f"box={1 if use_box else 0}:boxcolor={boxcolor}:"
            f"boxborderw=12"
        )
        filters.append(text_filter)

        # Add topic as smaller footer text
        topic_safe = topic[:60].replace("'", "").replace(":", " ")
        topic_filter = (
            f"drawtext=text='{topic_safe}':"
            f"fontcolor=white:fontsize=24:"
            f"x=(w-text_w)/2:y=h-60:"
            f"shadowcolor=black:shadowx=2:shadowy=2"
        )
        filters.append(topic_filter)

        filter_complex = ",".join(filters)
        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi", "-i", f"color=c={bg}:s={w}x{h}:d=1:r=1",
            "-vf", filter_complex,
            "-frames:v", "1",
            str(out_path),
        ]

        if ffmpeg.run(cmd, desc=f"thumbnail: {style_name}"):
            return out_path
        return None


def pick_best_thumbnail(manifest: dict) -> Optional[str]:
    """Pick the primary thumbnail from a manifest (first variant)."""
    variants = manifest.get("variants", [])
    if variants:
        return variants[0].get("path")
    return None
