"""The speaker's Ideal Text notebook read (GET /explore/arc/<arc_id>/ideal-text).

Moved out of ``routes.v2.explore_ideal_text`` unchanged (founder 2026-10-12:
"move logic out of the backend routes"). The route keeps the ownership gate
and the 500 boundary; ``build_notebook`` is the read itself:

    source → historical view → [live text → displayed text (stars folded,
    markers sanitized, anchors extracted) → locked-part compose | project
    fields] → [moment decorations | learning exposure | pieces, parts |
    tracked changes] → payload, with every optional stage that fell back
    named in `degraded` (audit Q-C1).

A bracket runs its branches at the same time (2026-10-18); `degraded` keeps
the order the stages ran in before that.

The route's own helpers (the moment maps, the pieces, the parts block, the
tracked-changes block) reach it through ``NotebookDeps``, bound by the route
on every call, so the canonical document (L1) is read and composed exactly as
before and nothing here decides a Feedback item.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from services.coach_video_storage import refreshed_media_url
from services.ideal_text_read import (
    decorate_key_moments,
    resolve_historical_read,
    resolve_live_text,
    resolve_ideal_text_source,
    resolve_project_read,
    resolve_suggestion_display,
)
from services.ideal_text_pieces import ideal_text_pieces
from services.token_prices import price_of as _price_of

logger = logging.getLogger(__name__)


def optional_read(label, default, reader, degradation=None):
    """Keep auxiliary state machines outside Ideal Text availability.

    Coach delivery, feedback enrichment, pricing, and journey metadata are
    valuable additions to the notebook; none owns the canonical document. A
    fault in one is omitted instead of turning safe text into a 500 — and,
    when the request carries a ``DegradationLog`` (audit Q-C1), named in
    the payload's `degraded` list rather than only in the log.
    """
    if degradation is not None:
        return degradation.run(f"optional.{label}", reader, default)
    try:
        return reader()
    except Exception as exc:
        logger.warning("ideal-text optional read failed %s: %s", label, exc)
        return default


@dataclass(frozen=True)
class NotebookDeps:
    """The route's helpers this read binds to (looked up per request)."""

    suggestions_enabled: Callable
    applied_lookup: Callable
    fold_applied: Callable
    explanations_map: Callable
    playback_map: Callable
    reference_map: Callable
    moments_entitled: Callable
    completed_spoken: Callable
    parts_block: Callable
    tracked_changes_block: Callable


def _displayed_text(database, arc_id, text, user_edited, deps, optional):
    """(stars_on, text, moments): applied suggestions folded in, markers
    sanitized, the key-moment anchors read, then the moment markers
    stripped — so every anchor is plain text in the served string."""
    from services.ideal_text_block import (
        extract_key_moments, sanitize_markers, strip_moment_markers,
    )
    from services.ideal_text_read import SuggestionDisplayRead

    # ── Star suggestions (2026-07-18, flag-gated). Fold APPLIED suggestions
    # into the DISPLAYED text FIRST (unless the user's free-form edit won),
    # then extract the anchors from the folded text. The canonical row is
    # never touched (L1). ──
    display = optional(
        "suggestion_display", None,
        lambda: resolve_suggestion_display(
            arc_id, text, user_edited, database=database,
            suggestions_enabled=deps.suggestions_enabled,
            applied_lookup=deps.applied_lookup,
            fold_applied=deps.fold_applied))
    if display is None:
        display = SuggestionDisplayRead(False, text)
    # Marker hygiene BEFORE the anchors are read (founder 2026-07-27).
    text = sanitize_markers(display.text)
    moments = extract_key_moments(text)
    # Serve the ANCHOR path, never both (audit 2026-07-18): extract first,
    # then strip.
    return display.enabled, strip_moment_markers(text), moments


def _persist_changed_composition(database, arc_id, user_id, composed, rows):
    """The refreshed paragraphs carry SERVER-minted ids; they must be stable
    across GETs, so a changed composition persists. Kept locks carry their
    ORIGINAL timestamps (a decision made before a lock and one after mean
    different things, §6)."""
    locked_at_by_id = {str(r.get("id")): r.get("locked_at")
                       for r in (rows or []) if isinstance(r, dict)}
    rows_out = [{**p, "locked_at": locked_at_by_id.get(p["id"])
                 if not p.get("locked") else
                 (locked_at_by_id.get(p["id"])
                  or datetime.now(timezone.utc).isoformat())}
                for p in composed["parts"]]
    if not database.replace_ideal_text_parts(arc_id, user_id, rows_out):
        logger.warning("compose: parts not persisted arc=%s", arc_id)


