"""Task 10 — AI-generated icebreaker for the user's NEXT session.

After session N finalizes, this module reads the session's snippets
+ admin coaching comments and asks one LLM call for a single warm,
personalized icebreaker question to open session N+1. Question lives
on session N's row (split-sinks: immutable ai_draft + editable
current); the soft-queue read in /v2/user/chat/first-question
delivers it when N+1 starts.

Why this lives alone
--------------------
One LLM call per finalize, one file per LLM purpose — keeps the
surfaces auditable and lets us tune the prompt without ripping into
a megamodule. (The old per-purpose finalize siblings — kpi-narrative,
session-predictions — were retired in the old-subsystem excision.)

The brief flagged: "plan for ≥2 prompt iterations". The split-sinks
design lets us A/B-eval: the immutable ai_draft is the LLM's
verbatim output, the editable current is what admins (and
eventually n+1) actually consume. Tracking divergence over time
is the quality signal.

Failure semantics
-----------------
Best-effort all the way through. LLM down → ai_draft stays NULL,
generation_error gets a short tag, n+1 falls back to the default
first-question path. Never raises into the finalize chain.

Public surface
--------------
  generate_next_session_icebreaker(session_id, *, overwrite=False)
    Read the session, build the prompt, call the LLM, write both
    columns + timestamp. Returns the question string or None on
    any failure path. Sets generation_error on failure.

  validate_icebreaker_body(body)
    Manual validator for the admin PUT endpoint. Returns the cleaned
    question or empty-string sentinel (skip). Raises
    IcebreakerValidationError with a user-friendly message.

  derive_queue_status(row, has_next_session)
    Map the 3 internal status values + ai_draft + generation_error
    + n+1 existence into the 5-state FE enum
    (not_yet_generated | pending_next_session | queued | delivered
    | skipped).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from services.db import db


logger = logging.getLogger(__name__)


# ── Validation bounds ──────────────────────────────────────────────
# Twitter-style ceiling — questions are conversational openers, not
# essays. Floor at 5 chars: any shorter and the prompt produced garbage
# the admin should regenerate, not save.
MIN_QUESTION_LEN = 5
MAX_QUESTION_LEN = 280

# How many recent snippets to feed the LLM. Per the FE handoff Q7
# (full transcript, last 12 turns): a session typically has 5-10
# snippets, so 12 is "all of them, with a safety cap". Keeps token
# cost bounded if a long retention session lands here.
MAX_SNIPPETS_IN_PROMPT = 12

_SURFACE = "next_session_icebreaker"


class IcebreakerValidationError(ValueError):
    """Manual-validator error with FE-renderable message.

    Raised by ``validate_icebreaker_body``. The route handler catches
    and 422s with the message verbatim — matches the INVALID_INPUT /
    EDIT_TOO_SMALL pattern in v2_routes.py.
    """


# ── Generation ─────────────────────────────────────────────────────


def generate_next_session_icebreaker(
    session_id: str,
    *,
    overwrite: bool = False,
) -> Optional[str]:
    """Generate + persist a personalized icebreaker for n+1.

    Called from:
      1. services.session_publish.finalize_session_pending_admin_review
         (Step 1.7) — pins the draft at finalize time.
      2. services.session_publish.auto_publish_trial_session — same
         for trial sessions.
      3. POST /v2/admin/sessions/<id>/next-session-icebreaker/regenerate
         — admin-triggered regen; passes ``overwrite=True``.

    ``overwrite=False`` (default): if ai_draft is already populated,
    return it unchanged. Lets finalize re-runs (admin clicks Publish
    twice) idempotent.

    ``overwrite=True``: blow away both columns and re-run the LLM.
    This is the "regenerate destroys admin edits" semantic — admin
    confirmed in the FE handoff (Q3).

    Returns the generated question string, or None when:
      - the session has too little signal (no admin comments AND no
        meaningful snippet transcripts) → generation_error =
        'transcript_too_short'
      - the LLM call fails / returns empty → generation_error =
        'llm_unavailable' | 'llm_empty'
      - the DB write fails (returns the in-memory string but logs)

    None paths never raise into the finalize chain.
    """
    try:
        session = db.v2_get_session_by_id(session_id) or {}
    except Exception as e:
        logger.warning(
            "icebreaker: session load failed sid=%s err=%s",
            session_id, e,
        )
        return None
    if not session:
        return None

    existing_draft = (
        session.get("next_session_icebreaker_ai_draft") or ""
    ).strip()
    if existing_draft and not overwrite:
        return existing_draft

    # On overwrite, clear the prior generation_error so the FE sees
    # the new attempt's outcome (success or fresh failure tag).
    if overwrite:
        try:
            db.clear_next_session_icebreaker_generation_error(session_id)
        except Exception:
            pass  # best-effort; not load-bearing

    try:
        snippets = db.get_snippets_by_session(session_id) or []
    except Exception as e:
        logger.warning(
            "icebreaker: snippet load failed sid=%s err=%s",
            session_id, e,
        )
        snippets = []

    if not _has_usable_signal(snippets):
        logger.info(
            "icebreaker: skipping sid=%s — no usable signal",
            session_id,
        )
        _mark_generation_error(session_id, "transcript_too_short")
        return None

    question = _llm_generate_question(snippets, session)
    if not question:
        _mark_generation_error(session_id, "llm_unavailable")
        return None

    # Defensive clamp — the model occasionally exceeds maxLength
    # despite the schema. Trim at the last space before the cap
    # so we don't cut mid-word, and re-append the trailing '?' if
    # we lopped it off.
    if len(question) > MAX_QUESTION_LEN:
        cut = question[:MAX_QUESTION_LEN].rsplit(" ", 1)[0]
        question = cut.rstrip(".,;:!?") + "?"

    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        db.set_next_session_icebreaker_ai_draft(
            session_id=session_id,
            ai_draft=question,
            generated_at=now_iso,
            reset_editable=True,  # overwrite=True OR fresh write — current = ai_draft
        )
    except Exception as e:
        logger.warning(
            "icebreaker: persist failed sid=%s err=%s",
            session_id, e,
        )
        # Caller still gets the question for any pass-through logging,
        # but FE will see ai_draft=NULL on next GET — acceptable, the
        # regenerate button is there.

    return question


# ── Status derivation ──────────────────────────────────────────────


def derive_queue_status(
    row: dict,
    has_next_session: bool,
) -> str:
    """Map the DB row + n+1 existence to the 5-state FE enum.

    The DB stores 3 statuses (pending | skipped | delivered) plus
    optional ai_draft + generation_error columns. The FE consumes 5
    states because "no draft yet" and "draft exists but n+1 hasn't
    started yet" and "n+1 scheduled and waiting" are visually
    distinct cards.

    Mapping table (left-most match wins):

      ai_draft IS NULL AND generation_error IS NULL  → 'not_yet_generated'
      ai_draft IS NULL AND generation_error IS NOT NULL → 'not_yet_generated'
                                                           (FE renders the
                                                            error banner)
      status == 'skipped'                            → 'skipped'
      status == 'delivered'                          → 'delivered'
      status == 'pending' AND has_next_session       → 'queued'
      status == 'pending' AND NOT has_next_session   → 'pending_next_session'

    'not_yet_generated' covers both the pre-finalize and the LLM-
    failure cases; the FE distinguishes them via the generation_error
    field on the GET payload, not via a separate status string.
    """
    ai_draft = (row.get("next_session_icebreaker_ai_draft") or "").strip()
    status = (row.get("next_session_icebreaker_status") or "pending").strip()

    if not ai_draft:
        return "not_yet_generated"
    if status == "skipped":
        return "skipped"
    if status == "delivered":
        return "delivered"
    if has_next_session:
        return "queued"
    return "pending_next_session"


# ── Validation ─────────────────────────────────────────────────────


def validate_icebreaker_body(body: Any) -> Optional[str]:
    """Validate the admin PUT body.

    Returns:
      - The cleaned question string on success.
      - None when the admin saved an empty value — caller maps to
        ``status='skipped'``, ``current=NULL``.

    Raises ``IcebreakerValidationError`` on:
      - body not a dict
      - ``question`` not a string
      - non-empty after trim but < MIN_QUESTION_LEN
      - over MAX_QUESTION_LEN chars
      - doesn't end with '?' (Q4 = hard-fail)

    Newlines collapse to single spaces (single-line UX in the card).
    """
    if not isinstance(body, dict):
        raise IcebreakerValidationError("Body must be a JSON object")

    raw = body.get("question")
    if raw is None:
        raise IcebreakerValidationError("question: required")
    if not isinstance(raw, str):
        raise IcebreakerValidationError("question: must be a string")

    # Newlines → space, then collapse runs of whitespace.
    cleaned = " ".join(raw.replace("\r", " ").replace("\n", " ").split())

    if not cleaned:
        # Empty save = skip signal. Caller maps to status='skipped'.
        return None

    if len(cleaned) < MIN_QUESTION_LEN:
        raise IcebreakerValidationError(
            f"question: must be at least {MIN_QUESTION_LEN} characters"
        )
    if len(cleaned) > MAX_QUESTION_LEN:
        raise IcebreakerValidationError(
            f"question: must be {MAX_QUESTION_LEN} characters or fewer"
        )
    if not cleaned.endswith("?"):
        raise IcebreakerValidationError(
            "question: must end with '?'"
        )

    return cleaned


# ── Internals ──────────────────────────────────────────────────────


def _has_usable_signal(snippets: list[dict]) -> bool:
    """At least one snippet has either a transcript OR an admin
    comment. Anything less and the LLM is guessing — better to skip
    and let the admin regenerate later when there's real content."""
    for s in snippets:
        if (s.get("transcript") or s.get("transcription_text") or "").strip():
            return True
        if (s.get("admin_comment") or "").strip():
            return True
    return False


