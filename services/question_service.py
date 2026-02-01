"""Service for generating personalized pre-recording questions based on questionnaire"""
from typing import Dict, List, Optional
from config import Config
import logging

config = Config()
logger = logging.getLogger(__name__)

# Import OpenAI service (will be initialized when needed)
try:
    from services.openai_service import openai_service
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False

# --- v1 theme and mapping constants ---
THEMES = [
    "presence_grounding",
    "clarity_simplicity",
    "pacing_rhythm",
    "energy_conviction",
    "confidence_comfort",
    "structure_organization",
    "story_narrative",
]

# Intent -> theme (20 intents from COMMANDS)
INTENT_TO_THEME: Dict[str, str] = {
    "permission_imperfect": "presence_grounding",
    "micro_start": "presence_grounding",
    "gentle_checkin": "presence_grounding",
    "breath_voice": "presence_grounding",
    "describe_obvious": "clarity_simplicity",
    "simple_opinion": "energy_conviction",
    "short_memory": "confidence_comfort",
    "reading_aloud": "structure_organization",
    "explain_simply": "clarity_simplicity",
    "list_format": "structure_organization",
    "slow_clarity": "pacing_rhythm",
    "neutral_story": "story_narrative",
    "personal_reflection": "confidence_comfort",
    "teach_back": "structure_organization",
    "contrast": "story_narrative",
    "time_constraint": "pacing_rhythm",
    "strong_opinion": "energy_conviction",
    "energy_push": "energy_conviction",
    "no_fillers_challenge": "pacing_rhythm",
    "cheeky_pressure": "energy_conviction",
}

POST_SETS_BY_THEME: Dict[str, List[int]] = {
    "presence_grounding": [1, 9, 16, 7],
    "clarity_simplicity": [3, 11, 6],
    "pacing_rhythm": [6, 16, 3],
    "energy_conviction": [2, 20, 5, 17],
    "confidence_comfort": [4, 15, 17, 14],
    "structure_organization": [11, 8, 3],
    "story_narrative": [18, 19, 5, 20],
}

