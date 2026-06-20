"""Optimization engine: weighted scoring model, ruleset builder, prompt injector.

Transforms raw analytics into strict generation constraints using a deterministic
weighted decision system. Cold-starts with domain defaults, activates real data
as it accumulates.
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from mindmargin.analytics.memory import (
    get_best_practices, get_best_hooks, get_best_titles,
    get_top_performers, get_pipeline_history,
    get_reinforced_patterns, get_suppressed_patterns,
    get_dead_patterns, get_topic_lineages,
)

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# Domain defaults for cold-start (no data yet)
# ──────────────────────────────────────────────

_DEFAULT_HOOK_ARCHETYPES = [
    {"archetype": "curiosity_gap", "avg_score": 88.0, "count": 1, "final_score": 88.0},
    {"archetype": "fear_based", "avg_score": 85.0, "count": 1, "final_score": 85.0},
    {"archetype": "contrarian", "avg_score": 82.0, "count": 1, "final_score": 82.0},
    {"archetype": "shock_value", "avg_score": 79.0, "count": 1, "final_score": 79.0},
    {"archetype": "mystery", "avg_score": 76.0, "count": 1, "final_score": 76.0},
]

_DEFAULT_HOOK_EXAMPLES = [
    {"archetype": "curiosity_gap", "hook_text": "What If Everything You Know About {topic} Is Wrong?", "ctr_score": 88},
    {"archetype": "fear_based", "hook_text": "The {topic} Warning Signs Everyone Ignored", "ctr_score": 85},
    {"archetype": "contrarian", "hook_text": "Why {topic} Was Actually Inevitable", "ctr_score": 82},
]

_DEFAULT_TITLE_EXAMPLES = [
    {"title": "{topic}: The Complete Untold Story", "ctr": 15.0, "used_count": 0},
    {"title": "The Rise and Fall of {topic}", "ctr": 12.0, "used_count": 0},
    {"title": "{topic}: A Behavioral Economics Autopsy", "ctr": 14.0, "used_count": 0},
]

_DEFAULT_RETENTION_DROP = 70.0
_DEFAULT_PACING_WPM = 150.0


# ──────────────────────────────────────────────
# Weighted Scoring Model
# ──────────────────────────────────────────────

@dataclass
class ScoredPattern:
    key: str
    category: str
    value: str
    impact: float        # 0-10
    confidence: float    # 0-1
    frequency: int       # how many times observed
    engagement_weight: float  # 0-1 (CTR / retention / watch time correlation)
    final_score: float   # computed: impact * confidence * frequency_norm * engagement_weight
    source: str = "default"  # "data" or "domain_default"

    @property
    def passes_threshold(self) -> bool:
        return self.final_score >= 7.0


@dataclass
class OptimizationRuleset:
    hook_rules: list[str] = field(default_factory=list)
    title_rules: list[str] = field(default_factory=list)
    thumbnail_rules: list[str] = field(default_factory=list)
    retention_rules: list[str] = field(default_factory=list)
    pacing_rules: list[str] = field(default_factory=list)
    structure_rules: list[str] = field(default_factory=list)
    avoid_rules: list[str] = field(default_factory=list)
    hook_archetype_ranking: list[dict] = field(default_factory=list)
    best_hook_examples: list[dict] = field(default_factory=list)
    best_title_examples: list[dict] = field(default_factory=list)
    retention_drop_pct: float = 70.0
    pacing_wpm: float = 150.0
    ruleset_source: str = "default"
    scored_patterns: list[ScoredPattern] = field(default_factory=list)
    filtered_patterns: list[dict] = field(default_factory=list)


def _performance_weight_selection(classification: str) -> float:
    return {"winner_candidate": 1.5, "keep_testing": 1.0,
            "stable_equivalent": 0.8, "weak_signal": 0.1}.get(classification, 1.0)


class OptimizationEngine:
    """Deterministic engine: queries memory → scores patterns → builds ruleset."""

    def __init__(self):
        self._cache: Optional[OptimizationRuleset] = None

    def build(self, force_refresh: bool = False) -> OptimizationRuleset:
        if self._cache and not force_refresh:
            return self._cache
        patterns = self._collect_patterns()
        scored = self._score_patterns(patterns)
        passed = [p for p in scored if p.passes_threshold]
        filtered = [p for p in scored if not p.passes_threshold]
        ruleset = self._build_ruleset(passed, filtered)
        self._cache = ruleset
        logger.info(f"OptimizationRuleset: {len(passed)} rules active, {len(filtered)} filtered")
        return ruleset

    def _collect_patterns(self) -> list[dict]:
        raw = get_best_practices()
        hooks = get_best_hooks(10)
        titles = get_best_titles(10)
        tops = get_top_performers("avg_view_duration_s", 10)
        history = get_pipeline_history(50)

        has_data = bool(hooks or titles or tops)
        patterns = []

        # --- Hook archetype patterns ---
        arch_scores = {}
        for h in hooks:
            arch = h.get("archetype", "unknown")
            score = h.get("actual_ctr") or h.get("ctr_score", 0)
            if arch not in arch_scores:
                arch_scores[arch] = []
            arch_scores[arch].append(score)

        if arch_scores:
            for arch, scores in arch_scores.items():
                avg = sum(scores) / len(scores)
                patterns.append({
                    "category": "hook_archetype",
                    "key": arch,
                    "value": f"Hook archetype '{arch}' scores {avg:.1f}",
                    "raw_score": avg,
                    "frequency": len(scores),
                    "impact": min(avg / 10, 10),
                    "confidence": min(len(scores) / 10, 1.0),
                    "engagement_weight": 0.9,
                })
        else:
            # Cold-start defaults (high frequency to pass threshold until real data)
            for a in _DEFAULT_HOOK_ARCHETYPES:
                patterns.append({
                    "category": "hook_archetype",
                    "key": a["archetype"],
                    "value": f"Hook archetype '{a['archetype']}' scores {a['avg_score']:.0f}",
                    "raw_score": a["avg_score"],
                    "frequency": 5,
                    "impact": a["avg_score"] / 10,
                    "confidence": 0.5,
                    "engagement_weight": 0.9,
                })

        # --- Retention patterns ---
        if tops:
            avg_ret = sum(t.get("avg_view_duration_s", 0) for t in tops) / len(tops)
            patterns.append({
                "category": "retention",
                "key": "avg_view_duration",
                "value": f"Top videos average {avg_ret:.0f}s view duration",
                "raw_score": avg_ret,
                "frequency": len(tops),
                "impact": min(avg_ret / 60, 10),
                "confidence": min(len(tops) / 10, 1.0),
                "engagement_weight": 1.0,
            })
        else:
            patterns.append({
                "category": "retention",
                "key": "retention_drop_first_30s",
                "value": f"First 30 seconds determine {_DEFAULT_RETENTION_DROP:.0f}% of viewer drop-off",
                "raw_score": _DEFAULT_RETENTION_DROP,
                "frequency": 5,
                "impact": 8.0,
                "confidence": 0.5,
                "engagement_weight": 1.0,
            })

        # --- Title patterns ---
        if titles:
            for t in titles:
                ctr = t.get("ctr", 0) or 0
                patterns.append({
                    "category": "title",
                    "key": t.get("title", "")[:60],
                    "value": f"Title CTR: {ctr:.1f}%",
                    "raw_score": ctr,
                    "frequency": t.get("used_count", 1) or 1,
                    "impact": min(ctr * 0.7, 10),
                    "confidence": min((t.get("used_count", 1) or 1) / 10, 1.0),
                    "engagement_weight": 0.8,
                })

        # --- Pacing patterns ---
        if history:
            pacing_points = []
            for h in history:
                wc = h.get("word_count", 0)
                dur = h.get("video_duration_s", 0)
                if wc > 0 and dur > 0:
                    pacing_points.append((wc / dur) * 60)
            if pacing_points:
                avg_wpm = sum(pacing_points) / len(pacing_points)
                patterns.append({
                    "category": "pacing",
                    "key": "avg_words_per_min",
                    "value": f"Average pacing: {avg_wpm:.0f} words/min",
                    "raw_score": avg_wpm,
                    "frequency": len(pacing_points),
                    "impact": 10 - abs(avg_wpm - 150) / 15,
                    "confidence": min(len(pacing_points) / 20, 1.0),
                    "engagement_weight": 0.7,
                })

        # --- Avoid patterns (negative signals) ---
        # These are learned from low-performing videos
        # For now, domain defaults
        for avoid in [
            {"key": "passive_opening", "value": "Avoid passive openings that don't create immediate curiosity"},
            {"key": "generic_language", "value": "Avoid generic phrases like 'in this video' or 'let's talk about'"},
            {"key": "no_emotional_hook", "value": "Do not start without an emotional hook in the first 5 seconds"},
            {"key": "weak_cta", "value": "Avoid weak calls to action — be specific about what to do next"},
        ]:
            patterns.append({
                "category": "avoid",
                "key": avoid["key"],
                "value": avoid["value"],
                "raw_score": 50,
                "frequency": 5,
                "impact": 7.0,
                "confidence": 0.5,
                "engagement_weight": 0.8,
            })

        # --- Selection Pressure: reinforced patterns (evolutionary winners) ---
        reinforced = get_reinforced_patterns(limit=20)
        for rp in reinforced:
            cat = rp["category"]
            key = rp["key"]
            score = rp.get("selection_score", 0) or 0
            conf = rp.get("confidence", 0) or 0
            rf_count = rp.get("reinforcement_count", 1) or 1
            pclass = rp.get("performance_class", "stable")

            # Scale score: selection_score * reinforcement_count
            boosted = score * min(rf_count, 5) * _performance_weight_selection(pclass)
            if cat == "hook_archetype":
                patterns.append({
                    "category": "hook_archetype",
                    "key": key,
                    "value": f"[SELECTION] Reinforced hook '{key}' ({rf_count}x wins, score={score:.2f})",
                    "raw_score": boosted * 10,
                    "frequency": rf_count * 2,
                    "impact": min(boosted * 5, 10),
                    "confidence": min(conf + 0.2, 1.0),
                    "engagement_weight": 0.95,
                })
            elif cat == "title":
                patterns.append({
                    "category": "title",
                    "key": key[:60],
                    "value": f"[SELECTION] Reinforced title pattern (score={score:.2f})",
                    "raw_score": boosted * 8,
                    "frequency": rf_count,
                    "impact": min(boosted * 4, 10),
                    "confidence": min(conf + 0.1, 1.0),
                    "engagement_weight": 0.85,
                })
            elif cat == "topic":
                patterns.append({
                    "category": "structure",
                    "key": f"topic_{key}",
                    "value": f"[SELECTION] Strong topic category '{key}' ({rf_count}x reinforced)",
                    "raw_score": boosted * 10,
                    "frequency": rf_count,
                    "impact": min(boosted * 3, 10),
                    "confidence": min(conf + 0.15, 1.0),
                    "engagement_weight": 0.75,
                })

        # --- Selection Pressure: suppressed patterns (evolutionary losers) ---
        suppressed = get_suppressed_patterns(limit=10)
        for sp in suppressed:
            decay = sp.get("current_decay", 1.0) or 1.0
            s_count = sp.get("suppression_count", 1) or 1
            # Only add as avoid if decayed below 0.7
            if decay < 0.7:
                patterns.append({
                    "category": "avoid",
                    "key": f"suppressed_{sp['category']}_{sp['key']}",
                    "value": (f"AVOID: {sp['value']} "
                              f"(decayed to {decay:.1%}, suppressed {s_count}x)"),
                    "raw_score": 30,
                    "frequency": s_count,
                    "impact": 8.0,
                    "confidence": min(0.5 + (s_count * 0.1), 0.9),
                    "engagement_weight": 0.9,
                })

        # --- Selection Pressure: dead patterns (archived failures) ---
        dead = get_dead_patterns(limit=5)
        for dp in dead:
            patterns.append({
                "category": "avoid",
                "key": f"dead_{dp['category']}_{dp['key']}",
                "value": (f"DEAD PATTERN - DO NOT USE: {dp['value']} "
                          f"(archived after {dp['suppression_count']} failures)"),
                "raw_score": 10,
                "frequency": dp.get("suppression_count", 5) or 5,
                "impact": 9.0,
                "confidence": 0.85,
                "engagement_weight": 1.0,
            })

        # --- Selection Pressure: topic expansion suggestions ---
        suggestions = get_topic_lineages(limit=10)
        unpub = [s for s in suggestions if not s.get("is_published")][:3]
        if unpub:
            topic_list = ", ".join(s["child_topic"] for s in unpub)
            patterns.append({
                "category": "structure",
                "key": "topic_expansion",
                "value": f"Consider related topic: {topic_list}",
                "raw_score": 75,
                "frequency": len(unpub),
                "impact": 7.0,
                "confidence": 0.6,
                "engagement_weight": 0.7,
            })

        return patterns


    def _score_patterns(self, patterns: list[dict]) -> list[ScoredPattern]:
        scored = []
        for p in patterns:
            impact = p.get("impact", 5.0)
            confidence = p.get("confidence", 0.5)
            frequency = p.get("frequency", 1)
            ew = p.get("engagement_weight", 0.5)
            freq_norm = min(frequency / 5.0, 1.0)
            final = impact * confidence * freq_norm * ew * 2.5
            scored.append(ScoredPattern(
                key=p["key"],
                category=p["category"],
                value=p["value"],
                impact=round(impact, 1),
                confidence=round(confidence, 2),
                frequency=frequency,
                engagement_weight=round(ew, 2),
                final_score=round(final, 1),
                source="data" if frequency > 1 else "default",
            ))
        scored.sort(key=lambda s: s.final_score, reverse=True)
        return scored

    def _build_ruleset(self, passed: list[ScoredPattern],
                       filtered: list[ScoredPattern]) -> OptimizationRuleset:
        ruleset = OptimizationRuleset()

        # Hook archetype ranking
        hook_archs = [p for p in passed if p.category == "hook_archetype"]
        if hook_archs:
            for p in hook_archs:
                ruleset.hook_archetype_ranking.append({
                    "archetype": p.key,
                    "avg_score": p.impact * 10,
                    "count": p.frequency,
                    "final_score": p.final_score,
                })
                ruleset.hook_rules.append(
                    f"Prioritize '{p.key}' hook archetype (score: {p.final_score:.0f})"
                )
        else:
            # Use defaults
            for a in _DEFAULT_HOOK_ARCHETYPES:
                ruleset.hook_archetype_ranking.append(a)
            ruleset.hook_rules.append("Use curiosity_gap as primary hook archetype")

        # Hook examples
        best_hooks_data = get_best_hooks(3)
        if best_hooks_data:
            ruleset.best_hook_examples = best_hooks_data
        else:
            ruleset.best_hook_examples = _DEFAULT_HOOK_EXAMPLES

        # Title rules
        title_patterns = [p for p in passed if p.category == "title"]
        if title_patterns:
            ruleset.title_rules.append("Use title patterns with proven CTR from your channel")
            for p in title_patterns[:3]:
                ruleset.title_rules.append(f"Title format: {p.value} (score: {p.final_score:.0f})")
        else:
            ruleset.title_rules.extend([
                "Keep titles under 50 characters for 15% higher CTR",
                "Include numbers or specific data points in titles",
                "Create curiosity gaps — hint at information without revealing it",
            ])
        # Title examples
        best_titles_data = get_best_titles(3)
        if best_titles_data:
            ruleset.best_title_examples = best_titles_data
        else:
            ruleset.best_title_examples = _DEFAULT_TITLE_EXAMPLES

        # Retention rules
        ret_p = next((p for p in passed if p.category == "retention"), None)
        if ret_p:
            ruleset.retention_rules.append(ret_p.value)
            if "30" in ret_p.key:
                ruleset.retention_drop_pct = ret_p.impact * 10
        else:
            ruleset.retention_rules.append(
                f"First 30 seconds determine {_DEFAULT_RETENTION_DROP:.0f}% of viewer drop-off"
            )
            ruleset.retention_drop_pct = _DEFAULT_RETENTION_DROP

        # Pacing rules
        pac_p = next((p for p in passed if p.category == "pacing"), None)
        if pac_p:
            ruleset.pacing_rules.append(pac_p.value)
            if "words/min" in pac_p.value:
                try:
                    ruleset.pacing_wpm = float(pac_p.value.split()[-2])
                except (ValueError, IndexError):
                    pass
        else:
            ruleset.pacing_rules.append(f"Aim for {_DEFAULT_PACING_WPM:.0f} words/min spoken pace")
            ruleset.pacing_wpm = _DEFAULT_PACING_WPM

        # Structure rules (always active)
        ruleset.structure_rules.extend([
            "First 30 seconds must contain: hook → curiosity gap → promise",
            "Each section must end with a transition that creates anticipation",
            "Keep paragraphs to 2-3 sentences max for spoken delivery",
            "Use rhetorical questions to maintain engagement throughout",
        ])

        # Avoid rules
        for p in passed:
            if p.category == "avoid":
                ruleset.avoid_rules.append(p.value)

        # Add default avoids
        default_avoids = [
            "Do NOT start with a cold factual statement — lead with emotion",
            "Do NOT use more than 3 sentences without a pattern interrupt",
            "Do NOT end sections without a forward-looking hook",
        ]
        for av in default_avoids:
            if av not in ruleset.avoid_rules:
                ruleset.avoid_rules.append(av)

        # Filtered patterns
        ruleset.filtered_patterns = [
            {"key": f.key, "category": f.category, "score": f.final_score,
             "reason": f"Below threshold 7.0 (impact={f.impact}, confidence={f.confidence}, freq={f.frequency})"}
            for f in filtered
        ]

        # Source label
        ruleset.ruleset_source = "data" if any(p.source == "data" for p in passed) else "default"
        ruleset.scored_patterns = passed

        return ruleset


# ──────────────────────────────────────────────
# Prompt Injectors
# ──────────────────────────────────────────────

def build_optimized_hook_prompt(topic: str, ruleset: OptimizationRuleset) -> str:
    """Build hook generation prompt with weighted ruleset injected."""
    ranking_lines = []
    for r in ruleset.hook_archetype_ranking:
        score = r.get("final_score", r.get("avg_score", 0))
        ranking_lines.append(f"  - {r['archetype']}: {r['avg_score']:.0f} (score: {score:.0f})")
    ranking_str = "\n".join(ranking_lines) or "No hook archetype data available."

    hook_lines = []
    for h in ruleset.best_hook_examples:
        arch = h.get("archetype", "?")
        text = h.get("hook_text", "")[:80]
        score = h.get("ctr_score", 0) or h.get("avg_score", 0)
        hook_lines.append(f"  - [{arch}] \"{text}\" (score: {score:.0f})")
    hook_str = "\n".join(hook_lines) or "No hook examples in memory."

    avoid_str = "\n".join(f"  - {a}" for a in ruleset.avoid_rules[:3]) if ruleset.avoid_rules else ""

    prompt = f"""Generate 5 YouTube video hooks for a documentary about '{topic}' in the behavioral economics niche.