def _mark_generation_error(session_id: str, error_tag: str) -> None:
    """Best-effort write of the generation_error column. Never raises."""
    try:
        db.set_next_session_icebreaker_generation_error(
            session_id=session_id,
            error_tag=error_tag,
        )
    except Exception as e:
        logger.warning(
            "icebreaker: error tag write failed sid=%s err=%s",
            session_id, e,
        )


def _llm_generate_question(
    snippets: list[dict],
    session: dict,
) -> Optional[str]:
    """One LLM call returning ONE question.

    Uses services.llm.chat_complete with a pinned JSON schema so the
    output is shape-safe. Returns the question string or None on any
    failure mode.
    """
    try:
        from services.llm import chat_complete
        from services.llm_config import SPEC_NEXT_SESSION_ICEBREAKER
        from services.will_voice import with_voice_rules
    except Exception as e:
        logger.warning("icebreaker: llm import failed: %s", e)
        return None

    system = with_voice_rules(
        "You are designing the FIRST question of a coaching session's "
        "warm-up phase. You'll be given a digest of the user's "
        "PREVIOUS coaching session — the snippets they recorded and "
        "what their coach observed. Produce ONE icebreaker question "
        "that:\n"
        "  - references something specific the user said or did last "
        "    session (a moment, a phrasing, a topic they brought up)\n"
        "  - feels warm and curious, not interrogative\n"
        "  - opens the door to reflection (not yes/no)\n"
        "  - is conversational and short (≤ 280 chars)\n"
        "  - ends with '?'\n"
        "  - does NOT mention coaching jargon like 'charisma', "
        "    'stress', 'KPI', 'snippet', or component names\n"
        "  - does NOT recap the previous session in declarative "
        "    sentences before the question\n"
        "\n"
        "Voice: a coach who remembered. Like 'hey, last week you "
        "mentioned X — how's that going?' but as one clean question.\n"
        "\n"
        "Output strict JSON with one key: 'question'. The value is "
        "the question text only — no quotes, no preamble, no "
        "explanation."
    )
    user_prompt = _build_user_prompt(snippets, session)

    schema = {
        "name": "next_session_icebreaker",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["question"],
            "properties": {
                "question": {
                    "type": "string",
                    "minLength": MIN_QUESTION_LEN,
                    "maxLength": MAX_QUESTION_LEN,
                },
            },
        },
        "strict": True,
    }

    result = chat_complete(
        spec=SPEC_NEXT_SESSION_ICEBREAKER,
        system=system,
        user=user_prompt,
        surface=_SURFACE,
        response_format_override={
            "type": "json_schema",
            "json_schema": schema,
        },
        user_id=str(session.get("user_id") or "") or None,
    )
    if not result:
        return None

    parsed = result.parsed
    if not isinstance(parsed, dict):
        # JSON-schema mode but parse failed inside chat_complete —
        # try the raw text as a single line.
        text = (result.text or "").strip()
        try:
            parsed = json.loads(text)
        except Exception:
            logger.warning(
                "icebreaker: llm output unparseable: %r", text[:200],
            )
            return None
        if not isinstance(parsed, dict):
            return None

    question = str(parsed.get("question") or "").strip()
    return question or None


