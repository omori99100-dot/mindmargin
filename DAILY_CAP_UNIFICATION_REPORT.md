# Daily Cap Unification Report — Phase 22

## Problem

The definition of "successful YouTube upload" was duplicated across 5+ locations
in the codebase, each using slightly different filtering criteria:

| Location | Original Filter | Bug |
|---|---|---|
| `decision_executor.py:_check_daily_publish_cap` | `l.get("error") == ""` | Counts blocked publishes (error="" + video_id="") |
| `governance.py:_check_max_daily` | `status=completed AND not log.get("error")` | Same bug |
| `strategy.py:published_today` | `status=completed AND error == ""` | Same bug |
| `decision_executor.py:log_execution` | `status=completed AND video_id AND not error` | Correct (inline) |
| `diagnose_cap.py` | `l.get("error") == ""` | Same bug |

The inconsistency caused the **cold-start deadlock**: blocked publishes recorded
`error=""` (line 569), which made the daily cap filter believe a real upload
had occurred, blocking all future publishes. The only "correct" filter was in
`log_execution` itself — but it was inline code, not reusable.

## Solution: Single Canonical Function

Added `is_successful_publish(log: dict) -> bool` to `mindmargin/analytics/memory.py:1071`:

```python
def is_successful_publish(log: dict) -> bool:
    """Canonical SSOT: returns True only when ALL three hold:
    1. pipeline_status == 'completed'
    2. video_id is non-empty
    3. error is empty/falsy
    """
    vid = log.get("video_id")
    return (log.get("pipeline_status") == "completed"
            and bool(vid.strip() if isinstance(vid, str) else vid)
            and not log.get("error"))
```

## Sites Replaced

| # | File | Line | Old Filter | New Filter |
|---|---|---|---|---|
| 1 | `decision_executor.py:_check_daily_publish_cap` | 361-363 | `l.get("error") == ""` | `is_successful_publish(l)` |
| 2 | `decision_executor.py:log_execution` | 265 | `pipeline_status == "completed" and video_id and not error` | `is_successful_publish({...})` |
| 3 | `governance.py:_check_max_daily` | 159-161 | `status=completed AND not error` | `is_successful_publish(log)` |
| 4 | `strategy.py:published_today` | 35-40 | `status=completed AND error == ""` | `is_successful_publish(e)` |
| 5 | `diagnose_cap.py` | 37-39 | `l.get("error") == ""` | `is_successful_publish(l)` |

## Additional Fix: Line 569

Previously: `log_error = "" if pipeline_status == "completed" else "pipeline failed"`

Now records the actual reason:
- `""` — only when a real upload occurred (pub_video_id is set)
- `"pipeline failed"` — when the pipeline itself crashed
- `"publish skipped (auto_publish=False)"` — when auto_publish is off
- Gate reason — when blocked by channel health or daily cap
- `"publish blocked or failed"` — fallback

## Tests Added

**19 comprehensive regression tests** in `tests/unit/test_is_successful_publish.py`:

| Scenario | Expected |
|---|---|
| Successful upload (completed + video_id + no error) | True |
| Pipeline failed (status=failed) | False |
| Pipeline failed with error | False |
| Pipeline failed but has video_id | False |
| Blocked by health gate (completed + no video_id + no error) | False |
| Blocked by daily cap (completed + no video_id + error msg) | False |
| Publish skipped (completed + no video_id + skip msg) | False |
| Upload exception (completed + no video_id + error) | False |
| Duplicate detected (completed + no video_id + dup error) | False |
| Restart recovery with old entries | True |
| Mixed log — blocked entry | False |
| Mixed log — success entry | True |
| Empty dict | False |
| None values for video_id | False |
| error=None with valid video_id | True |
| Unknown pipeline status | False |
| Running with video_id (guard) | False |
| Only video_id, no status | False |
| Whitespace video_id | False |

All **82 tests** pass (19 new + 9 bootstrap + 54 existing decision_executor).

## Verification

Local execution_log after fix:
```
id=10 topic='Netscape...' status=failed video_id='' error='pipeline failed' is_successful=False
id=9  topic='Circuit City'  status=completed video_id='VwyxyePTZ0w' error='' is_successful=True
id=8  topic='tech startup'  status=completed video_id='' error='' is_successful=False
...
```

- id=10 (pipeline failed): **not counted** toward daily cap
- id=8 (blocked publish): **not counted** toward daily cap (was counted before!)
- id=9 (real upload): **counted** toward daily cap

## Remaining

- [x] Code change
- [x] All tests passing
- [x] Pushed to GitHub
- [ ] GHA workflow triggered manually — user action required
- [ ] Real YouTube upload verified
