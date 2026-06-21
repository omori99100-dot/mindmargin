"""Seed the local database with published YouTube videos for cold-start analytics."""
import os, sys, pickle, sqlite3, json, logging
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)
sys.path.insert(0, BASE_DIR)
os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("seed_db")

DB_PATH = os.path.join(BASE_DIR, "data", "mindmargin.db")
TOKEN_PATH = os.path.join(BASE_DIR, "youtube_token.pickle")

# Connect to DB
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
conn = sqlite3.connect(DB_PATH)

# Ensure tables exist
conn.executescript("""
CREATE TABLE IF NOT EXISTS pipelines (
    id TEXT PRIMARY KEY,
    topic TEXT NOT NULL,
    mode TEXT DEFAULT 'documentary',
    status TEXT DEFAULT 'completed',
    word_count INTEGER DEFAULT 0,
    video_duration_s REAL DEFAULT 0,
    video_path TEXT DEFAULT '',
    thumbnail_path TEXT DEFAULT '',
    youtube_video_id TEXT DEFAULT '',
    youtube_url TEXT DEFAULT '',
    youtube_status TEXT DEFAULT '',
    created_at TEXT DEFAULT (datetime('now')),
    published_at TEXT
);

CREATE TABLE IF NOT EXISTS analytics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pipeline_id TEXT NOT NULL,
    video_id TEXT NOT NULL,
    views INTEGER DEFAULT 0,
    likes INTEGER DEFAULT 0,
    comments INTEGER DEFAULT 0,
    impressions INTEGER DEFAULT 0,
    avg_view_duration_s REAL DEFAULT 0,
    shares INTEGER DEFAULT 0,
    subscribers_gained INTEGER DEFAULT 0,
    collected_at TEXT DEFAULT (datetime('now')),
    FOREIGN KEY (pipeline_id) REFERENCES pipelines(id)
);
""")

# Check if we already have data
existing = conn.execute(
    "SELECT COUNT(*) FROM pipelines WHERE youtube_video_id != ''"
).fetchone()[0]

if existing > 0:
    log.info(f"Database already has {existing} published videos, skipping seed")
    conn.close()
    sys.exit(0)

# Load token
if not os.path.exists(TOKEN_PATH):
    log.info("No token found, skipping seed")
    conn.close()
    sys.exit(0)

with open(TOKEN_PATH, "rb") as f:
    creds = pickle.load(f)

from googleapiclient.discovery import build
yt = build("youtube", "v3", credentials=creds)

# Get channel uploads
channel_resp = yt.channels().list(part="contentDetails", mine=True).execute()
if not channel_resp.get("items"):
    log.info("No channel found")
    conn.close()
    sys.exit(0)

uploads_id = channel_resp["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

# Fetch all uploaded videos
videos = []
page_token = None
while True:
    pl_resp = yt.playlistItems().list(
        part="snippet", playlistId=uploads_id,
        maxResults=50, pageToken=page_token
    ).execute()
    for item in pl_resp.get("items", []):
        vid = item["snippet"]["resourceId"]["videoId"]
        title = item["snippet"]["title"]
        published = item["snippet"]["publishedAt"]
        videos.append({"id": vid, "title": title, "published_at": published})
    page_token = pl_resp.get("nextPageToken")
    if not page_token:
        break

log.info(f"Found {len(videos)} videos on channel")

# Insert into database
inserted = 0
for v in videos:
    existing_row = conn.execute(
        "SELECT id FROM pipelines WHERE youtube_video_id = ?", (v["id"],)
    ).fetchone()
    if existing_row:
        continue
    pid = f"seed_{v['id']}"
    conn.execute(
        "INSERT OR IGNORE INTO pipelines (id, topic, youtube_video_id, youtube_url, published_at, status) VALUES (?, ?, ?, ?, ?, ?)",
        (pid, v["title"], v["id"], f"https://youtu.be/{v['id']}", v["published_at"], "completed")
    )
    inserted += 1

conn.commit()
conn.close()
log.info(f"Seeded {inserted} new videos into database")
