from fastapi import APIRouter, Query
from typing import Optional

from mindmargin.content.library import ContentLibrary
from mindmargin.content.assets import AssetManager
from mindmargin.content.lifecycle import ContentLifecycleManager
from mindmargin.content.optimizer import ContentOptimizer
from mindmargin.content.repurpose import ContentRepurposer
from mindmargin.content.archive import ContentArchiver
from mindmargin.content.seo_refresh import SEORefreshEngine
from mindmargin.content.reuse import ContentReuseDetector
from mindmargin.content.recommendations import RecommendationEngine
from mindmargin.content.models import (
    ContentItem, ContentLifecycleState, OptimizationCategory,
    RecommendationType, RepurposeFormat, utcnow,
)

router = APIRouter(prefix="/api/v1/content", tags=["content"])


@router.get("/library")
def content_library(
    state: Optional[str] = None,
    category: Optional[str] = None,
    limit: int = Query(50, ge=1, le=500),
):
    lib = ContentLibrary()
    st = ContentLifecycleState(state) if state else None
    items = lib.list_items(state=st, category=category, limit=limit)
    return {
        "total": lib.get_total_count(),
        "items": [it.to_dict() for it in items],
        "by_state": lib.count_by_state(),
        "by_category": lib.count_by_category(),
    }


@router.get("/library/{content_id}")
def content_detail(content_id: str):
    lib = ContentLibrary()
    item = lib.get_item(content_id)
    if not item:
        return {"error": "Content not found"}
    return item.to_dict()


@router.post("/library/import")
def import_from_pipeline(
    pipeline_id: str = "",
    topic: str = "",
    video_id: str = "",
    title: str = "",
    description: str = "",
    category: str = "",
):
    lib = ContentLibrary()
    item = lib.import_from_pipeline(
        pipeline_id=pipeline_id, topic=topic, video_id=video_id,
        title=title, description=description, category=category,
    )
    return item.to_dict()


@router.get("/assets")
def content_assets(
    content_id: Optional[str] = None,
    asset_type: Optional[str] = None,
    limit: int = Query(100, ge=1, le=1000),
):
    mgr = AssetManager()
    from mindmargin.content.models import AssetType
    at = AssetType(asset_type) if asset_type else None
    if content_id:
        assets = mgr.list_assets(content_id, asset_type=at)
    else:
        assets = mgr.list_all_assets(asset_type=at, limit=limit)
    return {
        "total": len(assets),
        "assets": [a.to_dict() for a in assets],
        "stats": mgr.get_asset_stats(),
    }


@router.get("/lifecycle")
def content_lifecycle():
    lib = ContentLibrary()
    lifecycle = ContentLifecycleManager()
    items = lib.list_items(limit=500)
    report = {
        "total": len(items),
        "by_state": {},
        "needs_refresh": 0,
        "archivable": 0,
        "transitions_available": {},
    }
    for item in items:
        state = item.lifecycle_state.value
        report["by_state"][state] = report["by_state"].get(state, 0) + 1
        if lifecycle.detect_needs_refresh(item):
            report["needs_refresh"] += 1
        if lifecycle.detect_archivable([item]):
            report["archivable"] += 1
    return report


@router.post("/lifecycle/{content_id}/transition")
def transition_content(content_id: str, target_state: str):
    lib = ContentLibrary()
    lifecycle = ContentLifecycleManager()
    item = lib.get_item(content_id)
    if not item:
        return {"error": "Content not found"}
    new_state = ContentLifecycleState(target_state)
    item = lifecycle.transition(item, new_state)
    lib.update_item(item)
    return {"status": "ok", "new_state": item.lifecycle_state.value}


@router.get("/optimize")
def content_optimize(
    category: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
):
    lib = ContentLibrary()
    optimizer = ContentOptimizer()
    items = lib.list_items(limit=limit)
    report = optimizer.get_optimization_report(items)

    if category:
        cat = OptimizationCategory(category)
        if cat == OptimizationCategory.BEST_PERFORMING:
            report["items"] = [it.to_dict() for it in optimizer.find_best_performing(items)]
        elif cat == OptimizationCategory.UNDERPERFORMING:
            report["items"] = [it.to_dict() for it in optimizer.find_underperforming(items)]
        elif cat == OptimizationCategory.FORGOTTEN:
            report["items"] = [it.to_dict() for it in optimizer.find_forgotten(items)]
        elif cat == OptimizationCategory.VIRAL:
            report["items"] = [it.to_dict() for it in optimizer.find_viral(items)]
        elif cat == OptimizationCategory.EVERGREEN:
            report["items"] = [it.to_dict() for it in optimizer.find_evergreen(items)]
        elif cat == OptimizationCategory.DECAYING:
            report["items"] = [it.to_dict() for it in optimizer.find_decaying(items)]
        else:
            report["items"] = []
    else:
        report["items"] = []

    return report


@router.get("/refresh")
def content_refresh():
    lib = ContentLibrary()
    lifecycle = ContentLifecycleManager()
    items = lib.list_items(limit=500)
    needs_refresh = []
    for item in items:
        if lifecycle.detect_needs_refresh(item):
            item = lifecycle.update_item_scores(item)
            needs_refresh.append(item.to_dict())
            lib.update_item(item)
    return {
        "total_checked": len(items),
        "needs_refresh": len(needs_refresh),
        "items": needs_refresh,
    }


