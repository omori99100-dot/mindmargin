# FORENSIC_DAILY_CAP_REPORT.md

## Incident

The daily publish cap blocked execution with:
```
daily cap 1 reached (1 published today)
```

This is impossible because no video was uploaded today.

---

## (1) Which Function Returns the Count

`_check_daily_publish_cap()` at **`decision_executor.py:376`**:

```python
return True, f"daily cap {MAX_DAILY_PUBLISH} reached ({len(recent)} published today)"
```

The value `1` in `(1 published today)` is `len(recent)`.

---

## (2) Which SQL Query Produced It

No direct SQL. The rows come from `get_execution_log()` at **`memory.py:1057`**:

```python
def get_execution_log(limit: int = 20) -> list[dict]:
    conn = _get_db()
    rows = conn.execute(
        "SELECT * FROM execution_log ORDER BY executed_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]
```

SQL: `SELECT * FROM execution_log ORDER BY executed_at DESC LIMIT 50`

Then `_check_daily_publish_cap()` filters in-memory (lines 361-363):

```python
recent = [l for l in logs
          if l.get("executed_at", "") >= cutoff
          and l.get("error") == ""]
```

The cutoff value is computed at line 359:

```python
cutoff = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
```

So the count is: **number of `execution_log` rows where `error = ''` AND `executed_at >= now - 24h`**.

---

## (3) Which Exact Database Row Matched

The row has these column values:

| Column | Value | How Matched |
|--------|-------|-------------|
| `pipeline_status` | `"completed"` | (not filtered) |
| `video_id` | `""` | (not filtered) |
| `error` | `""` | `error == ""` → **TRUE** — counted |
| `executed_at` | `"2026-07-XXT21:30:00"` | `>= cutoff` → **TRUE** — within 24h |

**The row has `error = ''` but `video_id = ''` — meaning the pipeline completed but NO video was uploaded.**

This row is COUNTED toward the daily cap even though it represents a blocked publish, not an actual upload.

---

## (4) Why That Row Matches "Today"

The rolling 24-hour window:

```
cutoff = now - 24h = "2026-07-YY 21:00:00"  (when job runs at 21:00 UTC)
```

If the row was created at `2026-07-XXT21:30:00` (30 min after job start on a previous day), and now is within 24 hours of that timestamp, string comparison matches because ISO-8601 dates are lexicographically ordered:

```
"2026-07-XXT21:30:00" >= "2026-07-YY 21:00:00"  → True  (same calendar day range)
```

**Example:** Run 1 at Day N 21:00:00 → pipeline finishes at 21:30:00 → row has `executed_at = "2026-07-NT21:30:00"`. Run 2 at Day N+1 21:00:00 → cutoff = "2026-07-N 21:00:00". Row `"2026-07-NT21:30:00" >= "2026-07-N 21:00:00"` → True → counted.

---

## (5) Which Function Created That Row

The row was created by `save_execution_log()` at **`memory.py:1038`**, called from `log_execution()` at **`decision_executor.py:243`**, called from `execute_top_decision()` at **`decision_executor.py:575`**.

The call chain:

```
execute_top_decision()                                       decision_executor.py:384
  │
  ├─ Pipeline runs → pipeline_status = "completed"
  │
  ├─ _check_channel_health()
  │   └─ returns (False, "") [bootstrap bypass — total_videos < 4]
  │
  ├─ _check_daily_publish_cap()
  │   └─ returns (True, "daily cap 1 reached...") [THIS RUN — the blocking we're investigating]
  │   → pub_status = "blocked", pub_video_id = ""
  │
  └─ Line 569: log_error = "" if pipeline_status == "completed" else "pipeline failed"
       → pipeline_status = "completed" → log_error = ""
       │
       └─ log_execution(                                    decision_executor.py:575
             pipeline_id=...,
             topic=...,
             pipeline_status="completed",
             video_id="",           ← NO video uploaded (pub was blocked)
             video_url="",
             error=""               ← SET TO EMPTY STRING by line 569
           )
           │
           └─ save_execution_log(                           memory.py:1038
                  error=""          ← PASSED THROUGH
                )
                │
                └─ INSERT INTO execution_log                memory.py:1048
                     (pipeline_id, topic, ..., video_id, video_url, error, executed_at)
                   VALUES (?, ?, ..., "", "", "", datetime('now'))
                   → ROW: error='', video_id='', executed_at='now'
```

