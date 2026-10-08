"""The ONE-BLOCK IDEAL TEXT surface: the student read, the block/prior-take
decisions, revisions, the save + user-edit lanes, and the tracked-changes
block that renders what moved between takes.

This is the F1 deliverable's read surface -- the assembled best-per-slide
text the learner actually sees. Assembly and ranking themselves live in
services/ (ideal_text_block, best_presentation, cross_take_selection); these
routes serve, gate and record decisions against it.

Moved verbatim out of ``routes/v2_routes.py`` (god-file split, phase 4);
bodies are byte-identical. Routes register on the SAME ``v2_bp`` object, so
endpoint names and the URL map are unchanged.

Depends one-way on routes/v2/arcs.py (arc ownership + the moment maps) --
never the reverse.

Re-exported from ``routes.v2_routes`` for import compatibility.
"""
import logging
import re
import uuid
from datetime import datetime, timezone

import sentry_sdk
from flask import jsonify, request

from auth import require_auth
from routes.v2.guest_owner import require_owner_or_guest
from config import Config
from routes.v2.arcs import (
    _arc_owned_by_caller,
    _fold_applied_moments,
    _moment_applied_map,
    _moment_explanations_map,
    _moment_playback_map,
    _moment_reference_map,
    _moment_suggestions_enabled,
    _moments_entitled,
    _reassemble_after_decision,
)
from routes.v2.blueprint import v2_bp
from services.db import db, first_client_repository
from services.ideal_text_read import (
    decorate_key_moments,
    resolve_historical_read,
    resolve_live_text,
    resolve_ideal_text_source,
    resolve_project_read,
    resolve_suggestion_display,
)
from services.rate_limits import llm_limit
from services.token_prices import price_of as _price_of
from services.coach_video_storage import refreshed_media_url
from services.intervention_spend import (
    latest_spoken_take_sid as _latest_take_sid,
)
from services.recording_roots import (
    RecordingRootsStale,
    project_recording_roots,
)
from services.ideal_text_feedback_bake import request_rebake_after_answer
from services.paragraph_history import history_for_part
from services.slide_helper_words import (
    merge_recording_roots,
    record_lock,
    record_pick,
    slide_roots,
)

logger = logging.getLogger(__name__)
config = Config()


def _publish_ideal_text_core(arc_id, actor_id=None) -> None:
    """Publish the immutable cold-open read model after a product write."""
    try:
        from services.ideal_text_core_snapshot import publish_for_arc
        publish_for_arc(db, str(arc_id), str(actor_id) if actor_id else None)
    except Exception as error:
        logger.warning("ideal-text core publication failed arc=%s: %s",
                       arc_id, error)


def _ideal_optional_read(label, default, reader, degradation=None):
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


_CONFIDENT_MOMENT_INELIGIBLE_CODES = {
    "MLC3_ROLLOUT_NOT_ACTIVE",
    "MLC3_CURRENT_ENROLLMENT_REQUIRED",
    "MLC3_COHORT_MEMBERSHIP_REQUIRED",
    "MLC3_ENROLLMENT_AUTHORITY_STALE",
    "MLC3_DUAL_PURPOSE_AUTHORITY_REQUIRED",
    "MLC3_ROLLOUT_POLICY_AUTHORITY_MISMATCH",
}


def _confident_moment_error_code(error):
    match = re.search(
        r"\b(CONFIDENT_MOMENT_[A-Z0-9_]+|FEEDBACK_LANGUAGE_[A-Z0-9_]+|MLC3_[A-Z0-9_]+)\b",
        str(error),
    )
    return match.group(1) if match else "CONFIDENT_MOMENT_DATABASE_FAILURE"


def _completed_spoken_sessions(sessions):
    """Official takes whose processing completed successfully.

    Legacy synchronous rows predate ``analysis_state`` and therefore count as
    ready. Pending and failed submissions remain resumable recordings, but
    must not advance the guided journey or its take number.
    """
    return [
        row for row in (sessions or [])
        if row.get("recording_kind") != "read"
        and not row.get("paired_session_id")
        and row.get("analysis_state") in (None, "ready")
    ]


def _confidence_review_status_map(arc_id, moments):
    """Visible workflow state for owner-routed Confident Voice moments.

    This is deliberately a *presentation* join, not another source of truth:
    the owner's response remains in the routing table and the coach's blind
    judgement remains in the ratings table.  We only combine them here so the
    student can see whether a review is pending or complete without either
    signal being copied into the other's corpus.
    """
    try:
        routes = db.list_owner_voice_album_routes(str(arc_id)) or []
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
    try:
        labels = db.get_confidence_labels_by_snippet_ids(snippet_ids) or {}
    except Exception:
        labels = {}

    from services.professional_confidence import latest_professional_value
    result = {}
    for snippet_id in snippet_ids:
        owner = owner_by_snippet.get(snippet_id)
        coach = latest_professional_value(labels.get(snippet_id))

        # A No is a resolved project decision: it never styles the text.  The
        # later Voice Album disagreement exercise is intentionally separate.
        if owner != "yes":
            if coach == "yes":
                result[snippet_id] = "coach_reviewed"
            continue
        if coach == "yes":
            result[snippet_id] = "coach_reviewed"
            continue
        if coach != "no":
            result[snippet_id] = "pending_coach_review"
            continue
        try:
            rereview = db.get_confidence_rereview(snippet_id)
        except Exception:
            rereview = None
        result[snippet_id] = (
            "not_confirmed"
            if isinstance(rereview, dict)
            and rereview.get("status") == "confirmed_no"
            else "pending_coach_review"
        )
    return result


# The /talks/<talk_id>/ideal-text route (Paid Audits A7) was DELETED here
# (founder 2026-08-10: "older feedback system should be ripped off"). It had
# no FE caller and no BFF proxy — the audits product it served is retired,
# and the explore GET below is the one ideal-text read. Its builder
# (services/ideal_text_report.py) is removed too (N48.3 Q13 A).


def _instant_ideal_enabled() -> bool:
    """Instant ideal text (founder re-lock 2026-07-17): the MACHINE draft is
    served to the student FREE the moment take 3 lands — the June "the raw
    auto-assembled draft must NEVER reach the student" gate is explicitly
    reversed for this labeled instant lane. The coach-perfected text + takes
    2/3 feedback stay behind approval + the $25 unlock. DEFAULT OFF until the
    FE ships variant handling (deploy order: BE → FE → flip
    INSTANT_IDEAL_TEXT_ENABLED=1 in Railway)."""
    return bool(config.INSTANT_IDEAL_TEXT_ENABLED)


def _snip_slide(snip):
    # The cutter's own bucket (the slide on screen when the words
    # were spoken).
    m = (snip or {}).get("metrics")
    piece = m.get("piece") if isinstance(m, dict) else None
    si = piece.get("slide_index") if isinstance(piece, dict) else None
    return si if isinstance(si, int) and not isinstance(si, bool) \
        else None


def _ideal_piece_provenance_from_stored_paragraphs(_stored_paragraphs, _same_body):
    if not (_stored_paragraphs and _same_body):
        return None
    return [{
        "slide_index": p.get("slide_index"),
        "snippet_id": p.get("snippet_id"),
        "take_session_id": p.get("take_session_id"),
        "take_index": p.get("take_index"),
        "status": "settled",
        "challenger": None,
    } for p in _stored_paragraphs if isinstance(p, dict)]


def _ideal_piece_provenance_from_relocated_pieces(
    _stored_pieces, _same_body, served_text,
):
    if not (_stored_pieces and _same_body
            and isinstance(served_text, str) and served_text):
        return None
    from services.transcript_document import (
        paragraph_spans, relocate_pieces,
    )
    _located = relocate_pieces(
        served_text, _stored_pieces, paragraph_fallback=True)
    _derived = []
    for _lo, _hi in paragraph_spans(served_text):
        _piece = next((p for p in _located
                       if isinstance(p.get("start"), int)
                       and isinstance(p.get("end"), int)
                       and p["start"] < _hi
                       and p["end"] > _lo), None)
        if _piece is None:
            _derived = []
            break
        _derived.append({
            "slide_index": _piece.get("slide_index"),
            "snippet_id": _piece.get("snippet_id"),
            "take_session_id": _piece.get("take_session_id"),
            "take_index": _piece.get("take_index"),
            "status": "settled",
            "challenger": None,
        })
    return _derived or None


def _ideal_piece_provenance_by_slot(_stored_paragraphs, served_text):
    """Slot-for-slot Slide lineage when the words changed but the shape did
    not (founder 2026-09-28: "the text was not assigned to the slides ... it
    was all concatenated").

    The same proof the immutable snapshot already accepts
    (`ideal_text_core_snapshot._exact_pieces`, compatibility adoption): the
    edit surfaces rewrite Paragraph slots in place and cannot insert, delete,
    split, merge or reorder them, so on an equal Paragraph count slot N is
    still the Slide-bounded Paragraph N. Without this, any difference between
    the served words and the stored Take-1 body -- a later Take's rewrite, a
    folded suggestion -- threw every Slide away and the deck rendered one
    untitled section. A changed count still proves nothing and returns None."""
    if not (_stored_paragraphs and isinstance(served_text, str)
            and served_text.strip()):
        return None
    served = [p for p in served_text.split("\n\n") if p.strip()]
    rows = [p for p in _stored_paragraphs if isinstance(p, dict)]
    if len(rows) != len(_stored_paragraphs) or len(rows) != len(served):
        return None
    return _ideal_piece_provenance_from_stored_paragraphs(rows, True)


def _ideal_piece_provenance_canonical(arc_id, served_text):
    # CANONICAL SOURCE FIRST. Take 1's document provenance is persisted in
    # the same database write as its text. Later Takes advance the REVIEW
    # version without replacing those words, so rebuilding provenance from
    # the latest transcript describes a different document. That mismatch
    # is what made the FE reject the whole Ideal Text after Take 2.
    try:
        _ideal_row = db.ideal_text.get_coach_arc_ideal_text(arc_id) or {}
        _stored_doc = _ideal_row.get("document") or {}
        _stored_paragraphs = _stored_doc.get("paragraphs") or []
        _canonical_body = str(
            _ideal_row.get("auto_text") or _ideal_row.get("text") or "")
        try:
            from services.ideal_text_block import (
                sanitize_markers, strip_moment_markers,
            )
            _canonical_body = sanitize_markers(
                strip_moment_markers(_canonical_body))
        except Exception:
            _canonical_body = _canonical_body.strip()
        _same_body = (
            not isinstance(served_text, str)
            or not served_text
            or served_text.strip() == _canonical_body.strip()
        )
        exact = _ideal_piece_provenance_from_stored_paragraphs(
            _stored_paragraphs, _same_body)
        if exact is not None:
            return exact
        # Compatibility for canonical rows persisted between the document
        # column migration and this paragraph-grain fix. They have exact
        # canonical snippet pieces but no paragraph list. Re-anchor those
        # pieces to the currently served body, then derive one provenance
        # row per actual paragraph. Every paragraph must be covered; a
        # partial map falls through to the unlinked compatibility path.
        _stored_pieces = _stored_doc.get("pieces") or []
        relocated = _ideal_piece_provenance_from_relocated_pieces(
            _stored_pieces, _same_body, served_text)
        if relocated:
            return relocated
        adopted = _ideal_piece_provenance_by_slot(
            _stored_paragraphs, served_text)
        if adopted is not None:
            return adopted
    except Exception as _stored_doc_err:
        logger.warning(
            "stored ideal-text provenance failed arc=%s: %s",
            arc_id, _stored_doc_err)
    return None


def _ideal_piece_provenance_compat(arc_id):
    from services.transcript_document import build_transcript_document
    doc = build_transcript_document(arc_id, database=db)
    # ONE ROW PER PARAGRAPH (founder 2026-08-11). The consumer aligns
    # this list against the served text's "\n\n" paragraphs by LENGTH,
    # and `pieces` is per SNIPPET — so on any take where a slide held
    # more than one piece the counts disagreed, the alignment test
    # failed, and every slide attachment was dropped. `paragraphs` is
    # cut the same way the text is, by construction.
    rows = (doc or {}).get("paragraphs") or []
    if not rows:
        return []
    sid = doc.get("take_session_id")
    snips = {str(s.get("id")): s
             for s in (db.get_snippets_by_session(sid) or [])} \
        if sid else {}
    return [{
        # The document already resolved this (coach correction first,
        # then the cutter's bucket); `_snip_slide` stays as the floor
        # for a row that predates the field.
        "slide_index": (
            p.get("slide_index")
            if isinstance(p.get("slide_index"), int)
            and not isinstance(p.get("slide_index"), bool)
            else _snip_slide(snips.get(str(p.get("snippet_id"))))
        ),
        "snippet_id": p.get("snippet_id"),
        "take_session_id": p.get("take_session_id"),
        "take_index": p.get("take_index"),
        "status": "settled",
        "challenger": None,
    } for p in rows]


