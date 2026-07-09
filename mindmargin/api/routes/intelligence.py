from datetime import datetime

from fastapi import APIRouter, HTTPException, Query

from mindmargin.api.schemas import (
    ExperimentCycleResponse, ForecastResponse, WeeklyPlanResponse, WeeklyPlanEntry,
    GraphBuildResponse, AdjacentTopic, ExpansionOpportunity,
    DuplicateCheckResponse, ScoredCandidate,
)

router = APIRouter(tags=["Intelligence"])


# ── Experiments ──

@router.post("/experiments/run", response_model=ExperimentCycleResponse)
def run_experiments():
    from mindmargin.intelligence.experiments import run_experiment_cycle
    from mindmargin.analytics.memory import get_active_experiments
    result = run_experiment_cycle()
    active = get_active_experiments(50)
    return ExperimentCycleResponse(
        new_hypotheses=result["new_hypotheses"],
        experiments_completed=result["experiments_completed"],
        total_active=len(active),
        timestamp=result.get("timestamp", datetime.now().isoformat(timespec="seconds")),
    )


@router.get("/experiments")
def list_experiments(
    experiment_type: str = "",
    status: str = "",
    limit: int = 50,
):
    from mindmargin.analytics.memory import get_experiments
    experiments = get_experiments(experiment_type=experiment_type, status=status, limit=limit)
    return {"experiments": experiments, "total": len(experiments)}


@router.get("/experiments/{experiment_id}")
def get_experiment(experiment_id: str):
    from mindmargin.analytics.memory import get_experiment
    exp = get_experiment(experiment_id)
    if not exp:
        raise HTTPException(status_code=404, detail="Experiment not found")
    return exp


# ── Forecasts ──

@router.post("/forecasts/run", response_model=dict)
def run_forecasts():
    from mindmargin.intelligence.horizon import forecast_all
    forecasts = forecast_all()
    return {
        "status": "completed",
        "forecasts_generated": len(forecasts),
        "timestamp": datetime.now().isoformat(timespec="seconds"),
    }


@router.get("/forecasts", response_model=list[ForecastResponse])
def get_forecasts(window_days: int = 0, topic: str = "", limit: int = 50):
    from mindmargin.analytics.memory import get_forecasts
    results = get_forecasts(topic=topic, window_days=window_days, limit=limit)
    return [
        ForecastResponse(
            topic=r.get("topic", ""),
            window_days=r.get("window_days", 0),
            forecast_score=r.get("forecast_score", 0),
            confidence=r.get("confidence", 0),
            uncertainty=r.get("uncertainty", 0),
            lower_bound=r.get("lower_bound", 0),
            upper_bound=r.get("upper_bound", 0),
            forecast_date=r.get("forecast_date", ""),
        )
        for r in results
    ]


# ── Weekly Plan ──

@router.post("/plans/weekly/run", response_model=WeeklyPlanResponse)
def generate_weekly_plan():
    from mindmargin.intelligence.planner import plan_week
    plan = plan_week()
    return WeeklyPlanResponse(
        week_start=plan.get("week_start", ""),
        week_end=plan.get("week_end", ""),
        total_opportunities=plan.get("total_opportunities", 0),
        ranked_count=plan.get("ranked_count", 0),
        schedule=[WeeklyPlanEntry(**e) for e in plan.get("schedule", [])],
        summary=plan.get("summary", {}),
        generated_at=plan.get("generated_at", datetime.now().isoformat(timespec="seconds")),
    )


@router.get("/plans/weekly")
def get_weekly_plans(limit: int = 4):
    from mindmargin.analytics.memory import get_weekly_plans
    plans = get_weekly_plans(limit)
    return {"plans": plans, "total": len(plans)}


# ── Knowledge Graph ──

@router.post("/graph/build", response_model=GraphBuildResponse)
def build_graph():
    from mindmargin.intelligence.knowledge_graph import build_knowledge_graph
    result = build_knowledge_graph()
    return GraphBuildResponse(
        topics_found=result.get("topics_found", 0),
        keywords_extracted=result.get("keywords_extracted", 0),
        relationships_created=result.get("relationships_created", 0),
    )


@router.get("/graph/adjacent/{topic}", response_model=list[AdjacentTopic])
def get_adjacent_topics(topic: str, max_results: int = 10):
    from mindmargin.intelligence.knowledge_graph import find_adjacent
    results = find_adjacent(topic, max_results)
    return [AdjacentTopic(**r) for r in results]


@router.get("/graph/expansion", response_model=list[ExpansionOpportunity])
def get_expansion_opportunities(max_results: int = 20):
    from mindmargin.intelligence.knowledge_graph import KnowledgeGraph
    kg = KnowledgeGraph()
    results = kg.get_expansion_opportunities(max_results)
    return [ExpansionOpportunity(**r) for r in results]


@router.get("/graph/duplicate", response_model=DuplicateCheckResponse)
def check_duplicate(topic: str = Query(..., description="Topic to check"), threshold: float = 0.5):
    from mindmargin.intelligence.knowledge_graph import KnowledgeGraph
    kg = KnowledgeGraph()
    is_dup, dup_of, strength = kg.is_duplicate_coverage(topic, threshold)
    return DuplicateCheckResponse(is_duplicate=is_dup, duplicate_of=dup_of, similarity=round(strength, 2))


# ── Scoring & Opportunities ──

@router.post("/scoring/run", response_model=dict)
def run_scoring():
    from mindmargin.intelligence.scoring import run_opportunity_scoring
    scored = run_opportunity_scoring()
    return {"status": "completed", "candidates_scored": len(scored)}


@router.get("/opportunities", response_model=list[ScoredCandidate])
def get_opportunities(min_score: float = 0, limit: int = 50):
    from mindmargin.analytics.memory import get_opportunities
    opps = get_opportunities(min_score=min_score, limit=limit)
    return [
        ScoredCandidate(
            topic=o.get("topic", ""),
            opportunity_score=o.get("opportunity_score", 0),
            confidence=o.get("confidence", 0),
            trend_score=o.get("trend_score", 0),
            novelty=o.get("novelty", 0),
            seasonality=o.get("seasonality", 0),
            audience_match=o.get("audience_match", 0),
            evergreen_score=o.get("evergreen_score", 0),
            competition=o.get("competition", 0),
            historical_performance=o.get("historical_performance", 0),
            source=o.get("source", ""),
        )
        for o in opps
    ]


# ── Intelligence Job ──

@router.post("/intelligence/run", response_model=dict)
def run_intelligence_cycle():
    from mindmargin.jobs.daily_intelligence import run_intelligence_cycle
    result = run_intelligence_cycle()
    return result