def _pinned_after_failure(arc_id, rows, error, degradation):
    """§12.1 (founder 2026-08-14): a rebuild that cannot place the locks is
    a FAILED rebuild — the previous composed state serves instead of the raw
    machine text (field report #5)."""
    logger.error(
        "compose failed arc=%s: %s — serving the pinned stored "
        "composition (§12.1 failed-rebuild rule)", arc_id, error)
    degradation.record("compose", error)
    try:
        from services.ideal_text_parts import pinned_parts
        return pinned_parts(rows)
    except Exception as pin_error:
        logger.error(
            "compose pin fallback ALSO failed arc=%s: %s — locks "
            "will be invisible this read", arc_id, pin_error)
        degradation.record("compose_pin", pin_error)
        return None


def _compose_locked(database, arc_id, user_id, text, degradation):
    """(text, composed). PER-PART PERSISTENCE (founder 2026-08-10): locked
    paragraphs keep their typed words verbatim, unlocked ones refresh to the
    machine's current text. Runs after fold/sanitize/strip, because the
    stored parts were split by the client from exactly this final form."""
    rows = None
    try:
        from services.ideal_text_parts import compose_locked
        rows = database.get_ideal_text_parts(arc_id, user_id, with_lock=True)
        composed = compose_locked(text, rows)
        if composed is not None:
            from services.ideal_text_quality_gate import validate_composed_text
            quality = validate_composed_text(composed.get("text"), rows)
            if not quality["ok"]:
                from services.ideal_text_parts import pinned_parts
                logger.warning(
                    "compose quality gate rejected arc=%s reasons=%s",
                    arc_id, quality["reasons"])
                composed = pinned_parts(rows)
        if composed is not None:
            text = composed["text"]
            if composed.get("changed"):
                _persist_changed_composition(
                    database, arc_id, user_id, composed, rows)
    except Exception as error:
        composed = _pinned_after_failure(arc_id, rows, error, degradation)
        if composed is not None:
            text = composed["text"]
    return text, composed


def _review_status(owner, coach, rereview_of) -> Optional[str]:
    """One moment's visible review state, or None when nothing shows. A No
    is a resolved project decision: it never styles the text."""
    if owner != "yes":
        return "coach_reviewed" if coach == "yes" else None
    if coach == "yes":
        return "coach_reviewed"
    if coach != "no":
        return "pending_coach_review"
    rereview = rereview_of()
    return ("not_confirmed"
            if isinstance(rereview, dict)
            and rereview.get("status") == "confirmed_no"
            else "pending_coach_review")


def _labels_for(database, snippet_ids) -> dict:
    try:
        return database.get_confidence_labels_by_snippet_ids(snippet_ids) or {}
    except Exception:
        return {}


def confidence_review_status_map(database, arc_id, moments) -> dict:
    """Visible workflow state for owner-routed Confident Voice moments.

    This is deliberately a *presentation* join, not another source of truth:
    the owner's response remains in the routing table and the coach's blind
    judgement remains in the ratings table. They are only combined here so
    the student can see whether a review is pending or complete without
    either signal being copied into the other's corpus (L3).
    """
    try:
        routes = database.list_owner_voice_album_routes(str(arc_id)) or []
    except Exception:
        return {}
    owner_by_snippet = {
        str(row.get("snippet_id")): row.get("response")
        for row in routes if isinstance(row, dict) and row.get("snippet_id")
    }
    snippet_ids = [
        str(moment.get("snippet_id")) for moment in (moments or [])
        if isinstance(moment, dict)
        and str(moment.get("snippet_id") or "") in owner_by_snippet
    ]
    if not snippet_ids:
        return {}
    labels = _labels_for(database, snippet_ids)

    def rereview_of(snippet_id):
        try:
            return database.get_confidence_rereview(snippet_id)
        except Exception:
            return None

    from services.professional_confidence import latest_professional_value
    result = {}
    for snippet_id in snippet_ids:
        status = _review_status(
            owner_by_snippet.get(snippet_id),
            latest_professional_value(labels.get(snippet_id)),
            lambda sid=snippet_id: rereview_of(sid))
        if status is not None:
            result[snippet_id] = status
    return result


def _key_moments(database, arc_id, moments, stars_on, deps, optional):
    """(key_moments, explanations). Every attached post resolves ONCE per
    request (Ticket 6); the map's values are dicts in production, but a
    truthy marker must not take the response down (isinstance-guarded)."""
    take_ids = [m.get("take_session_id") for m in moments]
    explanations = optional(
        "moment_explanations", {}, lambda: deps.explanations_map(take_ids))
    playback = optional(
        "moment_playback", {}, lambda: deps.playback_map(take_ids))
    review_status = optional(
        "confidence_review_status", {},
        lambda: confidence_review_status_map(database, arc_id, moments))
    references = optional(
        "moment_references", {},
        lambda: deps.reference_map([
            v.get("reference_post_slug") if isinstance(v, dict) else None
            for v in explanations.values()
        ]))
    return decorate_key_moments(
        moments, suggestions_enabled=stars_on, explanations=explanations,
        playback=playback, review_status=review_status, references=references,
    ), explanations


