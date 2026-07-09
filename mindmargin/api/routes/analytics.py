from datetime import datetime

from fastapi import APIRouter, HTTPException, Query

from mindmargin.api.schemas import (
    PipelineStats, AnalyticsResponse, DriftReportResponse,
    ABTestSummary, ABTestResponse,
)

router = APIRouter(tags=["Analytics"])


@router.get("/stats", response_model=PipelineStats)
def get_stats():
    from mindmargin.analytics.memory import get_pipeline_stats
    stats = get_pipeline_stats()
    return PipelineStats(
        total_pipelines=stats.get("total_pipelines", 0),
        published_videos=stats.get("published_videos", 0),
        total_views=stats.get("total_views", 0),
        total_likes=stats.get("total_likes", 0),
        total_comments=stats.get("total_comments", 0),
        total_shares=stats.get("total_shares", 0),
        avg_view_duration_s=stats.get("avg_view_duration_s", 0),
        best_hooks=stats.get("best_hooks", []),
        best_titles=stats.get("best_titles", []),
    )


@router.get("/analytics/{video_id}", response_model=AnalyticsResponse)
def get_video_analytics(video_id: str):
    from mindmargin.analytics.feedback import collect_analytics
    from mindmargin.analytics.memory import get_video_analytics_from_db
    db_analytics = get_video_analytics_from_db(video_id)
    if db_analytics:
        return AnalyticsResponse(
            video_id=video_id,
            status="completed",
            views=db_analytics.get("views", 0),
            likes=db_analytics.get("likes", 0),
            comments=db_analytics.get("comments", 0),
            shares=db_analytics.get("shares", 0),
            avg_view_duration_s=db_analytics.get("avg_view_duration_s", 0),
            subscribers_gained=db_analytics.get("subscribers_gained", 0),
        )
    result = collect_analytics("api", video_id)
    if result.get("status") == "completed":
        return AnalyticsResponse(
            video_id=video_id,
            status="completed",
            views=result.get("views", 0),
            likes=result.get("likes", 0),
            comments=result.get("comments", 0),
        )
    return AnalyticsResponse(video_id=video_id, status="error",
                            error=result.get("error", "unknown"))


@router.get("/analytics", response_model=list[AnalyticsResponse])
def list_analytics(limit: int = 50):
    from mindmargin.analytics.memory import get_analytics_history
    history = get_analytics_history(limit)
    return [
        AnalyticsResponse(
            video_id=h.get("video_id", ""),
            status="collected",
            views=h.get("views", 0),
            likes=h.get("likes", 0),
            comments=h.get("comments", 0),
            shares=h.get("shares", 0),
            avg_view_duration_s=h.get("avg_view_duration_s", 0),
            subscribers_gained=h.get("subscribers_gained", 0),
        )
        for h in history
    ]


@router.get("/drift", response_model=DriftReportResponse)
def get_drift_report():
    from mindmargin.analytics.patterns import generate_drift_report
    report = generate_drift_report()
    return DriftReportResponse(
        status=report.get("status", ""),
        drift=report.get("drift", {}),
        trends=report.get("trends", {}),
        generated_at=datetime.now().isoformat(timespec="seconds"),
    )


@router.get("/ab/tests", response_model=ABTestSummary)
def get_ab_status():
    from mindmargin.analytics.memory import (
        get_ab_win_loss_counts, get_active_ab_tests,
        get_pending_ab_tests, get_ab_evolution_history,
    )
    win_loss = get_ab_win_loss_counts()
    active = get_active_ab_tests()
    pending = get_pending_ab_tests()
    history = get_ab_evolution_history(500)
    return ABTestSummary(
        title_wins=win_loss.get("title_wins", 0),
        title_losses=win_loss.get("title_losses", 0),
        thumb_wins=win_loss.get("thumb_wins", 0),
        thumb_losses=win_loss.get("thumb_losses", 0),
        active_tests=len(active),
        pending_tests=len(pending),
        evolution_history_count=len(history),
    )


@router.post("/ab/run", response_model=ABTestResponse)
def run_ab_rotation():
    from mindmargin.analytics.ab_testing import run_ab_rotation_cycle
    result = run_ab_rotation_cycle(dry_run=False)
    return ABTestResponse(
        status=result.get("status", "completed"),
        actions_taken=result.get("actions_taken", 0),
        active_tests=result.get("active_tests", 0),
        actions=result.get("actions", []),
    )


@router.get("/ab/winners")
def get_ab_winners(limit: int = 10):
    from mindmargin.analytics.memory import get_ab_winning_titles, get_ab_winning_thumbnails
    titles = get_ab_winning_titles(limit)
    thumbs = get_ab_winning_thumbnails(limit)
    return {"titles": titles, "thumbnails": thumbs}


@router.get("/ab/history")
def get_ab_history(limit: int = 20):
    from mindmargin.analytics.memory import get_ab_evolution_history
    return {"history": get_ab_evolution_history(limit)}


@router.post("/ab/seed/{pipeline_id}", response_model=dict)
def seed_ab_variants(pipeline_id: str):
    from mindmargin.analytics.memory import _get_db
    from mindmargin.analytics.ab_testing import seed_variants
    conn = _get_db()
    row = conn.execute(
        "SELECT youtube_video_id FROM pipelines WHERE id = ?",
        (pipeline_id,),
    ).fetchone()
    if row and row["youtube_video_id"]:
        n = seed_variants(pipeline_id, row["youtube_video_id"])
        return {"status": "completed", "seeded": n, "pipeline_id": pipeline_id}
    raise HTTPException(status_code=404, detail=f"Pipeline {pipeline_id} not found or no video_id")


@router.get("/selection", response_model=dict)
def get_selection_status():
    from mindmargin.analytics.selection import get_evolution_memory_summary
    return get_evolution_memory_summary()


@router.post("/selection/run", response_model=dict)
def run_selection():
    from mindmargin.analytics.selection import run_selection_cycle, format_selection_report
    result = run_selection_cycle()
    return result
