# MindMargin System Execution Order

## 1. Service Startup Sequence

Startup tiers — each tier waits for all previous tiers to be healthy before proceeding.

```
TIER 0: Infrastructure (no dependencies)
├── Redis           — message broker, cache, Celery backend
├── PostgreSQL      — persistent storage (videos, scripts, analytics, logs)
└── Nginx           — reverse proxy (production only)

TIER 1: AI Backends (depends on Tier 0)
├── Ollama          — LLM inference (requires PostgreSQL for config, Redis for queue)
├── ComfyUI         — image generation (SDXL, standalone, no infra deps)
└── Piper TTS       — voice synthesis (standalone binary, no infra deps)

TIER 2: Application (depends on Tier 0 + Tier 1)
├── API             — FastAPI server (requires Redis, PostgreSQL, Ollama)
└── Worker          — Celery worker (requires Redis, PostgreSQL, Ollama, optional: ComfyUI, Piper)

TIER 3: Observability (depends on Tier 0)
├── Flower          — Celery task monitoring (requires Redis)
└── n8n             — alternative workflow engine (optional, non-engine workflows)
```

### Startup Command Sequence

```bash
# Tier 0 — start infrastructure first
docker compose up -d redis postgres

# Wait for health checks
docker compose exec redis redis-cli ping       # expect PONG
docker compose exec postgres pg_isready -U mindmargin  # expect accepting connections

# Tier 1 — start AI backends
docker compose up -d ollama

# Pull model (one-time, ~40GB)
docker compose exec ollama ollama pull llama3:70b

# Start optional services
docker compose up -d comfyui      # needs ~12GB VRAM
# Piper runs natively, not in Docker (needs CPU .onnx model)

# Tier 2 — start application
docker compose up -d api worker

# Tier 3 — start monitoring
docker compose up -d flower n8n
```

### Local (Non-Docker) Startup

```powershell
# Terminal 1: Redis (if not running)
redis-server

# Terminal 2: PostgreSQL (if not running)
pg_ctl -D data start

# Terminal 3: Ollama
ollama serve

# Terminal 4: API
python -m mindmargin.main --api

# Terminal 5: Worker
celery -A mindmargin.workers.celery_app worker --loglevel=info --concurrency=1

# Terminal 6: ComfyUI (optional, for image gen)
python comfyui/main.py --listen 0.0.0.0
```

---

## 2. Agent Dependency Graph

### Full Pipeline — Linear Chain

```
TREND ──► RESEARCH ──► HOOK ──► SEO ──► SCRIPT ──► VISUAL ──► THUMBNAIL ──► VOICE ──► EDITING ──► UPLOAD ──► ANALYTICS ──► LEARNING
 │          │            │       │        │          │            │          │         │          │           │            │
 │          │            │       │        │          │            │          │         │          │           │            │
 │ Reads:   │ Reads:     │ Reads:│ Reads: │ Reads:   │ Reads:    │ Reads:   │ Reads:  │ Reads:   │ Reads:    │ Reads:     │ Reads:
 │ topic    │ topic      │ topic │ topic  │ research │ script    │ seo      │ script  │ visual   │ seo       │ analytics  │ analytics
 │          │ trend_data │ hooks │ hooks  │          │           │          │ seo     │ voice    │ upload    │            │
 │          │            │       │        │          │           │          │         │          │           │            │
 │ Writes:  │ Writes:    │ Writes:│ Writes:│ Writes: │ Writes:  │ Writes:  │ Writes: │ Writes:  │ Writes:   │ Writes:    │ Writes:
 │ trend    │ research   │ hooks  │ seo    │ script  │ visual   │ thumb-   │ voice   │ edit     │ upload    │ analytics  │ learning
 │ _analysis│ _data      │        │ _data  │ _data   │ _directions│nail_data│ _data   │ _plan    │ _data     │ _data      │ _data
```

### Dependency Table

