# R4 Release Candidate Governance Metadata

## Governance status

- `r3_status`: `REQUIRES_REVIEW`
- `r4_status`: `IN_PROGRESS`
- `production_authorization`: `NOT_GRANTED`
- `production_rollout`: `NOT_GRANTED`
- `execution_mode`: `GOVERNANCE_ONLY`

## Candidate status

- `candidate_status`: `NOT_CREATED`
- `candidate_id`: `UNASSIGNED`
- `source_reference`: `UNSET`
- `immutable_reference`: `REQUIRED_BEFORE_PRODUCTION_AUTHORIZATION`
- `artifact_manifest`: `REQUIRED`
- `artifact_hashes`: `REQUIRED`
- `release_owner`: `UNASSIGNED`
- `technical_reviewer`: `UNASSIGNED`
- `production_approver`: `UNASSIGNED`
- `operator`: `UNASSIGNED`
- `rollback_reference`: `REQUIRED`

The current workspace is explicitly **not** a release candidate. No commit, tag, staging, cleanup, normalization, or Git-history operation is performed by R4.

## Protected baseline

- `C1 = OFFICIALLY CLOSED / FROZEN`
- `C2-P0–P9 = PASS / PRESERVED`
- `R1.2 = CLOSED`
- `R2 = PASS — CONTROLLED INTEGRATION READINESS ONLY`
- Workflow remediation = `CLOSED`
- SQLite remediation = `CLOSED`

## Required release evidence

Before a future Production Authorization request, the candidate must have a complete manifest, immutable source reference, runtime/dependency fingerprint, contract/schema matrix, exact test evidence, security/redaction evidence, observability evidence, rollback reference, ownership, approval record, and risk register.

## Risk register summary

| Risk | Current status | Required disposition |
|---|---|---|
| `PiperSettings.model_path` warning | `ACCEPTED-RISK / DEFERRED-REMEDIATION` | Formal production risk acceptance or separate remediation authorization |
| Dirty/non-immutable workspace | `OPEN` | Define immutable candidate outside current workspace |
| Production credentials | `NOT_USED` | Separate authorization and least-privilege review |
| Production traffic | `NOT_USED` | Separate rollout authorization |

## Forbidden actions in R4

R4 does not create or approve a release candidate, does not use production credentials or traffic, and does not modify protected contracts, production modules, persistence architecture, Git history, or `PiperSettings.model_path`.
