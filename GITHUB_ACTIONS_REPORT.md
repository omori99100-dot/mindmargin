# MindMargin — GitHub Actions Audit

**Date:** 2026-07-03
**Status:** ✅ CONFIGURED

---

## Workflow Inventory

| Workflow | File | Trigger | Purpose |
|----------|------|---------|---------|
| CI | `ci.yml` | push/PR to main/develop | Tests, lint, Docker build, integration test |
| Daily Job | `daily_job.yml` | cron `0 21 * * *` + manual | Full pipeline: research → video → upload |
| Deploy | `deploy.yml` | manual only | Deploy to staging/production |

---

## 1. CI Workflow (`ci.yml`)

### Jobs

| Job | Runner | Timeout | Steps |
|-----|--------|---------|-------|
| `test` | ubuntu-latest | 15min | pytest tests/ |
| `lint` | ubuntu-latest | 10min | import check |
| `docker` | ubuntu-latest | 15min | Build 3 Dockerfiles |
| `integration` | ubuntu-latest | 20min | docker compose up, health check |

### Issues
- ❌ No `concurrency:` group — stale CI runs accumulate
- ❌ No `permissions:` block — uses default (could be broader)
- ⚠️ Lint job only checks `import mindmargin` — no actual linting
- ⚠️ Docker build is validation-only (no push)

---

## 2. Daily Job Workflow (`daily_job.yml`)

### Trigger
- **Schedule:** `cron "0 21 * * *"` (9 PM UTC daily)
- **Manual:** `workflow_dispatch`

### Steps (Critical Path)
1. Checkout code
2. Setup Python 3.11
3. `pip install -r requirements.txt`
4. `sudo apt-get install -y ffmpeg`
5. Install Ollama (curl | sh), pull `qwen2.5:0.5b`
6. Install Piper TTS binary + voice model
7. Patch `config/settings.yaml` via `sed`
8. Restore `data/mindmargin.db` from cache
9. Write secrets to disk: `YOUTUBE_TOKEN_B64` → pickle, `ENV_FILE` → .env, `CLIENT_SECRETS` → JSON
10. `python scripts/seed_db.py`
11. **`python -m mindmargin.main --run-daily-job`** ← The actual pipeline
12. Save `data/mindmargin.db` to cache
13. Notify on failure via Telegram

### Secrets Required

| Secret | Purpose | Criticality |
|--------|---------|-------------|
| `YOUTUBE_TOKEN_B64` | YouTube OAuth token (base64) | **Required** |
| `ENV_FILE` | Full `.env` file contents | **Required** |
| `CLIENT_SECRETS` | Google OAuth client secrets JSON | **Required** |
| `TELEGRAM_BOT_TOKEN` | Failure notification | Optional |
| `TELEGRAM_CHAT_ID` | Failure notification target | Optional |

### Issues
- ❌ **No concurrency control** — can overlap if schedule fires while previous runs
- ❌ **No retry logic** — Ollama pull or Piper download failure = entire job fails
- ⚠️ **SQLite in CI** — not suitable for concurrent access
- ⚠️ **Secrets written to disk** — plain files on runner filesystem
- ⚠️ **`sed` patches config** — fragile, modifies tracked file
- ⚠️ **Piper AMD64 only** — would fail on ARM runners
- ⚠️ **45min timeout** — may be tight for full pipeline + video rendering

---

## 3. Deploy Workflow (`deploy.yml`)

### Trigger
- **Manual only:** `workflow_dispatch` with `environment` input

### Steps
1. Confirmation gate (must match environment name)
2. Run tests
3. Build Docker images
4. Deploy via docker compose
5. Health check polling (20 attempts × 3s)
6. Notify success/failure via Telegram

### Issues
- ❌ **No concurrency control** — simultaneous deploys could conflict
- ⚠️ **Production nginx needs SSL certs** — no cert volume configured
- ⚠️ **No environment protection rules** documented

---

## Required Setup for GitHub Actions

### Step 1: Create GitHub Secrets

Go to repo → Settings → Secrets and variables → Actions → New repository secret

| Secret Name | Value |
|-------------|-------|
| `YOUTUBE_TOKEN_B64` | `base64 -w0 youtube_token.pickle` |
| `ENV_FILE` | Contents of `.env` file |
| `CLIENT_SECRETS` | Contents of `client_secrets.json` |
| `TELEGRAM_BOT_TOKEN` | (optional) Telegram bot token |
| `TELEGRAM_CHAT_ID` | (optional) Telegram chat ID |

### Step 2: Verify Workflow Triggers

```bash
# Trigger daily job manually
gh workflow run daily_job.yml

# Check status
gh run list --workflow=daily_job.yml
```

### Step 3: Monitor First Run

```bash
# Watch live logs
gh run watch <run-id>
```

---

## Recommendation

The GitHub Actions setup is functional but fragile. The main risks are:
1. No concurrency control on daily job
2. No retry on external dependency failures
3. SQLite concurrency issues in CI

For production, consider:
- Adding `concurrency: { group: daily-job, cancel-in-progress: false }` to daily_job.yml
- Adding retry steps for Ollama/Piper installation
- Using PostgreSQL instead of SQLite for CI
