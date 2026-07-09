from fastapi import APIRouter, HTTPException

from mindmargin.api.schemas import PipelineRequest, PipelineResponse
from mindmargin.core.pipeline import Pipeline

router = APIRouter(tags=["Pipelines"])

_active: dict[str, Pipeline] = {}


@router.post("/pipeline", response_model=PipelineResponse)
def start_pipeline(req: PipelineRequest):
    scale = 0.1 if req.quick else 1.0
    pipe = Pipeline(topic=req.topic, duration_scale=scale, mode=req.mode)
    _active[pipe.pipeline_id] = pipe
    result = pipe.run()
    resp = PipelineResponse(
        pipeline_id=result["pipeline_id"],
        topic=result["topic"],
        status=result["status"],
        completed_agents=result["completed_agents"],
        errors=result["errors"],
        output_dir=result.get("output_dir", ""),
        timing_s=result.get("timing_s"),
        video_path=result.get("video_path", ""),
        message="Pipeline completed" if result["status"] == "completed" else "Pipeline failed",
    )
    if result["status"] == "failed":
        raise HTTPException(status_code=500, detail=resp.model_dump_json())
    return resp


@router.get("/pipeline/{pipeline_id}", response_model=PipelineResponse)
def get_pipeline_status(pipeline_id: str):
    pipe = _active.get(pipeline_id)
    if not pipe:
        from mindmargin.analytics.memory import get_pipeline_history
        history = get_pipeline_history(200)
        for p in history:
            if p.get("id") == pipeline_id:
                return PipelineResponse(
                    pipeline_id=p["id"],
                    topic=p["topic"],
                    status=p.get("status", "completed"),
                    output_dir="",
                    message="Loaded from history",
                )
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
    from mindmargin.analytics.memory import get_pipeline_history
    history = get_pipeline_history(50)
    return {
        "active": list(_active.keys()),
        "historical": [
            {"id": p["id"], "topic": p["topic"], "status": p.get("status", ""),
             "created_at": p.get("created_at", ""),
             "youtube_video_id": p.get("youtube_video_id", "")}
            for p in history
        ],
    }
