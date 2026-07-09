import json
import os
import time
from pathlib import Path
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta, timezone

import pytest

from mindmargin.content.models import (
    ContentItem, ContentAsset, ContentVersion, ContentRelationship,
    Recommendation, RepurposeSuggestion, LibraryReport,
    AssetType, ContentLifecycleState, OptimizationCategory,
    RepurposeFormat, RecommendationType, utcnow,
)


def _make_item(**overrides) -> ContentItem:
    defaults = {
        "content_id": f"ci_test_{int(time.time()*1000)}",
        "topic": "Test Topic",
        "lifecycle_state": ContentLifecycleState.PUBLISHED,
        "published_at": (datetime.now(timezone.utc) - timedelta(days=10)).isoformat(),
        "total_views": 500,
        "total_likes": 20,
        "total_comments": 5,
        "total_shares": 2,
        "ctr": 0.04,
        "avg_view_duration_s": 120.0,
        "view_velocity": 0.1,
        "engagement_rate": 0.05,
        "freshness_score": 0.7,
        "evergreen_score": 0.3,
        "decay_rate": 0.1,
        "optimization_category": "opportunity",
        "seo_score": 0.5,
        "keywords": ["python", "tutorial"],
        "tags": ["coding", "education"],
        "title": "Test Title",
        "description": "Test description",
        "category": "educational",
        "created_at": utcnow(),
        "updated_at": utcnow(),
    }
    defaults.update(overrides)
    return ContentItem(**defaults)


# ── Models ──

class TestContentItem:
    def test_create(self):
        item = _make_item(content_id="ci_1", topic="AI Basics")
        assert item.content_id == "ci_1"
        assert item.topic == "AI Basics"
        assert item.lifecycle_state == ContentLifecycleState.PUBLISHED

    def test_to_dict(self):
        item = _make_item(content_id="ci_2")
        d = item.to_dict()
        assert d["content_id"] == "ci_2"
        assert d["lifecycle_state"] == "published"

    def test_from_dict(self):
        d = {"content_id": "ci_3", "topic": "X", "lifecycle_state": "draft",
             "keywords": [], "tags": [], "assets": [], "versions": [],
             "relationships": [], "reuse_history": [], "analytics_snapshot": {},
             "metadata": {}, "created_at": "", "updated_at": ""}
        item = ContentItem.from_dict(d)
        assert item.lifecycle_state == ContentLifecycleState.DRAFT


class TestContentAsset:
    def test_create_asset(self):
        a = ContentAsset(asset_id="a1", content_id="c1", asset_type=AssetType.VIDEO)
        assert a.asset_type == AssetType.VIDEO

    def test_to_dict_roundtrip(self):
        a = ContentAsset(asset_id="a2", content_id="c1", asset_type=AssetType.THUMBNAIL, version=2)
        d = a.to_dict()
        assert d["asset_type"] == "thumbnail"
        a2 = ContentAsset.from_dict(d)
        assert a2.version == 2


class TestRecommendation:
    def test_create(self):
        r = Recommendation(
            recommendation_id="r1", content_id="c1",
            recommendation_type=RecommendationType.TITLE_REFRESH,
        )
        assert r.recommendation_type == RecommendationType.TITLE_REFRESH

    def test_to_dict_roundtrip(self):
        r = Recommendation(
            recommendation_id="r2", content_id="c1",
            recommendation_type=RecommendationType.SEO_UPDATE, priority=8,
        )
        d = r.to_dict()
        assert d["recommendation_type"] == "seo_update"
        r2 = Recommendation.from_dict(d)
        assert r2.priority == 8


class TestRepurposeSuggestion:
    def test_create(self):
        s = RepurposeSuggestion(
            suggestion_id="s1", source_content_id="c1",
            target_format=RepurposeFormat.SHORT,
        )
        assert s.target_format == RepurposeFormat.SHORT

    def test_to_dict_roundtrip(self):
        s = RepurposeSuggestion(
            suggestion_id="s2", source_content_id="c1",
            target_format=RepurposeFormat.BLOG, confidence=0.8,
        )
        d = s.to_dict()
        assert d["target_format"] == "blog"
        s2 = RepurposeSuggestion.from_dict(d)
        assert s2.confidence == 0.8


