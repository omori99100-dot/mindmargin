from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Optional

router = APIRouter(prefix="/api/v1/github", tags=["github"])


class GitHubStatusResponse(BaseModel):
    total_runs: int = 0
    active_runs: int = 0
    completed_today: int = 0
    failed_today: int = 0
    success_rate: float = 100.0
    avg_duration_s: float = 0.0
    registry_workflows: int = 0
    artifacts_count: int = 0
    runners_available: int = 0
    health_score: float = 100.0
    policy: dict = {}


class WorkflowDispatchRequest(BaseModel):
    workflow_id: str
    trigger: str = "manual"
    params: dict = {}


class WorkflowDispatchResponse(BaseModel):
    dispatched: bool = False
    run_id: str = ""
    workflow_id: str = ""
    workflow_name: str = ""
    reason: str = ""
    timestamp: str = ""


class WorkflowListResponse(BaseModel):
    workflows: list[dict]
    total: int


class WorkflowRunResponse(BaseModel):
    run_id: str = ""
    workflow_name: str = ""
    state: str = ""
    created_at: str = ""
    duration_s: float = 0
    jobs: dict = {}
    failure_type: str = ""
    metadata: dict = {}


class WorkflowHistoryResponse(BaseModel):
    runs: list[dict]
    total: int


class WorkflowLogsResponse(BaseModel):
    run_id: str
    logs: str = ""
    job_logs: dict = {}


class ArtifactListResponse(BaseModel):
    artifacts: list[dict]
    total: int


class RunnerStatusResponse(BaseModel):
    pool: dict = {}
    availability_score: float = 0.0
    avg_queue_time_s: float = 0.0
    avg_job_duration_s: float = 0.0


class SecretsValidationResponse(BaseModel):
    secrets: dict = {}
    env_vars: list[dict] = []
    repository_config: dict = {}
    overall_valid: bool = False


class MonitorMetricsResponse(BaseModel):
    counters: dict = {}
    total_metrics: int = 0
    total_alerts: int = 0
    health: dict = {}


class RetryRequest(BaseModel):
    run_id: str


class RetryResponse(BaseModel):
    status: str = ""
    run_id: str = ""
    diagnosis: dict = {}
    recovery_action: dict = {}


class PolicyUpdateRequest(BaseModel):
    max_concurrent_workflows: Optional[int] = None
    daily_execution_limit: Optional[int] = None
    cost_limit_usd: Optional[float] = None
    maintenance_mode: Optional[bool] = None
    emergency_stop: Optional[bool] = None


def _get_controller():
    from mindmargin.github.controller import GitHubController
    return GitHubController()


def _get_dispatcher():
    from mindmargin.github.controller import GitHubController
    from mindmargin.github.dispatcher import WorkflowDispatcher
    controller = GitHubController()
    return WorkflowDispatcher(controller)


@router.get("/status", response_model=GitHubStatusResponse)
def github_status():
    controller = _get_controller()
    status = controller.get_status()
    return GitHubStatusResponse(**status.to_dict())


@router.get("/workflows", response_model=WorkflowListResponse)
def list_workflows():
    controller = _get_controller()
    defs = controller.registry.list_all()
    return WorkflowListResponse(
        workflows=[d.to_dict() for d in defs],
        total=len(defs),
    )


@router.post("/dispatch", response_model=WorkflowDispatchResponse)
def dispatch_workflow(body: WorkflowDispatchRequest):
    dispatcher = _get_dispatcher()
    result = dispatcher.dispatch(body.workflow_id, body.trigger, body.params)
    return WorkflowDispatchResponse(**result.to_dict())


@router.get("/runs", response_model=WorkflowHistoryResponse)
def list_runs(workflow_name: str = "", state: str = "", limit: int = 50):
    controller = _get_controller()
    runs = controller.state_store.list_runs(workflow_name, state, limit)
    return WorkflowHistoryResponse(
        runs=[r.to_dict() for r in runs],
        total=len(runs),
    )


@router.get("/runs/{run_id}", response_model=WorkflowRunResponse)
def get_run(run_id: str):
    controller = _get_controller()
    status = controller.get_workflow_status(run_id)
    if "error" in status:
        raise HTTPException(status_code=404, detail=status["error"])
    return WorkflowRunResponse(**status)


@router.get("/runs/{run_id}/logs", response_model=WorkflowLogsResponse)
def get_run_logs(run_id: str):
    controller = _get_controller()
    logs = controller.get_workflow_logs(run_id)
    if "error" in logs:
        raise HTTPException(status_code=404, detail=logs["error"])
    return WorkflowLogsResponse(**logs)


@router.post("/runs/{run_id}/cancel")
def cancel_run(run_id: str):
    controller = _get_controller()
    result = controller.cancel_workflow(run_id)
    if result.get("status") == "failed":
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


@router.post("/runs/{run_id}/retry", response_model=RetryResponse)
def retry_run(run_id: str):
    controller = _get_controller()
    result = controller.retry_workflow(run_id)
    return RetryResponse(**result)


@router.post("/runs/{run_id}/restart")
def restart_run(run_id: str):
    controller = _get_controller()
    result = controller.restart_workflow(run_id)
    if result.get("status") == "failed":
        raise HTTPException(status_code=400, detail=result.get("error"))
    return result


@router.get("/artifacts", response_model=ArtifactListResponse)
def list_artifacts(run_id: str = "", artifact_type: str = ""):
    controller = _get_controller()
    arts = controller.get_artifacts(run_id, artifact_type)
    return ArtifactListResponse(artifacts=arts, total=len(arts))


@router.get("/runners", response_model=RunnerStatusResponse)
def runner_status():
    controller = _get_controller()
    stats = controller.runner_mgr.get_stats()
    return RunnerStatusResponse(**stats)


@router.get("/secrets", response_model=SecretsValidationResponse)
def validate_secrets():
    controller = _get_controller()
    result = controller.secrets.validate_all()
    return SecretsValidationResponse(**result)


@router.get("/monitor", response_model=MonitorMetricsResponse)
def monitor_metrics():
    controller = _get_controller()
    summary = controller.monitor.get_summary()
    return MonitorMetricsResponse(**summary)


@router.get("/reports")
def list_reports(report_type: str = "", limit: int = 50):
    controller = _get_controller()
    return controller.reports.list_reports(report_type, limit)


@router.post("/policy")
def update_policy(body: PolicyUpdateRequest):
    controller = _get_controller()
    updates = {k: v for k, v in body.dict().items() if v is not None}
    return controller.update_policy(**updates)


@router.get("/policy")
def get_policy():
    controller = _get_controller()
    return controller.get_policy()


@router.get("/dispatch/log")
def dispatch_log(limit: int = 50):
    dispatcher = _get_dispatcher()
    return dispatcher.get_dispatch_log(limit)


@router.get("/dispatch/stats")
def dispatch_stats():
    dispatcher = _get_dispatcher()
    return dispatcher.get_dispatch_stats()


@router.get("/health")
def health_check():
    controller = _get_controller()
    return controller.monitor.get_health_report()
