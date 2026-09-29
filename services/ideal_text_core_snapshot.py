"""Materialized, actor-scoped Ideal Text core documents.

The read screen must never rebuild a document.  Processing and product
mutations call :func:`publish_for_arc`; the cold-open endpoint performs one
head+snapshot read and returns the frozen payload.  Feedback, playback,
exercise, coach and analytics state deliberately stay outside this module.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any, Mapping

from services.ideal_text_read import (
    resolve_ideal_text_source,
    resolve_live_text,
    resolve_project_read,
    resolve_suggestion_display,
)
from config import Config

config = Config()

logger = logging.getLogger(__name__)
PUBLICATION_TASK_PATH = (
    "services.ideal_text_core_snapshot.run_pending_publication")


def _canonical_sha(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
                     separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _completed_spoken(sessions: Any) -> list[Mapping[str, Any]]:
    return [row for row in (sessions or [])
            if row.get("recording_kind") != "read"
            and not row.get("paired_session_id")
            and row.get("analysis_state") in (None, "ready")]


def _applied_moments(database: Any, session_ids: list[Any]) -> dict[str, bool]:
    result: dict[str, bool] = {}
    for session_id in {str(value) for value in session_ids if value}:
        try:
            rows = database.get_suggestion_feedback_by_session(session_id) or []
        except Exception:
            continue
        for row in rows:
            if row.get("target") not in (
                    "moment_emphasize", "moment_replace",
                    "document_replace", "document_bold"):
                continue
            snippet_id = row.get("snippet_id")
            if snippet_id is not None:
                result[str(snippet_id)] = row.get("action") == "applied"
    return {key: value for key, value in result.items() if value}


def _fold_applied(text: str, moments: list[dict[str, Any]]) -> str:
    """Pure legacy-decision fold used only while materializing a snapshot."""
    from services.ideal_text_block import accent_span, within_accent_window
    for moment in moments or []:
        if not moment.get("applied"):
            continue
        suggestion = moment.get("suggestion") or {}
        moment_id = moment.get("id")
        take_id = moment.get("take_session_id")
        if not moment_id or not take_id:
            continue
        pattern = re.compile(
            r"\[\[moment:" + re.escape(str(moment_id)) + r"\|"
            + re.escape(str(take_id)) + r"\]\](?P<inner>.*?)\[\[/moment\]\]",
            re.DOTALL,
        )
        if suggestion.get("kind") == "replace" and str(
                suggestion.get("replacement") or "").strip():
            replacement = str(suggestion["replacement"]).strip()
            text = pattern.sub(
                lambda _match: (
                    f"[[moment:{moment_id}|{take_id}]]{replacement}[[/moment]]"
                ), text, count=1)
        elif suggestion.get("kind") == "emphasize":
            def emphasize(match: re.Match[str]) -> str:
                inner = match.group("inner")
                if "{{orange:" in inner or not within_accent_window(inner):
                    return match.group(0)
                return (f"[[moment:{moment_id}|{take_id}]]"
                        f"{accent_span(inner)}[[/moment]]")
            text = pattern.sub(emphasize, text, count=1)
    return text


def _suggestions_enabled() -> bool:
    return bool(config.MOMENT_SUGGESTIONS_ENABLED)


def _paragraphs_of(text: str) -> list[str]:
    return [part.strip() for part in text.split("\n\n") if part.strip()]


def _provenance_rows(row: Mapping[str, Any]) -> list[Mapping[str, Any]] | None:
    """The canonical document's per-paragraph provenance, or None when it is
    missing or any entry is malformed."""
    document = row.get("document") if isinstance(row.get("document"), dict) else {}
    provenance = document.get("paragraphs") if isinstance(document, dict) else []
    return (
        provenance
        if isinstance(provenance, list)
        and all(isinstance(item, Mapping) for item in provenance)
        else None
    )


def _previous_by_part(
    previous_payload: Mapping[str, Any] | None,
) -> dict[str, Mapping[str, Any]]:
    """``{part id: piece}`` from the previous immutable snapshot, when its
    parts and pieces line up one to one."""
    previous_by_part: dict[str, Mapping[str, Any]] = {}
    if not isinstance(previous_payload, Mapping):
        return previous_by_part
    previous_parts = previous_payload.get("parts")
    previous_pieces = previous_payload.get("pieces")
    if not (isinstance(previous_parts, list) and isinstance(previous_pieces, list)
            and len(previous_parts) == len(previous_pieces)):
        return previous_by_part
    for old_part, old_piece in zip(previous_parts, previous_pieces):
        if not isinstance(old_part, Mapping) \
                or not isinstance(old_piece, Mapping):
            continue
        old_id = str(old_part.get("id") or "")
        if old_id:
            previous_by_part[old_id] = old_piece
    return previous_by_part


def _proven_slide(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _published_piece(index: int, paragraph: str, part: Mapping[str, Any],
                     source: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "piece_key": index,
        "part_id": part.get("id"),
        "text": paragraph,
        "root_phrase": part.get("root_phrase"),
        "root_type": "flagship" if part.get("root_phrase") else None,
        "slide_index": _proven_slide(source.get("slide_index")),
        "block_key": None,
        "snippet_id": source.get("snippet_id"),
        "take_session_id": source.get("take_session_id"),
        "take_index": source.get("take_index"),
        "status": "settled",
        "challenger": None,
    }


def _exact_pieces(
    row: Mapping[str, Any],
    text: str,
    parts: list[dict[str, Any]] | None,
    previous_payload: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Return only provable paragraph→Slide mappings; never position-guess.

    The first snapshot proves Slide lineage from the canonical Take-1
    document.  Later wording edits preserve stable Paragraph ids, so their
    already-proven Slide lineage can be carried from the previous immutable
    snapshot.  New/split/merged Paragraph ids receive no attachment until a
    writer publishes explicit lineage.
    """
    paragraphs = _paragraphs_of(text)
    provenance_rows = _provenance_rows(row)
    part_rows = parts or []
    source_paragraphs = _paragraphs_of(
        str(row.get("auto_text") or row.get("text") or "").strip())
    aligned = (
        provenance_rows is not None
        and len(provenance_rows) == len(paragraphs) == len(source_paragraphs)
        and source_paragraphs == paragraphs
    )
    previous_by_part = _previous_by_part(previous_payload)

    # Compatibility adoption for documents first edited before the immutable
    # core began returning stored Paragraph identity.  The only live edit
    # surface mutates the existing Paragraph slots in place: it cannot insert,
    # delete, split, merge, or reorder them.  Under that contract equal counts
    # prove that slot N is still the same Slide-bounded Paragraph even when its
    # wording changed.  This repairs those already-saved documents once; from
    # the next snapshot onward `part_id` is carried explicitly and this branch
    # is no longer needed for that document.  Any structural ambiguity fails
    # closed to the unlinked "Your talk" view.
    #
    # IT NO LONGER REQUIRES THE PART ROWS (founder 2026-09-17: "after the lock
    # the different text shows … something without the slide, entirely wrong").
    # Reported with a deck whose kicker read "YOUR TALK" — the unlinked view —
    # on a document that had slides a moment earlier.
    #
    # The chain: a lock recomposes the served text, so `aligned` fails (the
    # words are no longer the machine's original). The carry by `part_id` is
    # next, and it needs a parts list. But `build_snapshot` drops `served_parts`
    # to None whenever they do not agree with the composed text — so `part_rows`
    # arrives empty, `bool(part_rows)` is False, and this branch cannot fire
    # either. Every paragraph is published with slide_index None, and
    # `groupChunksBySlide` fails on the first one (missing_parent_slide),
    # collapsing the whole deck into one untitled section with no slide.
    #
    # Worse, it is self-perpetuating: that snapshot is now the one WITHOUT
    # parts, so the next publication has nothing to carry from. A document that
    # lost its slides this way never got them back.
    #
    # `bool(part_rows)` was never load-bearing. The proof this branch rests on
    # is about PARAGRAPHS — the edit surface mutates slots in place and cannot
    # insert, delete, split, merge or reorder them, so on equal counts slot N
    # is still the same Slide-bounded Paragraph. Part rows are how identity is
    # carried when it IS available; they are not what makes the count a proof.
    # Requiring them turned "we also have ids" into a precondition for the one
    # path that exists precisely for when we do not.
    #
    # The counts still have to line up — provenance, served paragraphs and the
    # canonical source all agreeing — and any structural ambiguity still fails
    # closed to the unlinked view. Nothing is guessed that was not guessed
    # before; one thing that was provable stops being thrown away.
    ordinal_adoption = (
        provenance_rows is not None
        and len(provenance_rows) == len(paragraphs) == len(source_paragraphs)
    )

    out: list[dict[str, Any]] = []
    for index, paragraph in enumerate(paragraphs):
        part = part_rows[index] if index < len(part_rows) else {}
        previous = previous_by_part.get(str(part.get("id") or ""), {})
        source: Mapping[str, Any] = previous
        if aligned and provenance_rows is not None:
            source = provenance_rows[index]
        elif not source and ordinal_adoption:
            # See the compatibility proof above.  Never use this when a
            # stable-id mapping exists: durable identity always wins.
            assert provenance_rows is not None
            source = provenance_rows[index]
        out.append(_published_piece(index, paragraph, part, source))
    return out