def _build_user_prompt(snippets: list[dict], session: dict) -> str:
    """Serialise the previous-session digest the LLM grounds in.

    Per FE handoff Q7: feed the snippets (transcripts + admin
    comments). Snippets are the unit of "turns" in a v2 session —
    each one is a user answer + admin observation. 12 max keeps
    token cost bounded for outlier retention sessions.
    """
    parts: list[str] = []

    # Per-session intake context — short, present-or-absent. Gives
    # the LLM what the user said they wanted to work on.
    intake = session.get("intake_context") if isinstance(
        session.get("intake_context"), dict,
    ) else None
    if intake:
        topic = (intake.get("topic") or "").strip()
        audience = (intake.get("audience") or "").strip()
        if topic or audience:
            ctx_bits = []
            if topic:
                ctx_bits.append(f"topic: {topic}")
            if audience:
                ctx_bits.append(f"audience: {audience}")
            parts.append(
                "PREVIOUS SESSION CONTEXT:\n  " + " · ".join(ctx_bits)
            )

    # The snippets — each one as a mini-record. Capped per the handoff.
    # We iterate in original order; assumption is db.get_snippets_by_
    # session returns them in creation order, which matches user
    # experience order.
    rendered: list[str] = []
    for s in snippets[:MAX_SNIPPETS_IN_PROMPT]:
        transcript = (
            (s.get("transcript") or "")
            or (s.get("transcription_text") or "")
            or ""
        ).strip()
        if len(transcript) > 360:
            transcript = transcript[:360].rstrip() + "…"
        admin_comment = (s.get("admin_comment") or "").strip()
        if len(admin_comment) > 240:
            admin_comment = admin_comment[:240].rstrip() + "…"
        tone = (s.get("question_tone") or s.get("snippet_type") or "").strip().lower()

        if not (transcript or admin_comment):
            continue
        bits: list[str] = []
        if tone in ("charisma", "stress"):
            bits.append(f"[{tone}]")
        if transcript:
            bits.append(f'user: "{transcript}"')
        if admin_comment:
            bits.append(f"coach noted: {admin_comment}")
        rendered.append("  - " + " ".join(bits))

    if rendered:
        parts.append(
            "WHAT HAPPENED IN THE PREVIOUS SESSION (snippet-by-"
            "snippet, most recent last):\n" + "\n".join(rendered)
        )
    else:
        # Shouldn't fire — _has_usable_signal would have filtered
        # this case — but defensive.
        parts.append("WHAT HAPPENED: (no usable snippet content)")

    parts.append(
        "Write the ONE icebreaker question that opens the next "
        "session warmly, anchored on the SPECIFIC moment above that "
        "feels most worth picking up on. Output strict JSON."
    )
    return "\n\n".join(parts)
