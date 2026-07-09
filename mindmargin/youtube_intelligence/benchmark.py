import json
import logging
import uuid
from pathlib import Path
from typing import Optional

from mindmargin.config import settings
from mindmargin.youtube_intelligence.models import (
    BenchmarkReport, BenchmarkEntry, BenchmarkCategory, utcnow,
)

logger = logging.getLogger(__name__)


class BenchmarkEngine:
    def __init__(self, persist_dir: str = ""):
        root = Path(persist_dir or settings.storage.temp_root)
        self._dir = root / "youtube_intelligence" / "benchmarks"
        self._dir.mkdir(parents=True, exist_ok=True)

    def _save(self, report: BenchmarkReport):
        path = self._dir / f"{report.report_id}.json"
        path.write_text(json.dumps(report.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

    def _load_entries(self) -> list[BenchmarkEntry]:
        entries = []
        for f in self._dir.glob("entry_*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                entries.append(BenchmarkEntry.from_dict(data))
            except Exception:
                continue
        return entries

    def _save_entry(self, entry: BenchmarkEntry):
        path = self._dir / f"entry_{entry.entry_id}.json"
        path.write_text(json.dumps(entry.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

    def record_benchmark(self, category: BenchmarkCategory, metric_name: str,
                         metric_value: float, context: str = "",
                         source_video_id: str = "") -> BenchmarkEntry:
        entry = BenchmarkEntry(
            entry_id=f"bench_{uuid.uuid4().hex[:8]}",
            category=category,
            metric_name=metric_name,
            metric_value=metric_value,
            context=context,
            source_video_id=source_video_id,
            recorded_at=utcnow(),
        )
        self._save_entry(entry)
        return entry

    def get_best(self, category: BenchmarkCategory) -> Optional[BenchmarkEntry]:
        entries = self._load_entries()
        cat_entries = [e for e in entries if e.category == category]
        if not cat_entries:
            return None
        return max(cat_entries, key=lambda e: e.metric_value)

    def get_best_by_metric(self, metric_name: str) -> Optional[BenchmarkEntry]:
        entries = self._load_entries()
        matching = [e for e in entries if e.metric_name == metric_name]
        if not matching:
            return None
        return max(matching, key=lambda e: e.metric_value)

    def get_benchmarks_by_category(self) -> dict:
        entries = self._load_entries()
        result = {}
        for cat in BenchmarkCategory:
            cat_entries = [e for e in entries if e.category == cat]
            if cat_entries:
                best = max(cat_entries, key=lambda e: e.metric_value)
                avg = sum(e.metric_value for e in cat_entries) / len(cat_entries)
                result[cat.value] = {
                    "best_value": best.metric_value,
                    "best_context": best.context,
                    "best_video_id": best.source_video_id,
                    "avg_value": round(avg, 2),
                    "sample_count": len(cat_entries),
                    "recorded_at": best.recorded_at,
                }
        return result

    def compare_to_benchmark(self, category: BenchmarkCategory,
                              current_value: float) -> dict:
        best = self.get_best(category)
        if not best:
            return {"status": "no_benchmark", "current_value": current_value}
        diff = current_value - best.metric_value
        pct = (diff / best.metric_value * 100) if best.metric_value > 0 else 0
        return {
            "current_value": current_value,
            "benchmark_value": best.metric_value,
            "difference": round(diff, 2),
            "difference_pct": round(pct, 1),
            "status": "above_benchmark" if diff >= 0 else "below_benchmark",
            "best_context": best.context,
        }

    def record_from_video_data(self, video_data: dict) -> list[BenchmarkEntry]:
        entries = []
        if video_data.get("ctr_pct", 0) > 0:
            entries.append(self.record_benchmark(
                BenchmarkCategory.BEST_CTR, "ctr_pct", video_data["ctr_pct"],
                context=video_data.get("title", ""),
                source_video_id=video_data.get("video_id", ""),
            ))
        if video_data.get("watch_time_hours", 0) > 0:
            entries.append(self.record_benchmark(
                BenchmarkCategory.BEST_WATCH_TIME, "watch_time_hours",
                video_data["watch_time_hours"],
                context=video_data.get("title", ""),
                source_video_id=video_data.get("video_id", ""),
            ))
        if video_data.get("retention_pct", 0) > 0:
            entries.append(self.record_benchmark(
                BenchmarkCategory.BEST_RETENTION, "retention_pct",
                video_data["retention_pct"],
                context=video_data.get("title", ""),
                source_video_id=video_data.get("video_id", ""),
            ))
        if video_data.get("publish_time"):
            entries.append(self.record_benchmark(
                BenchmarkCategory.BEST_PUBLISHING_TIME, "publish_time",
                1.0,
                context=video_data["publish_time"],
                source_video_id=video_data.get("video_id", ""),
            ))
        if video_data.get("topic_category"):
            entries.append(self.record_benchmark(
                BenchmarkCategory.BEST_TOPIC_CATEGORY, "topic_category",
                video_data.get("views", 0),
                context=video_data["topic_category"],
                source_video_id=video_data.get("video_id", ""),
            ))
        return entries

    def generate_report(self) -> BenchmarkReport:
        by_cat = self.get_benchmarks_by_category()
        entries = self._load_entries()
        report = BenchmarkReport(
            report_id=f"bench_report_{uuid.uuid4().hex[:10]}",
            entries=entries[-50:],
            by_category=by_cat,
            summary=f"Tracking {len(entries)} benchmark entries across {len(by_cat)} categories.",
            generated_at=utcnow(),
        )
        self._save(report)
        return report

    def get_latest(self) -> Optional[BenchmarkReport]:
        files = sorted(self._dir.glob("bench_report_*.json"), reverse=True)
        if not files:
            return None
        try:
            data = json.loads(files[0].read_text(encoding="utf-8"))
            return BenchmarkReport.from_dict(data)
        except Exception:
            return None
