"""Script Agent — Documentary Production Engine.

Phase 21: Professional documentary script generation with:
- 10-section documentary structure
- Quality gates with auto-regeneration
- Scene planning for visual diversity
- Hook optimization (5 candidates scored)
- Title generation (15 candidates scored)
- Production quality reports
"""
import asyncio
import json
import logging
import math
from datetime import datetime
from typing import Optional

from mindmargin.config import settings
from mindmargin.core.storage import ensure_dirs, write_text
from mindmargin.integrations.manager import ProviderManager, create_default_manager
from mindmargin.prompts import (
    DOCUMENTARY_SECTION_PROMPTS, HOOK_SYSTEM, HOOK_PROMPT,
    TITLE_SYSTEM, TITLE_PROMPT,
    SEO_SYSTEM, SEO_PROMPT,
    SCRIPT_SYSTEM,
    QUALITY_SYSTEM, QUALITY_SCORING_PROMPT,
    GENERATION_MODES,
    SCENE_PLANNING_SYSTEM, SCENE_PLANNING_PROMPT,
    THUMBNAIL_SYSTEM, THUMBNAIL_CONCEPT_PROMPT,
    PRODUCTION_REPORT_SYSTEM, PRODUCTION_REPORT_PROMPT,
)
from mindmargin.prompts.optimizer import (
    OptimizationEngine,
    build_optimized_hook_prompt,
    build_optimized_title_prompt,
    build_optimized_section_prompt,
    build_optimized_seo_prompt,
)

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════
#  DOCUMENTARY SECTION STRUCTURE — Phase 21
# ═══════════════════════════════════════════════════════════════════

DOCUMENTARY_SECTIONS = [
    ("hook", "Hook", 120),
    ("context", "Context", 180),
    ("historical_background", "Historical Background", 240),
    ("growth_story", "Growth Story", 300),
    ("critical_decisions", "Critical Decisions", 300),
    ("main_mistakes", "Main Mistakes", 300),
    ("collapse", "Collapse", 300),
    ("consequences", "Consequences", 240),
    ("lessons_learned", "Lessons Learned", 240),
    ("closing", "Closing", 120),
]

# Legacy section names for backward compatibility
LEGACY_SECTION_NAMES = [
    ("hook", "The Hook — Open with a shocking stat or question", 90),
    ("rise", "The Rise — How it all began and the rapid ascent", 180),
    ("first_crack", "The First Crack — Early warning signs ignored", 150),
    ("overconfidence_loop", "The Overconfidence Loop — Psychology of the decision-makers", 210),
    ("escalation", "Escalation — Doubling down despite mounting evidence", 180),
    ("collapse", "The Collapse — The moment it all fell apart", 180),
    ("twist", "The Twist — What most people get wrong", 120),
    ("lesson", "The Lesson — What we can learn from this", 90),
    ("close", "The Close — Memorable ending with channel CTA", 60),
]

TITLE_TEMPLATES = [
    "{topic}: The Complete Untold Story",
    "The Rise and Fall of {topic}",
    "{topic}: A Behavioral Economics Autopsy",
    "What Really Happened With {topic}",
    "The {topic} Disaster — Every Mistake Explained",
]

HOOK_TEMPLATES = [
    ("curiosity_gap", "What If Everything You Know About {topic} Is Wrong?", 88),
    ("fear_based", "The {topic} Warning Signs Everyone Ignored", 85),
    ("contrarian", "Why {topic} Was Actually Inevitable", 82),
    ("shock_value", "The $70 Billion Lesson Nobody Learned From {topic}", 79),
    ("mystery", "The Hidden Psychology Behind {topic}", 76),
]

FALLBACK_SECTION_TEXT = (
    "[Section {sec_id}: {title}]\n\n"
    "This section explores the {name} phase of the {topic} story. "
    "In a production pipeline, this would contain LLM-generated content "
    "analyzing the events, psychology, and implications.\n\n"
)

# Quality gate thresholds
MIN_WORD_COUNT = 1500
MIN_SECTION_WORD_COUNT = 100
QUALITY_PASS_THRESHOLD = 60
MAX_QUALITY_REGENERATION_ATTEMPTS = 2

# Expected scene plan keys for validation
SCENE_PLAN_KEYS: set[str] = {
    "scene_description", "broll_suggestion", "footage_keywords",
    "camera_movement", "on_screen_text", "visual_elements",
    "duration_s", "emotion",
}