| Agent | Depends On | Provides To | Blackboard Key (Reads) | Blackboard Key (Writes) | Parallelizable |
|-------|-----------|-------------|----------------------|------------------------|----------------|
| **trend** | — | research | `topic` | `trend_analysis` | Yes (first) |
| **research** | trend | hook, seo, script | `topic`, `trend_analysis` | `research_data` | No |
| **hook** | research | seo | `topic`, `research_data` | `hooks` | No |
| **seo** | hook | thumbnail, upload | `topic`, `hooks` | `seo_data` | No |
| **script** | research | visual, voice | `topic`, `research_data` | `script_data` | No |
| **visual** | script | editing | `topic`, `script_data` | `visual_directions` | With thumbnail |
| **thumbnail** | seo | upload | `topic`, `seo_data` | `thumbnail_data` | With visual |
| **voice** | script | editing | `topic`, `script_data` | `voice_data` | No |
| **editing** | visual, voice | upload | `topic`, `visual_directions`, `voice_data` | `edit_plan` | No |
| **upload** | editing, seo, thumbnail | analytics | `topic`, `seo_data`, `edit_plan`, `thumbnail_data` | `upload_data` | No |
| **analytics** | upload | learning | `topic` | `analytics_data` | No |
| **learning** | analytics | — | `topic`, `analytics_data` | `learning_data` | No |

### Parallel Execution Opportunities

```
SEQUENTIAL (must wait):
  trend → research → hook → seo → script → voice → editing → upload → analytics → learning
  trend → research → script → visual
  trend → research → script → voice

PARALLEL (can run simultaneously):
  visual  ──┐
             ├──► editing (waits for both)
  voice   ──┘

  seo  ──┐
          ├──► upload (waits for both)
  thumbnail ──┘

  upload ──► analytics ──► learning (linear sub-pipeline)

MAX CONCURRENCY: 3 agents at once
  Batch 1: trend (only active agent)
  Batch 2: research (only active agent)
  Batch 3: hook (only active agent)
  Batch 4: seo (only active agent)
  Batch 5: script (only active agent)
  Batch 6: visual + voice (parallel)
  Batch 7: thumbnail (depends on seo, done by now)
  Batch 8: editing (waits for visual + voice)
  Batch 9: upload
  Batch 10: analytics
  Batch 11: learning
```

---

## 3. Core Workflows

### Workflow A: Full Production Pipeline (primary)
```
Purpose: End-to-end video creation and publication
Trigger: CLI --topic "Enron" --publish true
Duration: ~80 min on single RTX 4090
Steps:   trend → research → hook → seo → script → visual → thumbnail → voice → editing → upload
Output:  Published YouTube video + analytics tracking
```

### Workflow B: Draft Pipeline (testing/preview)
```
Purpose: Generate script + visuals without publication
Trigger: CLI --topic "Enron"
Duration: ~45 min
Steps:   trend → research → hook → seo → script → visual → voice
Output:  Script file, audio files, visual direction JSON — no video assembly
```

### Workflow C: Script-Only Pipeline
```
Purpose: Fast content validation — get a script in <5 min
Trigger: python -c "from mindmargin.agents.script import ScriptAgent; ..."
Duration: ~2 min (no LLM calls with mock data)
Steps:   research → script
Output:  9-section script with word count
```

### Workflow D: Republish Pipeline (rerun)
```
Purpose: Rerun SEO + thumbnail for an existing video
Trigger: API POST /api/v1/pipeline/republish
Duration: ~5 min
Steps:   seo → thumbnail → upload (update metadata only)
Output:  Updated title, description, tags, thumbnail
```

### Workflow E: Analytics Review
```
Purpose: Daily analytics check + learning loop
Trigger: Celery beat schedule (daily)
Duration: ~30s per video
Steps:   analytics → learning
Output:  Performance report + optimization recommendations
```

### Workflow F: Multi-Video Batch
```
Purpose: Produce 3 videos in one overnight batch
Trigger: Manual script or scheduler
Duration: ~4 hours (3 × 80 min, staggered)
Steps:   For each topic, run Workflow A sequentially
         GPU scheduling: Ollama (CPU), ComfyUI (GPU), Piper (CPU) interleaved
Strategy:
  18:00 — Pipeline 1 starts (trend → research → hook → seo → script)
  19:20 — Pipeline 1 visual gen (ComfyUI) + Pipeline 2 starts trend → research
  20:40 — Pipeline 1 editing + Pipeline 2 visual + Pipeline 3 trend
  22:00 — All 3 complete, upload scheduled
```

