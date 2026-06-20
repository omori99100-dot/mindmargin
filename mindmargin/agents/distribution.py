"""Distribution Agent: playlist building, cross-linking, dead video revision, pinned comments."""

import logging
from datetime import datetime
from typing import Optional

from mindmargin.analytics.memory import (
    get_pipeline_history, get_all_classifications, save_best_practice,
)

logger = logging.getLogger(__name__)

_TOPIC_PLAYLISTS: dict[str, list[str]] = {
    "Financial Fraud & Scams": [
        "enron", "theranos", "wework", "ftx", "ftx collapse",
        "cambridge analytica", "bernie madoff", "wirecard",
        "wirecard's billion dollar fraud", "celsius network",
    ],
    "Tech Giants That Fell": [
        "nokia", "blackberry", "kodak", "blockbuster", "yahoo",
        "myspace", "palm", "compaq", "netscape", "radioshack",
        "circuit city",
    ],
    "Financial Collapses & Crashes": [
        "lehman brothers", "silicon valley bank", "ltcm",
        "gamestop", "bitcoin crash",
    ],
    "Corporate Downfalls": [
        "sears", "arthur andersen", "toys r us",
        "uber", "the untold story of uber's toxic culture",
    ],
}


_TOPIC_SIMILARITY: dict[str, list[str]] = {
    "enron": ["theranos", "wework"],
    "theranos": ["enron", "bernie madoff"],
    "wework": ["uber", "theranos"],
    "ftx": ["celsius network", "bernie madoff"],
    "ftx collapse": ["ftx", "celsius network"],
    "cambridge analytica": ["facebook data scandal", "enron"],
    "bernie madoff": ["enron", "wirecard"],
    "wirecard": ["bernie madoff", "enron"],
    "wirecard's billion dollar fraud": ["wirecard", "bernie madoff"],
    "celsius network": ["ftx", "bitcoin crash"],
    "lehman brothers": ["silicon valley bank", "ltcm"],
    "silicon valley bank": ["lehman brothers", "ltcm"],
    "ltcm": ["lehman brothers", "silicon valley bank"],
    "gamestop": ["bitcoin crash", "ftx"],
    "bitcoin crash": ["ftx", "celsius network"],
    "nokia": ["blackberry", "kodak"],
    "blackberry": ["nokia", "palm"],
    "kodak": ["blockbuster", "nokia"],
    "blockbuster": ["kodak", "netflix"],
    "yahoo": ["myspace", "nokia"],
    "myspace": ["yahoo", "facebook"],
    "palm": ["blackberry", "nokia"],
    "compaq": ["dell", "ibm"],
    "netscape": ["yahoo", "microsoft"],
    "radioshack": ["circuit city", "blockbuster"],
    "circuit city": ["radioshack", "blockbuster"],
    "sears": ["toys r us", "radioshack"],
    "arthur andersen": ["enron", "wework"],
    "toys r us": ["sears", "blockbuster"],
    "uber": ["wework", "theranos"],
    "the untold story of uber's toxic culture": ["uber", "wework"],
}


