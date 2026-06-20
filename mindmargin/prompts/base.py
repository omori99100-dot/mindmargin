"""Core prompt templates for all AI generation."""

RESEARCH_SYSTEM = """You are a research analyst specializing in behavioral economics and business history. You produce concise, factual research briefs with psychological insights."""

RESEARCH_PROMPT = """Research the topic '{topic}' for a behavioral economics documentary.

Provide:
1. A trend score (0-100) predicting audience interest
2. 3-5 key events with dates
3. Key psychological biases at play
4. 2-3 critical decisions that defined the outcome
5. 3-5 authoritative sources

Return as JSON with keys: trend_score, events (list of dicts with date, title, description), biases (list), critical_decisions (list of dicts), sources (list of strings)"""

SCRIPT_SYSTEM = """You are an award-winning documentary scriptwriter specializing in behavioral economics and narrative storytelling. Your scripts are cinematic, emotionally engaging, and psychologically insightful. You write in a style similar to BBC documentaries, with vivid narrative drive and analytical depth."""

SECTION_PROMPTS = {
    "hook": """Write the HOOK section of a documentary script about {topic}.
Section title: {title}
Duration target: {duration_s}s

Style: Open with a shocking statistic, provocative question, or vivid scene that immediately grabs attention. Use open loops. Create curiosity gaps. End with a promise that compels the viewer to keep watching.

Write 150-300 words of compelling narration.""",

    "rise": """Write the RISE section of a documentary script about {topic}.
Section title: {title}
Duration target: {duration_s}s

Style: Chronicle the early success story. Show the optimism, the vision, the rapid growth. Make the audience feel the excitement and momentum. Foreshadow the cracks subtly.

Write 200-400 words.""",

    "first_crack": """Write the FIRST CRACK section of a documentary script about {topic}.
Section title: {title}
Duration target: {duration_s}s

Style: The first warning signs emerge. Early skeptics, ignored red flags. Build tension. Show how rational people rationalized away the evidence. Introduce the key psychological bias at play.

Write 200-400 words.""",

    "overconfidence_loop": """Write the OVERCONFIDENCE LOOP section of a documentary script about {topic}.
Section title: {title}
Duration target: {duration_s}s

Style: Deep dive into the psychology. Overconfidence bias, illusion of control, confirmation bias. Show how success bred arrogance. Use behavioral economics concepts naturally within the narrative.

Write 250-450 words.""",

    "escalation": """Write the ESCALATION section of a documentary script about {topic}.
Section title: {title}
Duration target: {duration_s}s

Style: Doubling down despite mounting evidence. Sunk cost fallacy in action. The stakes get higher. Tension becomes unbearable. Paint the picture of people trapped by their own decisions.

Write 200-400 words.""",

    "collapse": """Write the COLLAPSE section of a documentary script about {topic}.
Section title: {title}
Duration target: {duration_s}s

Style: The moment everything falls apart. Dramatic, visceral storytelling. Show the human cost. Let the weight of failure sink in. Use specific details and moments.

Write 200-400 words.""",

    "twist": """Write the TWIST section of a documentary script about {topic}.
Section title: {title}
Duration target: {duration_s}s

Style: The unexpected angle. What most people get wrong about this story. A contrarian take backed by evidence. Surprise the audience. Reframe everything they thought they knew.

Write 150-300 words.""",

    "lesson": """Write the LESSON section of a documentary script about {topic}.
Section title: {title}
Duration target: {duration_s}s

Style: Extract actionable wisdom. Connect to universal human biases. Make it personal for the viewer. Bridge from historical case study to personal relevance.

Write 150-300 words.""",

    "close": """Write the CLOSE section of a documentary script about {topic}.
Section title: {title}
Duration target: {duration_s}s

Style: Memorable, emotional ending. Echo the opening hook. Leave the audience with a lasting thought or question. Call to action for the channel (like, subscribe, comment). End on a powerful note.

Write 100-200 words.""",
}

