"""Explicit, bounded C2-P2 diagnosis coordination.

This module consumes the P1 read-only boundary and P0 contracts. It does not
persist records, emit events, modify C1/P0/P1, run experiments, or mutate
production strategy. It provides proposal, validation, and lineage-scoped
coordination only.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from typing import Any, Mapping, Optional

from mindmargin.intelligence.c2_access import (
    C2ReadOnlyEvidenceAccess,
    LineageScope,
    ReadOnlyLineageView,
)
from mindmargin.intelligence.c2_contracts import (
    C2ConfidenceValue,
    C2DiagnosisRecord,
)


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
class DiagnosisValidation:
    valid: bool
    status: str
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    lineage: Optional[ReadOnlyLineageView] = None


@dataclass(frozen=True)
class DiagnosisOutcome:
    record: Optional[C2DiagnosisRecord]
    validation: DiagnosisValidation


class C2DiagnosisCoordinator:
    """An explicit coordinator for bounded diagnosis proposals.

    The coordinator keeps only an in-memory proposal cache for deterministic
    retry suppression during one invocation lifetime. It has no persistence
    surface and cannot be called from production paths by this module.
    """

    def __init__(self, access: C2ReadOnlyEvidenceAccess):
        if not isinstance(access, C2ReadOnlyEvidenceAccess):
            raise TypeError("access must be a C2ReadOnlyEvidenceAccess instance")
        self.access = access
        self._proposal_cache: dict[str, C2DiagnosisRecord] = {}

    def propose(
        self,
        *,
        problem_statement: str,
        evidence_ids: list[str] | tuple[str, ...],
        pipeline_id: str = "",
        content_id: str = "",
        story_id: str = "",
        video_id: str = "",
        correlation_id: str = "",
        observation_ids: list[str] | tuple[str, ...] = (),
        parent_record_ids: list[str] | tuple[str, ...] = (),
        source_record_ids: list[str] | tuple[str, ...] = (),
        diagnosis_type: str = "unknown_condition",
        candidate_explanations: tuple[dict[str, Any], ...] = (),
        ruled_out_explanations: tuple[dict[str, Any], ...] = (),
        confidence: Optional[C2ConfidenceValue] = None,
        severity: str = "informational",
        reproducibility: str = "unknown",
        recommended_next_step: str = "none",
        limitations: tuple[dict[str, Any], ...] = (),
        source: str = "c2.p2.diagnosis_coordinator",
        idempotency_key: str = "",
        causal_claim: None = None,
    ) -> C2DiagnosisRecord:
        """Create a planned in-memory proposal; validation is explicit."""
        logical_key = idempotency_key or self._logical_idempotency_key(
            problem_statement=problem_statement,
            evidence_ids=evidence_ids,
            diagnosis_type=diagnosis_type,
            pipeline_id=pipeline_id,
            content_id=content_id,
            video_id=video_id,
            correlation_id=correlation_id,
        )
        record = C2DiagnosisRecord.create(
            problem_statement=problem_statement,
            evidence_ids=evidence_ids,
            pipeline_id=pipeline_id,
            correlation_id=correlation_id,
            observation_ids=tuple(observation_ids),
            parent_record_ids=tuple(parent_record_ids),
            source_record_ids=tuple(source_record_ids) or tuple(evidence_ids),
            diagnosis_type=diagnosis_type,
            candidate_explanations=tuple(candidate_explanations),
            ruled_out_explanations=tuple(ruled_out_explanations),
            confidence=confidence,
            severity=severity,
            reproducibility=reproducibility,
            recommended_next_step=recommended_next_step,
            limitations=tuple(limitations),
            causal_claim=causal_claim,
            source=source,
            idempotency_key=logical_key,
            status="planned",
        )
        record = replace(
            record,
            envelope=replace(record.envelope, content_id=content_id, story_id=story_id),
        )
        cached = self._proposal_cache.get(record.envelope.idempotency_key)
        if cached is not None:
            return cached
        self._proposal_cache[record.envelope.idempotency_key] = record
        return record

    @staticmethod
    def _logical_idempotency_key(*, problem_statement: str, evidence_ids: list[str] | tuple[str, ...], diagnosis_type: str, pipeline_id: str, content_id: str, video_id: str, correlation_id: str) -> str:
        payload = json.dumps({
            "problem_statement": problem_statement,
            "evidence_ids": sorted(evidence_ids),
            "diagnosis_type": diagnosis_type,
            "pipeline_id": pipeline_id,
            "content_id": content_id,
            "video_id": video_id,
            "correlation_id": correlation_id,
        }, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return "diagnosis:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]

    def validate(self, record: C2DiagnosisRecord) -> DiagnosisValidation:
        """Validate a proposal against resolved P1 evidence and lineage."""
        errors: list[str] = []
        warnings: list[str] = []
        if not isinstance(record, C2DiagnosisRecord):
            return DiagnosisValidation(False, "rejected", ("record_type_invalid",))
        if record.status != "planned":
            errors.append("diagnosis_must_be_planned_before_validation")
        if record.causal_claim is not None:
            errors.append("causal_claim_must_be_null")
        if not isinstance(record.confidence, C2ConfidenceValue):
            errors.append("confidence_required")
        if record.problem_statement.strip() == "":
            errors.append("problem_statement_required")
        if not record.envelope.pipeline_id and not record.envelope.correlation_id:
            errors.append("lineage_scope_required")

        evidence_rows: list[dict[str, Any]] = []
        observation_rows: list[dict[str, Any]] = []
        for evidence_id in record.evidence_ids:
            evidence = self.access.get_evidence(evidence_id)
            if evidence is None:
                errors.append(f"evidence_not_found:{evidence_id}")
                continue
            evidence_rows.append(evidence)
            if evidence.get("validation_status") != "valid":
                errors.append(f"evidence_not_valid:{evidence_id}")
            if not evidence.get("provenance"):
                errors.append(f"evidence_provenance_missing:{evidence_id}")
            evidence_observation_ids = evidence.get("observation_ids") or []
            if not evidence_observation_ids:
                errors.append(f"evidence_observation_missing:{evidence_id}")
            for observation_id in evidence_observation_ids:
                observation = self.access.get_observation(observation_id)
                if observation is None:
                    errors.append(f"observation_not_found:{observation_id}")
                    continue
                observation_rows.append(observation)
                if observation.get("quality") != "valid":
                    errors.append(f"observation_not_valid:{observation_id}")
                if observation.get("freshness_seconds") is None:
                    errors.append(f"observation_freshness_unknown:{observation_id}")

        if not evidence_rows:
            errors.append("supporting_evidence_required")

        scope = self._scope_from_record(record)
        lineage = None
        if scope is not None:
            lineage = self.access.lineage_view(scope=scope)
            if lineage.status != "complete":
                errors.append(f"lineage_not_complete:{lineage.status}")
            if lineage.missing_ids:
                errors.append("lineage_missing_ids")
            if lineage.invalid_edges:
                errors.append("lineage_invalid_edges")
            warnings.extend(lineage.quality_warnings)
        else:
            errors.append("lineage_scope_required")

        for row in evidence_rows + observation_rows:
            errors.extend(self._scope_errors(record, row))

        for edge_type, edge_ids in (("parent", record.envelope.parent_record_ids), ("source", record.envelope.source_record_ids)):
            for related_id in edge_ids:
                related = self.access.resolve_record(related_id)
                if related is None:
                    errors.append(f"lineage_{edge_type}_not_found:{related_id}")
                    continue
                errors.extend(f"lineage_{edge_type}_scope_mismatch:{reason}" for reason in self.access.validate_scope(record.envelope.__dict__, related).reasons)

        errors.extend(self._explanation_errors(record))
        if not record.limitations:
            errors.append("limitations_required_for_observational_diagnosis")

        if errors:
            return DiagnosisValidation(
                valid=False,
                status="rejected",
                errors=tuple(dict.fromkeys(errors)),
                warnings=tuple(dict.fromkeys(warnings)),
                lineage=lineage,
            )
        return DiagnosisValidation(
            valid=True,
            status="validated",
            warnings=tuple(dict.fromkeys(warnings)),
            lineage=lineage,
        )

    def diagnose_for_lineage(
        self,
        *,
        scope: LineageScope,
        problem_statement: str,
        confidence: C2ConfidenceValue,
        diagnosis_type: str = "unknown_condition",
        candidate_explanations: tuple[dict[str, Any], ...] = (),
        ruled_out_explanations: tuple[dict[str, Any], ...] = (),
        limitations: tuple[dict[str, Any], ...] = (),
        observation_ids: list[str] | tuple[str, ...] = (),
        recommended_next_step: str = "none",
        severity: str = "informational",
        reproducibility: str = "unknown",
        idempotency_key: str = "",
    ) -> DiagnosisOutcome:
        """Propose and validate a diagnosis from one explicit P1 lineage scope."""
        view = self.access.lineage_view(scope=scope)
        evidence_ids = tuple(row.get("record_id", "") for row in view.records_by_type.get("evidence", ()))
        inferred_observation_ids = tuple(row.get("record_id", "") for row in view.records_by_type.get("observation", ()))
        if not evidence_ids:
            validation = DiagnosisValidation(
                valid=False,
                status="rejected",
                errors=("supporting_evidence_required", f"lineage_not_complete:{view.status}"),
                warnings=view.quality_warnings,
                lineage=view,
            )
            return DiagnosisOutcome(record=None, validation=validation)
        record = self.propose(
            problem_statement=problem_statement,
            evidence_ids=evidence_ids,
            pipeline_id=scope.pipeline_id,
            content_id=scope.content_id,
            video_id=scope.video_id,
            correlation_id=scope.correlation_id,
            observation_ids=tuple(observation_ids) or inferred_observation_ids,
            parent_record_ids=evidence_ids,
            source_record_ids=evidence_ids,
            diagnosis_type=diagnosis_type,
            candidate_explanations=candidate_explanations,
            ruled_out_explanations=ruled_out_explanations,
            confidence=confidence,
            severity=severity,
            reproducibility=reproducibility,
            recommended_next_step=recommended_next_step,
            limitations=limitations,
            idempotency_key=idempotency_key,
        )
        validation = self.validate(record)
        if not validation.valid:
            return DiagnosisOutcome(record=record.transition_to("rejected"), validation=validation)
        return DiagnosisOutcome(record=record.transition_to("validated"), validation=validation)

    @staticmethod
    def _scope_from_record(record: C2DiagnosisRecord) -> Optional[LineageScope]:
        envelope = record.envelope
        if not any((envelope.pipeline_id, envelope.content_id, envelope.video_id, envelope.correlation_id)):
            return None
        return LineageScope(
            pipeline_id=envelope.pipeline_id,
            content_id=envelope.content_id,
            video_id=envelope.video_id,
            correlation_id=envelope.correlation_id,
        )

    @staticmethod
    def _scope_errors(record: C2DiagnosisRecord, row: Mapping[str, Any]) -> list[str]:
        errors: list[str] = []
        envelope = record.envelope
        for field_name in ("pipeline_id", "content_id", "video_id", "correlation_id"):
            expected = getattr(envelope, field_name)
            if expected and str(row.get(field_name) or "") != expected:
                errors.append(f"{field_name}_scope_mismatch:{row.get(field_name) or 'missing'}")
        return errors

    @staticmethod
    def _explanation_errors(record: C2DiagnosisRecord) -> list[str]:
        errors: list[str] = []
        allowed_ids = set(record.evidence_ids)
        for field_name, explanations in (
            ("candidate_explanations", record.candidate_explanations),
            ("ruled_out_explanations", record.ruled_out_explanations),
        ):
            for index, explanation in enumerate(explanations):
                if not isinstance(explanation, Mapping):
                    errors.append(f"{field_name}[{index}]_must_be_object")
                    continue
                text = str(explanation.get("text") or explanation.get("label") or "")
                if not text.strip():
                    errors.append(f"{field_name}[{index}]_text_required")
                if C2DiagnosisCoordinator._has_causal_language(text):
                    errors.append(f"{field_name}[{index}]_causal_language")
                linked_ids = explanation.get("evidence_ids") or []
                if not linked_ids:
                    errors.append(f"{field_name}[{index}]_evidence_ids_required")
                elif not set(linked_ids).issubset(allowed_ids):
                    errors.append(f"{field_name}[{index}]_evidence_ids_outside_diagnosis")
        return errors

    @staticmethod
    def _has_causal_language(text: str) -> bool:
        lowered = f" {text.lower()} "
        return any(phrase in lowered for phrase in _CAUSAL_LANGUAGE)


__all__ = ["C2DiagnosisCoordinator", "DiagnosisOutcome", "DiagnosisValidation"]
