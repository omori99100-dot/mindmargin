import argparse
import sys
from pathlib import Path

from mindmargin.config import settings
from mindmargin.logger import logger
from mindmargin.core.pipeline import Pipeline
from mindmargin.validation import verify_pipeline_output, print_validation
from mindmargin.prompts import GENERATION_MODES


def _do_publish(topic: str, pipeline_id: str, privacy: str, playlist: str):
    """Publish a pipeline's output to YouTube."""
    from mindmargin.integrations.youtube import check_credentials, upload_video
    from mindmargin.agents.thumbnail import ThumbnailAgent, pick_best_thumbnail
    from mindmargin.agents.metadata import MetadataAgent
    from mindmargin.analytics.memory import save_pipeline, save_titles, save_hooks, save_thumbnails
    from mindmargin.core.storage import project_dir

    # Check credentials
    creds = check_credentials()
    if not creds.get("authenticated"):
        print(f"\n  YouTube auth required. {creds.get('error', '')}")
        print("  See: https://console.cloud.google.com/apis/credentials")
        return

    print(f"\n  Authenticated as: {creds.get('channel_name', '?')}")

    # Load script data
    out_dir = project_dir(topic, pipeline_id)
    script_path = out_dir / "script" / "script.json"
    if not script_path.exists():
        print(f"  ERROR: script.json not found at {script_path}")
        return
    import json as _json
    script_data = _json.loads(script_path.read_text(encoding="utf-8"))

    # Skip thumbnail regen if already generated during pipeline
    thumb_result = {"thumbnails": {"variants": []}}
    existing_thumbs = sorted((out_dir / "thumbnails").glob("*.png")) if (out_dir / "thumbnails").exists() else []
    if existing_thumbs:
        thumbnail_path = str(existing_thumbs[0])
        thumb_result["thumbnails"]["variants"] = [{"path": str(p)} for p in existing_thumbs]
        print(f"  Thumbnails: {len(existing_thumbs)} existing variants (skipped regen)")
    else:
        print("  Generating thumbnails...")
        thumb_agent = ThumbnailAgent()
        thumb_result = thumb_agent.run(topic, pipeline_id, script_data)
        thumbnail_path = pick_best_thumbnail(thumb_result.get("thumbnails", {}))
        if thumbnail_path:
            print(f"  Thumbnails: {thumb_result['thumbnails']['variants_count']} variants")

    # Generate full metadata
    print("  Generating metadata...")
    meta_agent = MetadataAgent()
    meta_result = meta_agent.run(topic, pipeline_id, script_data)
    meta = meta_result.get("metadata", {})

    # Find video file
    video_candidates = list(out_dir.glob("video/*_final.mp4"))
    if not video_candidates:
        print("  ERROR: No final MP4 found. Run pipeline first.")
        return

    video_path = str(video_candidates[0])
    best_title = meta.get("best_title", topic)
    description = meta.get("description", "")
    tags = meta.get("tags", [])

    print(f"\n  Video: {video_path}")
    print(f"  Title: {best_title}")
    print(f"  Privacy: {privacy}")
    print(f"  Tags: {len(tags)} tags")
    print(f"\n  Uploading to YouTube...")

    result = upload_video(
        video_path=video_path,
        title=best_title,
        description=description,
        tags=tags,
        category_id=meta.get("category_id", "27"),
        privacy_status=privacy,
        playlist_id=playlist or None,
        thumbnail_path=thumbnail_path or None,
    )

    if result.get("status") == "completed":
        vid = result["video_id"]
        url = result["url"]
        print(f"\n  PUBLISHED: {url}")

        # Save to memory
        save_pipeline(
            pipeline_id=pipeline_id, topic=topic,
            word_count=script_data.get("word_count", 0),
            video_path=video_path,
            thumbnail_path=thumbnail_path or "",
            youtube_video_id=vid,
            youtube_url=url,
        )
        save_titles(pipeline_id, meta.get("all_titles", []))
        save_hooks(pipeline_id, script_data.get("hooks", []))
        save_thumbnails(pipeline_id,
                        thumb_result.get("thumbnails", {}).get("variants", []))
        # Seed A/B variants for future rotation
        try:
            from mindmargin.analytics.ab_testing import seed_variants
            seed_variants(pipeline_id, vid)
        except Exception as e:
            logger.warning(f"AB seeding skipped: {e}")
    else:
        print(f"  Upload failed: {result.get('error', 'unknown')}")


def _do_analytics(video_id: str, pipeline_id: str):
    """Collect and display analytics for a video."""
    from mindmargin.analytics.feedback import collect_analytics, analyze_performance

    if video_id:
        print(f"\n  Collecting analytics for video: {video_id}")
        result = collect_analytics(pipeline_id or "manual", video_id)
    else:
        from mindmargin.analytics.memory import get_pipeline_stats
        stats = get_pipeline_stats()
        print(f"\n  Pipeline Stats:")
        print(f"    Total pipelines: {stats['total_pipelines']}")
        print(f"    Published videos: {stats['published_videos']}")
        print(f"    Total views: {stats['total_views']}")
        print(f"    Total likes: {stats['total_likes']}")
        return

    if result.get("status") == "completed":
        print(f"    Views: {result.get('views', 0)}")
        print(f"    Likes: {result.get('likes', 0)}")
        print(f"    Comments: {result.get('comments', 0)}")
    else:
        print(f"    Error: {result.get('error', 'unknown')}")


def _do_dashboard():
    """Display publishing dashboard."""
    from mindmargin.analytics.memory import get_pipeline_history, get_pipeline_stats
    from mindmargin.analytics.feedback import format_feedback_report

    stats = get_pipeline_stats()
    history = get_pipeline_history(10)

    bar = "=" * 50
    print(f"\n{bar}")
    print(f"  MINDMARGIN PUBLISHING DASHBOARD")
    print(bar)
    print(f"  Total pipelines:   {stats['total_pipelines']}")
    print(f"  Published videos:  {stats['published_videos']}")
    print(f"  Total views:       {stats['total_views']}")
    print(f"  Total likes:       {stats['total_likes']}")
    print(bar)
    print(f"  RECENT PIPELINES:")
    for p in history:
        vid = p.get("youtube_video_id", "")
        url = p.get("youtube_url", "")
        status = "PUBLISHED" if vid else "LOCAL"
        print(f"    [{status}] {p['topic'][:40]:40s} {p.get('created_at', '')[:19]}")
        if url:
            print(f"            {url}")
    print(bar)
    if stats.get("best_hooks"):
        print(f"  BEST HOOKS:")
        for h in stats["best_hooks"]:
            print(f"    [{h.get('archetype', '?')}] {h.get('hook_text', '')[:70]}")
    if stats.get("best_titles"):
        print(f"  BEST TITLES:")
        for t in stats["best_titles"]:
            print(f"    {t.get('title', '')[:70]}")
    print(bar)


def _do_evolution_dashboard():
    """Display A/B Evolution Dashboard: winners, deltas, active tests, history."""
    from mindmargin.analytics.memory import (
        get_ab_winning_titles, get_ab_winning_thumbnails,
        get_ab_evolution_history, get_ab_win_loss_counts,
        get_ab_active_summary, get_ab_winner_for_pipeline,
        get_pipeline_history, get_pipeline_stats,
        get_best_practices,
    )

    bar = "=" * 58
    title_winners = get_ab_winning_titles(5)
    thumb_winners = get_ab_winning_thumbnails(5)
    active = get_ab_active_summary()
    win_loss = get_ab_win_loss_counts()
    history = get_ab_evolution_history(15)
    practices = get_best_practices()

    # ── Header ──
    print(f"\n{bar}")
    print(f"  EVOLUTION DASHBOARD  |  A/B Testing Layer")
    print(bar)

    # ── 1. Best Title Variants ──
    print(f"\n  [1] BEST TITLE VARIANTS  (winner by CTR)")
    if title_winners:
        for w in title_winners:
            ctr = w.get("ctr", 0) or 0
            wt = w.get("watch_time_s", 0) or 0
            print(f"  \u2713 {w.get('variant_value', '')[:50]:50s}  "
                  f"CTR={ctr:.1f}%  WT={wt:.0f}s  "
                  f"{w.get('topic', '')[:20]}")
    else:
        print(f"  ~ No winners declared yet (A/B tests still running)")
    print(bar)

    # ── 2. Best Thumbnail Styles ──
    print(f"\n  [2] BEST THUMBNAIL STYLES  (winner by CTR)")
    if thumb_winners:
        for w in thumb_winners:
            ctr = w.get("ctr", 0) or 0
            val = w.get("variant_value", "")
            style = val.split("|")[0] if "|" in val else val
            print(f"  \u2713 {style:25s}  CTR={ctr:.1f}%  "
                  f"{w.get('topic', '')[:25]}")
    else:
        print(f"  ~ No winners declared yet")
    print(bar)

    # ── 3+4. CTR Delta & Retention Delta ──
    print(f"\n  [3] CTR DELTA  |  [4] RETENTION DELTA")
    all_ab_practices = [p for p in practices
                        if p["category"] in ("ab_title_winner", "ab_thumbnail_winner")]
    if all_ab_practices:
        for p in all_ab_practices[:6]:
            cat = p["category"].replace("ab_", "").replace("_", " ")
            print(f"  {cat:20s} \u2192 {p.get('value', '')[:55]}")
    # Show avg CTR across winners
    all_winners = get_ab_winning_titles(50)
    all_thumbs = get_ab_winning_thumbnails(50)
    if all_winners:
        avg_ctr = sum((w.get("ctr", 0) or 0) for w in all_winners) / len(all_winners)
        print(f"  {'avg title CTR':20s} \u2192 {avg_ctr:.1f}% across {len(all_winners)} winners")
    if all_thumbs:
        avg_ctr_t = sum((w.get("ctr", 0) or 0) for w in all_thumbs) / len(all_thumbs)
        print(f"  {'avg thumb CTR':20s} \u2192 {avg_ctr_t:.1f}% across {len(all_thumbs)} winners")
    print(bar)

    # ── 5. Active A/B Tests ──
    print(f"\n  [5] ACTIVE A/B TESTS  ({len(active)} running)")
    if active:
        for a in active[:8]:
            from datetime import datetime
            start = a.get("test_start_time", "")
            elapsed = ""
            if start:
                try:
                    dt = datetime.strptime(start[:19], "%Y-%m-%d %H:%M:%S")
                    hours = int((datetime.utcnow() - dt).total_seconds() / 3600)
                    elapsed = f"{hours}h"
                except ValueError:
                    pass
            vtype = a["variant_type"][0].upper()
            idx = a["variant_index"]
            print(f"  [{vtype}#{idx}] {a.get('topic', '')[:35]:35s}  "
                  f"vid={a['video_id'][:8]}  since={elapsed}")
    else:
        print(f"  ~ No active tests")
    print(bar)

    # ── 6. Winners vs Losers ──
    print(f"\n  [6] WINNERS vs LOSERS")
    tw = win_loss.get("title_wins", 0)
    tl = win_loss.get("title_losses", 0)
    tn = tw + tl
    print(f"  {'Titles':20s} {tw:3d} wins  {tl:3d} losses  "
          f"(win rate {tw/max(tn,1)*100:.0f}%)")
    mw = win_loss.get("thumb_wins", 0)
    ml = win_loss.get("thumb_losses", 0)
    mn = mw + ml
    print(f"  {'Thumbnails':20s} {mw:3d} wins  {ml:3d} losses  "
          f"(win rate {mw/max(mn,1)*100:.0f}%)")
    total_wins = tw + mw
    total_losses = tl + ml
    total_n = total_wins + total_losses
    print(f"  {'TOTAL':20s} {total_wins:3d} wins  {total_losses:3d} losses  "
          f"(win rate {total_wins/max(total_n,1)*100:.0f}%)")
    print(bar)

    # ── 7. Evolution History ──
    print(f"\n  [7] EVOLUTION HISTORY  (last {len(history)} completed)")
    for h in history[:10]:
        vtype = h["variant_type"][0].upper()
        idx = h["variant_index"]
        w = "\u2713" if h.get("winner_flag") else "\u2717"
        ctr = h.get("ctr", 0) or 0
        val = h.get("variant_value", "")[:35]
        print(f"  {w} [{vtype}#{idx}] CTR={ctr:.1f}%  {val:35s}  "
              f"{h.get('topic', '')[:20]}")
    if not history:
        print(f"  ~ No completed A/B tests yet")
    print(bar)

    # ── Footer: Learning Feedback ──
    print(f"\n  LEARNING FEEDBACK: Optimizer ingests {len(all_ab_practices)} "
          f"AB-winning patterns")
    print(f"  Next rotation in: daily analytics job (--run-daily-job)")
    print(bar)


