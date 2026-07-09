import json
import logging
import uuid
from pathlib import Path
from typing import Optional

from mindmargin.config import settings
from mindmargin.youtube_intelligence.models import (
    RetentionAnalysis, RetentionDataPoint, RetentionPattern, utcnow,
)

logger = logging.getLogger(__name__)


class RetentionAnalyzer:
    def __init__(self, persist_dir: str = ""):
        root = Path(persist_dir or settings.storage.temp_root)
        self._dir = root / "youtube_intelligence" / "retention"
        self._dir.mkdir(parents=True, exist_ok=True)

    def _save(self, analysis: RetentionAnalysis):
        path = self._dir / f"{analysis.analysis_id}.json"
        path.write_text(json.dumps(analysis.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

    def detect_hook_strength(self, data_points: list[RetentionDataPoint]) -> tuple[float, list[RetentionPattern]]:
        if not data_points:
            return 0.0, []
        patterns = []
        first_point = data_points[0]
        early_points = [p for p in data_points if p.timestamp_pct <= 10 and p.timestamp_pct > 0]
        if not early_points:
            hook_drop = 0
        else:
            hook_drop = first_point.retention_pct - early_points[0].retention_pct
        if hook_drop < 10:
            patterns.append(RetentionPattern.STRONG_HOOK)
            score = 90 + (10 - hook_drop)
        elif hook_drop < 25:
            score = 60 + (25 - hook_drop)
        else:
            patterns.append(RetentionPattern.WEAK_INTRO)
            score = max(10, 50 - hook_drop)
        return min(score, 100), patterns

    def detect_drop_offs(self, data_points: list[RetentionDataPoint]) -> list[dict]:
        drop_offs = []
        for i in range(1, len(data_points)):
            prev = data_points[i - 1]
            curr = data_points[i]
            drop = prev.retention_pct - curr.retention_pct
            if drop > 5:
                drop_offs.append({
                    "timestamp_pct": curr.timestamp_pct,
                    "drop_magnitude": round(drop, 1),
                    "retention_after": round(curr.retention_pct, 1),
                    "pattern": "sudden_drop" if drop > 15 else "gradual_drop",
                })
        return drop_offs

    def detect_strong_endings(self, data_points: list[RetentionDataPoint]) -> list[dict]:
        endings = []
        last_points = [p for p in data_points if p.timestamp_pct >= 85]
        if len(last_points) >= 2:
            first = last_points[0]
            last = last_points[-1]
            if last.retention_pct >= first.retention_pct * 0.85:
                endings.append({
                    "retention_range": f"{first.timestamp_pct:.0f}%-{last.timestamp_pct:.0f}%",
                    "retention_level": round(last.retention_pct, 1),
                    "strength": "strong" if last.retention_pct > 40 else "moderate",
                })
        return endings

    def detect_patterns(self, data_points: list[RetentionDataPoint]) -> list[RetentionPattern]:
        patterns = []
        hook_score, hook_patterns = self.detect_hook_strength(data_points)
        patterns.extend(hook_patterns)

        drop_offs = self.detect_drop_offs(data_points)
        sudden = [d for d in drop_offs if d["pattern"] == "sudden_drop"]
        gradual = [d for d in drop_offs if d["pattern"] == "gradual_drop"]
        if sudden:
            patterns.append(RetentionPattern.SUDDEN_DROP)
        if gradual:
            patterns.append(RetentionPattern.GRADUAL_DROP)

        endings = self.detect_strong_endings(data_points)
        if endings:
            patterns.append(RetentionPattern.STRONG_ENDING)

        if not data_points:
            return patterns
        avg_ret = sum(p.retention_pct for p in data_points) / len(data_points)
        variance = sum((p.retention_pct - avg_ret) ** 2 for p in data_points) / len(data_points)
        if variance < 5:
            patterns.append(RetentionPattern.FLAT)

        recoveries = 0
        for i in range(2, len(data_points)):
            if (data_points[i].retention_pct > data_points[i - 1].retention_pct and
                    data_points[i - 1].retention_pct < data_points[i - 2].retention_pct):
                recoveries += 1
        if recoveries >= 2:
            patterns.append(RetentionPattern.RECOVERY)

        return patterns

    def compute_optimal_length(self, data_points: list[RetentionDataPoint],
                                video_lengths: list[dict] = None) -> float:
        if not data_points:
            return 600.0
        avg_ret = sum(p.retention_pct for p in data_points) / len(data_points)
        if avg_ret >= 60:
            return 900.0
        if avg_ret >= 45:
            return 720.0
        if avg_ret >= 30:
            return 600.0
        return 480.0

    def generate_script_recommendations(self, analysis: RetentionAnalysis) -> list[str]:
        recs = []
        if RetentionPattern.WEAK_INTRO in analysis.patterns:
            recs.append("Strengthen the hook: open with a bold claim, question, or visual surprise in the first 5 seconds.")
        if RetentionPattern.SUDDEN_DROP in analysis.patterns:
            drop_points = [d for d in analysis.drop_off_points if d["pattern"] == "sudden_drop"]
            for dp in drop_points[:3]:
                t = dp["timestamp_pct"]
                recs.append(f"At ~{t:.0f}% mark: add a pattern interrupt, visual change, or new information to re-engage.")
        if analysis.hook_strength_score < 50:
            recs.append("Use the 'Open Loop' technique: tease the payoff early and deliver later.")
        if analysis.ending_strength_score < 50:
            recs.append("End with a strong CTA and teaser for the next video to boost session time.")
        if RetentionPattern.FLAT in analysis.patterns:
            recs.append("Add more variation: change visual framing, use B-roll, or introduce a new sub-topic mid-video.")
        if not recs:
            recs.append("Retention is healthy. Focus on maintaining current script structure.")
        return recs

    def analyze_video(self, video_id: str, video_title: str,
                      data_points: list[dict],
                      video_length_seconds: float = 600) -> RetentionAnalysis:
        points = [RetentionDataPoint.from_dict(dp) if isinstance(dp, dict) else dp for dp in data_points]
        points.sort(key=lambda p: p.timestamp_pct)

        hook_score, hook_patterns = self.detect_hook_strength(points)
        drop_offs = self.detect_drop_offs(points)
        endings = self.detect_strong_endings(points)
        patterns = self.detect_patterns(points)
        optimal = self.compute_optimal_length(points)

        avg_ret = sum(p.retention_pct for p in points) / len(points) if points else 0
        ending_score = 80 if endings else 30

        analysis = RetentionAnalysis(
            analysis_id=f"ret_{uuid.uuid4().hex[:10]}",
            video_id=video_id,
            video_title=video_title,
            data_points=points,
            patterns=patterns,
            drop_off_points=drop_offs,
            strong_hooks=[{"score": hook_score}],
            strong_endings=endings,
            optimal_length_seconds=optimal,
            avg_retention_pct=round(avg_ret, 1),
            hook_strength_score=round(hook_score, 1),
            ending_strength_score=round(ending_score, 1),
            generated_at=utcnow(),
        )
        analysis.script_recommendations = self.generate_script_recommendations(analysis)
        self._save(analysis)
        return analysis

    def get_latest(self) -> Optional[RetentionAnalysis]:
        files = sorted(self._dir.glob("ret_*.json"), reverse=True)
        if not files:
            return None
        try:
            data = json.loads(files[0].read_text(encoding="utf-8"))
            return RetentionAnalysis.from_dict(data)
        except Exception:
            return None

    def list_analyses(self, limit: int = 10) -> list[RetentionAnalysis]:
        analyses = []
        for f in sorted(self._dir.glob("ret_*.json"), reverse=True)[:limit]:
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                analyses.append(RetentionAnalysis.from_dict(data))
            except Exception:
                continue
        return analyses