# ── Content Library ──

class TestContentLibrary:
    def test_add_and_get(self, tmp_path):
        from mindmargin.content.library import ContentLibrary
        lib = ContentLibrary(persist_dir=str(tmp_path))
        item = _make_item(content_id="ci_lib1", topic="Library Test")
        lib.add_item(item)
        got = lib.get_item("ci_lib1")
        assert got is not None
        assert got.topic == "Library Test"

    def test_list_items(self, tmp_path):
        from mindmargin.content.library import ContentLibrary
        lib = ContentLibrary(persist_dir=str(tmp_path))
        lib.add_item(_make_item(content_id="ci_l1", topic="A"))
        lib.add_item(_make_item(content_id="ci_l2", topic="B"))
        items = lib.list_items()
        assert len(items) == 2

    def test_list_by_state(self, tmp_path):
        from mindmargin.content.library import ContentLibrary
        lib = ContentLibrary(persist_dir=str(tmp_path))
        lib.add_item(_make_item(content_id="ci_s1", lifecycle_state=ContentLifecycleState.PUBLISHED))
        lib.add_item(_make_item(content_id="ci_s2", lifecycle_state=ContentLifecycleState.DRAFT))
        items = lib.list_items(state=ContentLifecycleState.PUBLISHED)
        assert len(items) == 1

    def test_search(self, tmp_path):
        from mindmargin.content.library import ContentLibrary
        lib = ContentLibrary(persist_dir=str(tmp_path))
        lib.add_item(_make_item(content_id="ci_search1", topic="Python Tutorial",
                               keywords=["python", "tutorial"]))
        lib.add_item(_make_item(content_id="ci_search2", topic="JavaScript Guide",
                               keywords=["javascript", "guide"]))
        results = lib.search_items("python")
        assert len(results) == 1

    def test_delete(self, tmp_path):
        from mindmargin.content.library import ContentLibrary
        lib = ContentLibrary(persist_dir=str(tmp_path))
        lib.add_item(_make_item(content_id="ci_del"))
        assert lib.delete_item("ci_del") is True
        assert lib.get_item("ci_del") is None

    def test_count_by_state(self, tmp_path):
        from mindmargin.content.library import ContentLibrary
        lib = ContentLibrary(persist_dir=str(tmp_path))
        lib.add_item(_make_item(content_id="ci_cs1", lifecycle_state=ContentLifecycleState.PUBLISHED))
        lib.add_item(_make_item(content_id="ci_cs2", lifecycle_state=ContentLifecycleState.DRAFT))
        counts = lib.count_by_state()
        assert counts.get("published", 0) == 1
        assert counts.get("draft", 0) == 1

    def test_import_from_pipeline(self, tmp_path):
        from mindmargin.content.library import ContentLibrary
        lib = ContentLibrary(persist_dir=str(tmp_path))
        item = lib.import_from_pipeline(
            pipeline_id="pipe1", topic="Imported Topic",
            video_id="vid1", title="Imported Title",
        )
        assert item.pipeline_id == "pipe1"
        assert item.video_id == "vid1"
        assert item.lifecycle_state == ContentLifecycleState.PUBLISHED


# ── Asset Manager ──

class TestAssetManager:
    def test_create_asset(self, tmp_path):
        from mindmargin.content.assets import AssetManager
        mgr = AssetManager(persist_dir=str(tmp_path))
        asset = mgr.create_asset("c1", AssetType.VIDEO, path="")
        assert asset.asset_type == AssetType.VIDEO
        assert asset.content_id == "c1"

    def test_list_assets(self, tmp_path):
        from mindmargin.content.assets import AssetManager
        mgr = AssetManager(persist_dir=str(tmp_path))
        mgr.create_asset("c1", AssetType.VIDEO)
        mgr.create_asset("c1", AssetType.THUMBNAIL)
        mgr.create_asset("c2", AssetType.VIDEO)
        assets = mgr.list_assets("c1")
        assert len(assets) == 2

    def test_get_asset(self, tmp_path):
        from mindmargin.content.assets import AssetManager
        mgr = AssetManager(persist_dir=str(tmp_path))
        asset = mgr.create_asset("c1", AssetType.SCRIPT)
        got = mgr.get_asset(asset.asset_id)
        assert got is not None
        assert got.asset_type == AssetType.SCRIPT

    def test_asset_stats(self, tmp_path):
        from mindmargin.content.assets import AssetManager
        mgr = AssetManager(persist_dir=str(tmp_path))
        mgr.create_asset("c1", AssetType.VIDEO)
        mgr.create_asset("c1", AssetType.THUMBNAIL)
        stats = mgr.get_asset_stats()
        assert stats["total"] == 2
        assert stats["by_type"]["video"] == 1

    def test_delete_asset(self, tmp_path):
        from mindmargin.content.assets import AssetManager
        mgr = AssetManager(persist_dir=str(tmp_path))
        asset = mgr.create_asset("c1", AssetType.VIDEO)
        assert mgr.delete_asset(asset.asset_id) is True
        assert mgr.get_asset(asset.asset_id) is None


