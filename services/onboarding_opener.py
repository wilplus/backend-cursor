"""Ticket 2 — Dad-joke onboarding opener.

A new user lands in onboarding. Will opens with one randomly-selected
joke (setup), waits for them to reply, drops the punchline, then
pivots to real onboarding with the canonical sentence::

    "Okok, nevermind. Let's focus on public speaking — how can I help you?"

Why this lives alone
--------------------
The opener is a deliberate tonal counterpoint to Will's Voice (which
is observational, never motivational). It signpostts the bit with a
fixed frame line so the user understands "this is the app being
playful for a beat" — vs. drifting into the warmth Will's Voice
actively guards against. Keeping it in its own module makes the
counterpoint explicit and prevents the joke flow from accidentally
inheriting Will's Voice constraints (which would kill the joke) or
the joke from infecting the rest of the surfaces.

Three stages, advancing on each user reply:

  setup     — system sends frame + setup. User reads, types anything.
  punchline — system reacts (LLM-handled, with voice anchor) and
              delivers the canonical punchline + emoji. User reads,
              types anything.
  pivot     — system delivers the canonical PIVOT_LINE verbatim.
              FE flips to onboarding. End of opener flow.

The pivot line is HARDCODED. The LLM never rewrites it. The bridge
LLM call (between user reply and punchline / pivot) is allowed to
generate a brief reactive line (e.g., "Alright, here it goes:") but
the canonical content always lands verbatim after it.

Failure semantics
-----------------
Best-effort all the way through. If the LLM bridge fails, the
endpoint falls back to the canonical content alone (no ack), which
still ships the joke + pivot correctly. The user never sees an
error state for an opener — at worst the bot is a bit terser than
intended.
"""
from __future__ import annotations

import logging
from typing import Final, Optional

from services.db import db


logger = logging.getLogger(__name__)


# ── Canonical strings (locked — never LLM-rewritten) ───────────────

DAD_JOKE_FRAME: Final[str] = (
    "Attention, before we begin, let me crack a dad-joke!"
)
"""Fixed lead-in shown before every joke's setup. Same line for all
10 jokes — the repetition is the running gag. Per FE handoff Q6:
fixed across all jokes, not variable."""


PIVOT_LINE: Final[str] = (
    "Okok, nevermind. Let's focus on public speaking — "
    "how can I help you?"
)
"""Canonical onboarding pivot. The LLM never rewrites this — every
opener flow ends with this exact sentence so onboarding analytics
have a stable entry point and the brand voice doesn't drift on the
user's first real interaction with Will.

If you find yourself tempted to parametrize this for A/B testing,
think twice — the consistency IS part of the bit's payoff (every
user lands on the same beat regardless of which joke they got)."""


# Bridge model used for the optional pre-canonical ack line.
# Stage-specific LLMSpec lives in services.llm_config (added next
# to SPEC_COACHING_INTRO).
_SURFACE = "onboarding_opener"


# Hard cap on the ack line so it doesn't bury the canonical content.
# 80 chars ≈ a one-line breath; punchline + emoji follow on a
# separate bubble anyway.
MAX_ACK_LEN = 80


# ── Public API ─────────────────────────────────────────────────────


def pick_random_joke() -> Optional[dict]:
    """Return one random active dad joke or None when:
      - table is missing (migration pending)
      - all jokes are inactive
      - DB hiccup

    Caller handles None by skipping the opener entirely (silent
    fallback to plain onboarding) — the joke is decorative, missing
    it should never block onboarding.
    """
    try:
        return db.get_random_dad_joke(locale="en")
    except Exception as e:
        logger.warning("opener: random joke load failed err=%s", e)
        return None


def build_setup_message(joke: dict) -> dict:
    """Render the first bubble.

    Returns the wire shape the FE consumes. Frame + setup are
    separate fields so FE can render as two stacked bubbles with
    staggered timing per the FE handoff §2:

        beat 1 — frame  (immediate)
        beat 2 — setup  (+700ms)

    The punchline + emoji come from the /next endpoint after the
    user replies.
    """
    return {
        "stage": "setup",
        "joke_id": joke.get("id"),
        "frame": DAD_JOKE_FRAME,
        "setup": joke.get("setup") or "",
    }


