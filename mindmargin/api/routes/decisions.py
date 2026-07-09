from datetime import datetime

from fastapi import APIRouter, HTTPException

from mindmargin.api.schemas import (
    DecisionExplanation, ExecuteDecisionResponse,
    FeedbackCycleResponse, AlternativeCandidate,
)

router = APIRouter(tags=["Decisions"])


@router.post("/decisions/execute", response_model=ExecuteDecisionResponse)
def execute_decision(quick: bool = False, auto_publish: bool = False):
    from mindmargin.agents.decision_executor import execute_top_decision, format_execution_report
    result = execute_top_decision(quick=quick, auto_publish=auto_publish)
    if result.get("status") == "failed":
        return ExecuteDecisionResponse(
            status="failed",
            topic=result.get("topic", ""),
            error=result.get("error", str(result.get("errors", "unknown"))),
        )
    explanation = None
    if "explanation" in result:
        exp = result["explanation"]
        explanation = DecisionExplanation(
            selected_topic=exp.get("selected_topic", result.get("topic", "")),
            opportunity_score=exp.get("opportunity_score", 0),
            confidence=exp.get("confidence", 0),
            positive_factors=exp.get("positive_factors", []),
            negative_factors=exp.get("negative_factors", []),
            alternative_candidates=[
                AlternativeCandidate(**a) for a in exp.get("alternative_candidates", [])
            ],
            timestamp=exp.get("timestamp", datetime.now().isoformat(timespec="seconds")),
            markdown=exp.get("markdown", ""),
        )
    return ExecuteDecisionResponse(
        status=result.get("status", "completed"),
        topic=result.get("topic", ""),
        pipeline_id=result.get("pipeline_id", ""),
        video_id=result.get("video_id", ""),
        video_url=result.get("video_url", ""),
        explanation=explanation,
    )


@router.post("/decisions/explain", response_model=DecisionExplanation)
def explain_decision(topic: str):
    from mindmargin.analytics.memory import get_top_opportunities
    from mindmargin.intelligence.explainer import DecisionExplainer
    opportunities = get_top_opportunities(20)
    selected = None
    alternatives = []
    for opp in opportunities:
        if opp.get("topic", "").lower() == topic.lower():
            selected = opp
        else:
            alternatives.append(opp)
    if not selected:
        raise HTTPException(status_code=404, detail=f"Topic '{topic}' not found in opportunities")
    explainer = DecisionExplainer()
    explanation = explainer.explain(selected, alternatives[:5])
    markdown = explainer.to_markdown(explanation)
    explanation["markdown"] = markdown
    return DecisionExplanation(
        selected_topic=explanation["selected_topic"],
        opportunity_score=explanation["opportunity_score"],
        confidence=explanation["confidence"],
        positive_factors=explanation["positive_factors"],
        negative_factors=explanation["negative_factors"],
        alternative_candidates=[
            AlternativeCandidate(**a) for a in explanation.get("alternative_candidates", [])
        ],
        timestamp=explanation.get("timestamp", datetime.now().isoformat(timespec="seconds")),
        markdown=markdown,
    )


@router.post("/feedback/run", response_model=FeedbackCycleResponse)
def run_feedback():
    from mindmargin.intelligence.feedback_engine import run_feedback_cycle
    result = run_feedback_cycle()
    return FeedbackCycleResponse(
        outcomes_collected=result.get("outcomes_collected", 0),
        weights_changed=result.get("weights_changed", 0),
        weight_deltas=result.get("weight_deltas", {}),
        timestamp=datetime.now().isoformat(timespec="seconds"),
    )


@router.get("/execution-log")
def get_execution_log(limit: int = 20):
    from mindmargin.analytics.memory import get_execution_log
    return {"log": get_execution_log(limit)}