def _ideal_piece_provenance_legacy_cache(arc_id):
    from services.ideal_text_block import _polish_as_suggestions_enabled
    _get_cache = getattr(db, "get_best_presentation_cache", None)
    cached = _get_cache(arc_id) if callable(_get_cache) else None
    slides = ((cached or {}).get("payload") or {}).get("slides") or []
    _polish_on = _polish_as_suggestions_enabled()
    out = []
    for s in slides:
        if not isinstance(s, dict):
            continue
        _edited = (s.get("text") or "").strip()
        _verbatim = (s.get("verbatim") or "").strip()
        # Mirror the (removed, N48.3 Q13 A) best-of assembly's paragraph
        # filter exactly — a pick it skipped must not shift the alignment
        # of a document it built.
        if not ((_verbatim if _polish_on else _edited) or _edited):
            continue
        out.append({
            "slide_index": s.get("index"),
            "snippet_id": s.get("snippet_id"),
            "take_session_id": s.get("session_id"),
            "take_index": s.get("take_index"),
            "status": "settled",
            "challenger": None,
        })
    return out


def _ideal_piece_provenance(arc_id, deckless_ok=True, served_text=None):
    """``(lane, rows)``: the machine assembly's per-piece slide identity, in
    served order, and which lane produced it — mirrors
    mirrors maybe_assemble_ideal_text's source choice WITHOUT re-running
    any composition on the student GET:

      * living transcript: the take's pieces, slide from the cutter's
        metrics.piece.slide_index bucket;
      * legacy: the persisted best-presentation compose cache — the very
        picks auto_text's paragraphs were joined from. No cache row →
        no attachment; the composer (its LLM pass included) NEVER runs
        on this GET.

    ONE ENTRY PER SERVED PARAGRAPH, because that is what the caller aligns
    it against. `deckless_ok` gates the LEGACY lane only — see the comment
    at that branch.

    Each entry: {slide_index, snippet_id, take_session_id, take_index,
    status, challenger}. Best-effort; [] when nothing is provable.

    ``lane`` is one of canonical / compat / legacy_cache / deckless, so a
    misaligned read can say which source it came from (audit A3). The
    master-document skeleton lane is retired (audit C2)."""
    from services.ideal_text_block import _living_transcript_enabled

    if _living_transcript_enabled():
        canonical = _ideal_piece_provenance_canonical(arc_id, served_text)
        # `is not None`, not truthiness: stored paragraphs that yield no rows
        # are still the canonical answer, never a cue to rebuild provenance
        # from the latest transcript.
        if canonical is not None:
            return "canonical", canonical
        # Compatibility only: rows created before document provenance was
        # added have no canonical map. The latest transcript remains the best
        # available structural source, but the FE now treats any mismatch as
        # optional metadata failure and still renders the text unlinked.
        return "compat", _ideal_piece_provenance_compat(arc_id)
    # LEGACY compose cache — and the ONLY lane the deckless guard belongs
    # to. This one keys its picks by SECTION index, which is not a deck page,
    # so without an uploaded deck it must not attach. The living-transcript
    # lanes above read the CUTTER's own bucket (the slide that was on screen when the
    # words were spoken), which is a real page whether or not a PDF was ever
    # uploaded — and applying the guard to every lane is what made the
    # built-in mock deck attach nothing at all (founder 2026-08-11).
    if not deckless_ok:
        return "deckless", []
    return "legacy_cache", _ideal_piece_provenance_legacy_cache(arc_id)


def _report_misaligned_pieces(arc_id, lane, prov, paragraphs, degradation):
    """Say so when provenance exists but does not line up with the served
    paragraphs, because every slide link on the read then becomes null
    (audit A3). The log line names the lane; the payload's ``degraded``
    list names the stage, so the FE can tell a shorter read for what it
    is. Nothing to say when there is no provenance at all."""
    if not prov or len(prov) == len(paragraphs):
        return
    logger.warning(
        "ideal-text pieces misaligned arc=%s lane=%s provenance=%d "
        "paragraphs=%d", arc_id, lane, len(prov), len(paragraphs))
    if degradation is not None:
        degradation.note("pieces", "misaligned")


def _ideal_text_pieces(arc_id, served_text, presentation_ref, user_id=None,
                       degradation=None):
    """The slide-linkage `pieces[]` of the SD student GET (FE handoff
    2026-08-03, FE PR #222): one entry per "\\n\\n"-paragraph of the
    SERVED text, each carrying the deck page its words were bucketed to.

    `slide_index` attaches ONLY when the mapping is structural — the
    machine assembly's piece list lines up 1:1 with the served
    paragraphs (the FE's own provability bar: it zips or hides on
    anything weaker). A reshaped text (user rewrite, coach restructure,
    stale cache) misaligns the counts and every slide_index degrades to
    null — the FE falls back to its exact-count zip, never a guessed
    attachment. An arc with no UPLOADED deck still attaches when the cutter
    bucketed its words against slides the speaker actually saw (the built-in
    deck); only the legacy compose lane, which keys picks by SECTION index
    rather than a deck page, stays deckless-gated — applying that guard to
    every lane is what made the mock deck attach nothing (founder
    2026-08-11). Provenance only, no scores (AC-9). Best-effort; []."""
    try:
        paragraphs = [p.strip() for p in (served_text or "").split("\n\n")
                      if p.strip()]
        if not paragraphs:
            return []
        # The deckless guard is passed DOWN rather than applied here, so it
        # lands on the one lane whose slide identity is not a deck page.
        lane, prov = _ideal_piece_provenance(
            arc_id,
            deckless_ok=bool(presentation_ref),
            served_text=served_text,
        )
        _report_misaligned_pieces(arc_id, lane, prov, paragraphs, degradation)
        aligned = bool(prov) and len(prov) == len(paragraphs)
        _part_roots: dict[int, dict] = {}
        if user_id:
            try:
                from services.ideal_text_parts import agrees_with_text, serve
                _served_parts = serve(db.get_ideal_text_parts(
                    arc_id, str(user_id), with_lock=True)) or []
                if (len(_served_parts) == len(paragraphs)
                        and agrees_with_text(_served_parts, served_text)):
                    _part_roots = {i: part for i, part in
                                   enumerate(_served_parts)}
            except Exception:
                _part_roots = {}
        out = []
        for i, para in enumerate(paragraphs):
            src = prov[i] if aligned else {}
            _part = _part_roots.get(i) or {}
            _metadata_root = _part.get("root_phrase")
            # The API serves only explicit, locked orange roots. A generated
            # first-words fallback is not a user decision and must not become
            # a prompt in the next Take or in Presentation Mode.
            root = ({"text": _metadata_root, "type": "flagship"}
                    if isinstance(_metadata_root, str) and _metadata_root
                    else {"text": None, "type": None})
            si = src.get("slide_index")
            if isinstance(si, bool) or not isinstance(si, int) or si < 0:
                si = None
            _snip = src.get("snippet_id")
            _sess = src.get("take_session_id")
            _bk = src.get("block_key")
            out.append({
                "piece_key": i,
                "text": para,
                "root_phrase": root["text"],
                "root_type": root["type"],
                "slide_index": si,
                "block_key": (_bk if isinstance(_bk, int)
                              and not isinstance(_bk, bool) else None),
                "snippet_id": str(_snip) if _snip else None,
                "take_session_id": str(_sess) if _sess else None,
                "take_index": src.get("take_index"),
                "status": src.get("status") or "settled",
                "challenger": src.get("challenger"),
            })
        return out
    except Exception as e:
        logger.warning("ideal-text pieces failed arc=%s: %s", arc_id, e)
        return []


@v2_bp.route("/explore/arc/<arc_id>/ideal-text/core", methods=["GET"])
@require_owner_or_guest
def v2_explore_get_ideal_text_core(arc_id):
    """Strict, read-only cold-open document.

    This endpoint reads one immutable prepared snapshot.  It does not compose,
    persist, aggregate feedback or prepare analytics.

    ONE REPAIR, WHEN THERE IS NO HEAD AT ALL (founder 2026-09-28, 16A): the
    owner's open asks the ordinary publisher for one -- see
    ``ideal_text_core_snapshot.read_core_or_publish``.  An existing head is only ever read.

    IT DOES RE-ADDRESS THE DECK (2026-09-19, founder: "no slide preview" /
    "it was visible for a moment but then gone").  ``publish_for_arc`` bakes
    ``project.presentation_ref`` into the snapshot as the URL stored at
    upload, and a snapshot is immutable by design -- so whatever address was
    current at publish time is served forever.  Since decks became user
    content (DPIA RISK-11, 2026-09-18) that address is a SIGNATURE, and
    ``refreshed_media_url`` exists precisely because "nothing depends on a
    stored URL staying valid".  Every other read of ``presentation_ref``
    already calls it -- arcs, user_account, coach, and the composing ideal
    text read below.  This one did not, which is the whole defect: the FE's
    first load reads the composing lane and sees a signed deck, every poll
    after reads THIS lane and sees a dead one.

    Re-addressing is not composing.  The stored snapshot, its payload and its
    ``payload_sha256`` are untouched; only the way this response points at the
    same bytes is refreshed.  Nothing re-hashes the served body -- enrichment
    and recording-roots bind on the snapshot id.
    """
    from time import perf_counter
    started = perf_counter()
    from services.db import IdealTextCoreReadError
    try:
        from services.ideal_text_core_snapshot import read_core_or_publish
        core_read = read_core_or_publish(
            db, arc_id, str(request.user_id),
            is_owner=lambda: _arc_owned_by_caller(arc_id)[0])
    except IdealTextCoreReadError:
        # A FAILED read is not "no document yet" (founder 2026-09-26: a
        # dropped connection showed an existing Ideal Text as missing). 503
        # says try again; the client retries and falls back, and never
        # renders a pending screen for a document that exists.
        response = jsonify({
            "code": "IDEAL_TEXT_READ_FAILED",
            "retryable": True,
        })
        response.status_code = 503
        response.headers["Retry-After"] = "2"
        response.headers["Cache-Control"] = "private, no-store"
        return response
    if not core_read:
        response = jsonify({
            "code": "IDEAL_TEXT_DOCUMENT_PENDING",
            "state": "pending",
        })
        response.status_code = 404
    else:
        snapshot = core_read["snapshot"]
        overlay = core_read["dynamic_overlay"]
        payload = dict(snapshot.get("payload") or {})
        payload.update({
            "document_snapshot_id": str(snapshot.get("id")),
            "document_snapshot_sha256": snapshot.get("payload_sha256"),
            "owner_edit": overlay["owner_edit"],
            "confident_moment_summary": overlay["confident_moment_summary"],
            "confident_moment_summary_status": (
                overlay["confident_moment_summary_status"]
            ),
        })
        # A ref this cannot read with certainty comes back unchanged, and a
        # missing one stays missing -- so a deckless arc still reports no deck
        # rather than an address that resolves to nothing.
        payload["presentation_ref"] = refreshed_media_url(
            payload.get("presentation_ref")) or None
        response = jsonify(payload)
    elapsed = (perf_counter() - started) * 1000
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Server-Timing"] = f"ideal_core;dur={elapsed:.1f}"
    return response


@v2_bp.route("/explore/arc/<arc_id>/recording-roots", methods=["GET"])
@require_owner_or_guest
def v2_explore_get_recording_roots(arc_id):
    """Live committed roots, bound to the current immutable document.

    Root choice is product state, not document content and not an ML label.
    The immutable core owns exact Paragraph -> Slide lineage; current part rows
    own the latest lock/root choice.  The projection refuses any identity or
    content mismatch rather than guessing where a phrase belongs.
    """
    owned, _sessions = _arc_owned_by_caller(arc_id)
    if not owned:
        return jsonify({"code": "NOT_FOUND", "error": "arc not found"}), 404
    actor_id = str(request.user_id)
    snapshot = db.get_ideal_text_document_core(arc_id, actor_id)
    if not snapshot:
        return jsonify({
            "code": "IDEAL_TEXT_DOCUMENT_PENDING",
            "state": "pending",
        }), 404
    try:
        roots = project_recording_roots(
            snapshot,
            db.get_ideal_text_parts(arc_id, actor_id, with_lock=True),
        )
    except RecordingRootsStale as error:
        return jsonify({"code": str(error)}), 409
    roots = merge_recording_roots(roots, slide_roots(db, arc_id, actor_id))
    response = jsonify({
        "document_snapshot_id": str(snapshot.get("id")),
        "document_snapshot_sha256": snapshot.get("payload_sha256"),
        "roots": roots,
    })
    response.headers["Cache-Control"] = "private, no-store"
    return response