### Workflow G: Shorts Pipeline
```
Purpose: Extract 8 Shorts from 1 long-form video
Trigger: Post-upload, within 24h of long-form publish
Duration: ~10 min per Short
Steps:   editing (extract clips) → voice (regenerate short segments) → thumbnail (vertical) → upload
Output:  8 YouTube Shorts (≤60s each)
```

---

## 4. Optional vs Required Modules

### REQUIRED (MVP cannot function without)

| Module | Reason | Fallback if missing |
|--------|--------|--------------------|
| `mindmargin/core/config.py` | All agents read settings from here | None — fatal |
| `mindmargin/core/blackboard.py` | Inter-agent communication | None — fatal |
| `mindmargin/core/checkpoint.py` | Fault-tolerant resume | None — fatal |
| `mindmargin/core/base.py` | All 12 agents inherit from BaseAgent | None — fatal |
| `mindmargin/core/orchestrator.py` | Pipeline execution engine | None — fatal |
| `mindmargin/agents/script.py` | Core content generation | ScriptAgent returns placeholder |
| `mindmargin/agents/voice.py` | Audio narration | VoiceAgent returns placeholder paths |
| `mindmargin/agents/editing.py` | Video assembly | EditingAgent returns FFmpeg command only |
| `mindmargin/utils/ffmpeg_utils.py` | Actual video rendering | Must have FFmpeg on PATH |
| `config/settings.yaml` | Runtime configuration | Hardcoded defaults in config.py |
| `config/agents.yaml` | Per-agent enable/disable/config | Hardcoded defaults in config.py |

### OPTIONAL (enhancements, not critical)

| Module | Purpose | Impact if Disabled |
|--------|---------|-------------------|
| `trend` | Topic scoring | Score defaults to 60 — pipeline runs anyway |
| `research` | Multi-source research | ScriptAgent uses topic string only |
| `hook` | CTR-optimized hook variants | Uses default hook template |
| `seo` | Title/description/tag generation | Uses topic as title, empty tags |
| `visual` | Scene-by-scene direction | EditingAgent uses generic shots |
| `thumbnail` | Thumbnail rendering | Uses text-overlay fallback |
| `upload` | YouTube API upload | Saves to disk only |
| `analytics` | Performance tracking | No metrics collected |
| `learning` | Optimization feedback | No recommendations generated |
| `ComfyUI` | AI image generation | Falls back to stock media / Ken Burns on static |
| `Piper TTS` | Local voice synthesis | Falls back to system TTS or placeholder silence |
| `Whisper STT` | Auto-caption generation | Falls back to FFmpeg burn-in with script text |
| `YouTube Data API` | Live upload | Saves video to `output/` for manual upload |
| `n8n` | Alternative workflow engine | Not used at all — Celery is primary |
| `Flower` | Celery monitoring | No live task visibility |
| `Nginx` | Reverse proxy | API available on raw port 8000 |
| `PostgreSQL` | Persistent storage | Falls back to SQLite or in-memory dict |
| `Redis` | Message broker | Celery falls back to filesystem transport |
| `Ollama` | LLM inference | Falls back to mock/template response (dramatic quality drop) |
| `Docker` | Containerization | All services run natively |

---

## 5. MVP Path (Minimum Viable Product)

### MVP Definition
A working pipeline that takes a topic string and produces a viewable video file on disk.

### MVP Agent Set
```
ENABLED: research, script, voice, editing
DISABLED: trend, hook, seo, visual, thumbnail, upload, analytics, learning
```

### MVP Data Flow
```
topic ──► research ──► script ──► voice ──► editing ──► output/video.mp4
           │            │           │           │
           │            │           │           └── FFmpeg concat + Ken Burns
           │            │           └────────────── Piper TTS WAV files
           │            └────────────────────────── 9-section script text
           └─────────────────────────────────────── Section metadata
```

### MVP Dependencies (Minimal)

```
EXTERNAL SERVICES NEEDED:
  └── FFmpeg (on PATH) — for video assembly

NO EXTERNAL SERVICES NEEDED:
  ├── No Redis
  ├── No PostgreSQL
  ├── No Ollama
  ├── No ComfyUI
  └── No YouTube API

AI SUBSTITUTIONS (all template-based, no inference):
  ├── research → returns 6 generic section templates
  ├── script → returns 9-section template with topic interpolated
  ├── voice → returns tone params per section (no actual audio gen)
  └── editing → returns FFmpeg command string (no actual render)
```