OPTIMIZATION RULESET (derived from performance data):
{ranking_str}

Top-performing hooks from similar content:
{hook_str}

Hook rules:
{chr(10).join(f'  - {r}' for r in ruleset.hook_rules[:3])}

{"What to avoid:" if avoid_str else ""}
{avoid_str}

Constraints:
- Prioritize the top-2 performing archetypes
- Each hook must create an open loop and curiosity gap
- Keep under 200 characters
- Use power words and emotional triggers proven to drive CTR
- First 5 seconds must grab attention immediately

For each hook, provide:
- archetype: one of [curiosity_gap, fear_based, contrarian, shock_value, mystery]
- hook_text: the actual hook (1-2 sentences, punchy)
- ctr_score: estimated click-through rate (0-100)
- emotional_trigger: the primary emotion it triggers
- retention_score: estimated audience retention (0-100)
- open_loop: whether it creates an open loop (true/false)
- engagement_bait: whether it prompts comments (true/false)

Return as JSON array of objects."""
    return prompt


def build_optimized_title_prompt(topic: str, ruleset: OptimizationRuleset) -> str:
    """Build title generation prompt with CTR data injected."""
    title_lines = []
    for t in ruleset.best_title_examples:
        ctr = t.get("ctr", 0) or 0
        used = t.get("used_count", 0) or 0
        title_lines.append(f"  - \"{t.get('title', '')[:60]}\" (CTR: {ctr:.1f}, used {used}x)")
    title_str = "\n".join(title_lines) or "No title data available."

    rule_lines = "\n".join(f"  - {r}" for r in ruleset.title_rules[:4])

    prompt = f"""Generate 5 YouTube video titles for a documentary about '{topic}' in the behavioral economics / business autopsy niche.