def _lineage_owner(database: Any, latest: Mapping[str, Any],
                   arc_id: str) -> tuple[str, str]:
    """(owner principal, project id) for the head's lineage.

    Most Takes carry no owner copy; the project always does
    (`get_project_owner_principal`, the same fallback the practice and
    training paths use). Requiring the copy made every publication of such a
    project fail, so it never got a head and opened as the unlinked "Your
    talk" view with no slides. A recording's arc IS its project, so the arc
    id stands in only when the project answers."""
    project_id = str(latest.get("project_id") or "")
    owner = str(latest.get("owner_principal_id") or "")
    if owner:
        return owner, project_id
    candidate = project_id or str(arc_id or "")
    owner = str(database.get_project_owner_principal(candidate) or "")
    return (owner, candidate) if owner else ("", project_id)


def _settle_parts(
    database: Any, arc_id: str, actor_id: str, text: str,
) -> tuple[str, dict | None, list]:
    """``(text, composed, stored_rows)``: the locked parts recomposed onto
    the served text (and stored when they changed), or, for a document with
    no parts at all, machine parts minted and stored."""
    from services.ideal_text_parts import compose_locked
    stored_rows = database.get_ideal_text_parts(
        arc_id, actor_id, with_lock=True) or []
    composed = compose_locked(text, stored_rows)
    if composed is not None:
        text = composed["text"]
        if composed.get("changed"):
            stored_rows = _store_recomposed(
                database, arc_id, actor_id, composed, stored_rows)
    elif not stored_rows:
        # WHERE A PARAGRAPH IS BORN (production, 2026-09-19: the binder logged
        # `parts=0 pieces=3` -- nothing to place against, on every take).
        #
        # Until now identity arrived only by USER action: the edit PUT and
        # seed-on-lock store the client's list, and `compose_locked` (the
        # branch above) refreshes a list that already has locks. A student who
        # has neither edited nor locked has no Paragraph ids at all, which is
        # the normal state of a fresh project -- and it costs them the V3
        # bookmarks (`piece_has_no_part_id` on every row) and the slide join on
        # the deck (`part_id: None` on every served piece, so the FE's
        # `partsFromCorePieces` declines the set).
        #
        # HERE, and only here, because this runs at a WRITE BOUNDARY:
        # `build_snapshot`'s own contract says it "may persist a newly composed
        # part list because it runs only while publishing; the GET path never
        # calls it". A student GET must still never mint identity.
        #
        # ONLY WHEN THE TABLE IS EMPTY. `elif` on the compose branch and
        # `not stored_rows` together mean this cannot touch a document that has
        # any identity of its own -- nothing is overwritten, ever, and a
        # document whose parts merely disagree with the served text keeps them
        # and keeps today's behaviour. L1 holds by construction too: the words
        # are not read for this, only split, and `mint_machine_parts` refuses
        # unless its list joins back to this exact text.
        stored_rows = _mint_parts(database, arc_id, actor_id, text, stored_rows)
    return text, composed, stored_rows


