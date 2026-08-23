# MindMargin — YouTube Integration Audit

**Date:** 2026-07-03
**Status:** ✅ OPERATIONAL

---

## OAuth Authentication

| Item | Status | Details |
|------|--------|---------|
| Client Secrets | ✅ Present | `client_secrets.json` (Google OAuth client ID) |
| Token File | ✅ Present | `youtube_token.pickle` |
| Authenticated | ✅ Yes | Channel: "Omar Mohamed" |
| Scopes | ✅ 5 scopes | youtube.upload, youtube, youtube.force-ssl, youtube.readonly, yt-analytics.readonly |
| Auto-refresh | ✅ Working | Refreshes on every API call if expired |

### Token Refresh Flow
1. Load pickle from `_find_token()` (searches CWD, output root, ~/.mindmargin/)
2. If expired + has refresh_token → `credentials.refresh(Request())`
3. Save updated pickle
4. On failure → falls through to full re-auth (requires browser)

---

## Video Upload Flow

### Step-by-Step
1. **Duplicate check** — queries SQLite for existing `youtube_video_id` on `pipeline_id`
2. **Auth check** — `check_credentials()` verifies authenticated state
3. **Thumbnail generation** — ThumbnailAgent produces 4 base styles + title variants via FFmpeg
4. **Metadata generation** — MetadataAgent produces title (≤100 chars), description (≤5000 chars), tags (≤500), category=27 (Education)
5. **Upload** — chunked resumable upload via `MediaFileUpload` (1MB chunks)
6. **Thumbnail upload** — `thumbnails().set()` API call
7. **Playlist add** — `playlistItems().insert()` for topic-based playlists
8. **DB save** — records `youtube_video_id`, `youtube_url` in pipelines table
9. **A/B seeding** — creates title/thumbnail variants for testing

### API Endpoints Called

| Function | Endpoint | Quota Cost |
|----------|----------|------------|
| `upload_video` | `videos().insert` | 1,600 |
| `_upload_thumbnail` | `thumbnails().set` | 50 |
| `_add_to_playlist` | `playlistItems().insert` | 50 |
| `update_video_metadata` | `videos().update` | 50 |
| `get_video_stats` | `videos().list` | 1 |
| `list_playlists` | `playlists().list` | 1 |
| `check_credentials` | `channels().list` | 1 |
| `post_comment` | `commentThreads().insert` | 50 |
| `pin_comment` | `commentThreads().update` | 50 |

**Total cost per full publish cycle:** ~1,850 units

---

## Quota Management

| Metric | Value |
|--------|-------|
| Daily limit | 10,000 units |
| Max uploads/day | 50 |
| Cost per upload | 1,600 units |
| Max uploads at quota | 6/day |
| Actual daily cap | 1 (enforced by decision_executor) |

---

## Playlist Management

4 topic-based playlists are auto-created:
1. "Financial Fraud & Scams"
2. "Tech Giants That Fell"
3. "Financial Collapses & Crashes"
4. "Corporate Downfalls"

Videos are matched to playlists by topic keyword scoring.

---

## Error Handling

| Scenario | Behavior |
|----------|----------|
| Upload fails | Returns `{"status": "failed", "error": "..."}`, logged, no retry |
| Thumbnail fails | Silent warning, continues |
| Playlist fails | Silent warning, continues |
| Comment fails | Logged as info, continues |
| Auth fails | Falls through to full re-auth flow |
| Circuit breaker | 3 consecutive failures → halts all publishing |

---

## Issues Found

1. **No upload retry** — `upload_retries: 3` config exists but is never used
2. **Thumbnail upload has no retry** — silently swallowed
3. **Quota tracking is optimistic** — doesn't account for failed API calls that still consume quota
4. **Client secret on disk** — security risk if repo is compromised
5. **Hardcoded email** in auth scripts: `oo607820@gmail.com`
6. **OAuth scopes mismatch** — `auth.py` requests 4 scopes, `client.py` requests 5

---

## Recommendation

The YouTube integration is fully functional. The only critical gap is the lack of upload retry logic. Consider implementing retry with exponential backoff for transient network errors during the upload phase.
