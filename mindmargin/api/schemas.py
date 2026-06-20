from pydantic import BaseModel
from typing import Optional


class PipelineRequest(BaseModel):
    topic: str
    publish: bool = False


class PipelineResponse(BaseModel):
    pipeline_id: str
    topic: str
    status: str
    completed_agents: list[str] = []
    errors: list[dict] = []
    output_dir: str = ""
    message: str = ""


class ErrorResponse(BaseModel):
    detail: str