@v2_bp.route("/explore/arc/<arc_id>/ideal-text/enrichment", methods=["GET"])
@require_owner_or_guest
def v2_explore_get_ideal_text_enrichment(arc_id):
    """Optional sections bound to one immutable document snapshot."""
    from time import perf_counter
    from services.ideal_text_enrichment import (
        budget_for, run_sections)
    started = perf_counter()
    owned, sessions = _arc_owned_by_caller(arc_id)
    if not owned:
        return jsonify({"code": "NOT_FOUND", "error": "arc not found"}), 404
    snapshot_id = (request.args.get("document_snapshot_id") or "").strip()
    if not snapshot_id:
        return jsonify({"code": "SNAPSHOT_REQUIRED",
                        "error": "document_snapshot_id is required"}), 400
    # The generation-fenced core read treats a head invalidated by a source
    # mutation as stale immediately.  Reading the mutable head directly here
    # would let enrichment attach to an old document during republishing.
    current = db.get_ideal_text_document_core(
        arc_id, str(request.user_id))
    selected = db.get_ideal_text_document_snapshot(
        arc_id, str(request.user_id), snapshot_id)
    if not selected:
        return jsonify({"code": "SNAPSHOT_NOT_FOUND"}), 404
    if not current or str(current.get("id")) != str(selected.get("id")):
        return jsonify({
            "code": "SNAPSHOT_STALE",
            "current_document_snapshot_id": (
                str(current.get("id")) if current else None),
        }), 409

    allowed_sections = {
        "feedback", "document_layers", "notes", "history", "journey",
        "entitlement", "learning",
    }
    requested_raw = (request.args.get("sections") or "").strip()
    requested_sections = (
        {value.strip() for value in requested_raw.split(",") if value.strip()}
        if requested_raw else allowed_sections
    )
    invalid_sections = sorted(requested_sections - allowed_sections)
    if invalid_sections:
        return jsonify({
            "code": "INVALID_ENRICHMENT_SECTION",
            "sections": invalid_sections,
        }), 400

    actor_id = str(request.user_id)
    core = selected.get("payload") or {}
    seed = selected.get("enrichment_seed") or {}
    moments = seed.get("moments") if isinstance(seed, dict) else []
    moments = moments if isinstance(moments, list) else []
    take_ids = [moment.get("take_session_id") for moment in moments
                if isinstance(moment, dict)]

    def feedback_section():
        explanations = _ideal_optional_read(
            "moment_explanations", {},
            lambda: _moment_explanations_map(take_ids))
        playback = _ideal_optional_read(
            "moment_playback", {}, lambda: _moment_playback_map(take_ids))
        review = _ideal_optional_read(
            "confidence_review_status", {},
            lambda: _confidence_review_status_map(arc_id, moments))
        references = _ideal_optional_read(
            "moment_references", {},
            lambda: _moment_reference_map([
                value.get("reference_post_slug")
                if isinstance(value, dict) else None
                for value in explanations.values()
            ]))
        return {
            "key_moments": decorate_key_moments(
                moments,
                suggestions_enabled=bool(seed.get("suggestions_enabled")),
                explanations=explanations,
                playback=playback,
                review_status=review,
                references=references,
            ),
            "explanations_available": bool(explanations),
        }

    def document_layers_section():
        prior = seed.get("prior_edit") if isinstance(seed, dict) else None
        result = {"prior_edit": prior}
        # The publish-boundary bake when it is provably the same answer,
        # else computed live — see `services.ideal_text_feedback_bake`.
        from services.ideal_text_feedback_bake import changes_block_for
        result.update(changes_block_for(db, arc_id, actor_id, snapshot_id,
                                        core))
        return result

    def learning_section():
        latest_id = str(core.get("latest_take_session_id") or "")
        latest = next((row for row in sessions
                       if str(row.get("id") or "") == latest_id), None)
        if not isinstance(latest, dict):
            return {"learning_exposure": None}
        from services.learning_exposures import prepare_ideal_text_presentation
        handle = prepare_ideal_text_presentation(
            database=db,
            owner_principal_id=str(latest.get("owner_principal_id") or ""),
            project_id=str(latest.get("project_id") or arc_id),
            take_id=latest_id,
            actor_id=actor_id,
            text=str(core.get("text") or ""),
            version=core.get("version"),
            take_count=core.get("take_count"),
            title=core.get("title"),
            parts=core.get("parts"),
            delivery_mode="canary",
        )
        return {"learning_exposure": handle}

    def journey_section():
        from services.coach_message_read import journey_payload
        return journey_payload(db, actor_id, arc_id, take_count, sessions, core.get("latest_take_session_id"))

    take_count = int(core.get("take_count") or 0)
    readers = {
        "feedback": feedback_section,
        "document_layers": document_layers_section,
        "notes": lambda: {
            "notes_text": db.get_user_arc_ideal_notes(
                arc_id, actor_id)},
        "history": lambda: {
            "decision_history": db.list_intervention_decision_history(arc_id)},
        "journey": journey_section,
        "entitlement": lambda: {
            "moments_unlocked": _moments_entitled(arc_id),
            "price_tokens": _price_of("moment_explanation"),
        },
        "learning": learning_section,
    }
    # Budgets live with `run_sections`. The long one is earned by asking for
    # the SLOW section, not by naming any section at all.
    enrichment_timeout = budget_for(requested_sections)
    sections, timings = run_sections({
        name: reader for name, reader in readers.items()
        if name in requested_sections
    }, timeout_seconds=enrichment_timeout)
    # Optional readers run concurrently and can outlive the snapshot check at
    # the top of this request.  Re-read the generation-fenced core after every
    # reader has settled.  A source mutation during enrichment must return a
    # retryable stale response and, crucially, must never deliver a stale
    # presentation acknowledgement token to the browser.
    final_current = db.get_ideal_text_document_core(
        arc_id, str(request.user_id))
    if (not final_current
            or str(final_current.get("id")) != str(selected.get("id"))):
        return jsonify({
            "code": "SNAPSHOT_STALE",
            "current_document_snapshot_id": (
                str(final_current.get("id")) if final_current else None),
        }), 409
    elapsed = (perf_counter() - started) * 1000
    response = jsonify({
        "document_snapshot_id": snapshot_id,
        "sections": sections,
    })
    timing_parts = [f"ideal_enrichment;dur={elapsed:.1f}"]
    timing_parts.extend(
        f"section_{name};dur={duration:.1f}"
        for name, duration in sorted(timings.items()))
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Server-Timing"] = ", ".join(timing_parts)
    return response



