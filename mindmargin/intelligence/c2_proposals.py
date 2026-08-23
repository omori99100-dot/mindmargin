"""C2-P4 experiment proposal boundary.

This module defines and validates proposals only. It does not execute, schedule,
persist, publish, mutate A/B state, or integrate with production paths.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass, field, replace
from typing import Any, Mapping, Optional

from mindmargin.intelligence.c2_access import C2ReadOnlyEvidenceAccess, LineageScope
from mindmargin.intelligence.c2_contracts import C2ConfidenceValue, C2HypothesisRecord
from mindmargin.intelligence.c2_hypothesis import C2HypothesisRegistry
from mindmargin.intelligence.metric_registry import MetricRegistry

_CAUSAL_LANGUAGE = (" caused ", " causes ", " cause ", "causal", "causally", "directly led to", "resulted in")
_PROPOSAL_STATUSES = ("proposed", "validated", "rejected")
_ALLOWED_RULE_OPERATORS = {"gt", "gte", "lt", "lte", "eq", "neq", "between"}
_ALLOWED_VARIANT_ROLES = {"control", "treatment"}


@dataclass(frozen=True)
class C2ExperimentProposal:
    proposal_id: str
    hypothesis_id: str
    supporting_evidence_ids: tuple[str, ...]
    decision_ids: tuple[str, ...]
    metric_name: str
    variants: tuple[dict[str, Any], ...]
    population: dict[str, Any]
    eligibility: dict[str, Any]
    minimum_sample: int
    success_rule: dict[str, Any]
    inconclusive_rule: dict[str, Any]
    safety_constraints: tuple[dict[str, Any], ...]
    rollback_criteria: tuple[dict[str, Any], ...]
    envelope: dict[str, Any]
    status: str = "proposed"

    def __post_init__(self) -> None:
        if self.status not in _PROPOSAL_STATUSES:
            raise ValueError(f"unsupported proposal status: {self.status}")
        if self.envelope.get("record_type") != "experiment_proposal":
            raise ValueError("proposal envelope record_type must be experiment_proposal")
        if self.envelope.get("record_id") != self.proposal_id:
            raise ValueError("proposal_id must match envelope record_id")
        if self.envelope.get("status") != self.status:
            raise ValueError("proposal and envelope status must match")
        if not self.hypothesis_id.strip():
            raise ValueError("hypothesis_id is required")
        if not self.supporting_evidence_ids:
            raise ValueError("supporting_evidence_ids are required")
        if not self.decision_ids:
            raise ValueError("decision_ids are required")
        if not self.metric_name.strip():
            raise ValueError("metric_name is required")
        if self.minimum_sample <= 0:
            raise ValueError("minimum_sample must be positive")

    @classmethod
    def create(
        cls,
        *,
        hypothesis_id: str,
        supporting_evidence_ids: list[str] | tuple[str, ...],
        decision_ids: list[str] | tuple[str, ...],
        metric_name: str,
        variants: list[dict[str, Any]] | tuple[dict[str, Any], ...],
        population: dict[str, Any],
        eligibility: dict[str, Any],
        minimum_sample: int,
        success_rule: dict[str, Any],
        inconclusive_rule: dict[str, Any],
        safety_constraints: list[dict[str, Any]] | tuple[dict[str, Any], ...],
        rollback_criteria: list[dict[str, Any]] | tuple[dict[str, Any], ...],
        pipeline_id: str = "",
        content_id: str = "",
        story_id: str = "",
        video_id: str = "",
        correlation_id: str = "",
        parent_record_ids: list[str] | tuple[str, ...] = (),
        source_record_ids: list[str] | tuple[str, ...] = (),
        idempotency_key: str = "",
        status: str = "proposed",
    ) -> "C2ExperimentProposal":
        proposal_id = f"prop_c2_{uuid.uuid4().hex}"
        evidence = tuple(supporting_evidence_ids)
        decisions = tuple(decision_ids)
        logical_key = idempotency_key or _logical_key(
            hypothesis_id=hypothesis_id,
            evidence=evidence,
            decisions=decisions,
            metric_name=metric_name,
            success_rule=success_rule,
            inconclusive_rule=inconclusive_rule,
        )
        envelope = {
            "record_type": "experiment_proposal",
            "record_id": proposal_id,
            "schema_version": "c2-p4-1",
            "pipeline_id": pipeline_id,
            "content_id": content_id,
            "story_id": story_id,
            "video_id": video_id,
            "correlation_id": correlation_id or pipeline_id,
            "parent_record_ids": tuple(parent_record_ids),
            "source_record_ids": tuple(source_record_ids) or tuple(dict.fromkeys(evidence + decisions + (hypothesis_id,))),
            "idempotency_key": logical_key,
            "status": status,
            "source": "c2.p4.proposal_boundary",
        }
        return cls(
            proposal_id=proposal_id,
            hypothesis_id=hypothesis_id,
            supporting_evidence_ids=evidence,
            decision_ids=decisions,
            metric_name=metric_name,
            variants=tuple(variants),
            population=dict(population),
            eligibility=dict(eligibility),
            minimum_sample=minimum_sample,
            success_rule=dict(success_rule),
            inconclusive_rule=dict(inconclusive_rule),
            safety_constraints=tuple(safety_constraints),
            rollback_criteria=tuple(rollback_criteria),
            envelope=envelope,
            status=status,
        )

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "record_type": "experiment_proposal",
            "proposal_id": self.proposal_id,
            "hypothesis_id": self.hypothesis_id,
            "supporting_evidence_ids": list(self.supporting_evidence_ids),
            "decision_ids": list(self.decision_ids),
            "metric_name": self.metric_name,
            "variants": list(self.variants),
            "population": self.population,
            "eligibility": self.eligibility,
            "minimum_sample": self.minimum_sample,
            "success_rule": self.success_rule,
            "inconclusive_rule": self.inconclusive_rule,
            "safety_constraints": list(self.safety_constraints),
            "rollback_criteria": list(self.rollback_criteria),
            "envelope": self.envelope,
            "status": self.status,
        }
        return _sanitize(payload)


@dataclass(frozen=True)
class ProposalValidation:
    valid: bool
    status: str
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    lineage: Optional[dict[str, Any]] = None


@dataclass(frozen=True)
class ProposalOutcome:
    proposal: Optional[C2ExperimentProposal]
    validation: ProposalValidation


class C2ExperimentProposalBoundary:
    """In-memory proposal registry; it has no execution or persistence methods."""

    def __init__(self, access: C2ReadOnlyEvidenceAccess, hypotheses: C2HypothesisRegistry, metrics: Optional[MetricRegistry] = None):
        if not isinstance(access, C2ReadOnlyEvidenceAccess):
            raise TypeError("access must be C2ReadOnlyEvidenceAccess")
        if not isinstance(hypotheses, C2HypothesisRegistry):
            raise TypeError("hypotheses must be C2HypothesisRegistry")
        self.access = access
        self.hypotheses = hypotheses
        self.metrics = metrics or MetricRegistry()
        self._by_key: dict[str, C2ExperimentProposal] = {}
        self._by_id: dict[str, C2ExperimentProposal] = {}

    def propose(self, **kwargs: Any) -> C2ExperimentProposal:
        """Create a typed proposal only; validation is explicit and no execution occurs."""
        logical_key = kwargs.get("idempotency_key") or _logical_key(
            hypothesis_id=kwargs.get("hypothesis_id", ""),
            evidence=tuple(kwargs.get("supporting_evidence_ids", ())),
            decisions=tuple(kwargs.get("decision_ids", ())),
            metric_name=kwargs.get("metric_name", ""),
            success_rule=kwargs.get("success_rule", {}),
            inconclusive_rule=kwargs.get("inconclusive_rule", {}),
        )
        existing = self._by_key.get(logical_key)
        if existing is not None:
            return existing
        create_kwargs = dict(kwargs)
        create_kwargs["idempotency_key"] = logical_key
        proposal = C2ExperimentProposal.create(**create_kwargs)
        self._by_key[logical_key] = proposal
        self._by_id[proposal.proposal_id] = proposal
        return proposal

    def get(self, proposal_id: str) -> Optional[C2ExperimentProposal]:
        return self._by_id.get(proposal_id)

    def validate(self, proposal: C2ExperimentProposal) -> ProposalValidation:
        errors: list[str] = []
        warnings: list[str] = []
        if not isinstance(proposal, C2ExperimentProposal):
            return ProposalValidation(False, "rejected", ("proposal_type_invalid",))
        if proposal.status != "proposed":
            errors.append("proposal_must_be_proposed_before_validation")
        hypothesis = self.hypotheses.get(proposal.hypothesis_id)
        if hypothesis is None:
            errors.append("hypothesis_not_found")
        else:
            if hypothesis.status != "testable":
                errors.append("hypothesis_must_be_testable")
            if hypothesis.causality_status != "not_claimed":
                errors.append("causality_status_must_be_not_claimed")
            if self._has_causal_language(hypothesis.statement):
                errors.append("hypothesis_causal_language")
            if set(proposal.supporting_evidence_ids) != set(hypothesis.supporting_evidence_ids):
                errors.append("proposal_evidence_must_match_hypothesis")
            errors.extend(self._scope_mismatch(proposal.envelope, hypothesis.envelope))
        if not proposal.supporting_evidence_ids:
            errors.append("supporting_evidence_required")
        evidence_rows: list[dict[str, Any]] = []
        for evidence_id in proposal.supporting_evidence_ids:
            evidence = self.access.get_evidence(evidence_id)
            if evidence is None:
                errors.append(f"evidence_not_found:{evidence_id}")
                continue
            evidence_rows.append(evidence)
            if evidence.get("validation_status") != "valid":
                errors.append(f"evidence_not_valid:{evidence_id}")
            if not evidence.get("provenance"):
                errors.append(f"evidence_provenance_missing:{evidence_id}")
            for observation_id in evidence.get("observation_ids") or []:
                observation = self.access.get_observation(observation_id)
                if observation is None:
                    errors.append(f"observation_not_found:{observation_id}")
                else:
                    if observation.get("quality") != "valid":
                        errors.append(f"observation_not_valid:{observation_id}")
                    if observation.get("freshness_seconds") is None:
                        errors.append(f"observation_freshness_unknown:{observation_id}")
                errors.extend(self._scope_mismatch(proposal.envelope, observation or {}))
            errors.extend(self._scope_mismatch(proposal.envelope, evidence))
        if not evidence_rows:
            errors.append("evidence_required")

        for decision_id in proposal.decision_ids:
            decision = self.access.resolve_record(decision_id)
            if decision is None or decision.get("record_type") != "decision":
                errors.append(f"decision_not_found:{decision_id}")
            else:
                errors.extend(self._scope_mismatch(proposal.envelope, decision))
        if not proposal.decision_ids:
            errors.append("decision_required")

        try:
            metric = self.metrics.require(proposal.metric_name)
        except ValueError:
            metric = None
            errors.append("metric_not_registered")
        if metric is not None and metric.name != proposal.metric_name:
            errors.append("metric_identity_mismatch")

        if proposal.minimum_sample <= 0:
            errors.append("minimum_sample_must_be_positive")
        if proposal.minimum_sample < 2:
            errors.append("minimum_sample_gate_too_low")
        errors.extend(self._validate_variants(proposal.variants))
        errors.extend(self._validate_population_eligibility(proposal.population, proposal.eligibility))
        errors.extend(self._validate_rule("success_rule", proposal.success_rule, proposal.metric_name))
        errors.extend(self._validate_rule("inconclusive_rule", proposal.inconclusive_rule, proposal.metric_name))
        if proposal.success_rule == proposal.inconclusive_rule:
            errors.append("success_and_inconclusive_rules_must_differ")
        if not proposal.safety_constraints:
            errors.append("safety_constraints_required")
        if not proposal.rollback_criteria:
            errors.append("rollback_criteria_required")
        errors.extend(self._validate_safety(proposal.safety_constraints, proposal.rollback_criteria))
        if self._has_causal_language(json.dumps(proposal.to_dict(), ensure_ascii=False)):
            errors.append("proposal_causal_language")

        lineage = self.get_lineage(proposal.proposal_id)
        if lineage["status"] != "complete":
            errors.append(f"lineage_not_complete:{lineage['status']}")
        if lineage["missing_ids"]:
            errors.append("lineage_missing_ids")
        if lineage["invalid_edges"]:
            errors.append("lineage_invalid_edges")
        if errors:
            return ProposalValidation(False, "rejected", tuple(dict.fromkeys(errors)), tuple(dict.fromkeys(warnings)), lineage)
        return ProposalValidation(True, "validated", warnings=tuple(dict.fromkeys(warnings)), lineage=lineage)

    def approve(self, proposal: C2ExperimentProposal) -> ProposalOutcome:
        """Validate only; no method here can execute or schedule a proposal."""
        validation = self.validate(proposal)
        if not validation.valid:
            return ProposalOutcome(proposal, validation)
        validated = replace(proposal, status="validated", envelope={**proposal.envelope, "status": "validated"})
        self._by_id[validated.proposal_id] = validated
        self._by_key[validated.envelope["idempotency_key"]] = validated
        return ProposalOutcome(validated, validation)

    def get_lineage(self, proposal_id: str) -> dict[str, Any]:
        proposal = self.get(proposal_id)
        if proposal is None:
            return {"status": "not_found", "proposal_id": proposal_id, "records_by_type": {}, "resolved_edges": [], "missing_ids": [], "invalid_edges": [], "quality_warnings": []}
        scope = LineageScope(
            pipeline_id=proposal.envelope.get("pipeline_id", ""),
            content_id=proposal.envelope.get("content_id", ""),
            video_id=proposal.envelope.get("video_id", ""),
            correlation_id=proposal.envelope.get("correlation_id", ""),
        )
        base = self.access.lineage_view(scope=scope).to_dict()
        records = dict(base["records_by_type"])
        records.setdefault("hypothesis", [])
        records.setdefault("experiment_proposal", [])
        hypothesis = self.hypotheses.get(proposal.hypothesis_id)
        resolved = list(base["resolved_edges"])
        missing = list(base["missing_ids"])
        invalid = list(base["invalid_edges"])
        if hypothesis is None:
            missing.append(proposal.hypothesis_id)
            invalid.append({"from": proposal.hypothesis_id, "to": proposal_id, "type": "hypothesis"})
        else:
            records["hypothesis"].append(hypothesis.to_dict())
            resolved.append({"from": proposal.hypothesis_id, "to": proposal_id, "type": "hypothesis"})
        for decision_id in proposal.decision_ids:
            decision = self.access.resolve_record(decision_id)
            if decision is None:
                missing.append(decision_id)
                invalid.append({"from": decision_id, "to": proposal_id, "type": "decision"})
            else:
                records.setdefault("decision", []).append(decision)
                resolved.append({"from": decision_id, "to": proposal_id, "type": "decision"})
        for evidence_id in proposal.supporting_evidence_ids:
            evidence = self.access.get_evidence(evidence_id)
            if evidence is None:
                missing.append(evidence_id)
                invalid.append({"from": evidence_id, "to": proposal_id, "type": "supporting_evidence"})
            else:
                resolved.append({"from": evidence_id, "to": proposal_id, "type": "supporting_evidence"})
        missing = list(dict.fromkeys(missing))
        status = "complete" if base["status"] == "complete" and not missing and not invalid else "partial"
        records["experiment_proposal"].append(proposal.to_dict())
        return {"status": status, "proposal_id": proposal_id, "records_by_type": records, "resolved_edges": resolved, "missing_ids": missing, "invalid_edges": invalid, "quality_warnings": list(base["quality_warnings"])}

    @staticmethod
    def _validate_variants(variants: tuple[dict[str, Any], ...]) -> list[str]:
        errors: list[str] = []
        if len(variants) < 2:
            errors.append("at_least_two_variants_required")
            return errors
        ids: set[str] = set()
        roles: set[str] = set()
        for index, variant in enumerate(variants):
            if not isinstance(variant, Mapping):
                errors.append(f"variant_{index}_must_be_object")
                continue
            variant_id = str(variant.get("variant_id") or "")
            role = str(variant.get("role") or "")
            if not variant_id:
                errors.append(f"variant_{index}_id_required")
            elif variant_id in ids:
                errors.append("variant_ids_must_be_unique")
            ids.add(variant_id)
            if role not in _ALLOWED_VARIANT_ROLES:
                errors.append(f"variant_{index}_role_invalid")
            roles.add(role)
            if not str(variant.get("description") or "").strip():
                errors.append(f"variant_{index}_description_required")
        if roles != _ALLOWED_VARIANT_ROLES:
            errors.append("control_and_treatment_required")
        return errors

    @staticmethod
    def _validate_population_eligibility(population: Mapping[str, Any], eligibility: Mapping[str, Any]) -> list[str]:
        errors: list[str] = []
        if not population or not str(population.get("unit") or "").strip():
            errors.append("population_unit_required")
        if not population or not str(population.get("scope") or "").strip():
            errors.append("population_scope_required")
        if not eligibility or not str(eligibility.get("rule") or eligibility.get("description") or "").strip():
            errors.append("eligibility_rule_required")
        return errors

    @staticmethod
    def _validate_rule(name: str, rule: Mapping[str, Any], metric_name: str) -> list[str]:
        errors: list[str] = []
        if not rule:
            return [f"{name}_required"]
        if rule.get("metric") != metric_name:
            errors.append(f"{name}_metric_mismatch")
        if rule.get("operator") not in _ALLOWED_RULE_OPERATORS:
            errors.append(f"{name}_operator_invalid")
        if "threshold" not in rule:
            errors.append(f"{name}_threshold_required")
        if not str(rule.get("window") or "").strip():
            errors.append(f"{name}_window_required")
        return errors

    @staticmethod
    def _validate_safety(safety: tuple[dict[str, Any], ...], rollback: tuple[dict[str, Any], ...]) -> list[str]:
        errors: list[str] = []
        for name, items in (("safety", safety), ("rollback", rollback)):
            for index, item in enumerate(items):
                if not isinstance(item, Mapping):
                    errors.append(f"{name}_{index}_must_be_object")
                    continue
                if not str(item.get("condition") or item.get("criterion") or "").strip():
                    errors.append(f"{name}_{index}_condition_required")
                if not str(item.get("action") or "").strip():
                    errors.append(f"{name}_{index}_action_required")
        return errors

    @staticmethod
    def _scope_mismatch(expected: Mapping[str, Any], actual: Mapping[str, Any] | Any) -> list[str]:
        errors: list[str] = []
        for field_name in ("pipeline_id", "content_id", "video_id", "correlation_id"):
            value = expected.get(field_name, "")
            actual_value = actual.get(field_name, "") if isinstance(actual, Mapping) else getattr(actual, field_name, "")
            if value and str(actual_value or "") != value:
                errors.append(f"{field_name}_scope_mismatch")
        return errors

    @staticmethod
    def _has_causal_language(text: str) -> bool:
        lowered = f" {text.lower()} "
        return any(phrase in lowered for phrase in _CAUSAL_LANGUAGE)


def _logical_key(*, hypothesis_id: str, evidence: tuple[str, ...], decisions: tuple[str, ...], metric_name: str, success_rule: Mapping[str, Any], inconclusive_rule: Mapping[str, Any]) -> str:
    payload = json.dumps({"hypothesis_id": hypothesis_id, "evidence": sorted(evidence), "decisions": sorted(decisions), "metric": metric_name, "success": success_rule, "inconclusive": inconclusive_rule}, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "proposal:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


_SECRET = re.compile(r"(?i)(api[_-]?key|token|secret|password|authorization|credential|bearer)")

def _sanitize(value: Any, key: str = "") -> Any:
    if _SECRET.search(key):
        return "[REDACTED]"
    if isinstance(value, Mapping):
        top_level = {
            "record_type", "proposal_id", "hypothesis_id", "supporting_evidence_ids", "decision_ids", "metric_name",
            "variants", "population", "eligibility", "minimum_sample", "success_rule", "inconclusive_rule",
            "safety_constraints", "rollback_criteria", "envelope", "status",
        }
        nested = {
            "record_type", "record_id", "schema_version", "pipeline_id", "content_id", "story_id", "video_id",
            "correlation_id", "parent_record_ids", "source_record_ids", "idempotency_key", "source", "status",
            "variant_id", "role", "description", "unit", "scope", "rule", "metric", "operator", "threshold",
            "window", "condition", "criterion", "action", "reason", "value", "type", "name",
        }
        allowed = top_level if key == "" else nested
        return {str(k): _sanitize(v, str(k)) for k, v in value.items() if str(k) in allowed}
    if isinstance(value, (list, tuple)):
        return [_sanitize(item, key) for item in value]
    if isinstance(value, str) and _SECRET.search(value):
        return "[REDACTED]"
    return value


__all__ = ["C2ExperimentProposal", "C2ExperimentProposalBoundary", "ProposalOutcome", "ProposalValidation"]