def _do_drift_report():
    """Display performance drift report."""
    from mindmargin.analytics.patterns import generate_drift_report

    report = generate_drift_report()
    bar = "=" * 50

    print(f"\n{bar}")
    print(f"  PERFORMANCE DRIFT REPORT")
    print(bar)

    if report["status"] == "insufficient_data":
        print(f"  Status: insufficient_data")
        reason = report.get("drift", {}).get("reason", "Need >=2 weeks of published analytics data")
        print(f"  {reason}")
        print(bar)
        return

    drift = report.get("drift", {})
    trends = report.get("trends", {})

    print(f"  Overall Drift: {drift.get('overall_drift', '?').upper()}")
    print(f"  {drift.get('learning_status', '')}")
    print(f"  Period: {drift.get('periods_compared', '?')}")
    print(f"  Confidence-weighted across {len(drift.get('drifts', []))} metrics")
    print(bar)

    if trends.get("metrics"):
        print(f"  WEEKLY METRIC TRENDS ({trends.get('periods', 0)} periods):")
        for metric_key, metric_data in trends["metrics"].items():
            vals = metric_data.get("values", [])
            if vals:
                recent = vals[-1]
                print(f"    {metric_data['label']}: {recent['value']}{metric_data['unit']} "
                      f"(week {recent['week']}, n={recent['videos']})")

    print(bar)
    print(f"  PER-METRIC DRIFT CLASSIFICATION:")
    for d in drift.get("drifts", []):
        icon = {"positive": "+", "negative": "-", "neutral": "~"}.get(
            d["drift_classification"], "?")
        print(f"    [{icon}] {d['label']:25s} {d['current_value']:>8.1f} "
              f"(prev: {d['previous_value']:>8.1f}) "
              f"change: {d['pct_change']:>+6.1f}%  "
              f"conf: {d['confidence']:.2f}  "
              f"n={d['samples_current']}+{d['samples_previous']}")

    print(bar)