def validate_scene_plan(scene_plan: object) -> tuple[list[dict], str]:
    """Validate a scene plan and return (clean_validated_list, error_message).

    Returns (valid_list, "") on success, (fallback_list, reason) on failure.
    The fallback is always a valid list of dicts compliant with SCENE_PLAN_KEYS.
    """
    if scene_plan is None:
        return _fallback_scene_plan(), "scene_plan is None"

    if not isinstance(scene_plan, list):
        return _fallback_scene_plan(), f"scene_plan type={type(scene_plan).__name__}, expected list"

    bad_elements: list[int] = []
    clean: list[dict] = []
    for idx, elem in enumerate(scene_plan):
        if not isinstance(elem, dict):
            bad_elements.append(idx)
            continue
        missing = SCENE_PLAN_KEYS - set(elem.keys())
        if missing:
            bad_elements.append(idx)
            continue
        clean.append(elem)

    if not bad_elements:
        return clean, ""

    reason = (
        f"scene_plan[{','.join(str(i) for i in bad_elements[:5])}] "
        f"invalid: {len(bad_elements)}/{len(scene_plan)} elements "
        f"not valid scene dicts"
    )
    if not clean:
        return _fallback_scene_plan(), reason
    return clean, reason


def _fallback_scene_plan() -> list[dict]:
    """Return a minimal valid scene plan."""
    return [{
        "scene_description": "Default visual representation of the section narrative",
        "broll_suggestion": "Stock footage related to the topic",
        "footage_keywords": ["documentary", "footage", "visual"],
        "camera_movement": "static",
        "on_screen_text": "",
        "visual_elements": [],
        "duration_s": 30,
        "emotion": "neutral",
    }]


def _build_timestamps(sections: list) -> str:
    cum = 0
    lines = []
    for sec_id, name, title, dur in sections:
        m, s = divmod(cum, 60)
        lines.append(f"{m:02d}:{s:02d} - {title}")
        cum += dur
    return "\n".join(lines)


def _estimate_duration_minutes(word_count: int) -> float:
    """Estimate narration duration from word count (avg 2.5 words/sec for documentaries)."""
    return round(word_count / (2.5 * 60), 1)