def _store_recomposed(
    database: Any, arc_id: str, actor_id: str, composed: dict,
    stored_rows: list,
) -> list:
    """Store the recomposed parts, each keeping its lock, and re-read."""
    locks = {str(row0.get("id")): row0.get("locked_at")
             for row0 in stored_rows if isinstance(row0, dict)}
    database.replace_ideal_text_parts(
        arc_id, actor_id,
        [{**part, "locked_at": locks.get(str(part["id"]))}
         for part in composed["parts"]])
    return database.get_ideal_text_parts(
        arc_id, actor_id, with_lock=True) or []


def _mint_parts(
    database: Any, arc_id: str, actor_id: str, text: str, stored_rows: list,
) -> list:
    """Mint machine parts for this exact text and store them; the stored
    rows, re-read, or ``stored_rows`` unchanged when nothing was stored."""
    from services.ideal_text_parts import mint_machine_parts
    minted = mint_machine_parts(text)
    if minted and database.replace_ideal_text_parts(
            arc_id, actor_id, minted):
        stored_rows = database.get_ideal_text_parts(
            arc_id, actor_id, with_lock=True) or []
        logger.info(
            "ideal-text parts minted for a never-edited document "
            "parts=%d arc=%s", len(minted), arc_id)
    return stored_rows