Best-performing titles from your channel:
{title_str}

Title optimization rules:
{rule_lines}

Each title must be:
- Clickable (curiosity gap, numbers, power words)
- SEO-optimized (include target keywords)
- Under 70 characters
- Descriptive enough that viewers know what they'll learn
- Specific, not generic

Return as JSON array of strings."""
    return prompt


def build_optimized_section_prompt(
    section_name: str, topic: str, title: str,
    duration_s: int, ruleset: OptimizationRuleset,
) -> str:
    """Build section generation prompt with retention/pacing rules injected."""
    retention_rule = ruleset.retention_rules[0] if ruleset.retention_rules else ""
    pacing_rule = ruleset.pacing_rules[0] if ruleset.pacing_rules else ""
    avoid_rules = "\n".join(f"  - {a}" for a in ruleset.avoid_rules[:3]) if ruleset.avoid_rules else ""
    structure_rules = "\n".join(f"  - {s}" for s in ruleset.structure_rules[:3])

    base_prompts = {
        "hook": f"""Write the HOOK section of a documentary script about {topic}.
Section title: {title}
Duration target: {duration_s}s

OPTIMIZATION RULES:

Retention Rule: {retention_rule}
Pacing Rule: {pacing_rule}

Structural Constraints:
{structure_rules}