@v2_bp.route("/explore/arc/<arc_id>/ideal-text", methods=["GET"])
@require_auth
def v2_explore_get_ideal_text(arc_id):
    """The user's ideal-text notebook (the purple bubble).

    Single-deliverable (founder 2026-07-17): the ideal text is FREE in both
    states — never a 402. Returns
    200 { arc_id, version, status:"verified"|"unverified", title,
          updated_at, latest_take_session_id, take_count,
          can_record_take, text, user_edited,
          prior_edit?, key_moments, moments_unlocked,
          explanations_available, price_credits,
          notes_text } — free in both states, never 402s. The
    crucial-bubble fields (founder 2026-07-20): `title` = latest take's
    topic.

    `take_count` (founder 2026-07-23) = the project's official-take count
    (per-arc). Since 2026-08-05 `version` IS this count — every take is
    its own version, and each one needs its own verification (founder:
    "each take is different and each should be verified"). The two used
    to differ, because `version` bumped only when the assembled text
    changed; a take that barely moved the text left the badge frozen.

    RETIRED 2026-08-05 — `reread_done` / `reread_processing` are gone
    with the read-out-loud lane. `can_record_take` (founder 2026-07-24,
    T1 · 1.2) is the signal for the "record another take" button: true
    the moment the project has a spoken take, so a finished recording
    returns the student straight to this screen ready to record again.
    `explanations_available`
    gates the unlock CTA (true only when a coach explanation exists);
    text-suggestion stars carry `quote` (the narrow underline span, or
    null = icon only).

    ?version=N (SD mode, founder 2026-07-20): the HISTORICAL read-only
    view of an old version — 200 { arc_id, version, historical:true,
    status:"superseded", current_version, created_at, text, key_moments }
    from the per-version snapshot; N == current serves the live notebook;
    no snapshot → 200 { historical_unavailable:true, requested_version,
    current_version } (the FE falls back to the live view).
    """
    try:
        owned, _sessions = _arc_owned_by_caller(arc_id)
        if not owned:
            return jsonify({"code": "NOT_FOUND", "error": "arc not found"}), 404
        # Every optional stage of this read either succeeds or is named in
        # the payload's `degraded` list (audit Q-C1, founder 2026-09-14):
        # the FE can show a shorter notebook for what it is, never a silent
        # one. Absent when nothing degraded.
        from services.degradation import DegradationLog
        _deg = DegradationLog("ideal_text")

        def _optional(label, default, reader):
            return _ideal_optional_read(label, default, reader, _deg)
        row = db.ideal_text.get_coach_arc_ideal_text(arc_id)

        # ── SINGLE DELIVERABLE (founder re-shape 2026-07-17): the ideal
        # text is FREE in both states — no 402 on this endpoint, ever. The
        # only paid thing in the app is the key-moment EXPLANATIONS
        # (GET /presentation/<id>/moments, 5 credits). ──
        _source = resolve_ideal_text_source(row)
        _r = _source.row
        _machine = _source.machine_text
        _version = _source.version

        # ── HISTORICAL view, ?version=N (founder 2026-07-20): an old
        # version bubble opens ITS OWN step — the frozen text + that
        # step's reasoning, read-only. N == current falls through to
        # the live notebook. No snapshot (pre-migration / assembled
        # before history existed) → historical_unavailable and the FE
        # falls back to the live view. Free, owner-only (same gate as
        # the live read). ──
        _historical = resolve_historical_read(
            arc_id,
            request.args.get("version"),
            _version,
            database=db,
        )
        if _historical is not None:
            return jsonify(_historical.payload), _historical.status
        # The student's in-place edit WINS display while it was made
        # against the CURRENT version (BE-2). A new take supersedes it —
        # the edit is retained (coach signal) but the fresh machine text
        # shows. `status` still reflects the coach's verification of the
        # version, independent of the student's own tweaks on top.
        _live = resolve_live_text(
            arc_id,
            request.user_id,
            _source,
            database=db,
        )
        _user_edited = _live.user_edited
        _text = _live.text
        # ── SUPERSEDED-EDIT RE-OFFER (founder 2026-07-28): when a newer
        # version has superseded the student's edit, serve the retained
        # copy as `prior_edit` so the FE can offer one-click "re-apply
        # your additions" across reload / device switch. The lane
        # semantics are UNCHANGED (the versioning change stays parked:
        # additions/moves never bake forward) — this only exposes the
        # already-retained row to its owner. Best-effort: absent on any
        # hiccup, never breaks the GET. Owner-keyed by the read above.
        _prior_edit = _live.prior_edit
        from services.ideal_text_block import extract_key_moments

        # ── Star suggestions (2026-07-18, flag-gated). Fold APPLIED
        # suggestions into the DISPLAYED text FIRST (unless the user's
        # free-form edit won — that wins wholesale), then extract the
        # anchors from the folded text so they always match what's
        # served. The canonical row is never touched (L1). ──
        _suggestion_display = _optional(
            "suggestion_display",
            None,
            lambda: resolve_suggestion_display(
                arc_id,
                _text,
                _user_edited,
                database=db,
                suggestions_enabled=_moment_suggestions_enabled,
                applied_lookup=_moment_applied_map,
                fold_applied=_fold_applied_moments,
            ),
        )
        if _suggestion_display is None:
            from services.ideal_text_read import SuggestionDisplayRead
            _suggestion_display = SuggestionDisplayRead(False, _text)
        _stars_on = _suggestion_display.enabled
        _text = _suggestion_display.text

        # Marker hygiene BEFORE the anchors are read (founder 2026-07-27):
        # a newline-straddling `{{orange:` is re-wrapped per line and any
        # unmatched token loses its braces, keeping every word. It runs
        # here — not at the jsonify — so `key_moments[].anchor` and the
        # tracked-change / key-point offsets below are all measured against
        # the very string the student is served.
        from services.ideal_text_block import sanitize_markers
        _text = sanitize_markers(_text)

        _moments = extract_key_moments(_text)
        # Serve the ANCHOR path, never both (audit 2026-07-18): the FE
        # drops any anchor sitting inside a marker token, which is
        # exactly where the [[moment:…]] wrapper puts it — with the
        # wrappers present every star is lost AND a free suggestion
        # falls through to the paid affordance. Extract first, then
        # strip, so each anchor is plain text in the served string.
        from services.ideal_text_block import strip_moment_markers
        _text = strip_moment_markers(_text)

        # ── PER-PART PERSISTENCE (founder 2026-08-10, the un-parked
        # versioning change). When the student has LOCKED parts, the served
        # document COMPOSES: locked paragraphs keep their typed words
        # verbatim, unlocked ones refresh to the machine's current text. The
        # version-gated whole-document edit swap — and the card that
        # apologised for it — stop applying on this lane.
        #
        # Placed HERE, after fold/sanitize/strip, because the stored parts
        # were split by the client from exactly this final form of the text;
        # composing against a pre-transform string could never match.
        # Everything downstream (key-moment anchors, pieces, the tracked-
        # changes gate) measures against the composed string, so anchors
        # into a locked paragraph's machine words simply fail to match and
        # drop — which IS the per-paragraph star fence, mechanically. ──
        _composed = None
        _p_rows = None
        try:
            from services.ideal_text_parts import compose_locked
            _p_rows = db.get_ideal_text_parts(
                arc_id, str(request.user_id), with_lock=True)
            _composed = compose_locked(_text, _p_rows)
            if _composed is not None:
                from services.ideal_text_quality_gate import (
                    validate_composed_text,
                )
                _quality = validate_composed_text(
                    _composed.get("text"), _p_rows)
                if not _quality["ok"]:
                    from services.ideal_text_parts import pinned_parts
                    logger.warning(
                        "compose quality gate rejected arc=%s reasons=%s",
                        arc_id, _quality["reasons"])
                    _composed = pinned_parts(_p_rows)
            if _composed is not None:
                _text = _composed["text"]
                # The refreshed paragraphs carry SERVER-minted ids; they must
                # be stable across GETs, so a changed composition persists.
                # Kept locks carry their ORIGINAL timestamps (a decision made
                # before a lock and one after mean different things, §6).
                if _composed.get("changed"):
                    _lk_by_id = {str(r.get("id")): r.get("locked_at")
                                 for r in (_p_rows or [])
                                 if isinstance(r, dict)}
                    if not db.replace_ideal_text_parts(
                            arc_id, str(request.user_id),
                            [{**p, "locked_at": _lk_by_id.get(p["id"])
                              if not p.get("locked") else
                              (_lk_by_id.get(p["id"])
                               or datetime.now(timezone.utc).isoformat())}
                             for p in _composed["parts"]]):
                        logger.warning(
                            "compose: parts not persisted arc=%s", arc_id)
        except Exception as _cmp_err:
            # §12.1 (founder 2026-08-14): a compose failure used to fall
            # through to the RAW machine text — the stored parts no longer
            # joined to it, the parts block dropped off the wire, and every
            # lock went invisible in one GET while the new take's
            # suggestions attached to unprotected text (field report #5).
            # A rebuild that cannot place the locks is a FAILED rebuild:
            # the previous composed state serves instead.
            logger.error(
                "compose failed arc=%s: %s — serving the pinned stored "
                "composition (§12.1 failed-rebuild rule)", arc_id, _cmp_err)
            _deg.record("compose", _cmp_err)
            try:
                from services.ideal_text_parts import pinned_parts
                _composed = pinned_parts(_p_rows)
                if _composed is not None:
                    _text = _composed["text"]
            except Exception as _pin_err:
                logger.error(
                    "compose pin fallback ALSO failed arc=%s: %s — locks "
                    "will be invisible this read", arc_id, _pin_err)
                _deg.record("compose_pin", _pin_err)
                _composed = None
        _moment_take_ids = [m.get("take_session_id") for m in _moments]
        _has_expl = _optional(
            "moment_explanations", {},
            lambda: _moment_explanations_map(_moment_take_ids))
        _playback = _optional(
            "moment_playback", {},
            lambda: _moment_playback_map(_moment_take_ids))
        _review_status = _optional(
            "confidence_review_status", {},
            lambda: _confidence_review_status_map(arc_id, _moments))
        # Ticket 6: resolve every attached post ONCE per request, not once per
        # moment (see _moment_reference_map — the per-moment form is an N+1).
        # isinstance-guarded: this map's values are dicts in production, but
        # callers (and tests) legitimately hand back a truthy marker instead,
        # and a bare .get() there is an AttributeError that takes the whole
        # ideal-text response down with it.
        _refs = _optional(
            "moment_references", {},
            lambda: _moment_reference_map([
                v.get("reference_post_slug") if isinstance(v, dict) else None
                for v in _has_expl.values()
            ]))

        _key_moments = decorate_key_moments(
            _moments,
            suggestions_enabled=_stars_on,
            explanations=_has_expl,
            playback=_playback,
            review_status=_review_status,
            references=_refs,
        )

        _notes = _optional(
            "owner_notes", None,
            lambda: db.get_user_arc_ideal_notes(arc_id, request.user_id))

        # ── Crucial-bubble fields (founder 2026-07-20): title + latest
        # take, derived from the ownership read (_sessions), zero extra
        # queries.
        #
        # The re-read lane is RETIRED (founder 2026-08-05) — reread_done
        # and reread_processing are gone from this payload with it. The
        # read/spoken SPLIT stays: historical read rows still sit in the
        # table until the teardown migration runs, and they must never
        # be counted as takes. Once the columns are dropped this reads
        # every row as spoken, which is then the truth. ──
        _project = resolve_project_read(
            _sessions,
            completed_spoken=_completed_spoken_sessions,
        )
        _spoken_rows = _project.spoken_rows
        _title = _project.title
        _latest_take_sid = _project.latest_take_session_id
        # ── NEXT TAKE (founder 2026-07-24, T1 · 1.2): available the
        # moment this project has a spoken take, so a finished recording
        # drops the student straight back here ready to record again.
        # Same continuable-project rule as GET /explore/arc/<id>/setup,
        # so the two can never disagree about whether a take can start.
        _can_record_take = _project.can_record_take
        from services.journey_messages import journey_seen
        _journey_seen = _optional(
            "journey_state", False,
            lambda: journey_seen(
                db, request.user_id, arc_id, len(_spoken_rows)))

        _decision_history = _optional(
            "decision_history", [],
            lambda: db.list_intervention_decision_history(arc_id))
        _moments_unlocked = _optional(
            "moment_entitlement", False,
            lambda: _moments_entitled(arc_id))
        _moment_price = _optional(
            "moment_price", 0,
            lambda: _price_of("moment_explanation"))

        # ── SLIDE LINKAGE (FE handoff 2026-08-03, FE PR #222): the deck
        # url + per-paragraph slide identity, so the reading view can
        # interleave slide → its words exactly, cross-device (the FE's
        # localStorage fallback only covered the recording device). The
        # FIRST non-null presentation_ref across takes in take order —
        # the same never-clobbered-by-a-deckless-retake resolution
        # build_best_presentation uses for its canonical deck ref. Zero
        # extra queries (the ownership read already has the sessions). ──
        _pres_ref = _project.presentation_ref
        # SLIDE TITLES (founder 2026-08-11: "yeah put only the title"). The
        # read surface already groups the text by slide and had a title slot
        # with nothing to put in it — the payload carried `slide_index` per
        # paragraph and no way to say what slide 2 IS. Titles only: the body
        # is what the speaker was meant to say, and printing it beside what
        # they DID say turns their own speech into a diff against a script.
        #
        # MOST-COMPLETE DECK WINS, the same resolution build_best_presentation
        # uses — a re-take that dropped its deck must not shorten the list and
        # blank the later slides.
        _slide_titles = _project.slide_titles

        # DATA FOUNDATION — preparing this actor-specific document packet is
        # NOT an exposure.  The client receives a one-time handle and creates
        # the receipt only after the Ideal Text itself has visibly painted.
        # Older/non-canonical rows degrade by omitting the handle; they never
        # counterfeit exposure data and never make the document unreadable.
        _ideal_text_exposure = None
        _latest_take_row = next((
            session for session in reversed(_spoken_rows)
            if str(session.get("id") or "") == str(_latest_take_sid or "")
        ), None)
        if isinstance(_latest_take_row, dict):
            try:
                from services.learning_exposures import (
                    prepare_ideal_text_presentation,
                )
                _owner_principal_id = str(
                    _latest_take_row.get("owner_principal_id") or "")
                _project_id = str(
                    _latest_take_row.get("project_id") or arc_id or "")
                if _owner_principal_id and _project_id:
                    _ideal_text_exposure = prepare_ideal_text_presentation(
                        database=db,
                        owner_principal_id=_owner_principal_id,
                        project_id=_project_id,
                        take_id=str(_latest_take_sid),
                        actor_id=str(request.user_id),
                        text=_text,
                        version=_version,
                        take_count=len(_spoken_rows),
                        title=_title,
                        parts=(
                            _composed.get("parts")
                            if isinstance(_composed, dict) else None
                        ),
                        delivery_mode="canary",
                    )
            except Exception as _exposure_error:
                logger.warning(
                    "ideal-text presentation not prepared arc=%s take=%s: %s",
                    arc_id, _latest_take_sid, _exposure_error,
                )
                _deg.record("learning_exposure", _exposure_error)

        return jsonify({
            "arc_id": arc_id,
            "version": _version,
            "status": _live.status,
            "title": _title,
            "updated_at": _r.get("updated_at"),
            "latest_take_session_id": _latest_take_sid,
            # The project's OFFICIAL-TAKE count (founder 2026-07-23):
            # the FE renders the document badge as "<take_count>.0".
            # PER-PROJECT by construction (spoken takes of THIS arc;
            # reads excluded) — never a global tally, and it grows on
            # every recorded take (unlike `version`, which bumps only
            # when the text actually changes). Canonical project ownership
            # keeps every new take appending to this exact Project.
            "take_count": len(_spoken_rows),
            # IMMEDIATE next-take affordance (founder 2026-07-24, T1 ·
            # 1.2): the FE can offer "record another take" as soon as
            # this is true. True once the project has a spoken take
            # (same continuable-project rule as /setup).
            "can_record_take": _can_record_take,
            "journey_next_steps_seen": _journey_seen,
            "text": _text,
            **({"learning_exposure": _ideal_text_exposure}
               if _ideal_text_exposure else {}),
            # The arc's served deck PDF (FE handoff 2026-08-03) — null on
            # a deckless arc; the FE treats anything but a non-empty
            # string as absent.
            "presentation_ref": refreshed_media_url(_pres_ref or None),
            # Slide titles by slide index — what the AUDIENCE saw, which is
            # the one piece of deck context the reader is allowed (it says
            # nothing about which take this is). [] when the arc has no deck;
            # an empty string at an index means that slide is untitled, and
            # the FE renders no title line rather than inventing one.
            "slide_titles": _slide_titles,
            # One entry per "\n\n"-paragraph of `text`, carrying the deck
            # page (`slide_index`) its words were bucketed to when the
            # mapping is provable — null degrades the FE to its
            # exact-count zip, never a guessed attachment.
            "pieces": _ideal_text_pieces(
                arc_id, _text, _pres_ref, str(request.user_id), degradation=_deg),
            # ── PARTS (SPEC-parts-locking-and-layers §3.1, Step 0): the
            # document as an ordered list with STABLE ids, so PR 3 has
            # something a lock can survive a reorder or a reword on.
            #
            # ABSENT, not [], when this document has no parts yet — the
            # two mean different things and the FE branches on exactly
            # that difference. Absent = "no identity stored, derive as
            # you always did"; [] = "this document is empty". `text` is
            # unchanged either way, so every read-only consumer is
            # untouched. Only served when the parts still JOIN BACK to
            # the served text: a new take or a coach verify can rewrite
            # the document underneath stored parts, and stale identity
            # pointing at words that are no longer there is worse than
            # none (#219's rule, applied to parts). ──
            **({"parts": _composed["parts"]} if _composed is not None
               else _ideal_parts_block(
                   arc_id, getattr(request, "user_id", ""), _text)),
            # True when the served text is the student's own edit of the
            # current version (the FE labels it). Under COMPOSE the document
            # is canonical — locked paragraphs carry the student's words by
            # construction — so the whole-document edit label (and the star
            # fence keyed on it) stops applying; the per-paragraph fence
            # happens mechanically, anchors into typed paragraphs just drop.
            "user_edited": False if _composed is not None else _user_edited,
            # The retained edit a NEWER version superseded (founder
            # 2026-07-28) — retired by per-part persistence (2026-08-10):
            # under compose the typed words never leave the document, so
            # there is nothing to offer back. Still served on the legacy
            # lane (no locked parts) for older clients.
            **({"prior_edit": _prior_edit}
               if _prior_edit and _composed is None else {}),
            "key_moments": _key_moments,
            "moments_unlocked": _moments_unlocked,
            # Founder 2026-07-20: the 5-credit unlock buys COACH
            # explanations — the FE must show the unlock CTA ONLY when
            # at least one exists (unverified text → nothing behind the
            # paywall → no paywall shown). Automatic moments are free
            # regardless.
            "explanations_available": bool(_has_expl),
            # ── LIVING TRANSCRIPT (founder 2026-07-20, flag-gated):
            # span-anchored tracked changes on the full-transcript
            # document — strike/propose/bold/advice, each pointing at
            # exactly the words it is about. Absent when the flag is
            # off (the FE keeps rendering today's star layer). ──
            # The user id is the CONTROL-ARM KEY, and passing it is the only
            # thing that arms the manager's three randomisations — they are
            # inert on an empty id by construction. Sending it here keeps the
            # decision in one place (MANAGER_CONTROLS_ENABLED, default off)
            # rather than in whether a call site remembered to.
            **_tracked_changes_block(
                arc_id, _text, getattr(request, "user_id", "") or "",
                # The take this arbitration is about — NOT the doc-level id
                # (see _tracked_changes_block). It keys the withhold arm and
                # every arm row.
                _latest_take_sid or "", review_version=_version,
                degradation=_deg),
            # ── PROPOSAL HISTORY (slice 2, founder 2026-08-11): the arc's
            # decided proposals, texts included, newest first — the deck
            # editor's "proposals from earlier iterations". Rows predating
            # the texts migration carry no text and are not listed. ──
            "decision_history": _decision_history,
            # The moments-unlock price, top level (the FE reads it here
            # for the locked-moment prompt — the only paid item). TOKENS:
            # this used to serve `price_credits` from a retired currency's
            # constant while the charge itself was 2,500 tokens.
            "price_tokens": _moment_price,
            # The personal notebook copy — free with the text now.
            "notes_text": _notes, "notes": _notes, "user_notes": _notes,
            # Every optional stage that fell back on this read, by name
            # (audit Q-C1). Absent when the notebook is complete.
            **_deg.payload(),
        }), 200
    except Exception as e:
        logger.error("explore ideal-text GET failed arc=%s: %s", arc_id, e,
                     exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR", "error": "Failed to load ideal text",
        }), 500


