# R5-A Staging Isolation Rollback Design

## Status

Design only. No Docker, production, persistence, candidate, or Git operation was performed.

## Future Rollback Principles

A future isolation implementation must be:

- non-destructive;
- reversible;
- independent of production data/output;
- independent of ledger deletion;
- independent of database reset;
- independent of Git reset or cleanup;
- evidence-preserving;
- bounded to the staging deployment scope.

## Required Future Sequence

1. Stop before activation if path, volume, network, port, credential, or health preconditions fail.
2. Freeze the staging attempt and record candidate, component, timestamp, and signal.
3. Use a target-specific kill-switch owned by the approved operator.
4. Return staging to its prior isolated state.
5. Verify that production data/output, Redis, Ollama, network, and credentials were not touched.
6. Verify health, lineage, idempotency, error, latency, timeout, and retry invariants.
7. Preserve logs/evidence and require review before reactivation.

## Unknowns That Block an Executable Rollback

The repository does not define a staging host/cluster, kill-switch command, operator endpoint, rollback command, recovery time objective, or target-specific health endpoint. No command is invented.

Any future implementation needing changes to Compose, deploy scripts, Dockerfiles, configuration, or production paths requires:

`BLOCKED — SEPARATE AUTHORIZATION REQUIRED`
