"""Audience Acquisition Analysis Script — dumps structured report to stdout."""
import sys
sys.path.insert(0, r'C:\Users\A Center\OneDrive\المستندات\mindmargin')

from datetime import datetime
from mindmargin.analytics.memory import _get_db, get_best_titles, get_best_hooks, get_ab_winning_titles

conn = _get_db()
now = datetime.utcnow()

rows = conn.execute("""
    SELECT p.id, p.topic, p.word_count, p.video_duration_s, p.youtube_video_id,
           p.youtube_url, p.created_at, p.published_at,
           COALESCE(a.views, 0) as views, COALESCE(a.likes, 0) as likes,
           COALESCE(a.comments, 0) as comments,
           COALESCE(a.avg_view_duration_s, 0) as avg_duration
    FROM pipelines p
    LEFT JOIN analytics a ON a.pipeline_id = p.id
    WHERE p.youtube_video_id != ''
    ORDER BY a.views DESC
""").fetchall()
videos = [dict(r) for r in rows]

class_rows = conn.execute("""
    SELECT vc.*, p.topic FROM video_classifications vc
    JOIN pipelines p ON p.id = vc.pipeline_id
    WHERE vc.id IN (SELECT MAX(id) FROM video_classifications GROUP BY video_id)
    ORDER BY vc.velocity DESC
""").fetchall()
classifications = {r['video_id']: dict(r) for r in class_rows}

for v in videos:
    vid = v['youtube_video_id']
    pub = v.get('published_at') or v.get('created_at', '')
    views = v['views']
    v['watch_time_s'] = (v.get('avg_duration', 0) or 0) * views if views > 0 else 0
    if pub:
        try:
            dt = datetime.strptime(pub[:19], '%Y-%m-%d %H:%M:%S')
            days = max((now - dt).total_seconds() / 86400, 0.01)
            v['velocity'] = round(views / days, 2)
            v['days_since_publish'] = round(days, 1)
        except Exception:
            v['velocity'] = 0.0
            v['days_since_publish'] = 999
    else:
        v['velocity'] = 0.0
        v['days_since_publish'] = 999
    cl = classifications.get(vid, {})
    v['classification'] = cl.get('classification', 'unclassified')

# Print velocity ranking
print("=" * 75)
print("  VIDEO PERFORMANCE RANKING (by views/day)")
print("=" * 75)
for v in sorted(videos, key=lambda x: x['velocity'], reverse=True):
    c = v['classification']
    icon = {'stable': '~', 'dead': 'x', 'weak': '-', 'breakout': '*', 'strong': '+'}.get(c, '?')
    print(f"  {v['velocity']:>6.2f}/day  {v['views']:>3d} views  [{icon}] {c:11s}  {v['topic'][:50]}")
print(f"\n  Total: {len(videos)} published videos")
print(f"  Channel views (last 7d): 602")

print()
print("=" * 75)
print("  TOPIC FAMILY RANKINGS")
print("=" * 75)

families = {
    'Financial Fraud & Scams': ['enron','theranos','wework','ftx','cambridge analytica','bernie madoff','wirecard','celsius network'],
    'Tech Giants That Fell': ['nokia','blackberry','kodak','blockbuster','yahoo','myspace','palm','compaq','netscape','radioshack','circuit city','toys r us'],
    'Financial Collapses & Crashes': ['lehman brothers','silicon valley bank','ltcm','gamestop','bitcoin crash'],
    'Corporate Downfalls': ['sears','arthur andersen','toys r us','uber'],
}

for fname, keywords in families.items():
    members = []
    for v in videos:
        t = v['topic'].lower()
        for kw in keywords:
            if kw in t or t in kw:
                members.append(v)
                break
    if not members:
        continue
    total_views = sum(m['views'] for m in members)
    avg_vel = round(sum(m['velocity'] for m in members) / len(members), 2)
    total_watch = sum(m['watch_time_s'] for m in members)
    stable = sum(1 for m in members if m['classification'] == 'stable')
    dead = sum(1 for m in members if m['classification'] == 'dead')
    top_member = max(members, key=lambda x: x['velocity'])
    
    print(f"\n  [{fname}]")
    print(f"       {len(members):2d} videos  {total_views:3d} total views  {avg_vel:>5.2f}/day avg vel")
    print(f"       stable={stable}  dead={dead}  top: {top_member['topic'][:40]} ({top_member['velocity']:.2f}/day)")
    for m in sorted(members, key=lambda x: x['velocity'], reverse=True)[:3]:
        print(f"         -> {m['velocity']:>5.2f}/day  {m['views']:>3d}v  {m['topic'][:45]}")

print()
print("=" * 75)
print("  BEST PERFORMING TITLES & HOOKS (from A/B completed)")
print("=" * 75)
for w in get_ab_winning_titles(10):
    c = w.get('ctr', 0) or 0
    imps = w.get('impressions', 0) or 0
    print(f"  CTR={c:.1f}%  imps={imps:>3d}  {w.get('variant_value','')[:55]}")

print()
for h in get_best_hooks(5):
    print(f"  [{h.get('archetype','?')}] {h.get('hook_text','')[:60]}")

print()
print("=" * 75)
print("  VELOCITY DISTRIBUTION")
print("=" * 75)
buckets = [('>5/day',0), ('2-5/day',0), ('1-2/day',0), ('0.5-1/day',0), ('0.1-0.5/day',0), ('0/day',0)]
for v in videos:
    vel = v['velocity']
    if vel >= 5: buckets[0] = (buckets[0][0], buckets[0][1]+1)
    elif vel >= 2: buckets[1] = (buckets[1][0], buckets[1][1]+1)
    elif vel >= 1: buckets[2] = (buckets[2][0], buckets[2][1]+1)
    elif vel >= 0.5: buckets[3] = (buckets[3][0], buckets[3][1]+1)
    elif vel > 0: buckets[4] = (buckets[4][0], buckets[4][1]+1)
    else: buckets[5] = (buckets[5][0], buckets[5][1]+1)
for label, count in buckets:
    bar = '#' * count
    print(f"  {label:12s}  {count:2d}  {bar}")

print()
print("=" * 75)
print("  TOP VELOCITY VIDEOS (>0.5/day)")
print("=" * 75)
for v in sorted(videos, key=lambda x: x['velocity'], reverse=True):
    if v['velocity'] < 0.5:
        break
    cl = v['classification']
    pub = v.get('published_at','') or v.get('created_at','')
    print(f"  {v['velocity']:>5.2f}/d  {v['views']:>2d}v  {cl:11s}  {v['topic'][:45]}")
    print(f"         {v['youtube_url']}")
