"""Contract-only tests for the explicitly authorized C2-P0 scope."""

import pytest

from mindmargin.intelligence.c2_contracts import (
    C2ConfidenceValue,
    C2DiagnosisRecord,
    C2HypothesisRecord,
    C2_SCHEMA_VERSION,
)
from mindmargin.intelligence.contracts import DiagnosisRecord as LegacyDiagnosisRecord


def _confidence(dimension="evidence_support"):
    return C2ConfidenceValue(
        score=0.72,
        dimension=dimension,
        basis="provenance_based",
        limitations=("observational evidence only",),
    )


def _diagnosis(**kwargs):
    return C2DiagnosisRecord.create(
        problem_statement="The observed failure pattern is bounded to the publish window.",
        evidence_ids=["ev_c1_1"],
        pipeline_id="p-c2-contract",
        correlation_id="corr-c2-contract",
        confidence=_confidence(),
        **kwargs,
    )


def _hypothesis(**kwargs):
    return C2HypothesisRecord.create(
        statement="A title-format change is associated with a measurable CTR increase in this scope.",
        supporting_evidence_ids=["ev_c1_1"],
        measurable_prediction="CTR increases by the declared threshold during the declared window.",
        falsification_condition="CTR does not exceed the declared threshold after the window.",
        inconclusive_condition="The minimum information threshold is not reached.",
        pipeline_id="p-c2-contract",
        correlation_id="corr-c2-contract",
        confidence=_confidence("prediction"),
        **kwargs,
    )


def test_c2_contracts_are_versioned_and_do_not_replace_legacy_diagnosis():
    diagnosis = _diagnosis()
    hypothesis = _hypothesis()

    assert diagnosis.envelope.schema_version == C2_SCHEMA_VERSION
    assert hypothesis.envelope.schema_version == C2_SCHEMA_VERSION
    assert diagnosis.envelope.record_type == "diagnosis"
    assert hypothesis.envelope.record_type == "hypothesis"

    legacy = LegacyDiagnosisRecord.create(
        "legacy problem",
        evidence=[{"metric": "ctr", "value": 0.4}],
        hypothesis="legacy hypothesis string",
    )
    assert legacy.problem == "legacy problem"
    assert legacy.hypothesis == "legacy hypothesis string"
    assert diagnosis.diagnosis_id.startswith("diag_c2_")
    assert hypothesis.hypothesis_id.startswith("hyp_c2_")


def test_c2_serialization_is_json_safe_and_contains_lineage():
    diagnosis = _diagnosis(
        parent_record_ids=("ev_c1_1",),
        source_record_ids=("ev_c1_1",),
        limitations=({"reason": "small bounded window", "scope": "single video"},),
    )
    payload = diagnosis.to_dict()

    assert payload["record_type"] == "diagnosis"
    assert payload["envelope"]["schema_version"] == "c2-1"
    assert payload["envelope"]["parent_record_ids"] == ["ev_c1_1"]
    assert payload["evidence_ids"] == ["ev_c1_1"]
    assert payload["confidence"]["dimension"] == "evidence_support"


def test_hypothesis_requires_measurable_prediction_and_falsification():
    with pytest.raises(ValueError, match="measurable_prediction"):
        C2HypothesisRecord.create(
            statement="A bounded claim",
            supporting_evidence_ids=["ev_1"],
            measurable_prediction="",
            falsification_condition="condition",
            inconclusive_condition="insufficient data",
        )

    with pytest.raises(ValueError, match="falsification_condition"):
        C2HypothesisRecord.create(
            statement="A bounded claim",
            supporting_evidence_ids=["ev_1"],
            measurable_prediction="metric changes",
            falsification_condition="",
            inconclusive_condition="insufficient data",
        )

    with pytest.raises(ValueError, match="inconclusive_condition"):
        C2HypothesisRecord.create(
            statement="A bounded claim",
            supporting_evidence_ids=["ev_1"],
            measurable_prediction="metric changes",
            falsification_condition="metric does not change",
            inconclusive_condition="",
        )


def test_diagnosis_and_hypothesis_require_supporting_evidence():
    with pytest.raises(ValueError, match="evidence_ids"):
        C2DiagnosisRecord.create(problem_statement="bounded", evidence_ids=[])

    with pytest.raises(ValueError, match="supporting_evidence_ids"):
        C2HypothesisRecord.create(
            statement="bounded",
            supporting_evidence_ids=[],
            measurable_prediction="metric changes",
            falsification_condition="metric does not change",
            inconclusive_condition="insufficient data",
        )


