import pytest
from mindmargin.youtube_intelligence.models import (
    RetentionDataPoint, CTRDataPoint, TrendDirection, BenchmarkCategory, RetentionPattern,
)


class TestChannelHealthMonitor:
    def test_compute_health_excellent(self, tmp_path):
        from mindmargin.youtube_intelligence.channel_health import ChannelHealthMonitor
        mon = ChannelHealthMonitor(persist_dir=str(tmp_path))
        data = {
            "views": 10000, "avg_views": 5000,
            "watch_time_hours": 500, "target_watch_time_hours": 200,
            "ctr_pct": 8, "avg_view_duration_seconds": 400, "avg_video_length_seconds": 600,
            "avg_retention_pct": 65, "subscribers": 50000, "previous_subscribers": 45000,
            "returning_viewer_pct": 35, "new_viewer_pct": 40,
            "traffic_diversity": 0.7, "impressions": 50000, "avg_impressions": 30000,
            "rpm": 12, "cpm": 18,
            "days_since_last_upload": 3, "target_upload_interval_days": 7,
            "subscriber_growth_rate_pct": 3,
        }
        report = mon.compute_health(data)
        assert report.overall_score > 60
        assert len(report.metrics) == 14
        assert report.grade in ["A+", "A", "B+", "B", "C+"]

    def test_compute_health_weak(self, tmp_path):
        from mindmargin.youtube_intelligence.channel_health import ChannelHealthMonitor
        mon = ChannelHealthMonitor(persist_dir=str(tmp_path))
        data = {
            "views": 100, "avg_views": 5000,
            "watch_time_hours": 2, "target_watch_time_hours": 200,
            "ctr_pct": 1, "avg_view_duration_seconds": 30, "avg_video_length_seconds": 600,
            "avg_retention_pct": 15, "subscribers": 100, "previous_subscribers": 120,
            "returning_viewer_pct": 5, "new_viewer_pct": 5,
            "traffic_diversity": 0.1, "impressions": 500, "avg_impressions": 10000,
            "rpm": 0.5, "cpm": 1,
            "days_since_last_upload": 60, "target_upload_interval_days": 7,
            "subscriber_growth_rate_pct": -2,
        }
        report = mon.compute_health(data)
        assert report.overall_score < 40
        assert report.grade in ["D", "F", "C"]
        assert len(report.top_weaknesses) > 0

    def test_get_latest_empty(self, tmp_path):
        from mindmargin.youtube_intelligence.channel_health import ChannelHealthMonitor
        mon = ChannelHealthMonitor(persist_dir=str(tmp_path))
        assert mon.get_latest() is None

    def test_list_reports(self, tmp_path):
        from mindmargin.youtube_intelligence.channel_health import ChannelHealthMonitor
        mon = ChannelHealthMonitor(persist_dir=str(tmp_path))
        mon.compute_health({"views": 100, "avg_views": 100, "ctr_pct": 5})
        reports = mon.list_reports()
        assert len(reports) == 1

    def test_health_trend(self, tmp_path):
        from mindmargin.youtube_intelligence.channel_health import ChannelHealthMonitor
        mon = ChannelHealthMonitor(persist_dir=str(tmp_path))
        mon.compute_health({"views": 100, "avg_views": 100, "ctr_pct": 5})
        trend = mon.get_health_trend()
        assert len(trend) == 1
        assert "score" in trend[0]