# Command definitions (20 commands across 5 tiers)
COMMANDS = [
    # Tier 1: Safety & permission (0.00–0.15)
    {
        "id": 1,
        "tier": 1,
        "cursor_range": (0.00, 0.15),
        "intent": "permission_imperfect",
        "mode": ["guided", "open"],
        "constraints": {"tone": "supportive", "pressure": "none"}
    },
    {
        "id": 2,
        "tier": 1,
        "cursor_range": (0.00, 0.15),
        "intent": "micro_start",
        "mode": ["guided", "open"],
        "constraints": {"length": "one_sentence", "pressure": "none"}
    },
    {
        "id": 3,
        "tier": 1,
        "cursor_range": (0.00, 0.15),
        "intent": "gentle_checkin",
        "mode": ["guided", "open"],
        "constraints": {"scope": "feelings_only", "pressure": "none"}
    },
    {
        "id": 4,
        "tier": 1,
        "cursor_range": (0.00, 0.15),
        "intent": "breath_voice",
        "mode": ["guided", "open"],
        "constraints": {"tone": "calming", "pressure": "none"}
    },
    
    # Tier 2: Low activation (0.15–0.30)
    {
        "id": 5,
        "tier": 2,
        "cursor_range": (0.15, 0.30),
        "intent": "describe_obvious",
        "mode": ["guided", "open"],
        "constraints": {"scope": "immediate_environment"}
    },
    {
        "id": 6,
        "tier": 2,
        "cursor_range": (0.15, 0.30),
        "intent": "simple_opinion",
        "mode": ["guided", "open"],
        "constraints": {"length": "one_thing", "detail": "minimal"}
    },
    {
        "id": 7,
        "tier": 2,
        "cursor_range": (0.15, 0.30),
        "intent": "short_memory",
        "mode": ["guided", "open"],
        "constraints": {"timeframe": "today", "detail": "minimal"}
    },
    {
        "id": 8,
        "tier": 2,
        "cursor_range": (0.15, 0.30),
        "intent": "reading_aloud",
        "mode": ["guided"],
        "constraints": {"length": "short_sentence"}
    },
    
    # Tier 3: Warm-up speaking (0.30–0.45)
    {
        "id": 9,
        "tier": 3,
        "cursor_range": (0.30, 0.45),
        "intent": "explain_simply",
        "mode": ["guided", "open"],
        "constraints": {"audience": "friend", "complexity": "simple"}
    },
    {
        "id": 10,
        "tier": 3,
        "cursor_range": (0.30, 0.45),
        "intent": "list_format",
        "mode": ["guided", "open"],
        "constraints": {"format": "list", "items": 3, "detail": "none"}
    },
    {
        "id": 11,
        "tier": 3,
        "cursor_range": (0.30, 0.45),
        "intent": "slow_clarity",
        "mode": ["guided", "open"],
        "constraints": {"pace": "slower_than_natural"}
    },
    {
        "id": 12,
        "tier": 3,
        "cursor_range": (0.30, 0.45),
        "intent": "neutral_story",
        "mode": ["guided", "open"],
        "constraints": {"tone": "neutral", "emotion": "none"}
    },
    
    # Tier 4: Engagement & structure (0.45–0.60)
    {
        "id": 13,
        "tier": 4,
        "cursor_range": (0.45, 0.60),
        "intent": "personal_reflection",
        "mode": ["guided", "open"],
        "constraints": {"depth": "personal", "scope": "why_matters"}
    },
    {
        "id": 14,
        "tier": 4,
        "cursor_range": (0.45, 0.60),
        "intent": "teach_back",
        "mode": ["guided", "open"],
        "constraints": {"format": "teaching", "clarity": "high"}
    },
    {
        "id": 15,
        "tier": 4,
        "cursor_range": (0.45, 0.60),
        "intent": "contrast",
        "mode": ["guided", "open"],
        "constraints": {"format": "before_vs_after"}
    },
    {
        "id": 16,
        "tier": 4,
        "cursor_range": (0.45, 0.60),
        "intent": "time_constraint",
        "mode": ["guided", "open"],
        "constraints": {"time_limit": 60, "focus": "high"}
    },
    
    # Tier 5: Challenge & edge (0.60–0.80)
    {
        "id": 17,
        "tier": 5,
        "cursor_range": (0.60, 0.80),
        "intent": "strong_opinion",
        "mode": ["guided", "open"],
        "constraints": {"tone": "assertive", "stance": "required"}
    },
    {
        "id": 18,
        "tier": 5,
        "cursor_range": (0.60, 0.80),
        "intent": "energy_push",
        "mode": ["guided", "open"],
        "constraints": {"volume": "higher", "intention": "stronger"}
    },
    {
        "id": 19,
        "tier": 5,
        "cursor_range": (0.60, 0.80),
        "intent": "no_fillers_challenge",
        "mode": ["guided", "open"],
        "constraints": {"challenge": "pause_instead_of_um"}
    },
    {
        "id": 20,
        "tier": 5,
        "cursor_range": (0.60, 0.80),
        "intent": "cheeky_pressure",
        "mode": ["guided", "open"],
        "constraints": {"tone": "playful_pressure", "attempts": 1}
    },
]


def calculate_cursor(mood: str, readiness: int) -> float:
    """
    Calculate difficulty cursor (0.0 - 1.0)
    
    Formula:
    - mood_multiplier: positive = 1.0, negative = 0.7
    - readiness_score: (readiness - 1) / 9  (normalizes 1-10 to 0.0-1.0)
    - cursor = readiness_score * mood_multiplier
    """
    mood_multiplier = 1.0 if mood == "positive" else 0.7
    readiness_score = (readiness - 1) / 9.0
    cursor = readiness_score * mood_multiplier
    
    # Clamp to 0.0-1.0 range
    return max(0.0, min(1.0, cursor))


def determine_mode(inspiration_needed: bool) -> str:
    """Determine structure mode based on inspiration need"""
    return "guided" if inspiration_needed else "open"


