"""Prompts for coach feedback-note drafting (per slide moment).

Moved verbatim from services/coach_comment_drafter.py (registry
extraction 2026-08-03). This is the FEEDBACK-GENERATION surface of the
eval plan: the draft a human coach edits before the user reads it.
BLIND-COACH context: this drafts from acoustics turned into plain
observations — the model never sees raw numbers (that conversion stays
in the service).

``system()`` is a builder so ``with_voice_rules`` applies at call time,
exactly as the service did inline.
"""
from __future__ import annotations

from typing import Optional

STYLE_EXAMPLE = (
    "🎤 Friendly, approachable delivery — the positive tone fits the message "
    "and builds trust early.\n"
    "✅ Your speaking speed feels comfortable and easy to follow.\n"
    "✅ Your voice naturally rises and falls, which keeps it engaging.\n"
    "💡 \"get to know yourself a little better\" is a bit vague — try "
    "\"understand how you come across as a speaker.\"\n"
    "📈 Compared to your last take, your pace was a touch more controlled."
)


def system() -> str:
    from services.will_voice import with_voice_rules
    return with_voice_rules(
        "You draft the feedback note a willab speaking coach leaves on ONE "
        "moment of a user's slide presentation. The coach sees it pre-filled "
        "and edits it; the user ultimately reads it — so write warm, plain, "
        "and specific.\n\n"
        "RULES:\n"
        "1. Start with the overall impression.\n"
        "2. Name the speaker's GOAL and whether the delivery supports it.\n"
        "3. Plain language ONLY. NEVER use technical terms — no F0, SD, "
        "voiced %, dB, wpm, 'coherence score'. You are GIVEN the metrics "
        "already turned into plain observations; use those words.\n"
        "4. When the prompt gives a comparison to previous takes, mention it.\n"
        "5. Give ONE thing that's working and ONE thing to improve next.\n"
        "6. Under 120 words. 2-4 emojis max. Encouragement first, correction "
        "second.\n"
        "7. LANGUAGE: write the ENTIRE note in the SAME language the user spoke "
        "in — match the transcript's language. A Polish transcript gets a "
        "Polish note, a Spanish one a Spanish note, and so on. Never default to "
        "English unless the user spoke English.\n\n"
        "FORMAT — short emoji-led lines (the example is English; mirror its "
        "shape in the user's language), e.g.:\n" + STYLE_EXAMPLE +
        "\n\nOUTPUT: strict JSON with key \"coach_note\" only."
    )


def user(transcript, slide, observations, take_comparison, goal) -> str:
    title = (slide.get("title") or "").strip() if isinstance(slide, dict) else ""
    body = (slide.get("body") or "").strip() if isinstance(slide, dict) else ""
    if len(body) > 400:
        body = body[:400].rstrip() + "…"
    obs = "; ".join(f"{k}: {v}" for k, v in (observations or {}).items()) or "(no metric read)"
    lines = []
    if goal:
        lines.append(f"speaker's goal / what this talk is about: \"{goal}\"")
    lines.append(f"slide title: \"{title}\"")
    lines.append(f"slide body: \"{body or '(none)'}\"")
    lines.append(f"what they said in this moment: \"{transcript}\"")
    lines.append(f"delivery (plain observations): {obs}")
    if take_comparison:
        lines.append(f"vs their previous takes: {take_comparison}")
    return "\n".join(lines)


REGISTER = {
    "coach_comment_draft.system": system,
    "coach_comment_draft.style_example": STYLE_EXAMPLE,
    "coach_comment_draft.user": user,
}
