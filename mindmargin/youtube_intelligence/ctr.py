import json
import logging
import uuid
from pathlib import Path
from typing import Optional

from mindmargin.config import settings
from mindmargin.youtube_intelligence.models import (
    CTRDataPoint, CTRReport, utcnow,
)

logger = logging.getLogger(__name__)


class CTROptimizer:
    def __init__(self, persist_dir: str = ""):
        root = Path(persist_dir or settings.storage.temp_root)
        self._dir = root / "youtube_intelligence" / "ctr"
        self._dir.mkdir(parents=True, exist_ok=True)

    def _save(self, report: CTRReport):
        path = self._dir / f"{report.report_id}.json"
        path.write_text(json.dumps(report.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

    def analyze_title_effectiveness(self, data_points: list[CTRDataPoint]) -> dict:
        if not data_points:
            return {"patterns": {}, "avg_ctr": 0}
        by_pattern = {}
        for dp in data_points:
            pattern = dp.title_pattern or "unknown"
            if pattern not in by_pattern:
                by_pattern[pattern] = {"total_ctr": 0, "count": 0, "best_ctr": 0}
            by_pattern[pattern]["total_ctr"] += dp.ctr_pct
            by_pattern[pattern]["count"] += 1
            by_pattern[pattern]["best_ctr"] = max(by_pattern[pattern]["best_ctr"], dp.ctr_pct)
        result = {}
        for pattern, stats in by_pattern.items():
            avg = stats["total_ctr"] / stats["count"] if stats["count"] > 0 else 0
            result[pattern] = {
                "avg_ctr": round(avg, 2),
                "count": stats["count"],
                "best_ctr": round(stats["best_ctr"], 2),
            }
        return {"patterns": result, "avg_ctr": round(sum(dp.ctr_pct for dp in data_points) / len(data_points), 2)}

    def analyze_thumbnail_effectiveness(self, data_points: list[CTRDataPoint]) -> dict:
        if not data_points:
            return {"styles": {}, "avg_ctr": 0}
        by_style = {}
        for dp in data_points:
            style = dp.thumbnail_style or "unknown"
            if style not in by_style:
                by_style[style] = {"total_ctr": 0, "count": 0, "best_ctr": 0}
            by_style[style]["total_ctr"] += dp.ctr_pct
            by_style[style]["count"] += 1
            by_style[style]["best_ctr"] = max(by_style[style]["best_ctr"], dp.ctr_pct)
        result = {}
        for style, stats in by_style.items():
            avg = stats["total_ctr"] / stats["count"] if stats["count"] > 0 else 0
            result[style] = {
                "avg_ctr": round(avg, 2),
                "count": stats["count"],
                "best_ctr": round(stats["best_ctr"], 2),
            }
        return {"styles": result, "avg_ctr": round(sum(dp.ctr_pct for dp in data_points) / len(data_points), 2)}

    def analyze_keyword_effectiveness(self, data_points: list[CTRDataPoint]) -> dict:
        if not data_points:
            return {"categories": {}, "avg_ctr": 0}
        by_cat = {}
        for dp in data_points:
            cat = dp.topic_category or "unknown"
            if cat not in by_cat:
                by_cat[cat] = {"total_ctr": 0, "count": 0}
            by_cat[cat]["total_ctr"] += dp.ctr_pct
            by_cat[cat]["count"] += 1
        result = {}
        for cat, stats in by_cat.items():
            avg = stats["total_ctr"] / stats["count"] if stats["count"] > 0 else 0
            result[cat] = {"avg_ctr": round(avg, 2), "count": stats["count"]}
        return {"categories": result, "avg_ctr": round(sum(dp.ctr_pct for dp in data_points) / len(data_points), 2)}

    def predict_ctr(self, title_pattern: str, thumbnail_style: str,
                    topic_category: str, historical_data: list[CTRDataPoint]) -> float:
        relevant = [dp for dp in historical_data
                    if dp.title_pattern == title_pattern or dp.thumbnail_style == thumbnail_style]
        if not relevant:
            return 5.0
        return round(sum(dp.ctr_pct for dp in relevant) / len(relevant), 2)

    def generate_recommendations(self, title_eff: dict, thumbnail_eff: dict,
                                  keyword_eff: dict) -> list[str]:
        recs = []
        patterns = title_eff.get("patterns", {})
        if patterns:
            best = max(patterns.items(), key=lambda x: x[1].get("avg_ctr", 0))
            worst = min(patterns.items(), key=lambda x: x[1].get("avg_ctr", 0))
            if best[0] != "unknown" and best[1]["avg_ctr"] > worst[1]["avg_ctr"] * 1.2:
                recs.append(f"Use '{best[0]}' title pattern (avg CTR: {best[1]['avg_ctr']:.1f}% vs worst: {worst[1]['avg_ctr']:.1f}%).")

        styles = thumbnail_eff.get("styles", {})
        if styles:
            best_style = max(styles.items(), key=lambda x: x[1].get("avg_ctr", 0))
            if best_style[0] != "unknown":
                recs.append(f"'{best_style[0]}' thumbnails perform best (avg CTR: {best_style[1]['avg_ctr']:.1f}%).")

        categories = keyword_eff.get("categories", {})
        if categories:
            best_cat = max(categories.items(), key=lambda x: x[1].get("avg_ctr", 0))
            worst_cat = min(categories.items(), key=lambda x: x[1].get("avg_ctr", 0))
            if best_cat[0] != worst_cat[0]:
                recs.append(f"'{best_cat[0]}' topics get better CTR ({best_cat[1]['avg_ctr']:.1f}%) than '{worst_cat[0]}' ({worst_cat[1]['avg_ctr']:.1f}%).")

        if not recs:
            recs.append("Collect more data points for better CTR analysis.")
        return recs

    def generate_report(self, data_points: list[dict]) -> CTRReport:
        points = [CTRDataPoint.from_dict(dp) if isinstance(dp, dict) else dp for dp in data_points]
        title_eff = self.analyze_title_effectiveness(points)
        thumb_eff = self.analyze_thumbnail_effectiveness(points)
        keyword_eff = self.analyze_keyword_effectiveness(points)
        recs = self.generate_recommendations(title_eff, thumb_eff, keyword_eff)

        ctrs = [dp.ctr_pct for dp in points] if points else [0]
        report = CTRReport(
            report_id=f"ctr_{uuid.uuid4().hex[:10]}",
            data_points=points,
            avg_ctr=round(sum(ctrs) / len(ctrs), 2),
            best_ctr=round(max(ctrs), 2),
            worst_ctr=round(min(ctrs), 2),
            title_effectiveness=title_eff,
            thumbnail_effectiveness=thumb_eff,
            keyword_effectiveness=keyword_eff,
            recommendations=recs,
            generated_at=utcnow(),
        )
        self._save(report)
        return report

    def get_latest(self) -> Optional[CTRReport]:
        files = sorted(self._dir.glob("ctr_*.json"), reverse=True)
        if not files:
            return None
        try:
            data = json.loads(files[0].read_text(encoding="utf-8"))
            return CTRReport.from_dict(data)
        except Exception:
            return None

    def list_reports(self, limit: int = 10) -> list[CTRReport]:
        reports = []
        for f in sorted(self._dir.glob("ctr_*.json"), reverse=True)[:limit]:
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                reports.append(CTRReport.from_dict(data))
            except Exception:
                continue
        return reports
