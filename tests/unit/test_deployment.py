import json
import logging
import os
import sys
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    from mindmargin.api.server import app
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


HAS_REDIS = False
try:
    import redis as _redis_mod
    HAS_REDIS = True
except ImportError:
    pass


# ── Health Endpoints ──

class TestHealthCheckers:
    def test_check_config_pass(self):
        from mindmargin.api.routes.health import _check_config
        result = _check_config()
        assert result.checker == "config"
        assert result.status == "pass"

    def test_check_database_pass(self, tmp_path):
        from mindmargin.api.routes.health import _check_database
        result = _check_database()
        assert result.checker == "database"
        assert result.status == "pass"

    @pytest.mark.skipif(not HAS_REDIS, reason="redis module not installed")
    def test_check_redis_pass(self):
        from mindmargin.api.routes.health import _check_redis
        with patch("mindmargin.api.routes.health.settings") as mock_settings:
            mock_settings.redis_url = "redis://localhost:6379/0"
            with patch("redis.Redis") as MockRedis:
                MockRedis.return_value.ping.return_value = True
                result = _check_redis()
                assert result.checker == "redis"
                assert result.status == "pass"

    @pytest.mark.skipif(not HAS_REDIS, reason="redis module not installed")
    def test_check_redis_fail(self):
        from mindmargin.api.routes.health import _check_redis
        with patch("mindmargin.api.routes.health.settings") as mock_settings:
            mock_settings.redis_url = "redis://localhost:6379/0"
            with patch("redis.Redis") as MockRedis:
                MockRedis.return_value.ping.side_effect = ConnectionError("refused")
                result = _check_redis()
                assert result.status == "critical"

    def test_check_redis_import_error(self):
        from mindmargin.api.routes.health import _check_redis
        with patch("mindmargin.api.routes.health.settings") as mock_settings:
            mock_settings.redis_url = "redis://localhost:6379/0"
            with patch.dict(sys.modules, {"redis": None}):
                result = _check_redis()
                assert result.status == "critical"

    def test_check_ollama_pass(self):
        from mindmargin.api.routes.health import _check_ollama
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"models": [{"name": "llama3"}]}
        with patch("httpx.get", return_value=mock_resp):
            result = _check_ollama()
            assert result.checker == "ollama"
            assert result.status == "pass"
            assert result.value == 1.0

    def test_check_ollama_fail(self):
        from mindmargin.api.routes.health import _check_ollama
        with patch("httpx.get", side_effect=ConnectionError("refused")):
            result = _check_ollama()
            assert result.status == "warning"

    def test_check_disk_pass(self):
        from mindmargin.api.routes.health import _check_disk
        result = _check_disk()
        assert result.checker == "disk"
        assert result.status in ("pass", "warning")

    def test_check_llm_pass(self):
        from mindmargin.api.routes.health import _check_llm
        with patch("mindmargin.integrations.manager.create_default_manager") as mock_pm:
            mock_pm.return_value.available = ["ollama", "openai"]
            result = _check_llm()
            assert result.checker == "llm"
            assert result.status == "pass"

    def test_check_pipelines_pass(self):
        from mindmargin.api.routes.health import _check_pipelines
        result = _check_pipelines()
        assert result.checker == "pipelines"
        assert result.status == "pass"


class TestHealthEndpoints:
    def test_health_check_returns_report(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] in ("pass", "degraded", "fail")
        assert "checkers" in data
        assert len(data["checkers"]) >= 4

    def test_health_check_counts(self, client):
        resp = client.get("/health")
        data = resp.json()
        total = data["pass_count"] + data["warning_count"] + data["failed_count"]
        assert total == len(data["checkers"])

    def test_readiness_check(self, client):
        resp = client.get("/readiness")
        assert resp.status_code == 200
        data = resp.json()
        assert "ready" in data
        assert "checks" in data
        assert "config" in data["checks"]
        assert "database" in data["checks"]

    def test_readiness_critical_blocks(self, client):
        resp = client.get("/readiness")
        data = resp.json()
        if data["checks"].get("config") == "critical" or data["checks"].get("database") == "critical":
            assert data["ready"] is False

    def test_liveness_check(self, client):
        resp = client.get("/liveness")
        assert resp.status_code == 200
        data = resp.json()
        assert data["alive"] is True
        assert "uptime_s" in data
        assert "timestamp" in data


