"""Explicit, in-memory C2-P3 Hypothesis Registry.

The registry consumes P1 read-only evidence access and optional validated P2
DiagnosisRecord objects. It never persists, executes experiments, creates
Knowledge/Strategy records, mutates production, or turns observational evidence
into supported hypotheses.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from typing import Any, Iterable, Mapping, Optional

from mindmargin.intelligence.c2_access import C2ReadOnlyEvidenceAccess, LineageScope
from mindmargin.intelligence.c2_contracts import C2ConfidenceValue, C2HypothesisRecord
from mindmargin.intelligence.c2_diagnosis import C2DiagnosisCoordinator, DiagnosisValidation

_CAUSAL_LANGUAGE = (
    " caused ",
    " causes ",
    " cause ",
    "caused by",
    "causal",
    "causally",
    "directly led to",
    "leads to",
    "resulted in",
)


@dataclass(frozen=True)
class HypothesisValidation:
    valid: bool
    status: str
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    lineage: Optional[dict[str, Any]] = None


@dataclass(frozen=True)
class HypothesisOutcome:
    record: Optional[C2HypothesisRecord]
    validation: HypothesisValidation


class C2HypothesisRegistry:
    """In-memory, explicit registry for proposed/testable hypotheses only."""

    def __init__(self, access: C2ReadOnlyEvidenceAccess):
        if not isinstance(access, C2ReadOnlyEvidenceAccess):
            raise TypeError("access must be a C2ReadOnlyEvidenceAccess instance")
        self.access = access
        self._records_by_id: dict[str, C2HypothesisRecord] = {}
        self._records_by_key: dict[str, C2HypothesisRecord] = {}

    def propose(
        self,
        *,
        statement: str,
        supporting_evidence_ids: list[str] | tuple[str, ...],
        measurable_prediction: str,
        falsification_condition: str,
        inconclusive_condition: str,
        expected_direction: str = "unknown",
        hypothesis_type: str = "predictive",
        diagnosis_ids: list[str] | tuple[str, ...] = (),
        target_observation_ids: list[str] | tuple[str, ...] = (),
        alternative_hypotheses: tuple[dict[str, Any], ...] = (),
        confidence: Optional[C2ConfidenceValue] = None,
        limitations: tuple[dict[str, Any], ...] = (),
        pipeline_id: str = "",
        content_id: str = "",
        story_id: str = "",
        video_id: str = "",
        correlation_id: str = "",
        parent_record_ids: list[str] | tuple[str, ...] = (),
        source_record_ids: list[str] | tuple[str, ...] = (),
        idempotency_key: str = "",
        diagnoses: Mapping[str, Any] | None = None,
    ) -> C2HypothesisRecord:
        """Create/register a proposed hypothesis in memory only."""
        evidence = tuple(supporting_evidence_ids)
        diagnosis_tuple = tuple(diagnosis_ids)
        logical_key = idempotency_key or self._logical_idempotency_key(
            statement=statement,
            scope=(pipeline_id, content_id, story_id, video_id, correlation_id),
            evidence_ids=evidence,
            prediction=measurable_prediction,
            falsification=falsification_condition,
        )
        existing = self._records_by_key.get(logical_key)
        if existing is not None:
            return existing
        record = C2HypothesisRecord.create(
            statement=statement,
            supporting_evidence_ids=evidence,
            measurable_prediction=measurable_prediction,
            falsification_condition=falsification_condition,
            inconclusive_condition=inconclusive_condition,
            pipeline_id=pipeline_id,
            correlation_id=correlation_id,
            hypothesis_type=hypothesis_type,
            diagnosis_ids=diagnosis_tuple,
            target_observation_ids=tuple(target_observation_ids),
            alternative_hypotheses=tuple(alternative_hypotheses),
            expected_direction=expected_direction,
            confidence=confidence,
            limitations=tuple(limitations),
            parent_record_ids=tuple(parent_record_ids) or tuple(dict.fromkeys(diagnosis_tuple + evidence)),
            source_record_ids=tuple(source_record_ids) or tuple(dict.fromkeys(evidence + diagnosis_tuple)),
            idempotency_key=logical_key,
            status="proposed",
        )
        record = replace(
            record,
            envelope=replace(
                record.envelope,
                content_id=content_id,
                story_id=story_id,
                video_id=video_id,
            ),
        )
        self._records_by_key[logical_key] = record
        self._records_by_id[record.hypothesis_id] = record
        return record

    def register(self, record: C2HypothesisRecord) -> C2HypothesisRecord:
        """Register an already-created P0 record without persistence."""
        if not isinstance(record, C2HypothesisRecord):
            raise TypeError("record must be a C2HypothesisRecord")
        existing = self._records_by_key.get(record.envelope.idempotency_key)
        if existing is not None:
            return existing
        self._records_by_key[record.envelope.idempotency_key] = record
        self._records_by_id[record.hypothesis_id] = record
        return record

    def get(self, hypothesis_id: str) -> Optional[C2HypothesisRecord]:
        return self._records_by_id.get(hypothesis_id)

    def validate(
        self,
        record: C2HypothesisRecord,
        *,
        diagnoses: Mapping[str, Any] | None = None,
    ) -> HypothesisValidation:
        """Validate entry criteria; valid proposed records become testable only via mark_testable."""
        errors: list[str] = []
        warnings: list[str] = []
        if not isinstance(record, C2HypothesisRecord):
            return HypothesisValidation(False, "rejected", ("record_type_invalid",))
        if record.status != "proposed":
            errors.append("hypothesis_must_be_proposed_before_testability_validation")
        if record.causality_status != "not_claimed":
            errors.append("causality_status_must_be_not_claimed")
        if record.confidence is None:
            errors.append("confidence_required")
        for field_name, value in (
            ("statement", record.statement),
            ("measurable_prediction", record.measurable_prediction),
            ("falsification_condition", record.falsification_condition),
            ("inconclusive_condition", record.inconclusive_condition),
        ):
            if not isinstance(value, str) or not value.strip():
                errors.append(f"{field_name}_required")
            elif self._has_causal_language(value):
                errors.append(f"{field_name}_causal_language")
        if not record.limitations:
            errors.append("limitations_required")

        evidence_rows: list[dict[str, Any]] = []
        observations: list[dict[str, Any]] = []
        for evidence_id in record.supporting_evidence_ids:
            evidence = self.access.get_evidence(evidence_id)
            if evidence is None:
                errors.append(f"evidence_not_found:{evidence_id}")
                continue
            evidence_rows.append(evidence)
            if evidence.get("validation_status") != "valid":
                errors.append(f"evidence_not_valid:{evidence_id}")
            if not evidence.get("provenance"):
                errors.append(f"evidence_provenance_missing:{evidence_id}")
            observation_ids = evidence.get("observation_ids") or []
            if not observation_ids:
                errors.append(f"evidence_observation_missing:{evidence_id}")
            for observation_id in observation_ids:
                observation = self.access.get_observation(observation_id)
                if observation is None:
                    errors.append(f"observation_not_found:{observation_id}")
                    continue
                observations.append(observation)
                if observation.get("quality") != "valid":
                    errors.append(f"observation_not_valid:{observation_id}")
                if observation.get("freshness_seconds") is None:
                    errors.append(f"observation_freshness_unknown:{observation_id}")
        if not evidence_rows:
            errors.append("supporting_evidence_required")

        lineage = self.get_lineage(record.hypothesis_id, diagnoses=diagnoses)
        if lineage["status"] != "complete":
            errors.append(f"lineage_not_complete:{lineage['status']}")
        if lineage["missing_ids"]:
            errors.append("lineage_missing_ids")
        if lineage["invalid_edges"]:
            errors.append("lineage_invalid_edges")

        for row in evidence_rows + observations:
            errors.extend(self._scope_errors(record, row))

        diagnoses_map = diagnoses or {}
        for diagnosis_id in record.diagnosis_ids:
            diagnosis = diagnoses_map.get(diagnosis_id)
            if diagnosis is None:
                errors.append(f"diagnosis_not_resolved:{diagnosis_id}")
                continue
            if getattr(diagnosis, "status", None) == "invalid":
                errors.append(f"diagnosis_invalid:{diagnosis_id}")
            if getattr(diagnosis, "status", None) != "validated":
                errors.append(f"diagnosis_not_validated:{diagnosis_id}")
            if getattr(diagnosis, "diagnosis_id", None) != diagnosis_id:
                errors.append(f"diagnosis_id_mismatch:{diagnosis_id}")
            if not set(record.supporting_evidence_ids).intersection(getattr(diagnosis, "evidence_ids", ())):
                errors.append(f"diagnosis_evidence_not_linked:{diagnosis_id}")

        errors.extend(self._alternative_errors(record))
        if errors:
            return HypothesisValidation(
                valid=False,
                status="rejected",
                errors=tuple(dict.fromkeys(errors)),
                warnings=tuple(dict.fromkeys(warnings)),
                lineage=lineage,
            )
        return HypothesisValidation(
            valid=True,
            status="testable",
            warnings=tuple(dict.fromkeys(warnings)),
            lineage=lineage,
        )

    def mark_testable(
        self,
        record: C2HypothesisRecord,
        *,
        diagnoses: Mapping[str, Any] | None = None,
    ) -> HypothesisOutcome:
        validation = self.validate(record, diagnoses=diagnoses)
        if not validation.valid:
            return HypothesisOutcome(record=record, validation=validation)
        testable = record.transition_to("testable")
        self._records_by_id[testable.hypothesis_id] = testable
        self._records_by_key[testable.envelope.idempotency_key] = testable
        return HypothesisOutcome(record=testable, validation=validation)

    def register_from_diagnosis(
        self,
        diagnosis: Any,
        *,
        statement: str,
        measurable_prediction: str,
        falsification_condition: str,
        inconclusive_condition: str,
        expected_direction: str = "unknown",
        confidence: Optional[C2ConfidenceValue] = None,
        limitations: tuple[dict[str, Any], ...] = (),
        alternative_hypotheses: tuple[dict[str, Any], ...] = (),
    ) -> HypothesisOutcome:
        """Create and validate a hypothesis from a P2 validated diagnosis."""
        if getattr(diagnosis, "status", None) != "validated":
            validation = HypothesisValidation(False, "rejected", ("diagnosis_must_be_validated",))
            return HypothesisOutcome(record=None, validation=validation)
        record = self.propose(
            statement=statement,
            supporting_evidence_ids=tuple(diagnosis.evidence_ids),
            measurable_prediction=measurable_prediction,
            falsification_condition=falsification_condition,
            inconclusive_condition=inconclusive_condition,
            expected_direction=expected_direction,
            diagnosis_ids=(diagnosis.diagnosis_id,),
            target_observation_ids=tuple(getattr(diagnosis, "observation_ids", ())),
            confidence=confidence,
            limitations=limitations,
            alternative_hypotheses=alternative_hypotheses,
            pipeline_id=diagnosis.envelope.pipeline_id,
            content_id=diagnosis.envelope.content_id,
            story_id=diagnosis.envelope.story_id,
            video_id=diagnosis.envelope.video_id,
            correlation_id=diagnosis.envelope.correlation_id,
        )
        return self.mark_testable(record, diagnoses={diagnosis.diagnosis_id: diagnosis})

    def transition(self, record: C2HypothesisRecord, status: str) -> C2HypothesisRecord:
        """Allow only the P3 transition to testable; future result states are gated."""
        if status in {"tested", "supported", "rejected", "inconclusive", "superseded"}:
            raise ValueError("future result/governance transitions are not executable in C2-P3")
        if status != "testable":
            raise ValueError("C2-P3 supports only proposed -> testable")
        return self.mark_testable(record).record or record

    def get_lineage(self, hypothesis_id: str, *, diagnoses: Mapping[str, Any] | None = None) -> dict[str, Any]:
        record = self.get(hypothesis_id)
        if record is None:
            return {
                "status": "not_found",
                "hypothesis_id": hypothesis_id,
                "records_by_type": {},
                "resolved_edges": [],
                "missing_ids": [],
                "invalid_edges": [],
                "quality_warnings": [],
            }
        scope = LineageScope(
            pipeline_id=record.envelope.pipeline_id,
            content_id=record.envelope.content_id,
            video_id=record.envelope.video_id,
            correlation_id=record.envelope.correlation_id,
        )
        base = self.access.lineage_view(scope=scope).to_dict()
        records_by_type = dict(base["records_by_type"])
        records_by_type.setdefault("diagnosis", [])
        records_by_type.setdefault("hypothesis", [])
        records_by_type["hypothesis"].append(record.to_dict())
        resolved_edges = list(base["resolved_edges"])
        missing_ids = list(base["missing_ids"])
        invalid_edges = list(base["invalid_edges"])
        diagnoses_map = diagnoses or {}
        for diagnosis_id in record.diagnosis_ids:
            diagnosis = diagnoses_map.get(diagnosis_id)
            if diagnosis is None:
                missing_ids.append(diagnosis_id)
                invalid_edges.append({"from": diagnosis_id, "to": hypothesis_id, "type": "diagnosis"})
                continue
            if getattr(diagnosis, "diagnosis_id", None) != diagnosis_id:
                invalid_edges.append({"from": diagnosis_id, "to": hypothesis_id, "type": "diagnosis", "reason": "id_mismatch"})
                continue
            if not self._diagnosis_scope_matches(record, diagnosis):
                invalid_edges.append({"from": diagnosis_id, "to": hypothesis_id, "type": "diagnosis", "reason": "scope_mismatch"})
                continue
            records_by_type["diagnosis"].append(diagnosis.to_dict())
            resolved_edges.append({"from": diagnosis_id, "to": hypothesis_id, "type": "diagnosis"})
        for evidence_id in record.supporting_evidence_ids:
            if self.access.get_evidence(evidence_id) is None:
                missing_ids.append(evidence_id)
                invalid_edges.append({"from": evidence_id, "to": hypothesis_id, "type": "supporting_evidence"})
            else:
                resolved_edges.append({"from": evidence_id, "to": hypothesis_id, "type": "supporting_evidence"})
        missing_ids = list(dict.fromkeys(missing_ids))
        status = "complete" if base["status"] == "complete" and not missing_ids and not invalid_edges else "partial"
        return {
            "status": status,
            "hypothesis_id": hypothesis_id,
            "records_by_type": records_by_type,
            "resolved_edges": resolved_edges,
            "missing_ids": missing_ids,
            "invalid_edges": invalid_edges,
            "quality_warnings": list(base["quality_warnings"]),
        }

    @staticmethod
    def _logical_idempotency_key(*, statement: str, scope: tuple[str, ...], evidence_ids: tuple[str, ...], prediction: str, falsification: str) -> str:
        payload = json.dumps({
            "statement": statement,
            "scope": scope,
            "supporting_evidence_ids": sorted(evidence_ids),
            "measurable_prediction": prediction,
            "falsification_condition": falsification,
        }, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return "hypothesis:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]

    @staticmethod
    def _scope_errors(record: C2HypothesisRecord, row: Mapping[str, Any]) -> list[str]:
        errors: list[str] = []
        for field_name in ("pipeline_id", "content_id", "video_id", "correlation_id"):
            expected = getattr(record.envelope, field_name)
            if expected and str(row.get(field_name) or "") != expected:
                errors.append(f"{field_name}_scope_mismatch:{row.get(field_name) or 'missing'}")
        return errors

    @staticmethod
    def _diagnosis_scope_matches(record: C2HypothesisRecord, diagnosis: Any) -> bool:
        envelope = getattr(diagnosis, "envelope", None)
        if envelope is None:
            return False
        return all(
            not getattr(record.envelope, field_name) or getattr(record.envelope, field_name) == getattr(envelope, field_name)
            for field_name in ("pipeline_id", "content_id", "story_id", "video_id", "correlation_id")
        )

    @staticmethod
    def _has_causal_language(text: str) -> bool:
        lowered = f" {text.lower()} "
        return any(phrase in lowered for phrase in _CAUSAL_LANGUAGE)

    def _alternative_errors(self, record: C2HypothesisRecord) -> list[str]:
        errors: list[str] = []
        allowed_ids = set(record.supporting_evidence_ids)
        for index, alternative in enumerate(record.alternative_hypotheses):
            if not isinstance(alternative, Mapping):
                errors.append(f"alternative_hypotheses[{index}]_must_be_object")
                continue
            text = str(alternative.get("text") or alternative.get("label") or "")
            if not text.strip():
                errors.append(f"alternative_hypotheses[{index}]_text_required")
            if self._has_causal_language(text):
                errors.append(f"alternative_hypotheses[{index}]_causal_language")
            linked_ids = alternative.get("evidence_ids") or []
            if not linked_ids:
                errors.append(f"alternative_hypotheses[{index}]_evidence_ids_required")
            elif not set(linked_ids).issubset(allowed_ids):
                errors.append(f"alternative_hypotheses[{index}]_evidence_ids_outside_hypothesis")
        return errors


__all__ = ["C2HypothesisRegistry", "HypothesisOutcome", "HypothesisValidation"]
