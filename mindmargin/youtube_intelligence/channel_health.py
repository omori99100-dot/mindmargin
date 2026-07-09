import json
import logging
import uuid
from pathlib import Path
from typing import Optional

from mindmargin.config import settings
from mindmargin.youtube_intelligence.models import (
    ChannelHealthReport, HealthMetric, HealthFactor, TrendDirection, utcnow,
)

logger = logging.getLogger(__name__)

HEALTH_WEIGHTS = {
    HealthFactor.VIEWS: 0.12,
    HealthFactor.WATCH_TIME: 0.12,
    HealthFactor.CTR: 0.10,
    HealthFactor.AVG_VIEW_DURATION: 0.10,
    HealthFactor.RETENTION: 0.10,
    HealthFactor.SUBSCRIBERS: 0.10,
    HealthFactor.RETURNING_VIEWERS: 0.08,
    HealthFactor.NEW_VIEWERS: 0.06,
    HealthFactor.TRAFFIC_SOURCES: 0.05,
    HealthFactor.IMPRESSIONS: 0.04,
    HealthFactor.RPM: 0.03,
    HealthFactor.CPM: 0.03,
    HealthFactor.UPLOAD_CONSISTENCY: 0.05,
    HealthFactor.CHANNEL_VELOCITY: 0.02,
}


def _score_views(views: int, avg_views: float) -> float:
    if avg_views <= 0:
        return 50.0
    ratio = views / avg_views
    return min(ratio * 50, 100.0)


def _score_watch_time(hours: float, target: float) -> float:
    if target <= 0:
        return 50.0
    return min((hours / target) * 100, 100.0)


def _score_ctr(ctr_pct: float) -> float:
    if ctr_pct >= 10:
        return 100.0
    if ctr_pct >= 7:
        return 85.0
    if ctr_pct >= 5:
        return 70.0
    if ctr_pct >= 3:
        return 50.0
    if ctr_pct >= 1:
        return 30.0
    return 10.0


def _score_avg_view_duration(seconds: float, video_length: float) -> float:
    if video_length <= 0:
        return 50.0
    pct = (seconds / video_length) * 100
    return min(pct, 100.0)


def _score_retention(avg_retention_pct: float) -> float:
    return min(avg_retention_pct, 100.0)


def _score_subscribers(subs: int, prev_subs: int) -> float:
    if prev_subs <= 0:
        return 50.0
    growth = ((subs - prev_subs) / prev_subs) * 100
    if growth >= 10:
        return 100.0
    if growth >= 5:
        return 80.0
    if growth >= 2:
        return 65.0
    if growth >= 0:
        return 50.0
    if growth >= -2:
        return 35.0
    return 15.0


def _score_returning(pct: float) -> float:
    if pct >= 40:
        return 100.0
    if pct >= 30:
        return 80.0
    if pct >= 20:
        return 65.0
    if pct >= 10:
        return 50.0
    return 30.0


def _score_new_viewers(pct: float) -> float:
    if pct >= 60:
        return 100.0
    if pct >= 40:
        return 80.0
    if pct >= 25:
        return 60.0
    if pct >= 10:
        return 40.0
    return 20.0


def _score_traffic(diversity: float) -> float:
    return min(diversity * 100, 100.0)


def _score_impressions(impressions: int, avg_impressions: float) -> float:
    if avg_impressions <= 0:
        return 50.0
    return min((impressions / avg_impressions) * 50, 100.0)


def _score_rpm(rpm: float) -> float:
    if rpm >= 15:
        return 100.0
    if rpm >= 10:
        return 80.0
    if rpm >= 5:
        return 60.0
    if rpm >= 2:
        return 40.0
    return 20.0


def _score_cpm(cpm: float) -> float:
    if cpm >= 20:
        return 100.0
    if cpm >= 15:
        return 80.0
    if cpm >= 8:
        return 60.0
    if cpm >= 3:
        return 40.0
    return 20.0


def _score_upload_consistency(days_since_last: float, target_days: float) -> float:
    if target_days <= 0:
        return 50.0
    if days_since_last <= target_days:
        return 100.0
    if days_since_last <= target_days * 1.5:
        return 70.0
    if days_since_last <= target_days * 2:
        return 40.0
    return 15.0