class TestGrowthEngine:
    def test_fast_growing_topics(self, tmp_path):
        from mindmargin.youtube_intelligence.growth import GrowthEngine
        eng = GrowthEngine(persist_dir=str(tmp_path))
        topics = [
            {"topic": "AI Tools", "velocity": 1.5, "views": 50000},
            {"topic": "Cooking", "velocity": 0.2, "views": 5000},
        ]
        signals = eng.detect_fast_growing_topics(topics)
        assert len(signals) == 1
        assert signals[0].topic == "AI Tools"
        assert signals[0].action_required is True

    def test_declining_topics(self, tmp_path):
        from mindmargin.youtube_intelligence.growth import GrowthEngine
        eng = GrowthEngine(persist_dir=str(tmp_path))
        topics = [{"topic": "Old News", "velocity": -0.5}]
        signals = eng.detect_declining_topics(topics)
        assert len(signals) == 1

    def test_evergreen_opportunities(self, tmp_path):
        from mindmargin.youtube_intelligence.growth import GrowthEngine
        eng = GrowthEngine(persist_dir=str(tmp_path))
        history = [{"topic": "Python Basics", "age_days": 120, "total_views": 10000, "recent_views": 3000}]
        signals = eng.detect_evergreen_opportunities(history)
        assert len(signals) == 1

    def test_audience_fatigue(self, tmp_path):
        from mindmargin.youtube_intelligence.growth import GrowthEngine
        eng = GrowthEngine(persist_dir=str(tmp_path))
        freq = [{"topic": "React Hooks", "occurrences_last_30d": 6, "views_trend": -0.4}]
        signals = eng.detect_audience_fatigue(freq)
        assert len(signals) == 1

    def test_content_saturation(self, tmp_path):
        from mindmargin.youtube_intelligence.growth import GrowthEngine
        eng = GrowthEngine(persist_dir=str(tmp_path))
        overlap = [{"topic": "JavaScript", "saturation_score": 0.9, "similar_count": 50}]
        signals = eng.detect_content_saturation(overlap)
        assert len(signals) == 1

    def test_growth_bottlenecks(self, tmp_path):
        from mindmargin.youtube_intelligence.growth import GrowthEngine
        eng = GrowthEngine(persist_dir=str(tmp_path))
        signals = eng.detect_growth_bottlenecks({"ctr_pct": 1.5, "avg_retention_pct": 20, "impressions": 1000})
        assert len(signals) == 2

    def test_analyze_growth(self, tmp_path):
        from mindmargin.youtube_intelligence.growth import GrowthEngine
        eng = GrowthEngine(persist_dir=str(tmp_path))
        report = eng.analyze_growth(
            {"ctr_pct": 5, "avg_retention_pct": 40},
            [{"topic": "AI", "velocity": 1.2}],
            [{"topic": "Python", "age_days": 100, "total_views": 5000, "recent_views": 1500}],
        )
        assert report.overall_growth_score > 0
        assert len(report.signals) > 0

    def test_list_reports(self, tmp_path):
        from mindmargin.youtube_intelligence.growth import GrowthEngine
        eng = GrowthEngine(persist_dir=str(tmp_path))
        eng.analyze_growth({}, [])
        assert len(eng.list_reports()) == 1


class TestAudienceIntelligence:
    def test_best_upload_time(self, tmp_path):
        from mindmargin.youtube_intelligence.audience import AudienceIntelligence
        ai = AudienceIntelligence(persist_dir=str(tmp_path))
        insight = ai.analyze_best_upload_time([
            {"hour": 10, "avg_views": 500},
            {"hour": 14, "avg_views": 800},
            {"hour": 20, "avg_views": 300},
        ])
        assert "14:00" in insight.metric_value

    def test_best_upload_day(self, tmp_path):
        from mindmargin.youtube_intelligence.audience import AudienceIntelligence
        ai = AudienceIntelligence(persist_dir=str(tmp_path))
        insight = ai.analyze_best_upload_day([
            {"day": "Monday", "avg_views": 400},
            {"day": "Saturday", "avg_views": 900},
        ])
        assert "Saturday" in insight.metric_value

    def test_geography(self, tmp_path):
        from mindmargin.youtube_intelligence.audience import AudienceIntelligence
        ai = AudienceIntelligence(persist_dir=str(tmp_path))
        insight = ai.analyze_geography([
            {"country": "USA", "view_pct": 45},
            {"country": "UK", "view_pct": 20},
        ])
        assert "USA" in insight.metric_value

    def test_devices(self, tmp_path):
        from mindmargin.youtube_intelligence.audience import AudienceIntelligence
        ai = AudienceIntelligence(persist_dir=str(tmp_path))
        insight = ai.analyze_devices([
            {"device": "Mobile", "view_pct": 65},
            {"device": "Desktop", "view_pct": 35},
        ])
        assert "Mobile" in insight.metric_value

    def test_returning_viewers_high(self, tmp_path):
        from mindmargin.youtube_intelligence.audience import AudienceIntelligence
        ai = AudienceIntelligence(persist_dir=str(tmp_path))
        insight = ai.analyze_returning_viewers(45)
        assert "loyal" in insight.recommendation.lower()

    def test_returning_viewers_low(self, tmp_path):
        from mindmargin.youtube_intelligence.audience import AudienceIntelligence
        ai = AudienceIntelligence(persist_dir=str(tmp_path))
        insight = ai.analyze_returning_viewers(8)
        assert "returning" in insight.recommendation.lower()

    def test_session_duration(self, tmp_path):
        from mindmargin.youtube_intelligence.audience import AudienceIntelligence
        ai = AudienceIntelligence(persist_dir=str(tmp_path))
        insight = ai.analyze_session_duration(900)
        assert "excellent" in insight.recommendation.lower()

    def test_build_profile(self, tmp_path):
        from mindmargin.youtube_intelligence.audience import AudienceIntelligence
        ai = AudienceIntelligence(persist_dir=str(tmp_path))
        profile = ai.build_profile({
            "hourly_views": [{"hour": 14, "avg_views": 500}],
            "daily_views": [{"day": "Saturday", "avg_views": 600}],
            "geography": [{"country": "USA", "view_pct": 50}],
            "devices": [{"device": "Mobile", "view_pct": 60}],
            "returning_viewer_pct": 30,
            "avg_session_duration": 400,
        })
        assert profile.best_upload_time != ""
        assert profile.best_upload_day != ""
        assert len(profile.insights) >= 5

    def test_list_profiles(self, tmp_path):
        from mindmargin.youtube_intelligence.audience import AudienceIntelligence
        ai = AudienceIntelligence(persist_dir=str(tmp_path))
        ai.build_profile({})
        assert len(ai.list_profiles()) == 1


