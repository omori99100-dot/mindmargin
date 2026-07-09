"""Module 8 — Daily Strategy Planner: top opportunities → ranked publishing plan."""

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path

from mindmargin.config import settings
from mindmargin.analytics.memory import (
    get_top_opportunities, save_daily_strategy, get_pipeline_history,
    get_execution_log, get_intelligence_rules, is_successful_publish,
)

logger = logging.getLogger(__name__)


class DailyPlanner:
    """Generate daily publishing strategy from intelligence data."""

    def __init__(self):
        self.strategy_date = datetime.utcnow().strftime("%Y-%m-%d")
        self.output_dir = Path(settings.storage.output_root) / "intelligence"
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def plan(self) -> dict:
        """Generate today's publishing plan.

        Returns dict with top opportunities, predicted scores, and publishing priority.
        """
        opportunities = get_top_opportunities(20)
        history = get_pipeline_history(100)
        rules = get_intelligence_rules()
        execution_log = get_execution_log(50)

        published_today = sum(
            1 for e in execution_log
            if e.get("executed_at", "").startswith(self.strategy_date)
            and is_successful_publish(e)
        )

        published_topics = {
            e.get("topic", "").lower().strip()
            for e in execution_log
            if e.get("executed_at", "").startswith(self.strategy_date)
        }

        # Score and rank opportunities with additional strategy factors
        ranked = []
        for opp in opportunities:
            topic = opp.get("topic", "")
            if topic.lower().strip() in published_topics:
                continue

            base_score = opp.get("opportunity_score", 0)

            # Freshness bonus: higher score for newer opportunities
            scored_at = opp.get("scored_at", "")
            freshness_bonus = 0
            if scored_at:
                try:
                    scored_dt = datetime.strptime(scored_at[:10], "%Y-%m-%d")
                    hours_ago = (datetime.utcnow() - scored_dt).total_seconds() / 3600
                    freshness_bonus = max(0, 5 - hours_ago / 24)
                except ValueError:
                    pass

            # Novelty bonus: prefer topics not covered recently
            recency_penalty = 0
            topic_lower = topic.lower()
            topic_words = set(topic_lower.split())
            for p in history[-20:]:
                if topic_words & set(p.get("topic", "").lower().split()):
                    recency_penalty -= 3

            final_score = base_score + freshness_bonus + recency_penalty

            ranked.append({
                "topic": topic,
                "opportunity_score": round(base_score, 1),
                "strategy_score": round(final_score, 1),
                "freshness_bonus": round(freshness_bonus, 1),
                "recency_penalty": round(recency_penalty, 1),
                "source": opp.get("source", ""),
                "confidence": opp.get("confidence", 0),
            })

        ranked.sort(key=lambda x: x["strategy_score"], reverse=True)

        # Strategy summary
        strategy = {
            "strategy_date": self.strategy_date,
            "generated_at": datetime.utcnow().isoformat(),
            "total_opportunities": len(opportunities),
            "ranked_count": len(ranked),
            "published_today": published_today,
            "daily_cap": 1,
            "top_pick": ranked[0] if ranked else None,
            "ranked_opportunities": ranked[:20],
            "recommended_topic": ranked[0]["topic"] if ranked else "",
            "recommended_strategy": self._recommend_strategy(ranked, rules, history),
        }

        # Save to DB and disk
        save_daily_strategy(self.strategy_date, json.dumps(strategy))
        self._save_to_disk(strategy)

        logger.info(f"Daily strategy: {len(ranked)} ranked opportunities, "
                    f"top={ranked[0]['topic'] if ranked else 'none'}")
        return strategy

    def _recommend_strategy(self, ranked: list[dict], rules: list[dict],
                            history: list[dict]) -> str:
        """Generate a plain-text publishing strategy recommendation."""
        if not ranked:
            return "No opportunities available. Run intelligence collection first."

        top = ranked[0]
        lines = [
            f"Publishing Priority: {top['topic']}",
            f"  Strategy Score: {top['strategy_score']:.1f}",
            f"  Opportunity Score: {top['opportunity_score']:.1f}",
            f"  Confidence: {top.get('confidence', 0):.0%}",
        ]

        # Add best practices as recommendations
        for rule in rules[:3]:
            lines.append(f"  Rule: {rule.get('value', '')}")
        return "\n".join(lines)

    def _save_to_disk(self, strategy: dict):
        md_path = self.output_dir / f"daily_strategy_{self.strategy_date}.md"
        json_path = self.output_dir / f"daily_strategy_{self.strategy_date}.json"

        json_path.write_text(
            json.dumps(strategy, indent=2, default=str), encoding="utf-8"
        )

        lines = [
            f"# Daily Strategy — {self.strategy_date}",
            f"",
            f"**Top Pick:** {strategy.get('recommended_topic', 'N/A')}",
            f"**Published Today:** {strategy.get('published_today', 0)} / {strategy.get('daily_cap', 1)}",
            f"**Total Opportunities:** {strategy.get('total_opportunities', 0)}",
            f"**Ranked:** {strategy.get('ranked_count', 0)}",
            f"",
            f"## Top 10 Opportunities",
            f"",
        ]
        for i, opp in enumerate(strategy.get("ranked_opportunities", [])[:10], 1):
            lines.append(
                f"{i}. **{opp['topic']}** — Score: {opp['strategy_score']:.1f} "
                f"(Opp: {opp['opportunity_score']:.1f})"
            )
        lines.extend([
            f"",
            f"## Strategy",
            f"",
            strategy.get("recommended_strategy", ""),
            f"",
            f"---",
            f"_Generated: {strategy.get('generated_at', '')}_",
        ])
        md_path.write_text("\n".join(lines), encoding="utf-8")


def run_daily_planning() -> dict:
    planner = DailyPlanner()
    return planner.plan()