@v2_bp.route("/explore/arc/<arc_id>/journey/next-steps", methods=["POST"])
@require_auth
def v2_explore_arc_journey_next_steps(arc_id):
    """Append the current take's exact journey bubble, idempotently."""
    try:
        owned, sessions = _arc_owned_by_caller(arc_id)
        if not owned:
            return jsonify({"code": "NOT_FOUND", "error": "arc not found"}), 404
        spoken = _completed_spoken_sessions(sessions)
        take_index = len(spoken)
        from services.journey_messages import journey_message
        message = journey_message(request.user_id, arc_id, take_index)
        if message is None:
            return jsonify({
                "code": "INVALID_STATE",
                "error": "Next steps are available after takes one to three.",
            }), 409
        persisted = db.insert_lounge_messages(request.user_id, [message])
        if not persisted:
            return jsonify({"code": "V2_ERROR",
                            "error": "Failed to save next steps"}), 500
        return jsonify({"message": persisted[0]}), 200
    except Exception as e:
        logger.error("journey next-steps failed arc=%s: %s", arc_id, e,
                     exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR",
                        "error": "Failed to save next steps"}), 500


@v2_bp.route("/explore/arc/<arc_id>/ideal-text/notes", methods=["PUT"])
@require_auth
def v2_explore_put_ideal_notes(arc_id):
    """Save the user's PERSONAL notebook copy (never the canonical — L1).
    Same gates as reading it (owned + paid + approved). Body: {text ≤20000}.
    200 {ok} · 400 · 402 · 404 · 500"""
    try:
        owned, _sessions = _arc_owned_by_caller(arc_id)
        if not owned:
            return jsonify({"code": "NOT_FOUND", "error": "arc not found"}), 404
        # Single deliverable (2026-07-17): the ideal text is free → so is the
        # personal notebook copy (no gate).
        body = request.get_json(silent=True) or {}
        text = body.get("text")
        if not isinstance(text, str):
            return jsonify({"code": "INVALID_INPUT",
                            "error": "text is required"}), 400
        text = re.sub(r"<[^>]*>", "", text).strip()
        if len(text) > 20000:
            return jsonify({"code": "INVALID_INPUT",
                            "error": "text too long"}), 400
        ok = db.upsert_user_arc_ideal_notes(arc_id, str(request.user_id), text)
        if not ok:
            return jsonify({"code": "V2_ERROR",
                            "error": "Could not save"}), 500
        return jsonify({"ok": True, "arc_id": arc_id}), 200
    except Exception as e:
        logger.error("ideal-notes PUT failed arc=%s: %s", arc_id, e,
                     exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to save"}), 500


@v2_bp.route("/explore/arc/<arc_id>/prior-take/decide", methods=["POST"])
@llm_limit
@require_auth
def v2_explore_decide_prior_take(arc_id):
    """The decision on a cross-take change (founder 2026-07-20 #4):

      accept → the PREVIOUS take's wording replaces the current one and
               BAKES FORWARD — an approved ledger row keyed on the
               current phrase, so every future document carries it and
               it is never re-litigated;
      keep   → the current wording stands; the offer is remembered as
               dismissed and never shown again.

    Body: { action: "accept"|"keep", snippet_id (the previous fragment —
            the change's `snippet_id`), quote (the current words),
            proposed_text (the previous words; required to accept) }
    200 { saved } · 400 · 404 · 500
    """
    try:
        from services.ideal_text_block import _living_transcript_enabled
        if not _living_transcript_enabled():
            return jsonify({"code": "NOT_FOUND", "error": "not found"}), 404
        owned, _pt_sessions = _arc_owned_by_caller(arc_id)
        if not owned:
            return jsonify({"code": "NOT_FOUND", "error": "arc not found"}), 404
        body = request.get_json(silent=True) or {}
        action = body.get("action")
        if action not in ("accept", "keep"):
            return jsonify({"code": "INVALID_INPUT",
                            "error": "action must be accept or keep"}), 400
        quote = (body.get("quote") or "").strip()
        snippet_id = (body.get("snippet_id") or "").strip()
        proposed = (body.get("proposed_text") or "").strip()
        if not quote or not snippet_id:
            return jsonify({
                "code": "INVALID_INPUT",
                "error": "quote and snippet_id are required",
            }), 400
        if action == "accept" and not proposed:
            return jsonify({"code": "INVALID_INPUT",
                            "error": "proposed_text is required"}), 400

        from services.ideal_decision_ledger import normalize_phrase
        _v = None
        try:
            _v = (db.ideal_text.get_coach_arc_ideal_text(arc_id) or {}).get("version")
        except Exception:
            _v = None
        ok = db.upsert_ideal_decision(
            arc_id=str(arc_id), kind="replace",
            target_phrase=normalize_phrase(quote),
            display_phrase=quote,
            replacement_text=(proposed if action == "accept" else None),
            decision=("approved" if action == "accept" else "dismissed"),
            source="prior_take", snippet_id=snippet_id,
            version=(_v if isinstance(_v, int) else None))
        if ok:
            # THE TAKE'S BUDGET (founder 2026-08-10): a decided offer keeps
            # its slot — approved and kept alike; deciding is what spends.
            # Also SPEC §6's ground-truth row. Best-effort.
            from services.intervention_spend import spend
            spend(db, arc_id, _pt_sessions,
                  change_key="prior_take:" + normalize_phrase(quote),
                  decision=("approved" if action == "accept"
                            else "disregarded"),
                  lane="lane:prior_take", intervention_type="REWRITE",
                  # PROPOSAL HISTORY (slice 2): this lane always has the
                  # quote in hand — the body requires it; the replacement
                  # rides on accepts (a keep has no proposed text to keep).
                  quote=quote, proposed_text=(proposed or None),
                  why_key=(str(body.get("why_key"))
                           if isinstance(body.get("why_key"), str)
                           and body.get("why_key").strip() else None))
            request_rebake_after_answer(arc_id, str(request.user_id))  # F3
        if ok and action == "accept":
            _reassemble_after_decision(arc_id)
        return jsonify({"saved": bool(ok)}), 200
    except Exception as e:
        logger.error("prior-take decide failed arc=%s: %s", arc_id, e,
                     exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR",
                        "error": "Failed to save the decision"}), 500


@v2_bp.route("/explore/arc/<arc_id>/blocks/<int:block_key>/decide",
             methods=["POST"])
@llm_limit
@require_auth
def v2_explore_decide_block(arc_id, block_key):
    """Always 404: the master-document block decision is retired (audit C2).

    Its body only ran when ``master_document_enabled()`` was true, and that
    has been permanently False since the experiment was retired. The route
    stays because the FE still calls it."""
    return jsonify({"code": "NOT_FOUND", "error": "not found"}), 404


@v2_bp.route("/explore/arc/<arc_id>/blocks/variants", methods=["GET"])
@require_auth
def v2_explore_block_variants(arc_id):
    """Always 404: the variant pool sat on top of the retired master
    document (audit C2). The route stays because the FE still calls it."""
    return jsonify({"code": "NOT_FOUND", "error": "not found"}), 404


@v2_bp.route("/explore/arc/<arc_id>/blocks/<int:block_key>/select",
             methods=["POST"])
@require_auth
def v2_explore_select_block_variant(arc_id, block_key):
    """Always 404: the variant pool sat on top of the retired master
    document (audit C2). The route stays because the FE still calls it."""
    return jsonify({"code": "NOT_FOUND", "error": "not found"}), 404


@v2_bp.route("/explore/arc/<arc_id>/ideal-text/revisions", methods=["GET"])
@require_auth
def v2_explore_ideal_revisions(arc_id):
    """Always 404: the variant pool sat on top of the retired master
    document (audit C2). The route stays because the FE still calls it."""
    return jsonify({"code": "NOT_FOUND", "error": "not found"}), 404


@v2_bp.route("/explore/arc/<arc_id>/ideal-text/revisions/<int:revision>"
             "/restore", methods=["POST"])
@require_auth
def v2_explore_restore_ideal_revision(arc_id, revision):
    """Always 404: the variant pool sat on top of the retired master
    document (audit C2). The route stays because the FE still calls it."""
    return jsonify({"code": "NOT_FOUND", "error": "not found"}), 404


@v2_bp.route("/explore/arc/<arc_id>/ideal-text/save", methods=["POST"])
@llm_limit
@require_auth
def v2_explore_save_ideal_text(arc_id):
    """Always 404: Save belonged to the retired master document (audit C2).

    Its body only ran when ``master_document_enabled()`` was true, which it
    never is. The route stays because the FE still calls it."""
    return jsonify({"code": "NOT_FOUND", "error": "not found"}), 404


def _generated_text(arc_id, user_id) -> "str | None":
    """The words the machine wrote for this document: the head snapshot's
    payload text. None when there is no snapshot or the read fails, and the
    parts block then carries no `edited` flags (see `mark_edited`)."""
    try:
        snapshot = db.get_ideal_text_document_snapshot(arc_id, user_id)
        payload = (snapshot or {}).get("payload")
        text = (payload or {}).get("text") if isinstance(payload, dict) else None
        return text if isinstance(text, str) else None
    except Exception as error:
        logger.warning("generated text unavailable arc=%s: %s", arc_id, error)
        return None


def _ideal_parts_block(arc_id, user_id, served_text) -> dict:
    """`{"parts": [...]}` for the student GET, or `{}` (the key ABSENT).

    STALE PARTS ARE NOT SERVED. Parts are written by the client against the
    document it was looking at; the document can then be rewritten underneath
    them by a new take assembling or a coach verifying, and neither of those
    goes through the arranger. Identity pointing at words that are no longer on
    screen is worse than no identity — it is the same failure as a tracked
    change anchored to a fragment that moved (#219), except a lock hung on it
    in PR 3 would silently guard the wrong paragraph.

    So the join has to match. When it does not, the key is simply absent and
    the FE derives parts the way it does today; the next save re-mints them
    against the text actually on screen.

    Best-effort by construction: any failure yields {}, which is the
    pre-migration payload exactly.
    """
    try:
        from services.ideal_text_parts import (
            agrees_with_text, mark_edited, serve,
        )
        parts = serve(db.get_ideal_text_parts(arc_id, user_id,
                                              with_lock=True))
        if parts is None:
            return {}
        parts = mark_edited(parts, _generated_text(arc_id, user_id))
        if not agrees_with_text(parts, served_text):
            # Dropping OPEN parts here is routine staleness. Dropping a
            # LOCK is not — every lock on this document just went invisible
            # for this read, which is field report #5's shape. Under the
            # §12.1 compose fallback the served text always agrees when
            # locks exist, so this firing means a path skipped compose:
            # say so loudly instead of degrading in silence.
            if any(p.get("locked") for p in parts):
                logger.error(
                    "ideal parts: %d stored parts (WITH locks) no longer "
                    "join to the served text arc=%s — locks invisible this "
                    "read (§12.1)", len(parts), arc_id)
            return {}
        return {"parts": parts}
    except Exception as e:
        logger.warning("ideal parts failed arc=%s: %s", arc_id, e)
        return {}


def _previous_spoken_session(arc_id, current_session_id):
    """The spoken take immediately BEFORE the document's take — the
    comparison base for cross-take discernment. None when this is the
    first take. Best-effort."""
    try:
        from services.slide_selection import spoken_arc_sessions
        spoken = spoken_arc_sessions(db.takes.get_arc_sessions(arc_id) or [])
        spoken.sort(key=lambda s: (s.get("take_index") or 0,
                                   s.get("created_at") or ""))
        ids = [str(s.get("id")) for s in spoken if s.get("id")]
        if not current_session_id or str(current_session_id) not in ids:
            return None
        i = ids.index(str(current_session_id))
        return ids[i - 1] if i > 0 else None
    except Exception:
        return None


def _locked_parts(arc_id, user_id, served_text) -> list:
    """The document's parts WITH their lock state, or [] when there are none.

    Same staleness rule as `_ideal_parts_block`: parts that no longer join to
    the served text describe a document the student is not looking at, and
    their offsets would point the layer filter at the wrong paragraph. [] then
    means "no locks to enforce", which is the safe direction — R1 suppresses
    interventions, so a bad parts read must never silently suppress the whole
    surface.
    """
    try:
        from services.ideal_text_parts import agrees_with_text, serve
        rows = db.get_ideal_text_parts(arc_id, user_id, with_lock=True)
        parts = serve(rows)
        if not parts or not agrees_with_text(parts, served_text):
            # [] = "no locks to enforce" — R1 then filters NOTHING, and a
            # composition suggestion can land on a locked paragraph. When
            # the dropped parts actually carried a lock, that is field
            # report #5's second half; the §12.1 compose fallback makes the
            # served text agree whenever locks exist, so a firing here is a
            # path that skipped compose — log it at error, not silence.
            if parts and any(p.get("locked") for p in parts):
                logger.error(
                    "locked parts: %d stored parts (WITH locks) do not "
                    "join to the served text arc=%s — layer filter runs "
                    "EMPTY this read (§12.1)", len(parts), arc_id)
            return []
        # `serve` carries the boolean for the wire; the layer filter reads
        # `locked_at`, so hand it the raw column rather than a second name for
        # the same fact.
        by_id = {str(r.get("id")): r.get("locked_at")
                 for r in rows if isinstance(r, dict)}
        for p in parts:
            p["locked_at"] = by_id.get(p["id"])
        return parts
    except Exception as e:
        logger.warning("locked parts failed arc=%s: %s", arc_id, e)
        return []