class TestRetentionAnalyzer:
    def test_hook_strength_strong(self, tmp_path):
        from mindmargin.youtube_intelligence.retention import RetentionAnalyzer
        ra = RetentionAnalyzer(persist_dir=str(tmp_path))
        points = [
            {"timestamp_pct": 0, "retention_pct": 100},
            {"timestamp_pct": 5, "retention_pct": 95},
            {"timestamp_pct": 50, "retention_pct": 60},
            {"timestamp_pct": 100, "retention_pct": 30},
        ]
        score, patterns = ra.detect_hook_strength([RetentionDataPoint.from_dict(p) for p in points])
        assert score > 60

    def test_hook_strength_weak(self, tmp_path):
        from mindmargin.youtube_intelligence.retention import RetentionAnalyzer
        ra = RetentionAnalyzer(persist_dir=str(tmp_path))
        points = [
            {"timestamp_pct": 0, "retention_pct": 100},
            {"timestamp_pct": 5, "retention_pct": 50},
        ]
        score, patterns = ra.detect_hook_strength([RetentionDataPoint.from_dict(p) for p in points])
        assert score < 50
        assert RetentionPattern.WEAK_INTRO in patterns

    def test_drop_offs(self, tmp_path):
        from mindmargin.youtube_intelligence.retention import RetentionAnalyzer
        ra = RetentionAnalyzer(persist_dir=str(tmp_path))
        points = [
            RetentionDataPoint(timestamp_pct=10, retention_pct=80),
            RetentionDataPoint(timestamp_pct=20, retention_pct=60),
            RetentionDataPoint(timestamp_pct=30, retention_pct=58),
        ]
        drop_offs = ra.detect_drop_offs(points)
        assert len(drop_offs) == 1
        assert drop_offs[0]["drop_magnitude"] == 20

    def test_strong_endings(self, tmp_path):
        from mindmargin.youtube_intelligence.retention import RetentionAnalyzer
        ra = RetentionAnalyzer(persist_dir=str(tmp_path))
        points = [
            RetentionDataPoint(timestamp_pct=85, retention_pct=50),
            RetentionDataPoint(timestamp_pct=95, retention_pct=48),
            RetentionDataPoint(timestamp_pct=100, retention_pct=45),
        ]
        endings = ra.detect_strong_endings(points)
        assert len(endings) == 1
        assert endings[0]["strength"] == "strong"

    def test_detect_patterns(self, tmp_path):
        from mindmargin.youtube_intelligence.retention import RetentionAnalyzer
        ra = RetentionAnalyzer(persist_dir=str(tmp_path))
        points = [
            RetentionDataPoint(timestamp_pct=0, retention_pct=100),
            RetentionDataPoint(timestamp_pct=10, retention_pct=95),
            RetentionDataPoint(timestamp_pct=50, retention_pct=60),
            RetentionDataPoint(timestamp_pct=100, retention_pct=30),
        ]
        patterns = ra.detect_patterns(points)
        assert len(patterns) > 0

    def test_analyze_video(self, tmp_path):
        from mindmargin.youtube_intelligence.retention import RetentionAnalyzer
        ra = RetentionAnalyzer(persist_dir=str(tmp_path))
        points = [
            {"timestamp_pct": 0, "retention_pct": 100},
            {"timestamp_pct": 10, "retention_pct": 85},
            {"timestamp_pct": 50, "retention_pct": 55},
            {"timestamp_pct": 100, "retention_pct": 25},
        ]
        analysis = ra.analyze_video("v1", "Test Video", points)
        assert analysis.avg_retention_pct > 0
        assert len(analysis.script_recommendations) > 0

    def test_list_analyses(self, tmp_path):
        from mindmargin.youtube_intelligence.retention import RetentionAnalyzer
        ra = RetentionAnalyzer(persist_dir=str(tmp_path))
        ra.analyze_video("v1", "Test", [{"timestamp_pct": 0, "retention_pct": 100}])
        assert len(ra.list_analyses()) == 1


