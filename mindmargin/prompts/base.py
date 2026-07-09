"""Core prompt templates for all AI generation.

Phase 21: Documentary Production Engine — prompts upgraded for professional
documentary-quality content generation.
"""

# ═══════════════════════════════════════════════════════════════════
#  RESEARCH
# ═══════════════════════════════════════════════════════════════════

RESEARCH_SYSTEM = """You are an elite research analyst specializing in business history, corporate failures, and behavioral economics. You produce comprehensive, well-sourced research briefs with psychological depth. Your research covers timelines, financials, key figures, market dynamics, and human drama."""

RESEARCH_PROMPT = """Conduct comprehensive research on '{topic}' for a professional documentary.

You must collect ALL of the following categories. Be as thorough as possible:

1. TIMELINE: Key events with exact dates (founding, IPO, peak, crisis,结局)
2. FOUNDERS & KEY FIGURES: Names, roles, backgrounds, key decisions they made
3. FINANCIAL MILESTONES: Revenue figures, market cap, stock price peaks, losses
4. MARKET SHARE: Industry position, competitors, market dynamics over time
5. ACQUISITIONS & DEALS: Major M&A activity, partnerships, investments
6. KEY DECISIONS: The 3-5 critical decisions that shaped the outcome
7. INTERNAL CONFLICTS: Leadership disputes, board battles, cultural problems
8. PUBLIC REACTIONS: Media coverage, customer sentiment, employee morale
9. MAJOR QUOTES: Direct quotes from executives, analysts, employees (attribution required)
10. LEGAL & REGULATORY: Court cases, SEC filings, investigations, settlements
11. IMPORTANT INTER interviews: Notable public statements, press conferences, earnings calls
12. EARNINGS DATA: Quarterly/annual results showing trajectory
13. HISTORICAL CONTEXT: Industry trends, economic conditions, technological shifts
14. PSYCHOLOGICAL BIASES: Overconfidence, sunk cost, confirmation bias, groupthink at play
15. LESSONS & ANALYSIS: What behavioral economists say about this case
16. CONTRASTING VIEWS: Different perspectives on what went wrong
17. CURRENT STATUS: What exists today as a result (bankruptcy, acquisition, transformation)

Return as JSON with ALL keys: timeline, founders, financials, market_share, acquisitions,
key_decisions, internal_conflicts, public_reactions, quotes, legal, interviews,
earnings, historical_context, psychological_biases, lessons, contrasting_views,
current_status, trend_score, sources"""

# ═══════════════════════════════════════════════════════════════════
#  DOCUMENTARY SCRIPT SYSTEM
# ═══════════════════════════════════════════════════════════════════

SCRIPT_SYSTEM = """You are a world-class documentary scriptwriter. You write scripts for YouTube documentaries that rival BBC, PBS, and Netflix productions. Your writing is cinematic, emotionally gripping, and analytically rigorous.

CRITICAL RULES:
- Write ONLY narration text — never include stage directions, B-roll notes, or scene descriptions
- Use natural spoken language — this will be read by a voice actor
- Every sentence must earn its place — no filler, no padding
- Vary sentence length dramatically — mix short punchy sentences with longer flowing ones
- Use specific numbers, dates, names, and details — never vague generalities
- Create vivid mental images through concrete details
- Build emotional tension through the narrative arc
- Never repeat information already covered
- Write as if telling a story to a smart friend over coffee
- Target 200-350 words per section for natural narration pacing"""

