"""Growth Intelligence Engine — topic expansion, clustering, opportunity discovery, portfolio balancing.

Responsibility:
1. Topic expansion beyond the static map
2. Topic clustering for content portfolio analysis
3. Competitor-inspired pattern detection
4. Emerging trend discovery
5. Content portfolio balancing recommendations
6. Opportunity identification

All decisions stored in memory via existing topic_lineages and best_practices tables.
"""

import logging
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Any, Optional

from mindmargin.analytics.memory import (
    get_all_classifications, get_pipeline_history, get_top_performers,
    get_topic_lineages, save_topic_lineage, mark_topic_published,
    save_best_practice, get_best_practices, get_best_hooks, get_best_titles,
)

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# Topic Expansion (beyond static map)
# ──────────────────────────────────────────────

# Base topic domains for expansion seed
_TOPIC_DOMAINS = [
    "business failure", "corruption", "political scandal",
    "financial crisis", "startup failure", "tech disruption",
    "fraud", "class action", "regulatory failure",
    "industry disruption", "cultural phenomenon",
    "sports controversy", "criminal enterprise", "media scandal",
]

# Related topic keywords for similarity matching
_TOPIC_KEYWORDS: dict[str, list[str]] = {
    "ftx": ["crypto", "bitcoin", "exchange", "sbf", "alameda", "binance"],
    "theranos": ["elizabeth holmes", "blood test", "healthcare", "startup fraud"],
    "enron": ["energy trading", "accounting fraud", "andrew fastow", "wall street"],
    "wecrashed": ["adam neumann", "softbank", "coworking", "real estate"],
    "madoff": ["ponzi", "wall street", "sec", "investment fraud"],
    "uber": ["gig economy", "ride sharing", "toxic culture", "tech startup"],
    "nokia": ["mobile phones", "finland", "smartphone", "disruption"],
}


def expand_topic_tree(parent_topic: str, max_depth: int = 2) -> list[dict]:
    """Generate topic expansion recommendations beyond the static map.

    Uses existing classifications, performance data, and keyword similarity
    to suggest child topics with confidence scores.
    """
    normalized = parent_topic.lower().strip()
    existing = get_topic_lineages(normalized, limit=50)
    existing_children = {e["child_topic"] for e in existing}

    # Get the topic's keywords
    seed_keywords = _TOPIC_KEYWORDS.get(normalized, [normalized])

    # Collect all published topics for pattern matching
    history = get_pipeline_history(200)
    published_topics = [p.get("topic", "").lower() for p in history if p.get("youtube_video_id")]

    # Score potential child topics
    candidates: list[dict] = []
    seen = {normalized} | existing_children

    # 1. Keyword-similar topics from history
    for pub_topic in set(published_topics):
        if pub_topic in seen:
            continue
        # Simple keyword overlap scoring
        pub_words = set(re.findall(r"\w+", pub_topic))
        overlap = sum(1 for kw in seed_keywords if kw in pub_topic or any(w in kw or kw in w for w in pub_words))
        if overlap > 0:
            confidence = min(overlap / max(len(seed_keywords), 1) * 0.8 + 0.2, 1.0)
            candidates.append({
                "parent": normalized,
                "child": pub_topic,
                "confidence": round(confidence, 2),
                "method": "keyword_match",
            })
            seen.add(pub_topic)

    # 2. Domain-based suggestions
    for domain in _TOPIC_DOMAINS:
        key = f"{domain} {normalized}"
        if key not in seen:
            candidates.append({
                "parent": normalized,
                "child": key,
                "confidence": 0.3,
                "method": "domain_seed",
            })

    # Sort by confidence
    candidates.sort(key=lambda c: c["confidence"], reverse=True)

    # Persist high-confidence suggestions
    for c in candidates[:10]:
        if c["confidence"] >= 0.4:
            save_topic_lineage(
                c["parent"], c["child"],
                c["confidence"],
                performance_inheritance=c["confidence"] * 0.5,
            )

    return candidates[:15]


# ──────────────────────────────────────────────
# Topic Clustering
# ──────────────────────────────────────────────

def cluster_published_topics() -> list[dict]:
    """Group published topics into clusters based on keyword similarity."""
    history = get_pipeline_history(200)
    published = [p for p in history if p.get("youtube_video_id")]

    # Simple keyword-based clustering
    clusters: dict[str, list[dict]] = defaultdict(list)
    assigned = set()

    # Use known topic families
    topic_families: dict[str, list[str]] = {
        "financial_fraud": ["enron", "madoff", "wirecard", "theranos"],
        "crypto_collapse": ["ftx", "celsius", "terra luna", "three arrows capital"],
        "tech_failure": ["nokia", "blackberry", "kodak", "myspace", "yahoo"],
        "startup_fraud": ["theranos", "wework", "uber"],
        "banking_crisis": ["lehman brothers", "silicon valley bank", "credit suisse"],
    }

    for p in published:
        topic = p.get("topic", "").lower()
        matched = False
        for family, keywords in topic_families.items():
            if any(kw in topic or topic in kw for kw in keywords):
                clusters[family].append(p)
                assigned.add(p["id"])
                matched = True
                break
        if not matched:
            clusters["other"].append(p)

    result = []
    for family, members in clusters.items():
        result.append({
            "cluster": family,
            "count": len(members),
            "members": [{"id": m["id"], "topic": m.get("topic")} for m in members],
            "avg_views": round(
                sum(m.get("stats", {}).get("views", 0)
                    for m in members if hasattr(m, "get"))
                / max(len(members), 1),
            ),
        })

    result.sort(key=lambda c: c["count"], reverse=True)
    return result