class TestCTROptimizer:
    def test_analyze_title_effectiveness(self, tmp_path):
        from mindmargin.youtube_intelligence.ctr import CTROptimizer
        co = CTROptimizer(persist_dir=str(tmp_path))
        points = [
            CTRDataPoint(video_id="v1", ctr_pct=8, title_pattern="question"),
            CTRDataPoint(video_id="v2", ctr_pct=4, title_pattern="statement"),
            CTRDataPoint(video_id="v3", ctr_pct=9, title_pattern="question"),
        ]
        result = co.analyze_title_effectiveness(points)
        assert "patterns" in result
        assert result["patterns"]["question"]["avg_ctr"] > result["patterns"]["statement"]["avg_ctr"]

    def test_analyze_thumbnail_effectiveness(self, tmp_path):
        from mindmargin.youtube_intelligence.ctr import CTROptimizer
        co = CTROptimizer(persist_dir=str(tmp_path))
        points = [
            CTRDataPoint(video_id="v1", ctr_pct=10, thumbnail_style="face_closeup"),
            CTRDataPoint(video_id="v2", ctr_pct=5, thumbnail_style="text_overlay"),
        ]
        result = co.analyze_thumbnail_effectiveness(points)
        assert result["styles"]["face_closeup"]["avg_ctr"] > result["styles"]["text_overlay"]["avg_ctr"]

    def test_predict_ctr(self, tmp_path):
        from mindmargin.youtube_intelligence.ctr import CTROptimizer
        co = CTROptimizer(persist_dir=str(tmp_path))
        history = [
            CTRDataPoint(video_id="v1", ctr_pct=8, title_pattern="question", thumbnail_style="face"),
            CTRDataPoint(video_id="v2", ctr_pct=6, title_pattern="question", thumbnail_style="text"),
        ]
        pred = co.predict_ctr("question", "face", "tech", history)
        assert pred > 0

    def test_generate_report(self, tmp_path):
        from mindmargin.youtube_intelligence.ctr import CTROptimizer
        co = CTROptimizer(persist_dir=str(tmp_path))
        data = [
            {"video_id": "v1", "ctr_pct": 7, "title_pattern": "question", "thumbnail_style": "face"},
            {"video_id": "v2", "ctr_pct": 4, "title_pattern": "list", "thumbnail_style": "text"},
        ]
        report = co.generate_report(data)
        assert report.avg_ctr > 0
        assert len(report.recommendations) > 0

    def test_list_reports(self, tmp_path):
        from mindmargin.youtube_intelligence.ctr import CTROptimizer
        co = CTROptimizer(persist_dir=str(tmp_path))
        co.generate_report([{"video_id": "v1", "ctr_pct": 5}])
        assert len(co.list_reports()) == 1