# ── Structured Logging ──

class TestStructuredLogging:
    def test_json_formatter(self):
        from mindmargin.monitoring import JSONFormatter
        fmt = JSONFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="test.py",
            lineno=1, msg="test message", args=(), exc_info=None,
        )
        output = fmt.format(record)
        data = json.loads(output)
        assert data["level"] == "INFO"
        assert data["message"] == "test message"
        assert "timestamp" in data

    def test_human_formatter(self):
        from mindmargin.monitoring import HumanFormatter
        fmt = HumanFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="test.py",
            lineno=1, msg="test message", args=(), exc_info=None,
        )
        output = fmt.format(record)
        assert "INFO" in output
        assert "test message" in output

    def test_setup_structured_logging_json(self, tmp_path):
        from mindmargin.monitoring import setup_structured_logging
        with patch("mindmargin.monitoring.settings") as mock_settings:
            mock_settings.log_level = "INFO"
            mock_settings.storage.output_root = str(tmp_path)
            mock_settings.production.enable_structured_logs = True
            logger = setup_structured_logging("test_json", json_output=True)
            assert logger is not None
            assert len(logger.handlers) >= 2

    def test_setup_structured_logging_human(self, tmp_path):
        from mindmargin.monitoring import setup_structured_logging
        with patch("mindmargin.monitoring.settings") as mock_settings:
            mock_settings.log_level = "DEBUG"
            mock_settings.storage.output_root = str(tmp_path)
            mock_settings.production.enable_structured_logs = False
            logger = setup_structured_logging("test_human", json_output=False)
            assert logger is not None

    def test_request_id_context_var(self):
        from mindmargin.monitoring import request_id
        assert request_id.get() is None
        token = request_id.set("test-123")
        assert request_id.get() == "test-123"
        request_id.reset(token)
        assert request_id.get() is None

    def test_timer_context_manager(self):
        from mindmargin.monitoring import Timer
        with Timer("test_op") as t:
            time.sleep(0.01)
        assert t.duration > 0

    def test_log_operation(self):
        from mindmargin.monitoring import log_operation
        log_operation("test_op", param1="value1")

    def test_log_metric(self):
        from mindmargin.monitoring import log_metric
        log_metric("test_metric", 42.0, env="test")

    def test_json_formatter_with_exception(self):
        from mindmargin.monitoring import JSONFormatter
        fmt = JSONFormatter()
        try:
            raise ValueError("test error")
        except ValueError:
            import sys
            exc_info = sys.exc_info()
        record = logging.LogRecord(
            name="test", level=logging.ERROR, pathname="test.py",
            lineno=1, msg="error occurred", args=(), exc_info=exc_info,
        )
        output = fmt.format(record)
        data = json.loads(output)
        assert "exception" in data
        assert "ValueError" in data["exception"]

    def test_json_formatter_with_request_id(self):
        from mindmargin.monitoring import JSONFormatter, request_id
        fmt = JSONFormatter()
        token = request_id.set("req-456")
        try:
            record = logging.LogRecord(
                name="test", level=logging.INFO, pathname="test.py",
                lineno=1, msg="with id", args=(), exc_info=None,
            )
            output = fmt.format(record)
            data = json.loads(output)
            assert data["request_id"] == "req-456"
        finally:
            request_id.reset(token)


# ── Docker/Deploy ──

