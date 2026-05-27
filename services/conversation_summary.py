"""Phase A2.1 — rolling conversation summary for the interview surface.

Replaces quadratic-cost full-history replay with a running digest:

  Before A2.1: every `/next-question` call ships the entire
    [{question, transcript}] sequence into the LLM prompt → tokens
    grow linearly per turn, coherence suffers as the prompt grows.

  After A2.1: each turn's exchange (question + user transcript) is
    folded into a ≤~150-token digest by a cheap async gpt-4o-mini
    call. The next `/next-question` reads the digest + the last 2
    raw turns → bounded prompt cost, no loss of "what just
    happened" fidelity.

Failure semantics
-----------------
A failed summary update MUST fall back to "keep previous summary".
Never block the next question on a slow / errored summarizer.
"""
from __future__ import annotations

import logging
import threading
from typing import Optional

from services.db import db


logger = logging.getLogger(__name__)


# Model + decoding spec centralized in services/llm_config.py —
# see SPEC_CONVERSATION_SUMMARY for the canonical values.


def update_summary_sync(
    *,
    session_id: str,
    previous_summary: Optional[str],
    question: str,
    transcript: str,
) -> Optional[str]:
    """Fold one (question, transcript) exchange into the rolling
    digest for ``session_id``. Synchronous — blocks until the LLM
    returns + the row is persisted. Returns the new summary on
    success, ``None`` on any failure (caller treats as "keep
    previous summary").

    Use the ``update_summary_async`` wrapper from the request hot
    path; this sync variant is the one tests and the async thread
    actually call.
    """
    q = (question or "").strip()
    t = (transcript or "").strip()
    if not q and not t:
        # Nothing to fold — leave the previous summary in place.
        return previous_summary

    new_summary = _llm_fold(
        previous_summary=previous_summary,
        question=q,
        transcript=t,
    )
    if not new_summary:
        # LLM down / parse error / empty — keep the previous
        # summary so the next question still has the older
        # (still-useful) context to read.
        logger.warning(
            "conversation_summary: LLM fold returned empty sid=%s "
            "— keeping previous summary",
            session_id,
        )
        return previous_summary

    persisted = db.set_session_conversation_summary(session_id, new_summary)
    if persisted is None:
        logger.warning(
            "conversation_summary: persist failed sid=%s — "
            "next read will see previous summary",
            session_id,
        )
        # Still return the new summary so the caller has the
        # latest text in memory, even though DB didn't take it.
    return new_summary


def update_summary_async(
    *,
    session_id: str,
    previous_summary: Optional[str],
    question: str,
    transcript: str,
) -> None:
    """Fire-and-forget. Spawns a daemon thread that runs
    ``update_summary_sync``. NEVER raises; failures inside the
    thread are caught and logged.

    Use this from the upload-answer hot path so the LLM call
    doesn't add wall-clock latency to the user's response.
    """
    def _runner() -> None:
        try:
            update_summary_sync(
                session_id=session_id,
                previous_summary=previous_summary,
                question=question,
                transcript=transcript,
            )
        except Exception as e:
            logger.warning(
                "conversation_summary: async runner crashed sid=%s "
                "err=%s — previous summary kept",
                session_id, e,
            )

    threading.Thread(
        target=_runner,
        name=f"conv-summary-{session_id[:8]}",
        daemon=True,
    ).start()


def format_summary_for_prompt(summary: str) -> str:
    """Wrap the digest in the prompt block the splice site expects.

    Kept here so the format lives next to the writer — if we ever
    change the section header, both sides update together.
    """
    s = (summary or "").strip()
    if not s:
        return ""
    return (
        "[CONVERSATION SO FAR — digest]\n"
        f"{s}\n"
        "Use this to track what the user has already revealed. "
        "Do NOT re-ask the same angles."
    )


# ── Internals ──────────────────────────────────────────────────────


def _llm_fold(
    *,
    previous_summary: Optional[str],
    question: str,
    transcript: str,
) -> Optional[str]:
    """One LLM call: prior summary + new exchange → updated digest."""
    from services.llm import chat_complete
    from services.llm_config import SPEC_CONVERSATION_SUMMARY

    system = (
        "You maintain a rolling digest of an ongoing interview "
        "conversation between an AI coach and a user. Each call, "
        "you receive: (a) the current digest, (b) the latest "
        "(question, transcript) exchange. Output: an updated "
        "digest that incorporates the new turn while staying "
        "≤150 tokens.\n"
        "\n"
        "Rules:\n"
        "  • Preserve concrete details the user revealed (people, "
        "    situations, recurring themes, specific past events). "
        "    These are what makes the next question feel personal.\n"
        "  • Drop conversational filler (\"yeah\", \"so\", \"like\"). "
        "    The digest is for a coach reading it once before "
        "    asking the next question, not a transcript.\n"
        "  • Use compact third-person notes — \"User mentioned X\", "
        "    \"Theme: Y\". Not chat dialogue, not bullet lists with "
        "    markers — just dense plain text.\n"
        "  • When the new turn contradicts something in the prior "
        "    digest, prefer the new info (the user just said it; "
        "    it's the freshest signal).\n"
        "  • If the new transcript is empty or near-empty (Whisper "
        "    miss, silent turn), preserve the previous digest "
        "    unchanged and add nothing.\n"
        "\n"
        "Output: plain text only. No headers, no JSON, no bullets."
    )

    prior = (previous_summary or "").strip() or "(none — this is the first turn)"

    user_prompt = (
        f"CURRENT DIGEST\n{prior}\n\n"
        f"NEW EXCHANGE\n"
        f"  AI question: {question}\n"
        f"  User transcript: {transcript}\n\n"
        "Return the updated digest only."
    )

    result = chat_complete(
        spec=SPEC_CONVERSATION_SUMMARY,
        system=system,
        user=user_prompt,
        surface="conversation_summary",
    )
    if result is None:
        # chat_complete already logged the failure reason.
        return None
    return result.text or None
