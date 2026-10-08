"""A rewrite the speaker declined is not offered again on that Paragraph
until its words change (founder 2026-10-05, N48.2, Q3 A; PARTS §12.3, the
Intent Ledger: "never re-litigated").

THE RECORD. "Keep my words" on a V3 rewrite card is the owner's
`keep_wording` answer on the `rewrite_clarity` item
(`take_feedback_self_report`, appended by the feedback-response route). The
item id is the V3 `candidate_key`, so the freeze that served it names the
Paragraph (`source_ideal_part_id`), the candidate holds the quote and the
proposed words, and the freeze's document snapshot holds the words the
Paragraph had when the speaker saw the card. Nothing is stored for this:
every input already exists, immutable.

THE RULE. On a later Take, a rewrite candidate is excluded with the typed
reason ``declined_by_owner`` when a standing decline names the same
Paragraph, the same quote and the same proposed words (whitespace and case
aside). A decline stands while the Paragraph's words are the ones it had at
the decline: the comparison is the declined freeze's Paragraph text against
the Paragraph text this Take is served on. A new Take that said different
words, or an edit, changes the words and the rewrite may be offered again.
A deliberate simplification: words that change and later change BACK to
exactly the declined version revive the decline. That keeps one comparison
instead of a walk through every version, and its only effect is not
re-offering a rewrite the speaker already said no to.

WHAT NEVER CHANGES. Only declines from an EARLIER Take, recorded before this
Take was created, count, so the set a Take is judged against is fixed the
moment it starts; and a candidate already in this Take's frozen selection is
never excluded, so a decline can never take back something a Take served.
An unreadable record excludes nothing (the pre-Q3 behaviour), logged. The
exclusion is an inventory row with its reason, never a substitute: V3 then
anchors the block's next defensible rewrite or leaves the lane honestly
empty (24f). Nothing here reaches the speaker (AC-9).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

logger = logging.getLogger(__name__)

DECLINED_BY_OWNER = "declined_by_owner"

RewriteKey = tuple[str, str, str]


def instant(value: Any) -> Optional[datetime]:
    """An aware datetime from a stored timestamp, or None."""
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def words(text: Any) -> str:
    """The words, whitespace collapsed; "" for anything not text."""
    return " ".join(text.split()) if isinstance(text, str) else ""


def rewrite_key(part_id: Any, quote: Any, proposed: Any) -> Optional[RewriteKey]:
    """(Paragraph, quote, proposed words) — "the same rewrite" — or None when
    any of the three is missing."""
    part, said, offered = str(part_id or ""), words(quote), words(proposed)
    if not part or not said or not offered:
        return None
    return part, said.casefold(), offered.casefold()


def _declines_before(rows: Iterable[Any], take_session_id: str,
                     take_started: datetime) -> list[dict]:
    """The declines on EARLIER Takes recorded before this Take began."""
    out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        take = str(row.get("take_session_id") or "")
        item = str(row.get("feedback_id") or "")
        at = instant(row.get("created_at"))
        if (not take or not item or take == take_session_id
                or at is None or at >= take_started or (take, item) in seen):
            continue
        seen.add((take, item))
        out.append({"take": take, "item": item, "at": at})
    return out


def _paragraph_words(snapshot: Any, part_id: str) -> Optional[str]:
    payload = snapshot.get("payload") if isinstance(snapshot, dict) else None
    parts = payload.get("parts") if isinstance(payload, dict) else None
    for part in parts or []:
        if isinstance(part, dict) and str(part.get("id")) == part_id:
            text = part.get("text")
            return text if isinstance(text, str) else None
    return None


def _indexed(rows: dict) -> tuple[list, dict, dict, dict]:
    """The four batch reads, keyed for lookup."""
    def rows_of(name: str) -> list:
        return [r for r in rows.get(name) or [] if isinstance(r, dict)]

    items = {(str(i.get("membership_id")), str(i.get("candidate_key"))): i
             for i in rows_of("items")}
    outputs = {str(c.get("id")): c.get("generated_output") or {}
               for c in rows_of("candidates")}
    snapshots = {str(s.get("id")): s for s in rows_of("snapshots")}
    return rows_of("memberships"), items, outputs, snapshots


def _freezes_before(memberships: list, take: str, at: datetime) -> list:
    """This Take's freezes made no later than `at`, newest first."""
    dated = [(instant(m.get("frozen_at")), m) for m in memberships
             if str(m.get("take_id")) == take]
    return [m for when, m in sorted(
        ((when, m) for when, m in dated if when is not None and when <= at),
        key=lambda pair: pair[0], reverse=True)]


def _declined_in(membership: dict, item: dict, outputs: dict,
                 snapshots: dict) -> Optional[dict]:
    """``{key, paragraph_text}`` for one served item, or None if unprovable."""
    part = str(item.get("source_ideal_part_id") or "")
    output = outputs.get(str(item.get("candidate_id"))) or {}
    text = _paragraph_words(
        snapshots.get(str(membership.get("document_snapshot_id"))), part)
    key = rewrite_key(part, output.get("quote"), output.get("proposed_text"))
    if key is None or text is None:
        return None
    return {"key": key, "paragraph_text": text}


def resolve_declines(declines: list[dict], rows: dict) -> list[dict]:
    """Each decline as ``{key, paragraph_text}``: the rewrite the newest
    freeze no later than the decline served under its item id, and the
    words its Paragraph had in that freeze's document. A decline that
    cannot be proven is left out, never guessed."""
    memberships, items, outputs, snapshots = _indexed(rows)
    out: list[dict] = []
    for decline in declines:
        for membership in _freezes_before(memberships, decline["take"],
                                          decline["at"]):
            item = items.get((str(membership.get("id")), decline["item"]))
            if item is None:
                continue
            resolved = _declined_in(membership, item, outputs, snapshots)
            if resolved is not None:
                out.append(resolved)
            break
    return out


def standing_declines(
    database: Any, *, arc_id: str, owner_user_id: str,
    take_session_id: str, take_created_at: Any, parts: Any,
) -> frozenset:
    """The rewrite keys this Take must not offer: declines from earlier
    Takes, recorded before this one began, whose Paragraph still has the
    words it had at the decline. Empty on anything unreadable (logged)."""
    started = instant(take_created_at)
    lister = getattr(database, "list_rewrite_declines", None)
    reader = getattr(database, "read_declined_v3_rewrite_rows", None)
    if started is None or lister is None or reader is None or not arc_id:
        return frozenset()
    rows = lister(str(arc_id), str(owner_user_id))
    if rows is None:
        logger.warning("rewrite declines: unreadable arc=%s take=%s -- none "
                       "applied", arc_id, take_session_id)
        return frozenset()
    declines = _declines_before(rows, str(take_session_id), started)
    if not declines:
        return frozenset()
    served = reader([d["take"] for d in declines], [d["item"] for d in declines])
    if served is None:
        logger.warning("rewrite declines: freezes unreadable arc=%s take=%s "
                       "-- none applied", arc_id, take_session_id)
        return frozenset()
    now = {str(p.get("id")): words(p.get("text"))
           for p in parts or [] if isinstance(p, dict) and p.get("id")}
    standing = frozenset(
        d["key"] for d in resolve_declines(declines, served)
        if now.get(d["key"][0]) is not None
        and now[d["key"][0]] == words(d["paragraph_text"]))
    logger.info("rewrite declines arc=%s take=%s recorded=%d standing=%d",
                arc_id, take_session_id, len(declines), len(standing))
    return standing