# ── Lifecycle Manager ──

class TestContentLifecycleManager:
    def test_can_transition(self):
        from mindmargin.content.lifecycle import ContentLifecycleManager
        mgr = ContentLifecycleManager()
        item = _make_item(lifecycle_state=ContentLifecycleState.PUBLISHED)
        assert mgr.can_transition(item, ContentLifecycleState.GROWING) is True
        assert mgr.can_transition(item, ContentLifecycleState.DRAFT) is False

    def test_transition(self):
        from mindmargin.content.lifecycle import ContentLifecycleManager
        mgr = ContentLifecycleManager()
        item = _make_item(lifecycle_state=ContentLifecycleState.PUBLISHED)
        item = mgr.transition(item, ContentLifecycleState.GROWING)
        assert item.lifecycle_state == ContentLifecycleState.GROWING

    def test_classify_growing(self):
        from mindmargin.content.lifecycle import ContentLifecycleManager
        mgr = ContentLifecycleManager()
        item = _make_item(view_velocity=0.5)
        state = mgr.classify_lifecycle(item)
        assert state == ContentLifecycleState.GROWING

    def test_classify_evergreen(self):
        from mindmargin.content.lifecycle import ContentLifecycleManager
        mgr = ContentLifecycleManager()
        item = _make_item(
            published_at=(datetime.now(timezone.utc) - timedelta(days=90)).isoformat(),
            view_velocity=0.0,
        )
        state = mgr.classify_lifecycle(item)
        assert state == ContentLifecycleState.EVERGREEN

    def test_classify_declining(self):
        from mindmargin.content.lifecycle import ContentLifecycleManager
        mgr = ContentLifecycleManager()
        item = _make_item(
            published_at=(datetime.now(timezone.utc) - timedelta(days=40)).isoformat(),
            view_velocity=-0.5,
            total_views=100,
        )
        state = mgr.classify_lifecycle(item)
        assert state == ContentLifecycleState.DECLINING

    def test_freshness_score(self):
        from mindmargin.content.lifecycle import ContentLifecycleManager
        mgr = ContentLifecycleManager()
        item = _make_item(published_at=datetime.now(timezone.utc).isoformat())
        score = mgr.compute_freshness_score(item)
        assert score == 1.0

    def test_evergreen_score(self):
        from mindmargin.content.lifecycle import ContentLifecycleManager
        mgr = ContentLifecycleManager()
        item = _make_item(
            published_at=(datetime.now(timezone.utc) - timedelta(days=90)).isoformat(),
            view_velocity=0.0,
        )
        score = mgr.compute_evergreen_score(item)
        assert score > 0.3

    def test_detect_needs_refresh(self):
        from mindmargin.content.lifecycle import ContentLifecycleManager
        mgr = ContentLifecycleManager()
        item = _make_item(view_velocity=-0.6)
        assert mgr.detect_needs_refresh(item) is True

    def test_detect_archivable(self):
        from mindmargin.content.lifecycle import ContentLifecycleManager
        mgr = ContentLifecycleManager()
        item = _make_item(
            total_views=0,
            published_at=(datetime.now(timezone.utc) - timedelta(days=100)).isoformat(),
        )
        assert mgr.detect_archivable([item]) == [item]

    def test_update_item_scores(self):
        from mindmargin.content.lifecycle import ContentLifecycleManager
        mgr = ContentLifecycleManager()
        item = _make_item()
        item = mgr.update_item_scores(item)
        assert item.freshness_score > 0
        assert item.optimization_category != ""


