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
    parser.add_argument("--resume", type=str, default="", help="Pipeline ID to resume")
    parser.add_argument("--quick", action="store_true", help="Quick mode (short video for testing)")
    parser.add_argument("--skip-validation", action="store_true", help="Skip output validation")
    parser.add_argument("--template", action="store_true", help="Use template fallbacks (skip LLM)")
    parser.add_argument("--mode", type=str, default="documentary", choices=modes,
                        help=f"Generation mode: {', '.join(modes)}")

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

    args = parser.parse_args()

    if args.api:
        import uvicorn
        logger.info(f"Starting API on {args.host}:{args.port}")
        uvicorn.run("mindmargin.api.server:app", host=args.host, port=args.port)
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

    if args.run_daily_job:
        import shutil
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
                    duration_scale=scale, mode=args.mode, use_templates=args.template)
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
