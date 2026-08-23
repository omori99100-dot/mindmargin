# Phase 21.1 — Reality Audit: Documentary Production Engine

**Audit Date:** 2026-07-04  
**Pipeline Run:** `pipe_20260703_223127` — "How Netscape Lost the Browser War — follow-up analysis"  
**Test Suite:** 144/144 pass

---

## Executive Summary

**Quality Score: 28/100**  
**Production Readiness: CRITICAL — Not ready for launch**

The Phase 21 documentary engine architecture is well-designed but the implementation is 80% placeholder/fallback logic. The pipeline runs end-to-end but produces **unusable output** — research is empty, quality scores are hardcoded, scene plans are generic boilerplate, thumbnails use random text, and titles reference wrong topics.

---

## CRITICAL FINDINGS (Must Fix Before Launch)

### C1: `generate_json_sync` / `generate_section_sync` Do Not Exist
**Severity:** CRITICAL | **File:** `integrations/provider.py`  
**Evidence:** Pipeline log: `LLM research enhancement failed: 'OllamaProvider' object has no attribute 'generate_json_sync'`

The base `LLMProvider` class only has async methods (`generate`, `generate_json`, `generate_section`). The sync wrappers called in `script.py:409,436,470,509,542` and `research.py:184` don't exist on any provider.

**Impact:** Every LLM call after the initial async generation falls back to hardcoded defaults:
- Research: all 17 categories remain `data: [], status: "pending"`
- Scene plans: all sections get generic "Visual representation of [section]" boilerplate
- Thumbnail concepts: single hardcoded concept with `emotion_score=70, curiosity_score=65`
- Production report: all scores hardcoded to 50
- Quality scoring: all sections scored 50/100 across all dimensions
- Section regeneration: never triggered (the `generate_section_sync` call fails silently)

**Root Cause:** The sync methods were never implemented on the provider classes. `script.py` and `research.py` call methods that don't exist.

**Fix:** Add sync wrapper methods to `LLMProvider` base class that run async methods via `asyncio.run()` or `loop.run_until_complete()`.

---

### C2: Research Agent Produces Zero Data
**Severity:** CRITICAL | **File:** `agents/research.py`  
**Evidence:** `research_data.json` shows all 17 categories with `data: [], status: "pending"`

The `build_research()` method creates empty stubs for all 17 categories. The `_enhance_with_llm()` method calls `llm.generate_json_sync()` which fails (see C1). No web search is performed — the research stage is purely structural.

**Impact:** Script agent receives empty research dict → generates sections from topic name alone → content is generic and lacks factual depth.

---

### C3: Titles Reference Wrong Topics
**Severity:** CRITICAL | **File:** `agents/script.py:277-292`  
**Evidence:** `script.json` titles:
```
"RadioShack's Fall from Fame: A Behavioral Economics Perspective"
"Long-Term Capital Management: The Undefeated Truth"
"A Tale of Two Corporations: Why RadioShack and Long-Term Capital Management Disappeared"
```

The LLM (`_generate_titles`) generates titles for **different case studies** instead of "How Netscape Lost the Browser War". The `best_title` is "Why Netscape Disappeared: The Complete Untold Story" which is at least on-topic, but 4 of 5 generated titles are wrong.

**Impact:** Wrong titles propagate to SEO, thumbnails, and YouTube metadata.

---

### C4: Thumbnail Text Is Wrong
**Severity:** CRITICAL | **File:** `agents/thumbnail.py`  
**Evidence:** Thumbnail text in `thumbnail_manifest.json`:
```
"Netflix, Google, and Netscape: A Tale of Three Faces" (4 variants)
"Why Netscape Disappeared: The Complete Untold Story" (2 variants)
"The Browser War Analysis: How Netscape Lost the Race" (2 variants)
"RadioShack's Fall from Fame: A Behavioral Economics Perspective" (2 variants)
```

The thumbnail agent generates random text that doesn't match the `best_title` from script.json. 2 of 10 variants reference RadioShack — a completely different company.

**Impact:** Thumbnails would be unusable for YouTube upload.

---

### C5: Scene Plans Are Generic Boilerplate
**Severity:** HIGH | **File:** `agents/script.py:431-459`  
**Evidence:** All 10 sections have identical scene plans:
```json
{
  "scene_description": "Visual representation of [section_name]",
  "broll_suggestion": "Footage related to [Section Title]",
  "footage_keywords": ["[section_name]", "documentary", "business"],
  "camera_movement": "static",
  "emotion": "neutral"
}
```

