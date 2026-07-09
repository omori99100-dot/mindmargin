"""Module 5 — Self-Learning Rules: adaptive recommendation engine."""

import logging
from collections import defaultdict
from datetime import datetime
from typing import Optional

from mindmargin.analytics.memory import (
    get_all_intelligence_rules, save_intelligence_rule,
    get_pipeline_history, get_best_practices,
    get_best_hooks, get_best_titles, get_top_performers,
)

logger = logging.getLogger(__name__)


class LearningEngine:
    """Adaptive learning engine that discovers and updates content rules."""

    def __init__(self):
        self.rules: list[dict] = []
        self._history = get_pipeline_history(200)

    def learn_all(self) -> list[dict]:
        """Run all learning passes and return updated rules."""
        self._learn_title_patterns()
        self._learn_hook_patterns()
        self._learn_publish_cadence()
        self._learn_niche_focus()
        self._learn_video_characteristics()
        self._consolidate_rules()

        logger.info(f"Learning engine: {len(self.rules)} rules active")
        return self.rules

    def _learn_title_patterns(self):
        """Learn optimal title formats from top performers."""
        titles = get_best_titles(20)
        if not titles:
            return

        patterns: dict[str, list[float]] = defaultdict(list)
        for t in titles:
            title = t.get("title", "")
            ctr = t.get("ctr", 0) or 0
            if ctr <= 0:
                continue
            # Question titles
            if title.startswith(("How", "Why", "What", "Who", "Where", "When")):
                patterns["question_format"].append(ctr)
            # List-style titles
            if any(c.isdigit() for c in title[:5]):
                patterns["numbered_list"].append(ctr)
            # Bold claims
            if any(w in title.lower() for w in ["the", "story", "truth", "inside"]):
                patterns["story_format"].append(ctr)
            # Colon titles
            if ":" in title:
                patterns["colon_format"].append(ctr)

        for pattern, ctrs in patterns.items():
            if ctrs:
                avg_ctr = sum(ctrs) / len(ctrs)
                save_intelligence_rule("title_format", pattern,
                                       f"Title pattern '{pattern}' avg CTR {avg_ctr:.1f}%",
                                       score=avg_ctr * 10,
                                       sample_size=len(ctrs),
                                       confidence=min(len(ctrs) / 10, 0.9))

    def _learn_hook_patterns(self):
        """Learn optimal hook structures from performance data."""
        hooks = get_best_hooks(20)
        archetype_scores: dict[str, list[float]] = defaultdict(list)
        for h in hooks:
            arch = h.get("archetype", "unknown")
            score = h.get("ctr_score", 0) or 0
            if score > 0:
                archetype_scores[arch].append(score)

        for arch, scores in archetype_scores.items():
            avg = sum(scores) / len(scores)
            save_intelligence_rule("hook_archetype", arch,
                                   f"Hook archetype '{arch}' avg score {avg:.1f}",
                                   score=avg,
                                   sample_size=len(scores),
                                   confidence=min(len(scores) / 5, 0.9))

    def _learn_publish_cadence(self):
        """Learn optimal publishing cadence."""
        published = [p for p in self._history if p.get("youtube_video_id")]
        if len(published) < 3:
            return

        dates = []
        for p in published:
            dt = p.get("published_at", "") or p.get("created_at", "")
            if dt:
                try:
                    dates.append(datetime.strptime(dt[:19], "%Y-%m-%d %H:%M:%S"))
                except ValueError:
                    pass

        if len(dates) >= 3:
            dates.sort()
            gaps = [(dates[i + 1] - dates[i]).days for i in range(len(dates) - 1)]
            if gaps:
                avg_gap = sum(gaps) / len(gaps)
                save_intelligence_rule("cadence", "optimal_gap",
                                       f"Optimal publishing gap: {avg_gap:.1f} days",
                                       score=min(100 / max(avg_gap, 1), 100),
                                       sample_size=len(gaps),
                                       confidence=min(len(gaps) / 5, 0.9))

    def _learn_niche_focus(self):
        """Learn which niche clusters perform best."""
        performers = get_top_performers(10)
        if not performers:
            return

        keywords = {
            "financial_fraud": ["fraud", "scandal", "ponzi", "collapse"],
            "business_story": ["story", "rise", "fall", "history"],
            "tech": ["tech", "startup", "silicon", "digital"],
        }

        cluster_views: dict[str, list[int]] = defaultdict(list)
        for p in performers:
            topic = p.get("topic", "").lower()
            views = p.get("views", 0) or 0
            for cluster, kws in keywords.items():
                if any(kw in topic for kw in kws):
                    cluster_views[cluster].append(views)

        for cluster, views in cluster_views.items():
            if views:
                avg = sum(views) / len(views)
                save_intelligence_rule("niche_focus", cluster,
                                       f"Niche '{cluster}' avg {avg:.0f} views",
                                       score=min(avg, 100),
                                       sample_size=len(views),
                                       confidence=min(len(views) / 5, 0.9))

    def _learn_video_characteristics(self):
        """Learn optimal video characteristics (length, style)."""
        durations = [(p.get("video_duration_s", 0) or 0,
                      p.get("views", 0) or 0)
                     for p in self._history
                     if (p.get("video_duration_s", 0) or 0) > 0]

        if len(durations) >= 5:
            durations.sort(key=lambda x: x[1], reverse=True)
            top_dur = sum(d[0] for d in durations[:5]) / max(len(durations[:5]), 1)
            save_intelligence_rule("video_characteristics", "optimal_duration",
                                   f"Optimal duration: {top_dur:.0f}s ({top_dur/60:.1f}min)",
                                   score=min(top_dur / 60 * 5, 100),
                                   sample_size=min(len(durations), 50),
                                   confidence=min(len(durations) / 20, 0.9))

    def _consolidate_rules(self):
        """Load all rules from DB for the rules property."""
        self.rules = get_all_intelligence_rules()


def run_learning_cycle() -> list[dict]:
    engine = LearningEngine()
    return engine.learn_all()
