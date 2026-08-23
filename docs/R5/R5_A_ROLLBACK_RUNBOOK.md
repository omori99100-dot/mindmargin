# R5-A Controlled Rollout Rollback Runbook

**Status:** `REQUIRES_REVIEW`  
**Candidate:** `r4-rc-e1990e48a2c9109f714d`  
**Production Rollout:** `NOT_GRANTED`

## Rollback Boundary

Rollback must be non-destructive and limited to the explicitly selected rollout component. It must not delete ledger records, reset SQLite, alter Git history, modify the immutable candidate, or change C1/C2/Phase A/B contracts.

## Required Procedure

1. Freeze expansion immediately when an abort condition is observed.
2. Record the candidate ID, source reference, time, signal, and operator.
3. Invoke the target-specific kill-switch.
4. Return the selected component to its pre-activation state or legacy path.
5. Verify health, error rate, latency, retry rate, lineage, idempotency, and absence of persistence mutation.
6. Preserve evidence and mark the rollout as aborted or rolled back.
7. Reopen the decision for independent review before any reactivation.

## Unknown Target-Specific Inputs

The following are not present in repository metadata and must be supplied before R5-B/R5-D:

- Target and environment.
- Component activation mechanism.
- Kill-switch command or endpoint.
- Rollback command or deployment reference.
- Recovery owner and escalation path.
- Recovery verification queries and thresholds.
- Maximum rollback time objective.

No command or endpoint is invented here. Executing an assumed rollback would be:

`BLOCKED — SEPARATE AUTHORIZATION REQUIRED`

## Recovery Verification

Recovery is not complete until target-specific health and safety checks pass, no forbidden side effect is observed, and the operator records the final evidence. If any check is unavailable, the result is `REQUIRES_REVIEW`, not success.