class TestCompetitionIntelligence:
    def test_add_competitor(self, tmp_path):
        from mindmargin.youtube_intelligence.competition import CompetitionIntelligence
        ci = CompetitionIntelligence(persist_dir=str(tmp_path))
        comp = ci.add_competitor("ch1", "TechReviewer", 500000)
        assert comp.channel_name == "TechReviewer"

    def test_remove_competitor(self, tmp_path):
        from mindmargin.youtube_intelligence.competition import CompetitionIntelligence
        ci = CompetitionIntelligence(persist_dir=str(tmp_path))
        ci.add_competitor("ch1", "Tech")
        assert ci.remove_competitor("ch1") is True
        assert len(ci.list_competitors()) == 0

    def test_compare_frequency(self, tmp_path):
        from mindmargin.youtube_intelligence.competition import CompetitionIntelligence
        ci = CompetitionIntelligence(persist_dir=str(tmp_path))
        ci.add_competitor("ch1", "A")
        ci.update_competitor_metrics("ch1", {"upload_frequency": 3})
        result = ci.compare_frequency(4)
        assert result["status"] == "above_average"

    def test_find_topic_gaps(self, tmp_path):
        from mindmargin.youtube_intelligence.competition import CompetitionIntelligence
        ci = CompetitionIntelligence(persist_dir=str(tmp_path))
        ci.add_competitor("ch1", "A")
        ci.update_competitor_metrics("ch1", {"content_gaps": ["AI Tools", "Python"]})
        gaps = ci.find_topic_gaps(["Python", "React"])
        assert len(gaps) == 1
        assert gaps[0]["topic"] == "ai tools"

    def test_generate_report(self, tmp_path):
        from mindmargin.youtube_intelligence.competition import CompetitionIntelligence
        ci = CompetitionIntelligence(persist_dir=str(tmp_path))
        ci.add_competitor("ch1", "TechReviewer")
        report = ci.generate_report({"topics": ["AI", "Python"], "upload_frequency": 2})
        assert len(report.competitors) == 1


class TestTrendsEngine:
    def test_classify_trend_rising(self, tmp_path):
        from mindmargin.youtube_intelligence.trends import TrendsEngine
        te = TrendsEngine(persist_dir=str(tmp_path))
        assert te.classify_trend(1000, 500) == TrendDirection.RISING

    def test_classify_trend_declining(self, tmp_path):
        from mindmargin.youtube_intelligence.trends import TrendsEngine
        te = TrendsEngine(persist_dir=str(tmp_path))
        assert te.classify_trend(100, 500) == TrendDirection.DECLINING

    def test_classify_trend_stable(self, tmp_path):
        from mindmargin.youtube_intelligence.trends import TrendsEngine
        te = TrendsEngine(persist_dir=str(tmp_path))
        assert te.classify_trend(450, 500) == TrendDirection.STABLE

    def test_compute_velocity(self, tmp_path):
        from mindmargin.youtube_intelligence.trends import TrendsEngine
        te = TrendsEngine(persist_dir=str(tmp_path))
        v = te.compute_velocity([100, 150, 225])
        assert v > 0

    def test_analyze_trends(self, tmp_path):
        from mindmargin.youtube_intelligence.trends import TrendsEngine
        te = TrendsEngine(persist_dir=str(tmp_path))
        data = [
            {"topic": "AI", "current_volume": 1000, "previous_volume": 500, "competition": 0.4},
            {"topic": "Cooking", "current_volume": 200, "previous_volume": 500, "competition": 0.2},
            {"topic": "Python Advanced", "current_volume": 300, "previous_volume": 200, "competition": 0.1},
        ]
        report = te.analyze_trends(data, ["AI", "Python"])
        assert len(report.trends) == 3
        assert len(report.rising_topics) == 2
        assert len(report.declining_topics) == 1
        assert len(report.niche_opportunities) == 1


class TestBenchmarkEngine:
    def test_record_benchmark(self, tmp_path):
        from mindmargin.youtube_intelligence.benchmark import BenchmarkEngine
        be = BenchmarkEngine(persist_dir=str(tmp_path))
        entry = be.record_benchmark(BenchmarkCategory.BEST_CTR, "ctr", 8.5, context="Question title")
        assert entry.metric_value == 8.5

    def test_get_best(self, tmp_path):
        from mindmargin.youtube_intelligence.benchmark import BenchmarkEngine
        be = BenchmarkEngine(persist_dir=str(tmp_path))
        be.record_benchmark(BenchmarkCategory.BEST_CTR, "ctr", 5.0)
        be.record_benchmark(BenchmarkCategory.BEST_CTR, "ctr", 9.0)
        best = be.get_best(BenchmarkCategory.BEST_CTR)
        assert best.metric_value == 9.0

    def test_compare_to_benchmark(self, tmp_path):
        from mindmargin.youtube_intelligence.benchmark import BenchmarkEngine
        be = BenchmarkEngine(persist_dir=str(tmp_path))
        be.record_benchmark(BenchmarkCategory.BEST_CTR, "ctr", 7.0)
        result = be.compare_to_benchmark(BenchmarkCategory.BEST_CTR, 8.0)
        assert result["status"] == "above_benchmark"

    def test_record_from_video_data(self, tmp_path):
        from mindmargin.youtube_intelligence.benchmark import BenchmarkEngine
        be = BenchmarkEngine(persist_dir=str(tmp_path))
        entries = be.record_from_video_data({
            "video_id": "v1", "title": "Test", "ctr_pct": 7.5,
            "watch_time_hours": 100, "retention_pct": 55,
            "topic_category": "Tech",
        })
        assert len(entries) >= 3

    def test_generate_report(self, tmp_path):
        from mindmargin.youtube_intelligence.benchmark import BenchmarkEngine
        be = BenchmarkEngine(persist_dir=str(tmp_path))
        be.record_benchmark(BenchmarkCategory.BEST_CTR, "ctr", 8.0)
        report = be.generate_report()
        assert len(report.entries) == 1


