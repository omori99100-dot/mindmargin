# R5-A Final Rollout Scope

**Status:** `REQUIRES_EXPLICIT_DECISION`  
**Recommended option:** controlled non-production staging Docker topology  
**Candidate:** `r4-rc-e1990e48a2c9109f714d`

## Proposed Scope

The recommended future scope is a controlled staging environment using the existing staging Docker topology (`api`, `worker`, `redis`, and `ollama`) with no external production traffic and no publish, scheduler, Workflow, or A/B activation.

This document defines a candidate architecture only. It does not select an actual host, cluster, network, component activation, traffic budget, or runtime duration.

## Required Explicit Values Before R5-B

- Staging host/cluster and network boundary.
- Component/path to exercise.
- Synthetic or controlled test volume.
- Observation duration.
- Operational, monitoring, abort, rollback, and escalation owners.
- Numeric error, latency, timeout, retry, and lineage thresholds.
- Kill-switch mechanism and recovery verification.
- Isolated data directory and persistence policy.

## Boundaries

No production credentials, OAuth tokens, production traffic, publish, scheduler, Workflow, A/B activation, production persistence, Git operation, candidate modification, or protected-area change is allowed.

C1, C2-P0–P9, Phase A/B, legacy APIs, `ExperimentResult`, DecisionStore/EventLedger, JSONL/SQLite, Workflow/SQLite remediation, and `PiperSettings.model_path` remain protected.

## Readiness Definition

R5-A can become PASS only when every required target-specific field is supplied and independently reviewable. Until then, the status remains `REQUIRES_REVIEW`, and R5-B/C/D remain unauthorized.
