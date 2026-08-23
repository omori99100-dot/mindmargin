# R5-A Abort Matrix

**Status:** `REQUIRES_REVIEW`  
**Candidate:** `r4-rc-e1990e48a2c9109f714d`  
**Rollout:** `NOT_GRANTED`

## Preconditions Before Thresholds Can Be Activated

Numeric thresholds cannot be finalized until target, environment, component, baseline window, and traffic limit are explicitly supplied. The entries below are required fields, not invented runtime values.

| Signal | Required numeric threshold | Current state | Action |
|---|---|---|---|
| Error rate | target-specific percentage over observation window | `UNKNOWN / REQUIRES EXPLICIT INPUT` | Do not activate |
| P95/P99 latency | target-specific milliseconds | `UNKNOWN / REQUIRES EXPLICIT INPUT` | Do not activate |
| Timeout rate | target-specific percentage/count | `UNKNOWN / REQUIRES EXPLICIT INPUT` | Do not activate |
| Retry rate | target-specific percentage/count | `UNKNOWN / REQUIRES EXPLICIT INPUT` | Do not activate |
| Duplicate/lost state | exact invariant threshold | `UNKNOWN / REQUIRES EXPLICIT INPUT` | Any observed violation aborts |
| Lineage completeness | required percentage/count | `UNKNOWN / REQUIRES EXPLICIT INPUT` | Any unexplained gap aborts |
| Security/redaction violation | zero tolerance | `0 allowed` | Immediate abort |
| Protected-area mutation | zero tolerance | `0 allowed` | Immediate abort and stop |
| Unexpected production side effect | zero tolerance | `0 allowed` | Kill-switch and rollback |

## Mandatory Abort Conditions

The rollout must not start, or must stop immediately, if candidate identity/hash/source mismatch, credentials are requested unexpectedly, a forbidden component activates, production persistence is touched, false success occurs, duplicate/lost state appears, lineage is incomplete, or rollback cannot be verified.

## Kill-Switch Requirement

A target-specific kill-switch owner, mechanism, invocation path, and verification step are still unknown. No activation is permitted until these are supplied explicitly.

## Current Decision

`R5-A = REQUIRES_REVIEW` because target-specific numeric thresholds and kill-switch details are unavailable. This matrix does not authorize Production Rollout.
