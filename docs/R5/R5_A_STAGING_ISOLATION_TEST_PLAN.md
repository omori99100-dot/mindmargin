# R5-A Staging Isolation Test Plan

## Status

Design only. No services are started and no Docker-dependent test is executed. Docker execution is an R5-B requirement.

## Test Matrix

| Area | Future proof | R5-A status | R5-B dependency |
|---|---|---:|---:|
| Path separation | staging data/output resolve outside production paths | design defined | required |
| Bind-mount separation | inspect rendered Compose mounts and assert disjointness | static design only | required |
| Redis separation | distinct project/volume identity and isolated keyspace | design defined | required |
| Ollama separation | distinct volume identity and model/cache boundary | design defined | required |
| Network isolation | inspect networks and attempt forbidden production reachability | not runnable here | required |
| Port isolation | assert no host-port collision and expected access scope | not resolved | required |
| Environment separation | staging environment markers and no production configuration | partial static proof | required |
| Credential boundary | no credentials in files/logs/env; no production credential injection | static negative checks | required |
| Persistence boundary | staging write/read cannot reach production data/output/SQLite/JSONL | not proven | required |
| Production-side-effect prevention | forbidden publish/scheduler/workflow/A-B/traffic calls absent | static/negative checks | required |
| Candidate provenance | image/build source resolves to immutable candidate | candidate evidence exists | required |
| Health/dependency behavior | Redis health and Ollama startup dependency are bounded | compose-defined only | required |
| Restart behavior | restart policy does not auto-expand scope or bypass kill-switch | compose-defined only | required |

## Static Tests Allowed in R5-A

Only read-only/static checks are appropriate in R5-A:

- parse Compose/Docker metadata without starting Docker;
- enumerate bind mounts, named volumes, ports, networks, environment names, dependencies, healthchecks, and restart policies;
- assert the proposed isolation fields are documented;
- assert no real credentials or OAuth values are present in candidate/design artifacts;
- assert candidate identity and source reference are unchanged;
- assert R5-B is required for every Docker-dependent proof.

## Docker-dependent Tests — R5-B Only

The following must not run in R5-A:

- `docker compose up`, `down`, `run`, or `exec`;
- container startup or health checks;
- network reachability tests;
- bind-mount write attempts;
- Redis/Ollama volume tests;
- API/Worker execution;
- production-side-effect probes involving live services.

## Thresholds

No numeric baseline exists in repository metadata. Therefore:

`THRESHOLD = REQUIRES BASELINE`

Future R5-B measurements must define error rate, latency, timeout, retry, duplicate/lost state, lineage, resource exhaustion, and health-failure baselines before applying abort thresholds.

## Pass Criteria for Future R5-A Design

- every overlap is mapped;
- target isolation architecture is explicit;
- required implementation files are identified;
- proof strategy is testable;
- Docker execution is explicitly deferred to R5-B;
- no services, credentials, traffic, persistence, or protected areas are touched.
