# R5-A Controlled Rollout Scope Record

**Status:** `REQUIRES_REVIEW`  
**Reference Candidate:** `r4-rc-e1990e48a2c9109f714d`  
**Immutable Reference:** `release_candidates/r4-rc-e1990e48a2c9109f714d/release_snapshot.tar.gz`  
**Production Authorization:** `GRANTED for candidate only`  
**Production Rollout:** `NOT_GRANTED`

## Scope Decision

R5-A is limited to defining a future controlled rollout. It does not activate production, publish, schedule, start Workflow/A-B, use credentials, or modify the candidate.

The repository contains generic production deployment metadata, including a Docker Compose production topology with API, worker, Redis, Ollama, and nginx services, and a deployment checklist referring to YouTube OAuth, GitHub Actions, daily jobs, and production configuration. These are **options and metadata only**; they are not treated as an authorized rollout target.

## Known

| Field | Current evidence |
|---|---|
| Candidate | `r4-rc-e1990e48a2c9109f714d` |
| Candidate artifact | Immutable snapshot and manifest exist |
| Production Authorization | Granted for the candidate only |
| Rollout Authorization | Not granted by this R5-A authorization |
| Generic deployment options | Docker production topology and checklist exist |
| Protected areas | Explicitly frozen/protected by governance |
| Credential boundary | No credentials may be read or used in R5-A |

## Unknown / Requires Explicit Input

The following cannot be safely inferred from repository metadata:

- Actual production target machine or service.
- Target environment and network boundary.
- Component/path to activate.
- Traffic percentage, volume, audience, or request budget.
- Rollout duration and observation window.
- Operational owner for the selected target.
- Numeric latency, error, retry, and failure thresholds tied to that target.
- Kill-switch endpoint or operator procedure for the target.
- Target-specific rollback command and recovery verification.

Therefore:

> `UNKNOWN / REQUIRES EXPLICIT INPUT`

## Realistic Options

The repository exposes generic options, not an approved choice:

1. Docker production topology (`api`, `worker`, `redis`, `ollama`, `nginx`) — **not selected** because it implies production environment and persistence boundaries.
2. GitHub Actions/daily job — **not selected** because it implies secrets, scheduler activation, and external execution.
3. YouTube publish path — **not selected** because it implies OAuth credentials, external traffic, and irreversible side effects.
4. Sandbox or controlled non-production probe — architecturally safest, but no concrete target/environment is defined in the repository.

## Recommended Architectural Choice

The safest future choice is a dedicated non-production controlled environment with zero external traffic and no publish/scheduler/Workflow/A-B activation. It is not selected as an executable target because its actual environment, endpoint, owner, and limits are not present.

## Blocking Decision

R5-A cannot reach PASS until a decision owner supplies or explicitly approves target, environment, component, traffic limit, duration, operational owner, numeric thresholds, kill-switch, rollback procedure, and recovery verification.

Any attempt to infer these values from generic production files is:

`BLOCKED — SEPARATE AUTHORIZATION REQUIRED`

## Protected Areas

C1, C2-P0–P9, Phase A/B, legacy APIs, `ExperimentResult`, DecisionStore/EventLedger, JSONL/SQLite, Workflow/SQLite remediation, `PiperSettings.model_path`, Knowledge, Strategy, P10, the immutable candidate, and Git history remain untouched.
