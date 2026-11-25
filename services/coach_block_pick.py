"""The blind "pick the most confident", gone from the app (founder,
25 November 2026, N701): no sheet is sampled or answered any more. Only its
ledger stays, over the answers already given.

Was: the blind "pick the most confident" (founder 2026-10-01, C5-b; Phase 8 of
the coach panel). On from 2026-10-08; the switch was deleted 2026-10-11.

C5-b: "On a sample of blocks, the coach hears that block's candidate
moments, audio only, in random order, without knowing which one the machine
bookmarked, and picks the one that sounds most confident. The pick never
changes the speaker's bookmarks. It is stored to measure, and later to
teach, the Manager's choice."

THE SAMPLE: V3 blocks (the frozen shadow frame) with at least two eligible
confidence candidates; at most three clips per sheet, the machine's pick
among them (D1), shuffled, audio only (no transcript, no speaker, no Take,
no hint); never a block of a Take the coach is walking, never a clip the
coach was exposed to; the weekly cap (20 per coach) is shared with the
error audit (Phase 6a).

THE RECORD (migration 0411, ``coach_block_pick``, answered once, provenance
``coach_block_pick``): the block, the Take, the candidate clips in the order
shown, the pick or Can't tell, the Manager's pick (stored, never sent to a
client), the versions. Never mixed with confidence labels, owner answers or
exercise outcomes (L3); never changes ideal_text_feedback_sets (L2). The
ledger reports the match rate with Can't tell counted apart. No training:
voice training waits for C1 and the founder's sentence.

ONLY SPEAKERS WITH THE TRAINING YES (3.5 pack, file 22 item E4; Privacy 3.5
§4a, signed 2026-10-08). A block reaches a sheet only while its speaker holds
the training yes and has not objected to the blind check
(``pair_consent.take_may_reach_a_coach_sheet``), read when the sheet is
written, when the queue is served and when it is answered. Anyone else is
skipped. A row is never edited after its answer, but a training withdrawal
DELETES every row about the speaker's Takes
(``pair_consent.erase_withdrawn_sheets``), as the purge does.
"""
from __future__ import annotations

import logging
from collections import Counter
from typing import Any, Iterable


_log = logging.getLogger(__name__)

#: At most this many clips on one sheet, the Manager's pick always among them.
SHEET_SIZE = 3
MIN_CANDIDATES = 2
PROVENANCE = "coach_block_pick"
POLICY_VERSION = "coach-block-pick-v1"
#: Wording approved by the founder (D2), word for word.
WORDING = {
    "queue_line": "Also waiting · blind",
    "title": "Pick the most confident moment",
    "short_title": "Pick the most confident",
    "private": "Private · training · one block · random order",
    "question": "Which of these sounds most confident?",
    "clip": "Clip {letter}",
    "this_one": "This one",
    "most_confident": "Most confident",
    "blind_note": "Audio only. No words, no names, no hint of the machine's pick.",
    "save": "Save my pick",
    "cant_tell": "Can't tell",
    "progress": "Block {n} of {of}",
}


# ── blocks worth asking about ─────────────────────────────────────────────

# ── the sheet and the answer ──────────────────────────────────────────────

# ── the ledger ─────────────────────────────────────────────────────────────

def match_rate(rows: Iterable[Any]) -> dict:
    """Picks that matched the Manager's, with Can't tell counted apart.
    Pure; founder-only."""
    counts: Counter = Counter()
    for r in rows:
        if not isinstance(r, dict) or not r.get("answered_at"):
            continue
        if r.get("cant_tell"):
            counts["cant_tell"] += 1
        elif str(r.get("pick_snippet_id")) == str(r.get("manager_pick_snippet_id")):
            counts["match"] += 1
        else:
            counts["differ"] += 1
    judged = counts["match"] + counts["differ"]
    return {"answered": judged + counts["cant_tell"], "match": counts["match"],
            "differ": counts["differ"], "cant_tell": counts["cant_tell"],
            "match_rate": round(counts["match"] / judged, 3) if judged else None,
            "policy_version": POLICY_VERSION}


def ledger(database: Any) -> dict:
    return {"enabled": True, **match_rate(database.list_coach_block_picks_all() or [])}


