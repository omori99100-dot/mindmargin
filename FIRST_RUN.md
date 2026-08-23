# MindMargin — First Run Guide

What happens when MindMargin runs for the first time.

---

## First Run Overview

When you trigger the first daily job, the pipeline executes this sequence:

```
1. Environment Setup
   ├── Install Python dependencies
   ├── Install FFmpeg (system)
   ├── Install Ollama + pull qwen2.5:0.5b model
   ├── Install Piper TTS + voice model
   └── Create output directories

2. Secret Restoration
   ├── Decode YouTube token from YOUTUBE_TOKEN_B64
   ├── Write .env file from ENV_FILE
   └── Write client_secrets.json from CLIENT_SECRETS

3. Database Initialization
   ├── Create data/mindmargin.db
   └── Seed with existing YouTube videos (if any)

4. Pipeline Execution
   ├── Analytics Collection (fetches stats for existing videos)
   ├── Pattern Analysis (learns from existing content)
   ├── A/B Rotation (tests title variants)
   ├── Selection Pressure (classifies video performance)
   ├── Decision Executor
   │   ├── Channel Brain (health assessment)
   │   ├── Growth Engine (opportunity analysis)
   │   ├── Topic Selection (picks best topic)
   │   ├── Pipeline (research → script → voice → video)
   │   └── Upload (publishes to YouTube)
   └── Execution Logging (records everything)

5. Cache Save
   └── Persist database for next run
```

---

## Expected Duration

| Phase | Duration |
|-------|----------|
| Environment setup | 2-5 minutes |
| Secret restoration | <1 second |
| Database initialization | <1 second |
| Analytics collection | 1-2 minutes |
| Pattern analysis | <1 second |
| A/B rotation | 30-60 seconds |
| Decision executor | 1-2 minutes |
| Pipeline execution | 5-10 minutes |
| YouTube upload | 1-2 minutes |
| **Total** | **10-20 minutes** |

---

## First Run Behavior

### If Database Is Empty
- No analytics to collect (skipped)
- No patterns to analyze (skipped)
- No A/B tests to rotate (skipped)
- Decision executor runs in **bootstrap mode** (confidence gate bypassed)
- Pipeline runs with fallback topic ("business failure")
- Video uploaded to YouTube

### If Database Has Existing Videos
- Analytics collected for all published videos
- Patterns learned from existing content
- A/B tests rotated
- Decision executor selects best topic from intelligence engine
- Pipeline runs with selected topic
- Video uploaded to YouTube

---

## Verifying First Run

### Check Workflow Logs

1. Go to **Actions** → **MindMargin Daily Job** → latest run
2. Look for these success indicators:

```
✅ All required secrets validated
✅ Database seed completed
✅ Analytics collection: N videos, 0 errors
✅ Channel Brain cycle complete: health=X.X/10
✅ Selected topic: '...'
✅ Pipeline completed
✅ Upload complete: https://youtu.be/...
```

### Check YouTube Channel

1. Go to your YouTube channel
2. Look for a new video (may be "private" or "unlisted")
3. Verify the video plays correctly

### Check Database

```bash
# List recent executions
python -c "
import sqlite3
conn = sqlite3.connect('data/mindmargin.db')
conn.row_factory = sqlite3.Row
for row in conn.execute('SELECT * FROM execution_log ORDER BY executed_at DESC LIMIT 5'):
    print(dict(row))
"
```

---

## Common First Run Issues

### "MISSING SECRET" Error
**Cause:** GitHub Secrets not configured.
**Fix:** Follow GITHUB_SETUP.md to configure all required secrets.

### "YouTube auth failed" Error
**Cause:** Token expired or client_secrets.json invalid.
**Fix:** Regenerate token locally and update GitHub Secrets.

### "No final MP4 found" Error
**Cause:** Video rendering failed (FFmpeg issue).
**Fix:** Check FFmpeg installation. Look for FFmpeg errors in logs.

### Pipeline Times Out
**Cause:** Video rendering takes too long.
**Fix:** Increase `timeout-minutes` in daily_job.yml (default: 45).

### Ollama Connection Refused
**Cause:** Ollama not running or wrong URL.
**Fix:** Ensure Ollama is running: `curl http://localhost:11434/api/tags`

---

## After First Run

Once the first run completes successfully:

1. **Monitor** the next 2-3 runs for consistency
2. **Review** the uploaded video on YouTube
3. **Check** Telegram notifications (if configured)
4. **Adjust** topic selection if needed (edit `_TOPIC_DOMAINS` in decision_executor.py)
5. **Set** video privacy to "public" when ready (edit `.env` → `YOUTUBE_DEFAULT_PRIVACY=public`)

---

## Local First Run (Without GitHub Actions)

To test locally before pushing to GitHub:

```bash
# 1. Configure environment
cp .env.example .env
# Edit .env with your settings

# 2. Check YouTube auth
python -m mindmargin.main --check-auth

# 3. Run daily job locally
python -m mindmargin.main --run-daily-job

# 4. Or run a quick test pipeline
python -m mindmargin.main --topic "Test Topic" --quick --publish
```

---

## What Gets Published

By default, videos are uploaded as **private**. To change this:

1. Edit `.env`: `YOUTUBE_DEFAULT_PRIVACY=unlisted` or `public`
2. Or change in `config/settings.yaml`: `default_privacy: public`

**Recommended approach:** Start with `private`, verify the video looks good, then change to `public`.
