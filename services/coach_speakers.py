"""The Speakers button's read, coach panel lock flow 1 and 3.

Pseudonymous; built from the coach's own queue so the language gate, the
reach rule and BLIND COACH hold by construction. Never a name, email or
user_id; nothing about any moment, only counts.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from services.coach_moments_queue import queue_for_coach


def speakers_summary(queue: list[dict]) -> list[dict]:
    """One row per speaker, in queue order: the goal, what waits, and which
    Takes are answered. Copies only those keys — never a moment."""
    out = []
    for speaker in queue or []:
        if not isinstance(speaker, dict):
            continue
        takes_in = speaker.get("takes")
        if not isinstance(takes_in, list):
            takes_in = []
        takes = []
        for take in takes_in:
            if not isinstance(take, dict):
                continue
            waiting = take.get("waiting") or 0
            waiting_for_text = bool(take.get("waiting_for_text"))
            takes.append({
                "session_id": take.get("session_id"),
                "take_index": take.get("take_index"),
                "sent_at": take.get("sent_at"),
                "waiting": waiting,
                "waiting_for_text": waiting_for_text,
                "answered": (not waiting_for_text) and waiting == 0,
            })
        out.append({
            "pseudonym": speaker.get("pseudonym"),
            "goal": speaker.get("goal"),
            "waiting": speaker.get("waiting") or 0,
            "waiting_for_text": speaker.get("waiting_for_text") or 0,
            "take_count": len(takes),
            "takes": takes,
        })
    return out


def speakers_for_coach(
    database: Any, rows: list, *, rater_id: Any,
    moments_for: Callable[[dict], Optional[list[str]]],
    pseudonym_for: Callable[[Any], str],
) -> list[dict]:
    """The Speakers button for one coach: the queue, then only counts."""
    return speakers_summary(queue_for_coach(
        database, rows, rater_id=rater_id,
        moments_for=moments_for, pseudonym_for=pseudonym_for))
