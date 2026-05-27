"""Phase Single-Slot-Chat — personalized intro line for the new
official recording session that opens after the user labels a
snippet from their previous session.

Backs ``POST /v2/coaching/intro-bubble``. One short LLM call
grounded in the just-labeled snippet's transcript + admin_comment
+ user_charisma_label, so the intro feels continuous with what
the user just experienced (not generic boilerplate).

Failure semantics
-----------------
Never raises. Any failure mode (LLM down, parse error, missing
admin_comment, etc.) returns ``None`` — the route handler treats
``None`` as "use the static fallback string" and STILL returns 200
so the FE never has to handle "intro generation failed."

Mirrors the pattern in services/directive_suggestions.py.
"""
from __future__ import annotations

import logging
from typing import Optional


logger = logging.getLogger(__name__)


# Bumped manually when the system prompt below materially changes
# so analytics can attribute regressions to a specific prompt
# version. Returned on the response in ``debug.prompt_version``.
PROMPT_VERSION = "coaching_intro_v1"

# Soft character cap. The prompt asks for ≤180 chars; we cap the
# stored / returned value at 220 (some headroom) so a single
# overshoot doesn't 500. Beyond 220 we truncate at a word boundary.
_HARD_CHAR_CAP = 220

# Model + decoding spec centralized in services/llm_config.py — see
# SPEC_COACHING_INTRO for the canonical config.


def generate_intro_line(
    *,
    user_id: str,
    snippet: dict,
) -> Optional[str]:
    """Produce a 1–2 sentence intro for the new recording session.

    Args
    ----
    user_id : str
        The authenticated owner. Logged only; the snippet is
        already owner-scoped by the route handler.
    snippet : dict
        The full snippet row (charisma_snippets) the user just
        labeled. Must include ``admin_comment`` for the LLM to
        have anything to ground on; without it we return None
        and the route falls back to the static line.

    Returns
    -------
    Optional[str]
        The intro string on success, ``None`` on any failure mode.
    """
    admin_comment = (snippet.get("admin_comment") or "").strip()
    if not admin_comment:
        # No coach insight = nothing to ground on. Caller falls
        # back to the static line.
        logger.info(
            "coaching_intro.no_admin_comment user=%s "
            "snippet=%s — falling back to static intro",
            user_id, snippet.get("id"),
        )
        return None

    from services.llm import chat_complete
    from services.llm_config import SPEC_COACHING_INTRO

    coach_label = (snippet.get("coach_label") or "").strip().lower() or None
    snippet_type = (snippet.get("snippet_type") or "").strip().lower() or None
    display_label = coach_label or snippet_type or "this moment"

    transcript = (
        (snippet.get("transcript") or "")
        or (snippet.get("transcription_text") or "")
        or (snippet.get("transcript_text") or "")
        or (snippet.get("transcript_excerpt") or "")
    ).strip()
    if not transcript:
        transcript = "(no transcript captured)"

    # ``user_charisma_label`` is the binary the user just set via
    # the labeling bubble — None if they haven't yet (shouldn't
    # happen on this path, but be defensive).
    user_label_raw = snippet.get("user_charisma_label")
    if isinstance(user_label_raw, bool):
        # "Did the user agree with the coach?" needs a comparison
        # between two semantics. The coach's label is on the type
        # axis ("charisma" vs "no_charisma"/"stress"). The user's
        # label is on the "is charisma?" axis (True/False). They
        # agree iff the coach's label aligning with charisma equals
        # what the user said.
        coach_says_charisma = (coach_label == "charisma")
        agreement = (coach_says_charisma == user_label_raw)
        user_stance = "agreed" if agreement else "disagreed"
    else:
        user_stance = "(unknown)"

    system = (
        "You are a warm communication coach. The user just finished "
        "reviewing a snippet from their previous recording — they "
        "marked whether they agreed with the coach's label, then "
        "read one reflection question. Now they're about to record "
        "a FRESH take.\n"
        "\n"
        "Write ONE 1–2 sentence intro line that:\n"
        "  • nods to what they just labeled (use the coach's "
        "insight to anchor — not the user's binary answer);\n"
        "  • invites them to start recording now;\n"
        "  • stays ≤180 characters;\n"
        "  • does NOT greet (\"Hi\", \"OK so\", \"Great\"), does "
        "NOT sign off, does NOT use bullets or markdown.\n"
        "\n"
        "Output STRICT JSON: {\"intro_text\": \"<one line>\"}."
    )

    # Cap inputs so a chatty transcript doesn't crowd the token budget.
    if len(admin_comment) > 400:
        admin_comment = admin_comment[:397] + "…"
    if len(transcript) > 400:
        transcript = transcript[:397] + "…"

    user_prompt = (
        "The snippet the user just reviewed:\n"
        f"  Coach's label:   {display_label}\n"
        f"  Coach's insight: {admin_comment}\n"
        f"  User's transcript on this moment: {transcript}\n"
        f"  User's agreement with coach: {user_stance}\n\n"
        "Generate the intro line now."
    )

    result = chat_complete(
        spec=SPEC_COACHING_INTRO,
        system=system,
        user=user_prompt,
        surface="coaching_intro",
        user_id=user_id,
    )
    if result is None:
        # chat_complete already logged the failure reason.
        return None

    parsed = result.parsed
    if not isinstance(parsed, dict):
        logger.warning(
            "coaching_intro.malformed_json user=%s raw_head=%r",
            user_id, result.text[:200],
        )
        return None
    intro_text = (parsed.get("intro_text") or "").strip()

    if not intro_text:
        logger.warning(
            "coaching_intro.empty_intro_text user=%s snippet=%s",
            user_id, snippet.get("id"),
        )
        return None

    # Soft truncate to keep the bubble tight even if the model
    # overshoots ≤180 by a lot. Word-boundary preferred.
    if len(intro_text) > _HARD_CHAR_CAP:
        cut = intro_text[: _HARD_CHAR_CAP].rsplit(" ", 1)[0]
        intro_text = cut.rstrip(",.;:") + "…"

    return intro_text
