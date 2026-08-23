# R5-A Staging Isolation Remediation — Pre-Implementation Audit

## Status

`PRE-IMPLEMENTATION AUDIT = COMPLETE`  
`Authorization scope = R5-A staging isolation remediation only`

## Dependency Map

```text
deploy/deploy.sh
  ├── deploy/docker/docker-compose.staging.yml
  │     ├── api  → Redis / Ollama / bind mounts
  │     ├── worker → Redis / Ollama / bind mounts
  │     ├── redis → named volume
  │     └── ollama → named volume
  └── deploy/docker/docker-compose.prod.yml
        ├── api / worker → same relative data/output bind mounts
        ├── redis / ollama → same logical volume names
        └── nginx → production ingress

Dockerfiles
  ├── Dockerfile.api → /app/data, /app/output, port 8000, /health
  └── Dockerfile.worker → /app/data, /app/output, Redis healthcheck

mindmargin/config.py
  ├── storage defaults → repository output paths
  ├── REDIS_URL / OLLAMA_BASE_URL / ENVIRONMENT
  └── PiperSettings.model_path (protected; no change)
```

## Findings Against Design

1. Staging and production share `../../data` and `../../output` bind mounts.
2. Staging and production use the same API host port `8000` in their Compose definitions.
3. Staging exposes Redis `6379` and Ollama `11434` to the host.
4. Staging and production declare logical volume names `redis_data` and `ollama_data` without explicit global namespace ownership.
5. No explicit staging network or default production-network deny boundary exists.
6. `deploy/deploy.sh` selects Compose files but does not enforce a staging project name, staging root, or fail-closed path checks.
7. Dockerfiles create `/app/data` and `/app/output`, but Compose bind mounts determine the effective host persistence boundary.
8. No configuration change is necessary for the minimal isolation patch if Compose and deploy guardrails provide explicit safe storage/network values.

## Proposed Allow-list

### Production/deployment files allowed to modify

- `deploy/docker/docker-compose.staging.yml`
- `deploy/deploy.sh`

### Test files allowed to create

- `tests/integration/test_r5_staging_isolation.py`

### Documentation artifacts allowed to create/update

- `docs/R5/R5_A_STAGING_ISOLATION_PRE_IMPLEMENTATION_AUDIT.md`
- `docs/R5/R5_A_STAGING_ISOLATION_COMPLETION_REPORT.md`
- `docs/R5/R5_A_STAGING_ISOLATION_DESIGN.md`
- `docs/R5/R5_A_STAGING_ISOLATION_TEST_PLAN.md`
- `docs/R5/R5_A_STAGING_ISOLATION_ROLLBACK.md`

### Protected and excluded

No change is allowed to C1, C2-P0–P9, Phase A/B, legacy APIs, ExperimentResult, DecisionStore/EventLedger, JSONL/SQLite, Workflow/SQLite remediation, `mindmargin/config.py`, Dockerfiles, production Compose, candidate contents, Git history, or `PiperSettings.model_path`.

## Minimal Implementation Strategy

1. Give staging an explicit non-production root supplied through `MINDMARGIN_STAGING_ROOT`; direct Compose use fails if it is absent.
2. Make `deploy.sh staging` choose a deterministic repository-local `.runtime/staging` fallback only when no user value is supplied, and reject paths equal to or containing production data/output roots.
3. Use separate bind paths under the staging root for `data` and `output`.
4. Use explicit globally named staging Redis/Ollama volumes and an explicit internal staging network.
5. Remove host exposure for staging Redis and Ollama; keep service-to-service DNS only.
6. Remove the staging API host-port collision; expose API only on the internal network unless a future separate authorization supplies a host port.
7. Add fail-closed guards and static tests; do not start services in R5-A unless Docker non-production boundary is independently proven.

## Stop Conditions

Stop with `BLOCKED — SEPARATE AUTHORIZATION REQUIRED` if the patch requires modifying production Compose, Dockerfiles, config contracts, persistence architecture, protected areas, Git, candidate contents, credentials, or production services.
