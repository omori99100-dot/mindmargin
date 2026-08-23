# R5-A Staging Isolation Design

## Status

`R5-A = REQUIRES_REVIEW`  
`Production Rollout = NOT_GRANTED / NOT_STARTED`  
`R5-B = NOT_AUTHORIZED`

## 1. Architecture Inspection Findings

The repository defines staging and production Docker Compose topologies with API, Worker, Redis, and Ollama. Production additionally defines Nginx. API and Worker are built from the same Dockerfiles and share the repository build context.

### Runtime and startup

- `Dockerfile.api` runs as non-root user `mindmargin`, exposes port `8000`, and has an HTTP healthcheck at `/health`.
- `Dockerfile.worker` runs as non-root user `mindmargin`, has a Redis ping healthcheck, and starts `python -m mindmargin.main --run-daily-job`.
- Staging API/Worker depend on healthy Redis and started Ollama.
- Staging uses `unless-stopped`; production uses `always`.
- `deploy/deploy.sh` selects staging or production only by Compose file; no repository-level path/network guardrail is defined there.

## 2. Isolation Map

### Staging

```text
STAGING
├── API                 host port 8000
├── Worker
├── Redis               host port 6379, redis_data
├── Ollama              host port 11434, ollama_data
├── data                ../../data:/app/data
└── output              ../../output:/app/output
```

### Production

```text
PRODUCTION
├── API                 host port 8000
├── Worker
├── Redis               redis_data
├── Ollama              ollama_data
├── Nginx               host ports 80/443
├── data                ../../data:/app/data
└── output              ../../output:/app/output
```

## 3. Confirmed and Potential Overlaps

| Boundary | Finding | Risk |
|---|---|---|
| `data` bind mount | staging and production both use `../../data` | staging can write/read production data if co-located |
| `output` bind mount | staging and production both use `../../output` | staging can write/read production output |
| Redis volume | both declare `redis_data`; project-name namespacing is not guaranteed by repository metadata | possible shared Redis persistence |
| Ollama volume | both declare `ollama_data`; project-name namespacing is not guaranteed | possible shared model/cache volume |
| API port | staging and production both publish `8000:8000` | host port collision or wrong service reachability |
| Redis port | staging publishes `6379:6379`; production does not publish Redis | host exposure and ambiguous access boundary |
| Ollama port | staging publishes `11434:11434`; production does not publish Ollama | host exposure and ambiguous access boundary |
| Networks | no explicit network definitions or ingress policy | default network/access is not an isolation proof |
| Deployment launcher | staging/prod selected by compose file only | no path/volume/network safety guard |
| Build context | both build from repository root | candidate/source provenance must be pinned later |
| Config | development compose adds `../../config`; staging does not | environment-specific configuration boundary is incomplete |

## 4. Recommended Isolation Architecture

The recommended future architecture is a non-production staging topology with:

1. Dedicated staging data path outside production data.
2. Dedicated staging output path outside production output.
3. Explicitly namespaced Redis volume owned only by the staging Compose project.
4. Explicitly namespaced Ollama volume owned only by staging.
5. Explicit staging network with no production network attachment.
6. Staging-only host ports or private network-only exposure; exact ports require explicit decision.
7. Production network inaccessible by default.
8. No production credentials in staging.
9. Explicit `ENVIRONMENT=staging` and separate configuration boundary.
10. Candidate/source pinning and an operator-controlled kill-switch.

No host, cluster, port numbers, paths, or commands are invented here. Each unresolved field is `REQUIRES EXPLICIT DECISION`.

## 5. Required Future Changes (Not Performed)

A real implementation would likely require changes to:

| Area | Why it would be required |
|---|---|
| `deploy/docker/docker-compose.staging.yml` | separate bind paths, volume names, network, and ports |
| `deploy/deploy.sh` | enforce staging project name/path and prevent accidental production overlap |
| possibly `mindmargin/config.py` | make storage/config boundaries explicit if Compose mounts alone are insufficient |
| staging environment metadata | define non-secret environment and ownership |
| tests/fixtures | prove path/volume/network/credential isolation |

These are design dependencies only. They are not authorized for modification in R5-A and remain:

`BLOCKED — SEPARATE AUTHORIZATION REQUIRED`

## 6. Production Side-Effect Boundary

Until the above isolation is implemented and proven, staging must not be started. No Docker service, API, Worker, Redis, Ollama, publish, scheduler, Workflow, A/B, production traffic, credential, or persistence operation is allowed in this phase.
