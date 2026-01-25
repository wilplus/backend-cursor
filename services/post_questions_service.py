"""Service for selecting and generating post-recording questions from question sets"""
from typing import Dict, List, Optional
import random
import logging

logger = logging.getLogger(__name__)

# 20 Question Sets (each has 3 questions: scale, binary, free_text)
POST_QUESTIONS_POOL = [
    {
        "id": 1,
        "name": "Presence & Awareness",
        "q1": {"text": "How present were you while speaking? (1-5)", "type": "scale"},
        "q2": {"text": "Did you notice yourself using filler words?", "type": "binary"},
        "q3": {"text": "What moment felt the most real?", "type": "free_text"},
    },
    {
        "id": 2,
        "name": "Energy & Engagement",
        "q1": {"text": "How energized did you feel? (1-5)", "type": "scale"},
        "q2": {"text": "Did you feel engaged with your topic?", "type": "binary"},
        "q3": {"text": "What gave you the most energy?", "type": "free_text"},
    },
    {
        "id": 3,
        "name": "Clarity & Flow",
        "q1": {"text": "How clear was your message? (1-5)", "type": "scale"},
        "q2": {"text": "Did your words flow naturally?", "type": "binary"},
        "q3": {"text": "What helped you speak more clearly?", "type": "free_text"},
    },
    {
        "id": 4,
        "name": "Confidence & Comfort",
        "q1": {"text": "How confident did you feel? (1-5)", "type": "scale"},
        "q2": {"text": "Did you feel comfortable speaking?", "type": "binary"},
        "q3": {"text": "What made you feel more confident?", "type": "free_text"},
    },
    {
        "id": 5,
        "name": "Connection & Impact",
        "q1": {"text": "How connected did you feel to your message? (1-5)", "type": "scale"},
        "q2": {"text": "Do you think your message landed?", "type": "binary"},
        "q3": {"text": "What would you want your listener to remember?", "type": "free_text"},
    },
    {
        "id": 6,
        "name": "Pacing & Rhythm",
        "q1": {"text": "How satisfied are you with your pacing? (1-5)", "type": "scale"},
        "q2": {"text": "Did you feel rushed at any point?", "type": "binary"},
        "q3": {"text": "What helped you find your rhythm?", "type": "free_text"},
    },
    {
        "id": 7,
        "name": "Authenticity & Voice",
        "q1": {"text": "How authentic did you sound? (1-5)", "type": "scale"},
        "q2": {"text": "Did you feel like yourself while speaking?", "type": "binary"},
        "q3": {"text": "When did you feel most like yourself?", "type": "free_text"},
    },
    {
        "id": 8,
        "name": "Preparation & Readiness",
        "q1": {"text": "How prepared did you feel? (1-5)", "type": "scale"},
        "q2": {"text": "Did preparation help you speak better?", "type": "binary"},
        "q3": {"text": "What preparation helped you most?", "type": "free_text"},
    },
    {
        "id": 9,
        "name": "Focus & Attention",
        "q1": {"text": "How focused were you? (1-5)", "type": "scale"},
        "q2": {"text": "Did you get distracted at any point?", "type": "binary"},
        "q3": {"text": "What helped you stay focused?", "type": "free_text"},
    },
    {
        "id": 10,
        "name": "Emotion & Expression",
        "q1": {"text": "How expressive were you? (1-5)", "type": "scale"},
        "q2": {"text": "Did you express your emotions clearly?", "type": "binary"},
        "q3": {"text": "What emotion came through strongest?", "type": "free_text"},
    },
    {
        "id": 11,
        "name": "Structure & Organization",
        "q1": {"text": "How organized were your thoughts? (1-5)", "type": "scale"},
        "q2": {"text": "Did your message have a clear structure?", "type": "binary"},
        "q3": {"text": "What structure worked best for you?", "type": "free_text"},
    },
    {
        "id": 12,
        "name": "Listening & Response",
        "q1": {"text": "How aware were you of your listener? (1-5)", "type": "scale"},
        "q2": {"text": "Did you adapt based on how it was received?", "type": "binary"},
        "q3": {"text": "How did you know your message was received?", "type": "free_text"},
    },
    {
        "id": 13,
        "name": "Growth & Learning",
        "q1": {"text": "How much did you learn from this? (1-5)", "type": "scale"},
        "q2": {"text": "Did you notice improvement from last time?", "type": "binary"},
        "q3": {"text": "What will you do differently next time?", "type": "free_text"},
    },
    {
        "id": 14,
        "name": "Challenge & Difficulty",
        "q1": {"text": "How challenging was this? (1-5)", "type": "scale"},
        "q2": {"text": "Did you push yourself outside your comfort zone?", "type": "binary"},
        "q3": {"text": "What was the hardest part?", "type": "free_text"},
    },
    {
        "id": 15,
        "name": "Satisfaction & Achievement",
        "q1": {"text": "How satisfied are you with this recording? (1-5)", "type": "scale"},
        "q2": {"text": "Did you achieve what you set out to do?", "type": "binary"},
        "q3": {"text": "What are you most proud of?", "type": "free_text"},
    },
    {
        "id": 16,
        "name": "Body & Voice",
        "q1": {"text": "How comfortable was your body? (1-5)", "type": "scale"},
        "q2": {"text": "Did your voice feel strong and clear?", "type": "binary"},
        "q3": {"text": "What physical sensations did you notice?", "type": "free_text"},
    },
    {
        "id": 17,
        "name": "Mindset & Attitude",
        "q1": {"text": "How positive was your mindset? (1-5)", "type": "scale"},
        "q2": {"text": "Did you approach this with the right attitude?", "type": "binary"},
        "q3": {"text": "What mindset helped you most?", "type": "free_text"},
    },
    {
        "id": 18,
        "name": "Story & Narrative",
        "q1": {"text": "How well did you tell your story? (1-5)", "type": "scale"},
        "q2": {"text": "Did your story have a clear arc?", "type": "binary"},
        "q3": {"text": "What made your story compelling?", "type": "free_text"},
    },
    {
        "id": 19,
        "name": "Improvisation & Spontaneity",
        "q1": {"text": "How spontaneous were you? (1-5)", "type": "scale"},
        "q2": {"text": "Did you go off-script in a good way?", "type": "binary"},
        "q3": {"text": "What surprised you while speaking?", "type": "free_text"},
    },
    {
        "id": 20,
        "name": "Impact & Resonance",
        "q1": {"text": "How impactful was your message? (1-5)", "type": "scale"},
        "q2": {"text": "Do you think it resonated with your listener?", "type": "binary"},
        "q3": {"text": "What do you hope they took away?", "type": "free_text"},
    },
]