def _served_parts(stored_rows: list, text: str) -> Any:
    """The parts to serve, or None when they do not join back to ``text``."""
    from services.ideal_text_parts import serve
    served_parts = serve(stored_rows)
    if served_parts is not None:
        from services.ideal_text_parts import agrees_with_text
        if not agrees_with_text(served_parts, text):
            served_parts = None
    return served_parts


def build_snapshot(
    database: Any,
    arc_id: str,
    actor_id: str,
    sessions: list[Mapping[str, Any]],
    previous_payload: Mapping[str, Any] | None = None,
) -> tuple[dict, dict, dict]:
    """Build the core payload at a write boundary.

    Returns ``(payload, enrichment_seed, lineage)``.  This function may
    persist a newly composed part list because it runs only while publishing;
    the GET path never calls it.
    """
    row = database.ideal_text.get_coach_arc_ideal_text(arc_id) or {}
    source = resolve_ideal_text_source(row)
    if not source.machine_text:
        raise ValueError("IDEAL_TEXT_DOCUMENT_PENDING")
    live = resolve_live_text(arc_id, actor_id, source, database=database)
    display = resolve_suggestion_display(
        arc_id, live.text, live.user_edited, database=database,
        suggestions_enabled=_suggestions_enabled,
        applied_lookup=lambda ids: _applied_moments(database, ids),
        fold_applied=_fold_applied,
    )
    from services.ideal_text_block import (
        extract_key_moments, sanitize_markers, strip_moment_markers,
    )
    text_with_moments = sanitize_markers(display.text)
    moment_seeds = extract_key_moments(text_with_moments)
    text = strip_moment_markers(text_with_moments)

    text, composed, stored_rows = _settle_parts(
        database, arc_id, actor_id, text)
    served_parts = _served_parts(stored_rows, text)

    project = resolve_project_read(
        sessions, completed_spoken=_completed_spoken)
    if not project.spoken_rows or not project.latest_take_session_id:
        raise ValueError("IDEAL_TEXT_DOCUMENT_TAKE_REQUIRED")
    latest = project.spoken_rows[-1]
    owner, project_id = _lineage_owner(database, latest, arc_id)
    if not owner or not project_id:
        raise ValueError("IDEAL_TEXT_DOCUMENT_LINEAGE_REQUIRED")
    version = source.version if isinstance(source.version, int) else 1
    payload = {
        "arc_id": arc_id,
        "version": version,
        "status": live.status,
        "title": project.title,
        "updated_at": row.get("updated_at"),
        "latest_take_session_id": project.latest_take_session_id,
        "take_count": len(project.spoken_rows),
        "can_record_take": project.can_record_take,
        "text": text,
        "presentation_ref": project.presentation_ref or None,
        "slide_titles": project.slide_titles,
        "pieces": _exact_pieces(
            row, text, served_parts, previous_payload=previous_payload),
        "parts": served_parts,
        "user_edited": bool(composed is None and live.user_edited),
    }
    seed = {
        "moments": moment_seeds,
        "prior_edit": live.prior_edit,
        "suggestions_enabled": display.enabled,
    }
    lineage = {
        "acquisition_principal_id": owner,
        "project_id": project_id,
        "source_take_session_id": project.latest_take_session_id,
        "version": version,
        "source_fingerprint_sha256": _canonical_sha({
            "payload": payload,
            "seed": seed,
            "row_updated_at": row.get("updated_at"),
        }),
    }
    return payload, seed, lineage