DOCUMENTARY_SECTION_PROMPTS = {
    "hook": """Write the HOOK for a documentary about {topic}.

This is the first 15-30 seconds. It must be IMPOSSIBLE to stop watching.

Techniques that work:
- Open mid-scene ("The boardroom went silent...")
- Shocking statistic or number
- Paradox or contradiction
- Vivid scene-setting
- Provocative question

You must create an OPEN LOOP — the viewer needs to know what happens next.

Write 100-200 words. Pure narration — no stage directions.""",

    "context": """Write the CONTEXT section for a documentary about {topic}.

This establishes the world BEFORE the story begins. Help the viewer understand:
- What industry/era are we in?
- What was the status quo?
- What were people's expectations?
- What was the competitive landscape?

Use specific numbers and details. Paint a picture of the world that existed.

Write 200-350 words. Pure narration.""",

    "historical_background": """Write the HISTORICAL BACKGROUND for a documentary about {topic}.

This is the origin story. Cover:
- Who founded/started it and why
- The early days (struggles, breakthroughs)
- The founding team and their vision
- Key early decisions
- What made it different from the start

Use dates, names, specific events. Make it feel like a real story, not a Wikipedia article.

Write 250-400 words. Pure narration.""",

    "growth_story": """Write the GROWTH STORY for a documentary about {topic}.

This is the ascent. Show:
- The rapid rise — specific numbers, milestones, achievements
- What was driving the success
- How the market/culture responded
- The human element — what did it feel like to be there?
- Key moments of triumph

Make the viewer feel the momentum, the excitement, the inevitability.

Write 300-450 words. Pure narration.""",

    "critical_decisions": """Write the CRITICAL DECISIONS section for a documentary about {topic}.

Focus on the 3-5 decisions that defined everything. For each:
- What was decided
- Who decided it
- What the alternatives were
- Why they chose this path
- What the consequences were

Show the HUMAN element — ego, ambition, fear, groupthink. Make the viewer understand why smart people made bad choices.

Write 300-450 words. Pure narration.""",

    "main_mistakes": """Write the MAIN MISTAKES section for a documentary about {topic}.

This is where you dissect what went wrong. Cover:
- The critical errors in judgment
- Warning signs that were ignored
- The psychology behind the mistakes (overconfidence, sunk cost, confirmation bias)
- How internal culture contributed
- The point of no return

Be specific. Use names, dates, numbers. Show, don't just tell.

Write 300-450 words. Pure narration.""",

    "collapse": """Write the COLLAPSE section for a documentary about {topic}.

This is the dramatic climax. Show:
- The moment everything fell apart
- The human cost — jobs lost, lives changed
- The speed of the collapse
- Key moments and turning points
- How the people involved reacted

Make it visceral. Let the weight of failure sink in.

Write 300-450 words. Pure narration.""",

    "consequences": """Write the CONSEQUENCES section for a documentary about {topic}.

After the collapse, what happened? Cover:
- Impact on employees, customers, investors
- Industry ripple effects
- Legal/regulatory aftermath
- What replaced it
- How it changed the industry/culture

Show the broader impact beyond just one company.

Write 250-400 words. Pure narration.""",

    "lessons_learned": """Write the LESSONS LEARNED section for a documentary about {topic}.

Extract universal wisdom. Connect to:
- Behavioral economics principles (name specific biases)
- Business strategy lessons
- Human psychology insights
- What this teaches us about ambition, greed, innovation
- How to recognize similar patterns in the future

Make it personal for the viewer. Why should they care?

Write 250-400 words. Pure narration.""",

    "closing": """Write the CLOSING for a documentary about {topic}.

This must be unforgettable. Techniques:
- Echo the opening hook
- Leave a lasting question
- Connect to the present day
- Hint at the next documentary
- End on an emotional note

The last sentence should make the viewer sit in silence for a moment.

Write 100-200 words. Pure narration.""",
}

# ═══════════════════════════════════════════════════════════════════
#  SCENE PLANNING
# ═══════════════════════════════════════════════════════════════════

SCENE_PLANNING_SYSTEM = """You are a documentary visual director. You plan scenes that match narration with compelling visuals. You think in terms of shots, movement, pacing, and visual storytelling."""

SCENE_PLANNING_PROMPT = """Plan visual scenes for this documentary section about {topic}.

For each paragraph (3-5 sentences), create a scene with:
- scene_description: What the viewer sees (1-2 sentences)
- broll_suggestion: Specific B-roll footage to search for
- footage_keywords: 3-5 search terms for stock footage
- camera_movement: Static, pan_left, pan_right, zoom_in, zoom_out, tracking, drone
- on_screen_text: Key text/numbers to display (if any)
- visual_elements: Charts, maps, logos, documents, newspaper clippings to show
- duration_s: Estimated seconds this scene covers
- emotion: The emotional tone of this visual

Write 5-8 scenes per section. Return as JSON array."""

# ═══════════════════════════════════════════════════════════════════
#  HOOK OPTIMIZATION
# ═══════════════════════════════════════════════════════════════════

HOOK_SYSTEM = """You are a YouTube hook optimization specialist. You create hooks that make it psychologically impossible to click away. You understand curiosity gaps, open loops, and emotional triggers at a deep level."""