class TestDockerConfig:
    def test_dockerfile_api_exists(self):
        path = Path(__file__).resolve().parent.parent.parent / "deploy" / "docker" / "Dockerfile.api"
        assert path.exists()

    def test_dockerfile_worker_exists(self):
        path = Path(__file__).resolve().parent.parent.parent / "deploy" / "docker" / "Dockerfile.worker"
        assert path.exists()

    def test_dockerfile_cli_exists(self):
        path = Path(__file__).resolve().parent.parent.parent / "deploy" / "docker" / "Dockerfile.cli"
        assert path.exists()

    def test_dockerfile_api_has_healthcheck(self):
        path = Path(__file__).resolve().parent.parent.parent / "deploy" / "docker" / "Dockerfile.api"
        content = path.read_text()
        assert "HEALTHCHECK" in content

    def test_dockerfile_api_has_user(self):
        path = Path(__file__).resolve().parent.parent.parent / "deploy" / "docker" / "Dockerfile.api"
        content = path.read_text()
        assert "USER mindmargin" in content

    def test_docker_compose_main(self):
        path = Path(__file__).resolve().parent.parent.parent / "deploy" / "docker" / "docker-compose.yml"
        assert path.exists()
        content = path.read_text()
        assert "redis:" in content
        assert "api:" in content
        assert "worker:" in content

    def test_docker_compose_prod(self):
        path = Path(__file__).resolve().parent.parent.parent / "deploy" / "docker" / "docker-compose.prod.yml"
        assert path.exists()
        content = path.read_text()
        assert "nginx:" in content

    def test_docker_compose_staging(self):
        path = Path(__file__).resolve().parent.parent.parent / "deploy" / "docker" / "docker-compose.staging.yml"
        assert path.exists()

    def test_nginx_config(self):
        path = Path(__file__).resolve().parent.parent.parent / "deploy" / "docker" / "nginx.conf"
        assert path.exists()
        content = path.read_text()
        assert "proxy_pass" in content
        assert "/health" in content

    def test_dockerignore(self):
        path = Path(__file__).resolve().parent.parent.parent / "deploy" / "docker" / ".dockerignore"
        assert path.exists()
        content = path.read_text()
        assert ".env" in content
        assert "__pycache__" in content


# ── CI/CD ──

class TestCICD:
    def test_ci_workflow_exists(self):
        path = Path(__file__).resolve().parent.parent.parent / ".github" / "workflows" / "ci.yml"
        assert path.exists()

    def test_daily_job_workflow_exists(self):
        path = Path(__file__).resolve().parent.parent.parent / ".github" / "workflows" / "daily_job.yml"
        assert path.exists()

    def test_deploy_workflow_exists(self):
        path = Path(__file__).resolve().parent.parent.parent / ".github" / "workflows" / "deploy.yml"
        assert path.exists()

    def test_ci_has_test_job(self):
        path = Path(__file__).resolve().parent.parent.parent / ".github" / "workflows" / "ci.yml"
        content = path.read_text()
        assert "pytest" in content

    def test_ci_has_docker_build(self):
        path = Path(__file__).resolve().parent.parent.parent / ".github" / "workflows" / "ci.yml"
        content = path.read_text()
        assert "docker build" in content

    def test_deploy_has_env_confirmation(self):
        path = Path(__file__).resolve().parent.parent.parent / ".github" / "workflows" / "deploy.yml"
        content = path.read_text()
        assert "confirm" in content.lower()


# ── Deployment Scripts ──

class TestDeployScript:
    def test_deploy_script_exists(self):
        path = Path(__file__).resolve().parent.parent.parent / "deploy" / "deploy.sh"
        assert path.exists()

    def test_deploy_script_has_commands(self):
        path = Path(__file__).resolve().parent.parent.parent / "deploy" / "deploy.sh"
        content = path.read_text()
        assert "cmd_dev" in content
        assert "cmd_prod" in content
        assert "cmd_stop" in content
        assert "cmd_test" in content


# ── Environment Config ──

class TestEnvironmentConfig:
    def test_env_example_exists(self):
        path = Path(__file__).resolve().parent.parent.parent / ".env.example"
        assert path.exists()

    def test_env_example_has_required_vars(self):
        path = Path(__file__).resolve().parent.parent.parent / ".env.example"
        content = path.read_text()
        assert "ENVIRONMENT=" in content
        assert "REDIS_URL=" in content
        assert "OLLAMA_BASE_URL=" in content
        assert "LOG_LEVEL=" in content

    def test_env_example_has_youtube_section(self):
        path = Path(__file__).resolve().parent.parent.parent / ".env.example"
        content = path.read_text()
        assert "YOUTUBE_" in content

    def test_env_example_has_production_section(self):
        path = Path(__file__).resolve().parent.parent.parent / ".env.example"
        content = path.read_text()
        assert "MAX_PARALLEL_JOBS=" in content
        assert "ENABLE_" in content