def enqueue_pending_publication(
    arc_id: str, source_generation: int | None = None,
) -> bool:
    """Best-effort broker delivery; the generation row is durable truth."""
    from services import job_queue
    if not job_queue.queue_configured():
        return False
    generation = source_generation
    if not isinstance(generation, int):
        from services.db import db
        generation = db.get_ideal_text_document_generation(str(arc_id))
    if not isinstance(generation, int):
        return False
    return job_queue.enqueue(
        PUBLICATION_TASK_PATH, str(arc_id), generation,
        rq_job_id=f"ideal-text-publish:{arc_id}:{generation}",
    )


def run_pending_publication(arc_id: str, source_generation: int) -> None:
    """RQ entry point. A newer generation supersedes this delivery safely."""
    from services.db import db
    current = db.get_ideal_text_document_generation(str(arc_id))
    if current != int(source_generation):
        return
    if publish_for_arc(db, str(arc_id), enqueue_on_failure=False) is None:
        raise RuntimeError("IDEAL_TEXT_DOCUMENT_PUBLICATION_RETRY_REQUIRED")


def sweep_pending_publications(database: Any, limit: int = 100) -> int:
    """Re-enqueue durable invalidations whose materialisation was interrupted."""
    queued = 0
    for row in database.list_pending_ideal_text_document_publications(limit):
        arc_id = str(row.get("arc_id") or "")
        generation = row.get("generation")
        if arc_id and isinstance(generation, int) and enqueue_pending_publication(
                arc_id, generation):
            queued += 1
    return queued


def publish_for_arc(database: Any, arc_id: str,
                    actor_id: str | None = None, *,
                    enqueue_on_failure: bool = True) -> dict | None:
    """Publish one immutable head; retry once if a source mutates mid-build."""
    try:
        sessions = database.takes.get_arc_sessions(arc_id) or []
        spoken = _completed_spoken(sessions)
        if not spoken:
            return None
        actor = _publishing_actor(spoken, actor_id)
        if not actor:
            return None
        for _attempt in range(2):
            result = _publish_attempt(database, arc_id, actor, sessions)
            if result is not None:
                # NO BAKE HERE, and the absence is the fix (#587, task #43).
                #
                # #580 computed the bookmarks on this line, which reads as the
                # obvious place: the snapshot has just been published and its
                # id is in hand. It was the worst place in the codebase.
                # SEVEN callers reach `publish_for_arc` — the cold-open GET,
                # two coach routes, block mutation, the later-take finalizer,
                # the RQ publisher and the backfill script — so a 20-40s
                # Manager run hung here is paid by all of them, including the
                # cold open the bake exists to make fast.
                #
                # Worst of all it is on Take 1 document creation, via
                # `maybe_assemble_ideal_text`. Publication went from about a
                # second to 22 and 42, and a take whose publication never
                # landed terminated as "we processed your take, but couldn't
                # create your Ideal Text" — F1 piece (b), lost to an
                # optimisation for the marks that hang off it.
                #
                # The bake now runs as its own queued job at the end of the
                # analysis run, where no request and no take is waiting on it
                # — see `services.ideal_text_feedback_bake.enqueue_bake`.
                # This function's job is to publish a head, and only that.
                return result
        raise ValueError("IDEAL_TEXT_DOCUMENT_SOURCE_STALE")
    except Exception as error:
        logger.warning("ideal-text snapshot publish failed arc=%s: %s",
                       arc_id, error)
        if enqueue_on_failure:
            _enqueue_retry(arc_id)
        return None


