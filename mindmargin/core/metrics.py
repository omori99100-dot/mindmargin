"""Unified metrics and health report generation."""

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from mindmargin.core.storage import _safe_base, project_dir

logger = logging.getLogger(__name__)


class PipelineMetrics:
    """Collects and persists pipeline execution metrics.

    Generates ``metrics.json`` (machine-readable) and
    ``pipeline_health_report.md`` (human-readable) per pipeline.
    """

    def __init__(self, pipeline_id: str, topic: str = ""):
        self.pipeline_id = pipeline_id
        self.topic = topic
        self.data: dict[str, object] = {
            "pipeline_id": pipeline_id,
            "topic": topic,
            "started_at": datetime.utcnow().isoformat(),
            "stages": {},
            "cache": {"hits": 0, "misses": 0, "ratio": 0.0},
            "encoder": "",
            "retries": 0,
            "skipped_clips": 0,
            "output_size_mb": 0.0,
            "video_duration_s": 0.0,
            "publish_status": "",
            "youtube_video_id": "",
            "final_status": "",
        }

    def record_stage(self, name: str, duration_s: float, extra: Optional[dict] = None):
        entry: dict[str, object] = {"duration_s": round(duration_s, 2)}
        if extra:
            entry.update(extra)
        self.data["stages"][name] = entry  # type: ignore[index]

    def record_cache(self, hits: int, misses: int):
        total = hits + misses
        self.data["cache"] = {
            "hits": hits,
            "misses": misses,
            "ratio": round(hits / total, 3) if total else 0.0,
        }

    def record_encoder(self, encoder: str):
        self.data["encoder"] = encoder

    def record_retries(self, count: int):
        self.data["retries"] = count

    def record_skipped_clips(self, count: int):
        self.data["skipped_clips"] = count

    def record_publish(self, status: str, video_id: str = ""):
        self.data["publish_status"] = status
        if video_id:
            self.data["youtube_video_id"] = video_id

    def record_final_status(self, status: str):
        self.data["final_status"] = status

    def _gather_resource_usage(self):
        """Best-effort CPU/RAM measurement (cross-platform)."""
        try:
            import psutil
            proc = psutil.Process()
            with proc.oneshot():
                self.data["cpu_percent"] = proc.cpu_percent(interval=0.1)
                mem = proc.memory_info()
                self.data["ram_mb"] = round(mem.rss / 1048576, 1)
                self.data["peak_ram_mb"] = round(proc.memory_info().rss / 1048576, 1)
        except ImportError:
            pass
        except Exception:
            pass

    def save(self, output_dir: Optional[Path] = None):
        self._gather_resource_usage()
        self.data["completed_at"] = datetime.utcnow().isoformat()

        if output_dir is None:
            output_dir = project_dir(self.topic, self.pipeline_id)

        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Machine-readable JSON
        metrics_path = output_dir / "metrics.json"
        metrics_path.write_text(
            json.dumps(self.data, indent=2, default=str), encoding="utf-8")

        # Human-readable Markdown report
        report_path = output_dir / "pipeline_health_report.md"
        report_path.write_text(self._format_markdown(), encoding="utf-8")

        logger.info(f"Metrics: {metrics_path}")
        logger.info(f"Health report: {report_path}")

    def _format_markdown(self) -> str:
        d = self.data
        stages = d.get("stages", {})
        cache = d.get("cache", {})

        lines = [
            f"# Pipeline Health Report: `{d['pipeline_id']}`",
            "",
            f"**Topic:** {d.get('topic', 'N/A')}",
            f"**Status:** {d.get('final_status', 'N/A')}",
            f"**Duration:** {sum(s.get('duration_s', 0) for s in stages.values()):.1f}s total",
            f"**Encoder:** {d.get('encoder', 'N/A')}",
            "",
            "---",
            "",
            "## Stage Timing",
            "",
            "| Stage | Duration (s) | Notes |",
            "|-------|-------------|-------|",
        ]

        for name, info in stages.items():
            dur = info.get("duration_s", 0)
            extra = info.get("note", "")
            lines.append(f"| {name} | {dur:.1f} | {extra} |")

        lines += [
            "",
            "## Cache Efficiency",
            "",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Hits | {cache.get('hits', 0)} |",
            f"| Misses | {cache.get('misses', 0)} |",
            f"| Hit Ratio | {cache.get('ratio', 0)*100:.1f}% |",
            "",
        ]

        if d.get("retries", 0):
            lines += [
                "## Retries",
                "",
                f"Total retries: {d['retries']}",
                "",
            ]

        if d.get("publish_status"):
            lines += [
                "## Publishing",
                "",
                f"| Field | Value |",
                f"|-------|-------|",
                f"| Status | {d['publish_status']} |",
                f"| Video ID | {d.get('youtube_video_id', 'N/A')} |",
                "",
            ]

        lines += [
            "---",
            f"_Generated at {d.get('completed_at', 'N/A')}_",
        ]

        return "\n".join(lines)