def select_post_question_set(user_id: str, recent_set_ids: List[int] = None) -> Dict:
    """
    Select a question set from the pool, avoiding recent sets
    
    Args:
        user_id: User ID (for future user-specific selection)
        recent_set_ids: List of recently used set IDs to avoid
    
    Returns:
        Selected question set dictionary
    """
    if recent_set_ids is None:
        recent_set_ids = []
    
    # Filter out recently used sets
    available = [s for s in POST_QUESTIONS_POOL if s["id"] not in recent_set_ids]
    
    # If all sets were used recently, reset and use all
    if not available:
        available = POST_QUESTIONS_POOL
    
    # Select random from available
    selected = random.choice(available)
    
    logger.info(f"Selected question set {selected['id']}: {selected['name']}")
    return selected


def generate_post_questions_from_set(question_set: Dict) -> List[Dict]:
    """
    Convert question set to the format expected by frontend
    
    Returns:
        List of 3 questions with proper structure
    """
    questions = [
        {
            "id": f"set-{question_set['id']}-q1",  # Temporary ID
            "question_text": question_set["q1"]["text"],
            "question_type": "scale",
            "question_set_id": question_set["id"],
            "order_index": 0
        },
        {
            "id": f"set-{question_set['id']}-q2",
            "question_text": question_set["q2"]["text"],
            "question_type": "binary",
            "question_set_id": question_set["id"],
            "order_index": 1
        },
        {
            "id": f"set-{question_set['id']}-q3",
            "question_text": question_set["q3"]["text"],
            "question_type": "free_text",
            "question_set_id": question_set["id"],
            "order_index": 2
        },
    ]
    
    return questions
