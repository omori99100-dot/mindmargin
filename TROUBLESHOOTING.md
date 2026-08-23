# MindMargin — Troubleshooting Guide

Common issues and their solutions.

---

## Quick Diagnostics

Run these commands to check system status:

```bash
# Check YouTube auth
python -m mindmargin.main --check-auth

# Check channel status
python -m mindmargin.main --channel-status

# Check executive agent status
python -m mindmargin.main --executive-status

# Check Ollama
curl http://localhost:11434/api/tags

# Check FFmpeg
ffmpeg -version

# Check Piper
piper --version
```

---

## GitHub Actions Issues

### "MISSING SECRET: YOUTUBE_TOKEN_B64"

**Cause:** The `YOUTUBE_TOKEN_B64` secret is not configured.

**Fix:**
1. Generate token: `base64 -w0 youtube_token.pickle`
2. Go to repo → Settings → Secrets → Actions
3. Add secret named `YOUTUBE_TOKEN_B64` with the base64 output

---

### "MISSING SECRET: CLIENT_SECRETS"

**Cause:** The `CLIENT_SECRETS` secret is not configured.

**Fix:**
1. Download `client_secrets.json` from Google Cloud Console
2. Go to repo → Settings → Secrets → Actions
3. Add secret named `CLIENT_SECRETS` with the file contents

---

### "YouTube auth failed: No client_secrets.json found"

**Cause:** Token or client secrets file missing or corrupted.

**Fix:**
1. Regenerate token locally:
   ```bash
   python -c "from mindmargin.integrations.youtube.client import _get_authenticated_service; _get_authenticated_service()"
   ```
2. Re-encode: `base64 -w0 youtube_token.pickle`
3. Update `YOUTUBE_TOKEN_B64` GitHub Secret

---

### Workflow Runs But No Video Uploaded

**Cause:** Pipeline completed but upload was skipped (health gate, daily cap, or circuit breaker).

**Fix:**
1. Check logs for "Channel health gate" or "Daily publish cap"
2. Check circuit breaker: look for "CIRCUIT BREAKER TRIPPED" in logs
3. If circuit breaker tripped, fix the underlying issue and reset

---

### Workflow Times Out

**Cause:** Video rendering takes longer than the timeout.

**Fix:**
1. Increase timeout in `.github/workflows/daily_job.yml`:
   ```yaml
   timeout-minutes: 60  # or 90
   ```
2. Or use `--quick` flag for faster (lower quality) rendering

---

## YouTube Upload Issues

### "Upload failed after 3 attempts"

**Cause:** Transient network error or YouTube API issue.

**Fix:**
- The system now retries with exponential backoff (3 attempts)
- If persistent, check YouTube API status: https://status.cloud.google.com/
- Verify quota not exceeded: check YouTube API console

---

### "HTTP 403: The request cannot be completed"

**Cause:** YouTube API quota exceeded or permissions issue.

**Fix:**
1. Check quota: [YouTube API Console](https://console.developers.google.com/apis/api/youtube.googleapis.com/quotas)
2. Wait for quota reset (daily at midnight Pacific Time)
3. Or request quota increase from Google

---

### "HTTP 401: Login Required"

**Cause:** OAuth token expired.

**Fix:**
1. Regenerate token locally
2. Update `YOUTUBE_TOKEN_B64` GitHub Secret
3. Re-run the workflow

---

### Thumbnail Upload Fails Silently

**Cause:** Thumbnail file not found or format invalid.

**Fix:**
- Check that thumbnail PNG files exist in the output directory
- Ensure thumbnails are valid PNG format
- This is non-blocking — video uploads without thumbnail

---

## Pipeline Issues

### "No final MP4 found"

**Cause:** Video rendering failed.

**Fix:**
1. Check FFmpeg is installed: `ffmpeg -version`
2. Check available disk space
3. Look for FFmpeg errors in logs
4. Try running pipeline locally with `--topic "test" --quick`

---

### "Pipeline failed: LLM provider not available"

**Cause:** Ollama not running or model not pulled.

**Fix:**
1. Start Ollama: `ollama serve`
2. Pull model: `ollama pull qwen2.5:0.5b`
3. Verify: `curl http://localhost:11434/api/tags`

---

### "Circuit breaker tripped"

**Cause:** 3 consecutive pipeline failures detected.

**Fix:**
1. Check execution logs for the root cause
2. Fix the underlying issue
3. Reset in Python:
   ```python
   from mindmargin.agents.decision_executor import reset_circuit_breaker
   reset_circuit_breaker()
   ```

---

### Pipeline Produces Silent Video

**Cause:** Piper TTS failed to generate audio.

**Fix:**
- Check Piper installation: `piper --version`
- Check voice model exists
- This is expected behavior — pipeline continues with silent audio as fallback

---

## Database Issues

### "database is locked"

**Cause:** Multiple processes accessing SQLite simultaneously.

**Fix:**
1. Ensure only one worker is running
2. Stop any other MindMargin instances
3. Wait a few seconds and retry

---

### Database Corruption

**Cause:** Unexpected shutdown during write.

**Fix:**
1. Stop the worker
2. Restore from backup
3. Or delete and re-seed:
   ```bash
   rm data/mindmargin.db
   python scripts/seed_db.py
   ```

---

## Configuration Issues

### "No Ollama connection"

**Cause:** Ollama not running or wrong URL.

**Fix:**
1. Check Ollama: `curl http://localhost:11434/api/tags`
2. Verify URL in `.env`: `OLLAMA_BASE_URL=http://localhost:11434`
3. Start Ollama if needed: `ollama serve`

---

### "FFmpeg not found"

**Cause:** FFmpeg not installed or not on PATH.

**Fix:**
1. Install FFmpeg: `sudo apt install ffmpeg` (Linux) or download from ffmpeg.org
2. Or set path in `config/settings.yaml`

---

### Unicode/Encoding Errors on Windows

**Cause:** Windows console encoding issues.

**Fix:**
1. Set environment variable: `PYTHONIOENCODING=utf-8`
2. Or run in PowerShell with: `$env:PYTHONIOENCODING="utf-8"`

---

## Performance Issues

### Slow Video Rendering

**Cause:** Software encoding or low CPU.

**Fix:**
- System automatically detects and uses hardware encoding (QSV, NVENC, AMF)
- Check logs for "Encoder available" to confirm HW encoding
- Reduce video quality: edit `config/settings.yaml` → `crf: 28` (higher = lower quality)

---

### Low LLM Quality

**Cause:** Using small model (qwen2.5:0.5b).

**Fix:**
- Pull a larger model: `ollama pull qwen2.5:7b`
- Update `.env`: `LLM_MODEL=qwen2.5:7b`
- Note: larger models are slower but produce better scripts

---

## Getting Help

1. Check logs: `output/pipeline.log`
2. Check errors: `output/errors.log`
3. Run diagnostics: `python -m mindmargin.main --check-auth`
4. Check GitHub Actions logs for workflow-specific issues