{"What to Avoid:" if avoid_rules else ""}
{avoid_rules}

Style:
- Open with a shocking statistic, provocative question, or vivid scene
- Use open loops and curiosity gaps
- End with a promise that compels the viewer to keep watching
- First 30 seconds must be the most compelling part
- Every sentence must either inform or create tension

Write 150-300 words of compelling narration.""",

        "rise": f"""Write the RISE section of a documentary script about {topic}.
Section title: {title}
Duration target: {duration_s}s

OPTIMIZATION RULES:

Pacing Rule: {pacing_rule}
Retention Rule: {retention_rule}

Style: Chronicle the early success story. Show the optimism, the vision, the rapid growth. Make the audience feel the excitement and momentum. Foreshadow the cracks subtly.
- Keep paragraphs to 2-3 spoken sentences
- End with a forward-looking hook to the next section

Write 200-400 words.""",

        "first_crack": f"""Write the FIRST CRACK section of a documentary script about {topic}.
Section title: {title}
Duration target: {duration_s}s

OPTIMIZATION RULES:
Pacing Rule: {pacing_rule}

Style: The first warning signs emerge. Early skeptics, ignored red flags. Build tension. Show how rational people rationalized away the evidence.
- Use specific examples to create visceral tension
- Each paragraph should escalate the unease

