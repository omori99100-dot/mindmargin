import logging
from fastapi import APIRouter, HTTPException

from mindmargin.api.schemas import PipelineRequest, PipelineResponse
from mindmargin.core.pipeline import Pipeline

logger = logging.getLogger(__name__)
router = APIRouter()

_active: dict[str, Pipeline] = {}


@router.post("/pipeline", response_model=PipelineResponse)
def start_pipeline(req: PipelineRequest):
    pipe = Pipeline(topic=req.topic)
    _active[pipe.pipeline_id] = pipe
    result = pipe.run()
    resp = PipelineResponse(
        pipeline_id=result["pipeline_id"],
        topic=result["topic"],
        status=result["status"],
        completed_agents=result["completed_agents"],
        errors=result["errors"],
        output_dir=result.get("output_dir", ""),
        message="Pipeline completed" if result["status"] == "completed" else "Pipeline failed",
    )
    if result["status"] == "failed":
        raise HTTPException(status_code=500, detail=resp.model_dump_json())
    return resp


@router.get("/pipeline/{pipeline_id}", response_model=PipelineResponse)
def get_status(pipeline_id: str):
    pipe = _active.get(pipeline_id)
    if not pipe:
        raise HTTPException(status_code=404, detail="Pipeline not found")
    return PipelineResponse(
        pipeline_id=pipe.pipeline_id,
        topic=pipe.topic,
        status=pipe.status,
        completed_agents=[k for k in ["research", "script", "voice", "editing"] if k in pipe.state],
        errors=pipe.errors,
        output_dir=str(pipe.state.get("output_dir", "")),
    )


@router.get("/pipelines")
def list_pipelines():
    return {"pipelines": list(_active.keys())}
