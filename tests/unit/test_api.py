"""Tests for the REST API layer (Phase 10)."""

import json
import pytest
from unittest.mock import patch, MagicMock, PropertyMock
from datetime import datetime

from fastapi.testclient import TestClient

from mindmargin.api.server import app
from mindmargin.config import settings


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def mock_all_db(monkeypatch):
    """Mock all DB-heavy operations to prevent SQLite threading issues."""

    def mock_history(*a, **kw):
        return [
            {"id": "pipe-1", "topic": "Test", "status": "completed",
             "created_at": "2026-01-01T00:00:00", "youtube_video_id": "vid1"},
        ]

    def mock_stats(*a, **kw):
        return {
            "total_pipelines": 5, "published_videos": 3,
            "total_views": 1000, "total_likes": 100,
            "total_comments": 20, "total_shares": 10,
            "avg_view_duration_s": 300.0,
            "best_hooks": [], "best_titles": [],
        }

    def mock_analytics(*a, **kw):
        return [
            {"video_id": "vid1", "views": 500, "likes": 50,
             "comments": 10, "shares": 5, "avg_view_duration_s": 300.0,
             "subscribers_gained": 10},
        ]

    def mock_experiments(*a, **kw):
        return [
            {"experiment_id": "exp-1", "hypothesis": "test",
             "experiment_type": "topic_angle", "topic": "AI",
             "status": "draft", "variant_a": "", "variant_b": "",
             "expected_gain": 15, "affected_metric": "views",
             "confidence": 0.5, "winner": "", "created_at": "",
             "evaluated_at": ""},
        ]

    def mock_none(*a, **kw):
        return None

    def mock_empty_list(*a, **kw):
        return []

    def mock_empty_dict(*a, **kw):
        return {}

    def mock_win_loss(*a, **kw):
        return {"title_wins": 2, "title_losses": 1,
                "thumb_wins": 1, "thumb_losses": 0}

    def mock_ec(*a, **kw):
        return {"new_hypotheses": 3, "experiments_completed": 1,
                "timestamp": "2026-01-01T00:00:00"}

    def mock_fa(*a, **kw):
        return []

    def mock_pw(*a, **kw):
        return {"week_start": "2026-01-06", "week_end": "2026-01-12",
                "total_opportunities": 0, "ranked_count": 0,
                "schedule": [], "summary": {},
                "generated_at": "2026-01-06T00:00:00"}

    def mock_fb(*a, **kw):
        return {"outcomes_collected": 5, "weights_changed": 2,
                "weight_deltas": {}}

    def mock_exec(*a, **kw):
        return {"status": "completed", "topic": "AI",
                "pipeline_id": "pipe-1", "video_id": "vid1",
                "video_url": "https://youtube.com/watch?v=vid1"}

    def mock_di(*a, **kw):
        return {"status": "completed", "stages": {},
                "started_at": "2026-01-01T00:00:00"}

    def mock_bg(*a, **kw):
        return {"topics_found": 5, "keywords_extracted": 20,
                "relationships_created": 8}

    def mock_fadj(*a, **kw):
        return []

    def mock_geo(*a, **kw):
        return []

    def mock_dup(*a, **kw):
        return (False, "", 0.0)

    def mock_scoring(*a, **kw):
        return []

    # memory.py
    monkeypatch.setattr("mindmargin.analytics.memory.get_pipeline_history", mock_history)
    monkeypatch.setattr("mindmargin.analytics.memory.get_pipeline_stats", mock_stats)
    monkeypatch.setattr("mindmargin.analytics.memory.get_analytics_history", mock_analytics)
    monkeypatch.setattr("mindmargin.analytics.memory.get_experiments", mock_experiments)
    monkeypatch.setattr("mindmargin.analytics.memory.get_experiment", mock_none)
    monkeypatch.setattr("mindmargin.analytics.memory.get_active_experiments", mock_empty_list)
    monkeypatch.setattr("mindmargin.analytics.memory.get_forecasts", mock_empty_list)
    monkeypatch.setattr("mindmargin.analytics.memory.get_weekly_plans", mock_empty_list)
    monkeypatch.setattr("mindmargin.analytics.memory.get_opportunities", mock_empty_list)
    monkeypatch.setattr("mindmargin.analytics.memory.get_ab_win_loss_counts", mock_win_loss)
    monkeypatch.setattr("mindmargin.analytics.memory.get_active_ab_tests", mock_empty_list)
    monkeypatch.setattr("mindmargin.analytics.memory.get_pending_ab_tests", mock_empty_list)
    monkeypatch.setattr("mindmargin.analytics.memory.get_ab_evolution_history", mock_empty_list)
    monkeypatch.setattr("mindmargin.analytics.memory.get_ab_winning_titles", mock_empty_list)
    monkeypatch.setattr("mindmargin.analytics.memory.get_ab_winning_thumbnails", mock_empty_list)
    monkeypatch.setattr("mindmargin.analytics.memory.get_execution_log", mock_empty_list)
    monkeypatch.setattr("mindmargin.analytics.memory.get_topic_relationships", mock_empty_list)
    # analytics patterns
    monkeypatch.setattr("mindmargin.analytics.patterns.generate_drift_report", mock_ec)
    # intelligence
    monkeypatch.setattr("mindmargin.intelligence.scoring.run_opportunity_scoring", mock_scoring)
    monkeypatch.setattr("mindmargin.intelligence.experiments.run_experiment_cycle", mock_ec)
    monkeypatch.setattr("mindmargin.intelligence.horizon.forecast_all", mock_fa)
    monkeypatch.setattr("mindmargin.intelligence.planner.plan_week", mock_pw)
    monkeypatch.setattr("mindmargin.intelligence.knowledge_graph.build_knowledge_graph", mock_bg)
    monkeypatch.setattr("mindmargin.intelligence.knowledge_graph.find_adjacent", mock_fadj)
    monkeypatch.setattr("mindmargin.intelligence.knowledge_graph.KnowledgeGraph.get_expansion_opportunities", mock_geo)
    monkeypatch.setattr("mindmargin.intelligence.knowledge_graph.KnowledgeGraph.is_duplicate_coverage", mock_dup)
    monkeypatch.setattr("mindmargin.intelligence.feedback_engine.run_feedback_cycle", mock_fb)
    # agents
    monkeypatch.setattr("mindmargin.agents.decision_executor.execute_top_decision", mock_exec)
    # analytics memory db (for seed_ab etc.)
    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchone.return_value = None
    monkeypatch.setattr("mindmargin.analytics.memory._get_db", lambda: mock_conn)
    # jobs
    monkeypatch.setattr("mindmargin.jobs.daily_intelligence.run_intelligence_cycle", mock_di)


