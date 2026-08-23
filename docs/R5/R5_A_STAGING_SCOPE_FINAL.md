# R5-A Staging Scope Finalization

**Status:** `REQUIRES_REVIEW`  
**Candidate:** `r4-rc-e1990e48a2c9109f714d`  
**Production Rollout:** `NOT_GRANTED`

## Final Staging Architecture

The repository defines a staging Docker topology consisting of `api`, `worker`, `redis`, and `ollama`.

- `api` depends on healthy Redis and started Ollama.
- `worker` depends on healthy Redis and started Ollama.
- API and worker use `ENVIRONMENT=staging`, `DEBUG=false`, and `LOG_LEVEL=INFO`.
- API listens on host port `8000`.
- Redis publishes host port `6379`.
- Ollama publishes host port `11434`.
- Services use `unless-stopped` restart behavior.
- No explicit custom network isolation is defined in the staging compose file; Docker Compose default network behavior remains a deployment concern.

This is a topology definition only. No service was started.

## Persistence Isolation Analysis

The staging compose file mounts:

- `../../data:/app/data` for API and worker.
- `../../output:/app/output` for API and worker.
- named `redis_data` volume for Redis.
- named `ollama_data` volume for Ollama.

The production compose file also mounts `../../data:/app/data` and `../../output:/app/output`. This creates a **potential shared-host-path collision** between staging and production if both are run from the same repository checkout or host.

The named Redis/Ollama volume names are not independently namespaced in the checked metadata. Their effective isolation depends on the Compose project name and deployment host, which are not defined by the repository.

### Result

`PERSISTENCE ISOLATION = BLOCKER / REQUIRES EXPLICIT DECISION`

No automatic fix was applied. No database, JSONL, output, Redis, or Ollama data was touched.

## Network Isolation Analysis

The staging configuration publishes ports `8000`, `6379`, and `11434` to the host. No explicit network boundary, ingress allow-list, host firewall policy, or staging-only endpoint restriction is defined in the repository.

### Result

`NETWORK ISOLATION = REQUIRES EXPLICIT DECISION`

The topology cannot be treated as safely isolated until host/network ownership and access boundaries are supplied.

## Scope Fields

| Field | Status |
|---|---|
| Staging topology | Defined as API/Worker/Redis/Ollama |
| Host/cluster | `REQUIRES EXPLICIT DECISION` |
| Environment boundary | `REQUIRES EXPLICIT DECISION` |
| Component activation | No activation authorized; exact test component `REQUIRES EXPLICIT DECISION` |
| Persistence policy | Blocked by shared `data`/`output` host paths |
| Network policy | Blocked/pending host ports and network boundary |
| Test volume | `TEST VOLUME = REQUIRES EXPLICIT DECISION` |
| Duration | `DURATION = REQUIRES EXPLICIT DECISION` |
| Owners | Target-specific operational/monitoring/abort/rollback owners unknown |
| Thresholds | `THRESHOLD = REQUIRES BASELINE` |
| Credentials | None permitted in R5-A |
| Production side effects | Zero; no traffic/publish/scheduler/Workflow/A-B |

## Decision

R5-A cannot become PASS from repository metadata alone. The recommended topology remains staging Docker, but execution requires explicit decisions for host/environment/network/persistence isolation, test volume, duration, owners, and baseline thresholds.
