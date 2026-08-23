# Upload Forensic Trace

## Execution Timeline

### Entry Point
```
main.py:694  --run-daily-job
  → jobs/daily_analytics.py:225  run_daily_job()
    → jobs/daily_analytics.py:228  run_feedback_loop()
      → jobs/daily_analytics.py:122  execute_top_decision(auto_publish=True)
```

### Decision Tree — all paths that prevent `publish_video()` from being called

```
execute_top_decision(auto_publish=True)      [decision_executor.py:392]
│
├─ Circuit Breaker Check                     [decision_executor.py:417]
│  └─ if _check_circuit_breaker() → True:
│       return {"status": "disabled", ...}   ← PUBLISH STOPPED HERE
│       (pipeline never runs)
│
├─ Topic Selection                           [decision_executor.py:460]
│  └─ if not topic:
│       return {"status": "failed", "error": "No topic"}  ← STOP
│
├─ Confidence Gate                           [decision_executor.py:483]
│  └─ if decision_confidence < MIN_CONFIDENCE:
│       return {"status": "skipped", ...}    ← STOP
│       (pipeline never runs)
│
├─ Pipeline Execution                        [decision_executor.py:512-536]
│  ├─ Exception → return {"status": "failed"}  ← STOP [LINE 521-529]
│  └─ if pipeline_status != "completed":
│       return {"status": "failed"}          ← STOP [LINE 531-536]
│       *** THIS IS THE MOST LIKELY STOP POINT ***
│       (pipeline crashed, no video produced)
│
└─ Publishing Stage                          [decision_executor.py:541-591]
   │
   ├─ if not auto_publish:                   ← always True from daily job
   │    pub_status stays "skipped"           ← STOP
   │
   ├─ Channel Health Gate                    [decision_executor.py:546-549]
   │  └─ if blocked:
   │       cycle["steps"]["publish"] = {"status": "blocked"}  ← STOP
   │       (publish_video() never called)
   │
   ├─ Daily Publish Cap                      [decision_executor.py:553-556]
   │  └─ if blocked:
   │       cycle["steps"]["publish"] = {"status": "blocked"}  ← STOP
   │       (publish_video() never called)
   │
   └─ publish_video(topic, pipeline_id, ...) [decision_executor.py:110]
      │                                     ← CALLED ONLY IF ALL GATES PASS
      │
      ├─ check_credentials()                [client.py:170]
      │  ├─ google libs missing?            → return {error}
      │  ├─ client_secrets not found?       → return {error}
      │  ├─ token not found/expired?        → return {error}
      │  └─ API call fails?                 → return {error}
      │
      ├─ Duplicate protection               [decision_executor.py:135]
      │  └─ if already published → return existing video_id
      │
      ├─ Output dir exists?                 [decision_executor.py:156]
      │  └─ if not → return {error: "Output directory not found"}
      │
      ├─ script.json exists?                [decision_executor.py:159]
      │  └─ if not → return {error: "script.json not found"}
      │
      ├─ Video file exists?                 [decision_executor.py:186]
      │  └─ if no *final.mp4 → return {error: "No final MP4 found"}
      │    *** ALSO LIKELY — if editing fails silently ***
      │
      ├─ upload_video(video_path, ...)      [client.py:205]
      │  ├─ service not available?          → return {error}
      │  ├─ video file missing?             → return {error}
      │  ├─ YouTube API returns 400/401/403 → return {error} (no retry)
      │  ├─ YouTube API returns 5xx/429     → retry up to 3×
      │  ├─ Exception during upload         → retry up to 3×
      │  └─ SUCCESS: returns {video_id, url} → YouTube video CREATED ✓
      │
      └─ On success: save_pipeline() writes
         youtube_video_id to pipelines table [decision_executor.py:210-217]
```

---

## Critical Finding: `publish_video()` is LIKELY NEVER CALLED

The most probable stop point is at **`decision_executor.py:531-536`** because the
pipeline's editing stage crashes with:

```
AttributeError: 'str' object has no attribute 'get'
```

This was reproduced locally. The editing agent receives `sections` containing a
non-dict element, causing the crash when calling `sec.get("scene_plan", [])`
at `editing.py:127`. Since `pipeline_status != "completed"`, the code returns
at line 534 before ever reaching the publish stage.

### Evidence from local run

```
Pipeline output:
  [ok]  research completed
  [ok]  script completed  (Quality gate: PASSED, 4773 words)
  [cache] voice script unchanged, skipping voice generation
  [FAIL] editing: 'str' object has no attribute 'get'

execute_top_decision returned:
  status:      failed
  pipeline_status: None
  publish_status: None
  video_id:    None
```