# ── Health Endpoints ──

class TestHealth:
    def test_root_endpoint(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "MindMargin API"

    def test_health_check(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data
        assert "environment" in data
        assert "checkers" in data


# ── Pipeline Endpoints ──

class TestPipelines:
    @patch("mindmargin.api.routes.pipelines.Pipeline")
    def test_start_pipeline(self, mock_pipeline_class, client):
        mock_pipe = MagicMock()
        mock_pipe.pipeline_id = "test-pipe-001"
        mock_pipe.topic = "test"
        mock_pipe.status = "completed"
        mock_pipe.state = {"research": {}, "script": {}, "voice": {}, "editing": {}}
        mock_pipe.errors = []
        mock_pipe.run.return_value = {
            "pipeline_id": "test-pipe-001", "topic": "test",
            "status": "completed",
            "completed_agents": ["research", "script", "voice", "editing"],
            "errors": [], "output_dir": "/tmp/test",
            "timing_s": 42.0, "video_path": "/tmp/test/video.mp4",
        }
        mock_pipeline_class.return_value = mock_pipe
        resp = client.post("/api/v1/pipeline", json={
            "topic": "AI Trends", "quick": True, "mode": "documentary",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "completed"

    def test_list_pipelines(self, client):
        resp = client.get("/api/v1/pipelines")
        assert resp.status_code == 200
        data = resp.json()
        assert "active" in data
        assert "historical" in data

    def test_get_pipeline_not_found(self, client):
        resp = client.get("/api/v1/pipeline/nonexistent")
        assert resp.status_code == 404


# ── Job Endpoints ──

class TestJobs:
    def test_list_jobs(self, client):
        resp = client.get("/api/v1/jobs")
        assert resp.status_code == 200
        data = resp.json()
        assert "jobs" in data
        assert "total" in data

    def test_get_job_not_found(self, client):
        resp = client.get("/api/v1/jobs/nonexistent")
        assert resp.status_code == 404

    def test_cancel_job_not_found(self, client):
        resp = client.post("/api/v1/jobs/nonexistent/cancel")
        assert resp.status_code == 404

    def test_retry_job_not_found(self, client):
        resp = client.post("/api/v1/jobs/nonexistent/retry")
        assert resp.status_code == 404


# ── Analytics Endpoints ──

class TestAnalytics:
    def test_get_stats(self, client):
        resp = client.get("/api/v1/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert "total_pipelines" in data
        assert "published_videos" in data

    def test_list_analytics(self, client):
        resp = client.get("/api/v1/analytics")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_get_analytics(self, client):
        resp = client.get("/api/v1/analytics/nonexistent_video")
        data = resp.json()
        assert data["status"] in ("error", "completed")

    def test_get_drift_report(self, client):
        resp = client.get("/api/v1/drift")
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data

    def test_ab_status(self, client):
        resp = client.get("/api/v1/ab/tests")
        assert resp.status_code == 200
        data = resp.json()
        assert "active_tests" in data
        assert "title_wins" in data

    def test_ab_winners(self, client):
        resp = client.get("/api/v1/ab/winners")
        assert resp.status_code == 200
        data = resp.json()
        assert "titles" in data
        assert "thumbnails" in data

    def test_ab_history(self, client):
        resp = client.get("/api/v1/ab/history")
        assert resp.status_code == 200
        data = resp.json()
        assert "history" in data

    def test_selection_status(self, client):
        resp = client.get("/api/v1/selection")
        assert resp.status_code == 200

    def test_seed_ab_not_found(self, client):
        resp = client.post("/api/v1/ab/seed/nonexistent")
        assert resp.status_code == 404


# ── Intelligence Endpoints ──

class TestIntelligence:
    def test_list_experiments(self, client):
        resp = client.get("/api/v1/experiments")
        assert resp.status_code == 200
        data = resp.json()
        assert "experiments" in data

    def test_get_experiment_not_found(self, client):
        resp = client.get("/api/v1/experiments/nonexistent")
        assert resp.status_code == 404

    def test_run_experiments(self, client):
        resp = client.post("/api/v1/experiments/run")
        assert resp.status_code == 200
        data = resp.json()
        assert "new_hypotheses" in data

    def test_run_forecasts(self, client):
        resp = client.post("/api/v1/forecasts/run")
        assert resp.status_code == 200
        data = resp.json()
        assert "forecasts_generated" in data

    def test_get_forecasts(self, client):
        resp = client.get("/api/v1/forecasts")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_get_forecasts_filtered(self, client):
        resp = client.get("/api/v1/forecasts?window_days=7")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_generate_weekly_plan(self, client):
        resp = client.post("/api/v1/plans/weekly/run")
        assert resp.status_code == 200
        data = resp.json()
        assert "week_start" in data

    def test_get_weekly_plans(self, client):
        resp = client.get("/api/v1/plans/weekly")
        assert resp.status_code == 200
        data = resp.json()
        assert "plans" in data

    def test_build_graph(self, client):
        resp = client.post("/api/v1/graph/build")
        assert resp.status_code == 200
        data = resp.json()
        assert "topics_found" in data
        assert data["topics_found"] == 5

    def test_get_adjacent_topics(self, client):
        resp = client.get("/api/v1/graph/adjacent/AI")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_get_expansion_opportunities(self, client):
        resp = client.get("/api/v1/graph/expansion")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_check_duplicate(self, client):
        resp = client.get("/api/v1/graph/duplicate?topic=AI")
        assert resp.status_code == 200
        data = resp.json()
        assert "is_duplicate" in data

    def test_check_duplicate_missing_param(self, client):
        resp = client.get("/api/v1/graph/duplicate")
        assert resp.status_code == 422

    def test_run_scoring(self, client):
        resp = client.post("/api/v1/scoring/run")
        assert resp.status_code == 200
        data = resp.json()
        assert "candidates_scored" in data

    def test_get_opportunities(self, client):
        resp = client.get("/api/v1/opportunities")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_get_opportunities_filtered(self, client):
        resp = client.get("/api/v1/opportunities?min_score=50")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_run_intelligence_cycle(self, client):
        resp = client.post("/api/v1/intelligence/run")
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data


# ── Decision Endpoints ──

class TestDecisions:
    def test_execute_decision(self, client):
        resp = client.post("/api/v1/decisions/execute")
        assert resp.status_code == 200
        data = resp.json()
        assert "status" in data

    def test_explain_decision_not_found(self, client):
        resp = client.post("/api/v1/decisions/explain?topic=nonexistent_topic_xyz")
        assert resp.status_code == 404

    def test_run_feedback(self, client):
        resp = client.post("/api/v1/feedback/run")
        assert resp.status_code == 200
        data = resp.json()
        assert "outcomes_collected" in data

    def test_get_execution_log(self, client):
        resp = client.get("/api/v1/execution-log")
        assert resp.status_code == 200
        data = resp.json()
        assert "log" in data


# ── Schema Validation ──

class TestSchemas:
    def test_pipeline_request_missing_topic(self, client):
        resp = client.post("/api/v1/pipeline", json={})
        assert resp.status_code == 422




# ── CORS ──

class TestCORS:
    def test_cors_headers(self, client):
        resp = client.options("/health", headers={
            "Origin": "http://example.com",
            "Access-Control-Request-Method": "GET",
        })
        assert resp.status_code == 200
        assert resp.headers.get("access-control-allow-origin") is not None
        assert resp.headers.get("access-control-allow-methods") is not None


# ── Error Handling ──

class TestErrorHandling:
    def test_404_json(self, client):
        resp = client.get("/api/v1/nonexistent-route")
        assert resp.status_code == 404

    def test_method_not_allowed(self, client):
        resp = client.delete("/api/v1/stats")
        assert resp.status_code in (405, 404)