class ScriptAgent:
    """Documentary Production Engine — Phase 21.

    Generates professional documentary scripts with:
    - 10-section narrative structure
    - Quality gates with auto-regeneration
    - Scene planning for visual diversity
    - Hook/title optimization
    - Production quality reports
    """

    def __init__(self, mode: str = "documentary", use_templates: bool = False,
                 provider_manager: Optional[ProviderManager] = None):
        self.name = "script"
        self._pm = provider_manager or create_default_manager()
        self.llm = self._pm.get()
        self.mode = mode
        self.mode_config = GENERATION_MODES.get(mode, GENERATION_MODES["documentary"])
        self.use_templates = use_templates

    def run(self, topic: str, pipeline_id: str, research: dict) -> dict:
        logger.info(f"ScriptAgent: generating documentary script for '{topic}' (mode: {self.mode})")

        # Build optimization ruleset from stored performance data
        engine = OptimizationEngine()
        ruleset = engine.build()
        if ruleset.ruleset_source == "data":
            logger.info(f"Optimization active: {len(ruleset.scored_patterns)} patterns, "
                        f"source={ruleset.ruleset_source}")
        else:
            logger.info("Optimization: cold-start defaults (no analytics data yet)")

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            titles, hooks, sections, seo = loop.run_until_complete(
                self._run_async(topic, research, ruleset)
            )
        finally:
            loop.close()

        # Quality gate: validate and potentially regenerate
        sections = self._quality_gate(sections, topic)

        # Generate scene plans for visual diversity
        sections = self._generate_scene_plans(sections, topic)

        # Merge quality scores
        scored = self._merge_scores(sections, topic)

        full_text = "\n\n".join(s["text"] for s in scored)
        word_count = len(full_text.split())
        estimated_duration = _estimate_duration_minutes(word_count)

        # Generate thumbnail concepts
        thumbnail_concepts = self._generate_thumbnail_concepts(topic, titles[0] if titles else topic)

        # Generate production report
        production_report = self._generate_production_report(
            topic, titles[0] if titles else topic, word_count,
            estimated_duration, len(scored)
        )

        dirs = ensure_dirs(topic, pipeline_id)
        script_data = {
            "topic": topic,
            "generation_mode": self.mode,
            "titles": titles,
            "best_title": titles[0] if titles else topic,
            "hooks": hooks,
            "sections": scored,
            "full_script": full_text,
            "word_count": word_count,
            "estimated_duration_minutes": estimated_duration,
            "seo": seo,
            "thumbnail_concepts": thumbnail_concepts,
            "production_report": production_report,
            "generated_at": datetime.utcnow().isoformat(),
            "version": "2.0",
        }
        write_text(dirs["script"] / "script.json", json.dumps(script_data, indent=2))
        write_text(dirs["script"] / "full_script.txt", full_text)

        # Log quality metrics
        if production_report:
            logger.info(
                f"Script quality: story={production_report.get('story_score', '?')}/100 "
                f"doc={production_report.get('documentary_quality_score', '?')}/100 "
                f"hook={production_report.get('hook_score', '?')}/100 "
                f"retention={production_report.get('engagement_prediction', '?')}/100"
            )
        logger.info(f"Script: {word_count} words, ~{estimated_duration} min, "
                     f"{len(scored)} sections")

        return {
            "agent": self.name,
            "status": "completed",
            "script": script_data,
        }

    async def _run_async(self, topic: str, research: dict, ruleset=None):
        if self.use_templates:
            titles = [t.format(topic=topic) for t in TITLE_TEMPLATES]
            hooks = [
                {"archetype": a, "hook_text": h.format(topic=topic), "ctr_score": s,
                 "emotional_trigger": "curiosity" if "curiosity" in a else "fear",
                 "retention_score": s - 5, "open_loop": True, "engagement_bait": False}
                for a, h, s in HOOK_TEMPLATES
            ]
            sections = self._template_sections(topic, research)
            seo = self._template_seo(topic)
            return titles, hooks, sections, seo
        await self._warmup()
        titles_task = asyncio.create_task(self._generate_titles(topic, ruleset))
        hooks_task = asyncio.create_task(self._generate_hooks(topic, ruleset))
        sections_task = asyncio.create_task(self._generate_sections(topic, research, ruleset))
        seo_task = asyncio.create_task(self._generate_seo(topic, ruleset))
        titles, hooks, sections, seo = await asyncio.gather(
            titles_task, hooks_task, sections_task, seo_task
        )
        return titles, hooks, sections, seo

    def _template_sections(self, topic: str, research: dict) -> list[dict]:
        sections_out = []
        for sec_id, (name, title, target_dur) in enumerate(DOCUMENTARY_SECTIONS, 1):
            text = FALLBACK_SECTION_TEXT.format(
                sec_id=sec_id, title=title, name=name.replace("_", " "), topic=topic
            )
            sections_out.append({
                "section_id": sec_id,
                "name": name,
                "title": title,
                "text": text.strip(),
                "duration_target_s": target_dur,
                "word_count": len(text.split()),
                "mode": self.mode,
            })
        return sections_out

    def _template_seo(self, topic: str) -> dict:
        tag = topic.lower().replace(" ", "")
        return {
            "titles": [t.format(topic=topic) for t in TITLE_TEMPLATES],
            "description": (
                f"An in-depth behavioral economics analysis of {topic}.\n\n"
                f"#behavioraleconomics #businessautopsy #{tag}\n"
            ),
            "tags": [tag, f"{tag}documentary", "behavioral economics",
                     "business autopsy", "documentary", "business story"],
            "thumbnail_text": topic.split(" ")[0].upper() if topic else "MINDSET",
            "category": "Education",
            "related_suggestions": [],
        }

    async def _warmup(self):
        try:
            await self.llm.generate("Say hello", task="hook", temperature=0.1)
        except Exception as e:
            logger.debug(f"LLM warm-up failed (non-critical): {e}")

    async def _generate_titles(self, topic: str, ruleset=None) -> list[str]:
        if ruleset:
            prompt = build_optimized_title_prompt(topic, ruleset)
        else:
            prompt = TITLE_PROMPT.format(topic=topic)
        result = await self.llm.generate_json(prompt, system=TITLE_SYSTEM, task="title")
        if isinstance(result, list) and len(result) >= 3:
            # Extract titles from structured result
            titles = []
            for item in result[:15]:
                if isinstance(item, dict):
                    titles.append(item.get("title", str(item)))
                else:
                    titles.append(str(item))
            return titles
        return [t.format(topic=topic) for t in TITLE_TEMPLATES]

    async def _generate_hooks(self, topic: str, ruleset=None) -> list[dict]:
        if ruleset:
            prompt = build_optimized_hook_prompt(topic, ruleset)
        else:
            prompt = HOOK_PROMPT.format(topic=topic)
        result = await self.llm.generate_json(prompt, system=HOOK_SYSTEM, task="hook_gen")
        if isinstance(result, list) and len(result) >= 3:
            return result[:5]
        return [
            {"archetype": a, "hook_text": h.format(topic=topic), "ctr_score": s,
             "emotional_trigger": "curiosity" if "curiosity" in a else "fear",
             "retention_score": s - 5, "open_loop": True, "engagement_bait": False}
            for a, h, s in HOOK_TEMPLATES
        ]

    async def _generate_sections(self, topic: str, research: dict, ruleset=None) -> list[dict]:
        system = self.mode_config["system"]
        temperature = self.mode_config["temperature"]
        results = []

        for sec_id, (name, title, target_dur) in enumerate(DOCUMENTARY_SECTIONS, 1):
            # Get section-specific prompt
            section_prompt_template = DOCUMENTARY_SECTION_PROMPTS.get(name)
            if section_prompt_template:
                prompt = section_prompt_template.format(topic=topic, title=title, duration_s=target_dur)
            elif ruleset:
                prompt = build_optimized_section_prompt(
                    name, topic, title, target_dur, ruleset
                )
            else:
                prompt = f"Write the {title} section of a documentary about {topic}. Write 200-400 words of compelling narration."

            result = await self._generate_one_section(
                sec_id, name, title, target_dur, prompt, system, temperature
            )
            results.append(result)

        return results

    async def _generate_one_section(self, sec_id: int, name: str, title: str,
                                     target_dur: int, prompt: str,
                                     system: str, temperature: float) -> dict:
        text = await self.llm.generate_section(
            prompt, name, system=system, temperature=temperature
        )
        if not text:
            text = FALLBACK_SECTION_TEXT.format(
                sec_id=sec_id, title=title, name=name.replace("_", " "), topic=""
            )
        return {
            "section_id": sec_id,
            "name": name,
            "title": title,
            "text": text.strip(),
            "duration_target_s": target_dur,
            "word_count": len(text.split()),
            "mode": self.mode,
        }

    # ═══════════════════════════════════════════════════════════════════
    #  QUALITY GATES — Phase 21
    # ═══════════════════════════════════════════════════════════════════

    def _quality_gate(self, sections: list[dict], topic: str) -> list[dict]:
        """Validate script quality and regenerate weak sections if needed."""
        issues = []

        # Check total word count
        total_words = sum(s.get("word_count", 0) for s in sections)
        if total_words < MIN_WORD_COUNT:
            issues.append(f"total_words={total_words} < {MIN_WORD_COUNT}")

        # Check individual sections
        for sec in sections:
            wc = sec.get("word_count", 0)
            if wc < MIN_SECTION_WORD_COUNT:
                issues.append(f"section '{sec['name']}' has {wc} words < {MIN_SECTION_WORD_COUNT}")

        if not issues:
            logger.info(f"Quality gate: PASSED ({total_words} words across {len(sections)} sections)")
            return sections

        logger.warning(f"Quality gate issues: {issues}")

        # Attempt regeneration of weak sections
        for attempt in range(MAX_QUALITY_REGENERATION_ATTEMPTS):
            regenerated = False
            for i, sec in enumerate(sections):
                if sec.get("word_count", 0) < MIN_SECTION_WORD_COUNT:
                    logger.info(f"Regenerating section '{sec['name']}' (attempt {attempt + 1})")
                    new_sec = self._regenerate_section(sec, topic)
                    if new_sec and new_sec.get("word_count", 0) >= MIN_SECTION_WORD_COUNT:
                        sections[i] = new_sec
                        regenerated = True

            if not regenerated:
                break

        total_words = sum(s.get("word_count", 0) for s in sections)
        logger.info(f"Quality gate after regeneration: {total_words} words")
        return sections

    def _regenerate_section(self, section: dict, topic: str) -> Optional[dict]:
        """Attempt to regenerate a single section."""
        try:
            name = section["name"]
            title = section["title"]
            target_dur = section.get("duration_target_s", 240)

            section_prompt_template = DOCUMENTARY_SECTION_PROMPTS.get(name)
            if section_prompt_template:
                prompt = section_prompt_template.format(topic=topic, title=title, duration_s=target_dur)
            else:
                prompt = f"Write the {title} section of a documentary about {topic}. Write 200-400 words."

            text = self.llm.generate_section_sync(
                prompt, name, system=self.mode_config["system"],
                temperature=self.mode_config["temperature"]
            )
            if text and len(text.split()) >= MIN_SECTION_WORD_COUNT:
                logger.info(f"Section '{name}' regenerated: {len(text.split())} words")
                return {
                    "section_id": section["section_id"],
                    "name": name,
                    "title": title,
                    "text": text.strip(),
                    "duration_target_s": target_dur,
                    "word_count": len(text.split()),
                    "mode": self.mode,
                }
            logger.warning(f"Section '{name}' regeneration produced insufficient text ({len(text.split()) if text else 0} words)")
        except Exception as e:
            logger.warning(f"Section regeneration failed for '{section.get('name', '?')}': {e}")
        return None

    # ═══════════════════════════════════════════════════════════════════
    #  SCENE PLANNING — Phase 21
    # ═══════════════════════════════════════════════════════════════════

    def _generate_scene_plans(self, sections: list[dict], topic: str) -> list[dict]:
        """Generate scene plans for visual diversity in each section."""
        for sec in sections:
            plan = self._generate_single_scene_plan(sec, topic)
            sec["scene_plan"] = plan
        return sections

    def _generate_single_scene_plan(self, sec: dict, topic: str) -> list[dict]:
        """Generate scene plan for one section with validation + retry."""
        name = sec["name"]
        section_text = sec['text'][:1000]

        for attempt in range(2):
            try:
                prompt = SCENE_PLANNING_PROMPT.format(topic=topic)
                result = self.llm.generate_json_sync(
                    prompt + f"\n\nSection text:\n{section_text}",
                    system=SCENE_PLANNING_SYSTEM,
                    task="scene_planning"
                )
                clean, reason = validate_scene_plan(result)
                if not reason:
                    logger.info(f"Scene plan for '{name}': {len(clean)} scenes generated")
                    return clean
                logger.warning(
                    f"Scene plan for '{name}' attempt {attempt + 1} invalid: {reason}"
                )
                if attempt == 0:
                    section_text += (
                        "\n\nIMPORTANT: Response MUST be a JSON array of objects. "
                        "Each object MUST have exactly these keys: "
                        "scene_description, broll_suggestion, footage_keywords, "
                        "camera_movement, on_screen_text, visual_elements, "
                        "duration_s, emotion. No strings. No text outside JSON."
                    )
            except Exception as e:
                logger.warning(f"Scene plan generation failed for '{name}' attempt {attempt + 1}: {e}")

        fallback = self._default_scene_plan(sec)
        logger.warning(f"Scene plan for '{name}': all attempts failed, using default")
        return fallback

    def _default_scene_plan(self, section: dict) -> list[dict]:
        """Generate a basic scene plan when LLM fails."""
        return [{
            "scene_description": f"Visual representation of {section['name']}",
            "broll_suggestion": f"Footage related to {section.get('title', '')}",
            "footage_keywords": [section["name"], "documentary", "business"],
            "camera_movement": "static",
            "on_screen_text": "",
            "visual_elements": [],
            "duration_s": section.get("duration_target_s", 120) // 3,
            "emotion": "neutral",
        }]

    # ═══════════════════════════════════════════════════════════════════
    #  THUMBNAIL CONCEPTS — Phase 21
    # ═══════════════════════════════════════════════════════════════════

    def _generate_thumbnail_concepts(self, topic: str, title: str) -> list[dict]:
        """Generate thumbnail design concepts."""
        try:
            prompt = THUMBNAIL_CONCEPT_PROMPT.format(topic=topic)
            result = self.llm.generate_json_sync(
                prompt, system=THUMBNAIL_SYSTEM, task="thumbnail_concepts"
            )
            if isinstance(result, list) and len(result) > 0:
                logger.info(f"Thumbnail concepts: {len(result)} generated")
                return result[:10]
            logger.warning("Thumbnail concepts: LLM returned empty, using defaults")
        except Exception as e:
            logger.warning(f"Thumbnail concept generation failed: {e}")
        return self._default_thumbnail_concepts(topic)

    def _default_thumbnail_concepts(self, topic: str) -> list[dict]:
        """Default thumbnail concepts when LLM fails."""
        return [
            {
                "main_subject": topic,
                "facial_expression": "disbelief",
                "color_palette": {"primary": "#1a1a2e", "accent": "#e94560"},
                "composition": "center",
                "contrast_level": "high",
                "text_overlay": topic.split()[0] if topic else "FAILURE",
                "text_position": "bottom",
                "emotion_score": 70,
                "curiosity_score": 65,
                "visual_hierarchy": ["text", "subject", "background"],
            }
        ]

    # ═══════════════════════════════════════════════════════════════════
    #  PRODUCTION REPORT — Phase 21
    # ═══════════════════════════════════════════════════════════════════

    def _generate_production_report(self, topic: str, title: str,
                                     word_count: int, estimated_duration: float,
                                     section_count: int) -> Optional[dict]:
        """Generate a production quality report."""
        try:
            prompt = PRODUCTION_REPORT_PROMPT.format(
                topic=topic, title=title, word_count=word_count,
                estimated_duration=estimated_duration, section_count=section_count
            )
            result = self.llm.generate_json_sync(
                prompt, system=PRODUCTION_REPORT_SYSTEM, task="production_report"
            )
            if isinstance(result, dict) and result.get("story_score") is not None:
                logger.info(f"Production report: story={result.get('story_score')}, "
                           f"doc={result.get('documentary_quality_score')}, "
                           f"hook={result.get('hook_score')}")
                return result
            logger.warning("Production report: LLM returned empty/invalid, using defaults")
        except Exception as e:
            logger.warning(f"Production report generation failed: {e}")
        return {
            "story_score": 50,
            "documentary_quality_score": 50,
            "hook_score": 50,
            "engagement_prediction": 50,
            "visual_diversity_score": 50,
            "estimated_retention_curve": [80, 60, 40],
            "estimated_ctr": 4.0,
            "strengths": [],
            "weaknesses": [],
            "comparable_references": [],
            "recommended_improvements": [],
        }

    # ═══════════════════════════════════════════════════════════════════
    #  QUALITY SCORING — Phase 21
    # ═══════════════════════════════════════════════════════════════════

    def _merge_scores(self, sections: list[dict], topic: str) -> list[dict]:
        """Score each section for quality metrics."""
        scored = []
        for sec in sections:
            try:
                prompt = QUALITY_SCORING_PROMPT.format(
                    text=sec["text"][:2000], section_name=sec["name"], topic=topic
                )
                result = self.llm.generate_json_sync(
                    prompt, system=QUALITY_SYSTEM, task="quality_scoring"
                )
                if isinstance(result, dict) and "overall_score" in result:
                    sec["quality_scores"] = result
                    logger.debug(f"Quality scores for '{sec['name']}': overall={result.get('overall_score')}")
                else:
                    logger.warning(f"Quality scoring for '{sec['name']}': LLM returned invalid result, using defaults")
                    sec["quality_scores"] = self._default_scores()
            except Exception as e:
                logger.warning(f"Quality scoring failed for '{sec['name']}': {e}")
                sec["quality_scores"] = self._default_scores()
            scored.append(sec)
        return scored

    def _default_scores(self) -> dict:
        return {
            "narrative_arc": 50, "specificity": 50,
            "emotional_depth": 50, "pacing": 50,
            "originality": 50, "transitions": 50,
            "information_density": 50, "behavioral_insight": 50,
            "documentary_quality": 50, "overall_score": 50,
        }

    # ═══════════════════════════════════════════════════════════════════
    #  SEO — Phase 21
    # ═══════════════════════════════════════════════════════════════════

    async def _generate_seo(self, topic: str, ruleset=None) -> dict:
        if ruleset:
            prompt = build_optimized_seo_prompt(topic, topic, ruleset)
        else:
            prompt = SEO_PROMPT.format(title=topic, topic=topic)
        result = await self.llm.generate_json(prompt, system=SEO_SYSTEM, task="seo")
        if isinstance(result, dict) and "description" in result:
            return result
        tag = topic.lower().replace(" ", "")
        return {
            "titles": [t.format(topic=topic) for t in TITLE_TEMPLATES],
            "description": (
                f"An in-depth behavioral economics analysis of {topic}.\n\n"
                f"#behavioraleconomics #businessautopsy #{tag}\n"
            ),
            "tags": [tag, f"{tag}documentary", "behavioral economics",
                     "business autopsy", "documentary", "business story"],
            "thumbnail_text": topic.split()[0].upper() if topic else "MINDSET",
            "category": "Education",
            "related_suggestions": [],
        }
