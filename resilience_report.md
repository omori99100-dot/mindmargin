# Resilience Report — Failure Recovery Testing

**Date:** 2026-06-06

---

## Results Summary

| Scenario | Status | Graceful? | Error Reported? | No Crash? |
|----------|--------|-----------|-----------------|-----------|
| **A. YouTube API unavailable** | ✅ PASS (4/4) | ✅ | ✅ | ✅ |
| **B. Ollama unavailable** | ✅ PASS | ✅ | ✅ | ✅ |
| **C. Piper unavailable** | ✅ PASS | ✅ (silent WAV placeholder) | ✅ | ✅ |
| **D. FFmpeg unavailable** | ✅ PASS (3/3) | ✅ | ✅ | ✅ |
| **E. Database locked** | ❌ FAIL | ❌ No retry logic | ❌ Propagates directly | ❌ Crashing query |
| **F. Disk full** | ⏭️ SKIP | — Windows limitation | — | — |

**Overall: 9/11 subtests pass (82%). 1 real vulnerability identified.**

---

## Detailed Findings

### A. YouTube API unavailable ✅
- `get_video_stats()` returns `{"status": "failed", "error": ...}` instead of crashing.
- `get_analytics()` falls back to `get_video_stats()` when Analytics API fails.
- `upload_video()` returns `{"status": "failed"}` when auth fails.
- No exceptions leak to the caller.

### B. Ollama unavailable ✅
- Pipeline catches ScriptAgent failure with retry (2 attempts).
- Returns `{"status": "failed", "error": ...}`.
- Pipeline continues to report status rather than crashing.

### C. Piper unavailable ✅
- `generate_wav()` detects `piper_available() == False`.
- Creates a silent WAV placeholder (`_write_silent_wav()`).
- VoiceAgent completes with status "completed" using placeholder audio.
- No crash, no data loss.

### D. FFmpeg unavailable ✅
- `ffmpeg_available()` correctly returns `False`.
- `ff.run()` returns `False` without crash.
- `section_video()` returns `None` without crash.

### E. Database locked ❌
**Vulnerability:**
- `memory._get_db()` has **no retry logic** for `sqlite3.OperationalError("database is locked")`.
- No `busy_timeout` is set on the SQLite connection.
- A concurrent writer (e.g., another process, or the monitoring metrics writer) could cause pipeline operations to fail.
- **Impact:** If two pipeline processes run simultaneously, one will crash with `OperationalError`.

### F. Disk full ⏭️ SKIP
- Windows NTFS does not enforce Unix-style `chmod` write protection on directories.
- Python's `pathlib.Path.write_text()` succeeds even when `S_IWRITE` is removed.
- This is a **platform limitation**, not a system bug. On Linux, `write_text()` would raise `PermissionError`.

---

## Recommendations

1. **Add `busy_timeout=5000` to all SQLite connections** in `memory.py` so the DB waits 5 seconds instead of failing immediately.
2. **Add retry wrapper** around `_get_db()` queries (3 retries with exponential backoff) for transient `OperationalError`.
3. **(Optional)** Add disk space check at pipeline start — `shutil.disk_usage()` before writing output.