def _learning_exposure(database, *, arc_id, user_id, spoken_rows,
                       latest_take_sid, text, version, title, composed,
                       degradation):
    """DATA FOUNDATION — preparing this actor-specific document packet is NOT
    an exposure. The client receives a one-time handle and creates the
    receipt only after the Ideal Text itself has visibly painted. Older rows
    degrade by omitting the handle; they never counterfeit exposure data."""
    latest = next((
        session for session in reversed(spoken_rows)
        if str(session.get("id") or "") == str(latest_take_sid or "")
    ), None)
    if not isinstance(latest, dict):
        return None
    try:
        from services.learning_exposures import prepare_ideal_text_presentation
        owner_principal_id = str(latest.get("owner_principal_id") or "")
        project_id = str(latest.get("project_id") or arc_id or "")
        if not (owner_principal_id and project_id):
            return None
        return prepare_ideal_text_presentation(
            database=database, owner_principal_id=owner_principal_id,
            project_id=project_id, take_id=str(latest_take_sid),
            actor_id=str(user_id), text=text, version=version,
            take_count=len(spoken_rows), title=title,
            parts=(composed.get("parts") if isinstance(composed, dict) else None),
            delivery_mode="canary",
        )
    except Exception as error:
        logger.warning(
            "ideal-text presentation not prepared arc=%s take=%s: %s",
            arc_id, latest_take_sid, error)
        degradation.record("learning_exposure", error)
        return None


def _project_fields(database, arc_id, user_id, sessions, deps, optional):
    """The crucial-bubble fields (founder 2026-07-20) and the notebook's
    optional neighbours, derived from the ownership read with zero extra
    session queries. The read/spoken SPLIT stays: a read row is never a
    take."""
    from services.journey_messages import journey_seen
    project = resolve_project_read(
        sessions, completed_spoken=deps.completed_spoken)
    spoken_rows = project.spoken_rows
    return project, {
        "notes": optional(
            "owner_notes", None,
            lambda: database.get_user_arc_ideal_notes(arc_id, user_id)),
        "journey_seen": optional(
            "journey_state", False,
            lambda: journey_seen(database, user_id, arc_id, len(spoken_rows))),
        "decision_history": optional(
            "decision_history", [],
            lambda: database.list_intervention_decision_history(arc_id)),
        "moments_unlocked": optional(
            "moment_entitlement", False, lambda: deps.moments_entitled(arc_id)),
        "price": optional(
            "moment_price", 0, lambda: _price_of("moment_explanation")),
    }


def _pieces_and_parts(database, arc_id, text, project, composed, user_id,
                      deps, degradation) -> tuple[list, dict]:
    """(pieces, parts block): the pieces, then, without a composition, the
    parts block."""
    pieces = ideal_text_pieces(database, arc_id, text, project.presentation_ref,
                               str(user_id), degradation=degradation)
    parts = ({"parts": composed["parts"]} if composed is not None
             else deps.parts_block(arc_id, user_id, text))
    return pieces, parts