HOOK_SYSTEM = """You are a YouTube hook optimization specialist. You create hooks that maximize click-through rate and audience retention."""

HOOK_PROMPT = """Generate 5 YouTube video hooks for a documentary about '{topic}' in the behavioral economics niche.

For each hook, provide:
- archetype: one of [curiosity_gap, fear_based, contrarian, shock_value, mystery]
- hook_text: the actual hook (1-2 sentences, punchy)
- ctr_score: estimated click-through rate (0-100)
- emotional_trigger: the primary emotion it triggers
- retention_score: estimated audience retention (0-100)
- open_loop: whether it creates an open loop (true/false)
- engagement_bait: whether it prompts comments (true/false)

Return as JSON array of objects."""

TITLE_SYSTEM = "You are a YouTube title optimization expert."

TITLE_PROMPT = """Generate 5 YouTube video titles for a documentary about '{topic}' in the behavioral economics / business autopsy niche.

Each title must be:
- Clickable (curiosity gap, numbers, power words)
- SEO-optimized (include target keywords)
- Under 70 characters
- Descriptive enough that viewers know what they'll learn

Return as JSON array of strings."""

SEO_SYSTEM = "You are a YouTube SEO specialist."

SEO_PROMPT = """Generate SEO metadata for a YouTube documentary titled '{title}' about {topic}.

Provide:
1. A search-optimized description (200-300 words with timestamps and keywords)
2. 10-15 relevant tags
3. A compelling thumbnail text concept
4. Suggested category
5. 3-5 related video suggestions

Return as JSON."""

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

QUALITY_SYSTEM = "You are a rigorous quality assessor for documentary scripts."

QUALITY_SCORING_PROMPT = """Score this script section for quality metrics.

Script: {text}
Section: {section_name}
Topic: {topic}

Rate each metric 0-100:
1. hook_strength: How compelling is the opening?
2. retention_potential: Will viewers stay engaged?
3. emotional_intensity: How emotionally impactful?
4. informational_value: How much does it teach?
5. pacing_quality: Is the rhythm natural?
6. clarity: Is the narrative easy to follow?
7. originality: Fresh perspective or cliche?
8. call_to_action_potential: Will it drive engagement?
9. psychological_depth: Behavioral economics insight?
10. overall_quality: Composite score

Return as JSON with scores, a brief justification for each, and a list of improvement suggestions."""

GENERATION_MODES = {
    "documentary": {
        "system": "You are an award-winning documentary scriptwriter for BBC-style business documentaries. Authoritative, narrative-driven, analytical.",
        "temperature": 0.7,
        "style_guide": "Balanced, researched tone. Third-person. Data-driven storytelling.",
    },
    "dark": {
        "system": "You are a noir-style narrative writer. Your scripts are dark, dramatic, and cinematic. Think true crime meets business autopsy.",
        "temperature": 0.85,
        "style_guide": "Atmospheric, tense, dramatic. Use vivid imagery. Lean into tragedy and human failure.",
    },
    "educational": {
        "system": "You are a university professor creating engaging educational content. Clear, structured, and insightful.",
        "temperature": 0.5,
        "style_guide": "Structured explanations. Define concepts. Use analogies. End with key takeaways.",
    },
    "motivational": {
        "system": "You are a high-energy motivational speaker and business storyteller. Inspiring, punchy, transformative.",
        "temperature": 0.8,
        "style_guide": "Uplifting, action-oriented. Use rhetorical questions. Direct address to viewer. Empowering language.",
    },
    "viral_shorts": {
        "system": "You write viral short-form video scripts. Every second must earn its place. Hook in 0-3 seconds, deliver value fast.",
        "temperature": 0.9,
        "style_guide": "Ultra-concise. Fast-paced. One big idea per section. Pattern interrupts. Strong hooks and endings.",
    },
}
