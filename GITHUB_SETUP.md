# MindMargin — GitHub Setup Guide

Complete instructions to configure MindMargin for autonomous YouTube publishing via GitHub Actions.

---

## Prerequisites

- GitHub account with repository access
- Google Cloud Console project with YouTube Data API v3 enabled
- Python 3.11+ (for local testing only)

---

## Step 1: YouTube OAuth Setup

### 1.1 Create Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project (or select existing)
3. Go to **APIs & Services > Library**
4. Search for **YouTube Data API v3** and enable it
5. Go to **APIs & Services > OAuth consent screen**
6. Select **External** user type
7. Fill in app name: `MindMargin`
8. Add scopes: `youtube.upload`, `youtube`, `youtube.force-ssl`, `youtube.readonly`, `yt-analytics.readonly`
9. Add your Google account as a test user

### 1.2 Create OAuth Credentials

1. Go to **APIs & Services > Credentials**
2. Click **Create Credentials > OAuth client ID**
3. Application type: **Desktop app**
4. Name: `MindMargin`
5. Click **Create**
6. Download the JSON file
7. Rename it to `client_secrets.json`

### 1.3 Generate Token (First Time)

Run locally to generate the token pickle:

```bash
pip install -r requirements.txt
python -c "
from mindmargin.integrations.youtube.client import _get_authenticated_service
svc = _get_authenticated_service()
print('Authentication successful!' if svc else 'Authentication failed')
"
```

This opens a browser for OAuth consent. After approval, `youtube_token.pickle` is saved.

### 1.4 Encode Token for GitHub Secrets

```bash
# Linux/macOS
base64 -w0 youtube_token.pickle

# Windows PowerShell
[Convert]::ToBase64String([IO.File]::ReadAllBytes("youtube_token.pickle"))
```

---

## Step 2: Configure GitHub Secrets

Go to your repository → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**

### Required Secrets

| Secret Name | How to Get |
|-------------|------------|
| `YOUTUBE_TOKEN_B64` | Output from base64 encoding of `youtube_token.pickle` |
| `ENV_FILE` | Contents of your `.env` file (see below) |
| `CLIENT_SECRETS` | Contents of `client_secrets.json` |

### Optional Secrets

| Secret Name | Purpose |
|-------------|---------|
| `TELEGRAM_BOT_TOKEN` | Telegram bot token for failure notifications |
| `TELEGRAM_CHAT_ID` | Telegram chat ID for notifications |

### Creating the ENV_FILE Secret

Create a `.env` file with these contents, then paste the entire file as the `ENV_FILE` secret:

```env
OLLAMA_BASE_URL=http://localhost:11434
LLM_MODEL=qwen2.5:0.5b
YOUTUBE_CLIENT_SECRETS_PATH=client_secrets.json
YOUTUBE_TOKEN_PATH=youtube_token.pickle
YOUTUBE_DEFAULT_PRIVACY=private
ENVIRONMENT=production
LOG_LEVEL=INFO
DEBUG=false
```

---

## Step 3: Enable GitHub Actions

1. Go to your repository → **Actions** tab
2. Click **I understand my workflows, go ahead and enable them**
3. Ensure the **MindMargin Daily Job** workflow is enabled

---

## Step 4: Configure Workflow Permissions

1. Go to **Settings** → **Actions** → **General**
2. Under **Workflow permissions**, select **Read and write permissions**
3. Check **Allow GitHub Actions to create and approve pull requests**
4. Click **Save**

---

## Step 5: Verify Setup

### 5.1 Check Secrets

Go to **Settings** → **Secrets and variables** → **Actions** and verify:

- [ ] `YOUTUBE_TOKEN_B64` exists
- [ ] `ENV_FILE` exists
- [ ] `CLIENT_SECRETS` exists

### 5.2 Trigger Manual Run

1. Go to **Actions** → **MindMargin Daily Job**
2. Click **Run workflow**
3. Click the green **Run workflow** button
4. Watch the workflow run — it should pass all validation steps

### 5.3 Verify YouTube Upload

After the workflow completes:
1. Check your YouTube channel for a new video
2. Check the workflow logs for `Upload complete: https://youtu.be/...`

---

## Step 6: Schedule Configuration

The daily job runs automatically at **9:00 PM UTC** every day. To change the schedule:

1. Edit `.github/workflows/daily_job.yml`
2. Find `cron: "0 21 * * *"`
3. Modify the cron expression:
   - `0 21 * * *` = Daily at 9 PM UTC
   - `0 9,21 * * *` = Twice daily at 9 AM and 9 PM UTC
   - `0 21 * * 1-5` = Weekdays only at 9 PM UTC

---

## Required Secrets Summary

| Secret | Required | Source |
|--------|----------|--------|
| `YOUTUBE_TOKEN_B64` | ✅ Yes | `base64 -w0 youtube_token.pickle` |
| `ENV_FILE` | ✅ Yes | Contents of `.env` file |
| `CLIENT_SECRETS` | ✅ Yes | Contents of `client_secrets.json` |
| `TELEGRAM_BOT_TOKEN` | Optional | Telegram bot for notifications |
| `TELEGRAM_CHAT_ID` | Optional | Telegram chat for notifications |

---

## Troubleshooting

See `TROUBLESHOOTING.md` for common issues and fixes.

If the workflow fails with "MISSING SECRET" errors, verify all three required secrets are configured in GitHub Actions settings.
