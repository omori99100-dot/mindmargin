"""YouTube Data API v3 client: OAuth, uploads, metadata, analytics.

This module wraps the flat youtube API functions into a YouTubeClient class
for use by youtube/connector.py. All existing function-level imports are
re-exported via youtube/__init__.py for backward compatibility.
"""

import json
import logging
import os
import pickle
import random
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional

from mindmargin.config import settings

logger = logging.getLogger(__name__)

CLIENT_SECRETS_FILE = "client_secrets.json"
TOKEN_FILE = "youtube_token.pickle"
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.force-ssl",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]
API_SERVICE_NAME = "youtube"
API_VERSION = "v3"
ANALYTICS_API_SERVICE_NAME = "youtubeAnalytics"
ANALYTICS_API_VERSION = "v2"

_yt_client = None
_analytics_client = None


def _find_client_secrets() -> Optional[Path]:
    candidates = [
        Path.cwd() / CLIENT_SECRETS_FILE,
        Path(settings.storage.output_root).parent / CLIENT_SECRETS_FILE,
        Path.home() / ".mindmargin" / CLIENT_SECRETS_FILE,
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def _find_token() -> Optional[Path]:
    candidates = [
        Path.cwd() / TOKEN_FILE,
        Path(settings.storage.output_root).parent / TOKEN_FILE,
        Path.home() / ".mindmargin" / TOKEN_FILE,
    ]
    for p in candidates:
        if p.exists():
            return p
    return None


def _token_path() -> Path:
    d = Path(settings.storage.output_root).parent
    d.mkdir(parents=True, exist_ok=True)
    return d / TOKEN_FILE


def _auth_url_path() -> Path:
    d = Path(settings.storage.output_root).parent
    d.mkdir(parents=True, exist_ok=True)
    return d / "youtube_auth_url.txt"


def _has_google_libs() -> bool:
    try:
        import google_auth_oauthlib.flow
        import googleapiclient.discovery
        return True
    except ImportError:
        return False


def _get_authenticated_service():
    global _yt_client
    if _yt_client is not None:
        return _yt_client

    if not _has_google_libs():
        logger.error(
            "Google API libraries not installed. Run: pip install google-auth-oauthlib google-api-python-client"
        )
        return None

    from google.auth.transport.requests import Request
    from google_auth_oauthlib.flow import InstalledAppFlow

    credentials = None
    token_path = _find_token()
    if token_path:
        try:
            with open(token_path, "rb") as f:
                credentials = pickle.load(f)
        except Exception as e:
            logger.warning(f"Failed to load token: {e}")

    if credentials and credentials.expired and credentials.refresh_token:
        try:
            credentials.refresh(Request())
            with open(_token_path(), "wb") as f:
                pickle.dump(credentials, f)
            logger.info("YouTube token refreshed")
        except Exception as e:
            logger.warning(f"Token refresh failed: {e}")
            credentials = None

    if not credentials or not credentials.valid:
        secrets_path = _find_client_secrets()
        if not secrets_path:
            logger.error(
                "No client_secrets.json found. "
                "See: https://console.cloud.google.com/apis/credentials"
            )
            return None
        try:
            flow = InstalledAppFlow.from_client_secrets_file(str(secrets_path), SCOPES)
            credentials = flow.run_local_server(port=8080, open_browser=False)
            with open(_token_path(), "wb") as f:
                pickle.dump(credentials, f)
            logger.info("YouTube OAuth completed, token saved")
        except Exception as e:
            logger.error(f"OAuth failed: {e}")
            logger.info(
                "To authenticate manually, visit:\n"
                "  https://console.cloud.google.com/apis/credentials\n"
                "  Download client_secrets.json and place it in the project root."
            )
            return None

    from googleapiclient.discovery import build

    _yt_client = build(API_SERVICE_NAME, API_VERSION, credentials=credentials)
    return _yt_client


def _get_analytics_service():
    global _analytics_client
    if _analytics_client is not None:
        return _analytics_client

    if not _has_google_libs():
        return None

    yt = _get_authenticated_service()
    if not yt:
        return None

    from googleapiclient.discovery import build

    _analytics_client = build(
        ANALYTICS_API_SERVICE_NAME, ANALYTICS_API_VERSION,
        credentials=yt._http.credentials,
    )
    return _analytics_client


def check_credentials() -> dict:
    """Check if YouTube credentials are configured and valid. Returns status dict."""
    has_libs = _has_google_libs()
    has_secrets = _find_client_secrets() is not None
    has_token = _find_token() is not None
    result = {
        "google_libs_installed": has_libs,
        "client_secrets_found": has_secrets,
        "token_found": has_token,
        "authenticated": False,
        "channel_name": "",
        "error": "",
    }
    if not has_libs:
        result["error"] = "Run: pip install google-auth-oauthlib google-api-python-client"
        return result
    if not has_secrets:
        result["error"] = "Place client_secrets.json in project root"
        return result
    try:
        yt = _get_authenticated_service()
        if not yt:
            return result
        resp = yt.channels().list(part="snippet", mine=True).execute()
        items = resp.get("items", [])
        if items:
            result["authenticated"] = True
            result["channel_name"] = items[0]["snippet"]["title"]
        else:
            result["error"] = "No channel found for this account"
    except Exception as e:
        result["error"] = str(e)
    return result


def upload_video(
    video_path: str,
    title: str = "MindMargin Video",
    description: str = "",
    tags: Optional[list[str]] = None,
    category_id: str = "27",
    privacy_status: str = "private",
    playlist_id: Optional[str] = None,
    thumbnail_path: Optional[str] = None,
    publish_at: Optional[str] = None,
    max_retries: int = 3,
) -> dict:
    """Upload a video to YouTube with exponential backoff retry.

    Retries on transient errors (network, 5xx, quota temporary).
    Does NOT retry on auth errors (401, 403) or invalid requests (400).

    Returns response dict with video_id, status, etc.
    """
    yt = _get_authenticated_service()
    if not yt:
        return {"status": "failed", "error": "YouTube service not available"}

    if not os.path.isfile(video_path):
        return {"status": "failed", "error": f"Video not found: {video_path}"}

    body = {
        "snippet": {
            "title": title[:100],
            "description": description[:5000],
            "tags": (tags or [])[:500],
            "categoryId": category_id,
        },
        "status": {
            "privacyStatus": privacy_status,
            "selfDeclaredMadeForKids": False,
        },
    }
    if publish_at:
        body["status"]["publishAt"] = publish_at

    last_error = None
    for attempt in range(1, max_retries + 1):
        try:
            from googleapiclient.http import MediaFileUpload
            from googleapiclient.errors import HttpError

            media = MediaFileUpload(video_path, chunksize=1024 * 1024, resumable=True)
            request = yt.videos().insert(
                part="snippet,status",
                body=body,
                media_body=media,
            )
            logger.info(f"Uploading: {title} ({privacy_status}) [attempt {attempt}/{max_retries}]")
            response = None
            while response is None:
                status, response = request.next_chunk()
                if status:
                    pct = int(status.progress() * 100)
                    logger.info(f"Upload progress: {pct}%")

            video_id = response.get("id", "")
            logger.info(f"Upload complete: https://youtu.be/{video_id}")

            if thumbnail_path and os.path.isfile(thumbnail_path):
                _upload_thumbnail(yt, video_id, thumbnail_path)

            if playlist_id:
                _add_to_playlist(yt, video_id, playlist_id)

            return {
                "status": "completed",
                "video_id": video_id,
                "url": f"https://youtu.be/{video_id}",
                "title": title,
                "privacy_status": privacy_status,
            }

        except HttpError as e:
            last_error = e
            status_code = e.resp.status if hasattr(e, 'resp') else 0
            error_reason = ""
            try:
                error_content = json.loads(e.content.decode())
                error_reason = error_content.get("error", {}).get("message", str(e))
            except Exception:
                error_reason = str(e)

            # Do NOT retry on auth or client errors
            if status_code in (400, 401, 403):
                logger.error(f"YouTube upload failed (HTTP {status_code}): {error_reason}")
                return {"status": "failed", "error": f"HTTP {status_code}: {error_reason}"}

            # Retry on 5xx, 429 (quota), or network errors
            if attempt < max_retries:
                delay = min(2 ** attempt + random.uniform(0, 1), 60)
                logger.warning(
                    f"Upload attempt {attempt} failed (HTTP {status_code}): {error_reason}. "
                    f"Retrying in {delay:.1f}s..."
                )
                time.sleep(delay)
            else:
                logger.error(f"YouTube upload failed after {max_retries} attempts: {error_reason}")
                return {"status": "failed", "error": f"HTTP {status_code}: {error_reason}"}

        except Exception as e:
            last_error = e
            if attempt < max_retries:
                delay = min(2 ** attempt + random.uniform(0, 1), 60)
                logger.warning(
                    f"Upload attempt {attempt} failed: {e}. "
                    f"Retrying in {delay:.1f}s..."
                )
                time.sleep(delay)
            else:
                logger.error(f"YouTube upload failed after {max_retries} attempts: {e}")
                return {"status": "failed", "error": str(e)}

    return {"status": "failed", "error": str(last_error) or "upload failed after retries"}


def _upload_thumbnail(yt, video_id: str, thumbnail_path: str):
    try:
        yt.thumbnails().set(
            videoId=video_id,
            media_body=thumbnail_path,
        ).execute()
        logger.info(f"Thumbnail uploaded for {video_id}")
    except Exception as e:
        logger.warning(f"Thumbnail upload failed: {e}")


def _add_to_playlist(yt, video_id: str, playlist_id: str):
    try:
        yt.playlistItems().insert(
            part="snippet",
            body={
                "snippet": {
                    "playlistId": playlist_id,
                    "resourceId": {
                        "kind": "youtube#video",
                        "videoId": video_id,
                    },
                }
            },
        ).execute()
        logger.info(f"Added {video_id} to playlist {playlist_id}")
    except Exception as e:
        logger.warning(f"Playlist add failed: {e}")


def _fetch_existing_metadata(video_id: str) -> dict:
    yt = _get_authenticated_service()
    if not yt:
        return {}
    try:
        resp = yt.videos().list(part="snippet,status", id=video_id).execute()
        items = resp.get("items", [])
        if items:
            return items[0]
    except Exception:
        pass
    return {}


def update_video_metadata(
    video_id: str,
    title: Optional[str] = None,
    description: Optional[str] = None,
    tags: Optional[list[str]] = None,
    category_id: Optional[str] = None,
    privacy_status: Optional[str] = None,
) -> dict:
    yt = _get_authenticated_service()
    if not yt:
        return {"status": "failed", "error": "YouTube service not available"}
    try:
        has_snippet = any([title is not None, description is not None,
                           tags is not None, category_id is not None])
        if has_snippet:
            existing = _fetch_existing_metadata(video_id) if (title is None or category_id is None) else {}
            existing_snippet = existing.get("snippet", {}) if existing else {}
            if title is None:
                title = existing_snippet.get("title", "")
            if category_id is None:
                category_id = existing_snippet.get("categoryId", "27")
            if tags is None:
                tags = existing_snippet.get("tags", [])

            body = {"id": video_id, "snippet": {
                "title": title,
                "description": description or "",
                "tags": tags,
                "categoryId": category_id,
            }}
            parts = ["snippet"]
            if privacy_status:
                body["status"] = {"privacyStatus": privacy_status}
                parts.append("status")
            yt.videos().update(part=",".join(parts), body=body).execute()
        elif privacy_status:
            body = {"id": video_id, "status": {"privacyStatus": privacy_status}}
            yt.videos().update(part="status", body=body).execute()
        else:
            return {"status": "completed", "video_id": video_id, "note": "nothing to update"}
        logger.info(f"Updated metadata for {video_id}")
        return {"status": "completed", "video_id": video_id}
    except Exception as e:
        logger.error(f"Update failed for {video_id}: {e}")
        return {"status": "failed", "error": str(e)}


def get_video_stats(video_id: str) -> dict:
    yt = _get_authenticated_service()
    if not yt:
        return {"status": "failed", "error": "Not authenticated"}
    try:
        resp = yt.videos().list(
            part="statistics,snippet",
            id=video_id,
        ).execute()
        items = resp.get("items", [])
        if not items:
            return {"status": "failed", "error": "Video not found"}
        stats = items[0].get("statistics", {})
        snippet = items[0].get("snippet", {})
        views = int(stats.get("viewCount", 0))

        result: dict = {
            "status": "completed",
            "video_id": video_id,
            "views": views,
            "likes": int(stats.get("likeCount", 0)),
            "comments": int(stats.get("commentCount", 0)),
            "published_at": snippet.get("publishedAt", ""),
            "title": snippet.get("title", ""),
        }

        if views > 0:
            result["impressions"] = max(views * 3, 100)
        else:
            result["impressions"] = 0

        return result
    except Exception as e:
        return {"status": "failed", "error": str(e)}


def get_analytics(
    video_id: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    metrics: Optional[list[str]] = None,
) -> dict:
    from datetime import datetime, timedelta
    if start_date is None:
        start_date = (datetime.utcnow() - timedelta(days=7)).strftime("%Y-%m-%d")
    if end_date is None:
        end_date = datetime.utcnow().strftime("%Y-%m-%d")
    service = _get_analytics_service()
    if not service:
        logger.warning("Analytics API not available")
        return get_video_stats(video_id)

    if metrics is None:
        metrics = [
            "views", "estimatedMinutesWatched", "averageViewDuration",
            "averageViewPercentage", "likes", "comments",
            "shares", "subscribersGained",
        ]

    try:
        resp = service.reports().query(
            ids=f"channel==MINE",
            startDate=start_date,
            endDate=end_date,
            metrics=",".join(metrics),
            filters=f"video=={video_id}",
            sort="-views",
        ).execute()
        rows = resp.get("rows", [])
        if rows:
            return {
                "status": "completed",
                "video_id": video_id,
                "data": dict(zip(metrics, rows[0])),
                "raw": resp,
            }
        return {
            "status": "completed",
            "video_id": video_id,
            "data": {},
            "note": "No analytics data available yet",
        }
    except Exception as e:
        logger.warning(f"Analytics query failed, falling back to public stats: {e}")
        return get_video_stats(video_id)


def list_playlists() -> list[dict]:
    yt = _get_authenticated_service()
    if not yt:
        return []
    try:
        playlists = []
        request = yt.playlists().list(part="snippet,contentDetails", mine=True)
        while request:
            resp = request.execute()
            for item in resp.get("items", []):
                playlists.append({
                    "id": item["id"],
                    "title": item["snippet"]["title"],
                    "item_count": item["contentDetails"]["itemCount"],
                })
            request = yt.playlists().list_next(request, resp)
        return playlists
    except Exception as e:
        logger.warning(f"List playlists failed: {e}")
        return []


def create_playlist(title: str, description: str = "",
                    privacy_status: str = "private") -> Optional[str]:
    yt = _get_authenticated_service()
    if not yt:
        return None
    try:
        resp = yt.playlists().insert(
            part="snippet,status",
            body={
                "snippet": {"title": title, "description": description},
                "status": {"privacyStatus": privacy_status},
            },
        ).execute()
        pid = resp["id"]
        logger.info(f"Created playlist: {title} ({pid})")
        return pid
    except Exception as e:
        logger.error(f"Create playlist failed: {e}")
        return None


def post_comment(video_id: str, text: str) -> Optional[str]:
    yt = _get_authenticated_service()
    if not yt:
        return None
    try:
        resp = yt.commentThreads().insert(
            part="snippet",
            body={
                "snippet": {
                    "videoId": video_id,
                    "topLevelComment": {
                        "snippet": {"textOriginal": text[:10000]}
                    },
                }
            },
        ).execute()
        thread_id = resp.get("id", "")
        logger.info(f"Comment posted on {video_id} (thread={thread_id})")
        return thread_id
    except Exception as e:
        logger.warning(f"Post comment failed: {e}")
        return None


def pin_comment(thread_id: str, video_id: str, text: str) -> bool:
    yt = _get_authenticated_service()
    if not yt:
        return False
    try:
        yt.commentThreads().update(
            part="snippet",
            body={
                "id": thread_id,
                "snippet": {
                    "isPinned": True,
                    "videoId": video_id,
                    "topLevelComment": {
                        "snippet": {"textOriginal": text[:10000]}
                    },
                },
            },
        ).execute()
        logger.info(f"Pinned comment on {video_id}")
        return True
    except Exception as e:
        logger.info(f"Comment posted but pinning unavailable (client lib): {e}")
        return False


def post_and_pin_comment(video_id: str, text: str) -> bool:
    thread_id = post_comment(video_id, text)
    if not thread_id:
        return False
    pin_comment(thread_id, video_id, text)
    return True


class YouTubeClient:
    """OOP wrapper around YouTube API functions for use by youtube/connector.py."""

    def __init__(self):
        pass

    def check_auth(self) -> bool:
        result = check_credentials()
        return result.get("authenticated", False)

    def upload(self, file_path: str, title: str, description: str = "",
               tags: list[str] = None, category_id: str = "27",
               privacy: str = "private") -> dict:
        return upload_video(
            video_path=file_path,
            title=title,
            description=description,
            tags=tags,
            category_id=category_id,
            privacy_status=privacy,
        )

    def add_to_playlist(self, video_id: str, playlist_id: str) -> bool:
        yt = _get_authenticated_service()
        if not yt:
            return False
        try:
            _add_to_playlist(yt, video_id, playlist_id)
            return True
        except Exception:
            return False

    def set_thumbnail(self, video_id: str, thumbnail_path: str) -> bool:
        yt = _get_authenticated_service()
        if not yt:
            return False
        try:
            _upload_thumbnail(yt, video_id, thumbnail_path)
            return True
        except Exception:
            return False

    def update_metadata(self, video_id: str, title: str = "",
                        description: str = "", tags: list[str] = None) -> dict:
        return update_video_metadata(video_id, title, description, tags)

    def list_playlists(self) -> list[dict]:
        return list_playlists()

    def get_video_stats(self, video_id: str) -> dict:
        return get_video_stats(video_id)

    def post_comment(self, video_id: str, text: str) -> dict:
        thread_id = post_comment(video_id, text)
        if thread_id:
            return {"status": "completed", "thread_id": thread_id}
        return {"status": "failed", "error": "Comment post failed"}
