# CTO Assessment and Incremental Design

## Executive assessment

The repository is not a simple video generator. It contains a production-oriented pipeline, persistent JSON checkpoints, a SQLite-based analytics memory, YouTube integration, A/B testing, channel intelligence, scheduling, recovery, an API, and a substantial test suite. The central architectural issue is not lack of functionality; it is that these capabilities evolved as adjacent subsystems rather than as one explicit decision-and-learning loop.

The current system therefore automates execution more reliably than it improves decisions. It can research, script, voice, edit, publish, collect metrics, classify performance, and store practices. However, the lineage from idea to diagnosis to strategy update is implicit, score semantics are spread across modules, and several recovery and persistence guarantees are weaker than their production terminology suggests.

## Evidence baseline

The archive contains 2311 files, including 178 application Python modules, 80 project tests, a FastAPI surface, Docker deployment definitions, and a large generated-output and agent-skills tree. The declared dependencies include FastAPI, Celery/Redis, SQLAlchemy, Google YouTube clients, and Pillow. The baseline suite collected 1501 tests after environment dependencies were installed; 1535 tests passed and 9 failed. The first collection failure was an undeclared `python-multipart` dependency, which is itself a packaging defect because an imported API route requires it at import time.

The nine failures cluster into four architectural defects: a missing compatibility seam in selection, scheduler recovery that pauses valid persisted schedules when handlers are not re-registered, Redis health reporting that treats an unavailable optional service as healthy, and a growth-analysis persistence path that is not safe under the test database contract. A background workflow thread also emitted a `FileNotFoundError` after its temporary directory was removed, exposing a lifecycle race.

## Current architecture map

| Layer | Current modules | Assessment |
|---|---|---|
| Core runtime | `mindmargin/core/pipeline.py`, `state.py`, `recovery.py`, `scheduler.py`, `workflows.py`, `queue.py` | Strong foundation, but state transitions are assignable strings and persistence is file-level rather than transactional. |
| Domain/content | `channel`, `content`, `business` | Broad model coverage, but several concepts overlap with analytics and executive modules. |
| Production | `agents/research.py`, `script.py`, `voice.py`, `editing.py`, `thumbnail.py`, `metadata.py` | Clear sequential pipeline and checkpointing; background thumbnail generation introduces an unjoined lifecycle. |
| Analytics | `analytics/memory.py`, `feedback.py`, `patterns.py`, `selection.py`, `ab_testing.py` | Valuable operational memory, but schema creation/migration is runtime-side-effect driven and data lineage is incomplete. |
| Intelligence | `intelligence/*`, `youtube_intelligence/*`, `executive/*` | The desired strategic capability largely exists in fragments; no single canonical decision/diagnosis contract connects them. |
| Integrations | `integrations/*`, `github/*`, YouTube connector | Useful provider abstraction and integrations; availability and idempotency policies need centralization. |
| API/operations | `api/*`, `operations/*`, `jobs/*` | Rich control plane; route import can fail when optional API dependencies are absent. |
| Storage | JSON output/checkpoints plus SQLite analytics memory | Simple and portable, but no append-only event ledger or atomic transition record is present. |

## Dependency-direction findings

The principal dependency smell is upward leakage into shared memory and configuration. Production and intelligence modules import `analytics.memory` directly, while API routes and jobs also invoke intelligence and storage functions directly. This makes the memory module both repository and integration seam. The result is duplicated persistence access, difficult test substitution, and implicit coupling between analytics schema details and decision logic.

The preferred direction is: domain contracts and pure decision functions at the center; application services orchestrate them; storage and external integrations implement ports at the edge. The migration should be incremental: retain existing functions as compatibility adapters while introducing canonical records and append-only events.

## Keep / Refactor / Replace / Remove / Missing