HOOK_PROMPT = """Generate 5 hooks for a documentary about '{topic}'.

Each hook must:
- Be 1-2 sentences (15-30 seconds when spoken)
- Create an immediate curiosity gap
- Make the viewer NEED to know what happens next
- Feel like the opening of a Netflix documentary

For each hook provide:
- hook_text: The actual narration
- archetype: curiosity_gap | shock_value | paradox | mid_scene | confession
- ctr_score: 0-100 (estimated click-through rate)
- retention_score: 0-100 (estimated audience retention past 30s)
- emotional_trigger: primary emotion triggered
- curiosity_gap_strength: 0-100 (how badly viewer needs to know what happens)
- open_loop_count: number of unanswered questions created
- why_it_works: 1-sentence explanation

Return as JSON array. Rank by ctr_score descending."""

# ═══════════════════════════════════════════════════════════════════
#  TITLE GENERATION
# ═══════════════════════════════════════════════════════════════════

TITLE_SYSTEM = """You are a YouTube title optimization expert. You understand that titles must create psychological tension that demands resolution."""

TITLE_PROMPT = """Generate 15 YouTube titles for a documentary about '{topic}'.

Requirements:
- Under 60 characters (YouTube truncates after 60)
- Must create curiosity gap or emotional tension
- Include at least 3 power words (destroyed, secret, billion, forbidden, exposed, etc.)
- No clickbait — must be factual
- Mix formats: question, number, statement, paradox

For each title provide:
- title: The title text
- curiosity_score: 0-100
- ctr_prediction: 0-100 (estimated click-through rate)
- emotional_score: 0-100 (emotional resonance)
- format: question | number | statement | paradox | confession
- why_it_works: 1-sentence explanation

Return as JSON array. Rank by ctr_prediction descending."""

# ═══════════════════════════════════════════════════════════════════
#  THUMBNAIL INTELLIGENCE
# ═══════════════════════════════════════════════════════════════════

THUMBNAIL_SYSTEM = """You are a YouTube thumbnail design strategist. You understand that thumbnails must communicate emotion and curiosity in under 1 second. You think in terms of contrast, facial expressions, color psychology, and visual hierarchy."""

THUMBNAIL_CONCEPT_PROMPT = """Generate 10 thumbnail concepts for a documentary about '{topic}'.

Each concept must include:
- main_subject: What dominates the frame (person, object, scene)
- facial_expression: If person — what emotion (shock, anger, smug, disbelief, fear)
- color_palette: Primary and accent colors (hex codes)
- composition: Rule of thirds | center | split | diagonal
- contrast_level: low | medium | high | extreme
- text_overlay: Max 3 words (or "none")
- text_position: top | bottom | left | right | center
- emotion_score: 0-100 (how strongly it communicates the story's emotion)
- curiosity_score: 0-100 (how much it makes you want to click)
- visual_hierarchy: What the eye sees first → second → third

Return as JSON array. Rank by (emotion_score + curiosity_score) / 2 descending."""

# ═══════════════════════════════════════════════════════════════════
#  QUALITY GATES
# ═══════════════════════════════════════════════════════════════════

QUALITY_SYSTEM = """You are a rigorous documentary quality assessor. You evaluate scripts against professional documentary standards. You are honest — you do not give participation trophies."""

QUALITY_SCORING_PROMPT = """Evaluate this documentary script section against professional standards.

Script: {text}
Section: {section_name}
Topic: {topic}

Rate each metric 0-100:
1. narrative_arc: Does it tell a compelling story?
2. specificity: Are there concrete details (names, dates, numbers)?
3. emotional_depth: Does it create genuine emotional engagement?
4. pacing: Is the rhythm natural for spoken narration?
5. originality: Does it offer fresh perspective?
6. transitions: Do sentences flow naturally?
7. information_density: Right amount of detail (not too much, not too little)?
8. behavioral_insight: Does it reveal something about human psychology?
9. documentary_quality: Would this pass in a BBC/Netflix documentary?
10. overall_score: Composite assessment

Also check for REJECTION criteria:
- under_1500_words: Total script under 1500 words
- repetition: Same information repeated
- no_story_arc: Reads like a list, not a story
- weak_transitions: Sentences don't connect
- wikipedia_style: Reads like an encyclopedia entry
- ai_sounding: Generic, formulaic language
- unsupported_claims: Statistics or facts without attribution

Return as JSON with scores, rejections (list), and improvement_suggestions."""

# ═══════════════════════════════════════════════════════════════════
#  PRODUCTION REPORT
# ═══════════════════════════════════════════════════════════════════

