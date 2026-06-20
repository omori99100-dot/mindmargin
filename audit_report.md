# Audit Report — mindmargin

**Date:** 2026-06-06
**Scope:** Full repository audit

> This is an informational audit report generated during Phase 6 validation.
> No issues identified here are being actioned unless explicitly stated.

---

## Critical Issues

### C1. `ON CONFLICT(rowid)` is a no-op on `video_classifications`

**File:** `mindmargin/analytics/memory.py`
**Table:** `video_classifications`

The `save_classification()` function uses:
```sql
INSERT INTO video_classifications (...) VALUES (...)
ON CONFLICT(rowid) DO UPDATE SET ...
```

Since `rowid` equals the auto-generated `id` column (never specified in the INSERT), a conflict **never** occurs. Calling `save_classification()` twice for the same `(pipeline_id, video_id)` pair creates **duplicate rows** instead of updating the existing classification.

**Impact:** The `get_classification_for_video()` function returns the first matching row (via `LIMIT 1`), so duplicate rows after the first are invisible. Memory and storage waste.

### C2. `thumbnails.used` constraint never matches

**File:** `mindmargin/analytics/ab_testing.py:151`

```python
rows = conn.execute("SELECT path FROM thumbnails WHERE pipeline_id=? AND used=1 ORDER BY id ASC LIMIT ?", ...)
```

The `thumbnails.used` column is always `0` — no code ever sets it to `1`. This query returns zero rows forever, breaking thumbnail restoration in A/B testing.

**Impact:** Thumbnail variants can never be restored from the database.

### C3. Phantom metric reads — 6 categories expected by health reports but never recorded

**File:** `mindmargin/analytics/monitoring.py`

| Category | Read by | Recorded in production? |
|----------|---------|------------------------|
| `upload` | `get_system_health()`, `generate_weekly_system_report()` | ❌ Only in tests |
| `generation_failure` | `get_system_health()`, `report()`, `check_alerts()` | ❌ Never |
| `analytics_failure` | `get_system_health()`, `report()`, `check_alerts()` | ❌ Never |
| `youtube_api_failure` | `get_system_health()`, `report()`, `check_alerts()` | ❌ Never |
| `ab_status` | `get_system_health()`, `generate_weekly_system_report()` | ❌ Never |
| `selection_status` | `get_system_health()`, `generate_weekly_system_report()` | ❌ Never |

**Impact:** Health reports, alerts, and system monitoring reports always show zero/null for these metrics. Failure detection is effectively dead.

---

## Medium Issues

### M1. Orphan modules

- **`mindmargin/db/`** — SQLAlchemy models directory. Imports into `__init__.py` but nothing imports this package.
- **`mindmargin/workers/`** — Celery app + task definitions. Nothing starts Celery or calls these tasks.

### M2. Read-never-written columns

| Table | Column | Read by | Actual value |
|-------|--------|---------|-------------|
| `hooks` | `actual_ctr` | `get_best_hooks()`, `selection.py`, `patterns.py`, `optimizer.py` | Always NULL, falls back to `ctr_score` |
| `hooks` | `actual_retention` | `get_best_hooks()` | Always NULL |
| `titles` | `ctr` | `get_best_titles()` ORDER BY | Always NULL |
| `titles` | `views` | `get_best_titles()` SELECT | Always 0 |
| `pipelines` | `published_at` | `ab_testing.py`, `selection.py` | Always NULL, falls back to `created_at` |

**Impact:** `COALESCE(actual_ctr, ctr_score)` always uses the initial `ctr_score` — actual performance never feeds back. Title ordering by CTR always uses 0.

### M3. Unused metrics — recorded but never read

| Metric | File | Line |
|--------|------|------|
| `encoder_selection` | `mindmargin/utils/ffmpeg.py:82` | → stored in metrics JSON, never queried |
| `executor`/`circuit_breaker_tripped` | `mindmargin/agents/decision_executor.py:228` | → stored, never queried |
| `_RUNTIME_STAGE_STORE` | `mindmargin/analytics/monitoring.py:92` | → appended, never read |

### M4. Dead code — defined but never called

| Function | File | Line |
|----------|------|------|
| `record_runtime()` | `monitoring.py` | 95 |
| `record_stage_runtime()` | `monitoring.py` | 101 |
| `generate_optimization_hints()` | `feedback.py` | defined |
| `format_feedback_report()` | `feedback.py` | defined |

### M5. Silent exception handlers

At least 9 sites use `except: pass` or `except Exception: errors += 1` without logging.
Files affected:
- `mindmargin/analytics/memory.py` (ALTER TABLE migrations)
- `mindmargin/analytics/patterns.py`
- `mindmargin/analytics/selection.py`
- `mindmargin/core/pipeline.py`

### M6. Duplicate auth flow

`mindmargin/auth.py` and `mindmargin/do_auth.py` share ~90% duplicated YouTube OAuth code.

### M7. Duplicate `_find_ffmpeg()` definition

**File:** `mindmargin/utils/ffmpeg.py` — two definitions at lines 21-26 and 90-95. The second one overwrites the first.

---

## Low Priority

### L1. Unused imports

~7 files have imports that are never referenced in the importing module.

### L2. Never-read columns (13 total)

`pipelines.status`, `pipelines.youtube_status`, `titles.used`, `titles.created_at`, `hooks.used`, `hooks.created_at`, `thumbnails.actual_ctr`, `thumbnails.impressions`, `thumbnails.created_at`, `video_classifications.watch_time_s`, `video_classifications.engagement_rate`, `video_classifications.age_days`, `video_classifications.classified_at`.

### L3. ALTER TABLE runs before CREATE TABLE

`memory.py` lines 31-36 try to ALTER TABLE `video_classifications` before its CREATE TABLE on line 145. This always raises on first run (caught and ignored).

### L4. `_RUNTIME_STORE` is in-memory only

Runtime data in `_RUNTIME_STORE` and `_RUNTIME_STAGE_STORE` is not persisted to disk, unlike `_METRICS_STORE`. Loss on process restart.

---

## Technical Debt Score

| Category | Score (0-100) |
|----------|--------------|
| **Code Quality** | 65 |
| **Schema Hygiene** | 50 |
| **Error Handling** | 55 |
| **Monitoring Completeness** | 40 |
| **Dead Code** | 60 |

**Overall Technical Debt Score: 54 / 100**

(100 = perfectly clean, 0 = completely broken. Score reflects the system is functional but carries meaningful deferred maintenance.)