### MVP Command

```bash
# Generates a video with placeholder content
# No external services needed — runs entirely offline
python -m mindmargin.main --topic "Enron"
# Output: output/videos/Enron_20260518_120000.mp4 (or command string)
```

### MVP Hardware Requirements

```
CPU: Any x64 processor (no AVX512 needed)
RAM: 512MB minimum
GPU: None required
Disk: 100MB free
FFmpeg: Required for actual video output

Total cost: $0/month
```

### MVP → Production Upgrade Path

```
STEP 1 — Add LLM (quality upgrade)
  └── Install Ollama, pull llama3:70b
  └── Enable research, hook, seo, script agents
  └── Cost: $0 (local), $20-40/mo (API)

STEP 2 — Add Voice (audio upgrade)
  └── Install Piper TTS, download voice model
  └── Enable voice agent
  └── Cost: $0

STEP 3 — Add Images (visual upgrade)
  └── Install ComfyUI, download SDXL model
  └── Enable visual agent
  └── Cost: $0 (need RTX 4090 or similar)

STEP 4 — Add YouTube Upload (distribution)
  └── Set up YouTube Data API credentials
  └── Enable upload agent
  └── Cost: $0 (free API quota)

STEP 5 — Add Infrastructure (scalability)
  └── Enable Redis + PostgreSQL
  └── Enable analytics + learning agents
  └── Set up Docker Compose
  └── Cost: $0 (local) or $50-100/mo (cloud)
```

---

## 6. Initialization Flow

### Application Boot Sequence

```
┌─────────────────────────────────────────────────────────┐
│                    python -m mindmargin.main             │
└─────────────────────────────────────────────────────────┘
                            │
                            ▼
              ┌───────────────────────────┐
              │  Parse CLI arguments       │
              │  --topic, --publish,       │
              │  --resume, --api           │
              └───────────────────────────┘
                            │
                            ▼
              ┌───────────────────────────┐
              │  setup_logger()            │
              │  → console handler         │
              │  → file handler            │
              │    (output/mindmargin.log) │
              └───────────────────────────┘
                            │
                            ▼
              ┌───────────────────────────┐
              │  load_settings()           │
              │  load_brand()              │
              │  load_agents_config()      │
              │                            │
              │  Merge order:              │
              │  1. Default Pydantic vals  │
              │  2. YAML file overrides    │
              │  3. Environment variables  │
              └───────────────────────────┘
                            │
                            ▼
              ┌───────────────────────────┐
              │  Orchestrator.__init__()   │
              │  → pipeline_id (or resume) │
              │  → Blackboard()            │
              │  → Checkpoint(output/     │
              │        checkpoints/)       │
              │  → _agents = {}           │
              └───────────────────────────┘
                            │
                            ▼
              ┌───────────────────────────┐
              │  orchestrator.run(topic)   │
              └───────────────────────────┘
                            │
                            ▼
              ┌───────────────────────────┐
              │  _build_agents()           │
              │  → 12 agent instances      │
              │  → Each gets:              │
              │    • AgentConfig           │
              │    • Blackboard reference  │
              │    • Checkpoint reference  │
              └───────────────────────────┘
                            │
                            ▼
              ┌───────────────────────────┐
              │  Agent Loop (×12)          │
              │                            │
              │  For each agent in order:  │
              │  1. Check config.enabled   │
              │  2. Check checkpoint       │
              │     → resume if exists     │
              │  3. agent.execute()        │
              │     → writes to blackboard │
              │     → saves checkpoint     │
              │     → marks completed      │
              │  4. On failure: stop       │
              └───────────────────────────┘
                            │
                            ▼
              ┌───────────────────────────┐
              │  Return result dict        │
              │  {status, pipeline_id}     │
              └───────────────────────────┘
```

### Agent Initialization (per agent)

```
agent.execute(pipeline_id)
│
├── Check config.enabled
│   └── False → return {status: "skipped"}
│
├── Check checkpoint.exists(pipeline_id, self.name)
│   └── True → return checkpoint data (resume)
│
├── self.run(pipeline_id)
│   │
│   ├── Read required keys from blackboard
│   ├── Execute agent logic
│   ├── Write results to blackboard
│   └── Return result dict
│
├── self.checkpoint.save(pipeline_id, self.name, result)
├── self.blackboard.mark_completed(self.name)
└── Return result
```

