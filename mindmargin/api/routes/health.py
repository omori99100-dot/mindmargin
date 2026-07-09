import time
import shutil
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter

from mindmargin.api.schemas import HealthReport, CheckerResult
from mindmargin.config import settings

router = APIRouter(tags=["Health"])


def _check_redis() -> CheckerResult:
    try:
        import redis
        r = redis.Redis.from_url(settings.redis_url, socket_timeout=3)
        r.ping()
        return CheckerResult(checker="redis", status="pass", value=1.0, detail=settings.redis_url)
    except Exception as e:
        return CheckerResult(checker="redis", status="critical", value=0, detail=str(e))


def _check_ollama() -> CheckerResult:
    try:
        import httpx
        resp = httpx.get(f"{settings.llm.base_url}/api/tags", timeout=5)
        if resp.status_code == 200:
            models = resp.json().get("models", [])
            names = [m.get("name", "") for m in models[:3]]
            return CheckerResult(
                checker="ollama", status="pass", value=float(len(models)),
                detail=f"{len(models)} models: {', '.join(names)}",
            )
        return CheckerResult(checker="ollama", status="warning", value=0, detail=f"HTTP {resp.status_code}")
    except Exception as e:
        return CheckerResult(checker="ollama", status="warning", value=0, detail=str(e))


def _check_disk() -> CheckerResult:
    try:
        output_dir = Path(settings.storage.output_root)
        output_dir.mkdir(parents=True, exist_ok=True)
        usage = shutil.disk_usage(str(output_dir))
        free_gb = usage.free / (1024**3)
        pct_free = (usage.free / usage.total) * 100
        status = "pass" if pct_free > 20 else "warning" if pct_free > 5 else "critical"
        return CheckerResult(
            checker="disk", status=status, value=round(free_gb, 1),
            detail=f"{pct_free:.1f}% free ({free_gb:.1f}GB)",
        )
    except Exception as e:
        return CheckerResult(checker="disk", status="warning", value=0, detail=str(e))


def _check_database() -> CheckerResult:
    try:
        from mindmargin.analytics.memory import _get_db
        conn = _get_db()
        conn.execute("SELECT 1").fetchone()
        return CheckerResult(checker="database", status="pass", value=1.0, detail="SQLite connected")
    except Exception as e:
        return CheckerResult(checker="database", status="critical", value=0, detail=str(e))


def _check_llm() -> CheckerResult:
    try:
        from mindmargin.integrations.manager import create_default_manager
        pm = create_default_manager()
        providers = list(pm.available)
        return CheckerResult(
            checker="llm", status="pass", value=float(len(providers)),
            detail=f"{len(providers)} providers: {', '.join(providers)}",
        )
    except Exception as e:
        return CheckerResult(checker="llm", status="warning", value=0, detail=str(e))


def _check_config() -> CheckerResult:
    try:
        _ = settings.environment
        return CheckerResult(checker="config", status="pass", value=1.0, detail=f"env={settings.environment}")
    except Exception as e:
        return CheckerResult(checker="config", status="critical", value=0, detail=str(e))


def _check_pipelines() -> CheckerResult:
    try:
        from mindmargin.analytics.memory import get_pipeline_stats
        stats = get_pipeline_stats()
        return CheckerResult(
            checker="pipelines", status="pass",
            value=float(stats.get("total_pipelines", 0)),
            detail=f"{stats.get('total_pipelines', 0)} total, {stats.get('published_videos', 0)} published",
        )
    except Exception as e:
        return CheckerResult(checker="pipelines", status="warning", value=0, detail=str(e))


@router.get("/health", response_model=HealthReport)
def health_check():
    checkers = []
    failed = 0
    warnings = 0
    passed = 0

    checks = [
        _check_config,
        _check_database,
        _check_redis,
        _check_ollama,
        _check_disk,
        _check_llm,
        _check_pipelines,
    ]

    for check_fn in checks:
        result = check_fn()
        checkers.append(result)
        if result.status == "critical":
            failed += 1
        elif result.status == "warning":
            warnings += 1
        else:
            passed += 1

    overall = "pass" if failed == 0 and warnings == 0 else "degraded" if failed == 0 else "fail"
    return HealthReport(
        status=overall,
        environment=settings.environment,
        timestamp=datetime.now().isoformat(timespec="seconds"),
        checkers=checkers,
        failed_count=failed,
        warning_count=warnings,
        pass_count=passed,
    )


@router.get("/readiness")
def readiness_check():
    ready = True
    checks = {}

    for name, check_fn in [("config", _check_config), ("database", _check_database), ("redis", _check_redis)]:
        result = check_fn()
        checks[name] = result.status
        if result.status == "critical":
            ready = False

    return {
        "ready": ready,
        "checks": checks,
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    }


@router.get("/liveness")
def liveness_check():
    return {
        "alive": True,
        "uptime_s": time.process_time(),
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    }