The `_generate_scene_plans()` calls `llm.generate_json_sync()` which fails → falls back to `_default_scene_plan()` which generates identical boilerplate for every section.

**Impact:** No visual diversity in video; every section looks the same.

---

### C6: Editing Agent Doesn't Consume Scene Plans
**Severity:** HIGH | **File:** `agents/editing.py`  
**Evidence:** `editing.py` has zero references to `scene_plan`. The `SECTION_COLORS` dict uses old section names (`hook, rise, first_crack, overconfidence_loop, escalation, twist, lesson, close`) that don't match the new 10-section documentary structure (`hook, context, historical_background, growth_story, critical_decisions, main_mistakes, collapse, consequences, lessons_learned, closing`).

**Impact:** Even if scene plans were generated properly, the editing agent would ignore them entirely.

---

### C7: Thumbnail Agent Doesn't Consume Thumbnail Concepts
**Severity:** HIGH | **File:** `agents/thumbnail.py`  
**Evidence:** `thumbnail.py` has zero references to `thumbnail_concepts`. The `best_title` from script.json is not used — thumbnail text is generated independently.

**Impact:** Thumbnail concepts with emotion/curiosity scores are generated but never used for selection or rendering.

---

### C8: Production Report Scores Are All Hardcoded
**Severity:** HIGH | **File:** `agents/script.py:560-575`  
**Evidence:** `script.json` production report:
```json
{
  "story_score": 50,
  "documentary_quality_score": 50,
  "hook_score": 50,
  "engagement_prediction": 50,
  "visual_diversity_score": 50,
  "estimated_retention_curve": [80, 60, 40],
  "strengths": [],
  "weaknesses": [],
  "comparable_references": [],
  "recommended_improvements": []
}
```

The `_generate_production_report()` calls `llm.generate_json_sync()` which fails → falls back to `_default_production_report()` which returns all 50s with empty arrays.

**Impact:** No meaningful quality assessment; production report is useless.

---

### C9: All Section Quality Scores Are 50/100
**Severity:** HIGH | **File:** `agents/script.py:545-554`  
**Evidence:** Every section in `script.json` has:
```json
"quality_scores": {
  "narrative_arc": 50, "specificity": 50, "emotional_depth": 50,
  "pacing": 50, "originality": 50, "transitions": 50,
  "information_density": 50, "behavioral_insight": 50,
  "documentary_quality": 50, "overall_score": 50
}
```

The `_score_section()` calls `llm.generate_json_sync()` which fails → falls back to `_default_scores()` which returns all 50s.

**Impact:** Quality gate cannot differentiate good sections from bad ones.

---

### C10: Quality Gates Only Check Word Count
**Severity:** MEDIUM | **File:** `agents/script.py:360-375`  
**Evidence:** `_quality_gate()` only checks `len(text.split()) < MIN_SECTION_WORD_COUNT`. It does NOT check quality scores, narrative arc, specificity, or any other quality dimension.

**Impact:** A section with 150 words of garbage passes the quality gate. A section with 149 words of brilliance fails it.

---

## MEDIUM FINDINGS

### M1: Hook Text Is Nonsensical
**Severity:** MEDIUM | **File:** `agents/script.py:294-307`  
**Evidence:** Hooks reference "The collapse of circuit city — follow-up analysis" instead of "How Netscape Lost the Browser War":
```
"The collapse of circuit city — follow-up analysis— What if everything you know about the collapse of circuit city — follow-up analy"
```

The LLM generates hooks for the wrong topic. The `HOOK_TEMPLATES` fallback also uses generic placeholders.

---

### M2: SEO Description Is Incoherent
**Severity:** MEDIUM | **File:** `agents/script.py:350-358`  
**Evidence:** `seo.description`: "How Netscape Lost the Browser War — follow-up analysis - The Untold Story Behind the Phone"

"The Phone" has nothing to do with Netscape or browser wars.

---

### M3: Video Render Produced 0KB File
**Severity:** MEDIUM | **File:** `utils/ffmpeg.py`  
**Evidence:** `video/pipe_20260703_223127_raw.mp4` is 0KB — the concat was interrupted by timeout (300s). Rendering 20 clips + concat took >5 minutes.

**Impact:** Pipeline timeout is too short for 10-section documentaries.