class TestYouTubeOptimizer:
    def test_get_status(self, tmp_path):
        from mindmargin.youtube_intelligence.optimizer import YouTubeOptimizer
        opt = YouTubeOptimizer(persist_dir=str(tmp_path))
        status = opt.get_status()
        assert isinstance(status.health_score, float)

    def test_get_optimization_priorities_empty(self, tmp_path):
        from mindmargin.youtube_intelligence.optimizer import YouTubeOptimizer
        opt = YouTubeOptimizer(persist_dir=str(tmp_path))
        priorities = opt.get_optimization_priorities()
        assert isinstance(priorities, list)


class TestYouTubeRecommendationEngine:
    def test_generate_from_health(self, tmp_path):
        from mindmargin.youtube_intelligence.recommendations import YouTubeRecommendationEngine
        re = YouTubeRecommendationEngine(persist_dir=str(tmp_path))
        recs = re.generate_from_health({"top_weaknesses": ["ctr", "retention"]})
        assert len(recs) == 2

    def test_generate_from_growth(self, tmp_path):
        from mindmargin.youtube_intelligence.recommendations import YouTubeRecommendationEngine
        re = YouTubeRecommendationEngine(persist_dir=str(tmp_path))
        recs = re.generate_from_growth({
            "fast_growing_topics": [{"topic": "AI"}],
            "bottlenecks": [{"topic": "Low CTR"}],
        })
        assert len(recs) == 2

    def test_list_recommendations(self, tmp_path):
        from mindmargin.youtube_intelligence.recommendations import YouTubeRecommendationEngine
        re = YouTubeRecommendationEngine(persist_dir=str(tmp_path))
        re.generate_from_health({"top_weaknesses": ["ctr"]})
        recs = re.list_recommendations()
        assert len(recs) == 1

    def test_mark_actioned(self, tmp_path):
        from mindmargin.youtube_intelligence.recommendations import YouTubeRecommendationEngine
        re = YouTubeRecommendationEngine(persist_dir=str(tmp_path))
        recs = re.generate_from_health({"top_weaknesses": ["ctr"]})
        ok = re.mark_actioned(recs[0].recommendation_id)
        assert ok is True


class TestYouTubeIntelligenceAPI:
    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from mindmargin.api.server import app
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c

    def test_status(self, client):
        resp = client.get("/api/v1/youtube/status")
        assert resp.status_code == 200

    def test_health(self, client):
        resp = client.get("/api/v1/youtube/health")
        assert resp.status_code == 200

    def test_growth(self, client):
        resp = client.get("/api/v1/youtube/growth")
        assert resp.status_code == 200

    def test_audience(self, client):
        resp = client.get("/api/v1/youtube/audience")
        assert resp.status_code == 200

    def test_retention(self, client):
        resp = client.get("/api/v1/youtube/retention")
        assert resp.status_code == 200

    def test_ctr(self, client):
        resp = client.get("/api/v1/youtube/ctr")
        assert resp.status_code == 200

    def test_competition(self, client):
        resp = client.get("/api/v1/youtube/competition")
        assert resp.status_code == 200

    def test_benchmarks(self, client):
        resp = client.get("/api/v1/youtube/benchmarks")
        assert resp.status_code == 200

    def test_trends(self, client):
        resp = client.get("/api/v1/youtube/trends")
        assert resp.status_code == 200

    def test_recommendations(self, client):
        resp = client.get("/api/v1/youtube/recommendations")
        assert resp.status_code == 200