| Decision | Components | Rationale |
|---|---|---|
| Keep | Pipeline stages, checkpoint files, `PipelineState`, provider manager, YouTube connector, analytics memory, A/B lifecycle, existing tests | These are valuable foundations and already encode real behavior. |
| Refactor | Direct calls into `analytics.memory`, mutable state setter, runtime schema migration, scheduler recovery, health checks, background thumbnail thread | They work in common paths but lack explicit contracts and failure semantics. |
| Replace gradually | Implicit “best practice” learning as the sole strategy interface with decision records plus diagnosis/hypothesis records | Averages and text rows are insufficient to evaluate decision quality or causal experiments. |
| Remove from distributable source | Credentials, token pickles, auth URL artifacts, generated output, caches, bytecode, logs, and test audio | These are runtime artifacts or secrets, not application source. Preserve outside the source tree if needed. |
| Missing | Append-only pipeline events, canonical content lineage, diagnosis contract, hypothesis-to-experiment linkage, atomic idempotency key for publishing, transition validation, declared multipart dependency, migration versioning | These are required for traceability, recovery, and learning-loop integrity. |

## Target architecture

```text
Research -> Opportunity Scoring -> Decision Record -> Story/Production Plan
    -> Production State Machine -> QC -> Idempotent Publish
    -> Metric Snapshots -> Diagnosis -> Hypothesis/Experiment
    -> Result -> Reusable Knowledge -> Strategy Update -> Next Decision
```

The first implementation slice should establish the contracts without rewriting the pipeline:

1. Add a canonical `DecisionRecord` and `PipelineEvent` model with JSON serialization.
2. Add a `DiagnosisRecord` model that records problem, evidence, likely cause, confidence, recommended action, expected effect, and actual result.
3. Add a small event/decision ledger under the existing output root, using atomic replacement and file locking where practical.
4. Add explicit transition validation and transition metadata to `PipelineState`, while preserving the existing state constants and public methods.
5. Add a publish idempotency guard keyed by pipeline ID and video fingerprint before the YouTube upload call.
6. Make scheduler recovery distinguish “persisted schedule is valid” from “this process has a handler bound”; do not silently mutate an active schedule to paused merely because a handler must be reattached.
7. Make optional-service health checks fail closed, and declare all import-time dependencies.

## Migration path

| Phase | Change | Main risk | Mitigation |
|---|---|---|---|
| A | Compatibility seams, dependency declaration, health/recovery fixes, tests | Behavioral drift in legacy tests | Preserve signatures and add regression tests first. |
| B | Event and decision records emitted alongside existing memory writes | Dual-write divergence | Treat event ledger as additive and include correlation IDs. |
| C | Diagnosis and experiment result records drive strategy recommendations | False causal inference | Enforce minimum sample and confidence gates; retain human approval for publish strategy changes. |
| D | Move reporting and future decisions to application services over the ledger | Incomplete historical data | Keep legacy reads as fallback until backfill and parity checks complete. |

## Implementation scope selected now

The current change set will be deliberately incremental. It will fix the nine baseline defects where they are local and safe, add canonical intelligence records and a small append-only ledger, add state-transition validation and idempotent publishing protection, harden optional dependency and repository hygiene, and add focused tests. It will not rewrite the agents, replace SQLite, or introduce new autonomous agents merely for appearance.

## Autonomy classification

| Capability | Classification | Guardrail |
|---|---|---|
| File naming, checksum calculation, retries, state validation | Deterministic | Pure functions and explicit tests. |
| Opportunity scoring and diagnosis suggestions | Assisted | Record rationale and confidence; require minimum evidence. |
| Strategy updates | Assisted / guarded autonomous | Apply only within configured bounds and preserve rollback history. |
| YouTube publishing | Human approval or guarded autonomous | Idempotency key, QC gate, credential check, and explicit publish policy. |

## Success criteria

The change is successful only if it preserves existing working behavior, makes important decisions and state transitions observable, closes the loop from metrics to diagnosis and reusable knowledge, and reduces failure ambiguity. Test count alone is not the success metric.
