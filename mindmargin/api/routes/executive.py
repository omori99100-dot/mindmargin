from fastapi import APIRouter

from mindmargin.api.schemas import (
    ExecutiveStatusResponse,
    ExecutivePlanResponse,
    ExecutiveHistoryResponse,
    ExecutivePolicyResponse,
    ExecutivePolicySetRequest,
    ExecutiveMemoryResponse,
    ExecutiveRunResponse,
)
from mindmargin.executive.agent import ExecutiveAgent

router = APIRouter(prefix="/api/v1/executive", tags=["executive"])

_agent: ExecutiveAgent = None


def _get_agent() -> ExecutiveAgent:
    global _agent
    if _agent is None:
        _agent = ExecutiveAgent()
    return _agent


@router.get("/status", response_model=ExecutiveStatusResponse)
def executive_status():
    agent = _get_agent()
    data = agent.get_status()
    return ExecutiveStatusResponse(**data)


@router.get("/plan", response_model=ExecutivePlanResponse)
def executive_plan():
    agent = _get_agent()
    data = agent.get_plan()
    return ExecutivePlanResponse(**data)


@router.get("/history", response_model=ExecutiveHistoryResponse)
def executive_history(limit: int = 50):
    agent = _get_agent()
    records = agent.get_history(limit=limit)
    return ExecutiveHistoryResponse(records=records, total=len(records))


@router.get("/policies", response_model=ExecutivePolicyResponse)
def executive_policies():
    agent = _get_agent()
    data = agent.get_policy()
    return ExecutivePolicyResponse(**data)


@router.post("/policies/set")
def executive_set_policy(req: ExecutivePolicySetRequest):
    agent = _get_agent()
    result = agent.set_policy(req.policy_type)
    return result


@router.get("/memory", response_model=ExecutiveMemoryResponse)
def executive_memory():
    agent = _get_agent()
    data = agent.get_memory()
    return ExecutiveMemoryResponse(**data)


@router.post("/run", response_model=ExecutiveRunResponse)
def executive_run():
    agent = _get_agent()
    result = agent.run_once()
    return ExecutiveRunResponse(**result)