def _score_velocity(subs_growth_rate: float) -> float:
    if subs_growth_rate >= 5:
        return 100.0
    if subs_growth_rate >= 2:
        return 80.0
    if subs_growth_rate >= 0.5:
        return 60.0
    if subs_growth_rate >= 0:
        return 40.0
    return 15.0


def _determine_trend(current: float, previous: float) -> TrendDirection:
    if previous <= 0:
        return TrendDirection.STABLE
    change_pct = ((current - previous) / abs(previous)) * 100
    if change_pct > 5:
        return TrendDirection.RISING
    if change_pct < -5:
        return TrendDirection.DECLINING
    return TrendDirection.STABLE


def _grade(score: float) -> str:
    if score >= 90:
        return "A+"
    if score >= 80:
        return "A"
    if score >= 70:
        return "B+"
    if score >= 60:
        return "B"
    if score >= 50:
        return "C+"
    if score >= 40:
        return "C"
    if score >= 30:
        return "D"
    return "F"


class ChannelHealthMonitor:
    def __init__(self, persist_dir: str = ""):
        root = Path(persist_dir or settings.storage.temp_root)
        self._dir = root / "youtube_intelligence" / "health"
        self._dir.mkdir(parents=True, exist_ok=True)

    def _save(self, report: ChannelHealthReport):
        path = self._dir / f"{report.report_id}.json"
        path.write_text(json.dumps(report.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

    def compute_health(self, channel_data: dict) -> ChannelHealthReport:
        metrics = []

        views = channel_data.get("views", 0)
        avg_views = channel_data.get("avg_views", 1)
        metrics.append(HealthMetric(
            factor=HealthFactor.VIEWS, value=float(views),
            score=_score_views(views, avg_views), weight=HEALTH_WEIGHTS[HealthFactor.VIEWS],
            benchmark=avg_views,
            delta_from_benchmark=round(((views - avg_views) / avg_views * 100) if avg_views > 0 else 0, 1),
        ))

        watch_time = channel_data.get("watch_time_hours", 0)
        target_watch_time = channel_data.get("target_watch_time_hours", 100)
        metrics.append(HealthMetric(
            factor=HealthFactor.WATCH_TIME, value=watch_time,
            score=_score_watch_time(watch_time, target_watch_time), weight=HEALTH_WEIGHTS[HealthFactor.WATCH_TIME],
            benchmark=target_watch_time,
        ))

        ctr = channel_data.get("ctr_pct", 0)
        metrics.append(HealthMetric(
            factor=HealthFactor.CTR, value=ctr,
            score=_score_ctr(ctr), weight=HEALTH_WEIGHTS[HealthFactor.CTR],
            benchmark=channel_data.get("benchmark_ctr", 5.0),
        ))

        avd = channel_data.get("avg_view_duration_seconds", 0)
        vid_len = channel_data.get("avg_video_length_seconds", 600)
        metrics.append(HealthMetric(
            factor=HealthFactor.AVG_VIEW_DURATION, value=avd,
            score=_score_avg_view_duration(avd, vid_len), weight=HEALTH_WEIGHTS[HealthFactor.AVG_VIEW_DURATION],
            benchmark=vid_len * 0.45,
        ))

        retention = channel_data.get("avg_retention_pct", 50)
        metrics.append(HealthMetric(
            factor=HealthFactor.RETENTION, value=retention,
            score=_score_retention(retention), weight=HEALTH_WEIGHTS[HealthFactor.RETENTION],
            benchmark=channel_data.get("benchmark_retention", 50),
        ))

        subs = channel_data.get("subscribers", 0)
        prev_subs = channel_data.get("previous_subscribers", subs)
        metrics.append(HealthMetric(
            factor=HealthFactor.SUBSCRIBERS, value=float(subs),
            score=_score_subscribers(subs, prev_subs), weight=HEALTH_WEIGHTS[HealthFactor.SUBSCRIBERS],
            trend=_determine_trend(float(subs), float(prev_subs)),
        ))

        returning = channel_data.get("returning_viewer_pct", 20)
        metrics.append(HealthMetric(
            factor=HealthFactor.RETURNING_VIEWERS, value=returning,
            score=_score_returning(returning), weight=HEALTH_WEIGHTS[HealthFactor.RETURNING_VIEWERS],
        ))

        new_v = channel_data.get("new_viewer_pct", 30)
        metrics.append(HealthMetric(
            factor=HealthFactor.NEW_VIEWERS, value=new_v,
            score=_score_new_viewers(new_v), weight=HEALTH_WEIGHTS[HealthFactor.NEW_VIEWERS],
        ))

        traffic_div = channel_data.get("traffic_diversity", 0.5)
        metrics.append(HealthMetric(
            factor=HealthFactor.TRAFFIC_SOURCES, value=traffic_div,
            score=_score_traffic(traffic_div), weight=HEALTH_WEIGHTS[HealthFactor.TRAFFIC_SOURCES],
        ))

        impressions = channel_data.get("impressions", 0)
        avg_imp = channel_data.get("avg_impressions", 1)
        metrics.append(HealthMetric(
            factor=HealthFactor.IMPRESSIONS, value=float(impressions),
            score=_score_impressions(impressions, avg_imp), weight=HEALTH_WEIGHTS[HealthFactor.IMPRESSIONS],
            benchmark=float(avg_imp),
        ))

        rpm = channel_data.get("rpm", 0)
        metrics.append(HealthMetric(
            factor=HealthFactor.RPM, value=rpm,
            score=_score_rpm(rpm), weight=HEALTH_WEIGHTS[HealthFactor.RPM],
        ))

        cpm = channel_data.get("cpm", 0)
        metrics.append(HealthMetric(
            factor=HealthFactor.CPM, value=cpm,
            score=_score_cpm(cpm), weight=HEALTH_WEIGHTS[HealthFactor.CPM],
        ))

        days_since = channel_data.get("days_since_last_upload", 7)
        target_days = channel_data.get("target_upload_interval_days", 7)
        metrics.append(HealthMetric(
            factor=HealthFactor.UPLOAD_CONSISTENCY, value=days_since,
            score=_score_upload_consistency(days_since, target_days), weight=HEALTH_WEIGHTS[HealthFactor.UPLOAD_CONSISTENCY],
            benchmark=target_days,
        ))

        velocity = channel_data.get("subscriber_growth_rate_pct", 0)
        metrics.append(HealthMetric(
            factor=HealthFactor.CHANNEL_VELOCITY, value=velocity,
            score=_score_velocity(velocity), weight=HEALTH_WEIGHTS[HealthFactor.CHANNEL_VELOCITY],
        ))

        overall = sum(m.score * m.weight for m in metrics)
        overall = round(min(max(overall, 0), 100), 1)
        grade = _grade(overall)

        strengths = [m.factor.value for m in metrics if m.score >= 75]
        weaknesses = [m.factor.value for m in metrics if m.score < 40]

        report = ChannelHealthReport(
            report_id=f"health_{uuid.uuid4().hex[:10]}",
            overall_score=overall,
            metrics=metrics,
            grade=grade,
            summary=f"Channel health: {grade} ({overall}/100). {len(strengths)} strengths, {len(weaknesses)} areas to improve.",
            top_strengths=strengths[:5],
            top_weaknesses=weaknesses[:5],
            generated_at=utcnow(),
        )
        self._save(report)
        return report

    def get_latest(self) -> Optional[ChannelHealthReport]:
        files = sorted(self._dir.glob("health_*.json"), reverse=True)
        if not files:
            return None
        try:
            data = json.loads(files[0].read_text(encoding="utf-8"))
            return ChannelHealthReport.from_dict(data)
        except Exception:
            return None

    def list_reports(self, limit: int = 10) -> list[ChannelHealthReport]:
        reports = []
        for f in sorted(self._dir.glob("health_*.json"), reverse=True)[:limit]:
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                reports.append(ChannelHealthReport.from_dict(data))
            except Exception:
                continue
        return reports

    def get_health_trend(self, limit: int = 30) -> list[dict]:
        reports = self.list_reports(limit)
        return [{"date": r.generated_at, "score": r.overall_score, "grade": r.grade} for r in reports]
