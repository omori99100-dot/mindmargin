from fastapi import APIRouter, HTTPException

from mindmargin.api.schemas import (
    OperationHistoryResponse,
    OperationRecoverResponse,
    OperationRunRequest,
    OperationRunResponse,
    OperationScheduleRequest,
    OperationStatusResponse,
)
from mindmargin.config import settings
from mindmargin.core.scheduler import Scheduler
from mindmargin.core.workflows import WorkflowEngine
from mindmargin.operations.controller import OperationsController
from mindmargin.operations.models import OPERATION_CRON_DEFAULTS, OperationType

router = APIRouter(tags=["Operations"])


def _get_controller() -> OperationsController:
    engine = WorkflowEngine()
    scheduler = Scheduler()
    controller = OperationsController(engine=engine, scheduler=scheduler)
    return controller


@router.get("/operations/status", response_model=OperationStatusResponse)
def get_operations_status():
    controller = _get_controller()
    report = controller.get_status()
    return OperationStatusResponse(
        status=report.status,
        active_operations=report.active_operations,
        completed_today=report.completed_today,
        failed_today=report.failed_today,
        scheduled=report.scheduled,
        records=[r.to_dict() for r in report.records],
    )


@router.get("/operations/history", response_model=OperationHistoryResponse)
def get_operations_history(limit: int = 50):
    controller = _get_controller()
    records = controller.get_history(limit=limit)
    return OperationHistoryResponse(
        records=[r.to_dict() for r in records],
        total=len(records),
    )


@router.post("/operations/run", response_model=OperationRunResponse)
def run_operation(body: OperationRunRequest):
    controller = _get_controller()
    try:
        op_type = OperationType(body.operation_type)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid operation type: {body.operation_type}. "
                   f"Valid types: {[t.value for t in OperationType]}",
        )
    result = controller.run_operation(op_type, metadata={
        "quick": body.quick,
        "auto_publish": body.auto_publish,
        "privacy": body.privacy,
    })
    return OperationRunResponse(
        operation_id=result.get("operation_id", ""),
        operation_type=body.operation_type,
        status=result.get("status", "failed"),
        result=result,
        error=result.get("error", ""),
    )


@router.post("/operations/schedule")
def schedule_operations():
    controller = _get_controller()
    scheduled = controller.schedule_all()
    return {
        "status": "completed",
        "scheduled": scheduled,
        "total": len(scheduled),
    }


@router.post("/operations/recover", response_model=OperationRecoverResponse)
def recover_operations():
    controller = _get_controller()
    report = controller.get_status()
    recovered = controller.recover_failed()
    return OperationRecoverResponse(
        recovered=recovered,
        total_failed=report.failed_today,
    )