Write 200-400 words.""",

        "overconfidence_loop": f"""Write the OVERCONFIDENCE LOOP section of a documentary script about {topic}.
Section title: {title}
Duration target: {duration_s}s

OPTIMIZATION RULES:
Pacing Rule: {pacing_rule}

Style: Deep dive into the psychology. Overconfidence bias, illusion of control, confirmation bias. Show how success bred arrogance.
- Use behavioral economics concepts naturally within the narrative
- Avoid academic language — make psychology feel like storytelling
- End with foreshadowing of the coming collapse

Write 250-450 words.""",

        "escalation": f"""Write the ESCALATION section of a documentary script about {topic}.
Section title: {title}
Duration target: {duration_s}s

OPTIMIZATION RULES:
Pacing Rule: {pacing_rule}

Style: Doubling down despite mounting evidence. Sunk cost fallacy in action. The stakes get higher. Tension becomes unbearable.
- Paint the picture of people trapped by their own decisions
- Use rhetorical questions to make the viewer feel the tension

Write 200-400 words.""",

        "collapse": f"""Write the COLLAPSE section of a documentary script about {topic}.
Section title: {title}
Duration target: {duration_s}s

Style: The moment everything falls apart. Dramatic, visceral storytelling. Show the human cost. Let the weight of failure sink in.
- Use specific, concrete details
- Let the gravity of the moment land without rushing
- This is the emotional peak — make it count

