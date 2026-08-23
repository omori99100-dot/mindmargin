# R5-A Isolation Remediation — Completion Report

## Final Status

# R5-A = REQUIRES_REVIEW

The authorized staging isolation remediation was applied only to the allow-listed staging deployment surface. The result is a static/configuration isolation improvement with verified fail-closed guards, but Docker-dependent isolation was not executed because Docker is unavailable in the sandbox. Therefore R5-A cannot be promoted to PASS.

## Reference

- Candidate: `r4-rc-e1990e48a2c9109f714d`
- Immutable candidate: unchanged
- Production Rollout: `NOT_GRANTED / NOT_STARTED`
- R5-B/C/D: `NOT_AUTHORIZED`

## Files Changed

### Production/deployment allow-list

- `deploy/docker/docker-compose.staging.yml`
- `deploy/deploy.sh`

### Test allow-list

- `tests/integration/test_r5_staging_isolation.py`

### Documentation artifacts

- `docs/R5/R5_A_STAGING_ISOLATION_PRE_IMPLEMENTATION_AUDIT.md`
- `docs/R5/R5_A_ISOLATION_REMEDIATION_COMPLETION_REPORT.md`

Existing R5 design/test/rollback documents were used as design references. No production Compose, Dockerfile, application code, contract, persistence, candidate, or protected baseline file was modified.

## Before / After

| Boundary | Before | After |
|---|---|---|
| Staging data | `../../data:/app/data` shared with production topology | `${MINDMARGIN_STAGING_ROOT}/data:/app/data` required |
| Staging output | `../../output:/app/output` shared with production topology | `${MINDMARGIN_STAGING_ROOT}/output:/app/output` required |
| Redis volume | logical `redis_data` | explicit `mindmargin_staging_redis_data` |
| Ollama volume | logical `ollama_data` | explicit `mindmargin_staging_ollama_data` |
| Network | implicit/default | explicit `mindmargin_staging_internal`, `internal: true` |
| API host port | `8000:8000`, colliding with production | no host port; internal service DNS only |
| Redis host port | `6379:6379` exposed | no host port; internal service DNS only |
| Ollama host port | `11434:11434` exposed | no host port; internal service DNS only |
| Compose project | implicit | `mindmargin-staging` via deploy guard |
| Deploy guard | no storage/path guard | fail-closed root overlap rejection |

## Deploy Safety Guard

`deploy.sh staging` now:

- uses `MINDMARGIN_STAGING_ROOT` or a deterministic non-production `.runtime/staging` root;
- rejects a root equal to, containing, or contained by the repository/production roots;
- creates only the isolated staging data/output directories after passing the guard;
- invokes staging Compose with project name `mindmargin-staging`;
- does not select production Compose.

The guard was tested with the repository root as an unsafe staging root. It failed closed with:

```text
Unsafe staging root overlaps protected root
```

and returned non-zero without starting Docker.

## Tests and Validation

### Static isolation tests

```text
python3 -m pytest -q tests/integration/test_r5_staging_isolation.py
6 passed, 0 failed
```

### Shell syntax

```text
bash -n deploy/deploy.sh
PASS
```

### Test compile

```text
python3 -m compileall -q tests/integration/test_r5_staging_isolation.py
PASS
```

### Compose validation

Docker was not available in the sandbox:

```text
compose_config=NOT_RUN_DOCKER_UNAVAILABLE
```

No Docker service or container was started. Compose rendered-config validation and Docker-dependent checks remain R5-B requirements.

## Isolation Proof Status

| Proof | Result |
|---|---|
| Static data path separation | PASS |
| Static output path separation | PASS |
| Explicit Redis volume separation | PASS |
| Explicit Ollama volume separation | PASS |
| Explicit internal staging network | PASS statically |
| Host port collision removed | PASS statically |
| Credential value boundary | PASS by scope; no credentials read or used |
| Deploy fail-closed guard | PASS |
| Docker rendered configuration | NOT VERIFIED — Docker unavailable |
| Container/network reachability | NOT VERIFIED — R5-B |
| Bind-mount write isolation | NOT VERIFIED — R5-B |
| Redis/Ollama runtime separation | NOT VERIFIED — R5-B |
| Production side-effect prevention at runtime | NOT VERIFIED — R5-B |

## Security and Protected Areas

- No production credentials, OAuth tokens, or traffic were used.
- No publish, scheduler, Workflow, or A/B activation occurred.
- No production service was started.
- No production persistence or output was touched.
- No candidate or candidate snapshot was modified.
- C1, C2-P0–P9, Phase A/B, legacy APIs, ExperimentResult, DecisionStore/EventLedger, JSONL/SQLite, Workflow/SQLite remediation, and `PiperSettings.model_path` were not modified.
- No Git staging, commit, reset, cleanup, normalization, move, copy, delete, rename, or history operation occurred.

## Required R5-B Verification

R5-B requires an explicitly authorized and proven non-production Docker boundary before service startup. It must verify rendered Compose configuration, service/container identity, network identity, volume identity, bind mounts, ports, environment, dependencies, healthchecks, and restart policies. It must prove staging cannot access production data, output, Redis, Ollama, network, credentials, or services.

If non-production boundary cannot be proven, the result must be:

`BLOCKED — NON-PRODUCTION BOUNDARY NOT PROVEN`

## Final Governance State

- **R5-A = REQUIRES_REVIEW**.
- **R5-A static isolation remediation = PASS**.
- **R5-A runtime isolation verification = NOT COMPLETE**.
- **R5-B = NOT AUTHORIZED**.
- **R5-C = NOT AUTHORIZED**.
- **R5-D = NOT AUTHORIZED**.
- **Production Authorization = GRANTED for candidate only**.
- **Production Rollout = NOT_GRANTED / NOT_STARTED**.
- **C1 = OFFICIALLY CLOSED / FROZEN**.
- **C2-P0–P9 = PASS / PRESERVED**.
- **R1.2 = CLOSED**.
- **R2 = PASS — CONTROLLED INTEGRATION READINESS ONLY**.
- **PiperSettings.model_path = ACCEPTED-RISK / DEFERRED-REMEDIATION**.
- **Knowledge / Strategy / P10 = NOT AUTHORIZED**.
- **Execution = STOPPED**.

The runtime proof gap is not fixed by the static pass. No R5-B or rollout work was started.
