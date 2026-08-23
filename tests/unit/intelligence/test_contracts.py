from mindmargin.intelligence.contracts import (
    DecisionRecord,
    DiagnosisRecord,
    EventLedger,
    ExperimentResult,
    PipelineEvent,
)


def test_decision_and_diagnosis_records_are_traceable():
    decision = DecisionRecord.create(
        "topic_selection",
        pipeline_id="p1",
        selected_option="enron",
        rationale="strong audience fit",
        confidence=0.82,
    )
    diagnosis = DiagnosisRecord.create(
        "weak initial curiosity",
        pipeline_id="p1",
        evidence=[{"metric": "first_3s_retention", "value": 0.41}],
        confidence=0.81,
        recommended_experiment="consequence-first opening",
    )
    assert decision.to_dict()["decision_id"].startswith("dec_")
    assert diagnosis.to_dict()["diagnosis_id"].startswith("diag_")
    assert diagnosis.evidence[0]["metric"] == "first_3s_retention"


def test_experiment_cannot_declare_winner_before_minimum_sample():
    experiment = ExperimentResult.create(
        "curiosity hook improves early retention",
        "hook_type",
        variants=[{"name": "question"}, {"name": "consequence"}],
        minimum_sample=100,
        sample_size=20,
    )
    assert not experiment.is_sample_sufficient
    try:
        experiment.declare_winner("consequence", 0.9)
    except ValueError as exc:
        assert "minimum sample" in str(exc)
    else:
        raise AssertionError("winner must be gated by minimum sample")


def test_event_ledger_round_trip(tmp_path):
    ledger = EventLedger(tmp_path / "events.jsonl")
    event = PipelineEvent.create(
        "pipeline.state_changed",
        "p2",
        from_state="CREATED",
        to_state="RESEARCHING",
    )
    ledger.append(event)
    rows = ledger.read("pipeline.state_changed")
    assert len(rows) == 1
    assert rows[0]["pipeline_id"] == "p2"
    assert rows[0]["to_state"] == "RESEARCHING"