Write 200-400 words.""",

        "twist": f"""Write the TWIST section of a documentary script about {topic}.
Section title: {title}
Duration target: {duration_s}s

Style: The unexpected angle. What most people get wrong about this story. A contrarian take backed by evidence. Surprise the audience.
- Reframe everything they thought they knew
- Use data or evidence to support the counter-narrative
- End by connecting back to the broader lesson

Write 150-300 words.""",

        "lesson": f"""Write the LESSON section of a documentary script about {topic}.
Section title: {title}
Duration target: {duration_s}s

Style: Extract actionable wisdom. Connect to universal human biases. Make it personal for the viewer.
- Bridge from historical case study to personal relevance
- Use "you" to make the lesson feel direct and applicable
- This section should feel like a revelation

Write 150-300 words.""",

        "close": f"""Write the CLOSE section of a documentary script about {topic}.
Section title: {title}
Duration target: {duration_s}s

Style: Memorable, emotional ending. Echo the opening hook. Leave the audience with a lasting thought or question.
- Include a specific call to action (like, subscribe, comment)
- End on a powerful, quotable line
- Make it feel complete, not abrupt

Write 100-200 words.""",
    }

    return base_prompts.get(
        section_name,
        f"Write the {section_name.replace('_', ' ').title()} section of a documentary script about {topic}.\n"
        f"Section title: {title}\nDuration target: {duration_s}s\n\nWrite 150-400 words."
    )


def build_optimized_seo_prompt(topic: str, title: str, ruleset: OptimizationRuleset) -> str:
    """Build SEO metadata prompt with best-performing tags and formats."""
    title_lines = "\n".join(
        f"  - \"{t.get('title', '')[:60]}\""
        for t in ruleset.best_title_examples[:3]
    ) if ruleset.best_title_examples else "No title data."

    prompt = f"""Generate SEO metadata for a YouTube documentary titled '{title}' about {topic}.

