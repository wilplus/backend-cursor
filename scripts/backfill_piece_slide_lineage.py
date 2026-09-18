#!/usr/bin/env python3
"""Republish Ideal Text heads that lost every Paragraph -> Slide link.

THE DEFECT (founder 2026-09-18: "after a lock the text skipped the slides and
got concatenated again", with a deck whose kicker read "YOUR TALK").

Before #539 a lock recomposed the served text, which made ``aligned`` fail; the
carry by ``part_id`` needed a parts list that ``build_snapshot`` had already
dropped, so the ordinal-adoption branch could not fire either. Every paragraph
was published with ``slide_index`` NULL. The frontend's ``groupChunksBySlide``
then fails on the first paragraph with ``missing_parent_slide`` — it refuses to
invent a parent slide — and the deck collapses into one unlinked section with no
slide kickers and, because the preview is rendered per slide group, no slide
picture at all.

#539 stopped NEW snapshots being poisoned. It does not repair the ones already
written, and nothing else will: ``GET /ideal-text/core`` serves one immutable
prepared snapshot and explicitly "does not compose, repair, persist". A document
that lost its slides this way stays flat on every reload, forever.

WHAT THIS DOES. For each affected head it calls ``publish_for_arc`` — the same
publisher the next Take would use, with the #539 fix in it — so the lineage is
re-derived from the machine's own provenance rows and a NEW immutable head is
published. Nothing is edited in place and nothing is deleted: the poisoned
snapshot stays in the table as superseded history.

WHAT THIS IS NOT. It does not rebuild the document (L1). ``publish_for_arc``
composes exactly what it would compose at the next publish; the words are the
words the user already has. It cannot invent a slide either: where provenance is
missing or the counts disagree, ``build_snapshot`` fails closed to NULL and the
arc is reported as UNRECOVERED rather than guessed at.

Preview is the default, on purpose — this writes to canonical document lineage.

Usage::

    python3 scripts/backfill_piece_slide_lineage.py                 # preview
    python3 scripts/backfill_piece_slide_lineage.py --arc-id <uuid> # one arc
    python3 scripts/backfill_piece_slide_lineage.py --apply         # publish
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Any, Mapping

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.db import db  # noqa: E402
from services.ideal_text_core_snapshot import publish_for_arc  # noqa: E402


def _pieces(payload: Any) -> list[Mapping[str, Any]]:
    if not isinstance(payload, Mapping):
        return []
    raw = payload.get("pieces")
    if not isinstance(raw, list):
        return []
    return [p for p in raw if isinstance(p, Mapping)]


def _linked(pieces: list[Mapping[str, Any]]) -> int:
    """How many paragraphs carry a usable slide index.

    Mirrors the frontend's reader exactly: a bool is not an int here, and a
    negative index is not a slide. Anything it would reject must count as
    unlinked, or this script would call a document healthy that still renders
    as one flat section.
    """
    total = 0
    for piece in pieces:
        slide = piece.get("slide_index")
        if isinstance(slide, bool) or not isinstance(slide, int) or slide < 0:
            continue
        total += 1
    return total


def _is_poisoned(pieces: list[Mapping[str, Any]]) -> bool:
    """A head that will render flat no matter how often it is reloaded.

    Scoped to the total loss, not to partial gaps. A NULL that FOLLOWS a real
    slide index is legitimate and the client inherits it (a paragraph continues
    on the slide it started on); only a document whose FIRST paragraph has no
    provable slide collapses, and with every index NULL that is guaranteed.
    Documents with one paragraph are excluded: a single unlinked section is the
    same screen either way, so republishing one buys nothing.
    """
    return len(pieces) > 1 and _linked(pieces) == 0


def _heads(arc_id: str | None, limit: int) -> list[dict]:
    query = db.client.table("ideal_text_document_heads").select(
        "arc_id, actor_id, snapshot_id")
    if arc_id:
        query = query.eq("arc_id", str(arc_id))
    return list(query.limit(limit).execute().data or [])


def _head_payload(arc_id: str, actor_id: str) -> Mapping[str, Any] | None:
    snapshot = db.get_ideal_text_document_snapshot(str(arc_id), str(actor_id))
    if not isinstance(snapshot, Mapping):
        return None
    payload = snapshot.get("payload")
    return payload if isinstance(payload, Mapping) else None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--arc-id", default=None,
                        help="repair one arc instead of scanning")
    parser.add_argument("--limit", type=int, default=500,
                        help="how many heads to scan (default 500)")
    parser.add_argument("--apply", action="store_true",
                        help="publish; without it nothing is written")
    args = parser.parse_args()

    heads = _heads(args.arc_id, args.limit)
    print(f"scanned {len(heads)} head(s)")

    affected: list[tuple[str, str, int]] = []
    for head in heads:
        arc_id = str(head.get("arc_id") or "")
        actor_id = str(head.get("actor_id") or "")
        if not arc_id or not actor_id:
            continue
        pieces = _pieces(_head_payload(arc_id, actor_id))
        if _is_poisoned(pieces):
            affected.append((arc_id, actor_id, len(pieces)))

    if not affected:
        print("no head has lost its slide lineage — nothing to do")
        return 0

    print(f"\n{len(affected)} head(s) render as one unlinked section:")
    for arc_id, actor_id, count in affected:
        print(f"  arc={arc_id} actor={actor_id} paragraphs={count}")

    if not args.apply:
        print("\npreview only — re-run with --apply to republish")
        return 0

    repaired = 0
    unrecovered: list[str] = []
    for arc_id, actor_id, _count in affected:
        result = publish_for_arc(db, arc_id, actor_id,
                                 enqueue_on_failure=False)
        after = _pieces(_head_payload(arc_id, actor_id))
        linked = _linked(after)
        if result is not None and linked > 0:
            repaired += 1
            print(f"  repaired arc={arc_id} "
                  f"({linked}/{len(after)} paragraphs linked)")
        else:
            # Fails closed: provenance is missing or its counts disagree, so
            # the lineage is genuinely unprovable. Report it; never guess.
            unrecovered.append(arc_id)
            print(f"  UNRECOVERED arc={arc_id} — provenance cannot prove it")

    print(f"\nrepaired {repaired}, unrecovered {len(unrecovered)}")
    for arc_id in unrecovered:
        print(f"  still flat: {arc_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