@router.get("/repurpose")
def content_repurpose(
    content_id: Optional[str] = None,
    format: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
):
    repurposer = ContentRepurposer()
    fmt = RepurposeFormat(format) if format else None
    suggestions = repurposer.get_suggestions(content_id=content_id, target_format=fmt, limit=limit)
    return {
        "total": len(suggestions),
        "suggestions": [s.to_dict() for s in suggestions],
    }


@router.post("/repurpose/generate")
def generate_repurpose_suggestions(content_id: str):
    lib = ContentLibrary()
    repurposer = ContentRepurposer()
    item = lib.get_item(content_id)
    if not item:
        return {"error": "Content not found"}
    suggestions = repurposer.generate_suggestions(item)
    repurposer.save_suggestions(suggestions)
    return {
        "content_id": content_id,
        "suggestions_generated": len(suggestions),
        "suggestions": [s.to_dict() for s in suggestions],
    }


@router.get("/recommendations")
def content_recommendations(
    content_id: Optional[str] = None,
    type: Optional[str] = None,
    status: str = "pending",
    limit: int = Query(50, ge=1, le=200),
):
    engine = RecommendationEngine()
    rec_type = RecommendationType(type) if type else None
    recs = engine.get_recommendations(content_id=content_id, rec_type=rec_type,
                                       status=status, limit=limit)
    stats = engine.get_recommendation_stats()
    return {
        "total": len(recs),
        "recommendations": [r.to_dict() for r in recs],
        "stats": stats,
    }


@router.post("/recommendations/generate")
def generate_all_recommendations():
    lib = ContentLibrary()
    engine = RecommendationEngine()
    items = lib.list_items(limit=500)
    recs = engine.generate_all_recommendations(items)
    return {
        "total_items": len(items),
        "recommendations_generated": len(recs),
    }


@router.put("/recommendations/{recommendation_id}/action")
def action_recommendation(recommendation_id: str, status: str = "actioned"):
    engine = RecommendationEngine()
    ok = engine.mark_actioned(recommendation_id, status)
    if not ok:
        return {"error": "Recommendation not found"}
    return {"status": "ok", "recommendation_id": recommendation_id, "new_status": status}


@router.get("/seo")
def content_seo_report():
    lib = ContentLibrary()
    seo = SEORefreshEngine()
    items = lib.list_items(limit=500)
    return seo.generate_seo_report(items)


@router.get("/archive")
def content_archive(limit: int = Query(50, ge=1, le=200)):
    archiver = ContentArchiver()
    records = archiver.get_archive_records(limit=limit)
    stats = archiver.get_archive_stats()
    return {
        "total": stats["total_archived"],
        "records": records,
        "stats": stats,
    }


@router.post("/archive/{content_id}")
def archive_content(content_id: str, reason: str = "manual"):
    lib = ContentLibrary()
    archiver = ContentArchiver()
    item = lib.get_item(content_id)
    if not item:
        return {"error": "Content not found"}
    item = archiver.archive_item(item, reason=reason)
    lib.update_item(item)
    return {"status": "ok", "archived": content_id, "reason": reason}


@router.post("/archive/{content_id}/restore")
def restore_content(content_id: str):
    lib = ContentLibrary()
    archiver = ContentArchiver()
    item = lib.get_item(content_id)
    if not item:
        return {"error": "Content not found"}
    item = archiver.restore_item(item)
    lib.update_item(item)
    return {"status": "ok", "restored": content_id}


@router.get("/reuse")
def content_reuse():
    lib = ContentLibrary()
    reuse_detector = ContentReuseDetector()
    items = lib.list_items(limit=500)
    duplicates = reuse_detector.detect_duplicate_topics(items)
    overlaps = reuse_detector.detect_keyword_overlap(items)
    republish = reuse_detector.detect_republish_candidates(items)
    playlist_recs = reuse_detector.detect_playlist_update_needed(items)
    return {
        "duplicate_topics": duplicates,
        "keyword_overlaps": overlaps[:20],
        "republish_candidates": len(republish),
        "playlist_recommendations": len(playlist_recs),
    }


@router.get("/report")
def content_library_report():
    lib = ContentLibrary()
    optimizer = ContentOptimizer()
    lifecycle = ContentLifecycleManager()
    engine = RecommendationEngine()
    items = lib.list_items(limit=500)
    report = optimizer.get_optimization_report(items)

    seo_scores = []
    needs_refresh = 0
    for item in items:
        item = lifecycle.update_item_scores(item)
        seo_scores.append(item.seo_score)
        if lifecycle.detect_needs_refresh(item):
            needs_refresh += 1

    rec_stats = engine.get_recommendation_stats()
    avg_seo = sum(seo_scores) / len(seo_scores) if seo_scores else 0

    return {
        "total_items": len(items),
        "by_state": lib.count_by_state(),
        "by_category": lib.count_by_category(),
        "optimization": report,
        "avg_seo_score": round(avg_seo, 3),
        "needs_refresh": needs_refresh,
        "recommendations": rec_stats,
    }
