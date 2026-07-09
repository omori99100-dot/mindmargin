from fastapi import APIRouter, HTTPException

from mindmargin.api.schemas import JobResponse, JobListResponse
from mindmargin.core.jobs import Job

router = APIRouter(tags=["Jobs"])

STATE_ICONS = {
    "COMPLETED": "+", "FAILED": "-", "RUNNING": ">", "PENDING": "o",
    "PAUSED": "|", "CANCELLED": "x", "RETRYING": "~",
}


@router.get("/jobs", response_model=JobListResponse)
def list_jobs(limit: int = 20):
    jobs_data = Job.list_jobs(limit)
    jobs = [_job_to_response(j) for j in jobs_data]
    return JobListResponse(jobs=jobs, total=len(jobs))


@router.get("/jobs/{job_id}", response_model=JobResponse)
def get_job(job_id: str):
    job = Job.load(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return _job_to_response(job.to_dict())


@router.post("/jobs", response_model=JobResponse)
def create_job(job_type: str, params: str = "{}"):
    import json
    try:
        params_dict = json.loads(params) if params else {}
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON in params")
    from mindmargin.core.jobs import _next_job_id, run_job
    job_id = _next_job_id()
    job = Job(job_id, job_type, params_dict)
    job.start()
    job.complete({"message": "manually created"})
    return _job_to_response(job.to_dict())


@router.post("/jobs/{job_id}/cancel", response_model=JobResponse)
def cancel_job(job_id: str):
    job = Job.load(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    try:
        job.cancel()
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _job_to_response(job.to_dict())


@router.post("/jobs/{job_id}/retry", response_model=JobResponse)
def retry_job(job_id: str):
    job = Job.load(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    try:
        job.retry()
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    return _job_to_response(job.to_dict())


def _job_to_response(d: dict) -> JobResponse:
    return JobResponse(
        job_id=d.get("job_id", ""),
        job_type=d.get("job_type", ""),
        state=d.get("state", "PENDING"),
        created_at=d.get("created_at", ""),
        started_at=d.get("started_at", ""),
        completed_at=d.get("completed_at", ""),
        result=d.get("result", {}),
        error=d.get("error", ""),
        retry_count=d.get("retry_count", 0),
        max_retries=d.get("max_retries", 3),
        metadata=d.get("metadata", {}),
    )
