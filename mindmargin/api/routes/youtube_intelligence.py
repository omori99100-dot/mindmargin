from fastapi import APIRouter

router = APIRouter(tags=["YouTube Intelligence"])


@router.get("/youtube/status")
def get_status():
    from mindmargin.youtube_intelligence.optimizer import YouTubeOptimizer
    opt = YouTubeOptimizer()
    return opt.get_status().to_dict()


@router.get("/youtube/health")
def get_health():
    from mindmargin.youtube_intelligence.channel_health import ChannelHealthMonitor
    monitor = ChannelHealthMonitor()
    report = monitor.get_latest()
    return report.to_dict() if report else {"message": "No health data yet"}


@router.post("/youtube/health/compute")
def compute_health(channel_data: dict = None):
    from mindmargin.youtube_intelligence.channel_health import ChannelHealthMonitor
    monitor = ChannelHealthMonitor()
    data = channel_data or {}
    report = monitor.compute_health(data)
    return report.to_dict()


@router.get("/youtube/growth")
def get_growth():
    from mindmargin.youtube_intelligence.growth import GrowthEngine
    engine = GrowthEngine()
    reports = engine.list_reports(1)
    return reports[0].to_dict() if reports else {"message": "No growth data yet"}


@router.post("/youtube/growth/analyze")
def analyze_growth(channel_data: dict = None, topic_data: list = None):
    from mindmargin.youtube_intelligence.growth import GrowthEngine
    engine = GrowthEngine()
    report = engine.analyze_growth(channel_data or {}, topic_data or [])
    return report.to_dict()


@router.get("/youtube/audience")
def get_audience():
    from mindmargin.youtube_intelligence.audience import AudienceIntelligence
    ai = AudienceIntelligence()
    profile = ai.get_latest()
    return profile.to_dict() if profile else {"message": "No audience data yet"}


@router.post("/youtube/audience/build")
def build_audience(channel_data: dict = None):
    from mindmargin.youtube_intelligence.audience import AudienceIntelligence
    ai = AudienceIntelligence()
    profile = ai.build_profile(channel_data or {})
    return profile.to_dict()


@router.get("/youtube/retention")
def get_retention():
    from mindmargin.youtube_intelligence.retention import RetentionAnalyzer
    ra = RetentionAnalyzer()
    analyses = ra.list_analyses(1)
    return analyses[0].to_dict() if analyses else {"message": "No retention data yet"}


@router.post("/youtube/retention/analyze")
def analyze_retention(video_id: str = "", video_title: str = "",
                      data_points: list = None):
    from mindmargin.youtube_intelligence.retention import RetentionAnalyzer
    ra = RetentionAnalyzer()
    analysis = ra.analyze_video(video_id, video_title, data_points or [])
    return analysis.to_dict()


@router.get("/youtube/ctr")
def get_ctr():
    from mindmargin.youtube_intelligence.ctr import CTROptimizer
    co = CTROptimizer()
    report = co.get_latest()
    return report.to_dict() if report else {"message": "No CTR data yet"}


@router.post("/youtube/ctr/report")
def generate_ctr(data_points: list = None):
    from mindmargin.youtube_intelligence.ctr import CTROptimizer
    co = CTROptimizer()
    report = co.generate_report(data_points or [])
    return report.to_dict()


@router.get("/youtube/competition")
def get_competition():
    from mindmargin.youtube_intelligence.competition import CompetitionIntelligence
    ci = CompetitionIntelligence()
    report = ci.get_latest()
    return report.to_dict() if report else {"message": "No competition data yet"}


@router.post("/youtube/competition/report")
def generate_competition(channel_data: dict = None):
    from mindmargin.youtube_intelligence.competition import CompetitionIntelligence
    ci = CompetitionIntelligence()
    report = ci.generate_report(channel_data or {})
    return report.to_dict()


@router.get("/youtube/benchmarks")
def get_benchmarks():
    from mindmargin.youtube_intelligence.benchmark import BenchmarkEngine
    be = BenchmarkEngine()
    report = be.generate_report()
    return report.to_dict()


@router.get("/youtube/trends")
def get_trends():
    from mindmargin.youtube_intelligence.trends import TrendsEngine
    te = TrendsEngine()
    report = te.get_latest()
    return report.to_dict() if report else {"message": "No trends data yet"}


@router.post("/youtube/trends/analyze")
def analyze_trends(trend_data: list = None, your_topics: list = None):
    from mindmargin.youtube_intelligence.trends import TrendsEngine
    te = TrendsEngine()
    report = te.analyze_trends(trend_data or [], your_topics or [])
    return report.to_dict()


@router.get("/youtube/recommendations")
def get_recommendations(status: str = None, limit: int = 20):
    from mindmargin.youtube_intelligence.recommendations import YouTubeRecommendationEngine
    re = YouTubeRecommendationEngine()
    recs = re.list_recommendations(status=status, limit=limit)
    return {"recommendations": [r.to_dict() for r in recs], "count": len(recs)}


@router.post("/youtube/recommendations/generate")
def generate_recommendations(health: dict = None, growth: dict = None,
                              ctr: dict = None, audience: dict = None,
                              benchmarks: dict = None):
    from mindmargin.youtube_intelligence.recommendations import YouTubeRecommendationEngine
    re = YouTubeRecommendationEngine()
    recs = re.generate_all(health, growth, ctr, audience, benchmarks)
    return {"recommendations": [r.to_dict() for r in recs], "count": len(recs)}


@router.post("/youtube/full-analysis")
def run_full_analysis(channel_data: dict = None, topic_data: list = None,
                       content_history: list = None, video_data: list = None,
                       competitor_channels: list = None):
    from mindmargin.youtube_intelligence.optimizer import YouTubeOptimizer
    opt = YouTubeOptimizer()
    results = opt.run_full_analysis(
        channel_data or {}, topic_data or [], content_history or [],
        video_data or [], competitor_channels or [],
    )
    return results
