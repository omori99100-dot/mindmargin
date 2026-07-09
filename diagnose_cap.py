"""Diagnostic: reproduce the daily publish cap check with full variable tracing.

Uses the canonical is_successful_publish() from memory.py so that this
diagnostic always stays in sync with production code.
"""
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = Path("data/mindmargin.db")
MAX_DAILY_PUBLISH = 1

# Import the canonical definition of "successful publish"
from mindmargin.analytics.memory import is_successful_publish


def diagnose():
    print("=" * 60)
    print("  DAILY PUBLISH CAP DIAGNOSTIC")
    print("=" * 60)

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    # 1. Raw execution log
    print("\n[1] ALL execution_log entries (newest first):")
    rows = conn.execute("SELECT * FROM execution_log ORDER BY executed_at DESC").fetchall()
    for r in rows:
        d = dict(r)
        print(f"  id={d['id']} pipeline={d['pipeline_id']} status={d['pipeline_status']} "
              f"video_id={d['video_id']!r} error={d['error']!r} is_successful={is_successful_publish(d)} "
              f"executed_at={d['executed_at']}")

    # 2. Daily cap check simulation
    print("\n[2] Daily cap check simulation (using is_successful_publish):")
    cutoff = (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")
    print(f"  utcnow()  = {datetime.utcnow().isoformat()}")
    print(f"  cutoff    = {cutoff}")

    logs = [dict(r) for r in conn.execute(
        "SELECT * FROM execution_log ORDER BY executed_at DESC LIMIT 50"
    ).fetchall()]
    print(f"  get_execution_log(limit=50) returned {len(logs)} rows")

    recent = [l for l in logs
              if l.get("executed_at", "") >= cutoff
              and is_successful_publish(l)]
    print(f"  After filter (executed_at >= cutoff AND is_successful_publish): {len(recent)} entries")
    for l in recent:
        print(f"    {l['executed_at']} | {l['topic']} | video_id={l['video_id']!r}")
    print(f"  Cap blocked: {len(recent) >= MAX_DAILY_PUBLISH}")

    # 3. Check pipelines table for today's activity
    print("\n[3] Pipelines with youtube_video_id (potential duplicates):")
    today = datetime.utcnow().strftime("%Y-%m-%d")
    for r in conn.execute(
        "SELECT id, topic, youtube_video_id, youtube_url FROM pipelines WHERE youtube_video_id != ''"
    ).fetchall():
        d = dict(r)
        print(f"  {d['id']} | {d['topic']} | {d['youtube_video_id']}")

    # 4. Inconsistent entries (historical — is_successful_publish now handles these correctly)
    print("\n[4] Entries where is_successful_publish returns False (not counted toward cap):")
    for r in rows:
        d = dict(r)
        if not is_successful_publish(d):
            print(f"  id={d['id']} pipeline={d['pipeline_id']} topic={d['topic']} "
                  f"video_id={d['video_id']!r} error={d['error']!r}")

    # 5. Simulate what happens if we run the pipeline NOW
    print("\n[5] What the cap check would see RIGHT NOW:")
    print(f"  Would block: {len(recent) >= MAX_DAILY_PUBLISH}")
    print(f"  Successful entries count: {len(recent)}")
    print(f"  MAX_DAILY_PUBLISH: {MAX_DAILY_PUBLISH}")

    # 6. Check for governance rules
    print("\n[6] Governance rules file:")
    rules_path = Path("temp/channel/governance/rules.json")
    if rules_path.exists():
        import json
        rules = json.loads(rules_path.read_text(encoding="utf-8"))
        for r in rules:
            if "daily" in r.get("rule_type", "").lower() or "upload" in r.get("rule_type", "").lower():
                print(f"  {r.get('name')}: enabled={r.get('enabled')} config={r.get('config')}")
    else:
        print("  (rules file not found)")

    conn.close()

if __name__ == "__main__":
    diagnose()