---

## 7. Service Communication Map

### Inter-Service Communication

```
┌───────────┐         HTTP (11434)        ┌───────────┐
│   API     │◄──────────────────────────► │  Ollama   │
│  (8000)   │                             │ (LLM)     │
└─────┬─────┘                             └───────────┘
      │                                          ▲
      │ HTTP (8000)                              │ HTTP (11434)
      │                                          │
      ▼                                          │
┌───────────┐         HTTP (8188)        ┌───────────┐
│  Worker   │◄──────────────────────────► │  ComfyUI  │
│ (Celery)  │                             │ (Images)  │
└─────┬─────┘                             └───────────┘
      │                                          ▲
      │ Subprocess (piper CLI)                   │ HTTP (5000)
      ▼                                          │
┌───────────┐                            ┌───────────┐
│  Piper    │                            │  Whisper  │
│  TTS      │                            │  (STT)    │
└───────────┘                            └───────────┘
      │
      │ Subprocess (ffmpeg CLI)
      ▼
┌───────────┐
│  FFmpeg   │
│  (Video)  │
└───────────┘

DATA PLANE (Redis):
  ┌──────┐     ┌──────────┐     ┌──────────┐
  │ API  │────►│  Redis   │◄───►│  Worker  │
  └──────┘     │(Broker)  │     └──────────┘
               └─────┬────┘
                     │
               ┌─────▼────┐
               │  Flower  │
               │(Monitor) │
               └──────────┘

DATA PLANE (PostgreSQL):
  ┌──────┐     ┌──────────┐     ┌──────────┐
  │ API  │────►│PostgreSQL│◄───►│  Worker  │
  └──────┘     │ (Storage)│     └──────────┘
               └──────────┘

CONTROL PLANE (Blackboard — in-process):
  ┌──────────┐     ┌──────────┐     ┌──────────┐
  │ Agent 1  │────►│Blackboard│◄────│ Agent 2  │
  └──────────┘     └──────────┘     └──────────┘
       │                │                │
       │     Checkpoint │                │
       ▼                ▼                ▼
  ┌─────────────────────────────────────────┐
  │          Checkpoint Files               │
  │     (output/checkpoints/*.json)         │
  └─────────────────────────────────────────┘
```

### Data Flow (per video pipeline)

```
Topic String
    │
    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                           Blackboard Memory                            │
│                                                                        │
│  topic: "Enron"                                                        │
│  trend_analysis: {...}   ← trend writes                                │
│  research_data: {...}    ← research writes, script/hook/seo read       │
│  hooks: [...]            ← hook writes, seo reads                      │
│  seo_data: {...}         ← seo writes, thumbnail/upload reads          │
│  script_data: {...}      ← script writes, visual/voice reads           │
│  visual_directions: [...]← visual writes, editing reads                │
│  thumbnail_data: [...]   ← thumbnail writes, upload reads              │
│  voice_data: {...}       ← voice writes, editing reads                 │
│  edit_plan: {...}        ← editing writes, upload reads                │
│  upload_data: {...}      ← upload writes, analytics reads              │
│  analytics_data: {...}   ← analytics writes, learning reads            │
│  learning_data: {...}    ← learning writes (final)                     │
│                                                                        │
│  completed_agents: [trend, research, hook, ...]                        │
│  pipeline_id: "pipe_20260518_120000"                                   │
│  status: "completed" / "failed"                                        │
└────────────────────────────────────────────────────────────────────────┘
```

### Port Map

| Service | Port | Protocol | Purpose |
|---------|------|----------|---------|
| API | 8000 | HTTP | REST API endpoints |
| Worker | — | — | Celery (background tasks, no direct port) |
| Redis | 6379 | TCP | Message broker, cache, Celery backend |
| PostgreSQL | 5432 | TCP | Persistent storage |
| Ollama | 11434 | HTTP | LLM inference API |
| ComfyUI | 8188 | HTTP | Image generation API |
| Flower | 5555 | HTTP | Celery task monitoring dashboard |
| n8n | 5678 | HTTP | Alternative workflow editor |
| Nginx | 80 | HTTP | Reverse proxy |
| Piper | — | CLI | Voice synthesis (subprocess) |
| FFmpeg | — | CLI | Video rendering (subprocess) |

