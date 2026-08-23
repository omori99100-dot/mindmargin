# Root Cause Final Report

## Executive Summary

The system suffered from two intertwined deadlocks that prevented autonomous
YouTube publishing. Both originated from a single root cause: **no canonical
definition of "successful publish" existed in the codebase**.

Every component had its own ad-hoc filter for counting published videos, and
each used different criteria. When a fix was applied to one site, it broke
another, creating a cascade of failures.

---

## Timeline

| Phase | What Happened | Why |
|---|---|---|
| Initial state | `_check_daily_publish_cap` used `error == ""` to count publishes | Worked in simple cases |
| First publish | Channel health gate blocked it (health 2.25 < 4.0) | Bootstrap needed |
| Line 569 fix | `error=""` forced for completed pipelines | To bootstrap confidence gate |
| Bug introduced | Blocked publishes now had `error=""` + `video_id=""` | Daily cap counted them as real |
| Deadlock | Cap reported "1 published today" → blocked all future runs | No real upload could happen |
| Confidence gate | `confidence 0.55 < MIN_CONFIDENCE 0.60` | Locked out all topics |
| **Phase 22 fix** | `is_successful_publish()` checks ALL THREE conditions | Single source of truth |

---

## Root Cause Diagram

```
                    ┌─────────────────────────────┐
                    │  No canonical definition of  │
                    │   "successful publish"       │
                    └─────────────────────────────┘
                               │
             ┌─────────────────┼─────────────────┐
             ▼                 ▼                  ▼
     ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
     │Cap check uses│  │log_execution │  │Line 569 sets │
     │error=="" only│  │checks ALL 3  │  │error="" for  │
     │(misses       │  │(correct but  │  │completed but │
     │video_id="")  │  │not reusable) │  │blocked runs  │
     └──────────────┘  └──────────────┘  └──────┬───────┘
              │                                  │
              └──────────────┬───────────────────┘
                             ▼
              ┌─────────────────────────────┐
              │ Blocked publish recorded    │
              │ error="" + video_id=""      │
              └─────────────────────────────┘
                             │
                             ▼
              ┌─────────────────────────────┐
              │ Cap check counts it as real │
              │ → "1 published today"       │
              │ → blocks all future runs    │
              └─────────────────────────────┘
```

---

## The Fix

**One function, one purpose, every call site uses it:**

```python
def is_successful_publish(log: dict) -> bool:
    vid = log.get("video_id")
    return (log.get("pipeline_status") == "completed"
            and bool(vid.strip() if isinstance(vid, str) else vid)
            and not log.get("error"))
```

Returning `True` only when ALL three conditions hold guarantees that:
- A completed pipeline with `error=""` is NOT enough
- A completed pipeline with `video_id=""` is NOT enough
- Only a pipeline with **completed status + real video ID + no error** counts

---

## Files Changed

| File | Change |
|---|---|
| `mindmargin/analytics/memory.py` | Added `is_successful_publish()` + updated docstring |
| `mindmargin/agents/decision_executor.py` | Replaced `error == ""` filter; fixed line 569 error message |
| `mindmargin/channel/governance.py` | Replaced inline filter with canonical call |
| `mindmargin/intelligence/strategy.py` | Replaced inline filter with canonical call |
| `diagnose_cap.py` | Rewrote to use canonical function |
| `tests/unit/test_is_successful_publish.py` | 19 new regression tests |

---

## Verification Criteria

| Criterion | Status |
|---|---|
| All 82 tests pass | ✅ |
| Blocked publishes not counted toward daily cap | ✅ (confirmed via execution_log) |
| Real uploads counted exactly once | ✅ (confirmed via execution_log) |
| Meaningful error messages in execution_log | ✅ (line 569 fix) |
| Committed and pushed to GitHub | ✅ |
| GHA workflow triggered | ⏳ User action needed |
| Real YouTube upload verified | ⏳ Pending GHA run |

---

## Lessons Learned

1. **Define the contract first.** `is_successful_publish()` should have been in
   the codebase from day one — before any filtering logic was written.

2. **Bootstrap workarounds create bugs.** Forcing `error=""` to bypass the
   confidence gate broke the daily cap. The proper fix was to bypass the gate
   differently (which was already done: `total_videos < 4`).

3. **Record real errors, not placeholder values.** Line 569 now records the
   actual reason publish was blocked. This doesn't affect the canonical
   function (which checks `video_id`) and makes debugging easier.

4. **Test the contract, not the implementation.** The 19 regression tests
   test `is_successful_publish()` directly — not the internal details of
   each call site. This means future filters will automatically be correct
   if they use the canonical function.