def _publishing_actor(
    spoken: list[Mapping[str, Any]], actor_id: str | None,
) -> str:
    """The given actor, else the latest spoken Take's user or owner, else ""."""
    latest = sorted(spoken, key=lambda row: row.get("take_index") or 0)[-1]
    return str(actor_id or latest.get("user_id")
               or latest.get("owner_principal_id") or "")


def _publish_attempt(
    database: Any, arc_id: str, actor: str, sessions: list,
) -> dict | None:
    """One build-and-publish against the current generation; None when the
    source moved underneath it."""
    generation = database.get_ideal_text_document_generation(
        str(arc_id))
    if not isinstance(generation, int):
        raise ValueError("IDEAL_TEXT_DOCUMENT_GENERATION_REQUIRED")
    previous = database.get_ideal_text_document_snapshot(
        str(arc_id), actor)
    previous_payload = (
        previous.get("payload")
        if isinstance(previous, Mapping)
        and isinstance(previous.get("payload"), Mapping)
        else None
    )
    payload, seed, lineage = build_snapshot(
        database, str(arc_id), actor, sessions,
        previous_payload=previous_payload)
    return database.publish_ideal_text_document_snapshot(
        arc_id=str(arc_id), actor_id=actor, payload=payload,
        enrichment_seed=seed, source_generation=generation,
        **lineage)


def _enqueue_retry(arc_id: str) -> None:
    try:
        enqueue_pending_publication(str(arc_id))
    except Exception as enqueue_error:
        logger.warning(
            "ideal-text snapshot retry enqueue failed arc=%s: %s",
            arc_id, enqueue_error,
        )


# Per-process memory of when each arc last tried an on-open publication. The
# client asks again every few seconds while a document is pending; one build
# per arc per window is enough, and the rest simply read.
MISSING_HEAD_PUBLISH_WINDOW_SECONDS = 30.0
_missing_head_publish_attempts: dict[str, float] = {}


def read_core_or_publish(database: Any, arc_id: str, actor_id: str, *,
                         is_owner: Any) -> dict | None:
    """The owner-checked cold-open read; when there is no head at all, one
    publication and a second read (founder 2026-09-28, decision 16A: "build
    and save it the moment it's opened").

    The head is normally published at every write boundary. When that
    publication fails -- a dropped connection, a worker that never ran the
    retry, a Take without its owner copy -- the project has a document and no
    head, and every open read the composing lane instead, which cannot always
    prove each Paragraph's Slide: the deck collapsed into one untitled "Your
    talk" section with no slide picture. Publishing here repairs the head
    once, through the same writer every other boundary uses.

    Only the project's owner triggers it (``is_owner``), at most once per arc
    per window, and only when the read found no head -- an existing head is
    never rebuilt from here. A failed READ still raises to the caller."""
    import time

    core_read = database.get_ideal_text_document_core_v2(arc_id, actor_id)
    if core_read:
        return core_read
    key = str(arc_id)
    now = time.monotonic()
    last = _missing_head_publish_attempts.get(key)
    if last is not None and now - last < MISSING_HEAD_PUBLISH_WINDOW_SECONDS:
        return None
    _missing_head_publish_attempts[key] = now
    try:
        if not is_owner():
            return None
        published = publish_for_arc(database, key, actor_id)
    except Exception as error:
        logger.warning("ideal-text core on-open publish failed arc=%s: %s",
                       arc_id, error)
        return None
    logger.info("ideal-text core on-open publish arc=%s published=%s",
                arc_id, published is not None)
    if published is None:
        return None
    return database.get_ideal_text_document_core_v2(arc_id, actor_id)