def build_punchline_message(joke: dict, ack: str = "") -> dict:
    """Render the punchline bubble (stage 2 → stage 3).

    ``ack`` is the optional LLM-generated reactive line that lands
    BEFORE the punchline. Empty string when the LLM call failed or
    was skipped — the punchline alone is enough for the joke to
    land.

    Punchline + emoji join into one string (the emoji is the comic
    landing; separating them across bubbles loses the timing).
    """
    punchline_text = (joke.get("punchline") or "").strip()
    emoji = (joke.get("emoji") or "").strip()
    rendered = (
        f"{punchline_text} {emoji}".strip()
        if emoji
        else punchline_text
    )
    return {
        "stage": "punchline",
        "joke_id": joke.get("id"),
        "ack": (ack or "").strip(),
        "punchline": rendered,
    }


def build_pivot_message() -> dict:
    """Render the final bubble (stage 3 → end of opener).

    Always delivers PIVOT_LINE verbatim. No LLM involvement — the
    pivot line is canonical and consistent across every opener flow
    by design. FE flips to onboarding's first real question after
    this bubble.
    """
    return {
        "stage": "pivot",
        "joke_id": None,
        "pivot_line": PIVOT_LINE,
        "done": True,
    }


def generate_punchline_ack(user_reply: str) -> str:
    """LLM-generated brief reaction to the user's reply before the
    punchline lands.

    Best-effort. Returns "" on any failure path so the caller can
    proceed with the canonical content alone. The Will's Voice rules
    are injected via with_voice_rules so the ack stays observational
    (e.g., "Alright" / "Here goes:") rather than drifting into
    motivational filler (e.g., "Great answer! You got it!").

    Even though the ack is for a comedic context where the voice
    rules don't strictly apply, including them prevents the model
    from producing the worst failure mode — over-praise that breaks
    the joke's deadpan.
    """
    if not user_reply or not user_reply.strip():
        return ""

    try:
        from services.llm import chat_complete
        from services.llm_config import SPEC_ONBOARDING_OPENER
        from services.will_voice import with_voice_rules
    except Exception as e:
        logger.warning("opener: llm import failed err=%s", e)
        return ""

    system = with_voice_rules(
        "You are about to deliver the punchline of a dad joke to a "
        "user in onboarding. The user just gave a brief reply to "
        "the SETUP. Write ONE short reactive line (≤" + str(MAX_ACK_LEN) +
        " chars) that flows naturally into the punchline that "
        "follows. The punchline will appear on a separate bubble "
        "after your line — do NOT include the punchline itself, do "
        "NOT spoil it, do NOT explain the joke.\n"
        "\n"
        "Examples of GOOD ack lines:\n"
        "  - \"Alright:\"\n"
        "  - \"Ok, here goes:\"\n"
        "  - \"Fair. So:\"\n"
        "  - \"Brace yourself:\"\n"
        "\n"
        "Examples of BAD ack lines (never produce):\n"
        "  - \"Great guess!\" (praise inflation)\n"
        "  - \"That's not it!\" (corrective)\n"
        "  - \"You're so funny\" (parasocial)\n"
        "  - Any line that itself attempts a joke\n"
        "\n"
        "Output strict JSON: {\"ack\": \"<one short line>\"}."
    )
    user_prompt = f"User's reply to the setup: \"{user_reply.strip()}\""

    result = chat_complete(
        spec=SPEC_ONBOARDING_OPENER,
        system=system,
        user=user_prompt,
        surface=_SURFACE,
        response_format_override={"type": "json_object"},
    )
    if not result:
        return ""

    parsed = result.parsed
    if not isinstance(parsed, dict):
        return ""
    ack = (parsed.get("ack") or "").strip()
    # Defensive clamp — model can exceed the spec's char limit.
    if len(ack) > MAX_ACK_LEN:
        ack = ack[: MAX_ACK_LEN - 1].rstrip() + "…"
    return ack