---

## 8. Error Handling & Recovery

### Agent Failure Recovery

```
Agent fails during execution:
  │
  ├── orchestrator catches Exception
  ├── blackboard.add_error(agent_name, str(e))
  ├── Checkpoint: NOT saved (incomplete agent)
  ├── Pipeline status: "failed"
  └── Resume: checkpoint skipped only for failed agent
      → All previous agents marked completed
      → Failed agent re-executes from scratch
```

### Service Failure Recovery

```
Dependency fails:
  │
  ├── Redis down → Celery cannot queue tasks
  │   └── API starts in "degraded" mode (sync execution)
  │
  ├── PostgreSQL down → Models cannot persist
  │   └── Agent falls back to in-memory dict
  │
  ├── Ollama down → LLM-dependent agents fail
  │   └── Agent returns template-based result (degraded)
  │
  ├── ComfyUI down → VisualAgent fails
  │   └── Falls back to StockMediaProvider
  │
  └── Piper missing → VoiceAgent returns params only
      └── EditingAgent uses silent audio track
```

### Checkpoint Resume Flow

```
Resume failed pipeline:
  │
  ├── CLI: python -m mindmargin.main --topic "Enron" --resume pipe_20260518_120000
  │
  ├── Orchestrator checks checkpoint files for each agent:
  │   ├── Checkpoint exists → skip (already completed)
  │   └── Checkpoint missing → execute agent
  │
  └── Re-executed agents write fresh blackboard values
      → Idempotent per agent by design
```

---

## 9. Agent Execution Timeline (Full Pipeline)

```
Time    Agent           Duration  Key Resource
────    ─────           ────────  ────────────
T+0s    trend           30s       CPU (no GPU)
T+30s   research        120s      Ollama (CPU)
T+150s  hook            60s       Ollama (CPU)
T+210s  seo             60s       Ollama (CPU)
T+270s  script          600s      Ollama (CPU)  — 9 LLM calls
T+870s  visual          60s       Ollama (CPU)  — scene descriptions
T+930s  thumbnail       120s      CPU (Pillow rendering)
T+1050s voice           600s      Piper (CPU)  — 9 WAV files
T+1650s editing         3000s     FFmpeg (CPU) — video assembly
T+4650s upload          60s       Network (YouTube API)
T+4710s analytics       30s       CPU (no GPU)
T+4740s learning        30s       Ollama (CPU)

Total: ~79 min
```

---

## 10. Configuration Sources (Priority Order)

```
┌──────────────────────────────────────────────────────────────────────┐
│                    Configuration Merge Priority                      │
│                                                                      │
│  Lowest                                                                │
│    ▼                                                                  │
│  ┌──────────────────────────────────────────────┐                    │
│  │  1. Pydantic defaults in config.py            │                    │
│  │     {llm.model: "llama3:70b", piper.voice:   │                    │
│  │      "en_US-lessac-medium", ...}              │                    │
│  └──────────────────────────────────────────────┘                    │
│                          │                                            │
│                          ▼                                            │
│  ┌──────────────────────────────────────────────┐                    │
│  │  2. YAML files in config/                     │                    │
│  │     settings.yaml, agents.yaml, brand.yaml    │                    │
│  │     → Overrides matching keys only            │                    │
│  └──────────────────────────────────────────────┘                    │
│                          │                                            │
│                          ▼                                            │
│  ┌──────────────────────────────────────────────┐                    │
│  │  3. Environment variables                     │                    │
│  │     OLLAMA_BASE_URL, LLM_MODEL,               │                    │
│  │     YOUTUBE_API_KEY, REDIS_URL, etc.          │                    │
│  │     → Override YAML values                    │                    │
│  └──────────────────────────────────────────────┘                    │
│                          │                                            │
│                          ▼                                            │
│  Highest                                                               │
│                                                                      │
│  Result: Unified namespace accessible via                             │
│  mindmargin.core.config.settings.llm.model                            │
└──────────────────────────────────────────────────────────────────────┘
```