# ──────────────────────────────────────────────
# Opportunity Identification
# ──────────────────────────────────────────────

def identify_growth_opportunities() -> list[dict]:
    """Score and rank content opportunities.

    Factors:
    - Topic similarity to existing winners (performance inheritance)
    - Gap in current portfolio (untapped clusters)
    - Keyword momentum (inferred from frequency in recent history)
    - Expansion potential (how many child topics per parent)
    """
    classifications = get_all_classifications(200)
    history = get_pipeline_history(200)
    published = {p["id"] for p in history if p.get("youtube_video_id")}
    lineages = get_topic_lineages(limit=100)

    opportunities = []

    # 1. Unpublished child topics from lineage (highest potential)
    for lineage in lineages:
        if not lineage.get("is_published"):
            inheritance = lineage.get("performance_inheritance", 0) or 0
            confidence = lineage.get("confidence", 0) or 0
            score = inheritance * 0.6 + confidence * 0.4
            opportunities.append({
                "topic": lineage["child_topic"],
                "type": "lineage_expansion",
                "parent": lineage["parent_topic"],
                "score": round(score, 2),
                "rationale": f"Performance inheritance from '{lineage['parent_topic']}': {inheritance:.2f}",
            })

    # 2. Performers' topics not yet covered
    top_performers = get_top_performers("views", 10)
    published_topics = {p.get("topic", "").lower() for p in history if p["id"] in published}
    for tp in top_performers:
        t = tp.get("topic", "").lower()
        for known, keywords in _TOPIC_KEYWORDS.items():
            if known not in published_topics and known != t:
                opportunities.append({
                    "topic": known,
                    "type": "portfolio_gap",
                    "parent": t,
                    "score": 0.5,
                    "rationale": f"Similar to high-performer '{t}' but not yet covered",
                })
                break

    # 3. Fresh topics (no competition within channel)
    for domain in _TOPIC_DOMAINS:
        if not any(domain.split()[0] in t for t in published_topics):
            opportunities.append({
                "topic": domain,
                "type": "new_domain",
                "parent": "",
                "score": 0.35,
                "rationale": f"Untapped domain: {domain}",
            })

    # Deduplicate and sort
    seen_topics = set()
    unique_ops = []
    for op in sorted(opportunities, key=lambda x: x["score"], reverse=True):
        if op["topic"] not in seen_topics:
            seen_topics.add(op["topic"])
            unique_ops.append(op)

    return unique_ops[:20]


# ──────────────────────────────────────────────
# Content Portfolio Balancing
# ──────────────────────────────────────────────

def analyze_portfolio_balance() -> dict:
    """Evaluate how balanced the content portfolio is across domains."""
    clusters = cluster_published_topics()
    classifications = get_all_classifications(200)

    total = sum(c["count"] for c in clusters)
    if total == 0:
        return {"status": "insufficient_data", "clusters": 0}

    # Herfindahl-Hirschman Index for concentration
    shares = [(c["count"] / total) ** 2 for c in clusters]
    hhi = sum(shares) * 100

    # Dominant cluster
    dominant = max(clusters, key=lambda c: c["count"]) if clusters else None

    # Weak clusters (below average performance)
    weak_clusters = []
    for c in clusters:
        weak = [cls for cls in classifications
                if cls.get("classification") in ("weak_signal", "insufficient_signal")]
        wc = sum(1 for w in weak if any(
            w.get("pipeline_id", "") == m["id"] for m in c["members"]
        ))
        if wc > 0 and c["count"] > 0:
            weak_pct = (wc / c["count"]) * 100
            if weak_pct > 50:
                weak_clusters.append({
                    "cluster": c["cluster"],
                    "weak_pct": round(weak_pct, 0),
                    "recommendation": "Re-evaluate or diversify away from this cluster",
                })

    return {
        "status": "completed",
        "total_clusters": len(clusters),
        "cluster_distribution": [
            {"name": c["cluster"], "count": c["count"],
             "pct": round(c["count"] / total * 100, 1)}
            for c in clusters
        ],
        "concentration_index": round(hhi, 1),
        "dominant_cluster": dominant["cluster"] if dominant else "",
        "dominant_pct": round(dominant["count"] / total * 100, 0) if dominant else 0,
        "weak_clusters": weak_clusters,
        "recommendation": (
            "Portfolio is well-diversified" if hhi < 30
            else "Consider diversifying into new topic domains" if hhi < 50
            else "High concentration risk — actively seek new content domains"
        ),
    }


# ──────────────────────────────────────────────
# Main Entry Point
# ──────────────────────────────────────────────

def run_growth_analysis() -> dict:
    """Run full growth intelligence analysis and return consolidated report."""
    clusters = cluster_published_topics()
    opportunities = identify_growth_opportunities()
    balance = analyze_portfolio_balance()

    report = {
        "status": "completed",
        "generated_at": datetime.utcnow().isoformat(),
        "clusters": clusters,
        "opportunities": opportunities,
        "portfolio_balance": balance,
        "top_recommendations": [
            op["topic"] for op in opportunities[:5]
        ],
    }

    # Persist top opportunity as a best practice
    if opportunities:
        top = opportunities[0]
        save_best_practice(
            "growth", "next_topic_recommendation",
            f"Next recommended topic: '{top['topic']}' (score: {top['score']})",
            top["score"] * 10,
        )

    logger.info(f"Growth analysis: {len(clusters)} clusters, "
                f"{len(opportunities)} opportunities identified")
    return report
