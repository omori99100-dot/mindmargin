import json
import logging
import uuid
from pathlib import Path
from typing import Optional

from mindmargin.config import settings
from mindmargin.youtube_intelligence.models import (
    AudienceProfile, AudienceInsight, TrendDirection, utcnow,
)

logger = logging.getLogger(__name__)


class AudienceIntelligence:
    def __init__(self, persist_dir: str = ""):
        root = Path(persist_dir or settings.storage.temp_root)
        self._dir = root / "youtube_intelligence" / "audience"
        self._dir.mkdir(parents=True, exist_ok=True)

    def _save(self, profile: AudienceProfile):
        path = self._dir / f"{profile.profile_id}.json"
        path.write_text(json.dumps(profile.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

    def analyze_best_upload_time(self, hourly_views: list[dict]) -> AudienceInsight:
        if not hourly_views:
            return AudienceInsight(
                insight_id=f"insight_{uuid.uuid4().hex[:8]}",
                category="timing", metric_name="best_upload_time",
                metric_value="unknown", confidence=0.0,
            )
        sorted_hours = sorted(hourly_views, key=lambda x: x.get("avg_views", 0), reverse=True)
        best = sorted_hours[0]
        avg = sum(h.get("avg_views", 0) for h in hourly_views) / len(hourly_views) if hourly_views else 1
        confidence = min(best.get("avg_views", 0) / avg, 1.0) if avg > 0 else 0.5
        return AudienceInsight(
            insight_id=f"insight_{uuid.uuid4().hex[:8]}",
            category="timing", metric_name="best_upload_time",
            metric_value=f"{best.get('hour', 12)}:00 UTC",
            confidence=round(confidence, 2),
            sample_size=sum(h.get("sample_count", 0) for h in hourly_views),
            recommendation=f"Upload around {best.get('hour', 12)}:00 UTC for maximum initial views.",
        )

    def analyze_best_upload_day(self, daily_views: list[dict]) -> AudienceInsight:
        if not daily_views:
            return AudienceInsight(
                insight_id=f"insight_{uuid.uuid4().hex[:8]}",
                category="timing", metric_name="best_upload_day",
                metric_value="unknown", confidence=0.0,
            )
        sorted_days = sorted(daily_views, key=lambda x: x.get("avg_views", 0), reverse=True)
        best = sorted_days[0]
        avg = sum(d.get("avg_views", 0) for d in daily_views) / len(daily_views) if daily_views else 1
        confidence = min(best.get("avg_views", 0) / avg, 1.0) if avg > 0 else 0.5
        return AudienceInsight(
            insight_id=f"insight_{uuid.uuid4().hex[:8]}",
            category="timing", metric_name="best_upload_day",
            metric_value=best.get("day", "unknown"),
            confidence=round(confidence, 2),
            sample_size=sum(d.get("sample_count", 0) for d in daily_views),
            recommendation=f"Publish on {best.get('day', 'unknown')}s for best performance.",
        )

    def analyze_geography(self, geo_data: list[dict]) -> AudienceInsight:
        if not geo_data:
            return AudienceInsight(
                insight_id=f"insight_{uuid.uuid4().hex[:8]}",
                category="demographics", metric_name="top_geography",
                metric_value="unknown", confidence=0.0,
            )
        sorted_geo = sorted(geo_data, key=lambda x: x.get("view_pct", 0), reverse=True)
        top = sorted_geo[0]
        return AudienceInsight(
            insight_id=f"insight_{uuid.uuid4().hex[:8]}",
            category="demographics", metric_name="top_geography",
            metric_value=top.get("country", "unknown"),
            confidence=top.get("view_pct", 0) / 100,
            sample_size=top.get("views", 0),
            recommendation=f"Tailor content for {top.get('country', 'unknown')} audience ({top.get('view_pct', 0):.0f}% of views).",
        )

    def analyze_devices(self, device_data: list[dict]) -> AudienceInsight:
        if not device_data:
            return AudienceInsight(
                insight_id=f"insight_{uuid.uuid4().hex[:8]}",
                category="devices", metric_name="primary_device",
                metric_value="unknown", confidence=0.0,
            )
        sorted_dev = sorted(device_data, key=lambda x: x.get("view_pct", 0), reverse=True)
        top = sorted_dev[0]
        return AudienceInsight(
            insight_id=f"insight_{uuid.uuid4().hex[:8]}",
            category="devices", metric_name="primary_device",
            metric_value=top.get("device", "unknown"),
            confidence=top.get("view_pct", 0) / 100,
            sample_size=top.get("views", 0),
            recommendation=f"Optimize for {top.get('device', 'unknown')} ({top.get('view_pct', 0):.0f}% of views).",
        )

    def analyze_returning_viewers(self, returning_pct: float) -> AudienceInsight:
        if returning_pct >= 40:
            rec = "Strong loyal audience. Focus on new viewer acquisition."
            trend = TrendDirection.RISING
        elif returning_pct >= 25:
            rec = "Healthy returning viewer base. Maintain consistency."
            trend = TrendDirection.STABLE
        else:
            rec = "Low returning viewers. Improve content consistency and end screens."
            trend = TrendDirection.DECLINING
        return AudienceInsight(
            insight_id=f"insight_{uuid.uuid4().hex[:8]}",
            category="loyalty", metric_name="returning_viewer_pct",
            metric_value=f"{returning_pct:.1f}%",
            confidence=0.9,
            trend=trend,
            recommendation=rec,
        )

    def analyze_session_duration(self, avg_session: float, target: float = 600) -> AudienceInsight:
        ratio = avg_session / target if target > 0 else 0
        if ratio >= 1.2:
            rec = "Excellent session duration. Viewers binge-watch your content."
            trend = TrendDirection.RISING
        elif ratio >= 0.8:
            rec = "Good session duration. Consider playlists and end screens."
            trend = TrendDirection.STABLE
        else:
            rec = "Low session duration. Improve content flow and add playlist hooks."
            trend = TrendDirection.DECLINING
        return AudienceInsight(
            insight_id=f"insight_{uuid.uuid4().hex[:8]}",
            category="engagement", metric_name="avg_session_duration",
            metric_value=f"{avg_session:.0f}s",
            confidence=0.85,
            trend=trend,
            recommendation=rec,
        )

    def analyze_loyal_segments(self, segment_data: list[dict]) -> list[AudienceInsight]:
        insights = []
        for seg in segment_data:
            insights.append(AudienceInsight(
                insight_id=f"insight_{uuid.uuid4().hex[:8]}",
                category="segments", metric_name=seg.get("name", "segment"),
                metric_value=f"{seg.get('view_pct', 0):.1f}%",
                confidence=seg.get("confidence", 0.5),
                sample_size=seg.get("viewer_count", 0),
                recommendation=f"Segment '{seg.get('name', 'unknown')}' represents {seg.get('view_pct', 0):.1f}% of audience.",
            ))
        return insights

    def build_profile(self, channel_data: dict) -> AudienceProfile:
        insights = []

        hourly = channel_data.get("hourly_views", [])
        if hourly:
            insights.append(self.analyze_best_upload_time(hourly))

        daily = channel_data.get("daily_views", [])
        if daily:
            insights.append(self.analyze_best_upload_day(daily))

        geo = channel_data.get("geography", [])
        if geo:
            insights.append(self.analyze_geography(geo))

        devices = channel_data.get("devices", [])
        if devices:
            insights.append(self.analyze_devices(devices))

        returning = channel_data.get("returning_viewer_pct", 20)
        insights.append(self.analyze_returning_viewers(returning))

        session = channel_data.get("avg_session_duration", 300)
        insights.append(self.analyze_session_duration(session))

        segments = channel_data.get("loyal_segments", [])
        insights.extend(self.analyze_loyal_segments(segments))

        best_time = next((i for i in insights if i.metric_name == "best_upload_time"), None)
        best_day = next((i for i in insights if i.metric_name == "best_upload_day"), None)

        profile = AudienceProfile(
            profile_id=f"aud_{uuid.uuid4().hex[:10]}",
            best_upload_time=best_time.metric_value if best_time else "",
            best_upload_day=best_day.metric_value if best_day else "",
            top_geographies=[g for g in channel_data.get("geography", [])[:5]],
            top_languages=[l for l in channel_data.get("languages", [])[:5]],
            device_breakdown=[d for d in channel_data.get("devices", [])[:5]],
            returning_viewer_pct=returning,
            subscriber_view_pct=channel_data.get("subscriber_view_pct", 0),
            avg_session_duration=session,
            audience_overlap_score=channel_data.get("audience_overlap_score", 0),
            loyal_segments=[s for s in channel_data.get("loyal_segments", [])[:10]],
            insights=insights,
            generated_at=utcnow(),
        )
        self._save(profile)
        return profile

    def get_latest(self) -> Optional[AudienceProfile]:
        files = sorted(self._dir.glob("aud_*.json"), reverse=True)
        if not files:
            return None
        try:
            data = json.loads(files[0].read_text(encoding="utf-8"))
            return AudienceProfile.from_dict(data)
        except Exception:
            return None

    def list_profiles(self, limit: int = 10) -> list[AudienceProfile]:
        profiles = []
        for f in sorted(self._dir.glob("aud_*.json"), reverse=True)[:limit]:
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                profiles.append(AudienceProfile.from_dict(data))
            except Exception:
                continue
        return profiles
