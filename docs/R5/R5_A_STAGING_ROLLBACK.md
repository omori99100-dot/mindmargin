# R5-A Staging Rollback and Recovery

**Status:** `REQUIRES_REVIEW`  
**Production Rollout:** `NOT_GRANTED`

## Rollback Requirements

Any future staging operation must be reversible and non-destructive. It must not delete ledger/history, reset SQLite, use Git reset, remove historical evidence, mutate the immutable candidate, or create duplicate execution.

## Required Sequence

1. Freeze any test or activation immediately on an abort signal.
2. Record candidate ID, component, timestamp, signal, and operator.
3. Invoke a target-specific kill-switch.
4. Restore the staging component or return to its pre-check state.
5. Verify service health and target-specific error/latency/timeout/retry thresholds.
6. Verify no shared `data`/`output` or Redis/Ollama persistence collision.
7. Verify lineage and idempotency invariants.
8. Preserve all evidence and require independent review before reactivation.

## Unknowns

The repository does not define a safe kill-switch command, host/cluster rollback mechanism, recovery owner, recovery time objective, or target-specific verification endpoint. No command is invented.

## Blocking Conditions

Rollback is not considered executable until persistence isolation and network boundaries are explicitly resolved and the target-specific owner and procedure are supplied.
