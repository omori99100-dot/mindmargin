"""YouTube integration package.

Re-exports all public and internal functions from client.py for backward
compatibility with existing imports like:
    from mindmargin.integrations.youtube import check_credentials, upload_video
    import mindmargin.integrations.youtube as yt
"""

from mindmargin.integrations.youtube.client import (
    # Public API
    check_credentials,
    upload_video,
    update_video_metadata,
    get_video_stats,
    get_analytics,
    list_playlists,
    create_playlist,
    post_comment,
    pin_comment,
    post_and_pin_comment,
    # Client class
    YouTubeClient,
    # Internal functions used by other modules
    _get_authenticated_service,
    _get_analytics_service,
    _fetch_existing_metadata,
    _has_google_libs,
    _find_client_secrets,
    _find_token,
    _token_path,
    _auth_url_path,
    _upload_thumbnail,
    _add_to_playlist,
    # Constants
    CLIENT_SECRETS_FILE,
    TOKEN_FILE,
    SCOPES,
    API_SERVICE_NAME,
    API_VERSION,
    ANALYTICS_API_SERVICE_NAME,
    ANALYTICS_API_VERSION,
)

__all__ = [
    "check_credentials",
    "upload_video",
    "update_video_metadata",
    "get_video_stats",
    "get_analytics",
    "list_playlists",
    "create_playlist",
    "post_comment",
    "pin_comment",
    "post_and_pin_comment",
    "YouTubeClient",
    "_get_authenticated_service",
    "_fetch_existing_metadata",
    "_has_google_libs",
    "_find_client_secrets",
    "_find_token",
    "_token_path",
    "_auth_url_path",
    "_upload_thumbnail",
    "_add_to_playlist",
    "CLIENT_SECRETS_FILE",
    "TOKEN_FILE",
    "SCOPES",
    "API_SERVICE_NAME",
    "API_VERSION",
    "ANALYTICS_API_SERVICE_NAME",
    "ANALYTICS_API_VERSION",
]