class DistributionAgent:
    """Distribution optimization for published YouTube videos."""

    def __init__(self):
        self.name = "distribution"

    def _get_published_videos(self) -> list[dict]:
        """Get all published videos from memory."""
        history = get_pipeline_history(200)
        return [p for p in history if p.get("youtube_video_id")]

    def _normalize_topic(self, topic: str) -> str:
        return topic.lower().strip()

    def _match_playlist_topic(self, topic: str) -> Optional[str]:
        """Find which playlist a video belongs to."""
        norm = self._normalize_topic(topic)
        for playlist_name, topics in _TOPIC_PLAYLISTS.items():
            for t in topics:
                if t in norm or norm in t:
                    return playlist_name
        return None

    def build_playlists(self) -> dict:
        """Create topical playlists and add videos to them."""
        from mindmargin.integrations.youtube import (
            list_playlists, create_playlist, _add_to_playlist as add_to_playlist,
            _get_authenticated_service,
        )

        yt = _get_authenticated_service()
        if not yt:
            return {"status": "failed", "error": "YouTube service not available"}

        videos = self._get_published_videos()
        if not videos:
            return {"status": "skipped", "reason": "No published videos found"}

        existing = {p["title"]: p["id"] for p in list_playlists()}
        video_by_topic: dict[str, dict] = {}
        for v in videos:
            video_by_topic[self._normalize_topic(v["topic"])] = v

        created = 0
        added = 0
        errors = 0

        for playlist_name, topic_keywords in _TOPIC_PLAYLISTS.items():
            pid = existing.get(playlist_name)
            if not pid:
                pid = create_playlist(
                    title=playlist_name,
                    description=f"Curated by MindMargin — {playlist_name.lower()}",
                    privacy_status="public",
                )
                if pid:
                    created += 1
                    existing[playlist_name] = pid
                else:
                    errors += 1
                    continue

            for kw in topic_keywords:
                for norm_topic, v in video_by_topic.items():
                    if kw in norm_topic or norm_topic in kw:
                        try:
                            add_to_playlist(yt, v["youtube_video_id"], pid)
                            added += 1
                        except Exception:
                            errors += 1
                        break

        result = {
            "status": "completed",
            "playlists_created": created,
            "videos_added": added,
            "errors": errors,
        }
        logger.info(f"Playlist build: {created} created, {added} videos added, {errors} errors")
        save_best_practice("distribution", "playlists_built",
                           f"Built {created} playlists with {added} videos", 50)
        return result

    def cross_link_videos(self) -> dict:
        """Add related video links to each video's description."""
        from mindmargin.integrations.youtube import update_video_metadata, get_video_stats

        videos = self._get_published_videos()
        if not videos:
            return {"status": "skipped", "reason": "No published videos found"}

        video_map: dict[str, dict] = {}
        for v in videos:
            norm = self._normalize_topic(v["topic"])
            video_map[norm] = v

        updated = 0
        errors = 0

        for v in videos:
            vid = v["youtube_video_id"]
            topic = v["topic"]
            norm = self._normalize_topic(topic)

            related = _TOPIC_SIMILARITY.get(norm, [])
            if not related:
                continue

            related_links = []
            for r in related:
                match = video_map.get(r)
                if match and match["youtube_video_id"] != vid:
                    related_links.append(
                        f"  \u2022 {match['topic']}: https://youtu.be/{match['youtube_video_id']}"
                    )

            if not related_links:
                continue

            stats = get_video_stats(vid)
            if stats.get("status") != "completed":
                errors += 1
                continue

            existing_desc = stats.get("title", "")
            if not existing_desc:
                errors += 1
                continue

            try:
                from mindmargin.integrations.youtube import _fetch_existing_metadata
                resp = _fetch_existing_metadata(vid)
                full_desc = resp.get("snippet", {}).get("description", "")
            except Exception:
                errors += 1
                continue

            if "\u25b6\ufe0f WATCH NEXT" in full_desc:
                continue

            cross_section = (
                "\n\n\u25b6\ufe0f WATCH NEXT:\n"
                + "\n".join(related_links)
                + "\n"
            )
            new_desc = full_desc + cross_section

            update_video_metadata(video_id=vid, description=new_desc)
            updated += 1

        result = {
            "status": "completed",
            "descriptions_updated": updated,
            "errors": errors,
        }
        logger.info(f"Cross-linking: {updated} descriptions updated, {errors} errors")
        save_best_practice("distribution", "cross_links_added",
                           f"Added cross-links to {updated} video descriptions", 30)
        return result

    def revise_dead_videos(self) -> dict:
        """Update metadata of dead-classified videos with improved titles."""
        from mindmargin.integrations.youtube import update_video_metadata

        classifications = get_all_classifications(100)
        dead = [c for c in classifications if c["classification"] in ("weak_signal",)]

        if not dead:
            return {"status": "skipped", "reason": "No dead videos to revise"}

        history_map = {p["id"]: p for p in get_pipeline_history(200)}

        _TITLE_PREFIXES = [
            "The Truth About ",
            "What Really Happened With ",
            "Inside the Collapse of ",
            "The Real Story of ",
        ]

        updated = 0
        errors = 0
        seen_video_ids: set[str] = set()

        for d in dead:
            video_id = d.get("video_id", "")
            if video_id in seen_video_ids:
                continue
            seen_video_ids.add(video_id)

            pid = d.get("pipeline_id", "")
            pipe = history_map.get(pid)
            if not pipe:
                errors += 1
                continue

            topic = pipe.get("topic", "")
            existing_vid = pipe.get("youtube_video_id", "")
            if not existing_vid or existing_vid != video_id:
                errors += 1
                continue

            new_title = f"{_TITLE_PREFIXES[abs(hash(topic)) % len(_TITLE_PREFIXES)]}{topic}"
            new_title = new_title[:100]

            result = update_video_metadata(video_id=video_id, title=new_title)
            if result.get("status") == "completed":
                updated += 1
            else:
                errors += 1

        result = {
            "status": "completed",
            "videos_revised": updated,
            "errors": errors,
        }
        logger.info(f"Dead video revision: {updated} revised, {errors} errors")
        save_best_practice("distribution", "dead_videos_revised",
                           f"Revised metadata for {updated} dead-classified videos", 20)
        return result

    def post_pinned_comments(self) -> dict:
        """Post and pin chapter-comment on every published video."""
        from mindmargin.integrations.youtube import post_and_pin_comment
        from mindmargin.agents.metadata import MetadataAgent

        videos = self._get_published_videos()
        if not videos:
            return {"status": "skipped", "reason": "No published videos found"}

        posted = 0
        skipped = 0
        errors = 0

        agent = MetadataAgent()

        for v in videos:
            vid = v["youtube_video_id"]
            topic = v.get("topic", "")
            pid = v.get("id", "")

            try:
                import json as _json
                from mindmargin.core.storage import project_dir as _project_dir
                out_dir = _project_dir(topic, pid)
                script_path = out_dir / "script" / "script.json"
                if not script_path.exists():
                    skipped += 1
                    continue
                script_data = _json.loads(script_path.read_text(encoding="utf-8"))
                sections = script_data.get("sections", [])
                chapters = agent._build_chapters(sections)
                comment = agent._build_pinned_comment(topic, chapters)

                ok = post_and_pin_comment(vid, comment)
                if ok:
                    posted += 1
                else:
                    errors += 1
            except Exception:
                errors += 1

        result = {
            "status": "completed",
            "comments_posted": posted,
            "skipped": skipped,
            "errors": errors,
        }
        logger.info(f"Pinned comments: {posted} posted, {skipped} skipped, {errors} errors")
        save_best_practice("distribution", "pinned_comments_posted",
                           f"Posted pinned comments on {posted} videos", 20)
        return result

    def run_all(self) -> dict:
        """Run all distribution tactics in sequence."""
        results = {}

        logger.info("=== Distribution Agent Starting ===")

        logger.info("[1/4] Building playlists...")
        results["playlists"] = self.build_playlists()

        logger.info("[2/4] Cross-linking videos...")
        results["cross_links"] = self.cross_link_videos()

        logger.info("[3/4] Revising dead video metadata...")
        results["dead_revision"] = self.revise_dead_videos()

        logger.info("[4/4] Posting pinned comments...")
        results["pinned_comments"] = self.post_pinned_comments()

        logger.info("=== Distribution Agent Complete ===")

        return {
            "status": "completed",
            "playlists_created": results["playlists"].get("playlists_created", 0),
            "videos_added": results["playlists"].get("videos_added", 0),
            "descriptions_updated": results["cross_links"].get("descriptions_updated", 0),
            "dead_revised": results["dead_revision"].get("videos_revised", 0),
            "comments_posted": results["pinned_comments"].get("comments_posted", 0),
            "details": results,
        }


