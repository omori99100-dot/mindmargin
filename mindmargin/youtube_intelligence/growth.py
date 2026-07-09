import json
import logging
import uuid
from pathlib import Path
from typing import Optional

from mindmargin.config import settings
from mindmargin.youtube_intelligence.models import (
    GrowthReport, GrowthSignalRecord, GrowthSignal, TrendDirection, utcnow,
)

logger = logging.getLogger(__name__)


class GrowthEngine:
    def __init__(self, persist_dir: str = ""):
        root = Path(persist_dir or settings.storage.temp_root)
        self._dir = root / "youtube_intelligence" / "growth"
        self._dir.mkdir(parents=True, exist_ok=True)

    def _save(self, report: GrowthReport):
        path = self._dir / f"{report.report_id}.json"
        path.write_text(json.dumps(report.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8")

    def detect_fast_growing_topics(self, topic_data: list[dict]) -> list[GrowthSignalRecord]:
        signals = []
        for td in topic_data:
            velocity = td.get("velocity", 0)
            if velocity > 0.5:
                sig = GrowthSignalRecord(
                    signal_id=f"sig_{uuid.uuid4().hex[:8]}",
                    signal_type=GrowthSignal.FAST_GROWING_TOPIC,
                    topic=td.get("topic", ""),
                    strength=min(velocity * 100, 100),
                    evidence=[f"Velocity: {velocity:.2f}", f"Views: {td.get('views', 0)}"],
                    first_detected=td.get("first_seen", utcnow()),
                    last_updated=utcnow(),
                    action_required=velocity > 1.0,
                )
                signals.append(sig)
        return signals

    def detect_declining_topics(self, topic_data: list[dict]) -> list[GrowthSignalRecord]:
        signals = []
        for td in topic_data:
            velocity = td.get("velocity", 0)
            if velocity < -0.3:
                sig = GrowthSignalRecord(
                    signal_id=f"sig_{uuid.uuid4().hex[:8]}",
                    signal_type=GrowthSignal.DECLINING_TOPIC,
                    topic=td.get("topic", ""),
                    strength=abs(velocity) * 100,
                    evidence=[f"Negative velocity: {velocity:.2f}", f"Views trend: declining"],
                    first_detected=td.get("first_seen", utcnow()),
                    last_updated=utcnow(),
                    action_required=velocity < -0.8,
                )
                signals.append(sig)
        return signals

    def detect_evergreen_opportunities(self, content_history: list[dict]) -> list[GrowthSignalRecord]:
        signals = []
        for item in content_history:
            age_days = item.get("age_days", 0)
            views = item.get("total_views", 0)
            recent_views = item.get("recent_views", 0)
            if age_days > 90 and views > 0:
                recency_ratio = recent_views / views if views > 0 else 0
                if recency_ratio > 0.1:
                    sig = GrowthSignalRecord(
                        signal_id=f"sig_{uuid.uuid4().hex[:8]}",
                        signal_type=GrowthSignal.EVERGREEN_OPPORTUNITY,
                        topic=item.get("topic", ""),
                        strength=recency_ratio * 100,
                        evidence=[f"Age: {age_days}d", f"Recency ratio: {recency_ratio:.2f}"],
                        first_detected=item.get("first_seen", utcnow()),
                        last_updated=utcnow(),
                        action_required=recency_ratio > 0.25,
                    )
                    signals.append(sig)
        return signals

    def detect_audience_fatigue(self, topic_frequency: list[dict]) -> list[GrowthSignalRecord]:
        signals = []
        for tf in topic_frequency:
            occurrences = tf.get("occurrences_last_30d", 0)
            avg_views = tf.get("avg_views_per_video", 0)
            trend = tf.get("views_trend", 0)
            if occurrences >= 4 and trend < -0.2:
                fatigue_score = min(occurrences * abs(trend) * 50, 100)
                sig = GrowthSignalRecord(
                    signal_id=f"sig_{uuid.uuid4().hex[:8]}",
                    signal_type=GrowthSignal.AUDIENCE_FATIGUE,
                    topic=tf.get("topic", ""),
                    strength=fatigue_score,
                    evidence=[f"Occurrences: {occurrences}", f"Views trend: {trend:.2f}"],
                    first_detected=utcnow(),
                    last_updated=utcnow(),
                    action_required=fatigue_score > 50,
                )
                signals.append(sig)
        return signals

    def detect_content_saturation(self, topic_overlap: list[dict]) -> list[GrowthSignalRecord]:
        signals = []
        for to in topic_overlap:
            saturation = to.get("saturation_score", 0)
            if saturation > 0.7:
                sig = GrowthSignalRecord(
                    signal_id=f"sig_{uuid.uuid4().hex[:8]}",
                    signal_type=GrowthSignal.CONTENT_SATURATION,
                    topic=to.get("topic", ""),
                    strength=saturation * 100,
                    evidence=[f"Saturation: {saturation:.2f}", f"Similar videos: {to.get('similar_count', 0)}"],
                    first_detected=utcnow(),
                    last_updated=utcnow(),
                    action_required=saturation > 0.85,
                )
                signals.append(sig)
        return signals

    def detect_growth_bottlenecks(self, channel_metrics: dict) -> list[GrowthSignalRecord]:
        signals = []
        ctr = channel_metrics.get("ctr_pct", 5)
        retention = channel_metrics.get("avg_retention_pct", 50)
        impressions = channel_metrics.get("impressions", 0)
        subs = channel_metrics.get("subscribers", 0)

        if ctr < 3 and impressions > 0:
            signals.append(GrowthSignalRecord(
                signal_id=f"sig_{uuid.uuid4().hex[:8]}",
                signal_type=GrowthSignal.GROWTH_BOTTLENECK,
                topic="Low CTR limiting impressions",
                strength=100 - ctr * 10,
                evidence=[f"CTR: {ctr:.1f}%", f"Impressions: {impressions}"],
                first_detected=utcnow(), last_updated=utcnow(), action_required=True,
            ))
        if retention < 30:
            signals.append(GrowthSignalRecord(
                signal_id=f"sig_{uuid.uuid4().hex[:8]}",
                signal_type=GrowthSignal.GROWTH_BOTTLENECK,
                topic="Low retention hurting algorithm",
                strength=100 - retention,
                evidence=[f"Retention: {retention:.1f}%"],
                first_detected=utcnow(), last_updated=utcnow(), action_required=True,
            ))
        return signals

    def analyze_growth(self, channel_data: dict, topic_data: list[dict] = None,
                       content_history: list[dict] = None,
                       topic_frequency: list[dict] = None,
                       topic_overlap: list[dict] = None) -> GrowthReport:
        topic_data = topic_data or []
        content_history = content_history or []
        topic_frequency = topic_frequency or []
        topic_overlap = topic_overlap or []

        all_signals = []
        all_signals.extend(self.detect_fast_growing_topics(topic_data))
        all_signals.extend(self.detect_declining_topics(topic_data))
        all_signals.extend(self.detect_evergreen_opportunities(content_history))
        all_signals.extend(self.detect_audience_fatigue(topic_frequency))
        all_signals.extend(self.detect_content_saturation(topic_overlap))
        all_signals.extend(self.detect_growth_bottlenecks(channel_data))

        fast_growing = [s.to_dict() for s in all_signals if s.signal_type == GrowthSignal.FAST_GROWING_TOPIC]
        declining = [s.to_dict() for s in all_signals if s.signal_type == GrowthSignal.DECLINING_TOPIC]
        evergreen = [s.to_dict() for s in all_signals if s.signal_type == GrowthSignal.EVERGREEN_OPPORTUNITY]
        missed = [s.to_dict() for s in all_signals if s.signal_type == GrowthSignal.MISSED_OPPORTUNITY]
        bottlenecks = [s.to_dict() for s in all_signals if s.signal_type == GrowthSignal.GROWTH_BOTTLENECK]

        positive = len([s for s in all_signals if s.signal_type in (
            GrowthSignal.FAST_GROWING_TOPIC, GrowthSignal.EVERGREEN_OPPORTUNITY)])
        negative = len([s for s in all_signals if s.signal_type in (
            GrowthSignal.DECLINING_TOPIC, GrowthSignal.GROWTH_BOTTLENECK, GrowthSignal.AUDIENCE_FATIGUE)])
        growth_score = max(0, min(100, 50 + (positive - negative) * 10))

        report = GrowthReport(
            report_id=f"growth_{uuid.uuid4().hex[:10]}",
            signals=all_signals,
            fast_growing_topics=fast_growing,
            declining_topics=declining,
            evergreen_opportunities=evergreen,
            missed_opportunities=missed,
            bottlenecks=bottlenecks,
            overall_growth_score=growth_score,
            summary=f"Growth score: {growth_score}/100. {len(fast_growing)} fast-growing, {len(declining)} declining, {len(evergreen)} evergreen, {len(bottlenecks)} bottlenecks.",
            generated_at=utcnow(),
        )
        self._save(report)
        return report

    def list_reports(self, limit: int = 10) -> list[GrowthReport]:
        reports = []
        for f in sorted(self._dir.glob("growth_*.json"), reverse=True)[:limit]:
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                reports.append(GrowthReport.from_dict(data))
            except Exception:
                continue
        return reports