### Why GHA exits with code 0 despite the crash

```
run_feedback_loop() at line 126:
  try:
      exec_result = execute_top_decision(auto_publish=True)  # returns {"status":"failed"}
  except Exception as e:
      logger.warning(f"Decision executor failed: {e}")  # NOT triggered (no exception)
      exec_result = {"status": "failed", "error": str(e)}

  result = {
      "status": "completed",  # ← ALWAYS "completed" regardless of step 6 result
      ...
  }
```

The daily job ALWAYS returns `{"status": "completed"}`. The GHA workflow runs
`python -m mindmargin.main --run-daily-job` — if no unhandled exception
propagates, exit code is 0, and the workflow reports "success". The user sees
"Workflow completed successfully" but no video was ever uploaded.

---

## All Conditions That Can Prevent `publish_video()` — Complete Table

| Condition | File:Line | Value | Can Silent Skip? |
|---|---|---|---|
| Circuit breaker tripped | `decision_executor.py:418` | `_check_circuit_breaker()` | No — logs critical error |
| No topic selected | `decision_executor.py:461` | `topic = ""` | No — logs error |
| Confidence too low | `decision_executor.py:485` | `confidence < 0.50` | No — logs warning |
| Pipeline exception | `decision_executor.py:521` | `Exception raised` | No — logs error |
| Pipeline not completed | `decision_executor.py:531` | `status != "completed"` | No — logs in run_feedback_loop |
| auto_publish=False | `decision_executor.py:545` | `auto_publish is True` | N/A — always True |
| Health gate blocked | `decision_executor.py:549` | `health < 4.0` and total_videos >= 4 | No — logs warning |
| Daily cap reached | `decision_executor.py:556` | `is_successful_publish` count >= 1 | No — logs warning |
| YouTube auth failed | `decision_executor.py:124-132` | `not creds.get("authenticated")` | No — logs error |
| Duplicate detected | `decision_executor.py:135-151` | `youtube_video_id != ''` in DB | Returns "completed" with existing video_id |
| Output dir missing | `decision_executor.py:156` | `not out_dir.exists()` | No — logs error |
| script.json missing | `decision_executor.py:159` | `not script_path.exists()` | No — logs error |
| No final MP4 found | `decision_executor.py:186` | `no video/*_final.mp4` | No — logs error |
| YouTube API error | `client.py:283-308` | HTTP 400/401/403/5xx | No — logs error |
| YouTube API exception | `client.py:310-321` | Network/other error | No — logs error |

---

## Simulation / Test Mode / Dry Run Search Results

Searched entire repository for every occurrence of:
- `auto_publish` — only in `decision_executor.py` (function param = True)
- `skip_publish` — NOT FOUND anywhere
- `dry_run` — NOT FOUND in production code (only in validate scripts)
- `test_mode` — NOT FOUND in production code
- `simulate` — NOT FOUND in production code (only in validate scripts)
- `mock` — only in test files (`tests/`) and validate scripts
- `publish=False` — only in test mock calls
- `upload=False` — NOT FOUND

**No simulation, dry-run, test-mode, or mock paths exist in production code.**

---

## OAuth Credentials in GHA

The GHA workflow correctly:
1. Validates secrets: `YOUTUBE_TOKEN_B64`, `ENV_FILE`, `CLIENT_SECRETS`
2. Restores them: `base64 -d > youtube_token.pickle`, writes `.env` and `client_secrets.json`
3. Writes to the project root, which `_find_client_secrets()` and `_find_token()` search

The `_get_authenticated_service()` function (`client.py:87-146`):
- Searches CWD → `settings.storage.output_root + ../` → `~/.mindmargin/`
- In GHA, CWD is the checkout directory where secrets were restored
- Tokens that expire are refreshed automatically (line 112)
- Only on first run (no cached token) would OAuth be needed (not possible in GHA — `flow.run_local_server(port=8080)` would hang)

**Conclusion**: OAuth is correctly configured for GHA. If `publish_video()` were
reached, the upload would use valid credentials.

---

## Answer: Exact Line Where Upload Stops

The upload process stops at **`decision_executor.py:531-536`** because the
pipeline's editing stage crashes (`editing.py:127`), producing
`pipeline_status != "completed"`. `publish_video()` on line 110 is **never
called**.

The editing crash is the blocker. The daily cap, confidence gate, circuit
breaker, and health gate fixes are all verified correct — they are not
preventing the upload.
