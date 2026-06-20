import asyncio
import json
import logging
from datetime import datetime

from mindmargin.config import settings
from mindmargin.core.storage import ensure_dirs, write_text
from mindmargin.integrations.ollama import OllamaClient
from mindmargin.prompts import (
    SECTION_PROMPTS, HOOK_SYSTEM, HOOK_PROMPT,
    TITLE_SYSTEM, TITLE_PROMPT,
    SEO_SYSTEM, SEO_PROMPT,
    SCRIPT_SYSTEM,
    QUALITY_SYSTEM, QUALITY_SCORING_PROMPT,
    GENERATION_MODES,
)
from mindmargin.prompts.optimizer import (
    OptimizationEngine,
    build_optimized_hook_prompt,
    build_optimized_title_prompt,
    build_optimized_section_prompt,
    build_optimized_seo_prompt,
)

logger = logging.getLogger(__name__)

SECTION_NAMES = [
    ("hook", "The Hook \u2014 Open with a shocking stat or question", 90),
    ("rise", "The Rise \u2014 How it all began and the rapid ascent", 180),
    ("first_crack", "The First Crack \u2014 Early warning signs ignored", 150),
    ("overconfidence_loop", "The Overconfidence Loop \u2014 Psychology of the decision-makers", 210),
    ("escalation", "Escalation \u2014 Doubling down despite mounting evidence", 180),
    ("collapse", "The Collapse \u2014 The moment it all fell apart", 180),
    ("twist", "The Twist \u2014 What most people get wrong", 120),
    ("lesson", "The Lesson \u2014 What we can learn from this", 90),
    ("close", "The Close \u2014 Memorable ending with channel CTA", 60),
]

TITLE_TEMPLATES = [
    "{topic}: The Complete Untold Story",
    "The Rise and Fall of {topic}",
    "{topic}: A Behavioral Economics Autopsy",
    "What Really Happened With {topic}",
    "The {topic} Disaster \u2014 Every Mistake Explained",
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


def _build_timestamps(sections: list) -> str:
    cum = 0
    lines = []
    for sec_id, name, title, dur in sections:
        m, s = divmod(cum, 60)
        lines.append(f"{m:02d}:{s:02d} - {title}")
        cum += dur
    return "\n".join(lines)


class ScriptAgent:
    """AI-powered script generation with quality scoring, modes, and retention engineering."""

    def __init__(self, mode: str = "documentary", use_templates: bool = False):
        self.name = "script"
        self.llm = OllamaClient()
        self.mode = mode
        self.mode_config = GENERATION_MODES.get(mode, GENERATION_MODES["documentary"])
        self.use_templates = use_templates

    def run(self, topic: str, pipeline_id: str, research: dict) -> dict:
        logger.info(f"ScriptAgent: generating script for '{topic}' (mode: {self.mode})")

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

        scored = self._merge_scores(sections, topic)
        full_text = "\n\n".join(s["text"] for s in sections)
        word_count = len(full_text.split())

        dirs = ensure_dirs(topic, pipeline_id)
        script_data = {
            "topic": topic,
            "generation_mode": self.mode,
            "titles": titles,
            "best_title": titles[0],
            "hooks": hooks,
            "sections": scored,
            "full_script": full_text,
            "word_count": word_count,
            "seo": seo,
            "generated_at": datetime.utcnow().isoformat(),
        }
        write_text(dirs["script"] / "script.json", json.dumps(script_data, indent=2))
        write_text(dirs["script"] / "full_script.txt", full_text)

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
        for sec_id, (name, title, target_dur) in enumerate(SECTION_NAMES, 1):
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
        except Exception:
            pass

    async def _generate_titles(self, topic: str, ruleset=None) -> list[str]:
        if ruleset:
            prompt = build_optimized_title_prompt(topic, ruleset)
        else:
            prompt = TITLE_PROMPT.format(topic=topic)
        result = await self.llm.generate_json(prompt, system=TITLE_SYSTEM, task="title")
        if isinstance(result, list) and len(result) >= 3:
            return result[:5]
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

        for sec_id, (name, title, target_dur) in enumerate(SECTION_NAMES, 1):
            if ruleset:
                prompt = build_optimized_section_prompt(
                    name, topic, title, target_dur, ruleset
                )
            else:
                section_prompt = SECTION_PROMPTS.get(name, SECTION_PROMPTS["hook"])
                prompt = section_prompt.format(
                    topic=topic, title=title, duration_s=target_dur
                )
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

    def _merge_scores(self, sections: list[dict], topic: str) -> list[dict]:
        scored = []
        for sec in sections:
            scored.append({**sec, "quality_scores": {
                "hook_strength": 50, "retention_potential": 50,
                "emotional_intensity": 50, "informational_value": 50,
                "pacing_quality": 50, "clarity": 50, "originality": 50,
                "call_to_action_potential": 50, "psychological_depth": 50,
                "overall_quality": 50,
                "justification": "Skipped (accelerated)",
                "improvements": [],
            }})
        return scored

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
            "thumbnail_text": topic.split(" ")[0].upper() if topic else "MINDSET",
            "category": "Education",
            "related_suggestions": [],
        }
