"""Read-only C2-P1 access boundary over the frozen Phase A/B/C1 ledger.

This module does not write records, alter DecisionStore/EventLedger, invoke C1
collectors, create C2 records, or connect to production paths. It exposes typed
read/scope/lineage views for a future interpretation layer.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Optional, Protocol


class LedgerReader(Protocol):
    """Minimal read-only surface required from the existing DecisionStore."""

    @property
    def ledger(self) -> Any:  # pragma: no cover - protocol declaration
        ...


@dataclass(frozen=True)
class LineageScope:
    pipeline_id: str = ""
    content_id: str = ""
    video_id: str = ""
    correlation_id: str = ""

    def __post_init__(self) -> None:
        if not any((self.pipeline_id, self.content_id, self.video_id, self.correlation_id)):
            raise ValueError("at least one lineage scope identifier is required")


@dataclass(frozen=True)
class ScopeValidation:
    valid: bool
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class ReadOnlyLineageView:
    status: str
    scope: LineageScope
    records_by_type: dict[str, tuple[dict[str, Any], ...]]
    resolved_edges: tuple[dict[str, Any], ...] = ()
    missing_ids: tuple[str, ...] = ()
    invalid_edges: tuple[dict[str, Any], ...] = ()
    quality_warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "scope": {
                "pipeline_id": self.scope.pipeline_id,
                "content_id": self.scope.content_id,
                "video_id": self.scope.video_id,
                "correlation_id": self.scope.correlation_id,
            },
            "records_by_type": {key: list(value) for key, value in self.records_by_type.items()},
            "resolved_edges": list(self.resolved_edges),
            "missing_ids": list(self.missing_ids),
            "invalid_edges": list(self.invalid_edges),
            "quality_warnings": list(self.quality_warnings),
        }


_RECORD_ID_FIELDS = ("record_id", "decision_id", "event_id", "experiment_id")
_RECORD_TYPES = ("decision", "event", "experiment", "observation", "evidence")


class C2ReadOnlyEvidenceAccess:
    """Typed read-only facade over the existing DecisionStore.

    The facade only calls the existing ledger's read operation. It deliberately
    has no save/append/update methods, and returns copies of rows so callers
    cannot mutate the in-memory representation held by the ledger reader.
    """

    def __init__(self, store: LedgerReader):
        if not hasattr(store, "ledger") or not hasattr(store.ledger, "read"):
            raise TypeError("store must expose the existing read-only ledger.read interface")
        self._store = store

    def _all_rows(self) -> list[dict[str, Any]]:
        return [dict(row) for row in self._store.ledger.read()]

    @classmethod
    def _row_id(cls, row: Mapping[str, Any]) -> str:
        record_type = str(row.get("record_type") or "")
        preferred = {
            "decision": "decision_id",
            "event": "event_id",
            "experiment": "experiment_id",
            "observation": "record_id",
            "evidence": "record_id",
        }.get(record_type)
        if preferred and row.get(preferred):
            return str(row[preferred])
        for field_name in _RECORD_ID_FIELDS:
            value = row.get(field_name)
            if value:
                return str(value)
        return ""

    @staticmethod
    def _record_type(row: Mapping[str, Any]) -> str:
        value = row.get("record_type")
        if value:
            return str(value)
        event_type = row.get("event_type")
        if event_type:
            return "event"
        return ""

    def resolve_record(self, record_id: str) -> Optional[dict[str, Any]]:
        """Resolve one persisted Phase A/B/C1 record by its typed ID."""
        if not isinstance(record_id, str) or not record_id.strip():
            return None
        for row in self._all_rows():
            if self._row_id(row) == record_id:
                return row
        return None

    def get_observation(self, record_id: str) -> Optional[dict[str, Any]]:
        row = self.resolve_record(record_id)
        return row if row and self._record_type(row) == "observation" else None

    def get_evidence(self, record_id: str) -> Optional[dict[str, Any]]:
        row = self.resolve_record(record_id)
        return row if row and self._record_type(row) == "evidence" else None

    def validate_scope(self, child: Mapping[str, Any], parent: Mapping[str, Any]) -> ScopeValidation:
        """Validate explicit lineage scope; missing fields are not equalities."""
        reasons: list[str] = []
        for field_name in ("pipeline_id", "content_id", "video_id", "correlation_id"):
            child_value = str(child.get(field_name) or "")
            parent_value = str(parent.get(field_name) or "")
            if child_value and parent_value and child_value != parent_value:
                reasons.append(f"{field_name}_mismatch")
        return ScopeValidation(valid=not reasons, reasons=tuple(reasons))

    @staticmethod
    def _matches_scope(row: Mapping[str, Any], scope: LineageScope) -> bool:
        for field_name in ("pipeline_id", "content_id", "video_id", "correlation_id"):
            requested = getattr(scope, field_name)
            if requested and str(row.get(field_name) or "") != requested:
                return False
        return True

    @staticmethod
    def _scope_reasons(row: Mapping[str, Any], scope: LineageScope) -> list[str]:
        reasons: list[str] = []
        for field_name in ("pipeline_id", "content_id", "video_id", "correlation_id"):
            requested = getattr(scope, field_name)
            if requested and not row.get(field_name):
                reasons.append(f"missing_{field_name}")
            elif requested and str(row.get(field_name)) != requested:
                reasons.append(f"{field_name}_mismatch")
        return reasons

    def _rows_for_scope(self, scope: LineageScope, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [row for row in rows if self._matches_scope(row, scope)]

    def lineage_view(self, *, scope: LineageScope) -> ReadOnlyLineageView:
        """Build a conservative lineage report without fabricating edges."""
        all_rows = self._all_rows()
        scoped_rows = self._rows_for_scope(scope, all_rows)
        by_id = {self._row_id(row): row for row in all_rows if self._row_id(row)}
        records_by_type: dict[str, tuple[dict[str, Any], ...]] = {
            record_type: tuple(dict(row) for row in scoped_rows if self._record_type(row) == record_type)
            for record_type in _RECORD_TYPES
        }
        missing_ids: list[str] = []
        invalid_edges: list[dict[str, Any]] = []
        resolved_edges: list[dict[str, Any]] = []
        warnings: list[str] = []

        if not scoped_rows:
            return ReadOnlyLineageView(
                status="not_found",
                scope=scope,
                records_by_type=records_by_type,
            )

        for child in scoped_rows:
            child_id = self._row_id(child)
            child_type = self._record_type(child)
            if child_type in {"observation", "evidence"}:
                if not child.get("correlation_id"):
                    invalid_edges.append({"from": child_id, "to": child_id, "type": "missing_correlation"})
                if child_type == "observation":
                    if child.get("quality") != "valid":
                        warnings.append(f"observation_quality:{child_id}:{child.get('quality', 'unknown')}")
                    if child.get("freshness_seconds") is None:
                        warnings.append(f"observation_freshness_unknown:{child_id}")
                if child_type == "evidence":
                    validation_status = child.get("validation_status")
                    if validation_status != "valid":
                        warnings.append(f"evidence_validation:{child_id}:{validation_status or 'unknown'}")
                    if not child.get("provenance"):
                        warnings.append(f"evidence_provenance_missing:{child_id}")

                for edge_type, ids in (
                    ("parent", child.get("parent_record_ids", [])),
                    ("source", child.get("source_record_ids", [])),
                ):
                    for related_id in ids or []:
                        edge = {"from": related_id, "to": child_id, "type": edge_type}
                        related = by_id.get(related_id)
                        if related is None:
                            missing_ids.append(related_id)
                            invalid_edges.append(edge)
                            continue
                        scope_check = self.validate_scope(child, related)
                        if not scope_check.valid:
                            edge["reason"] = list(scope_check.reasons)
                            invalid_edges.append(edge)
                            continue
                        resolved_edges.append(edge)

        if not records_by_type["observation"]:
            warnings.append("missing_observation")
        if records_by_type["observation"] and not records_by_type["evidence"]:
            warnings.append("missing_evidence")
        if records_by_type["evidence"]:
            for evidence in records_by_type["evidence"]:
                if evidence.get("validation_status") != "valid":
                    warnings.append("non_valid_evidence_present")
                    break

        unique_missing = tuple(dict.fromkeys(missing_ids))
        unique_warnings = tuple(dict.fromkeys(warnings))
        status = "complete" if (
            bool(records_by_type["observation"])
            and bool(records_by_type["evidence"])
            and not invalid_edges
            and not unique_missing
            and "non_valid_evidence_present" not in unique_warnings
            and not any(item.startswith("observation_quality:") for item in unique_warnings)
            and not any(item.startswith("observation_freshness_unknown:") for item in unique_warnings)
            and not any(item.startswith("evidence_provenance_missing:") for item in unique_warnings)
        ) else "partial"
        return ReadOnlyLineageView(
            status=status,
            scope=scope,
            records_by_type=records_by_type,
            resolved_edges=tuple(resolved_edges),
            missing_ids=unique_missing,
            invalid_edges=tuple(invalid_edges),
            quality_warnings=unique_warnings,
        )


__all__ = [
    "C2ReadOnlyEvidenceAccess",
    "LedgerReader",
    "LineageScope",
    "ReadOnlyLineageView",
    "ScopeValidation",
]