Best-performing title formats from your channel:
{title_lines}

Provide:
1. A search-optimized description (200-300 words) with:
   - Keyword-rich opening paragraph (first 150 characters are most important for SEO)
   - Timestamped chapters for each section
   - Related video suggestions
   - Engagement CTA (like, subscribe, comment with a specific question)
2. 10-15 relevant tags covering: topic name, niche keywords, related themes
3. A compelling thumbnail text concept (2-4 words, high impact)
4. Suggested YouTube category

Return as JSON with keys: description, tags (array), thumbnail_text, category."""
    return prompt


# ──────────────────────────────────────────────
# Convenience builder: single entry point
# ──────────────────────────────────────────────

def build_optimization_context(topic: str) -> tuple[OptimizationRuleset, dict[str, str]]:
    """Build full optimization context: ruleset + all generated prompts.

    Returns (ruleset, prompts_dict) where prompts_dict has keys:
    hook, title, seo, and section_<name> entries.
    """
    engine = OptimizationEngine()
    ruleset = engine.build()

    prompts = {
        "hook": build_optimized_hook_prompt(topic, ruleset),
        "title": build_optimized_title_prompt(topic, ruleset),
        "seo": build_optimized_seo_prompt(topic, topic, ruleset),
    }

    return ruleset, prompts
