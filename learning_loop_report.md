# Learning Loop Validation Report

**Date:** 2026-06-06

---

## Architecture Overview

The intended self-improvement cycle:

```
Pipeline → classify_video() → reinforce_winners()/suppress_losers()
    ↑                                              ↓
    │                                        reinforced_patterns
    │                                        suppressed_patterns
    │                                              ↓
    │                                      OptimizationEngine
    │                                              ↓
    └──── ScriptAgent (builds prompts) ←──── ruleset
```

## Link-by-Link Verification

### ✅ Working Links

| # | Chain | Status | Evidence |
|---|-------|--------|----------|
| 1 | `classify_video()` → `analytics` table | ✅ | `save_analytics()` writes views, likes, comments, impressions, CTR, retention |
| 2 | `classify_video()` → `video_classifications` table | ✅ | `save_classification()` writes classification, confidence, metrics |
| 3 | `video_classifications` → `reinforce_winners()` | ✅ | `get_all_classifications()` at selection.py:441 |
| 4 | `video_classifications` → `suppress_losers()` | ✅ | `get_all_classifications()` at selection.py:549 |
| 5 | `reinforce_winners()` → `reinforced_patterns` table | ✅ | `save_reinforced_pattern()` for topics, hook archetypes, titles |
| 6 | `suppress_losers()` → `suppressed_patterns` table | ✅ | `save_suppressed_pattern()` for topics, hook archetypes |
| 7 | `reinforced_patterns` → `OptimizationEngine` | ✅ | `get_reinforced_patterns()` at optimizer.py:240 |
| 8 | `suppressed_patterns` → `OptimizationEngine` | ✅ | `get_suppressed_patterns()` at optimizer.py:286 |
| 9 | `OptimizationEngine` → `ScriptAgent` prompts | ✅ | `ruleset` passed to `build_optimized_*_prompt()` functions |
| 10 | Topic-level reinforcement between cycles | ✅ | Real classification data drives topic reinforcement via `save_reinforced_pattern("topic", ...)` |

### ❌ Broken Links

| # | Chain | Status | Root Cause | Impact |
|---|-------|--------|------------|--------|
| 11 | Real YouTube CTR → `hooks.actual_ctr` | **BROKEN** | No code ever writes to this column | `get_best_hooks()` always uses LLM-estimated `ctr_score`; hooks never ranked by real performance |
| 12 | Real YouTube retention → `hooks.actual_retention` | **BROKEN** | No code ever writes to this column | Always NULL |
| 13 | Real YouTube CTR → `titles.ctr` | **BROKEN** | No code ever writes to this column | `get_best_titles()` sorts with `COALESCE(ctr, 0)` = 0 → titles effectively unordered by performance |
| 14 | Real YouTube views → `titles.views` | **BROKEN** | No code ever writes to this column | Always 0 |
| 15 | A/B test winners → hooks/titles tables | **BROKEN** | `_feed_winner_back()` writes to `best_practices` only | Real A/B test CTR data never flows to hooks/titles tables |

## Two Separate Circuits

### Circuit A: Real-Data (WORKS)
```
YouTube Analytics API → classification → reinforce/suppress → optimzer → topic-level guidance
```
Topic and archetype-level reinforcement IS based on real YouTube CTR/retention metrics.

### Circuit B: Estimate-Only (BROKEN)
```
LLM estimates → hooks.ctr_score → get_best_hooks() → optimizer → hook/title guidance
```
Hook-level and title-level performance data is never updated with real YouTube data. The optimizer always sees initial LLM estimates (or zeros for titles).

## Bottom Line

**Topic priorities change between cycles?** ✅ YES — reinforced topic patterns affect topic selection and topic-level optimization.

**Hook examples change between cycles?** ⏸️ PARTIALLY — archetype ranking may shift, but specific hook examples always use initial `ctr_score` estimates, not real CTR.

**Title examples change between cycles?** ❌ NO — `titles.ctr` is always 0, so `get_best_titles()` returns effectively random order (insertion order).

The learning loop is **partially functional**: the architecture correctly connects all components, but two gaps prevent the system from learning from actual YouTube hook/title performance data. These gaps require dedicated UPDATE-back population logic to write real analytics data back to the hooks/titles tables.