def test_causal_fields_are_rejected_or_fixed_to_non_causal_values():
    with pytest.raises(ValueError, match="causal_claim"):
        _diagnosis(causal_claim="metric X caused metric Y")

    with pytest.raises(ValueError, match="causality_status"):
        _hypothesis(causality_status="causal_claim")

    assert _hypothesis().causality_status == "not_claimed"
    assert _diagnosis().causal_claim is None


def test_confidence_is_bounded_and_not_causal():
    with pytest.raises(ValueError, match="between"):
        C2ConfidenceValue(1.1, "evidence_support", "rule_based")
    with pytest.raises(ValueError, match="dimension"):
        C2ConfidenceValue(0.5, "causality", "rule_based")
    with pytest.raises(ValueError, match="basis"):
        C2ConfidenceValue(0.5, "evidence_support", "causal_inference")


def test_diagnosis_lifecycle_accepts_only_declared_transitions():
    diagnosis = _diagnosis()
    validated = diagnosis.transition_to("validated")
    superseded = validated.transition_to("superseded")

    assert diagnosis.status == "planned"
    assert validated.status == "validated"
    assert superseded.status == "superseded"
    assert diagnosis.envelope.status == "planned"
    assert validated.envelope.status == "validated"

    with pytest.raises(ValueError, match="invalid diagnosis transition"):
        diagnosis.transition_to("superseded")


def test_hypothesis_lifecycle_preserves_typed_confidence():
    hypothesis = _hypothesis()
    testable = hypothesis.transition_to("testable")
    tested = testable.transition_to("tested")
    supported = tested.transition_to("supported")

    assert supported.status == "supported"
    assert supported.envelope.status == "supported"
    assert isinstance(supported.confidence, C2ConfidenceValue)
    assert supported.confidence.dimension == "prediction"

    with pytest.raises(ValueError, match="invalid hypothesis transition"):
        hypothesis.transition_to("supported")


def test_idempotency_keys_are_deterministic_for_same_logical_input():
    diagnosis_a = _diagnosis(idempotency_key="")
    diagnosis_b = C2DiagnosisRecord.create(
        problem_statement=diagnosis_a.problem_statement,
        evidence_ids=["ev_c1_1"],
        pipeline_id="p-c2-contract",
        correlation_id="corr-c2-contract",
    )
    hypothesis_a = _hypothesis(idempotency_key="")
    hypothesis_b = C2HypothesisRecord.create(
        statement=hypothesis_a.statement,
        supporting_evidence_ids=["ev_c1_1"],
        measurable_prediction=hypothesis_a.measurable_prediction,
        falsification_condition=hypothesis_a.falsification_condition,
        inconclusive_condition=hypothesis_a.inconclusive_condition,
        pipeline_id="p-c2-contract",
        correlation_id="corr-c2-contract",
    )

    assert diagnosis_a.envelope.idempotency_key == diagnosis_b.envelope.idempotency_key
    assert hypothesis_a.envelope.idempotency_key == hypothesis_b.envelope.idempotency_key
    assert diagnosis_a.diagnosis_id != diagnosis_b.diagnosis_id
    assert hypothesis_a.hypothesis_id != hypothesis_b.hypothesis_id


def test_c2_allowlist_redacts_secret_keys_and_drops_unknown_payload_fields():
    diagnosis = _diagnosis(
        candidate_explanations=(
            {
                "label": "quota candidate",
                "basis": "bounded evidence",
                "unknown_payload": "must be dropped",
                "api_key": "top-secret",
            },
        ),
        limitations=({"reason": "bounded", "secret_token": "must redact", "unknown": "drop"},),
    )
    payload = diagnosis.to_dict()
    candidate = payload["candidate_explanations"][0]
    limitation = payload["limitations"][0]

    assert "unknown_payload" not in candidate
    assert candidate["api_key"] == "[REDACTED]"
    assert "unknown" not in limitation
    assert limitation["secret_token"] == "[REDACTED]"


def test_c2_contracts_do_not_persist_raw_arbitrary_top_level_fields():
    hypothesis = _hypothesis()
    payload = hypothesis.to_dict()
    assert "raw_payload" not in payload
    assert "provider_response" not in payload
    assert "authorization" not in payload
