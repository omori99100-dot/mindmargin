# R5-A Staging Abort Matrix

**Status:** `REQUIRES_REVIEW`  
**Candidate:** `r4-rc-e1990e48a2c9109f714d`  
**Services:** API / Worker / Redis / Ollama topology only; not started.

## Threshold State

No trusted staging baseline exists in repository metadata. Therefore:

`THRESHOLD = REQUIRES BASELINE`

| Signal | Required threshold | Current state |
|---|---|---|
| Error rate | numeric staging baseline | `REQUIRES BASELINE` |
| Latency | numeric staging baseline | `REQUIRES BASELINE` |
| Timeout rate | numeric staging baseline | `REQUIRES BASELINE` |
| Retry rate | numeric staging baseline | `REQUIRES BASELINE` |
| Duplicate/lost state | zero-tolerance invariant | required; measurement procedure pending |
| Lineage failure | numeric or zero-tolerance invariant | required; procedure pending |
| Health failure | service-specific health threshold | required; owner/endpoint pending |
| Resource exhaustion | CPU/memory/storage threshold | required; host limits pending |
| Secret exposure | zero tolerance | `0 allowed` |
| Persistence collision | zero tolerance | `0 allowed`; currently a blocker until isolated |
| Network boundary violation | zero tolerance | `0 allowed`; host policy pending |

## Mandatory Abort Conditions

Do not start staging if shared `data` or `output` paths remain possible, if Redis/Ollama volume ownership is ambiguous, if host ports are exposed without an approved network boundary, if owner/kill-switch is missing, or if target-specific thresholds are absent.

If a running future staging check discovers any collision, forbidden side effect, duplicate/lost state, lineage gap, false success, credential request, or rollback uncertainty, stop and preserve evidence.

## Kill-Switch

A target-specific kill-switch command and owner are not defined. No command is invented. This field remains:

`REQUIRES EXPLICIT DECISION`

## Current Decision

`R5-A = REQUIRES_REVIEW` due persistence isolation, network boundary, thresholds, test volume, duration, and target-specific ownership gaps.