def _seed_parts_for_lock(arc_id, user_id, echo, raw_parts) -> list:
    """Adopt the CLIENT's parts list so a lock can land on a document with no
    stored identity. Returns the seeded parts in `_locked_parts` shape, or [].

    SEED-ON-LOCK (SPEC-lockin-loop-and-coach-panel §2, the founder's DoD). The
    founder's loop locks a paragraph the student never EDITED — record, accept
    a chip, tap "Lock it" — and an unedited document has stored no parts, so
    this endpoint used to 409 STALE on exactly the flow the product is for.
    The refetch the FE answers a 409 with cannot help either: the GET serves
    parts only when some were stored.

    The trust model is the user-edit PUT's, unchanged: the client MINTS ids
    (it owns the marker-aware splitter — §10.2), the server VALIDATES (real
    UUIDs, joins back to the echoed document byte for byte) and stores. Two
    refusals on top:

      * ANY stored part carrying a lock → no seed. Stale-but-locked rows mean
        the document moved under a locked paragraph, and compose_locked owns
        that reconciliation on the next GET — adopting the client's fresh list
        here would drop a lock the student already placed.
      * `locked` flags inside the seed are IGNORED — every seeded part lands
        open. The lock this request asks for still passes the R3 gate below;
        honouring flags in the list would let one PUT lock paragraphs the
        gate never checked.
    """
    try:
        from services.ideal_text_parts import (
            InvalidParts, agrees_with_text, validate,
        )
        if not isinstance(raw_parts, list) or not raw_parts:
            return []
        existing = db.get_ideal_text_parts(arc_id, user_id, with_lock=True)
        if any(r.get("locked_at") for r in (existing or [])
               if isinstance(r, dict)):
            return []
        try:
            parts = validate(raw_parts)
        except InvalidParts:
            return []
        if not parts or not agrees_with_text(parts, echo):
            return []
        rows = [{"id": p["id"], "ord": p["ord"], "text": p["text"],
                 "locked_at": None} for p in parts]
        if not db.replace_ideal_text_parts(arc_id, user_id, rows):
            return []
        return [dict(r, locked=False) for r in rows]
    except Exception as e:
        logger.warning("seed parts for lock failed arc=%s: %s", arc_id, e)
        return []


def _record_arms(result, session_id, user_id) -> None:
    """Persist one arbitration's experiment arms. Best-effort, never raises.

    THE MODULE IS EXPLICIT that running the controls without this is strictly
    WORSE than not running them: 12% of (user, lane) pairs receive nothing and
    20% of winning notes are withheld, users pay that cost in feedback, and
    without the arm stored next to the outcome no causal claim is recoverable
    — while it looks from the outside exactly like a working experiment.

    ONE ROW PER (session, lane) CONSIDERED, upserted on that pair. This surface
    is POLLED, so the same arbitration is written repeatedly; the upsert makes
    that idempotent, and every value it writes is deterministic for a given
    (user, session) — the assignments are pure functions of the salts, and the
    exploration roll is stable by construction — so a re-write cannot change a
    recorded arm underneath the analysis.
    """
    try:
        from services.manager_engine import arm_rows
        rows = arm_rows(result, session_id=str(session_id or ""),
                        user_id=str(user_id or ""))
        if rows:
            db.record_intervention_arms(rows)
    except Exception as e:
        logger.warning("intervention arms not recorded session=%s: %s",
                       session_id, e)


def _with_evidence_coordinates(rows, *, arc_id, served_text, pieces):
    """Ground feedback rows in the exact Project/Take/slide/paragraph span.

    Rows without provable coordinates are withheld. This is a pure boundary:
    it does not query storage or decide which feedback deserves to surface.
    """
    from services.intervention_spend import paragraph_index_at

    grounded = []
    for row in rows or []:
        span = row.get("span") if isinstance(row, dict) else None
        if not isinstance(span, dict):
            continue
        start, end = span.get("start"), span.get("end")
        if not isinstance(start, int) or not isinstance(end, int) or end <= start:
            continue
        matches = [p for p in pieces
                   if isinstance(p, dict)
                   and isinstance(p.get("start"), int)
                   and isinstance(p.get("end"), int)
                   and p["start"] <= start and end <= p["end"]]
        row_take_id = row.get("take_session_id")
        # A later-Take acoustic item can route through a canonical text span.
        # Prefer the evidence piece carrying that exact Take id; falling back
        # to the first containing canonical piece would stamp the right audio
        # with the wrong slide whenever the spans overlap.
        piece = next((p for p in matches
                      if row_take_id
                      and str(p.get("take_session_id") or "")
                      == str(row_take_id)), None)
        if piece is None:
            piece = matches[0] if matches else None
        take_id = row_take_id or (piece or {}).get("take_session_id")
        slide_index = (piece or {}).get("slide_index")
        if (not take_id
                or (slide_index is not None
                    and (isinstance(slide_index, bool)
                         or not isinstance(slide_index, int)
                         or slide_index < 0))):
            continue
        row["evidence"] = {
            "project_id": str(arc_id),
            "take_session_id": str(take_id),
            "slide_index": slide_index,
            "paragraph_index": paragraph_index_at(served_text, start),
            "span": {"start": start, "end": end},
        }
        grounded.append(row)
    return grounded


def _tracked_changes_block(arc_id, served_text, user_id="",
                           take_session_id="", review_version=None,
                           degradation=None) -> dict:
    """The `changes` block of the SD student GET (founder 2026-07-20) —
    {} when the Living Transcript flag is off, so the key is simply
    ABSENT and the FE keeps rendering today's star layer.

    The stages live in ``services.ideal_text_changes`` (audit Q-C1 / Q-C3);
    this wrapper binds them to the database service and to the helpers this
    surface shares (the moment maps, the previous-take lookup, the locked
    parts, the evidence coordinates, the experiment arms). It keeps the name
    and signature the internal callers and the tests use. ``degradation`` is
    the request's log; without one the block reports its own fallbacks
    under a `degraded` key of its own.
    """
    from services.ideal_text_changes import ChangesDeps, build_changes_block
    return build_changes_block(
        arc_id, served_text, user_id, take_session_id, review_version,
        deps=ChangesDeps(
            database=db,
            first_client_repository=first_client_repository,
            applied_map=_moment_applied_map,
            playback_map=_moment_playback_map,
            previous_spoken_session=_previous_spoken_session,
            locked_parts=_locked_parts,
            with_evidence_coordinates=_with_evidence_coordinates,
            record_arms=_record_arms,
        ),
        degradation=degradation,
    )


@v2_bp.route("/explore/arc/<arc_id>/parts/<part_id>/lock", methods=["PUT"])
@require_auth
def v2_explore_set_part_lock(arc_id, part_id):
    """Lock or unlock ONE part (SPEC-parts-locking-and-layers §4, R3, R5).

    THE LOCK IS NOT A SETTING — it changes which INTERVENTION LAYER may fire on
    this paragraph. Open (`locked_at IS NULL`) takes composition: the machine
    may propose changing the words. Locked takes accentuation: it may only
    propose styling words already there. Offering the wrong one is worse than
    offering nothing — a rewrite destroys memorisation the speaker has already
    paid for, and an emphasis styles a sentence about to be replaced.

    Body: {locked: bool, text_echo: str}.

    `text_echo` IS THE DOCUMENT THE STUDENT WAS LOOKING AT, and it is required
    rather than nice-to-have. A lock means "these words are settled", so it has
    to be a claim about specific words. Between the GET and this PUT a new take
    can assemble or the coach can verify, replacing the text underneath — and
    locking a part id against a document that has moved settles a paragraph the
    student never read. Same idiom as the block decide endpoint's
    `challenger_session_echo`, and the same 409.

    R2 — APPROVE IS NOT LOCK. This decides no intervention. It promotes one
    part over a series of already-decided changes; the decisions themselves ride
    their own endpoints and are untouched here.

    R3 RETIRED (founder 2026-10-05, "i guess yes"): a part with open
    feedback on it locks like any other. The old gate refused while any served
    row on the paragraph was undecided -- a V3 rewrite or praise note included
    -- and the page read that refusal as final, so helper words saved while
    their lock did not. Nothing is auto-decided: an open row simply stays
    open, and a rewrite on a locked paragraph is refused at Accept
    (`accepted_rewrite`, PROTECTED).

    200 {locked, part_id} · 400 · 404 · 409 STALE_DOCUMENT · 500
    """
    try:
        from services.ideal_text_parts import agrees_with_text
        owned, _lock_sessions = _arc_owned_by_caller(arc_id)
        if not owned:
            return jsonify({"code": "NOT_FOUND", "error": "arc not found"}), 404
        body = request.get_json(silent=True) or {}
        locked = body.get("locked")
        if not isinstance(locked, bool):
            return jsonify({"code": "INVALID_INPUT",
                            "error": "locked must be a boolean"}), 400
        echo = body.get("text_echo")
        if not isinstance(echo, str) or not echo.strip():
            return jsonify({"code": "INVALID_INPUT",
                            "error": "text_echo is required"}), 400
        echo = echo.strip()

        user_id = str(getattr(request, "user_id", "") or "")
        parts = _locked_parts(arc_id, user_id, echo)
        if not parts:
            # SEED-ON-LOCK (SPEC-lockin-loop §2): no usable stored identity,
            # but the client sent its derived parts list — validate and adopt
            # it, so the founder's record→accept→"Lock it" loop works on a
            # document the student never manually edited. Refused (no seed
            # sent, malformed, disagrees with the echo, or a stored lock
            # exists) → the 409 below, exactly as before.
            parts = _seed_parts_for_lock(arc_id, user_id, echo,
                                         body.get("parts"))
        if not parts or not agrees_with_text(parts, echo):
            # Either no identity is stored, or it no longer describes this
            # document. Both mean the same thing to the caller: refetch.
            return jsonify({"code": "STALE_DOCUMENT",
                            "error": "document moved"}), 409
        target = next((p for p in parts if p["id"] == str(part_id).lower()),
                      None)
        if target is None:
            return jsonify({"code": "NOT_FOUND", "error": "part not found"}), 404

        _reason = body.get("reason")
        if _reason not in (None, "keep_evolving"):
            return jsonify({"code": "INVALID_INPUT",
                            "error": "reason is not valid"}), 400
        if _reason == "keep_evolving" and locked:
            return jsonify({"code": "INVALID_INPUT",
                            "error": "keep_evolving requires unlocked"}), 400
        if not db.set_ideal_text_part_lock(
                arc_id, user_id, str(part_id), locked,
                revision_action=("keep_evolving"
                                 if _reason == "keep_evolving" else None)):
            return jsonify({"code": "V2_ERROR",
                            "error": "Could not save"}), 500
        record_lock(db, arc_id, user_id, str(part_id),
                    _latest_take_sid(_lock_sessions), locked)
        # Canonical paragraph versioning is an immutable decision chain. The
        # legacy part row remains the live read during parity; the canonical
        # write binds the explicit action to this exact paragraph body and the
        # latest spoken Take. A missing exposure snapshot is observable and
        # retriable, never a reason to undo the user's successful lock.
        try:
            from services.feedback_data_contract import (
                canonical_paragraph_decision,
                content_hash,
            )
            from services.intervention_spend import latest_spoken_take_sid

            _decision_take_id = latest_spoken_take_sid(_lock_sessions)
            _decision_session = (
                db.v2_get_session_by_id(_decision_take_id) or {}
                if _decision_take_id else {}
            )
            _updated_parts = db.get_ideal_text_parts(
                arc_id, user_id, with_lock=True) or []
            _updated_part = next((
                row for row in _updated_parts
                if str(row.get("id") or "") == str(part_id).lower()
            ), {})
            _decision_value = (
                "lock_for_next_take" if locked
                else "keep_evolving" if _reason == "keep_evolving"
                else "reopen_for_edit"
            )
            _legacy_revision = db.get_latest_ideal_text_part_revision(
                arc_id=arc_id, user_id=user_id, part_id=str(part_id)) or {}
            _revision_coordinate = content_hash({
                "part_id": str(part_id).lower(),
                "value": _decision_value,
                "legacy_revision_id": _legacy_revision.get("id"),
                "legacy_revision_action": _legacy_revision.get("action"),
                "iteration": _updated_part.get("iteration"),
                "locked_at": _updated_part.get("locked_at"),
                "text": target.get("text"),
            })
            _canonical_part_decision = canonical_paragraph_decision(
                take_id=str(_decision_take_id or ""),
                project_id=str(_decision_session.get("project_id") or ""),
                rater_id=user_id,
                source_ideal_part_id=str(part_id).lower(),
                exact_text=str(target.get("text") or ""),
                value=_decision_value,
                revision_coordinate=_revision_coordinate,
            )
            if _canonical_part_decision is not None:
                db.record_canonical_paragraph_decision(
                    _canonical_part_decision)
        except Exception as _canonical_part_error:
            logger.warning(
                "canonical paragraph decision dual-write failed "
                "arc=%s part=%s: %s", arc_id, part_id,
                _canonical_part_error,
            )
        _proposal = None
        if locked:
            from services.rooting_phrase import propose_rooting_phrase
            _proposal = propose_rooting_phrase(target.get("text"))
        _publish_ideal_text_core(arc_id, user_id)
        return jsonify({
            "locked": locked,
            "part_id": str(part_id),
            "root_phrase_proposal": _proposal,
        }), 200
    except Exception as e:
        logger.error("part lock failed arc=%s part=%s: %s", arc_id, part_id, e,
                     exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR",
                        "error": "Failed to set the lock"}), 500


