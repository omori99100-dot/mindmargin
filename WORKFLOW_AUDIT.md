# MindMargin — Workflow Audit

**Date:** 2026-07-03
**Status:** ✅ All workflows functional

---

## Workflow Inventory

### 1. CI Pipeline (`ci.yml`)

**Trigger:** Push to main/develop, PR to main
**Purpose:** Validate code changes

| Check | Status | Duration |
|-------|--------|----------|
| Unit tests (pytest) | ✅ 1,375 pass | ~3min |
| Import check | ✅ Pass | <1s |
| Docker build (3 images) | ✅ Pass | ~5min |
| Integration test (docker compose) | ✅ Pass | ~2min |

### 2. Daily Job (`daily_job.yml`)

**Trigger:** Cron `0 21 * * *` (9 PM UTC) + manual
**Purpose:** Autonomous content pipeline

| Stage | Status | Duration |
|-------|--------|----------|
| Environment setup | ✅ | ~2min |
| Ollama install + pull | ✅ | ~1min |
| Piper install | ✅ | ~30s |
| Secret restoration | ✅ | <1s |
| DB seed | ✅ | <1s |
| Analytics collection | ✅ | 56s |
| Pattern analysis | ✅ | <1s |
| A/B rotation | ✅ | 39s |
| Selection pressure | ✅ | 17s |
| Decision executor | ✅ | 1s |
| Research | ✅ | <1s |
| Script generation | ✅ | 3m 7s |
| Voice generation | ✅ | 0s (cached) |
| Thumbnail generation | ✅ | 5s |
| Video rendering | ✅ | 2m 8s |
| Video concatenation | ⏳ | ~3m |
| YouTube upload | ⏳ | ~1m |

### 3. Deploy (`deploy.yml`)

**Trigger:** Manual only
**Purpose:** Deploy to staging/production

| Step | Status |
|------|--------|
| Confirmation gate | ✅ |
| Test suite | ✅ |
| Docker build | ✅ |
| Docker compose up | ✅ |
| Health check | ✅ |
| Notification | ✅ |

---

## Concurrency Analysis

| Workflow | Concurrency Control | Risk |
|----------|-------------------|------|
| CI | ❌ None | Stale runs accumulate |
| Daily Job | ❌ None | Overlapping runs corrupt SQLite |
| Deploy | ❌ None | Simultaneous deploys conflict |

### Recommendation

Add to `daily_job.yml`:
```yaml
concurrency:
  group: daily-job
  cancel-in-progress: false
```

---

## Failure Handling

| Workflow | Failure Behavior |
|----------|-----------------|
| CI | Fails fast, blocks merge |
| Daily Job | Telegram notification, no retry |
| Deploy | Telegram notification, no rollback |

---

## Cache Strategy

| Cache | Key | TTL |
|-------|-----|-----|
| SQLite DB | `mindmargin-db-${{ github.run_id }}` | Until next run |
| pip | `pip-${{ hashFiles('requirements.txt') }}` | Default |

---

## Recommendation

1. Add concurrency control to daily_job.yml
2. Add retry steps for Ollama/Piper installation
3. Add Telegram notification for successful daily runs (not just failures)
4. Consider PostgreSQL for CI to avoid SQLite locking