# ── Optimizer ──

class TestContentOptimizer:
    def test_classify_viral(self):
        from mindmargin.content.optimizer import ContentOptimizer
        opt = ContentOptimizer()
        item = _make_item(view_velocity=0.8)
        cat = opt.classify_item(item)
        assert cat == OptimizationCategory.VIRAL

    def test_classify_evergreen(self):
        from mindmargin.content.optimizer import ContentOptimizer
        opt = ContentOptimizer()
        item = _make_item(evergreen_score=0.8)
        cat = opt.classify_item(item)
        assert cat == OptimizationCategory.EVERGREEN

    def test_classify_forgotten(self):
        from mindmargin.content.optimizer import ContentOptimizer
        opt = ContentOptimizer()
        item = _make_item(
            total_views=0,
            published_at=(datetime.now(timezone.utc) - timedelta(days=90)).isoformat(),
        )
        cat = opt.classify_item(item)
        assert cat == OptimizationCategory.FORGOTTEN

    def test_find_best_performing(self):
        from mindmargin.content.optimizer import ContentOptimizer
        opt = ContentOptimizer()
        items = [
            _make_item(content_id="c1", total_views=5000, ctr=0.08),
            _make_item(content_id="c2", total_views=100, ctr=0.02),
        ]
        best = opt.find_best_performing(items, limit=1)
        assert best[0].content_id == "c1"

    def test_find_viral(self):
        from mindmargin.content.optimizer import ContentOptimizer
        opt = ContentOptimizer()
        items = [
            _make_item(content_id="c1", view_velocity=0.9),
            _make_item(content_id="c2", view_velocity=-0.2),
        ]
        viral = opt.find_viral(items)
        assert len(viral) == 1

    def test_optimization_report(self):
        from mindmargin.content.optimizer import ContentOptimizer
        opt = ContentOptimizer()
        items = [_make_item(content_id=f"c{i}") for i in range(5)]
        report = opt.get_optimization_report(items)
        assert report["total_items"] == 5
        assert "categories" in report


# ── Repurpose ──

class TestContentRepurposer:
    def test_generate_suggestions(self, tmp_path):
        from mindmargin.content.repurpose import ContentRepurposer
        repurposer = ContentRepurposer(persist_dir=str(tmp_path))
        item = _make_item(
            total_views=1000, total_likes=50,
            metadata={"video_duration_s": 600, "word_count": 800},
        )
        suggestions = repurposer.generate_suggestions(item)
        assert len(suggestions) > 0

    def test_save_and_get_suggestions(self, tmp_path):
        from mindmargin.content.repurpose import ContentRepurposer
        repurposer = ContentRepurposer(persist_dir=str(tmp_path))
        item = _make_item(total_views=1000, metadata={"video_duration_s": 600, "word_count": 600})
        suggestions = repurposer.generate_suggestions(item)
        repurposer.save_suggestions(suggestions)
        got = repurposer.get_suggestions(content_id=item.content_id)
        assert len(got) > 0

    def test_mark_actioned(self, tmp_path):
        from mindmargin.content.repurpose import ContentRepurposer
        repurposer = ContentRepurposer(persist_dir=str(tmp_path))
        item = _make_item(total_views=1000, metadata={"video_duration_s": 600})
        suggestions = repurposer.generate_suggestions(item)
        repurposer.save_suggestions(suggestions)
        ok = repurposer.mark_actioned(suggestions[0].suggestion_id)
        assert ok is True


# ── SEO Refresh ──