@v2_bp.route("/explore/arc/<arc_id>/parts/<part_id>/helper-words",
             methods=["PUT"])
@require_auth
def v2_explore_set_part_helper_words_from_take(arc_id, part_id):
    """Helper words taken from any earlier Take (founder lock 2026-09-30,
    B4, D5): the speaker opens another Take's version of the Paragraph on
    the helper words overlay and taps words there. Those words need not be
    in the current text — they show as the headline with nothing italic
    until said again — so the Paragraph-level rooting phrase, which is a
    span of the current text, cannot hold them. They go to the Slide's
    helper words, where the recording screen and the page read them from,
    replacing the Paragraph's current pick; the lock that follows (the
    same "Use these helper words" tap) locks them like any other pick.
    One Take, one phrase (Q3): the words must be exact words of that one
    version."""
    owned, _sessions = _arc_owned_by_caller(arc_id)
    if not owned:
        return jsonify({"code": "NOT_FOUND", "error": "arc not found"}), 404
    body = request.get_json(silent=True) or {}
    user_id = str(request.user_id)
    history = history_for_part(db, arc_id, user_id, str(part_id))
    if history is None:
        return jsonify({"code": "NOT_FOUND", "error": "part not found"}), 404
    from services.slide_helper_words import phrase_in_version, version_of_take
    version = version_of_take(history, body.get("take_index"))
    if version is None:
        return jsonify({"code": "INVALID_INPUT",
                        "error": "that Take has no version of this text"}), 400
    words = phrase_in_version(body.get("phrase"), version.get("paragraphs"))
    from services.slide_helper_words import within_cap
    if words is None or not within_cap(words):
        return jsonify({"code": "INVALID_ROOT_PHRASE",
                        "error": "Choose exact words from that Take."}), 400
    # The Paragraph-level span, if any, is cleared: the Slide's pick is now
    # the one set of words, and the page must not show two.
    db.set_ideal_text_part_root(arc_id=arc_id, user_id=user_id,
                                part_id=str(part_id), phrase=None,
                                start=None, end=None)
    record_pick(db, arc_id, user_id, str(part_id),
                _latest_take_sid(_sessions), words)
    return jsonify({"saved": True, "phrase": words}), 200


@v2_bp.route("/explore/arc/<arc_id>/parts/<part_id>/history",
             methods=["GET"])
@require_owner_or_guest
def v2_explore_get_part_history(arc_id, part_id):
    """The history behind a Paragraph's bookmark (contract 16): its Slide's
    words Take by Take, and the helper words locked when. Owner only."""
    owned, _sessions = _arc_owned_by_caller(arc_id)
    if not owned:
        return jsonify({"code": "NOT_FOUND", "error": "arc not found"}), 404
    history = history_for_part(db, arc_id, str(request.user_id),
                               str(part_id))
    if history is None:
        return jsonify({"code": "NOT_FOUND", "error": "part not found"}), 404
    from services.paragraph_history import with_earlier_take_details
    from services.snippet_audio_url import resolve_snippet_audio_url
    history = _ideal_optional_read(
        "earlier_take_details", history,
        lambda: with_earlier_take_details(
            db, arc_id, str(request.user_id), history,
            lambda snippet: resolve_snippet_audio_url(snippet, db)))
    response = jsonify(history)
    response.headers["Cache-Control"] = "private, no-store"
    return response


@v2_bp.route("/explore/arc/<arc_id>/parts/<part_id>/root", methods=["PUT"])
@require_auth
def v2_explore_set_part_root(arc_id, part_id):
    """Accept, replace, or skip the orange exact-span prompt on one part."""
    try:
        owned, _sessions = _arc_owned_by_caller(arc_id)
        if not owned:
            return jsonify({"code": "NOT_FOUND", "error": "arc not found"}), 404
        body = request.get_json(silent=True) or {}
        echo = body.get("text_echo")
        if not isinstance(echo, str) or not echo.strip():
            return jsonify({"code": "INVALID_INPUT",
                            "error": "text_echo is required"}), 400
        echo = echo.strip()
        user_id = str(getattr(request, "user_id", "") or "")
        parts = _locked_parts(arc_id, user_id, echo)
        target = next((p for p in parts
                       if p.get("id") == str(part_id).lower()), None)
        if target is None:
            return jsonify({"code": "STALE_DOCUMENT",
                            "error": "document moved"}), 409
        # No lock precondition — why, in db.set_ideal_text_part_root.
        phrase = body.get("phrase")
        start, end = body.get("start"), body.get("end")
        if phrase is None:
            if start is not None or end is not None:
                return jsonify({"code": "INVALID_INPUT",
                                "error": "skip must not include a span"}), 400
            valid = None
        else:
            from services.rooting_phrase import validate_rooting_phrase
            valid = validate_rooting_phrase(
                target.get("text"), phrase, start, end)
            if valid is None:
                return jsonify({
                    "code": "INVALID_ROOT_PHRASE",
                    # "locked" dropped 2026-09-25, founder sign-off.
                    "error": "Choose exact words from this paragraph.",
                }), 400
        if not db.set_ideal_text_part_root(
                arc_id=arc_id, user_id=user_id, part_id=str(part_id),
                phrase=(valid or {}).get("text"),
                start=(valid or {}).get("start"),
                end=(valid or {}).get("end")):
            return jsonify({"code": "V2_ERROR",
                            "error": "Could not save the rooting phrase"}), 500
        _root_take_id = _latest_take_sid(_sessions)
        record_pick(db, arc_id, user_id, str(part_id), _root_take_id,
                    (valid or {}).get("text"))
        try:
            from services.feedback_data_contract import (
                canonical_root_phrase,
                canonical_root_phrase_skip,
                content_hash,
            )

            _root_session = (
                db.v2_get_session_by_id(_root_take_id) or {}
                if _root_take_id else {}
            )
            _root_parts = db.get_ideal_text_parts(
                arc_id, user_id, with_lock=True) or []
            _root_part = next((
                row for row in _root_parts
                if str(row.get("id") or "") == str(part_id).lower()
            ), {})
            _root_revision = db.get_latest_ideal_text_part_revision(
                arc_id=arc_id, user_id=user_id, part_id=str(part_id)) or {}
            _root_coordinate = content_hash({
                "part_id": str(part_id).lower(),
                "legacy_revision_id": _root_revision.get("id"),
                "legacy_revision_action": _root_revision.get("action"),
                "root_selected_at": _root_part.get("root_selected_at"),
                "phrase": (valid or {}).get("text"),
                "start": (valid or {}).get("start"),
                "end": (valid or {}).get("end"),
                "action": "select" if valid is not None else "skip",
            })
            if valid is not None:
                _canonical_root = canonical_root_phrase(
                    take_id=str(_root_take_id or ""),
                    project_id=str(_root_session.get("project_id") or ""),
                    rater_id=user_id,
                    source_ideal_part_id=str(part_id).lower(),
                    exact_text=valid["text"],
                    start=valid["start"],
                    end=valid["end"],
                    revision_coordinate=_root_coordinate,
                )
                if _canonical_root is not None:
                    db.record_canonical_root_phrase(_canonical_root)
            else:
                _canonical_skip = canonical_root_phrase_skip(
                    take_id=str(_root_take_id or ""),
                    project_id=str(_root_session.get("project_id") or ""),
                    rater_id=user_id,
                    source_ideal_part_id=str(part_id).lower(),
                    revision_coordinate=_root_coordinate,
                )
                if _canonical_skip is not None:
                    db.record_canonical_root_phrase_skip(_canonical_skip)
        except Exception as _canonical_root_error:
            logger.warning(
                "canonical root phrase dual-write failed "
                "arc=%s part=%s: %s", arc_id, part_id,
                _canonical_root_error,
            )
        _publish_ideal_text_core(arc_id, user_id)
        return jsonify({
            "saved": True,
            "part_id": str(part_id),
            "root_phrase": (valid or {}).get("text"),
            "root_start": (valid or {}).get("start"),
            "root_end": (valid or {}).get("end"),
        }), 200
    except Exception as e:
        logger.error("part root failed arc=%s part=%s: %s",
                     arc_id, part_id, e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR",
                        "error": "Failed to save the rooting phrase"}), 500


def _legacy_user_edit_via_cas(arc_id, body, text, version):
    """Preserve the frozen old-client wire contract through the atomic RPC."""
    legacy_parts = None
    if "parts" in body:
        from services.ideal_text_parts import (
            InvalidParts, agrees_with_text, validate,
        )

        raw_parts = body.get("parts")
        if isinstance(raw_parts, list):
            raw_parts = [
                {**part, "text": re.sub(r"<[^>]*>", "", part.get("text"))}
                if isinstance(part, dict) and isinstance(part.get("text"), str)
                else part
                for part in raw_parts
            ]
        try:
            legacy_parts = validate(raw_parts)
        except InvalidParts as error:
            return jsonify({"code": "INVALID_INPUT", "error": str(error)}), 400
        if not agrees_with_text(legacy_parts, text):
            return jsonify({
                "code": "INVALID_INPUT",
                "error": "parts do not join to text",
            }), 400

    row = db.ideal_text.get_coach_arc_ideal_text(arc_id) or {}
    machine = ((row.get("auto_text") or "").strip()
               or ((row.get("text") or "").strip()
                   if not (row.get("updated_by") or row.get("approved_at"))
                   else ""))
    current = row.get("version") or (1 if machine else None)
    if not isinstance(current, int):
        return jsonify({"code": "NOTHING_TO_EDIT",
                        "error": "No ideal text to edit yet."}), 409
    if version != current:
        return jsonify({"code": "VERSION_SUPERSEDED",
                        "current_version": current}), 409

    result = db.compare_and_set_user_ideal_edit(
        owner_user_id=str(request.user_id),
        arc_id=str(arc_id),
        source_document_version=version,
        expected_user_text_revision=None,
        expected_user_text_sha256=None,
        desired_user_text=text,
        desired_parts_lineage=legacy_parts,
        idempotency_key=None,
    )
    if not isinstance(result, dict) or result.get("saved") is not True or (
        result.get("ideal_text_user_edit_contract_version")
        != "ideal-text-user-edit-cas-v2"
    ) or result.get("arc_id") != str(arc_id) or (
        result.get("source_document_version") != version
    ) or result.get("dataset_eligible") is not False:
        raise TypeError("invalid legacy Ideal Text CAS response")

    if body.get("reapplied") is True:
        logger.info("ideal_edit.reapplied arc=%s version=%s chars=%d",
                    arc_id, current, len(text))
    try:
        verified_version = row.get("verified_version")
        verified_text = (row.get("verified_text") or "").strip()
        base = (verified_text if verified_version == current and verified_text
                else machine)
        if base:
            from services.protected_phrases import record_user_edit_decisions

            record_user_edit_decisions(
                db, arc_id, base_text=base, user_text=text, version=current,
            )
    except Exception as error:
        logger.warning("ideal user-edit: ledger failed arc=%s: %s",
                       arc_id, error)
    _publish_ideal_text_core(arc_id, str(request.user_id))
    return jsonify({"saved": True, "arc_id": arc_id,
                    "version": current}), 200


def _validate_cas_pair_and_key(body):
    """CAS-mode expected_user_text_revision/sha256 pair + idempotency_key.

    Returns (expected_revision, expected_hash, operation_key, error) where
    ``error`` is a Flask error tuple, or None when the body validates."""
    expected_revision = None
    raw_revision = body.get("expected_user_text_revision")
    expected_hash = body.get("expected_user_text_sha256")
    if raw_revision is not None:
        if not isinstance(raw_revision, str) or not re.fullmatch(
            r"[1-9][0-9]*", raw_revision
        ):
            return None, None, None, (jsonify({
                "code": "INVALID_INPUT",
                "error": "revision must be a bigint string"}), 400)
        expected_revision = int(raw_revision)
        if expected_revision > 9223372036854775807:
            return None, None, None, (jsonify({
                "code": "INVALID_INPUT",
                "error": "revision exceeds bigint"}), 400)
    if (expected_revision is None) is not (expected_hash is None):
        return None, None, None, (jsonify({
            "code": "INVALID_INPUT", "error": "CAS pair invalid"}), 400)
    if expected_hash is not None and (
        not isinstance(expected_hash, str)
        or not re.fullmatch(r"[0-9a-f]{64}", expected_hash)
    ):
        return None, None, None, (jsonify({
            "code": "INVALID_INPUT", "error": "hash invalid"}), 400)
    operation_key = body.get("idempotency_key")
    if not isinstance(operation_key, str) or not operation_key.strip() or len(operation_key) > 200:
        return None, None, None, (jsonify({
            "code": "INVALID_INPUT",
            "error": "idempotency_key invalid"}), 400)
    return expected_revision, expected_hash, operation_key, None


