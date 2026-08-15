"""KEY MOMENTS — one selector over ONE construct (founder ruling 2026-08-14).

A key moment is a snippet whose voice the panel judged CONFIDENT: quorum on
`conf-q-v1` with the settled value `yes`.

That is the whole definition. There is no `key-moment` construct, no separate
instrument, and nothing here to rate — §17's `conf-q-v1` already says what is
being asked ("Does the speaker sound confident here?") and
services/label_quorum.py already says when it is settled. This module only
SELECTS.

WHAT IT REPLACED, AND WHY BOTH PREDECESSORS WERE FICTIONS
---------------------------------------------------------
1. `training_labels.value == 'challenge'` — the retired challenge/threat
   construct. Its coach control was deleted from the FE on 2026-08-07, so the
   corpus froze: every session reviewed after that date produced zero key
   moments on every surface, including the paid unlock. Worse, two surfaces
   disagreed about the rule — the game counted `challenge` only while the
   feedback page and the paywall counted `challenge` OR `threat`, so a threat
   moment was simultaneously a key moment behind the paywall and a WRONG
   ANSWER in the game.

2. The coach's `strong` tag — briefly proposed as the replacement, and also a
   fiction: no picker for it exists anywhere. The frontend wrote
   `tag: cs.tag ?? "strong"`, defaulting it as a side effect of typing a note.
   A judgment nobody makes is not a judgment.

The only thing a coach actually judges is confidence, on the ternary
instrument. So every surface now reads that, and the same rows that train the
shadow model are the rows that decide what a student sees — one construct, one
instrument, one quorum.

WHY QUORUM AND NOT A SINGLE RATING. One rating is weak supervision, never
ground truth (label ledger rule 3): a lone `yes` is one opinion, and putting it
behind a paywall would sell one person's guess as a finding. `resolve()` also
excludes self-reports (rule 2) and machine proposals (rule 1), so a key moment
is always at least two humans, neither of them the speaker.

Pure apart from one injected read. AC-9: this selects moments, it never scores
them — no count, rank or confidence value is ever surfaced.
"""
from __future__ import annotations

import logging
from typing import Any, Iterable, Optional

logger = logging.getLogger(__name__)

# The construct being read. §17 `conf-q-v1`; the rows live in
# `confidence_labels` and carry this state_id.
STATE_ID = "confidence"

# The settled value that makes a moment KEY. `no` and the ambiguous class are
# settled too — they are simply not this.
KEY_VALUE = "yes"


def is_key_resolution(resolution: Any) -> bool:
    """Does one `label_quorum.resolve()` verdict make a key moment?

    Requires BOTH a settled quorum and the positive value. A
    `perceptually_ambiguous` settlement is a real finding about the moment and
    a legitimate corpus row, but it is not a moment worth replaying.
    """
    if not isinstance(resolution, dict):
        return False
    from services.label_quorum import QUORUM
    return (resolution.get("status") == QUORUM
            and resolution.get("value") == KEY_VALUE)


def confidence_verdicts(database, snippet_ids: Iterable[Any]) -> dict:
    """`{snippet_id: settled_value}` for every snippet the panel has SETTLED.

    ONE batched read, so a caller with a whole arc's snippets does not fan out
    per snippet. Unsettled snippets are ABSENT from the map rather than present
    with a None — an unrated or still-splitting moment has no verdict, and
    handing back a placeholder is how a front-runner gets mistaken for a
    finding (label ledger rule 3).

    Values are the ledger's own: `yes`, `no`, or `ambiguous` (the settled
    perceptually-ambiguous class). Callers decide what each means to them;
    this only reports what the panel concluded.

    Best-effort by design: a read miss returns an EMPTY map rather than
    raising, which degrades a surface to "nothing settled yet" instead of
    failing a page. That is the same direction every other read on these paths
    fails, and the honest one — we cannot claim a verdict we could not read.
    """
    ids = [str(s) for s in (snippet_ids or []) if s]
    if not ids:
        return {}
    try:
        by_snip = database.get_confidence_labels_by_snippet_ids(ids) or {}
    except Exception as e:
        logger.warning("key_moments: confidence read failed (%d ids): %s",
                       len(ids), e)
        return {}

    from services.label_quorum import resolve
    out: dict = {}
    for snip_id, rows in by_snip.items():
        try:
            res = resolve(rows, state_id=STATE_ID)
            if isinstance(res, dict) and res.get("settled"):
                out[str(snip_id)] = res.get("value")
        except Exception as e:
            # One malformed snippet must not take the whole arc's read down.
            logger.warning("key_moments: resolve failed snip=%s: %s",
                           snip_id, e)
    return out


def key_snippet_ids(database, snippet_ids: Iterable[Any]) -> set:
    """The subset of `snippet_ids` that reached confidence quorum = yes.

    A filter over `confidence_verdicts` — same single batched read, same
    degrade-to-empty behaviour. Kept as its own name because "is this a key
    moment" is the question four surfaces actually ask.
    """
    return {
        sid for sid, value in
        confidence_verdicts(database, snippet_ids).items()
        if value == KEY_VALUE
    }


def is_key_moment(database, snippet_id: Optional[Any]) -> bool:
    """Single-snippet convenience. Prefer `key_snippet_ids` for a set —
    this exists for the per-moment serve path, which already holds one id."""
    if not snippet_id:
        return False
    return str(snippet_id) in key_snippet_ids(database, [snippet_id])