def select_commands(cursor: float, mode: str, num_questions: int = 3) -> List[Dict]:
    """
    Select commands based on cursor and mode
    
    Strategy:
    - Find commands where cursor falls within cursor_range
    - Filter by mode compatibility
    - Select num_questions commands (prioritize lower tiers if multiple match)
    - If not enough in exact tier, include adjacent tiers
    """
    # Find commands matching cursor range
    matching = [
        cmd for cmd in COMMANDS
        if cmd["cursor_range"][0] <= cursor <= cmd["cursor_range"][1]
        and mode in cmd["mode"]
    ]
    
    # If not enough, expand to adjacent tiers
    if len(matching) < num_questions:
        # Find tier of matching commands
        tiers = set(cmd["tier"] for cmd in matching) if matching else {1}
        min_tier = min(tiers)
        max_tier = max(tiers)
        
        # Include adjacent tiers
        expanded = [
            cmd for cmd in COMMANDS
            if (min_tier - 1 <= cmd["tier"] <= max_tier + 1)
            and mode in cmd["mode"]
        ]
        matching = expanded
    
    # Sort by tier (lower = easier) and select
    matching.sort(key=lambda x: x["tier"])
    selected = matching[:num_questions]
    
    return selected


def generate_question_from_command(command: Dict, cursor: float, mode: str) -> str:
    """
    Generate a personalized question based on command intent using OpenAI
    """
    if config.is_production and config.OPENAI_API_KEY and HAS_OPENAI:
        try:
            prompt = f"""Generate a recording challenge aligned with Command {command['id']}: {command['intent']}.

Context:
- Mode: {mode}
- Difficulty cursor: {cursor:.2f} (0.0 = easiest, 1.0 = hardest)
- Tier: {command['tier']}
- Constraints: {command['constraints']}

Requirements:
- Be supportive, not demanding
- Match the user's readiness level (cursor {cursor:.2f})
- Respect the intent: {command['intent']}
- If mode is "guided", provide more structure
- If mode is "open", allow more freedom
- Keep it conversational and encouraging
- Don't repeat previous questions
- Generate ONE question/prompt that fits this command. Be natural and adaptive."""

            # Initialize OpenAI service if not already done
            if not hasattr(openai_service, 'client') or openai_service.client is None:
                from services.openai_service import OpenAIService
                openai_service = OpenAIService()
            
            response = openai_service.client.chat.completions.create(
                model="gpt-4o-mini",  # Using mini for cost efficiency
                messages=[
                    {"role": "system", "content": "You are a supportive speaking coach. Generate personalized recording challenges that match the user's readiness level."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.7,
                max_tokens=150
            )
            
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.error(f"Failed to generate question with AI: {str(e)}")
            # Fall back to template
    
    # Fallback: Use template system (for dev mode or if AI fails)
    return generate_question_from_template(command, cursor, mode)


def generate_question_from_template(command: Dict, cursor: float, mode: str) -> str:
    """
    Generate question using templates (fallback for dev mode)
    """
    templates = {
        "permission_imperfect": [
            "You don't need to perform. Just share one thought that's on your mind.",
            "There's no pressure here. Say whatever comes to you naturally.",
            "Take your time. What's one thing you'd like to express right now?",
        ],
        "micro_start": [
            "Say one sentence about how you're feeling.",
            "Share just one thought—nothing more.",
            "One sentence. That's all. What comes to mind?",
        ],
        "gentle_checkin": [
            "How are you feeling right now?",
            "What's on your mind at this moment?",
            "Take a breath. How do you feel?",
        ],
        "breath_voice": [
            "Take a deep breath and say one thing that matters to you.",
            "Breathe in, and when you're ready, share something simple.",
            "Relax your shoulders. Now, what would you like to say?",
        ],
        "describe_obvious": [
            "Look around you. Describe one thing you see.",
            "What's one thing in your immediate environment?",
            "Notice something nearby. Tell me about it.",
        ],
        "simple_opinion": [
            "What's one thing you like?",
            "Share a simple preference you have.",
            "What's your opinion on something simple?",
        ],
        "short_memory": [
            "What's one thing that happened today?",
            "Share a brief memory from today.",
            "Tell me about something that happened recently.",
        ],
        "reading_aloud": [
            "Read this sentence aloud: 'The quick brown fox jumps over the lazy dog.'",
            "Read this aloud: 'Practice makes progress, not perfection.'",
            "Read this aloud: 'Slow is smooth, and smooth is fast.'",
        ],
        "explain_simply": [
            "Explain something simple to a friend. What would you say?",
            "How would you explain a basic concept to someone?",
            "Describe something in simple terms.",
        ],
        "list_format": [
            "List three things you're grateful for.",
            "Name three things that make you happy.",
            "What are three things you appreciate?",
        ],
        "slow_clarity": [
            "Speak slowly and clearly about something important to you.",
            "Take your time. Explain something at a comfortable pace.",
            "Slow down. What would you like to share?",
        ],
        "neutral_story": [
            "Tell a brief, neutral story about something that happened.",
            "Share a simple story without strong emotions.",
            "What's a straightforward story you can tell?",
        ],
        "personal_reflection": [
            "Why does this matter to you?",
            "What makes this important in your life?",
            "Reflect on why this is meaningful to you.",
        ],
        "teach_back": [
            "Explain this as if you're teaching someone else.",
            "How would you teach this concept to another person?",
            "Break this down as if explaining to a student.",
        ],
        "contrast": [
            "Compare how this was before versus how it is now.",
            "What changed? How was it different before?",
            "Contrast the past and present of this topic.",
        ],
        "time_constraint": [
            "You have one minute. Share what's most important.",
            "In 60 seconds, what would you want to say?",
            "Speak for one minute about something that matters.",
        ],
        "strong_opinion": [
            "What's a strong opinion you hold? Share it confidently.",
            "Express a firm stance on something you believe in.",
            "What's something you feel strongly about?",
        ],
        "energy_push": [
            "Speak with more energy and intention about something you care about.",
            "Bring more passion to your voice. What excites you?",
            "Speak with conviction. What drives you?",
        ],
        "no_fillers_challenge": [
            "Speak without filler words. Pause instead of saying 'um' or 'uh'.",
            "Challenge yourself: speak clearly with intentional pauses.",
            "No 'ums' or 'uhs'. Use pauses instead. What would you say?",
        ],
        "cheeky_pressure": [
            "One take. Make it count. What's your message?",
            "You've got this. One shot. What do you want to say?",
            "No do-overs. What's worth saying right now?",
        ],
    }
    
    intent = command["intent"]
    template_list = templates.get(intent, ["Tell me about something."])
    
    # Simple rotation: use first template (could be improved with user history)
    return template_list[0]


# --- v1: recording prompt templates (same as above, used for command options) ---
COMMAND_PROMPT_TEMPLATES = {
    "permission_imperfect": ["You don't need to perform. Just share one thought that's on your mind.", "There's no pressure here. Say whatever comes to you naturally.", "Take your time. What's one thing you'd like to express right now?"],
    "micro_start": ["Say one sentence about how you're feeling.", "Share just one thought—nothing more.", "One sentence. That's all. What comes to mind?"],
    "gentle_checkin": ["How are you feeling right now?", "What's on your mind at this moment?", "Take a breath. How do you feel?"],
    "breath_voice": ["Take a deep breath and say one thing that matters to you.", "Breathe in, and when you're ready, share something simple.", "Relax your shoulders. Now, what would you like to say?"],
    "describe_obvious": ["Look around you. Describe one thing you see.", "What's one thing in your immediate environment?", "Notice something nearby. Tell me about it."],
    "simple_opinion": ["What's one thing you like?", "Share a simple preference you have.", "What's your opinion on something simple?"],
    "short_memory": ["What's one thing that happened today?", "Share a brief memory from today.", "Tell me about something that happened recently."],
    "reading_aloud": ["Read this sentence aloud: 'The quick brown fox jumps over the lazy dog.'", "Read this aloud: 'Practice makes progress, not perfection.'", "Read this aloud: 'Slow is smooth, and smooth is fast.'"],
    "explain_simply": ["Explain something simple to a friend. What would you say?", "How would you explain a basic concept to someone?", "Describe something in simple terms."],
    "list_format": ["List three things you're grateful for.", "Name three things that make you happy.", "What are three things you appreciate?"],
    "slow_clarity": ["Speak slowly and clearly about something important to you.", "Take your time. Explain something at a comfortable pace.", "Slow down. What would you like to share?"],
    "neutral_story": ["Tell a brief, neutral story about something that happened.", "Share a simple story without strong emotions.", "What's a straightforward story you can tell?"],
    "personal_reflection": ["Why does this matter to you?", "What makes this important in your life?", "Reflect on why this is meaningful to you."],
    "teach_back": ["Explain this as if you're teaching someone else.", "How would you teach this concept to another person?", "Break this down as if explaining to a student."],
    "contrast": ["Compare how this was before versus how it is now.", "What changed? How was it different before?", "Contrast the past and present of this topic."],
    "time_constraint": ["You have one minute. Share what's most important.", "In 60 seconds, what would you want to say?", "Speak for one minute about something that matters."],
    "strong_opinion": ["What's a strong opinion you hold? Share it confidently.", "Express a firm stance on something you believe in.", "What's something you feel strongly about?"],
    "energy_push": ["Speak with more energy and intention about something you care about.", "Bring more passion to your voice. What excites you?", "Speak with conviction. What drives you?"],
    "no_fillers_challenge": ["Speak without filler words. Pause instead of saying 'um' or 'uh'.", "Challenge yourself: speak clearly with intentional pauses.", "No 'ums' or 'uhs'. Use pauses instead. What would you say?"],
    "cheeky_pressure": ["One take. Make it count. What's your message?", "You've got this. One shot. What do you want to say?", "No do-overs. What's worth saying right now?"],
}


def get_command_prompt_for_intent(intent: str, variant_index: int = 0) -> str:
    """Return recording prompt text for an intent (for session_command_options snapshot)."""
    templates = COMMAND_PROMPT_TEMPLATES.get(intent, ["Tell me about something."])
    idx = min(variant_index, len(templates) - 1) if templates else 0
    return templates[idx] if templates else "Tell me about something."


def filter_commands_for_theme_cursor_mode(
    theme_code: str,
    cursor: float,
    effective_mode: str,
    no_fillers_eligible: bool = False,
) -> List[Dict]:
    """
    Return COMMANDS that match theme, cursor range, and effective_mode.
    - reading_aloud: only when effective_mode != 'open'.
    - no_fillers_challenge: only when no_fillers_eligible is True (caller computes from user stats).
    """
    out = []
    for cmd in COMMANDS:
        if INTENT_TO_THEME.get(cmd["intent"]) != theme_code:
            continue
        if not (cmd["cursor_range"][0] <= cursor <= cmd["cursor_range"][1]):
            continue
        if effective_mode not in cmd["mode"]:
            continue
        if cmd["intent"] == "reading_aloud" and effective_mode == "open":
            continue
        if cmd["intent"] == "no_fillers_challenge" and not no_fillers_eligible:
            continue
        out.append(cmd)
    return out


def get_commands_for_theme_ignore_cursor(
    theme_code: str,
    effective_mode: str,
    no_fillers_eligible: bool = False,
) -> List[Dict]:
    """
    Return COMMANDS that match theme and mode (cursor range ignored).
    Used as fallback so we always have options when cursor band has few/no commands (e.g. confidence_comfort at 0.7).
    """
    out = []
    for cmd in COMMANDS:
        if INTENT_TO_THEME.get(cmd["intent"]) != theme_code:
            continue
        if effective_mode not in cmd["mode"]:
            continue
        if cmd["intent"] == "reading_aloud" and effective_mode == "open":
            continue
        if cmd["intent"] == "no_fillers_challenge" and not no_fillers_eligible:
            continue
        out.append(cmd)
    return out


def get_commands_for_mode_any_theme(
    effective_mode: str,
    no_fillers_eligible: bool = False,
) -> List[Dict]:
    """
    Return all COMMANDS that match mode (any theme). Last-resort fallback so we never return 0 options.
    """
    out = []
    for cmd in COMMANDS:
        if effective_mode not in cmd["mode"]:
            continue
        if cmd["intent"] == "reading_aloud" and effective_mode == "open":
            continue
        if cmd["intent"] == "no_fillers_challenge" and not no_fillers_eligible:
            continue
        out.append(cmd)
    return out