class TestSEORefreshEngine:
    def test_analyze_seo_score(self):
        from mindmargin.content.seo_refresh import SEORefreshEngine
        seo = SEORefreshEngine()
        item = _make_item(title="Test", description="Desc", keywords=["a", "b", "c"],
                          tags=["t1", "t2"], ctr=0.05)
        score = seo.analyze_seo_score(item)
        assert score > 0.5

    def test_detect_title_refresh(self):
        from mindmargin.content.seo_refresh import SEORefreshEngine
        seo = SEORefreshEngine()
        item = _make_item(ctr=0.01)
        rec = seo.detect_title_refresh_needed(item)
        assert rec is not None
        assert rec.recommendation_type == RecommendationType.TITLE_REFRESH

    def test_detect_thumbnail_refresh(self):
        from mindmargin.content.seo_refresh import SEORefreshEngine
        seo = SEORefreshEngine()
        item = _make_item(ctr=0.01)
        rec = seo.detect_thumbnail_refresh_needed(item)
        assert rec is not None

    def test_detect_seo_update(self):
        from mindmargin.content.seo_refresh import SEORefreshEngine
        seo = SEORefreshEngine()
        item = _make_item(title="", description="", keywords=[], tags=[], ctr=0.0)
        rec = seo.detect_seo_update_needed(item)
        assert rec is not None

    def test_find_keyword_overlap(self):
        from mindmargin.content.seo_refresh import SEORefreshEngine
        seo = SEORefreshEngine()
        items = [
            _make_item(content_id="c1", keywords=["python", "ai"]),
            _make_item(content_id="c2", keywords=["python", "ml"]),
        ]
        overlaps = seo.find_keyword_overlap(items)
        assert any(o["keyword"] == "python" for o in overlaps)

    def test_find_duplicate_topics(self):
        from mindmargin.content.seo_refresh import SEORefreshEngine
        seo = SEORefreshEngine()
        items = [
            _make_item(content_id="c1", topic="Python Tutorial"),
            _make_item(content_id="c2", topic="python tutorial"),
        ]
        dupes = seo.find_duplicate_topics(items)
        assert len(dupes) == 1

    def test_seo_report(self):
        from mindmargin.content.seo_refresh import SEORefreshEngine
        seo = SEORefreshEngine()
        items = [_make_item(content_id=f"c{i}") for i in range(3)]
        report = seo.generate_seo_report(items)
        assert report["total_items"] == 3


# ── Archive ──

class TestContentArchiver:
    def test_archive_item(self, tmp_path):
        from mindmargin.content.archive import ContentArchiver
        archiver = ContentArchiver(persist_dir=str(tmp_path))
        item = _make_item(content_id="ci_arch1")
        item = archiver.archive_item(item, reason="test")
        assert item.lifecycle_state == ContentLifecycleState.ARCHIVED

    def test_restore_item(self, tmp_path):
        from mindmargin.content.archive import ContentArchiver
        archiver = ContentArchiver(persist_dir=str(tmp_path))
        item = _make_item(content_id="ci_arch2", lifecycle_state=ContentLifecycleState.ARCHIVED)
        item = archiver.restore_item(item)
        assert item.lifecycle_state == ContentLifecycleState.PUBLISHED

    def test_get_archive_records(self, tmp_path):
        from mindmargin.content.archive import ContentArchiver
        archiver = ContentArchiver(persist_dir=str(tmp_path))
        item = _make_item(content_id="ci_arch3")
        archiver.archive_item(item, reason="reason1")
        records = archiver.get_archive_records()
        assert len(records) == 1

    def test_archive_stats(self, tmp_path):
        from mindmargin.content.archive import ContentArchiver
        archiver = ContentArchiver(persist_dir=str(tmp_path))
        item = _make_item(content_id="ci_arch4", total_views=100)
        archiver.archive_item(item)
        stats = archiver.get_archive_stats()
        assert stats["total_archived"] == 1
        assert stats["total_views_when_archived"] == 100


# ── Reuse Detector ──

