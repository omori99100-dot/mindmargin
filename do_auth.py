"""YouTube OAuth — one-shot: opens browser, catches callback, saves token."""
import os, pickle, sys, webbrowser
from pathlib import Path

os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.force-ssl",
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]

from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

secrets_path = BASE_DIR / "client_secrets.json"
token_path = BASE_DIR / "youtube_token.pickle"

# Check existing token first
if token_path.exists():
    try:
        from google.auth.transport.requests import Request
        with open(token_path, "rb") as f:
            creds = pickle.load(f)
        if creds and creds.valid:
            yt = build("youtube", "v3", credentials=creds)
            resp = yt.channels().list(part="snippet", mine=True).execute()
            name = resp["items"][0]["snippet"]["title"] if resp.get("items") else "?"
            print(f"AUTH SUCCESS - Token already valid")
            print(f"Authenticated as: {name}")
            print("READY FOR AUTOMATION PIPELINE")
            sys.exit(0)
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            with open(token_path, "wb") as f:
                pickle.dump(creds, f)
            yt = build("youtube", "v3", credentials=creds)
            resp = yt.channels().list(part="snippet", mine=True).execute()
            name = resp["items"][0]["snippet"]["title"] if resp.get("items") else "?"
            print(f"AUTH SUCCESS - Token refreshed")
            print(f"Authenticated as: {name}")
            print("READY FOR AUTOMATION PIPELINE")
            sys.exit(0)
    except Exception as e:
        print(f"Token stale, re-authenticating: {e}")

print("=" * 60)
print("  GOOGLE OAuth REQUIRED")
print("  Sign in with: oo607820@gmail.com")
print("  Browser will open automatically...")
print("=" * 60)
print()

flow = InstalledAppFlow.from_client_secrets_file(str(secrets_path), SCOPES)
creds = flow.run_local_server(port=8080, open_browser=True)

with open(token_path, "wb") as f:
    pickle.dump(creds, f)
print(f"Token saved: {token_path}")

yt = build("youtube", "v3", credentials=creds)
resp = yt.channels().list(part="snippet", mine=True).execute()
name = resp["items"][0]["snippet"]["title"] if resp.get("items") else "?"
print(f"AUTH SUCCESS - Authenticated as: {name}")
print("READY FOR AUTOMATION PIPELINE")
