"""An accepted rewrite becomes a new version of its Paragraph (contract 29b,
clause 16; F1 Repair Plan Phase 4, P1-1).

FOUNDER, 2026-10-01 (C11): "Accept writes a new version of the Paragraph,
labelled 'Correction accepted'." Contract 9: between Takes the Ideal Text
changes through the user's own edit, an explicitly accepted proposal, or an
adopted practice -- and the next Take replaces all of these with what was
said.

WHAT ACCEPT DID BEFORE. The owner's `apply_suggestion` answer was saved, and
the page then sent a decision-ledger star keyed on the whole document piece
of the item's snippet, with the replacement read from an unrelated
moment-suggestion row. For a V3 rewrite that either did nothing or replaced
the wrong words, and the ledger bakes "forever forward", against clause 9.
No Paragraph version was ever written.

WHAT IT DOES NOW. After the answer is saved, the server -- never the
browser -- takes the rewrite's own words from the V3 freeze that served it
(the selected membership item names the Paragraph; its candidate holds the
quote and the proposed words), replaces the quote in that Paragraph, and
writes the result through the one sanctioned owner-edit writer,
`compare_and_set_user_ideal_edit_v1`. That RPC appends the immutable
`owner_part_text_updated` revision (clause 16) and stores the owner edit,
which the next Take supersedes (Q5 A) -- the "next Take replaces them" of
clause 9.

A PARAGRAPH WITH HELPER WORDS OR A LOCK (founder 2026-10-05: "it is possible
that helper words are attached to the words that are not visible - but
exist only in the history; that should be the logic of it"). The accepted
words go in and the Paragraph stays locked. Its helper words stay too:
words picked in the text move to the Slide row -- where words from an
earlier Take already live, shown as the Paragraph's helper words with
nothing marked in the text -- and the in-text span is cleared, so they
point at the version they were picked from, which stays in History. The
write goes through `accept_rewrite_into_part_v1` (0418), the one door the
owner-edit writer opens for a protected Paragraph's text. If the words
cannot be carried, nothing is written (`protected`).

WHAT IT REFUSES, and says so: a quote that is no longer in
the Paragraph, a quote found more than once (the freeze carries no span,
so the server never guesses which), and a document whose Paragraphs do not
join to the text the speaker is reading. Each is an outcome the page shows
as "not saved"; none changes a word. A repeated answer (a replay) finds the
words already in place and changes nothing (audit 2026-10-04).
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

APPLIED = "applied"
ALREADY = "already_applied"
PROTECTED = "protected"
STALE = "stale"
NOT_FOUND = "not_found"
FAILED = "failed"

# The writer's refusals, by code (never a substring of an unrelated code).
_PROTECTED_CODES = ("IDEAL_TEXT_PART_REQUIRES_UNLOCK",)
_STALE_CODES = ("IDEAL_TEXT_DOCUMENT_SOURCE_STALE", "IDEAL_TEXT_USER_EDIT_CONFLICT",
                "IDEAL_TEXT_PARTS_REFRESH_REQUIRED")


def served_rewrite(database: Any, take_session_id: str,
                   feedback_id: str) -> Optional[dict]:
    """The selected V3 rewrite this Take served under `feedback_id`:
    ``{part_id, quote, proposed_text}``, or None."""
    reader = getattr(database, "get_served_v3_rewrite", None)
    if reader is None:
        return None
    row = reader(str(take_session_id), str(feedback_id))
    if not isinstance(row, dict):
        return None
    output = row.get("generated_output") or {}
    quote = str(output.get("quote") or "")
    proposed = str(output.get("proposed_text") or "").strip()
    part_id = str(row.get("source_ideal_part_id") or "")
    if not quote.strip() or not proposed or not part_id:
        return None
    return {"part_id": part_id, "quote": quote, "proposed_text": proposed}


def _served_text(database: Any, arc_id: str, owner_user_id: str
                 ) -> tuple[Optional[str], Optional[int]]:
    """The words the speaker is reading and the document version, as the
    edit route reads them: the owner edit at the current version, else the
    machine text."""
    row = database.ideal_text.get_coach_arc_ideal_text(arc_id) or {}
    machine = ((row.get("auto_text") or "").strip()
               or ((row.get("text") or "").strip()
                   if not (row.get("updated_by") or row.get("approved_at"))
                   else ""))
    version = row.get("version") or (1 if machine else None)
    if not isinstance(version, int):
        return None, None
    edit = database.get_user_ideal_edit(arc_id, owner_user_id) or {}
    own = str(edit.get("text") or "").strip()
    if own and edit.get("version") == version:
        return own, version
    return machine or None, version


def _positions(text: str, needle: str) -> list[int]:
    """Every non-overlapping start of `needle` in `text`."""
    out: list[int] = []
    at = text.find(needle) if needle else -1
    while at >= 0:
        out.append(at)
        at = text.find(needle, at + len(needle))
    return out


def _free_quotes(text: str, quote: str, proposed: str) -> list[int]:
    """The quote's starts that do not sit inside the accepted words already
    in place (proposed "we grew fast" holds the quote "we grew")."""
    covered = [(s, s + len(proposed)) for s in _positions(text, proposed)]
    return [a for a in _positions(text, quote)
            if not any(s <= a and a + len(quote) <= e for s, e in covered)]


def rewritten_parts(parts: list, part_id: str, quote: str,
                    proposed: str) -> tuple[str, Optional[list]]:
    """The Paragraphs with the quote replaced in `part_id`. Pure.

    Returns (outcome, parts): APPLIED with the new parts, ALREADY when the
    Paragraph already reads the accepted words and no free quote is left,
    else STALE (the quote is gone, or found more than once) or NOT_FOUND
    with None."""
    target = next((p for p in parts if str(p.get("id")) == part_id), None)
    if target is None:
        return NOT_FOUND, None
    text = str(target.get("text") or "")
    free = _free_quotes(text, quote, proposed)
    if not free and quote.strip() != quote:
        quote = quote.strip()
        free = _free_quotes(text, quote, proposed) if quote else []
    if not free:
        return (ALREADY if proposed in text else STALE), None
    if len(free) > 1:
        return STALE, None
    at = free[0]
    new_text = text[:at] + proposed + text[at + len(quote):]
    out = []
    for p in parts:
        row = {"id": str(p.get("id")), "ord": int(p.get("ord") or 0),
               "text": str(p.get("text") or "").strip()}
        if row["id"] == part_id:
            row["text"] = new_text
        out.append(row)
    return APPLIED, out


def _slide_words_on(database: Any, arc_id: str, owner_user_id: str,
                    part_id: str) -> bool:
    """Helper words saved on the Slide row for this Paragraph (from practice
    or an earlier Take)."""
    reader = getattr(database, "get_slide_helper_words", None)
    rows = reader(str(arc_id), str(owner_user_id)) if reader else []
    return any(str(r.get("source_part_id") or "").lower() == part_id.lower()
               and str(r.get("phrase") or "").strip()
               for r in rows or [] if isinstance(r, dict))


def _protected(database: Any, arc_id: str, owner_user_id: str,
               target: dict) -> bool:
    return bool(target.get("locked_at") or target.get("root_phrase")
                or _slide_words_on(database, arc_id, owner_user_id,
                                   str(target.get("id") or "")))


def _carry_helper_words(database: Any, arc_id: str, owner_user_id: str,
                        target: dict, take_session_id: str) -> bool:
    """Before a protected Paragraph's text changes: its in-text helper words
    move to the Slide row, locked, and the span is cleared. True when the
    words are safe on the Slide row (or there were none in the text)."""
    from services.slide_helper_words import record_lock, record_pick
    part_id = str(target.get("id") or "")
    phrase = str(target.get("root_phrase") or "").strip()
    if not phrase:
        return True
    if not _slide_words_on(database, arc_id, owner_user_id, part_id):
        record_pick(database, arc_id, owner_user_id, part_id,
                    take_session_id, phrase)
        record_lock(database, arc_id, owner_user_id, part_id,
                    take_session_id, True)
        if not _slide_words_on(database, arc_id, owner_user_id, part_id):
            logger.warning("accept_rewrite: helper words not carried "
                           "arc=%s part=%s", arc_id, part_id)
            return False
    return bool(database.set_ideal_text_part_root(
        arc_id=arc_id, user_id=owner_user_id, part_id=part_id,
        phrase=None, start=None, end=None))


def _write(database: Any, *, arc_id: str, owner_user_id: str, version: int,
           desired: list, protected_part: Optional[str]) -> Any:
    from services.ideal_text_parts import joined
    text = joined(desired)
    if protected_part:
        return database.accept_rewrite_into_part(
            owner_user_id=str(owner_user_id), arc_id=str(arc_id),
            source_document_version=version, part_id=protected_part,
            desired_user_text=text, desired_parts_lineage=desired)
    return database.compare_and_set_user_ideal_edit(
        owner_user_id=str(owner_user_id), arc_id=str(arc_id),
        source_document_version=version,
        expected_user_text_revision=None,
        expected_user_text_sha256=None,
        desired_user_text=text,
        desired_parts_lineage=desired,
        idempotency_key=None,
    )


def accept_rewrite(database: Any, *, arc_id: str, owner_user_id: str,
                   take_session_id: str, feedback_id: str) -> str:
    """Write the accepted rewrite as a new version of its Paragraph.
    Returns one of the outcomes above. Never raises."""
    try:
        item = served_rewrite(database, take_session_id, feedback_id)
        if item is None:
            return NOT_FOUND
        served, version = _served_text(database, arc_id, owner_user_id)
        if served is None or version is None:
            return STALE
        parts = sorted(
            database.get_ideal_text_parts(arc_id, owner_user_id,
                                          with_lock=True) or [],
            key=lambda p: int(p.get("ord") or 0))
        from services.ideal_text_parts import agrees_with_text
        if not parts or not agrees_with_text(parts, served):
            logger.warning("accept_rewrite: paragraphs do not join to the "
                           "served text arc=%s", arc_id)
            return STALE
        target = next((p for p in parts
                       if str(p.get("id")) == item["part_id"]), None)
        outcome, desired = rewritten_parts(
            parts, item["part_id"], item["quote"], item["proposed_text"])
        if outcome != APPLIED or desired is None:
            return outcome
        protected = target is not None and _protected(
            database, arc_id, owner_user_id, target)
        if protected and not _carry_helper_words(
                database, arc_id, owner_user_id, target, take_session_id):
            return PROTECTED
        try:
            result = _write(database, arc_id=arc_id,
                            owner_user_id=owner_user_id, version=version,
                            desired=desired,
                            protected_part=(item["part_id"] if protected
                                            else None))
        except Exception as error:
            if any(code in str(error) for code in _PROTECTED_CODES):
                return PROTECTED
            if any(code in str(error) for code in _STALE_CODES):
                return STALE
            raise
        if not isinstance(result, dict) or result.get("saved") is not True:
            return FAILED
        try:
            from services.ideal_text_core_snapshot import publish_for_arc
            publish_for_arc(database, str(arc_id))
        except Exception as error:
            logger.warning("accept_rewrite: publish failed arc=%s: %s",
                           arc_id, error, exc_info=True)
        return APPLIED
    except Exception as error:
        logger.error("accept_rewrite failed arc=%s take=%s item=%s: %s",
                     arc_id, take_session_id, feedback_id, error,
                     exc_info=True)
        return FAILED


def text_update_for_answer(database: Any, row: dict, arc_id: str,
                           owner_user_id: str, take_session_id: str) -> dict:
    """For the answer route: ``{"text_update": outcome}`` when the answer
    accepts a rewrite, else ``{}``. The words come from the V3 freeze that
    served the item, and the outcome rides the answer so the sheet can say
    when nothing changed."""
    if (row.get("feedback_family") != "rewrite_clarity"
            or row.get("response") != "apply_suggestion"):
        return {}
    return {"text_update": accept_rewrite(
        database, arc_id=arc_id, owner_user_id=owner_user_id,
        take_session_id=take_session_id,
        feedback_id=str(row.get("feedback_id") or ""))}
