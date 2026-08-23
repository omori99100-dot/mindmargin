# R5-A Staging Isolation Design — Completion Report

## Final Status

# R5-A STAGING ISOLATION DESIGN = REQUIRES_REVIEW

## Scope Completed

The authorized read-only architecture inspection covered Compose files, Dockerfiles, deploy launcher, bind mounts, named volumes, networks, ports, environment variables, Redis/Ollama wiring, API/Worker persistence, startup dependencies, healthchecks, and restart policies.

No Docker service was started. No API, Worker, Redis, or Ollama was run. No production credentials, OAuth, traffic, publish, scheduler, Workflow, A/B, persistence mutation, candidate mutation, Git operation, or protected-area modification occurred.

## Confirmed Overlaps

1. Staging and production API/Worker both bind `../../data:/app/data`.
2. Staging and production API/Worker both bind `../../output:/app/output`.
3. Both Compose files declare `redis_data`; repository metadata does not prove project/volume namespace separation.
4. Both Compose files declare `ollama_data`; repository metadata does not prove project/volume namespace separation.
5. Staging and production both publish API host port `8000`.
6. Staging publishes Redis `6379` and Ollama `11434` directly to the host.
7. No explicit Compose network isolation or production-network deny boundary is defined.
8. `deploy/deploy.sh` selects Compose files but does not enforce path/volume/network isolation.
9. Both API/Worker images build from the repository root, requiring future candidate/source pinning at deployment time.
10. Dockerfiles create `/app/data` and `/app/output` and run as non-root `mindmargin`, but the bind mounts override the effective persistence boundary.

## Recommended Architecture

Use a separate non-production staging topology with:

- dedicated staging data path;
- dedicated staging output path;
- explicitly namespaced Redis volume;
- explicitly namespaced Ollama volume;
- explicit staging network;
- staging-only ports or private network-only access;
- production network inaccessible by default;
- no production credentials;
- explicit staging configuration and ownership;
- immutable candidate/source pinning;
- operator-controlled kill-switch.

No host, cluster, port, path, command, or numeric threshold was invented.

## Required Future Changes — Not Performed

The real remediation would likely require:

- `deploy/docker/docker-compose.staging.yml` for paths, namespaced volumes, networks, and ports;
- `deploy/deploy.sh` for project/path safety guards;
- possibly `mindmargin/config.py` for explicit storage/config boundaries;
- static and Docker-dependent isolation tests/fixtures.

These changes are outside this design-only authorization and are:

`BLOCKED — SEPARATE AUTHORIZATION REQUIRED`

## Future Proof Strategy

R5-A defines static validation. R5-B must perform Docker-dependent checks for path, volume, Redis, Ollama, network, port, environment, credential, persistence, and production-side-effect boundaries. Numeric thresholds remain:

`THRESHOLD = REQUIRES BASELINE`

## Rollback Design

Future rollback must be non-destructive, reversible, evidence-preserving, and independent of database reset, ledger deletion, Git reset, or cleanup. The repository does not define a target-specific kill-switch or rollback command; no command was invented.

## Definition of Done Assessment

| Criterion | Result |
|---|---|
| All overlap points mapped | PASS |
| Isolation architecture designed | PASS |
| Data/output separation specified | PASS — implementation pending |
| Redis/Ollama separation specified | PASS — implementation pending |
| Network/port boundary specified | PASS — implementation pending |
| Credential/persistence boundary specified | PASS — proof pending |
| Proof strategy defined | PASS |
| Future test strategy defined | PASS |
| R5-B requirements identified | PASS |
| Runtime/production side effects absent | PASS |
| Actual isolation implemented and proven | NOT IN SCOPE |

Because implementation/proof is not authorized and persistence/network details remain undecided, the final status remains `REQUIRES_REVIEW`.

## Governance State

- **R5-A = REQUIRES_REVIEW**.
- **R5-A Isolation Design = REQUIRES_REVIEW**.
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

Any implementation change to Docker topology, deploy scripts, configuration, persistence, or production paths requires:

`BLOCKED — SEPARATE AUTHORIZATION REQUIRED`
