import pytest
from mindmargin.youtube_intelligence.models import (
    HealthMetric, HealthFactor, ChannelHealthReport, AudienceInsight, AudienceProfile,
    GrowthSignalRecord, GrowthSignal, GrowthReport, RetentionDataPoint, RetentionAnalysis,
    RetentionPattern, CTRDataPoint, CTRReport, CompetitorChannel, CompetitionReport,
    BenchmarkEntry, BenchmarkCategory, BenchmarkReport, TrendRecord, TrendReport,
    TrendDirection, YouTubeRecommendation, RecommendationType, YouTubeIntelligenceStatus,
    utcnow,
)


class TestHealthMetric:
    def test_create(self):
        m = HealthMetric(factor=HealthFactor.CTR, value=7.5, score=85.0)
        assert m.value == 7.5
        assert m.score == 85.0

    def test_above_benchmark(self):
        m = HealthMetric(factor=HealthFactor.VIEWS, value=1000, score=80, benchmark=500)
        assert m.is_above_benchmark is True

    def test_below_benchmark(self):
        m = HealthMetric(factor=HealthFactor.VIEWS, value=100, score=30, benchmark=500)
        assert m.is_above_benchmark is False

    def test_to_dict_roundtrip(self):
        m = HealthMetric(factor=HealthFactor.CTR, value=5, score=70, trend=TrendDirection.RISING)
        d = m.to_dict()
        assert d["factor"] == "ctr"
        m2 = HealthMetric.from_dict(d)
        assert m2.trend == TrendDirection.RISING


class TestChannelHealthReport:
    def test_to_dict_roundtrip(self):
        r = ChannelHealthReport(report_id="h1", overall_score=75, grade="B+")
        d = r.to_dict()
        r2 = ChannelHealthReport.from_dict(d)
        assert r2.overall_score == 75


class TestAudienceInsight:
    def test_to_dict_roundtrip(self):
        i = AudienceInsight(insight_id="i1", category="timing", metric_name="best_time",
                            metric_value="14:00 UTC", trend=TrendDirection.RISING)
        d = i.to_dict()
        i2 = AudienceInsight.from_dict(d)
        assert i2.trend == TrendDirection.RISING


class TestAudienceProfile:
    def test_to_dict_roundtrip(self):
        p = AudienceProfile(profile_id="a1", best_upload_time="14:00 UTC",
                            returning_viewer_pct=35.0)
        d = p.to_dict()
        p2 = AudienceProfile.from_dict(d)
        assert p2.returning_viewer_pct == 35.0


class TestGrowthSignalRecord:
    def test_to_dict_roundtrip(self):
        s = GrowthSignalRecord(signal_id="s1", signal_type=GrowthSignal.FAST_GROWING_TOPIC,
                                topic="AI", strength=80)
        d = s.to_dict()
        s2 = GrowthSignalRecord.from_dict(d)
        assert s2.signal_type == GrowthSignal.FAST_GROWING_TOPIC


class TestGrowthReport:
    def test_to_dict_roundtrip(self):
        r = GrowthReport(report_id="g1", overall_growth_score=72)
        d = r.to_dict()
        r2 = GrowthReport.from_dict(d)
        assert r2.overall_growth_score == 72


class TestRetentionDataPoint:
    def test_create(self):
        p = RetentionDataPoint(timestamp_pct=10, retention_pct=85)
        assert p.retention_pct == 85


class TestRetentionAnalysis:
    def test_to_dict_roundtrip(self):
        a = RetentionAnalysis(analysis_id="r1", avg_retention_pct=55,
                              patterns=[RetentionPattern.STRONG_HOOK])
        d = a.to_dict()
        a2 = RetentionAnalysis.from_dict(d)
        assert a2.patterns == [RetentionPattern.STRONG_HOOK]


class TestCTRDataPoint:
    def test_create(self):
        dp = CTRDataPoint(video_id="v1", ctr_pct=7.5)
        assert dp.ctr_pct == 7.5

    def test_to_dict_roundtrip(self):
        dp = CTRDataPoint(video_id="v2", title="Test", ctr_pct=5.0)
        d = dp.to_dict()
        dp2 = CTRDataPoint.from_dict(d)
        assert dp2.ctr_pct == 5.0


class TestCTRReport:
    def test_to_dict_roundtrip(self):
        r = CTRReport(report_id="ctr1", avg_ctr=6.5)
        d = r.to_dict()
        r2 = CTRReport.from_dict(d)
        assert r2.avg_ctr == 6.5


class TestCompetitorChannel:
    def test_to_dict_roundtrip(self):
        c = CompetitorChannel(channel_id="ch1", channel_name="TechReviewer", subscriber_count=500000)
        d = c.to_dict()
        c2 = CompetitorChannel.from_dict(d)
        assert c2.subscriber_count == 500000


class TestCompetitionReport:
    def test_to_dict_roundtrip(self):
        r = CompetitionReport(report_id="cr1", avg_competitor_frequency=3.5)
        d = r.to_dict()
        r2 = CompetitionReport.from_dict(d)
        assert r2.avg_competitor_frequency == 3.5


class TestBenchmarkEntry:
    def test_to_dict_roundtrip(self):
        e = BenchmarkEntry(entry_id="b1", category=BenchmarkCategory.BEST_CTR,
                            metric_name="ctr", metric_value=8.5)
        d = e.to_dict()
        e2 = BenchmarkEntry.from_dict(d)
        assert e2.category == BenchmarkCategory.BEST_CTR


class TestBenchmarkReport:
    def test_to_dict_roundtrip(self):
        r = BenchmarkReport(report_id="br1")
        d = r.to_dict()
        r2 = BenchmarkReport.from_dict(d)
        assert r2.report_id == "br1"


class TestTrendRecord:
    def test_to_dict_roundtrip(self):
        t = TrendRecord(trend_id="t1", topic="Python", direction=TrendDirection.RISING, velocity=0.5)
        d = t.to_dict()
        t2 = TrendRecord.from_dict(d)
        assert t2.direction == TrendDirection.RISING


class TestTrendReport:
    def test_to_dict_roundtrip(self):
        r = TrendReport(report_id="tr1", summary="5 rising, 2 declining")
        d = r.to_dict()
        r2 = TrendReport.from_dict(d)
        assert "rising" in r2.summary


class TestYouTubeRecommendation:
    def test_to_dict_roundtrip(self):
        r = YouTubeRecommendation(recommendation_id="rec1",
                                   recommendation_type=RecommendationType.GROWTH,
                                   title="Capitalize on AI trend")
        d = r.to_dict()
        r2 = YouTubeRecommendation.from_dict(d)
        assert r2.recommendation_type == RecommendationType.GROWTH


class TestYouTubeIntelligenceStatus:
    def test_to_dict_roundtrip(self):
        s = YouTubeIntelligenceStatus(health_score=85, growth_score=72)
        d = s.to_dict()
        s2 = YouTubeIntelligenceStatus.from_dict(d)
        assert s2.health_score == 85