---

## (6) At What Moment It Was Inserted

The row was inserted by a **previous run** of the same workflow, at the end of `execute_top_decision()` (line 575-580), AFTER the publish gates were evaluated.

**Run N (previous day):**
1. Pipeline runs → `pipeline_status = "completed"` 
2. Channel health gate: bootstrap bypass → PASS
3. Daily publish cap: checked, either PASS (no previous rows) or BLOCKED
4. If BLOCKED: `pub_status = "blocked"`, `pub_video_id = ""`
5. Line 569: `log_error = ""` (because `pipeline_status == "completed"`)
6. Row inserted: `{error="", video_id="", executed_at="now"}`
7. This row is now available to poison the next run's daily cap check

**Run N+1 (today):**
1. Pipeline runs → `pipeline_status = "completed"`
2. Channel health gate: bootstrap bypass → PASS
3. Daily publish cap: queries `execution_log`, finds Run N's row with `error=""` → `len(recent) = 1`
4. `1 >= MAX_DAILY_PUBLISH (1)` → **BLOCKED**

---

## (7) What the Row Represents

### Actual meaning

The row represents a **pipeline that completed but whose publish was blocked by a safety gate** (either channel health on early runs, or daily publish cap on subsequent runs).

### Evidence from column values

| Column | Value | Interpretation |
|--------|-------|----------------|
| `pipeline_status` | `"completed"` | Pipeline generated all 7 stages successfully |
| `video_id` | `""` (empty) | **No YouTube upload happened** |
| `error` | `""` (empty) | Line 569 forces `error=""` for any completed pipeline |

### Classification verdict

| Category | Answer |
|----------|--------|
| Real YouTube upload? | **NO** — `video_id` is empty |
| Duplicate detection? | **NO** — duplicate detection happens before publish and returns early |
| Skipped publish? | **YES** — publish was blocked by a gate, not attempted |
| Completed pipeline? | **YES** — pipeline ran, video exists on disk |
| Failed upload? | **NO** — upload was never attempted (gate blocked first) |
| Cached state? | **NO** — persisted to SQLite database |
| Restored state? | **NO** — freshly inserted each day |

---

## (8) Root Cause

**Line 569 in `decision_executor.py`** forces `error=""` for ALL completed pipelines, regardless of whether the publish actually succeeded:

```python
log_error = "" if pipeline_status == "completed" else "pipeline failed"
```

This is too broad. When the publish is blocked by a gate (channel health or daily cap), `video_id` is empty (no upload happened), but `error` is also empty. The daily cap check at line 362-363 filters on `error == ""`:

```python
recent = [l for l in logs
          if l.get("executed_at", "") >= cutoff
          and l.get("error") == ""]
```

This treats a blocked publish as a successful upload for cap-counting purposes.

### Chain of causality

```
Line 569: log_error = "" for completed pipeline (regardless of upload success)
  → Row: error="", video_id=""
    → Daily cap: error=="" → counted as "published today"
      → Next run: cap blocks, creates ANOTHER row with error="", video_id=""
        → Perpetual cycle
```

---

## (9) Precise Fix

**Do NOT change line 569.** The `error=""` for completed pipelines is needed for the confidence gate bootstrap detection.

**Instead, change the daily cap filter** (line 362) to check `video_id` (actual upload evidence) instead of `error`:

```python
# Current (broken):
recent = [l for l in logs
          if l.get("executed_at", "") >= cutoff
          and l.get("error") == ""]

# Fixed:
recent = [l for l in logs
          if l.get("executed_at", "") >= cutoff
          and l.get("video_id")]        # ← only count rows with actual uploads
```

This correctly distinguishes:
- `{error="", video_id="xxx"}` → real upload → counted by cap ✅
- `{error="", video_id=""}` → blocked publish → NOT counted ✅

No other changes needed. The confidence gate bootstrap is preserved (`error=""` for all completed pipelines), and the daily cap only counts actual uploads.