def _valid_part_id(value):
    """Is ``value`` a canonical (lowercase, unpadded) UUID string?"""
    try:
        return str(uuid.UUID(value)) == value
    except (TypeError, ValueError, AttributeError):
        return False


def _validate_expected_part_rows(expected_parts):
    """One row per expected_parts entry: shape, part_id, lock/hash state,
    and its optional revision head. Returns a Flask error tuple, or None
    when every row validates."""
    for position, row in enumerate(expected_parts):
        if not isinstance(row, dict) or set(row) != {
            "position", "part_id", "text_sha256", "locked",
            "current_part_revision_id",
        } or row.get("position") != position:
            return jsonify({"code": "INVALID_INPUT",
                            "error": "expected part invalid"}), 400
        if not _valid_part_id(row.get("part_id")):
            return jsonify({"code": "INVALID_INPUT",
                            "error": "part_id invalid"}), 400
        if not isinstance(row.get("locked"), bool) or not isinstance(row.get("text_sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", row["text_sha256"]):
            return jsonify({"code": "INVALID_INPUT",
                            "error": "expected part state invalid"}), 400
        head = row.get("current_part_revision_id")
        if head is not None and (
            not isinstance(head, str) or not re.fullmatch(r"[1-9][0-9]*", head)
        ):
            return jsonify({"code": "INVALID_INPUT",
                            "error": "part revision invalid"}), 400
    return None


def _validate_desired_part_rows(desired_parts):
    """One row per desired_parts entry: shape and part_id. Returns a
    Flask error tuple, or None when every row validates."""
    for position, row in enumerate(desired_parts):
        if not isinstance(row, dict) or set(row) != {
            "position", "part_id", "text",
        } or row.get("position") != position or not isinstance(row.get("text"), str):
            return jsonify({"code": "INVALID_INPUT",
                            "error": "desired part invalid"}), 400
        if not _valid_part_id(row.get("part_id")):
            return jsonify({"code": "INVALID_INPUT",
                            "error": "part_id invalid"}), 400
    return None


def _validate_current_edit_parts_lineage(parts_lineage):
    """CAS-mode parts lineage shape (expected_parts/desired_parts row
    validation). Returns a Flask error tuple, or None when valid."""
    if not isinstance(parts_lineage, dict) or set(parts_lineage) != {
        "expected_parts", "desired_parts",
    }:
        return jsonify({"code": "INVALID_INPUT",
                        "error": "parts lineage invalid"}), 400
    expected_parts = parts_lineage.get("expected_parts")
    desired_parts = parts_lineage.get("desired_parts")
    if not isinstance(expected_parts, list) or not isinstance(desired_parts, list):
        return jsonify({"code": "INVALID_INPUT",
                        "error": "parts arrays required"}), 400
    error = _validate_expected_part_rows(expected_parts)
    if error is not None:
        return error
    error = _validate_desired_part_rows(desired_parts)
    if error is not None:
        return error
    if len({row["part_id"] for row in expected_parts}) != len(expected_parts) or len({row["part_id"] for row in desired_parts}) != len(desired_parts):
        return jsonify({"code": "INVALID_INPUT", "error": "duplicate part"}), 400
    return None


def _validate_cas_response_envelope(result, arc_id, version, is_current,
                                    expected_revision):
    """The CAS RPC's top-level response contract. Raises TypeError on any
    violation; returns nothing when valid."""
    if not isinstance(result, dict):
        raise TypeError("invalid Ideal Text CAS response")
    required = {
        "ideal_text_user_edit_contract_version", "saved", "arc_id",
        "source_document_version", "previous_user_text_revision",
        "result_user_text_revision", "result_user_text_sha256",
        "desired_parts_lineage_sha256", "part_revisions", "dataset_eligible",
    }
    if set(result) != required or result.get("ideal_text_user_edit_contract_version") != "ideal-text-user-edit-cas-v2" or result.get("saved") is not True or result.get("arc_id") != str(arc_id) or result.get("dataset_eligible") is not False:
        raise TypeError("invalid Ideal Text CAS response shape")
    if result.get("source_document_version") != version:
        raise TypeError("invalid Ideal Text CAS source version")
    for field in ("result_user_text_revision",):
        if not isinstance(result.get(field), str) or not re.fullmatch(r"[1-9][0-9]*", result[field]) or int(result[field]) > 9223372036854775807:
            raise TypeError("invalid Ideal Text CAS bigint")
    if result.get("previous_user_text_revision") is not None and (
        not isinstance(result["previous_user_text_revision"], str)
        or not re.fullmatch(r"[1-9][0-9]*", result["previous_user_text_revision"])
        or int(result["previous_user_text_revision"]) > 9223372036854775807
    ):
        raise TypeError("invalid previous Ideal Text CAS bigint")
    expected_wire_revision = (
        None if expected_revision is None else str(expected_revision)
    )
    if is_current and result.get(
        "previous_user_text_revision"
    ) != expected_wire_revision:
        raise TypeError("Ideal Text CAS previous revision mismatch")
    for field in ("result_user_text_sha256", "desired_parts_lineage_sha256"):
        if not isinstance(result.get(field), str) or not re.fullmatch(
            r"[0-9a-f]{64}", result[field]
        ):
            raise TypeError("invalid Ideal Text CAS hash")


def _validate_part_revision_ordering(part_revisions):
    """Every returned part revision names a real action against a unique
    part, with positions consistent with that action and a strictly
    increasing removed-last/position/part_id order. Raises TypeError on
    any violation; returns nothing when valid."""
    allowed_actions = {
        "owner_part_created", "owner_part_text_updated",
        "owner_part_reordered", "owner_part_text_updated_and_reordered",
        "owner_part_removed",
    }
    seen_parts = set()
    prior_order = None
    for row in part_revisions:
        if not isinstance(row, dict) or set(row) != {
            "part_id", "revision_id", "action", "previous_position",
            "result_position",
        }:
            raise TypeError("invalid part revision shape")
        try:
            part_id = str(uuid.UUID(row.get("part_id")))
        except (TypeError, ValueError, AttributeError) as error:
            raise TypeError("invalid part revision identity") from error
        if part_id != row.get("part_id") or part_id in seen_parts:
            raise TypeError("invalid part revision identity")
        seen_parts.add(part_id)
        revision_id = row.get("revision_id")
        if not isinstance(revision_id, str) or not re.fullmatch(
            r"[1-9][0-9]*", revision_id
        ) or int(revision_id) > 9223372036854775807:
            raise TypeError("invalid part revision bigint")
        action = row.get("action")
        previous_position = row.get("previous_position")
        result_position = row.get("result_position")
        if action not in allowed_actions:
            raise TypeError("invalid part revision action")
        if action == "owner_part_created":
            valid_positions = previous_position is None and type(result_position) is int and result_position >= 0
        elif action == "owner_part_removed":
            valid_positions = result_position is None and type(previous_position) is int and previous_position >= 0
        else:
            valid_positions = type(previous_position) is int and previous_position >= 0 and type(result_position) is int and result_position >= 0
        if not valid_positions:
            raise TypeError("invalid part revision positions")
        order = (
            1 if action == "owner_part_removed" else 0,
            previous_position if result_position is None else result_position,
            uuid.UUID(part_id).bytes,
        )
        if prior_order is not None and order <= prior_order:
            raise TypeError("invalid part revision order")
        prior_order = order


@v2_bp.route("/explore/arc/<arc_id>/ideal-text/user-edit", methods=["PUT"])
@require_auth
def v2_explore_put_ideal_user_edit(arc_id):
    """Persist the student's IN-PLACE edit of the SD ideal text (founder
    2026-07-17). The post-recording screen IS the ideal text 1.0, editable in
    place — this makes that edit survive reloads + show on every surface. The
    edit is stamped with the ideal-text VERSION it was made against; it wins
    display only while that equals the current version (a new take supersedes
    it — retained, not shown; BE-2 pinned default). NEVER overwrites the coach
    canonical or the legacy notebook copy (L1 — separate lanes).

    Body: {text ≤20000, version:int, reapplied?:true}. `reapplied` (founder
    2026-07-28) marks a one-click re-apply of a superseded edit — LOG-ONLY
    telemetry (the decision metric for the parked versioning change): never
    persisted, never surfaced; anything but boolean true is ignored.
    200 {saved: true, version}
    400 INVALID_INPUT · 404 · 409 VERSION_SUPERSEDED {current_version} · 500
    """
    try:
        owned, _sessions = _arc_owned_by_caller(arc_id)
        if not owned:
            return jsonify({"code": "NOT_FOUND", "error": "arc not found"}), 404
        # D22-D24: this endpoint is one database-owned text/parts/revision
        # transaction; no direct owner-lane or post-RPC part write happens
        # here.
        body = request.get_json(silent=True) or {}
        if not isinstance(body, dict):
            return jsonify({"code": "INVALID_INPUT", "error": "object required"}), 400
        cas_keys = {
            "expected_user_text_revision", "expected_user_text_sha256",
            "idempotency_key",
        }
        is_current = cas_keys <= set(body)
        current_allowed = {
            "text", "version", "parts", *cas_keys, "reapplied",
        }
        legacy_allowed = {"text", "version", "parts", "reapplied"}
        if is_current:
            if set(body) - current_allowed or not {
                "text", "version", "parts", *cas_keys,
            } <= set(body):
                return jsonify({"code": "INVALID_INPUT", "error": "request keys invalid"}), 400
        elif set(body) - legacy_allowed or set(body) & cas_keys:
            return jsonify({"code": "INVALID_INPUT", "error": "request keys invalid"}), 400
        if "reapplied" in body and not isinstance(body["reapplied"], bool):
            return jsonify({"code": "INVALID_INPUT", "error": "reapplied must be boolean"}), 400
        text = body.get("text")
        if not isinstance(text, str):
            return jsonify({"code": "INVALID_INPUT",
                            "error": "text is required"}), 400
        _v = body.get("version")
        if not isinstance(_v, int) or isinstance(_v, bool) or _v < 1:
            return jsonify({"code": "INVALID_INPUT",
                            "error": "version must be a positive integer"}), 400
        text = re.sub(r"<[^>]*>", "", text).strip()   # markers ride through
        if len(text) > 20000:
            return jsonify({"code": "INVALID_INPUT",
                            "error": "text too long"}), 400
        if not text:
            return jsonify({"code": "IDEAL_TEXT_EMPTY_EDIT_REJECTED"}), 400

        if not is_current:
            try:
                return _legacy_user_edit_via_cas(arc_id, body, text, _v)
            except Exception as error:
                code = _confident_moment_error_code(error)
                if code.startswith("IDEAL_TEXT_"):
                    return jsonify({"code": code}), 409
                raise

        expected_revision = None
        expected_hash = None
        operation_key = None
        parts_lineage = body.get("parts")
        if is_current:
            expected_revision, expected_hash, operation_key, cas_error = (
                _validate_cas_pair_and_key(body))
            if cas_error is not None:
                return cas_error
            parts_error = _validate_current_edit_parts_lineage(parts_lineage)
            if parts_error is not None:
                return parts_error
        elif parts_lineage is not None and not isinstance(parts_lineage, list):
            return jsonify({"code": "INVALID_INPUT", "error": "legacy parts invalid"}), 400

        try:
            result = db.compare_and_set_user_ideal_edit(
                owner_user_id=str(request.user_id), arc_id=str(arc_id),
                source_document_version=_v,
                expected_user_text_revision=expected_revision,
                expected_user_text_sha256=expected_hash,
                desired_user_text=text,
                desired_parts_lineage=parts_lineage,
                idempotency_key=operation_key,
            )
        except Exception as error:
            code = _confident_moment_error_code(error)
            if code.startswith("IDEAL_TEXT_"):
                return jsonify({"code": code}), 409
            raise
        _validate_cas_response_envelope(result, arc_id, _v, is_current,
                                        expected_revision)
        part_revisions = result.get("part_revisions")
        if not isinstance(part_revisions, list):
            raise TypeError("invalid part revision inventory")
        _validate_part_revision_ordering(part_revisions)
        if body.get("reapplied") is True:
            logger.info("ideal_edit.reapplied arc=%s version=%s chars=%d", arc_id, _v, len(text))
        _publish_ideal_text_core(arc_id, str(request.user_id))
        return jsonify(result), 200
    except Exception as e:
        logger.error("ideal user-edit PUT failed arc=%s: %s", arc_id, e,
                     exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to save"}), 500
