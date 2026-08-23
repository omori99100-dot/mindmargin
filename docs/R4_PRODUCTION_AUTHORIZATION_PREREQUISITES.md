# R4 Production Authorization Prerequisites

## Purpose

هذا المستند يحدد الأدلة المطلوبة قبل تقديم طلب Production Authorization مستقل. لا يمنح هذا المستند authorization ولا ينفذ production traffic أو rollout.

## Authorization boundary

R4 يقيّم governance metadata وsecurity metadata وobservability وrollback prerequisites في sandbox فقط. Production Authorization، production credentials، production traffic، publish، scheduler، Workflow، وA/B activation تقع خارج R4 وتحتاج تفويضًا منفصلًا.

## Required gates

| Gate | Required evidence | Current status |
|---|---|---|
| Immutable release candidate | source reference، manifest، hashes، owner | `REQUIRES_REVIEW` |
| Contract preservation | C1/C2/Phase A/B/legacy matrix | `PASS / PRESERVED` |
| Security boundary | no secrets in code/artifacts/logs، redaction proof | `SANDBOX PASS` |
| Configuration boundary | metadata-only review، no credential values | `SANDBOX PASS` |
| Observability | correlation، metrics، SLO، alert owner، runbook | `REQUIRED BEFORE AUTHORIZATION` |
| Rollback | trigger، owner، kill-switch، recovery evidence | `SANDBOX PASS / PRODUCTION APPROVAL REQUIRED` |
| Risk acceptance | formal owner approval for Piper warning | `PENDING` |
| Operational ownership | release owner، approver، operator، escalation | `PENDING` |

## Security and credential boundary

No production credentials or OAuth tokens may be read, copied, logged, serialized, or used by R4. Configuration checks may inspect names, types, modes, and non-secret metadata only. Any secret exposure is an immediate STOP condition.

## Observability prerequisites

A future authorization request must define structured logs, correlation IDs, latency/error/retry metrics, SLOs, alert thresholds, owners, runbooks, retention, and redaction. Business outcomes must remain distinct from operational success.

## Rollback and kill-switch prerequisites

A future production request must identify measurable abort triggers, a named decision owner, a tested kill-switch, a non-destructive rollback path, post-rollback verification, and an audit trail. Deleting ledgers, resetting databases, or changing Git history is not an accepted rollback.

## Risk acceptance

`PiperSettings.model_path` remains `ACCEPTED-RISK / DEFERRED-REMEDIATION`. R4 does not modify it. Production Authorization cannot treat this status as formal approval until an accountable production risk owner records explicit acceptance or a separate remediation authorization is granted.

## Protected areas

C1, C2-P0–P9, Phase A/B, legacy APIs, `ExperimentResult`, DecisionStore/EventLedger, JSONL/SQLite, Workflow remediation, SQLite remediation, production paths, Knowledge, Strategy, P10, and `PiperSettings.model_path` remain protected.

## Decision rule

R4 may produce a readiness result, but it cannot grant Production Authorization. Any dependency outside the R4 allow-list is:

`BLOCKED — SEPARATE AUTHORIZATION REQUIRED`