class TestContentReuseDetector:
    def test_detect_duplicate_topics(self):
        from mindmargin.content.reuse import ContentReuseDetector
        detector = ContentReuseDetector()
        items = [
            _make_item(content_id="c1", topic="AI Basics"),
            _make_item(content_id="c2", topic="ai basics"),
        ]
        dupes = detector.detect_duplicate_topics(items)
        assert len(dupes) == 1

    def test_detect_keyword_overlap(self):
        from mindmargin.content.reuse import ContentReuseDetector
        detector = ContentReuseDetector()
        items = [
            _make_item(content_id="c1", keywords=["python", "ai"]),
            _make_item(content_id="c2", keywords=["python", "ml"]),
        ]
        overlaps = detector.detect_keyword_overlap(items)
        assert any(o["keyword"] == "python" for o in overlaps)

    def test_detect_reuse_opportunities(self):
        from mindmargin.content.reuse import ContentReuseDetector
        detector = ContentReuseDetector()
        items = [
            _make_item(content_id="c1", total_views=600, evergreen_score=0.7),
        ]
        recs = detector.detect_reuse_opportunities(items)
        assert len(recs) > 0

    def test_detect_playlist_update(self):
        from mindmargin.content.reuse import ContentReuseDetector
        detector = ContentReuseDetector()
        items = [
            _make_item(content_id=f"c{i}", category="educational",
                       lifecycle_state=ContentLifecycleState.PUBLISHED)
            for i in range(4)
        ]
        recs = detector.detect_playlist_update_needed(items)
        assert len(recs) > 0


# ── Recommendation Engine ──

class TestRecommendationEngine:
    def test_generate_all(self, tmp_path):
        from mindmargin.content.recommendations import RecommendationEngine
        engine = RecommendationEngine(persist_dir=str(tmp_path))
        items = [_make_item(content_id="c1", ctr=0.01, total_views=1000,
                            metadata={"video_duration_s": 600, "word_count": 600})]
        recs = engine.generate_all_recommendations(items)
        assert len(recs) > 0

    def test_get_recommendations(self, tmp_path):
        from mindmargin.content.recommendations import RecommendationEngine
        engine = RecommendationEngine(persist_dir=str(tmp_path))
        items = [_make_item(content_id="c1", ctr=0.01)]
        engine.generate_all_recommendations(items)
        recs = engine.get_recommendations(status=None)
        assert len(recs) > 0

    def test_mark_actioned(self, tmp_path):
        from mindmargin.content.recommendations import RecommendationEngine
        engine = RecommendationEngine(persist_dir=str(tmp_path))
        items = [_make_item(content_id="c1", ctr=0.01)]
        recs = engine.generate_all_recommendations(items)
        ok = engine.mark_actioned(recs[0].recommendation_id)
        assert ok is True

    def test_recommendation_stats(self, tmp_path):
        from mindmargin.content.recommendations import RecommendationEngine
        engine = RecommendationEngine(persist_dir=str(tmp_path))
        items = [_make_item(content_id="c1", ctr=0.01)]
        engine.generate_all_recommendations(items)
        stats = engine.get_recommendation_stats()
        assert stats["total"] > 0


# ── REST API ──

class TestContentAPI:
    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from mindmargin.api.server import app
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c

    def test_library_endpoint(self, client):
        resp = client.get("/api/v1/content/library")
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "by_state" in data

    def test_assets_endpoint(self, client):
        resp = client.get("/api/v1/content/assets")
        assert resp.status_code == 200

    def test_lifecycle_endpoint(self, client):
        resp = client.get("/api/v1/content/lifecycle")
        assert resp.status_code == 200
        data = resp.json()
        assert "total" in data

    def test_optimize_endpoint(self, client):
        resp = client.get("/api/v1/content/optimize")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_items" in data

    def test_refresh_endpoint(self, client):
        resp = client.get("/api/v1/content/refresh")
        assert resp.status_code == 200

    def test_repurpose_endpoint(self, client):
        resp = client.get("/api/v1/content/repurpose")
        assert resp.status_code == 200

    def test_recommendations_endpoint(self, client):
        resp = client.get("/api/v1/content/recommendations")
        assert resp.status_code == 200

    def test_seo_endpoint(self, client):
        resp = client.get("/api/v1/content/seo")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_items" in data

    def test_archive_endpoint(self, client):
        resp = client.get("/api/v1/content/archive")
        assert resp.status_code == 200

    def test_reuse_endpoint(self, client):
        resp = client.get("/api/v1/content/reuse")
        assert resp.status_code == 200

    def test_report_endpoint(self, client):
        resp = client.get("/api/v1/content/report")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_items" in data

    def test_import_endpoint(self, client):
        resp = client.post("/api/v1/content/library/import",
                          params={"pipeline_id": "p1", "topic": "API Test"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["pipeline_id"] == "p1"
