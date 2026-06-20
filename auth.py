"""Standalone YouTube OAuth — auto-opens browser, saves token as youtube_token.pickle."""
import os
import sys
import pickle
from pathlib import Path


def _get_channel_name(creds):
    try:
        from googleapiclient.discovery import build
        yt = build("youtube", "v3", credentials=creds)
        resp = yt.channels().list(part="snippet", mine=True).execute()
        items = resp.get("items", [])
        if items:
            return items[0]["snippet"]["title"]
    except Exception:
        pass
    return "(pending verification)"


def main():
    os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
    BASE_DIR = Path(__file__).resolve().parent
    sys.path.insert(0, str(BASE_DIR))

    SCOPES = [
        "https://www.googleapis.com/auth/youtube.upload",
        "https://www.googleapis.com/auth/youtube",
        "https://www.googleapis.com/auth/youtube.readonly",
        "https://www.googleapis.com/auth/yt-analytics.readonly",
    ]

    secrets_path = BASE_DIR / "client_secrets.json"
    if not secrets_path.exists():
        print(f"ERROR: {secrets_path} not found")
        print("Place client_secrets.json in the project root.")
        sys.exit(1)

    token_path = BASE_DIR / "youtube_token.pickle"

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        print("ERROR: google-auth-oauthlib not installed.")
        print("Run: pip install google-auth-oauthlib google-api-python-client")
        sys.exit(1)

    # Check existing token
    if token_path.exists():
        try:
            from google.auth.transport.requests import Request
            with open(token_path, "rb") as f:
                creds = pickle.load(f)
            if creds and creds.valid:
                print("AUTH SUCCESS - Token already valid")
                print(f"Channel: {_get_channel_name(creds)}")
                return
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
                with open(token_path, "wb") as f:
                    pickle.dump(creds, f)
                print("AUTH SUCCESS - Token refreshed")
                print(f"Channel: {_get_channel_name(creds)}")
                return
        except Exception as e:
            print(f"Token invalid, re-authenticating: {e}")

    # Run OAuth flow — prints URL, you visit it manually
    print("=" * 60)
    print("  GOOGLE OAuth REQUIRED")
    print("  Sign in with: oo607820@gmail.com")
    print("=" * 60)
    print()
    flow = InstalledAppFlow.from_client_secrets_file(str(secrets_path), SCOPES)
    creds = flow.run_local_server(port=8080, open_browser=False)

    with open(token_path, "wb") as f:
        pickle.dump(creds, f)
    print(f"Token saved: {token_path}")

    name = _get_channel_name(creds)
    print(f"AUTH SUCCESS - Authenticated as: {name}")
    print("READY FOR AUTOMATION PIPELINE")


if __name__ == "__main__":
    main()