def main():
    modes = list(GENERATION_MODES.keys())
    parser = argparse.ArgumentParser(description="MindMargin MVP Pipeline")
    parser.add_argument("--topic", type=str, default="", help="Video topic")
    parser.add_argument("--api", action="store_true", help="Start API server")
    parser.add_argument("--host", type=str, default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--api-workers", type=int, default=1, help="Number of API workers")
    parser.add_argument("--api-reload", action="store_true", help="Enable auto-reload for API")
    parser.add_argument("--resume", type=str, default="", help="Pipeline ID to resume")
    parser.add_argument("--quick", action="store_true", help="Quick mode (short video for testing)")
    parser.add_argument("--skip-validation", action="store_true", help="Skip output validation")
    parser.add_argument("--template", action="store_true", help="Use template fallbacks (skip LLM)")
    parser.add_argument("--mode", type=str, default="documentary", choices=modes,
                        help=f"Generation mode: {', '.join(modes)}")
    parser.add_argument("--editing-timeout", type=int, default=None,
                        help="Editing stage timeout in seconds (default: no timeout)")
    parser.add_argument("--force-editing", action="store_true",
                        help="Force re-render all editing clips (ignore cache)")

    # Publishing & Analytics
    parser.add_argument("--publish", action="store_true", help="Publish to YouTube after generation")
    parser.add_argument("--publish-existing", type=str, default="",
                        help="Publish existing pipeline by ID")
    parser.add_argument("--privacy", type=str, default="private",
                        choices=["private", "unlisted", "public"],
                        help="YouTube privacy status")
    parser.add_argument("--playlist", type=str, default="", help="YouTube playlist ID")
    parser.add_argument("--analytics", type=str, nargs="?", const="", default=None,
                        help="Collect analytics (optionally: video_id)")
    parser.add_argument("--pipeline-id", type=str, default="",
                        help="Pipeline ID for analytics/dashboard lookup")
    parser.add_argument("--dashboard", action="store_true", help="Show publishing dashboard")
    parser.add_argument("--check-auth", action="store_true", help="Check YouTube auth status")
    parser.add_argument("--list-playlists", action="store_true", help="List YouTube playlists")
    parser.add_argument("--run-daily-job", action="store_true", help="Run daily analytics collection + feedback loop")
    parser.add_argument("--run-intelligence", action="store_true", help="Run full daily intelligence cycle (11 stages)")
    parser.add_argument("--run-feedback", action="store_true", help="Run feedback cycle: outcomes → error analysis → weight update")
    parser.add_argument("--run-experiments", action="store_true", help="Run experiment engine: generate hypotheses + evaluate (Phase 3)")
    parser.add_argument("--plan-week", action="store_true", help="Generate weekly publishing plan (Phase 6)")
    parser.add_argument("--build-graph", action="store_true", help="Build knowledge graph from existing data (Phase 7)")
    parser.add_argument("--run-forecast", action="store_true", help="Generate prediction forecasts (Phase 8)")
    parser.add_argument("--analyze-patterns", action="store_true", help="Run pattern analysis on stored data")
    parser.add_argument("--drift-report", action="store_true", help="Show performance drift report (learning validation)")
    parser.add_argument("--evolution-dashboard", action="store_true", help="Show A/B Evolution Dashboard")
    parser.add_argument("--execute-brain", action="store_true", help="Run autonomous cycle: brain -> topic -> pipeline -> publish -> log")
    parser.add_argument("--no-publish", action="store_true", help="Skip YouTube publishing (pipeline only)")
    parser.add_argument("--selection-run", action="store_true", help="Run selection pressure cycle (classify → reinforce → suppress → expand)")
    parser.add_argument("--selection-status", action="store_true", help="Show selection pressure status")
    parser.add_argument("--ab-run", action="store_true", help="Run A/B rotation cycle")
    parser.add_argument("--ab-status", action="store_true", help="Show A/B test status")
    parser.add_argument("--ab-seed", type=str, default="", help="Seed A/B variants for a pipeline ID")
    parser.add_argument("--distribute", action="store_true", help="Run distribution agent: playlists, cross-links, dead video revision, pinned comments")

    # Production commands
    parser.add_argument("--job-status", type=str, default="", help="Query job status by ID")
    parser.add_argument("--job-list", action="store_true", help="List recent jobs")
    parser.add_argument("--job-cancel", type=str, default="", help="Cancel a running/paused job")
    parser.add_argument("--job-retry", type=str, default="", help="Retry a failed job")
    parser.add_argument("--resume-all", action="store_true", help="Resume all unfinished pipelines")
    parser.add_argument("--detect-unfinished", action="store_true", help="Detect and list unfinished pipelines")
    parser.add_argument("--recover", action="store_true", help="Recover unfinished pipelines (prompts per pipeline)")

    # Channel Manager commands
    parser.add_argument("--channel-status", action="store_true", help="Show Channel Manager status")
    parser.add_argument("--channel-calendar", type=int, nargs="?", const=30, default=0,
                        help="Show publishing calendar (optionally: days)")
    parser.add_argument("--channel-run", action="store_true", help="Run full Channel Manager daily cycle")
    parser.add_argument("--channel-content", type=str, nargs="?", const="", default=None,
                        help="List content (optionally: content_id)")
    parser.add_argument("--channel-advance", type=str, nargs=2, metavar=("CONTENT_ID", "STATE"),
                        help="Advance content to a new state")
    parser.add_argument("--channel-governance", action="store_true", help="Show governance rules")

    # Operations Hub commands
    parser.add_argument("--ops-status", action="store_true", help="Show Autonomous Operations Hub status")
    parser.add_argument("--ops-history", type=int, nargs="?", const=20, default=0,
                        help="Show operation execution history (optionally: limit)")
    parser.add_argument("--ops-run", type=str, default="", help="Run an operation by type (e.g. daily_analytics)")
    parser.add_argument("--ops-schedule", action="store_true", help="Register all operations with the scheduler")
    parser.add_argument("--ops-recover", action="store_true", help="Recover failed operations")

    # Executive Agent commands
    parser.add_argument("--executive-run", action="store_true", help="Run one executive cycle")
    parser.add_argument("--executive-status", action="store_true", help="Show Executive Agent status")
    parser.add_argument("--executive-plan", action="store_true", help="Show current executive plan")
    parser.add_argument("--executive-policy", type=str, nargs="?", const="", default=None,
                        help="Show or set executive policy (set: conservative/balanced/aggressive/growth)")
    parser.add_argument("--executive-start", action="store_true", help="Start continuous executive loop")
    parser.add_argument("--executive-stop", action="store_true", help="Stop continuous executive loop")
    parser.add_argument("--executive-memory", action="store_true", help="Show executive memory stats")

    # GitHub Automation commands
    parser.add_argument("--github-status", action="store_true", help="Show GitHub Actions status")
    parser.add_argument("--github-workflows", action="store_true", help="List registered GitHub workflows")
    parser.add_argument("--github-dispatch", type=str, default="", help="Dispatch a GitHub workflow by ID")
    parser.add_argument("--github-retry", type=str, default="", help="Retry a failed GitHub workflow run")
    parser.add_argument("--github-logs", type=str, default="", help="Show logs for a GitHub workflow run")
    parser.add_argument("--github-artifacts", action="store_true", help="List GitHub workflow artifacts")
    parser.add_argument("--github-secrets", action="store_true", help="Validate GitHub secrets and config")
    parser.add_argument("--github-monitor", action="store_true", help="Show GitHub monitoring metrics")

    # Content Intelligence commands
    parser.add_argument("--content-library", action="store_true", help="Show content library")
    parser.add_argument("--content-assets", action="store_true", help="Show content assets")
    parser.add_argument("--content-optimize", action="store_true", help="Run content optimization")
    parser.add_argument("--content-refresh", action="store_true", help="Check content freshness")
    parser.add_argument("--content-repurpose", action="store_true", help="Generate repurpose suggestions")
    parser.add_argument("--content-recommendations", action="store_true", help="Show content recommendations")
    parser.add_argument("--content-seo", action="store_true", help="Show SEO report")
    parser.add_argument("--content-lifecycle", action="store_true", help="Show content lifecycle")
    parser.add_argument("--content-archive", action="store_true", help="Show archived content")
    parser.add_argument("--content-report", action="store_true", help="Show full content library report")

    # Business Intelligence commands
    parser.add_argument("--business-status", action="store_true", help="Show business status")
    parser.add_argument("--business-goals", action="store_true", help="Show business goals")
    parser.add_argument("--business-revenue", action="store_true", help="Show revenue summary")
    parser.add_argument("--business-budget", action="store_true", help="Show budget status")
    parser.add_argument("--business-forecast", action="store_true", help="Show revenue forecast")
    parser.add_argument("--business-campaigns", action="store_true", help="Show campaigns")
    parser.add_argument("--business-report", action="store_true", help="Show full business report")

    # YouTube Intelligence commands
    parser.add_argument("--yt-health", action="store_true", help="Show YouTube channel health score")
    parser.add_argument("--yt-growth", action="store_true", help="Show YouTube growth analysis")
    parser.add_argument("--yt-retention", action="store_true", help="Show YouTube retention analysis")
    parser.add_argument("--yt-ctr", action="store_true", help="Show YouTube CTR analysis")
    parser.add_argument("--yt-audience", action="store_true", help="Show YouTube audience insights")
    parser.add_argument("--yt-benchmarks", action="store_true", help="Show YouTube benchmarks")
    parser.add_argument("--yt-competition", action="store_true", help="Show YouTube competition report")
    parser.add_argument("--yt-recommendations", action="store_true", help="Show YouTube recommendations")
    parser.add_argument("--yt-status", action="store_true", help="Show YouTube Intelligence status")
    parser.add_argument("--yt-full-analysis", action="store_true", help="Run full YouTube analysis")

    args = parser.parse_args()

    if args.api:
        import uvicorn
        logger.info(f"Starting API on {args.host}:{args.port} (workers={args.api_workers}, reload={args.api_reload})")
        uvicorn.run(
            "mindmargin.api.server:app",
            host=args.host,
            port=args.port,
            workers=args.api_workers if not args.api_reload else 1,
            reload=args.api_reload,
        )
        return

    # Standalone commands (no topic required)
    if args.dashboard:
        _do_dashboard()
        return

    if args.evolution_dashboard:
        _do_evolution_dashboard()
        return

    if args.drift_report:
        _do_drift_report()
        return

    if args.ab_run:
        from mindmargin.analytics.ab_testing import run_ab_rotation_cycle
        result = run_ab_rotation_cycle(dry_run=False)
        print(f"\n  AB rotation: {result['status']}")
        print(f"  Actions: {result.get('actions_taken', 0)}")
        print(f"  Active tests: {result.get('active_tests', 0)}")
        for a in result.get("actions", [])[:5]:
            print(f"    - {a}")
        return

    if args.ab_status:
        from mindmargin.analytics.memory import get_active_ab_tests, get_pending_ab_tests
        from mindmargin.analytics.ab_testing import _fetch_video_analytics
        active = get_active_ab_tests()
        pending = get_pending_ab_tests()
        print(f"\n  A/B Test Status:")
        print(f"  Active:  {len(active)}")
        print(f"  Pending: {len(pending)}")
        for t in active[:10]:
            try:
                metrics = _fetch_video_analytics(t["video_id"])
                print(f"    [ACTIVE] [{t['variant_type']}] #{t['variant_index']} "
                      f"video={t['video_id'][:8]} ctr={metrics['ctr']:.1f}% "
                      f"imp={metrics['impressions']}")
            except Exception as e:
                print(f"    [ACTIVE] [{t['variant_type']}] #{t['variant_index']} "
                      f"video={t['video_id'][:8]} (analytics pending)")
        for t in pending[:10]:
            print(f"    [PENDING] [{t['variant_type']}] #{t['variant_index']} "
                  f"video={t['video_id'][:8]}")
        return

    if args.execute_brain:
        from mindmargin.agents.decision_executor import execute_top_decision, format_execution_report
        result = execute_top_decision(quick=args.quick, auto_publish=not args.no_publish)
        report = format_execution_report(result)
        print(report)
        return

    if args.selection_run:
        from mindmargin.analytics.selection import run_selection_cycle, format_selection_report
        result = run_selection_cycle()
        report = format_selection_report(result)
        print(report)
        return

    if args.selection_status:
        from mindmargin.analytics.selection import get_evolution_memory_summary
        summary = get_evolution_memory_summary()
        bar = "=" * 55
        print(f"\n{bar}")
        print(f"  SELECTION PRESSURE STATUS")
        print(bar)
        print(f"  Classifications:")
        for c in ("winner_candidate", "keep_testing", "stable_equivalent", "weak_signal", "insufficient_signal"):
            count = summary["classifications"].get(c, 0)
            print(f"    {c:22s}: {count}")
        print(f"  Total classified: {summary['total_classified']}")
        print(f"  Reinforced patterns: {summary['reinforced_count']}")
        print(f"  Suppressed patterns: {summary['suppressed_count']}")
        print(f"  Dead patterns:       {summary['dead_count']}")
        if summary["dominant_archetypes"]:
            print(f"  Dominant archetypes:")
            for a in summary["dominant_archetypes"]:
                print(f"    {a['archetype']:20s} "
                      f"{a['dominance_pct']:.0f}% ({a['sample_size']} samples)")
        suggestions = [l for l in summary["topic_suggestions"][:5]
                       if not l.get("is_published")]
        if suggestions:
            print(f"  Suggested topics:")
            for s in suggestions:
                print(f"    -> {s['child_topic'][:50]} "
                      f"(conf: {s['confidence']:.0%}, "
                      f"inherit: {s['performance_inheritance']:.1f})")
        print(bar)
        return

    if args.ab_seed:
        from mindmargin.analytics.ab_testing import seed_variants
        from mindmargin.analytics.memory import _get_db
        conn = _get_db()
        row = conn.execute(
            "SELECT youtube_video_id FROM pipelines WHERE id = ?",
            (args.ab_seed,)
        ).fetchone()
        if row and row["youtube_video_id"]:
            n = seed_variants(args.ab_seed, row["youtube_video_id"])
            print(f"\n  Seeded {n} variants for pipeline {args.ab_seed}")
        else:
            print(f"\n  Pipeline {args.ab_seed} not found")
        return

    if args.run_intelligence:
        from mindmargin.jobs.daily_intelligence import run_daily_intelligence_job
        result = run_daily_intelligence_job()
        print(f"\n  Daily intelligence job: {result['status']}")
        stages = result.get("stages", {})
        for stage, info in stages.items():
            status = info.get("status", "?")
            detail = ""
            if stage == "scoring":
                detail = f" ({info.get('candidates', 0)} candidates)"
            elif stage == "performance":
                detail = f" ({info.get('insights', 0)} insights)"
            elif stage == "learning":
                detail = f" ({info.get('rules', 0)} rules)"
            elif stage == "memory":
                detail = f" ({info.get('new_entries', 0)} entries)"
            elif stage == "strategy":
                detail = f" (top: {info.get('top_pick', '')})"
            elif stage == "feedback":
                detail = f" ({info.get('outcomes_collected', 0)} outcomes, {info.get('weights_changed', 0)} changed)"
            elif stage == "experiments":
                detail = f" ({info.get('new_hypotheses', 0)} new, {info.get('completed', 0)} completed)"
            elif stage == "knowledge_graph":
                detail = f" ({info.get('topics', 0)} topics, {info.get('relationships', 0)} rels)"
            elif stage == "forecasts":
                detail = f" ({info.get('forecasts', 0)} forecasts)"
            elif stage == "weekly_plan":
                detail = f" ({info.get('items', 0)} items)" if info.get('items') else f" ({info.get('reason', '')})"
            elif stage == "weekly_report":
                detail = f" ({info.get('week', info.get('reason', ''))})"
            print(f"    {stage:20s}: {status}{detail}")
        return

    if args.run_feedback:
        from mindmargin.intelligence.feedback_engine import run_feedback_cycle
        result = run_feedback_cycle()
        outcomes = result.get("outcomes_collected", 0)
        changed = result.get("weights_changed", 0)
        print(f"\n  Feedback cycle: {outcomes} outcomes, {changed} weights changed")
        for comp, delta in result.get("weight_deltas", {}).items():
            old = delta.get("old", 0)
            new = delta.get("new", 0)
            arrow = "↑" if new > old else "↓"
            print(f"    {comp:20s}: {old:.3f} {arrow} {new:.3f}")
        return

    if args.run_experiments:
        from mindmargin.intelligence.experiments import run_experiment_cycle
        result = run_experiment_cycle()
        print(f"\n  Experiment engine: {result['new_hypotheses']} new hypotheses, "
              f"{result['experiments_completed']} completed")
        return

    if args.plan_week:
        from mindmargin.intelligence.planner import plan_week
        plan = plan_week()
        items = plan.get("summary", {}).get("total_items", 0)
        print(f"\n  Weekly plan generated: {items} items across "
              f"{plan.get('summary', {}).get('days_active', 0)} days")
        for entry in plan.get("schedule", [])[:10]:
            print(f"    {entry['day']:10s} {entry['format_label']:20s} {entry['topic'][:50]}")
        return

    if args.build_graph:
        from mindmargin.intelligence.knowledge_graph import build_knowledge_graph
        result = build_knowledge_graph()
        print(f"\n  Knowledge graph: {result['topics_found']} topics, "
              f"{result['keywords_extracted']} keywords, "
              f"{result['relationships_created']} relationships")
        return

    if args.run_forecast:
        from mindmargin.intelligence.horizon import forecast_all
        forecasts = forecast_all()
        windows = {}
        for f in forecasts:
            w = f["window_days"]
            windows.setdefault(w, []).append(f)
        print(f"\n  Prediction forecasts: {len(forecasts)} across {len(windows)} windows")
        for w in sorted(windows):
            print(f"    {w:2d}-day window: {len(windows[w])} topics")
        return

    if args.run_daily_job:
        import os, shutil
        from datetime import datetime
        from pathlib import Path
        cutoff = datetime.now().timestamp() - 86400
        temp_dir = Path(os.environ.get("TEMP", "")) / "mindmargin_output"
        if temp_dir.exists():
            for p in temp_dir.iterdir():
                if p.is_file() and p.stat().st_mtime < cutoff:
                    p.unlink(missing_ok=True)
                elif p.is_dir() and p.stat().st_mtime < cutoff:
                    shutil.rmtree(p, ignore_errors=True)
        from mindmargin.jobs.daily_analytics import run_daily_job
        result = run_daily_job()
        print(f"\n  Daily analytics job: {result['status']}")
        print(f"  Videos collected: {result.get('analytics_collected', 0)}")
        print(f"  Best practices: {result.get('total_best_practices', 0)}")
        return

    if args.distribute:
        from mindmargin.agents.distribution import DistributionAgent
        agent = DistributionAgent()
        result = agent.run_all()
        bar = "=" * 55
        print(f"\n{bar}")
        print(f"  DISTRIBUTION AGENT RESULTS")
        print(bar)
        print(f"  Playlists created:    {result.get('playlists_created', 0)}")
        print(f"  Videos added:         {result.get('videos_added', 0)}")
        print(f"  Descriptions updated: {result.get('descriptions_updated', 0)}")
        print(f"  Dead videos revised:  {result.get('dead_revised', 0)}")
        print(f"  Comments posted:      {result.get('comments_posted', 0)}")
        print(bar)
        return

    # ── Channel Manager commands ──

    if args.channel_status:
        from mindmargin.channel.manager import ChannelManager
        mgr = ChannelManager()
        report = mgr.get_status()
        bar = "=" * 55
        print(f"\n{bar}")
        print(f"  CHANNEL MANAGER STATUS")
        print(bar)
        print(f"  Status:           {report.status.upper()}")
        print(f"  Active content:   {report.active_content}")
        print(f"  Published today:  {report.published_today}")
        print(f"  Scheduled:        {report.scheduled_count}")
        print(f"  Health score:     {report.health_score:.1f}/10")
        print(f"  Total items:      {report.total_items}")
        print(f"  Governance rules: {report.governance_rules_active} active")
        print(f"  Calendar:         {report.calendar_7day}d7 / {report.calendar_30day}d30 / {report.calendar_90day}d90")
        if report.state_breakdown:
            print(f"\n  State breakdown:")
            for state, count in sorted(report.state_breakdown.items()):
                if count:
                    print(f"    {state:15s}: {count}")
        if report.format_balance:
            print(f"\n  Format balance:")
            for fmt, count in report.format_balance.items():
                print(f"    {fmt:10s}: {count}")
        print(bar)
        return

    if args.channel_calendar:
        from mindmargin.channel.manager import ChannelManager
        days = args.channel_calendar
        mgr = ChannelManager()
        entries = mgr.get_calendar(days)
        bar = "=" * 55
        print(f"\n{bar}")
        print(f"  PUBLISHING CALENDAR  ({days} days, {len(entries)} entries)")
        print(bar)
        for e in entries:
            print(f"  [{e.format.upper():6s}] {e.publish_time[:16] if e.publish_time else '':16s}  "
                  f"{e.topic[:50]}")
        print(bar)
        return

    if args.channel_run:
        from mindmargin.channel.manager import ChannelManager
        mgr = ChannelManager()
        print(f"\n  Running Channel Manager daily cycle...")
        result = mgr.run_daily_cycle()
        bar = "=" * 55
        print(f"\n{bar}")
        print(f"  CHANNEL DAILY CYCLE RESULT")
        print(bar)
        print(f"  Status: {result.get('status', '?')}")
        for step_name, info in result.get("steps", {}).items():
            status = info.get("status", "?")
            detail = {k: v for k, v in info.items() if k != "status"}
            detail_str = " ".join(f"{k}={v}" for k, v in detail.items())
            print(f"    {step_name:15s}: {status}  {detail_str}")
        print(bar)
        return

    if args.channel_content is not None:
        from mindmargin.channel.manager import ChannelManager
        content_id = args.channel_content if args.channel_content else ""
        mgr = ChannelManager()
        items = mgr.get_content(content_id=content_id or None)
        bar = "=" * 55
        print(f"\n{bar}")
        print(f"  CHANNEL CONTENT ({len(items)} items)")
        print(bar)
        for item in items:
            print(f"  [{item['state']:12s}] {item['topic'][:50]:50s}  {item['format'][:5]}")
        print(bar)
        return

    if args.channel_advance:
        from mindmargin.channel.manager import ChannelManager
        content_id, target_state = args.channel_advance
        mgr = ChannelManager()
        item = mgr.get_content(content_id=content_id)
        if not item:
            print(f"\n  Content not found: {content_id}")
            return
        prev = item[0].get("state", "?")
        ok = mgr.advance_content(content_id, target_state)
        print(f"\n  Content: {content_id}")
        print(f"  State:   {prev} -> {target_state}  [{ 'OK' if ok else 'FAILED' }]")
        return

    if args.channel_governance:
        from mindmargin.channel.manager import ChannelManager
        mgr = ChannelManager()
        rules = mgr.get_governance_rules()
        bar = "=" * 55
        print(f"\n{bar}")
        print(f"  GOVERNANCE RULES ({len(rules)} total)")
        print(bar)
        for r in rules:
            enabled = "+" if r["enabled"] else "-"
            print(f"  [{enabled}] {r['rule_id'][:30]:30s} {r['rule_type'][:25]:25s} "
                  f"value={r['parameters'].get('value', r['parameters'].get('max', '?'))}")
        print(bar)
        return

    # ── Executive Agent commands ──

    if args.executive_run:
        from mindmargin.executive.agent import ExecutiveAgent
        agent = ExecutiveAgent()
        print(f"\n  Running Executive cycle...")
        result = agent.run_once()
        bar = "=" * 55
        print(f"\n{bar}")
        print(f"  EXECUTIVE CYCLE RESULT")
        print(bar)
        print(f"  Status:     {result.get('status', '?')}")
        print(f"  Cycle:      {result.get('cycle', 0)}")
        print(f"  Problems:   {len(result.get('problems', []))}")
        for p in result.get("problems", []):
            print(f"    ! {p}")
        print(f"  Opportunities: {len(result.get('opportunities', []))}")
        for o in result.get("opportunities", []):
            print(f"    + {o}")
        decision = result.get("decision")
        if decision:
            print(f"  Decision:   {decision.get('selected_action', '?')}")
            print(f"  Priority:   {decision.get('priority', '?')}")
            print(f"  Reason:     {decision.get('reason', '?')}")
            print(f"  Policy:     {decision.get('policy_applied', '?')}")
        actions = result.get("actions_executed", [])
        if actions:
            print(f"\n  Actions executed ({len(actions)}):")
            for a in actions:
                print(f"    [{a.get('status', '?')}] {a.get('action_type', '?')} "
                      f"({a.get('duration_s', 0):.1f}s)")
        print(bar)
        return

    if args.executive_status:
        from mindmargin.executive.agent import ExecutiveAgent
        agent = ExecutiveAgent()
        data = agent.get_status()
        bar = "=" * 55
        print(f"\n{bar}")
        print(f"  EXECUTIVE AGENT STATUS")
        print(bar)
        print(f"  Running:    {data.get('running', False)}")
        print(f"  Cycles:     {data.get('cycle_count', 0)}")
        print(f"  Policy:     {data.get('policy', '?')}")
        mem = data.get("memory", {})
        print(f"  Memory:     {mem.get('total', 0)} entries")
        last_dec = data.get("last_decision")
        if last_dec:
            print(f"  Last decision: {last_dec.get('selected_action', '?')} "
                  f"[{last_dec.get('priority', '?')}]")
        print(bar)
        return

    if args.executive_plan:
        from mindmargin.executive.agent import ExecutiveAgent
        agent = ExecutiveAgent()
        data = agent.get_plan()
        bar = "=" * 55
        print(f"\n{bar}")
        print(f"  EXECUTIVE PLAN")
        print(bar)
        print(f"  Summary: {data.get('snapshot_summary', '?')}")
        print(f"  Generated: {data.get('generated_at', '?')[:19]}")
        actions = data.get("actions", [])
        if actions:
            print(f"\n  Actions ({len(actions)}):")
            for a in actions:
                print(f"    [{a.get('priority', '?'):8s}] {a.get('action_type', '?'):30s} "
                      f"impact={a.get('estimated_impact', 0):.2f}")
                print(f"             {a.get('reason', '')}")
        else:
            print(f"  No actions planned")
        print(bar)
        return

    if args.executive_policy is not None:
        from mindmargin.executive.agent import ExecutiveAgent
        agent = ExecutiveAgent()
        if args.executive_policy and args.executive_policy != "":
            policy_type = args.executive_policy
            valid = ["conservative", "balanced", "aggressive", "growth"]
            if policy_type not in valid:
                print(f"\n  Invalid policy: {policy_type}")
                print(f"  Valid policies: {valid}")
                return
            result = agent.set_policy(policy_type)
            print(f"\n  Policy set to: {policy_type}")
        else:
            data = agent.get_policy()
            bar = "=" * 55
            print(f"\n{bar}")
            print(f"  EXECUTIVE POLICY")
            print(bar)
            print(f"  Type:          {data.get('policy_type', '?')}")
            print(f"  Publish freq:  {data.get('publishing_frequency_hours', 0)}h")
            print(f"  Risk tolerance: {data.get('risk_tolerance', 0):.0%}")
            print(f"  Experiment freq: {data.get('experiment_frequency_hours', 0)}h")
            print(f"  Budget:        {data.get('budget_usage_pct', 0):.0f}%")
            print(f"  Auto approve:  {data.get('auto_approve_threshold', 0):.0%}")
            print(f"  Max concurrent: {data.get('max_concurrent_workflows', 0)}")
            print(f"  Auto publish:  {data.get('enable_auto_publish', False)}")
            print(f"  Auto experiments: {data.get('enable_auto_experiments', False)}")
            print(f"  Description:   {data.get('description', '')}")
            print(bar)
        return

    if args.executive_start:
        from mindmargin.executive.agent import ExecutiveAgent
        agent = ExecutiveAgent()
        print(f"\n  Starting Executive continuous loop (300s intervals)...")
        print(f"  Press Ctrl+C to stop")
        try:
            agent.start_loop()
            import time
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            agent.stop_loop()
            print(f"\n  Executive loop stopped.")
        return

    if args.executive_stop:
        print(f"\n  Executive loop stop requested.")
        return

    if args.executive_memory:
        from mindmargin.executive.agent import ExecutiveAgent
        agent = ExecutiveAgent()
        data = agent.get_memory()
        bar = "=" * 55
        print(f"\n{bar}")
        print(f"  EXECUTIVE MEMORY")
        print(bar)
        print(f"  Total entries: {data.get('total', 0)}")
        if data.get("oldest"):
            print(f"  Oldest: {data.get('oldest', '')[:19]}")
        if data.get("newest"):
            print(f"  Newest: {data.get('newest', '')[:19]}")
        cats = data.get("categories", {})
        if cats:
            print(f"\n  By category:")
            for cat, count in sorted(cats.items(), key=lambda x: x[1], reverse=True):
                print(f"    {cat:30s}: {count}")
        print(bar)
        return

    # ── GitHub Automation commands ──
    if args.github_status:
        from mindmargin.github.controller import GitHubController
        ctrl = GitHubController()
        status = ctrl.get_status()
        bar = "=" * 55
        print(f"\n{bar}")
        print(f"  GITHUB ACTIONS STATUS")
        print(bar)
        print(f"  Total runs:       {status.total_runs}")
        print(f"  Active runs:      {status.active_runs}")
        print(f"  Completed today:  {status.completed_today}")
        print(f"  Failed today:     {status.failed_today}")
        print(f"  Success rate:     {status.success_rate:.1f}%")
        print(f"  Avg duration:     {status.avg_duration_s:.1f}s")
        print(f"  Workflows:        {status.registry_workflows}")
        print(f"  Artifacts:        {status.artifacts_count}")
        print(f"  Runners:          {status.runners_available} available")
        print(f"  Health:           {status.health_score:.1f}/100")
        print(bar)
        return

    if args.github_workflows:
        from mindmargin.github.controller import GitHubController
        ctrl = GitHubController()
        defs = ctrl.registry.list_all()
        bar = "=" * 70
        print(f"\n{bar}")
        print(f"  REGISTERED GITHUB WORKFLOWS")
        print(bar)
        print(f"  {'ID':<25s} {'Name':<30s} {'Priority':<10s} {'Enabled'}")
        print(f"  {'-'*25} {'-'*30} {'-'*10} {'-'*7}")
        for d in defs:
            print(f"  {d.workflow_id:<25s} {d.name:<30s} {d.priority.value:<10s} {d.enabled}")
        print(f"\n  Total: {len(defs)} workflows")
        print(bar)
        return

    if args.github_dispatch:
        from mindmargin.github.controller import GitHubController
        from mindmargin.github.dispatcher import WorkflowDispatcher
        ctrl = GitHubController()
        dispatcher = WorkflowDispatcher(ctrl)
        result = dispatcher.dispatch(args.github_dispatch, trigger="cli")
        bar = "=" * 55
        print(f"\n{bar}")
        print(f"  WORKFLOW DISPATCH")
        print(bar)
        print(f"  Dispatched: {result.dispatched}")
        print(f"  Run ID:     {result.run_id}")
        print(f"  Workflow:   {result.workflow_name}")
        print(f"  Reason:     {result.reason}")
        print(bar)
        return

    if args.github_retry:
        from mindmargin.github.controller import GitHubController
        ctrl = GitHubController()
        result = ctrl.retry_workflow(args.github_retry)
        bar = "=" * 55
        print(f"\n{bar}")
        print(f"  WORKFLOW RETRY")
        print(bar)
        print(f"  Status:     {result.get('status', 'unknown')}")
        print(f"  Run ID:     {args.github_retry}")
        diagnosis = result.get("diagnosis", {})
        if diagnosis:
            print(f"  Failure:    {diagnosis.get('overall_failure_type', 'unknown')}")
            print(f"  Recommend:  {diagnosis.get('recommendation', 'N/A')}")
        print(bar)
        return

    if args.github_logs:
        from mindmargin.github.controller import GitHubController
        ctrl = GitHubController()
        logs = ctrl.get_workflow_logs(args.github_logs)
        bar = "=" * 55
        print(f"\n{bar}")
        print(f"  WORKFLOW LOGS: {args.github_logs}")
        print(bar)
        if "error" in logs:
            print(f"  Error: {logs['error']}")
        else:
            job_logs = logs.get("job_logs", {})
            for jid, jlog in job_logs.items():
                if jlog:
                    print(f"\n  --- {jid} ---")
                    print(f"  {jlog[:500]}")
        print(bar)
        return

    if args.github_artifacts:
        from mindmargin.github.controller import GitHubController
        ctrl = GitHubController()
        arts = ctrl.artifacts.list_artifacts()
        bar = "=" * 70
        print(f"\n{bar}")
        print(f"  GITHUB ARTIFACTS")
        print(bar)
        if not arts:
            print(f"  No artifacts stored.")
        else:
            print(f"  {'ID':<30s} {'Name':<25s} {'Type':<12s} {'Size'}")
            print(f"  {'-'*30} {'-'*25} {'-'*12} {'-'*10}")
            for a in arts[:20]:
                print(f"  {a.artifact_id:<30s} {a.name:<25s} {a.artifact_type.value:<12s} {a.size_bytes:,}B")
            print(f"\n  Total: {len(arts)} artifacts")
        stats = ctrl.artifacts.get_stats()
        print(f"  Total size: {stats['total_size_bytes']:,} bytes")
        print(bar)
        return

    if args.github_secrets:
        from mindmargin.github.controller import GitHubController
        ctrl = GitHubController()
        result = ctrl.secrets.validate_all()
        bar = "=" * 55
        print(f"\n{bar}")
        print(f"  GITHUB SECRETS VALIDATION")
        print(bar)
        secrets_data = result.get("secrets", {})
        print(f"  Overall valid: {result.get('overall_valid', False)}")
        print(f"  Checks:  {secrets_data.get('passed', 0)}/{secrets_data.get('total_checks', 0)} passed")
        print(f"  Failed:  {secrets_data.get('failed', 0)}")
        print(f"  Warnings: {secrets_data.get('warnings', 0)}")
        for check in secrets_data.get("checks", []):
            status = "OK" if check["status"] == "set" else "MISSING"
            print(f"    [{status}] {check['name']}")
        print(bar)
        return

    if args.github_monitor:
        from mindmargin.github.controller import GitHubController
        ctrl = GitHubController()
        health = ctrl.monitor.get_health_report()
        summary = ctrl.monitor.get_summary()
        bar = "=" * 55
        print(f"\n{bar}")
        print(f"  GITHUB MONITORING")
        print(bar)
        print(f"  Status:      {health['status']}")
        print(f"  Health:      {health['health_score']}/100")
        print(f"  Metrics:     {health['total_metrics']}")
        print(f"  Alerts:      {health['total_alerts']}")
        counters = summary.get("counters", {})
        if counters:
            print(f"\n  Counters:")
            for key, val in sorted(counters.items()):
                print(f"    {key}: {val}")
        print(bar)
        return

    # ── Content Intelligence commands ──

    if args.content_library:
        from mindmargin.content.library import ContentLibrary
        from mindmargin.content.models import ContentLifecycleState
        lib = ContentLibrary()
        items = lib.list_items(limit=50)
        bar = "=" * 65
        print(f"\n{bar}")
        print(f"  CONTENT LIBRARY ({lib.get_total_count()} items)")
        print(bar)
        print(f"  By state: {lib.count_by_state()}")
        print(f"  By category: {lib.count_by_category()}")
        print(f"\n  {'ID':<16s} {'Topic':<30s} {'State':<14s} {'Views'}")
        print(f"  {'-'*15} {'-'*29} {'-'*13} {'-'*8}")
        for it in items:
            print(f"  {it.content_id[:15]:16s} {it.topic[:30]:30s} "
                  f"{it.lifecycle_state.value:14s} {it.total_views}")
        print(bar)
        return

    if args.content_assets:
        from mindmargin.content.assets import AssetManager
        mgr = AssetManager()
        stats = mgr.get_asset_stats()
        all_assets = mgr.list_all_assets(limit=50)
        bar = "=" * 65
        print(f"\n{bar}")
        print(f"  CONTENT ASSETS ({stats['total']} total)")
        print(bar)
        print(f"  By type: {stats['by_type']}")
        print(f"\n  {'ID':<16s} {'Type':<14s} {'Content ID':<16s} {'Version'}")
        print(f"  {'-'*15} {'-'*13} {'-'*15} {'-'*7}")
        for a in all_assets:
            print(f"  {a.asset_id[:15]:16s} {a.asset_type.value:14s} "
                  f"{a.content_id[:15]:16s} {a.version}")
        print(bar)
        return

    if args.content_optimize:
        from mindmargin.content.library import ContentLibrary
        from mindmargin.content.optimizer import ContentOptimizer
        lib = ContentLibrary()
        optimizer = ContentOptimizer()
        items = lib.list_items(limit=200)
        report = optimizer.get_optimization_report(items)
        bar = "=" * 55
        print(f"\n{bar}")
        print(f"  CONTENT OPTIMIZATION REPORT")
        print(bar)
        print(f"  Total items:     {report['total_items']}")
        print(f"  Best performing: {report['best_performing_count']}")
        print(f"  Underperforming: {report['underperforming_count']}")
        print(f"  Forgotten:       {report['forgotten_count']}")
        print(f"  Viral:           {report['viral_count']}")
        print(f"  Evergreen:       {report['evergreen_count']}")
        print(f"  Decaying:        {report['decaying_count']}")
        print(f"  Opportunity:     {report['opportunity_count']}")
        print(bar)
        return

    if args.content_refresh:
        from mindmargin.content.library import ContentLibrary
        from mindmargin.content.lifecycle import ContentLifecycleManager
        lib = ContentLibrary()
        lifecycle = ContentLifecycleManager()
        items = lib.list_items(limit=200)
        needs = []
        for it in items:
            if lifecycle.detect_needs_refresh(it):
                needs.append(it)
        bar = "=" * 55
        print(f"\n{bar}")
        print(f"  CONTENT FRESHNESS CHECK ({len(needs)} need refresh)")
        print(bar)
        for it in needs[:20]:
            print(f"  [{it.lifecycle_state.value:12s}] {it.topic[:40]:40s} "
                  f"fresh={it.freshness_score:.2f} vel={it.view_velocity:.2f}")
        if not needs:
            print(f"  All content is fresh")
        print(bar)
        return

    if args.content_repurpose:
        from mindmargin.content.library import ContentLibrary
        from mindmargin.content.repurpose import ContentRepurposer
        lib = ContentLibrary()
        repurposer = ContentRepurposer()
        items = lib.list_items(limit=50)
        all_suggestions = []
        for it in items:
            suggestions = repurposer.generate_suggestions(it)
            all_suggestions.extend(suggestions)
        repurposer.save_suggestions(all_suggestions)
        bar = "=" * 55
        print(f"\n{bar}")
        print(f"  REPURPOSE SUGGESTIONS ({len(all_suggestions)} generated)")
        print(bar)
        by_fmt = {}
        for s in all_suggestions:
            by_fmt[s.target_format.value] = by_fmt.get(s.target_format.value, 0) + 1
        for fmt, count in sorted(by_fmt.items(), key=lambda x: x[1], reverse=True):
            print(f"    {fmt:20s}: {count}")
        print(bar)
        return

    if args.content_recommendations:
        from mindmargin.content.library import ContentLibrary
        from mindmargin.content.recommendations import RecommendationEngine
        lib = ContentLibrary()
        engine = RecommendationEngine()
        items = lib.list_items(limit=200)
        recs = engine.generate_all_recommendations(items)
        stats = engine.get_recommendation_stats()
        bar = "=" * 65
        print(f"\n{bar}")
        print(f"  CONTENT RECOMMENDATIONS ({len(recs)} generated)")
        print(bar)
        print(f"  By type:")
        for t, count in sorted(stats["by_type"].items(), key=lambda x: x[1], reverse=True):
            print(f"    {t:30s}: {count}")
        print(f"\n  Top 10:")
        for rec in recs[:10]:
            print(f"    [P{rec.priority}] {rec.recommendation_type.value:25s} "
                  f"{rec.title[:40]}")
        print(bar)
        return

    if args.content_seo:
        from mindmargin.content.library import ContentLibrary
        from mindmargin.content.seo_refresh import SEORefreshEngine
        lib = ContentLibrary()
        seo = SEORefreshEngine()
        items = lib.list_items(limit=200)
        report = seo.generate_seo_report(items)
        bar = "=" * 55
        print(f"\n{bar}")
        print(f"  SEO REPORT")
        print(bar)
        print(f"  Total items:      {report['total_items']}")
        print(f"  Avg SEO score:    {report['avg_seo_score']:.3f}")
        print(f"  Low SEO count:    {report['low_seo_count']}")
        print(f"  Keyword overlaps: {report['keyword_overlaps']}")
        print(f"  Duplicate topics: {report['duplicate_topics']}")
        if report["top_keyword_overlaps"]:
            print(f"\n  Top keyword overlaps:")
            for o in report["top_keyword_overlaps"][:5]:
                print(f"    '{o['keyword']}' appears in {o['count']} items")
        if report["top_duplicate_topics"]:
            print(f"\n  Duplicate topics:")
            for d in report["top_duplicate_topics"][:5]:
                print(f"    '{d['topic']}' ({d['count']} items)")
        print(bar)
        return

    if args.content_lifecycle:
        from mindmargin.content.library import ContentLibrary
        from mindmargin.content.lifecycle import ContentLifecycleManager
        lib = ContentLibrary()
        lifecycle = ContentLifecycleManager()
        items = lib.list_items(limit=200)
        by_state = {}
        needs_refresh = 0
        archivable = 0
        for it in items:
            state = it.lifecycle_state.value
            by_state[state] = by_state.get(state, 0) + 1
            if lifecycle.detect_needs_refresh(it):
                needs_refresh += 1
            if lifecycle.detect_archivable([it]):
                archivable += 1
        bar = "=" * 55
        print(f"\n{bar}")
        print(f"  CONTENT LIFECYCLE ({len(items)} items)")
        print(bar)
        for state, count in sorted(by_state.items()):
            print(f"    {state:15s}: {count}")
        print(f"\n  Needs refresh:  {needs_refresh}")
        print(f"  Archivable:     {archivable}")
        print(bar)
        return

    if args.content_archive:
        from mindmargin.content.archive import ContentArchiver
        archiver = ContentArchiver()
        records = archiver.get_archive_records(limit=20)
        stats = archiver.get_archive_stats()
        bar = "=" * 55
        print(f"\n{bar}")
        print(f"  ARCHIVED CONTENT ({stats['total_archived']} items)")
        print(bar)
        print(f"  Total views when archived: {stats['total_views_when_archived']}")
        print(f"  Archive reasons: {stats['archive_reasons']}")
        for r in records[:15]:
            print(f"    [{r.get('archived_at', '')[:10]}] {r.get('topic', '')[:40]:40s} "
                  f"views={r.get('total_views', 0)} reason={r.get('reason', '')[:20]}")
        print(bar)
        return

    if args.content_report:
        from mindmargin.content.library import ContentLibrary
        from mindmargin.content.optimizer import ContentOptimizer
        from mindmargin.content.lifecycle import ContentLifecycleManager
        from mindmargin.content.recommendations import RecommendationEngine
        lib = ContentLibrary()
        optimizer = ContentOptimizer()
        lifecycle = ContentLifecycleManager()
        engine = RecommendationEngine()
        items = lib.list_items(limit=200)
        opt_report = optimizer.get_optimization_report(items)
        rec_stats = engine.get_recommendation_stats()
        bar = "=" * 60
        print(f"\n{bar}")
        print(f"  CONTENT LIBRARY REPORT")
        print(bar)
        print(f"  Total items:       {len(items)}")
        print(f"  By state:          {lib.count_by_state()}")
        print(f"  By category:       {lib.count_by_category()}")
        print(f"\n  Optimization:")
        print(f"    Best performing: {opt_report['best_performing_count']}")
        print(f"    Underperforming: {opt_report['underperforming_count']}")
        print(f"    Forgotten:       {opt_report['forgotten_count']}")
        print(f"    Viral:           {opt_report['viral_count']}")
        print(f"    Evergreen:       {opt_report['evergreen_count']}")
        print(f"    Decaying:        {opt_report['decaying_count']}")
        print(f"\n  Recommendations:")
        print(f"    Total:           {rec_stats['total']}")
        print(f"    Pending:         {rec_stats['pending']}")
        print(f"    Actioned:        {rec_stats['actioned']}")
        print(bar)
        return

    # ── Business Intelligence commands ──

    if args.business_status:
        from mindmargin.business.portfolio import BusinessPortfolio
        portfolio = BusinessPortfolio()
        status = portfolio.get_business_status()
        bar = "=" * 60
        print(f"\n{bar}")
        print(f"  BUSINESS STATUS")
        print(bar)
        print(f"  Revenue (30d):   ${status['total_revenue_30d']:>10.2f}")
        print(f"  Revenue (90d):   ${status['total_revenue_90d']:>10.2f}")
        print(f"  Revenue (365d):  ${status['total_revenue_365d']:>10.2f}")
        print(f"  Costs (30d):     ${status['total_costs_30d']:>10.2f}")
        print(f"  Costs (90d):     ${status['total_costs_90d']:>10.2f}")
        print(f"  Profit (30d):    ${status['profit_30d']:>10.2f}")
        print(f"  Profit (90d):    ${status['profit_90d']:>10.2f}")
        print(f"  ROI (30d):       {status['roi_30d']:>9.1f}%")
        print(f"  ROI (90d):       {status['roi_90d']:>9.1f}%")
        print(f"  RPM:             ${status['rpm']:>9.2f}")
        print(f"  Active campaigns:{status['active_campaigns']:>9d}")
        print(f"  Goals:           {status['goals_achieved']}/{status['goals_total']}")
        print(f"  Budget used:     {status['budget_utilization_pct']:>8.1f}%")
        rev = status.get("revenue_by_type", {})
        if rev:
            print(f"\n  Revenue by type:")
            for t, v in rev.items():
                print(f"    {t:30s}: ${v:>10.2f}")
        costs = status.get("costs_by_category", {})
        if costs:
            print(f"\n  Costs by category:")
            for c, v in costs.items():
                print(f"    {c:30s}: ${v:>10.2f}")
        print(bar)
        return

    if args.business_goals:
        from mindmargin.business.goals import GoalEngine
        engine = GoalEngine()
        goals = engine.list_goals()
        progress = engine.get_overall_progress()
        weighted = engine.get_weighted_score()
        bar = "=" * 65
        print(f"\n{bar}")
        print(f"  BUSINESS GOALS  (progress: {progress['progress_pct']:.1f}%, score: {weighted:.1f})")
        print(bar)
        print(f"  {'ID':<18s} {'Name':<25s} {'Progress':>10s} {'Target':>12s} {'Weight'}")
        print(f"  {'-'*17} {'-'*24} {'-'*9} {'-'*11} {'-'*6}")
        for g in goals:
            pct = f"{g.progress_pct:.1f}%"
            target = f"{g.target_value:.0f} {g.unit}"
            marker = "*" if g.is_achieved else " "
            print(f"  {marker}{g.goal_id[:17]:17s} {g.name[:25]:25s} {pct:>10s} {target:>12s} {g.weight:.1f}")
        print(f"\n  Achieved: {progress['achieved']}/{progress['total']}")
        print(bar)
        return

    if args.business_revenue:
        from mindmargin.business.revenue import RevenueEngine
        engine = RevenueEngine()
        total = engine.get_total_revenue()
        by_type = engine.get_revenue_by_type()
        by_source = engine.get_revenue_by_source()
        monthly = engine.get_monthly_revenue(6)
        bar = "=" * 55
        print(f"\n{bar}")
        print(f"  REVENUE SUMMARY")
        print(bar)
        print(f"  Total revenue:   ${total:>10.2f}")
        if by_type:
            print(f"\n  By type:")
            for t, v in by_type.items():
                print(f"    {t:30s}: ${v:>10.2f}")
        if by_source:
            print(f"\n  By source:")
            for s, v in by_source.items():
                print(f"    {s:30s}: ${v:>10.2f}")
        if monthly:
            print(f"\n  Monthly:")
            for m in monthly:
                print(f"    {m['month']}: ${m['revenue']:>10.2f}")
        print(bar)
        return

    if args.business_budget:
        from mindmargin.business.budget import BudgetManager
        mgr = BudgetManager()
        summary = mgr.get_budget_summary()
        costs = mgr.get_costs_by_category()
        bar = "=" * 55
        print(f"\n{bar}")
        print(f"  BUDGET STATUS")
        print(bar)
        print(f"  Total limit:     ${summary['total_limit']:>10.2f}")
        print(f"  Total spent:     ${summary['total_spent']:>10.2f}")
        print(f"  Remaining:       ${summary['total_remaining']:>10.2f}")
        print(f"  Utilization:     {summary['utilization_pct']:>9.1f}%")
        if costs:
            print(f"\n  Costs by category:")
            for c, v in costs.items():
                print(f"    {c:25s}: ${v:>10.2f}")
        print(bar)
        return

    if args.business_forecast:
        from mindmargin.business.forecast import ForecastEngine
        from mindmargin.business.revenue import RevenueEngine
        from mindmargin.business.budget import BudgetManager
        fe = ForecastEngine()
        re = RevenueEngine()
        bm = BudgetManager()
        rev_entries = re.list_entries(limit=100)
        cost_entries = bm.list_costs(limit=100)
        from mindmargin.business.models import ForecastWindow
        forecast = fe.generate_forecast(rev_entries, cost_entries, ForecastWindow.DAYS_30)
        s = forecast.summary
        bar = "=" * 55
        print(f"\n{bar}")
        print(f"  30-DAY FORECAST")
        print(bar)
        print(f"  Revenue:         ${s['total_revenue']:>10.2f}")
        print(f"  Expenses:        ${s['total_expenses']:>10.2f}")
        print(f"  Profit:          ${s['total_profit']:>10.2f}")
        print(f"  ROI:             {s['overall_roi']:>9.1f}%")
        print(f"  Daily revenue:   ${s['avg_daily_revenue']:>10.2f}")
        print(f"  Daily expenses:  ${s['avg_daily_expenses']:>10.2f}")
        print(f"  Growth rate:     {s['growth_rate']:>9.1%}")
        print(f"  Final subs:      {s['final_subscribers']:>10d}")
        print(bar)
        return

    if args.business_campaigns:
        from mindmargin.business.campaigns import CampaignManager
        mgr = CampaignManager()
        campaigns = mgr.list_campaigns(limit=20)
        bar = "=" * 70
        print(f"\n{bar}")
        print(f"  CAMPAIGNS ({len(campaigns)} total)")
        print(bar)
        print(f"  {'ID':<16s} {'Name':<20s} {'Type':<12s} {'Status':<10s} {'ROI'}")
        print(f"  {'-'*15} {'-'*19} {'-'*11} {'-'*9} {'-'*8}")
        for c in campaigns:
            print(f"  {c.campaign_id[:15]:16s} {c.name[:20]:20s} "
                  f"{c.campaign_type.value:12s} {c.status.value:10s} {c.roi:>7.1f}%")
        print(f"\n  Total budget: ${mgr.get_total_budget():.2f}")
        print(f"  Total spent:  ${mgr.get_total_spent():.2f}")
        print(f"  Total rev:    ${mgr.get_total_revenue():.2f}")
        print(f"  Overall ROI:  {mgr.get_overall_roi():.1f}%")
        print(bar)
        return

    if args.business_report:
        from mindmargin.business.portfolio import BusinessPortfolio
        portfolio = BusinessPortfolio()
        report = portfolio.get_full_report()
        s = report["status"]
        bar = "=" * 60
        print(f"\n{bar}")
        print(f"  FULL BUSINESS REPORT")
        print(bar)
        print(f"  Revenue 30d:     ${s['total_revenue_30d']:>10.2f}")
        print(f"  Costs 30d:       ${s['total_costs_30d']:>10.2f}")
        print(f"  Profit 30d:      ${s['profit_30d']:>10.2f}")
        print(f"  ROI 30d:         {s['roi_30d']:>9.1f}%")
        print(f"  Health score:    ---")
        print(f"\n  Goals: {report['goal_progress']['achieved']}/{report['goal_progress']['total']} "
              f"(weighted: {report['weighted_score']:.1f})")
        print(f"\n  Campaigns: {len(report['campaigns'])}")
        for c in report["campaigns"][:5]:
            print(f"    [{c['status']}] {c['name'][:30]:30s} ROI={c.get('roi', 0):.1f}%")
        print(f"\n  Budget: ${report['budget']['total_spent']:.2f} / ${report['budget']['total_limit']:.2f}")
        print(bar)
        return

    # ── YouTube Intelligence commands ──

    if args.yt_status:
        from mindmargin.youtube_intelligence.optimizer import YouTubeOptimizer
        opt = YouTubeOptimizer()
        status = opt.get_status()
        bar = "=" * 60
        print(f"\n{bar}")
        print(f"  YOUTUBE INTELLIGENCE STATUS")
        print(bar)
        print(f"  Health score:       {status.health_score:>8.1f}")
        print(f"  Growth score:       {status.growth_score:>8.1f}")
        print(f"  Audience segments:  {status.audience_segments:>8d}")
        print(f"  Active signals:     {status.active_signals:>8d}")
        print(f"  CTR analyses:       {status.ctr_analyses:>8d}")
        print(f"  Competitors:        {status.competitors_tracked:>8d}")
        print(f"  Benchmarks:         {status.benchmarks_recorded:>8d}")
        print(f"  Trends tracked:     {status.trends_tracked:>8d}")
        if status.last_health_check:
            print(f"  Last health check:  {status.last_health_check}")
        if status.last_growth_analysis:
            print(f"  Last growth:        {status.last_growth_analysis}")
        print(bar)
        return

    if args.yt_health:
        from mindmargin.youtube_intelligence.channel_health import ChannelHealthMonitor
        monitor = ChannelHealthMonitor()
        report = monitor.get_latest()
        bar = "=" * 65
        print(f"\n{bar}")
        print(f"  CHANNEL HEALTH")
        print(bar)
        if not report:
            print("  No health data yet. Run --yt-full-analysis first.")
            print(bar)
            return
        print(f"  Overall: {report.overall_score}/100 ({report.grade})")
        print(f"  {report.summary}")
        if report.top_strengths:
            print(f"\n  Strengths: {', '.join(report.top_strengths)}")
        if report.top_weaknesses:
            print(f"  Weaknesses: {', '.join(report.top_weaknesses)}")
        print(f"\n  {'Factor':<25s} {'Score':>6s} {'Weight':>7s} {'Trend':>10s}")
        print(f"  {'-'*24} {'-'*5} {'-'*6} {'-'*9}")
        for m in report.metrics:
            trend = m.trend.value if hasattr(m, 'trend') else ""
            print(f"  {m.factor.value:<25s} {m.score:>5.1f} {m.weight:>6.1%} {trend:>10s}")
        print(bar)
        return

    if args.yt_growth:
        from mindmargin.youtube_intelligence.growth import GrowthEngine
        engine = GrowthEngine()
        reports = engine.list_reports(1)
        bar = "=" * 60
        print(f"\n{bar}")
        print(f"  GROWTH ANALYSIS")
        print(bar)
        if not reports:
            print("  No growth data yet. Run --yt-full-analysis first.")
            print(bar)
            return
        r = reports[0]
        print(f"  Growth score: {r.overall_growth_score}/100")
        print(f"  {r.summary}")
        if r.fast_growing_topics:
            print(f"\n  Fast-growing topics:")
            for s in r.fast_growing_topics[:5]:
                print(f"    {s.get('topic', ''):40s} strength={s.get('strength', 0):.0f}")
        if r.declining_topics:
            print(f"\n  Declining topics:")
            for s in r.declining_topics[:5]:
                print(f"    {s.get('topic', ''):40s} strength={s.get('strength', 0):.0f}")
        if r.evergreen_opportunities:
            print(f"\n  Evergreen opportunities:")
            for s in r.evergreen_opportunities[:5]:
                print(f"    {s.get('topic', ''):40s} strength={s.get('strength', 0):.0f}")
        if r.bottlenecks:
            print(f"\n  Bottlenecks:")
            for s in r.bottlenecks[:3]:
                print(f"    {s.get('topic', '')}")
        print(bar)
        return

    if args.yt_retention:
        from mindmargin.youtube_intelligence.retention import RetentionAnalyzer
        ra = RetentionAnalyzer()
        analyses = ra.list_analyses(5)
        bar = "=" * 60
        print(f"\n{bar}")
        print(f"  RETENTION ANALYSIS")
        print(bar)
        if not analyses:
            print("  No retention data yet. Run --yt-full-analysis first.")
            print(bar)
            return
        for a in analyses:
            print(f"\n  [{a.video_id[:20]}] {a.video_title[:35]}")
            print(f"    Avg retention: {a.avg_retention_pct:.1f}%")
            print(f"    Hook score: {a.hook_strength_score:.0f}/100")
            print(f"    Ending score: {a.ending_strength_score:.0f}/100")
            print(f"    Optimal length: {a.optimal_length_seconds:.0f}s")
            if a.patterns:
                print(f"    Patterns: {', '.join(p.value for p in a.patterns)}")
            if a.script_recommendations:
                for rec in a.script_recommendations[:2]:
                    print(f"    -> {rec}")
        print(bar)
        return

    if args.yt_ctr:
        from mindmargin.youtube_intelligence.ctr import CTROptimizer
        co = CTROptimizer()
        report = co.get_latest()
        bar = "=" * 60
        print(f"\n{bar}")
        print(f"  CTR ANALYSIS")
        print(bar)
        if not report:
            print("  No CTR data yet. Run --yt-full-analysis first.")
            print(bar)
            return
        print(f"  Average CTR: {report.avg_ctr:.2f}%")
        print(f"  Best CTR:    {report.best_ctr:.2f}%")
        print(f"  Worst CTR:   {report.worst_ctr:.2f}%")
        if report.title_effectiveness.get("patterns"):
            print(f"\n  Title patterns:")
            for p, s in report.title_effectiveness["patterns"].items():
                print(f"    {p:25s} avg={s['avg_ctr']:.1f}% ({s['count']} videos)")
        if report.thumbnail_effectiveness.get("styles"):
            print(f"\n  Thumbnail styles:")
            for s, data in report.thumbnail_effectiveness["styles"].items():
                print(f"    {s:25s} avg={data['avg_ctr']:.1f}% ({data['count']} videos)")
        if report.recommendations:
            print(f"\n  Recommendations:")
            for rec in report.recommendations:
                print(f"    -> {rec}")
        print(bar)
        return

    if args.yt_audience:
        from mindmargin.youtube_intelligence.audience import AudienceIntelligence
        ai = AudienceIntelligence()
        profile = ai.get_latest()
        bar = "=" * 60
        print(f"\n{bar}")
        print(f"  AUDIENCE INSIGHTS")
        print(bar)
        if not profile:
            print("  No audience data yet. Run --yt-full-analysis first.")
            print(bar)
            return
        print(f"  Best upload time: {profile.best_upload_time or 'unknown'}")
        print(f"  Best upload day:  {profile.best_upload_day or 'unknown'}")
        print(f"  Returning viewers: {profile.returning_viewer_pct:.1f}%")
        print(f"  Subscriber view:  {profile.subscriber_view_pct:.1f}%")
        print(f"  Avg session:      {profile.avg_session_duration:.0f}s")
        if profile.top_geographies:
            print(f"\n  Top geographies:")
            for g in profile.top_geographies[:5]:
                print(f"    {g.get('country', ''):25s} {g.get('view_pct', 0):.1f}%")
        if profile.top_languages:
            print(f"\n  Top languages:")
            for l in profile.top_languages[:5]:
                print(f"    {l.get('language', ''):25s} {l.get('view_pct', 0):.1f}%")
        if profile.insights:
            print(f"\n  Insights:")
            for i in profile.insights[:5]:
                print(f"    [{i.category}] {i.metric_name}: {i.metric_value}")
                if i.recommendation:
                    print(f"      -> {i.recommendation}")
        print(bar)
        return

    if args.yt_benchmarks:
        from mindmargin.youtube_intelligence.benchmark import BenchmarkEngine
        be = BenchmarkEngine()
        by_cat = be.get_benchmarks_by_category()
        bar = "=" * 60
        print(f"\n{bar}")
        print(f"  BENCHMARKS")
        print(bar)
        if not by_cat:
            print("  No benchmarks recorded yet.")
            print(bar)
            return
        print(f"  {'Category':<30s} {'Best':>10s} {'Avg':>10s} {'Samples'}")
        print(f"  {'-'*29} {'-'*9} {'-'*9} {'-'*7}")
        for cat, data in by_cat.items():
            print(f"  {cat:<30s} {data['best_value']:>10.2f} {data['avg_value']:>10.2f} {data['sample_count']}")
        print(bar)
        return

    if args.yt_competition:
        from mindmargin.youtube_intelligence.competition import CompetitionIntelligence
        ci = CompetitionIntelligence()
        competitors = ci.list_competitors()
        report = ci.get_latest()
        bar = "=" * 65
        print(f"\n{bar}")
        print(f"  COMPETITION INTELLIGENCE")
        print(bar)
        print(f"  Tracked competitors: {len(competitors)}")
        if competitors:
            print(f"\n  {'Channel':<25s} {'Subs':>10s} {'Avg Views':>12s} {'Freq':>6s} {'Growth'}")
            print(f"  {'-'*24} {'-'*9} {'-'*11} {'-'*5} {'-'*6}")
            for c in competitors:
                print(f"  {c.channel_name[:25]:<25s} {c.subscriber_count:>10d} {c.avg_views:>12.0f} {c.upload_frequency:>5.1f} {c.estimated_growth_rate:>5.1f}%")
        if report:
            if report.topic_gaps:
                print(f"\n  Topic gaps:")
                for g in report.topic_gaps[:5]:
                    print(f"    {g.get('topic', '')} ({g.get('competitor', '')})")
            if report.recommendations:
                print(f"\n  Recommendations:")
                for rec in report.recommendations[:3]:
                    print(f"    -> {rec}")
        print(bar)
        return

    if args.yt_recommendations:
        from mindmargin.youtube_intelligence.recommendations import YouTubeRecommendationEngine
        re = YouTubeRecommendationEngine()
        recs = re.list_recommendations(limit=20)
        stats = re.get_stats()
        bar = "=" * 65
        print(f"\n{bar}")
        print(f"  YOUTUBE RECOMMENDATIONS (pending: {stats['pending']}, total: {stats['total']})")
        print(bar)
        if not recs:
            print("  No recommendations generated yet.")
            print(bar)
            return
        print(f"  {'#':<4s} {'Pri':>3s} {'Conf':>5s} {'Type':<15s} Title")
        print(f"  {'-'*3} {'-'*2} {'-'*4} {'-'*14} {'-'*30}")
        for i, r in enumerate(recs[:20], 1):
            print(f"  {i:<4d} {r.priority:>3d} {r.confidence:>4.0%} {r.recommendation_type.value:<15s} {r.title[:40]}")
            if r.description:
                print(f"       {r.description[:55]}")
        print(bar)
        return

    if args.yt_full_analysis:
        from mindmargin.youtube_intelligence.optimizer import YouTubeOptimizer
        opt = YouTubeOptimizer()
        print("  Running full YouTube Intelligence analysis...")
        results = opt.run_full_analysis({}, [], [], [], [])
        health = results.get("health", {})
        growth = results.get("growth", {})
        bar = "=" * 60
        print(f"\n{bar}")
        print(f"  FULL ANALYSIS COMPLETE")
        print(bar)
        print(f"  Health score: {health.get('overall_score', 0)}/100 ({health.get('grade', 'N/A')})")
        print(f"  Growth score: {growth.get('overall_growth_score', 0)}/100")
        print(f"  Status: {results.get('status', {}).get('active_signals', 0)} active signals")
        print(f"\n  Recommendations:")
        recs = results.get("recommendations", [])
        if isinstance(recs, list):
            for r in recs[:5]:
                if isinstance(r, dict):
                    print(f"    -> {r.get('title', r.get('description', ''))}")
        print(bar)
        return

    # ── Operations Hub commands ──

    if args.ops_status:
        from mindmargin.core.workflows import WorkflowEngine
        from mindmargin.core.scheduler import Scheduler
        from mindmargin.operations.controller import OperationsController
        engine = WorkflowEngine()
        sched = Scheduler()
        controller = OperationsController(engine=engine, scheduler=sched)
        report = controller.get_status()
        bar = "=" * 55
        print(f"\n{bar}")
        print(f"  AUTONOMOUS OPERATIONS HUB STATUS")
        print(bar)
        print(f"  Overall:      {report.status.upper()}")
        print(f"  Active ops:   {report.active_operations}")
        print(f"  Completed:    {report.completed_today} today")
        print(f"  Failed:       {report.failed_today} today")
        print(f"  Scheduled:    {report.scheduled}")
        print(bar)
        if report.records:
            print(f"  Recent operations:")
            for r in report.records[:10]:
                print(f"    [{r.status.value.upper():10s}] {r.operation_type.value:25s} "
                      f"{r.started_at[:19] if r.started_at else '':19s}")
        print(bar)
        return

    if args.ops_history:
        from mindmargin.core.workflows import WorkflowEngine
        from mindmargin.operations.controller import OperationsController
        limit = args.ops_history if args.ops_history > 0 else 20
        engine = WorkflowEngine()
        controller = OperationsController(engine=engine)
        records = controller.get_history(limit=limit)
        bar = "=" * 55
        print(f"\n{bar}")
        print(f"  OPERATION EXECUTION HISTORY ({len(records)})")
        print(bar)
        for r in records:
            print(f"  [{r.status.value.upper():10s}] {r.operation_type.value:25s} "
                  f"{r.started_at[:19] if r.started_at else '':19s}")
            if r.error:
                print(f"  {'':12s} Error: {r.error[:80]}")
        print(bar)
        return

    if args.ops_run:
        from mindmargin.core.workflows import WorkflowEngine
        from mindmargin.operations.controller import OperationsController
        from mindmargin.operations.models import OperationType
        try:
            op_type = OperationType(args.ops_run)
        except ValueError:
            print(f"\n  Invalid operation type: {args.ops_run}")
            print(f"  Valid types: {[t.value for t in OperationType]}")
            return
        engine = WorkflowEngine()
        controller = OperationsController(engine=engine)
        print(f"\n  Running operation: {op_type.value}...")
        result = controller.run_operation(op_type)
        bar = "=" * 55
        print(f"\n{bar}")
        print(f"  OPERATION RESULT")
        print(bar)
        print(f"  Type:   {op_type.value}")
        print(f"  Status: {result.get('status', '?')}")
        if result.get('operation_id'):
            print(f"  Op ID:  {result['operation_id']}")
        if result.get('workflow_id'):
            print(f"  WF ID:  {result['workflow_id']}")
        if result.get('error'):
            print(f"  Error:  {result['error']}")
        print(bar)
        return

    if args.ops_schedule:
        from mindmargin.core.workflows import WorkflowEngine
        from mindmargin.core.scheduler import Scheduler
        from mindmargin.operations.controller import OperationsController
        engine = WorkflowEngine()
        sched = Scheduler()
        controller = OperationsController(engine=engine, scheduler=sched)
        print(f"\n  Registering operations with scheduler...")
        scheduled = controller.schedule_all()
        if scheduled:
            print(f"  Scheduled {len(scheduled)} operations:")
            for op_type, sid in scheduled.items():
                print(f"    {op_type:30s} -> {sid}")
        else:
            print(f"  No operations were scheduled (scheduler may not be available)")
        return

    if args.ops_recover:
        from mindmargin.core.workflows import WorkflowEngine
        from mindmargin.operations.controller import OperationsController
        engine = WorkflowEngine()
        controller = OperationsController(engine=engine)
        recovered = controller.recover_failed()
        report = controller.get_status()
        print(f"\n  Recovered {recovered} failed operations. "
              f"{report.failed_today} still failed.")
        return

    # ── Production commands ──

    if args.job_status:
        from mindmargin.core.jobs import Job
        job = Job.load(args.job_status)
        if job:
            d = job.to_dict()
            bar = "=" * 50
            print(f"\n{bar}")
            print(f"  JOB STATUS: {d['job_id']}")
            print(bar)
            print(f"  Type:    {d.get('job_type', '?')}")
            print(f"  State:   {d.get('state', '?')}")
            print(f"  Created: {d.get('created_at', '?')[:19]}")
            if d.get('started_at'):
                print(f"  Started: {d['started_at'][:19]}")
            if d.get('completed_at'):
                print(f"  Done:    {d['completed_at'][:19]}")
            if d.get('error'):
                print(f"  Error:   {d['error']}")
            if d.get('result'):
                print(f"  Result:  {json.dumps(d['result'], default=str)[:200]}")
            print(bar)
        else:
            print(f"  Job not found: {args.job_status}")
        return

    if args.job_list:
        from mindmargin.core.jobs import Job
        jobs = Job.list_jobs(20)
        bar = "=" * 50
        print(f"\n{bar}")
        print(f"  RECENT JOBS ({len(jobs)})")
        print(bar)
        for j in jobs:
            state_icon = {"COMPLETED": "+", "FAILED": "-", "RUNNING": ">", "PENDING": "o",
                         "PAUSED": "|", "CANCELLED": "x", "RETRYING": "~"}.get(j.get("state", ""), "?")
            jid = j.get("job_id", "")[:30]
            jtype = j.get("job_type", "")[:20]
            jstate = j.get("state", "")[:12]
            print(f"  [{state_icon}] {jid:30s} {jtype:20s} {jstate}")
        print(bar)
        return

    if args.job_cancel:
        from mindmargin.core.jobs import Job
        job = Job.load(args.job_cancel)
        if job:
            try:
                job.cancel()
                print(f"  Cancelled: {args.job_cancel}")
            except Exception as e:
                print(f"  Error: {e}")
        else:
            print(f"  Job not found: {args.job_cancel}")
        return

    if args.job_retry:
        from mindmargin.core.jobs import Job
        job = Job.load(args.job_retry)
        if job:
            try:
                job.retry()
                from mindmargin.core.jobs import run_job
                from mindmargin.agents.decision_executor import execute_top_decision
                run_job("pipeline", lambda j: {"result": execute_top_decision()},
                        {"max_retries": 3})
                print(f"  Retry queued: {args.job_retry}")
            except Exception as e:
                print(f"  Error: {e}")
        else:
            print(f"  Job not found: {args.job_retry}")
        return

    if args.detect_unfinished:
        from mindmargin.core.state import PipelineState
        unfinished = PipelineState.list_unfinished()
        bar = "=" * 50
        print(f"\n{bar}")
        if unfinished:
            print(f"  UNFINISHED PIPELINES ({len(unfinished)})")
            print(bar)
            for ps in unfinished:
                d = ps.to_dict()
                state = d.get("state", "?")
                topic = d.get("topic", "?")[:40]
                updated = d.get("updated_at", "")[:19]
                print(f"  [{state:15s}] {topic:40s} {updated}")
        else:
            print(f"  No unfinished pipelines detected.")
        print(bar)
        return

    if args.resume_all:
        from mindmargin.core.state import PipelineState
        from mindmargin.core.jobs import run_job
        from mindmargin.agents.decision_executor import execute_top_decision
        unfinished = PipelineState.list_unfinished()
        if not unfinished:
            print("  No unfinished pipelines to resume.")
        else:
            print(f"  Resuming {len(unfinished)} unfinished pipeline(s)...")
            for ps in unfinished:
                job = run_job("pipeline_resume",
                              lambda j, pid=ps.pipeline_id: {"result": execute_top_decision()},
                              {"max_retries": 3, "pipeline_id": ps.pipeline_id})
                print(f"    {ps.pipeline_id} -> job {job.job_id}")
        return

    if args.recover:
        from mindmargin.core.state import PipelineState
        unfinished = PipelineState.list_unfinished()
        if not unfinished:
            print("  No unfinished pipelines to recover.")
        else:
            print(f"\n  Detected {len(unfinished)} unfinished pipeline(s):")
            for i, ps in enumerate(unfinished, 1):
                d = ps.to_dict()
                print(f"  {i}. [{d.get('state', '?')}] {d.get('topic', '?')} ({ps.pipeline_id})")
            print(f"\n  Run with --resume-all to resume all.")
            print(f"  Or run individual pipelines with their original topic.")
        return

    if args.analyze_patterns:
        from mindmargin.analytics.patterns import full_pattern_analysis
        result = full_pattern_analysis()
        print(f"\n  Pattern analysis: {result['status']}")
        print(f"  Retention: {result['retention']['status']}")
        print(f"  Hooks: {result['hooks']['status']}")
        print(f"  Pacing: {result['pacing']['status']}")
        print(f"  Topics: {result['topics']['status']}")
        print(f"  Best practices: {result['best_practices_count']}")
        return

    if args.check_auth:
        from mindmargin.integrations.youtube import check_credentials
        creds = check_credentials()
        if creds.get("authenticated"):
            print(f"\n  Authenticated as: {creds.get('channel_name', '?')}")
        else:
            print(f"\n  Not authenticated: {creds.get('error', '')}")
        return

    if args.list_playlists:
        from mindmargin.integrations.youtube import list_playlists
        playlists = list_playlists()
        if playlists:
            print(f"\n  YouTube Playlists ({len(playlists)}):")
            for p in playlists:
                print(f"    [{p['id']}] {p['title']} ({p['item_count']} videos)")
        else:
            print("\n  No playlists found or not authenticated")
        return

    if args.analytics is not None:
        _do_analytics(args.analytics, args.pipeline_id)
        return

    if args.publish_existing:
        _do_publish(args.topic or "video", args.publish_existing, args.privacy, args.playlist)
        return

    if not args.topic:
        parser.print_help()
        return

    # Run pipeline
    logger.info(f"MindMargin MVP | topic='{args.topic}' | resume={args.resume or 'none'}")

    scale = 0.1 if args.quick else 1.0
    pipe = Pipeline(topic=args.topic, pipeline_id=args.resume or None,
                    duration_scale=scale, mode=args.mode, use_templates=args.template,
                    editing_timeout=args.editing_timeout, force_editing=args.force_editing)
    result = pipe.run()

    bar = "=" * 50
    print(f"\n{bar}")
    print(f"  PIPELINE: {result['status'].upper()}")
    print(f"  Pipeline: {result['pipeline_id']}")
    print(f"  Topic:    {result['topic']}")
    print(f"  Timing:   {result.get('timing_s', '?')}s total")
    if result.get("timing_detail"):
        print(f"  Detail:   {result['timing_detail']}")
    print(f"  Agents:   {', '.join(result['completed_agents'])}")
    print(f"  Output:   {result.get('output_dir', 'N/A')}")
    print(f"  Video:    {result.get('video_path', 'N/A')}")
    print(bar)

    if result["status"] == "failed":
        logger.error(f"Pipeline failed: {result['errors']}")
        sys.exit(1)

    if not args.skip_validation and result.get("output_dir"):
        val = verify_pipeline_output(result["output_dir"])
        print_validation(val)

    # Store in memory
    from mindmargin.analytics.memory import save_pipeline_result
    save_pipeline_result(result.get("pipeline_id", result.get("topic", "")), result)

    # Generate thumbnails after pipeline
    if result.get("output_dir") and result["status"] == "completed":
        try:
            from mindmargin.agents.thumbnail import ThumbnailAgent
            script_path = Path(result["output_dir"]) / "script" / "script.json"
            if script_path.exists():
                import json as _json
                script_data = _json.loads(script_path.read_text(encoding="utf-8"))
                thumb_agent = ThumbnailAgent()
                thumb_agent.run(result["topic"], result["pipeline_id"], script_data)
        except Exception as e:
            logger.warning(f"Thumbnail generation skipped: {e}")

    # Publish if requested
    if args.publish:
        _do_publish(result["topic"], result["pipeline_id"], args.privacy, args.playlist)

    print(f"\nDone: {result.get('output_dir', '')}")


if __name__ == "__main__":
    main()
