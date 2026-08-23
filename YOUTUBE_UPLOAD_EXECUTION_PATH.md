# YouTube Upload Execution Path

## Complete Function Call Chain

```
main.py --run-daily-job
  └── run_daily_job()                        [daily_analytics.py:225]
      └── run_feedback_loop()                [daily_analytics.py:63]
          ├── Step 1: collect_all_analytics()
          ├── Step 2: full_pattern_analysis()
          ├── Step 3: _generate_recommendations()
          ├── Step 4: run_ab_rotation_cycle()
          ├── Step 5: run_selection_cycle()
          └── Step 6: execute_top_decision(auto_publish=True)  ← UPLOAD PATH
                                                                    [decision_executor.py:392]

execute_top_decision(auto_publish=True)
  │
  ├── _check_circuit_breaker()              [decision_executor.py:277]
  │   └── Reads last 3 execution_log entries
  │       Only pipeline_status != "completed" counts as failure
  │       ✓ Fixed: gate blocks do NOT trip breaker
  │
  ├── run_brain_cycle()                     [channel_brain.py]
  │   └── Returns decisions with confidence scores
  │
  ├── run_growth_analysis()                 [growth_engine.py]
  │   └── Returns opportunities
  │
  ├── select_topic(brain, growth)           [decision_executor.py:37]
  │   └── Picks best unpublished topic
  │
  ├── Confidence Gate                       [decision_executor.py:480-494]
  │   ├── Bootstrap: if no execution history → bypass
  │   └── Normal: confidence must be >= 0.50
  │
  ├── execute_pipeline(topic, quick)        [decision_executor.py:513]
  │   │                                     → [pipeline.py:77]
  │   │
  │   ├── ResearchAgent.run()               [research.py]
  │   │   └── LLM-based research
  │   │
  │   ├── ScriptAgent.run()                 [script.py:137]
  │   │   ├── _generate_titles()
  │   │   ├── _generate_sections()          ← returns list[dict]
  │   │   ├── _quality_gate()              [script.py:357]
  │   │   ├── _generate_scene_plans()      [script.py:433]
  │   │   └── _merge_scores()              [script.py:545]
  │   │
  │   ├── VoiceAgent.run()                  [voice.py]
  │   │   └── TTS generation
  │   │
  │   └── EditingAgent.run()               [editing.py:50]  ← FAILS HERE
  │       ├── _render_sections()           [editing.py:109]
  │       │   └── for sec in sections:
  │       │       sec.get("scene_plan", [])  ← CRASH: 'str' has no .get()
  │       ├── _concat_video()
  │       ├── _concat_audio()
  │       ├── _generate_subtitles()
  │       └── _final_merge()
  │
  │   RESULT: pipeline_status = "failed"   [decision_executor.py:531]
  │   → log_execution(..., error="pipeline failed")
  │   → return {"status": "failed"}        [decision_executor.py:534]
  │   → publish_video() NEVER CALLED
  │
  │  ═══════════════════════════════════════════════
  │   THE PATH BELOW IS ONLY REACHED IF
  │   pipeline_status == "completed"
  │  ═══════════════════════════════════════════════
  │
  ├── save_pipeline_result()                [decision_executor.py:539]
  │
  └── Publish Stage
      │
      ├── _check_channel_health()           [decision_executor.py:548]
      │   ├── Bootstrap: total_videos < 4 → PASS
      │   └── Normal: health >= 4.0 → PASS
      │       Returns (False, "") → proceeds
      │
      ├── _check_daily_publish_cap()        [decision_executor.py:553]
      │   ├── Uses is_successful_publish()  ← canonical SSOT
      │   └── Only real uploads count
      │       Returns (False, "") → proceeds
      │
      └── publish_video()                   [decision_executor.py:110]
          │
          ├── check_credentials()           [client.py:170]
          │   ├── _has_google_libs()        [client.py:78]
          │   ├── _find_client_secrets()    [client.py:42]
          │   ├── _find_token()             [client.py:54]
          │   └── _get_authenticated_service() [client.py:87]
          │       ├── Load token pickle
          │       ├── Refresh if expired
          │       └── Or OAuth flow (not used in GHA)
          │
          ├── Duplicate detection           [decision_executor.py:135-151]
          │   └── Checks pipelines table for existing youtube_video_id
          │
          ├── Load script.json
          │
          ├── Generate/load thumbnails
          │
          ├── Generate metadata
          │
          ├── Find video/*_final.mp4        [decision_executor.py:186]
          │
          └── upload_video(                 [client.py:205]
                video_path, title, desc, tags, ...
              )
              │
              ├── _get_authenticated_service()
              ├── MediaFileUpload (resumable, 1MB chunks)
              ├── yt.videos().insert(part="snippet,status", ...)
              ├── request.next_chunk() loop  ← ACTUAL API CALL
              ├── response.get("id")          ← video_id from YouTube
              ├── _upload_thumbnail()
              └── _add_to_playlist()
                  │
                  └── Returns {"status":"completed","video_id":...,"url":...}

                  On success → save_pipeline() writes youtube_video_id
                  On failure → returns {"status":"failed","error":...}

```

---

## `youtube_video_id` Write Path

Only written to the `pipelines` table at `decision_executor.py:210-217`:

```python
if up_result.get("status") == "completed":         # ← YouTube API returned success
    vid = up_result["video_id"]                      # ← video_id from YouTube response
    save_pipeline(
        pipeline_id=pipeline_id, topic=topic,
        ...
        youtube_video_id=vid,                        # ← WRITTEN HERE
        youtube_url=url,
    )
```

This is the **only** place in the entire codebase where `youtube_video_id` is
written to the `pipelines` table. It is ONLY reached after:
1. Pipeline completed ✅
2. Health gate passed ✅
3. Daily cap passed ✅
4. YouTube credentials OK ✅
5. `upload_video()` returned `status == "completed"` ✅
6. YouTube API returned a real `video_id` ✅

No simulation, dry-run, or test-mode path can trigger this write.

---

## Answer: The Pipeline Editing Stage is the Blocker

The video upload process does **not** fail at any of the recently fixed gates
(daily cap, circuit breaker, confidence gate, health gate).

It fails because the **editing agent crashes** with:

```
AttributeError: 'str' object has no attribute 'get'
```

at `editing.py:127` → `sec.get("scene_plan", [])` where `sec` is a string
instead of a dict.

This means:
- No video file is produced
- `publish_video()` is never called
- `youtube_video_id` is never written
- The GHA workflow exits with code 0 because `run_feedback_loop()` always
  returns `status="completed"` regardless of individual step results

**The editing agent crash is the root cause of the missing upload — not the
daily cap, not the circuit breaker, not the health gate, not the confidence
gate, and not the OAuth credentials.**

---

## All `auto_publish=False` / `skip_publish` / `dry_run` / `test_mode` / `simulate` / `mock` Occurrences

| Pattern | Occurrences | In Production Path? |
|---|---|---|
| `auto_publish` | 4 hits in `decision_executor.py` | ✅ Parameter to `execute_top_decision()` — always `True` from daily job |
| `skip_publish` | 0 hits | ❌ Not found anywhere |
| `dry[_ ]run` | 2 hits in `PH21_3_PRODUCTION_VALIDATOR.py` | ❌ Validation script, not production |
| `test[_ ]mode` | 0 hits in `mindmargin/` | ❌ Not found |
| `simulate` | 0 hits in `mindmargin/` | ❌ Not found |
| `mock` | Only in `tests/` and `validate_*.py` | ❌ Test files only |
| `publish=False` | Only in test mock configs | ❌ Test files only |
| `upload=False` | 0 hits | ❌ Not found |