PRODUCTION_REPORT_SYSTEM = """You are a documentary production analyst. You provide executive summaries of documentary quality with actionable insights."""

PRODUCTION_REPORT_PROMPT = """Generate a production quality report for this documentary about '{topic}'.

Title: {title}
Word count: {word_count}
Estimated duration: {estimated_duration} minutes
Sections: {section_count}

Evaluate and provide:
1. story_score: 0-100 (overall narrative quality)
2. documentary_quality_score: 0-100 (professional documentary standard)
3. hook_score: 0-100 (opening hook strength)
4. engagement_prediction: 0-100 (predicted audience retention)
5. visual_diversity_score: 0-100 (variety of visual elements needed)
6. estimated_retention_curve: [beginning%, middle%, end%] (predicted audience retention at each stage)
7. estimated_ctr: percentage (predicted click-through rate)
8. strengths: list of 3-5 things done well
9. weaknesses: list of 3-5 things to improve
10. comparable_references: 2-3 similar successful documentaries to reference
11. recommended_improvements: prioritized list of specific improvements
12. title_effectiveness: 0-100 (how well the title serves the content)

Return as JSON."""

# ═══════════════════════════════════════════════════════════════════
#  SEO METADATA
# ═══════════════════════════════════════════════════════════════════

SEO_SYSTEM = "You are a YouTube SEO specialist."

SEO_PROMPT = """Generate SEO metadata for a YouTube documentary titled '{title}' about {topic}.

Provide:
1. A search-optimized description (200-300 words with timestamps and keywords)
2. 10-15 relevant tags
3. A compelling thumbnail text concept
4. Suggested category
5. 3-5 related video suggestions

Return as JSON."""

# ═══════════════════════════════════════════════════════════════════
#  NARRATION ANALYSIS
# ═══════════════════════════════════════════════════════════════════

NARRATION_SYSTEM = """You are a voiceover director and pacing specialist. You analyze scripts and optimize them for spoken delivery."""

NARRATION_PACING_PROMPT = """Analyze this script section for narration quality and pacing:

{text}

Provide:
1. estimated_duration_s: time to speak at natural pace (words/2.8)
2. pause_points: list of natural pause points (sentence indices)
3. emotional_arc: [neutral, building, intense, peak, resolving] - which applies
4. sentence_pacing: list of dicts with sentence index and suggested speed (slow/medium/fast)
5. emphasis_words: list of words that should be emphasized

Return as JSON."""

# ═══════════════════════════════════════════════════════════════════
#  GENERATION MODES
# ═══════════════════════════════════════════════════════════════════

GENERATION_MODES = {
    "documentary": {
        "system": SCRIPT_SYSTEM,
        "temperature": 0.7,
        "style_guide": "Professional documentary. Third-person narration. Data-driven storytelling. Vivid details. Emotional depth.",
    },
    "dark": {
        "system": "You are a noir-style documentary writer. Your scripts are dark, atmospheric, and cinematic. Think true crime meets business autopsy. Every sentence drips with tension.",
        "temperature": 0.85,
        "style_guide": "Atmospheric, tense, dramatic. Use vivid imagery. Lean into tragedy and human failure. Dark humor where appropriate.",
    },
    "educational": {
        "system": "You are a university professor creating engaging educational documentaries. Clear, structured, and insightful. You make complex topics accessible without dumbing them down.",
        "temperature": 0.5,
        "style_guide": "Structured explanations. Define concepts. Use analogies. End with key takeaways. Academic rigor with storytelling flair.",
    },
    "motivational": {
        "system": "You are a high-energy motivational documentary writer. You tell stories of triumph and failure that inspire action. Every word is chosen for maximum emotional impact.",
        "temperature": 0.8,
        "style_guide": "Uplifting, action-oriented. Use rhetorical questions. Direct address to viewer. Empowering language. Transformation narratives.",
    },
    "viral_shorts": {
        "system": "You write viral short-form video scripts. Every second must earn its place. Hook in 0-3 seconds, deliver value fast, end with impact.",
        "temperature": 0.9,
        "style_guide": "Ultra-concise. Fast-paced. One big idea per section. Pattern interrupts. Strong hooks and endings.",
    },
}

# ═══════════════════════════════════════════════════════════════════
#  BACKWARD COMPATIBILITY — keep old names working
# ═══════════════════════════════════════════════════════════════════

SECTION_PROMPTS = DOCUMENTARY_SECTION_PROMPTS  # alias for imports