---

### M4: 53 Empty Exception Handlers (try/except/pass)
**Severity:** MEDIUM | **File:** Multiple files  
**Evidence:** 53 instances of `except Exception: pass` silently swallowing errors across the codebase. Critical ones:
- `core/pipeline.py:105` — plugin manager creation
- `agents/script.py:275,476,515` — LLM warm-up, thumbnail concepts, story scoring
- `integrations/youtube/client.py:366,608` — YouTube API errors

---

### M5: Piper TTS Placeholder
**Severity:** LOW | **File:** `integrations/piper.py:29,58,72`  
**Evidence:** When Piper binary is not found, a silent WAV placeholder is created. This is intentional but means voice generation produces silence.

---

## DEAD CODE / UNUSED MODULES

| Item | Location | Status |
|------|----------|--------|
| `LEGACY_SECTION_NAMES` | `script.py` | Defined but never referenced |
| `SECTION_PROMPTS` alias | `prompts/__init__.py` | Preserved for backward compat but no callers |
| `scene_plan` in script output | `script.py` | Generated but never consumed by editing |
| `thumbnail_concepts` in script output | `script.py` | Generated but never consumed by thumbnail |
| Quality scores in sections | `script.py` | Generated but never used for gating decisions |
| `production_report` | `script.py` | Generated but never consumed by pipeline |

---

## WHAT ACTUALLY WORKS

| Feature | Status | Notes |
|---------|--------|-------|
| 10-section documentary structure | WORKS | Sections generated correctly with LLM |
| Section word counts | WORKS | 5358 words across 10 sections |
| Quality gate (word count only) | WORKS | Passes at 5358 words |
| Voice generation | WORKS | Cached from previous run |
| Thumbnail rendering | WORKS | 10 variants generated |
| Video section rendering | WORKS | 20 clips rendered (title + content per section) |
| FFmpeg concat | WORKS | Would complete if given enough time |
| Intel QSV encoding | WORKS | 34.6 fps hardware encoding |
| Pipeline orchestration | WORKS | All stages execute in order |
| Decision executor | WORKS | Topic selection, daily cap, logging all function |

---

## RECOMMENDED FIX ORDER

### Phase 21.2 — Critical Path (Before Launch)
1. **Add `generate_json_sync` and `generate_section_sync` to LLMProvider** (fixes C1, which cascades to fix C2, C5, C8, C9)
2. **Fix thumbnail text to use `best_title` from script.json** (fixes C4)
3. **Fix title generation to stay on-topic** (fixes C3)
4. **Connect scene plans to editing agent** (fixes C6)
5. **Connect thumbnail concepts to thumbnail agent** (fixes C7)

### Phase 21.3 — Quality (After Launch)
6. Quality gates should check quality scores, not just word count (fixes C10)
7. Hook generation should use correct topic (fixes M1)
8. SEO description should be coherent (fixes M2)
9. Increase pipeline timeout for 10-section documentaries (fixes M3)
10. Add logging to empty exception handlers (fixes M4)

---

## PRODUCTION READINESS SCORE

| Dimension | Score | Notes |
|-----------|-------|-------|
| Architecture | 90/100 | Well-designed 10-section documentary structure |
| Implementation | 25/100 | 80% fallback/placeholder logic |
| LLM Integration | 10/100 | Sync methods don't exist; all LLM calls after initial generation fail |
| Content Quality | 15/100 | Generic boilerplate; wrong topics in titles/hooks/thumbnails |
| Visual Quality | 40/100 | Thumbnails render but with wrong text; scene plans are identical |
| Audio Quality | 70/100 | Voice generation works (cached) |
| Video Quality | 50/100 | Clips render correctly but concat needs more time |
| Testing | 85/100 | 144 tests pass but don't validate actual output quality |
| **Overall** | **28/100** | **Not ready for public launch** |

---

## BOTTOM LINE

The pipeline **runs** but produces **unusable content**. The core blocker is that `generate_json_sync` and `generate_section_sync` methods don't exist on the LLM providers, causing every LLM call after initial section generation to fail silently and fall back to hardcoded defaults. Fixing this single issue would cascade improvements across research, scene planning, quality scoring, thumbnail concepts, and production reports.

The architecture is solid. The implementation needs the sync wrapper methods added, then the downstream connections (scene plans → editing, thumbnail concepts → thumbnail agent) need to be wired up.