def _payload(*, arc_id, version, live, row, project, extra, text, exposure,
             composed, key_moments, explanations, pieces, parts, changes,
             degradation) -> dict:
    """The notebook as served, with the `degraded` list last."""
    spoken_rows = project.spoken_rows
    presentation_ref = refreshed_media_url(project.presentation_ref or None)
    notes = extra["notes"]
    return {
        "arc_id": arc_id,
        "version": version,
        "status": live.status,
        "title": project.title,
        "updated_at": row.get("updated_at"),
        "latest_take_session_id": project.latest_take_session_id,
        # The project's OFFICIAL-TAKE count (founder 2026-07-23), per project.
        "take_count": len(spoken_rows),
        # IMMEDIATE next-take affordance (founder 2026-07-24, T1 · 1.2).
        "can_record_take": project.can_record_take,
        "journey_next_steps_seen": extra["journey_seen"],
        "text": text,
        **({"learning_exposure": exposure} if exposure else {}),
        # The arc's served deck PDF (FE handoff 2026-08-03); null when none.
        "presentation_ref": presentation_ref,
        # Slide titles by slide index — what the AUDIENCE saw.
        "slide_titles": project.slide_titles,
        # One entry per "\n\n"-paragraph of `text`, with its provable slide.
        "pieces": pieces,
        # PARTS (SPEC-parts-locking-and-layers §3.1): ABSENT, not [], when
        # this document has no parts that still join to the served text.
        **parts,
        # Under COMPOSE the document is canonical, so the whole-document
        # edit label stops applying.
        "user_edited": False if composed is not None else live.user_edited,
        # The retained edit a NEWER version superseded (founder 2026-07-28),
        # served on the legacy lane (no locked parts) only.
        **({"prior_edit": live.prior_edit}
           if live.prior_edit and composed is None else {}),
        "key_moments": key_moments,
        "moments_unlocked": extra["moments_unlocked"],
        # The unlock CTA shows ONLY when a coach explanation exists.
        "explanations_available": bool(explanations),
        # LIVING TRANSCRIPT (founder 2026-07-20, flag-gated); absent when
        # off. The user id is the CONTROL-ARM KEY; the take id keys the arms.
        **changes,
        # PROPOSAL HISTORY (slice 2, founder 2026-08-11), newest first.
        "decision_history": extra["decision_history"],
        # The moments-unlock price, in TOKENS.
        "price_tokens": extra["price"],
        # The personal notebook copy — free with the text now.
        "notes_text": notes, "notes": notes, "user_notes": notes,
        # Every optional stage that fell back on this read (audit Q-C1).
        **degradation.payload(),
    }


def build_notebook(database, *, arc_id: str, user_id: Any, sessions: list,
                   requested_version: Optional[str],
                   deps: NotebookDeps) -> tuple[dict, int]:
    """(payload, status) for the owner's notebook. Free in both states —
    never a 402 (single deliverable, founder 2026-07-17)."""
    from services.degradation import DegradationLog
    from services.parallel import run_in_parallel

    row = database.ideal_text.get_coach_arc_ideal_text(arc_id)
    source = resolve_ideal_text_source(row)
    # HISTORICAL view, ?version=N (founder 2026-07-20): read-only, owner-only.
    historical = resolve_historical_read(
        arc_id, requested_version, source.version, database=database)
    if historical is not None:
        return historical.payload, historical.status

    # INDEPENDENT STAGES RUN TOGETHER (2026-10-18: this read took 4.7 s, 49
    # database calls one after another). Two waves: the document and the
    # project fields, then everything that needs the composed text. Each
    # stage keeps its own log, merged in the order the stages used to run,
    # so `degraded` reads exactly as it did.
    def stage_log():
        log = DegradationLog("ideal_text")
        return log, lambda label, default, reader: optional_read(
            label, default, reader, log)

    document_log, document_optional = stage_log()
    project_log, project_optional = stage_log()

    def document():
        # The student's in-place edit WINS display while it was made against
        # the CURRENT version (BE-2); `prior_edit` re-offers a superseded one.
        live = resolve_live_text(arc_id, user_id, source, database=database)
        stars_on, text, moments = _displayed_text(
            database, arc_id, live.text, live.user_edited, deps,
            document_optional)
        text, composed = _compose_locked(
            database, arc_id, str(user_id), text, document_log)
        return live, stars_on, text, moments, composed

    (live, stars_on, text, moments, composed), (project, extra) = run_in_parallel(
        document,
        lambda: _project_fields(
            database, arc_id, user_id, sessions, deps, project_optional))

    moments_log, moments_optional = stage_log()
    exposure_log, pieces_log, changes_log = (
        DegradationLog("ideal_text") for _ in range(3))
    (key_moments, explanations), exposure, (pieces, parts), changes = (
        run_in_parallel(
            lambda: _key_moments(
                database, arc_id, moments, stars_on, deps, moments_optional),
            lambda: _learning_exposure(
                database, arc_id=arc_id, user_id=user_id,
                spoken_rows=project.spoken_rows,
                latest_take_sid=project.latest_take_session_id, text=text,
                version=source.version, title=project.title,
                composed=composed, degradation=exposure_log),
            lambda: _pieces_and_parts(
                database, arc_id, text, project, composed, user_id, deps,
                pieces_log),
            lambda: deps.tracked_changes_block(
                arc_id, text, user_id or "",
                project.latest_take_session_id or "",
                review_version=source.version, degradation=changes_log)))

    degradation = DegradationLog("ideal_text")
    for log in (document_log, moments_log, project_log, exposure_log,
                pieces_log, changes_log):
        degradation.items.extend(log.items)
    return _payload(
        arc_id=arc_id, version=source.version, live=live, row=source.row,
        project=project, extra=extra, text=text, exposure=exposure,
        composed=composed, key_moments=key_moments, explanations=explanations,
        pieces=pieces, parts=parts, changes=changes,
        degradation=degradation), 200
