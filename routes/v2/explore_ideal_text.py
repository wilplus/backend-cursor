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
import os
import re
from datetime import datetime, timezone

import sentry_sdk
from flask import jsonify, request

from auth import require_auth
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
from services.db import db
from services.ideal_text_read import (
    decorate_key_moments,
    resolve_historical_read,
    resolve_live_text,
    resolve_ideal_text_source,
    resolve_project_read,
    resolve_suggestion_display,
)
from services.rate_limits import llm_limit
from services.rehearsal_roots import rehearsal_root
from services.token_prices import price_of as _price_of

logger = logging.getLogger(__name__)
config = Config()


def _ideal_optional_read(label, default, reader):
    """Keep auxiliary state machines outside Ideal Text availability.

    Coach delivery, feedback enrichment, pricing, and journey metadata are
    valuable additions to the notebook; none owns the canonical document. A
    fault in one is logged and omitted instead of turning safe text into a 500.
    """
    try:
        return reader()
    except Exception as exc:
        logger.warning("ideal-text optional read failed %s: %s", label, exc)
        return default


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
# (services/ideal_text_report.py) stays for its own callers/tests.


def _instant_ideal_enabled() -> bool:
    """Instant ideal text (founder re-lock 2026-07-17): the MACHINE draft is
    served to the student FREE the moment take 3 lands — the June "the raw
    auto-assembled draft must NEVER reach the student" gate is explicitly
    reversed for this labeled instant lane. The coach-perfected text + takes
    2/3 feedback stay behind approval + the $25 unlock. DEFAULT OFF until the
    FE ships variant handling (deploy order: BE → FE → flip
    INSTANT_IDEAL_TEXT_ENABLED=1 in Railway)."""
    return (os.getenv("INSTANT_IDEAL_TEXT_ENABLED") or "0").strip().lower() \
        in ("1", "true", "yes")


def _ideal_piece_provenance(arc_id, deckless_ok=True, served_text=None):
    """The machine assembly's per-piece slide identity, in served order —
    mirrors maybe_assemble_ideal_text's source choice WITHOUT re-running
    any composition on the student GET:

      * master flag: the skeleton blocks own the cutter's slide_index;
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
    status, challenger}. Best-effort; [] when nothing is provable."""
    from services.ideal_text_block import (
        _living_transcript_enabled, _polish_as_suggestions_enabled,
    )
    from services.master_document import master_document_enabled

    def _snip_slide(snip):
        # The cutter's own bucket (the slide on screen when the words
        # were spoken) — same read master_document keys its skeleton on.
        m = (snip or {}).get("metrics")
        piece = m.get("piece") if isinstance(m, dict) else None
        si = piece.get("slide_index") if isinstance(piece, dict) else None
        return si if isinstance(si, int) and not isinstance(si, bool) \
            else None

    if _living_transcript_enabled() and master_document_enabled():
        rows = sorted(
            (r for r in (db.list_ideal_text_blocks(str(arc_id)) or [])
             if r.get("active", True) and r.get("status") != "candidate"),
            key=lambda r: r.get("block_key") or 0)
        if rows:
            # ONE ROW PER SERVED PARAGRAPH, not per block (SPEC §11.1).
            # Since the cap, a block packs into one OR MORE "\n\n"
            # paragraphs, so a per-block list under-counts and the
            # caller's count-zip drops every slide attachment. Mirror the
            # assembly's packing exactly — same pure packer, same cap,
            # same strip-empty filter, over the same rows — WITHOUT
            # re-running any composition on the student GET. A block with
            # no incumbent text contributes no paragraph in the assembly,
            # so it contributes no row here either.
            from services.slide_word_split import PARAGRAPH_CAP_CHARS
            from services.transcript_document import pack_items
            out = []
            for r in rows:
                items = []
                for p in (r.get("incumbent_pieces") or []):
                    _t = (p.get("text") or "").strip()
                    if _t:
                        items.append((p, _t))
                for pack in pack_items(items, PARAGRAPH_CAP_CHARS):
                    out.append({
                        "slide_index": r.get("slide_index"),
                        # The KEYED pill→picker join (FE picker handoff
                        # 2026-08-03): the FE deep-links a paragraph's
                        # pill into the variants sheet by block_key —
                        # never by index-zipping two lists that merely
                        # happen to be sorted the same way. Sibling
                        # paragraphs of one block share its key.
                        "block_key": r.get("block_key"),
                        "snippet_id": pack[0][0].get("snippet_id"),
                        "take_session_id": r.get("incumbent_take_session_id"),
                        "take_index": r.get("incumbent_take_index"),
                        "status": r.get("status") or "settled",
                        "challenger": r.get("challenger_take_index"),
                    })
            if out:
                return out
        # No skeleton yet → the living-transcript document, exactly the
        # fallback the assembly itself makes.
    if _living_transcript_enabled():
        # CANONICAL SOURCE FIRST. Take 1's document provenance is persisted in
        # the same database write as its text. Later Takes advance the REVIEW
        # version without replacing those words, so rebuilding provenance from
        # the latest transcript describes a different document. That mismatch
        # is what made the FE reject the whole Ideal Text after Take 2.
        try:
            _ideal_row = db.get_coach_arc_ideal_text(arc_id) or {}
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
            if _stored_paragraphs and _same_body:
                return [{
                    "slide_index": p.get("slide_index"),
                    "snippet_id": p.get("snippet_id"),
                    "take_session_id": p.get("take_session_id"),
                    "take_index": p.get("take_index"),
                    "status": "settled",
                    "challenger": None,
                } for p in _stored_paragraphs if isinstance(p, dict)]
            # Compatibility for canonical rows persisted between the document
            # column migration and this paragraph-grain fix. They have exact
            # canonical snippet pieces but no paragraph list. Re-anchor those
            # pieces to the currently served body, then derive one provenance
            # row per actual paragraph. Every paragraph must be covered; a
            # partial map falls through to the unlinked compatibility path.
            _stored_pieces = _stored_doc.get("pieces") or []
            if (_stored_pieces and _same_body
                    and isinstance(served_text, str) and served_text):
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
                if _derived:
                    return _derived
        except Exception as _stored_doc_err:
            logger.warning(
                "stored ideal-text provenance failed arc=%s: %s",
                arc_id, _stored_doc_err)
        # Compatibility only: rows created before document provenance was
        # added have no canonical map. The latest transcript remains the best
        # available structural source, but the FE now treats any mismatch as
        # optional metadata failure and still renders the text unlinked.
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
    # LEGACY compose cache — and the ONLY lane the deckless guard belongs
    # to. This one keys its picks by SECTION index, which is not a deck page,
    # so without an uploaded deck it must not attach. The two lanes above
    # read the CUTTER's own bucket (the slide that was on screen when the
    # words were spoken), which is a real page whether or not a PDF was ever
    # uploaded — and applying the guard to all three is what made the
    # built-in mock deck attach nothing at all (founder 2026-08-11).
    if not deckless_ok:
        return []
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
        # Mirror assemble_ideal_text_block's paragraph filter exactly —
        # a pick it skipped must not shift the alignment here.
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


def _ideal_text_pieces(arc_id, served_text, presentation_ref, user_id=None):
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
        prov = _ideal_piece_provenance(
            arc_id,
            deckless_ok=bool(presentation_ref),
            served_text=served_text,
        )
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
            root = ({"text": _metadata_root, "type": "flagship"}
                    if isinstance(_metadata_root, str) and _metadata_root
                    else rehearsal_root(para))
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
        row = db.get_coach_arc_ideal_text(arc_id)

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
        _suggestion_display = _ideal_optional_read(
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
            try:
                from services.ideal_text_parts import pinned_parts
                _composed = pinned_parts(_p_rows)
                if _composed is not None:
                    _text = _composed["text"]
            except Exception as _pin_err:
                logger.error(
                    "compose pin fallback ALSO failed arc=%s: %s — locks "
                    "will be invisible this read", arc_id, _pin_err)
                _composed = None
        _moment_take_ids = [m.get("take_session_id") for m in _moments]
        _has_expl = _ideal_optional_read(
            "moment_explanations", {},
            lambda: _moment_explanations_map(_moment_take_ids))
        _playback = _ideal_optional_read(
            "moment_playback", {},
            lambda: _moment_playback_map(_moment_take_ids))
        _review_status = _ideal_optional_read(
            "confidence_review_status", {},
            lambda: _confidence_review_status_map(arc_id, _moments))
        # Ticket 6: resolve every attached post ONCE per request, not once per
        # moment (see _moment_reference_map — the per-moment form is an N+1).
        # isinstance-guarded: this map's values are dicts in production, but
        # callers (and tests) legitimately hand back a truthy marker instead,
        # and a bare .get() there is an AttributeError that takes the whole
        # ideal-text response down with it.
        _refs = _ideal_optional_read(
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

        _notes = _ideal_optional_read(
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
        _journey_seen = _ideal_optional_read(
            "journey_state", False,
            lambda: journey_seen(
                db, request.user_id, arc_id, len(_spoken_rows)))

        _decision_history = _ideal_optional_read(
            "decision_history", [],
            lambda: db.list_intervention_decision_history(arc_id))
        _moments_unlocked = _ideal_optional_read(
            "moment_entitlement", False,
            lambda: _moments_entitled(arc_id))
        _moment_price = _ideal_optional_read(
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
            "presentation_ref": _pres_ref or None,
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
                arc_id, _text, _pres_ref, str(request.user_id)),
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
            # MASTER DOCUMENT (founder 2026-07-22): the latest save —
            # the FE hides take badges and gates the re-read button on
            # saved_version == version. Absent pre-migration/flag-off.
            **_ideal_save_state(arc_id, _version),
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
                # The take this arbitration is about — NOT the doc-level id,
                # which is None under the master flag (see _tracked_changes_
                # block). It keys the withhold arm and every arm row.
                _latest_take_sid or "", review_version=_version),
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
            _v = (db.get_coach_arc_ideal_text(arc_id) or {}).get("version")
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
    """The MASTER-DOCUMENT block decision (founder 2026-07-22):

      accept → the offered block becomes the master's (badge flips to
               the new take; a candidate block activates); the document
               reassembles at once — version bump + snapshot + the
               idempotent ready bubble;
      keep   → the offer is remembered on the block's rejected list and
               never re-offered for that take.

    Body: { action: "accept"|"keep",
            take_session_id: <echo of the offered take — the race guard> }
    200 { saved } · 400 · 404 · 409 NOT_PENDING / STALE_OFFER · 500
    """
    try:
        from services.ideal_text_block import _living_transcript_enabled
        from services.master_document import (
            decide_block, master_document_enabled,
        )
        if not (master_document_enabled() and _living_transcript_enabled()):
            return jsonify({"code": "NOT_FOUND", "error": "not found"}), 404
        owned, _blk_sessions = _arc_owned_by_caller(arc_id)
        if not owned:
            return jsonify({"code": "NOT_FOUND", "error": "arc not found"}), 404
        body = request.get_json(silent=True) or {}
        action = body.get("action")
        if action not in ("accept", "keep"):
            return jsonify({"code": "INVALID_INPUT",
                            "error": "action must be accept or keep"}), 400
        echo = (body.get("take_session_id") or "").strip()
        if not echo:
            return jsonify({"code": "INVALID_INPUT",
                            "error": "take_session_id is required"}), 400
        ok, err = decide_block(arc_id, int(block_key), action, echo, db)
        if not ok:
            if err == "NOT_FOUND":
                return jsonify({"code": "NOT_FOUND",
                                "error": "block not found"}), 404
            if err in ("NOT_PENDING", "STALE_OFFER"):
                return jsonify({
                    "code": err,
                    "error": ("No offer is pending here."
                              if err == "NOT_PENDING"
                              else "A newer take changed this offer."),
                }), 409
            return jsonify({"code": "V2_ERROR",
                            "error": "Could not save"}), 500
        # THE TAKE'S BUDGET (founder 2026-08-10): a decided offer keeps its
        # slot — accepted and kept alike. Also SPEC §6's ground-truth row.
        # ONLY this explicit tap spends: the save-time bulk auto-keeps must
        # never write here (SPEC R4 — fabricated refusals). Best-effort.
        from services.intervention_spend import spend
        _bq = body.get("quote")
        _bpt = body.get("proposed_text")
        _bwk = body.get("why_key")
        spend(db, arc_id, _blk_sessions,
              change_key=f"block:{int(block_key)}:{echo}",
              decision=("approved" if action == "accept"
                        else "disregarded"),
              lane="lane:new_take", intervention_type="REWRITE",
              # PROPOSAL HISTORY (slice 2): optional — older clients write
              # text-less rows, which the history read skips.
              quote=(str(_bq) if isinstance(_bq, str) and _bq.strip()
                     else None),
              proposed_text=(str(_bpt) if isinstance(_bpt, str)
                             and _bpt.strip() else None),
              why_key=(str(_bwk) if isinstance(_bwk, str)
                       and _bwk.strip() else None))
        if action == "accept":
            _reassemble_after_decision(arc_id)
            try:
                from services.arc_notifications import (
                    fire_ideal_version_ready,
                )
                _r2 = db.get_coach_arc_ideal_text(arc_id) or {}
                if _r2.get("version"):
                    fire_ideal_version_ready(
                        db, str(request.user_id), str(arc_id),
                        _r2["version"])
            except Exception:
                pass
        return jsonify({"saved": True}), 200
    except Exception as e:
        logger.error("block decide failed arc=%s key=%s: %s",
                     arc_id, block_key, e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR",
                        "error": "Failed to save the decision"}), 500


def _block_variants_gate() -> bool:
    """The variant-pool read surfaces exist only on top of the master
    model (founder 2026-08-03; BLOCK_VARIANTS_ENABLED default OFF —
    flag off, every route below is a plain 404 and the FE is
    unaffected)."""
    try:
        from services.ideal_text_block import _living_transcript_enabled
        from services.ideal_text_variants import variants_enabled
        from services.master_document import master_document_enabled
        return (variants_enabled() and master_document_enabled()
                and _living_transcript_enabled())
    except Exception:
        return False


@v2_bp.route("/explore/arc/<arc_id>/blocks/variants", methods=["GET"])
@require_auth
def v2_explore_block_variants(arc_id):
    """The PICKER read (founder 2026-08-03, fear #3): per block, every
    text this block has ever had — each take's version (verbatim,
    take-badged) plus the student's latest edit — with the current one
    flagged. Block-level granularity by design (the mobile picker stays
    clean). AC-9: provenance and text only, no scores.

    200 { blocks: [{block_key, label, take_index, variants: [
          {variant_id, source, take_index, text, is_current}]}],
          head_revision } · 404 · 500
    """
    try:
        if not _block_variants_gate():
            return jsonify({"code": "NOT_FOUND", "error": "not found"}), 404
        owned, _ = _arc_owned_by_caller(arc_id)
        if not owned:
            return jsonify({"code": "NOT_FOUND",
                            "error": "arc not found"}), 404
        from services.ideal_text_variants import block_variants_payload
        payload = block_variants_payload(db, str(arc_id))
        if payload is None:
            return jsonify({"code": "V2_ERROR",
                            "error": "Could not read the document — "
                                     "try again."}), 500
        return jsonify({"arc_id": arc_id, **payload}), 200
    except Exception as e:
        logger.error("block variants GET failed arc=%s: %s", arc_id, e,
                     exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to load"}), 500


@v2_bp.route("/explore/arc/<arc_id>/blocks/<int:block_key>/select",
             methods=["POST"])
@require_auth
def v2_explore_select_block_variant(arc_id, block_key):
    """MIX AND MATCH (founder 2026-08-03): point one block at ANY pooled
    variant — this take's, an earlier take's, or my own edit. The
    displaced text stays in the pool (selecting is never destructive),
    the composition records a new revision, and the document reassembles
    at once.

    Body: { variant_id }
    200 { saved } · 400 · 404 · 409 NOT_PENDING (candidate block) · 500
    """
    try:
        if not _block_variants_gate():
            return jsonify({"code": "NOT_FOUND", "error": "not found"}), 404
        owned, _ = _arc_owned_by_caller(arc_id)
        if not owned:
            return jsonify({"code": "NOT_FOUND",
                            "error": "arc not found"}), 404
        body = request.get_json(silent=True) or {}
        variant_id = (str(body.get("variant_id") or "")).strip()
        if not variant_id:
            return jsonify({"code": "INVALID_INPUT",
                            "error": "variant_id is required"}), 400
        from services.ideal_text_variants import select_block_variant
        ok, err = select_block_variant(db, str(arc_id), int(block_key),
                                       variant_id, str(request.user_id))
        if not ok:
            if err == "NOT_FOUND":
                return jsonify({"code": "NOT_FOUND",
                                "error": "block or variant not found"}), 404
            if err == "NOT_PENDING":
                return jsonify({"code": "NOT_PENDING",
                                "error": "This block is not selectable "
                                         "yet."}), 409
            return jsonify({"code": "V2_ERROR",
                            "error": "Could not save"}), 500
        _reassemble_after_decision(arc_id)
        return jsonify({"saved": True}), 200
    except Exception as e:
        logger.error("block select failed arc=%s key=%s: %s",
                     arc_id, block_key, e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR",
                        "error": "Failed to save the selection"}), 500


@v2_bp.route("/explore/arc/<arc_id>/ideal-text/revisions", methods=["GET"])
@require_auth
def v2_explore_ideal_revisions(arc_id):
    """The composition timeline (founder 2026-08-03, fear #2): every
    selection state the document has been in, newest first, with the
    head flagged — the FE's undo/history surface. Selections are pointer
    lists; the texts live in the pool, so nothing here is a copy.

    200 { revisions: [{revision, reason, created_at, is_head}],
          head_revision } · 404 · 500
    """
    try:
        if not _block_variants_gate():
            return jsonify({"code": "NOT_FOUND", "error": "not found"}), 404
        owned, _ = _arc_owned_by_caller(arc_id)
        if not owned:
            return jsonify({"code": "NOT_FOUND",
                            "error": "arc not found"}), 404
        rows = db.list_ideal_text_compositions(str(arc_id), limit=50)
        if rows is None:
            rows = []
        head = (db.get_ideal_text_composition_head(str(arc_id))
                or {}).get("head_revision")
        return jsonify({
            "arc_id": arc_id,
            "head_revision": head,
            "revisions": [{
                "revision": r.get("revision"),
                "reason": r.get("reason"),
                "created_at": r.get("created_at"),
                "is_head": r.get("revision") == head,
            } for r in rows],
        }), 200
    except Exception as e:
        logger.error("ideal revisions GET failed arc=%s: %s", arc_id, e,
                     exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to load"}), 500


@v2_bp.route("/explore/arc/<arc_id>/ideal-text/revisions/<int:revision>"
             "/restore", methods=["POST"])
@require_auth
def v2_explore_restore_ideal_revision(arc_id, revision):
    """GO BACK (founder 2026-08-03, fear #2): repoint the document at an
    earlier composition. Blocks that revision recorded write through;
    blocks added since stay as they are (restore repoints, never
    deletes). The restore lands as a NEW revision, so it is itself
    undoable. The document reassembles at once.

    200 { restored, head_revision } · 404 · 500
    """
    try:
        if not _block_variants_gate():
            return jsonify({"code": "NOT_FOUND", "error": "not found"}), 404
        owned, _ = _arc_owned_by_caller(arc_id)
        if not owned:
            return jsonify({"code": "NOT_FOUND",
                            "error": "arc not found"}), 404
        from services.ideal_text_variants import restore_revision
        ok, err = restore_revision(db, str(arc_id), int(revision),
                                   str(request.user_id))
        if not ok:
            if err == "NOT_FOUND":
                return jsonify({"code": "NOT_FOUND",
                                "error": "revision not found"}), 404
            return jsonify({"code": "V2_ERROR",
                            "error": "Could not restore"}), 500
        _reassemble_after_decision(arc_id)
        head = (db.get_ideal_text_composition_head(str(arc_id))
                or {}).get("head_revision")
        return jsonify({"restored": True, "arc_id": arc_id,
                        "head_revision": head}), 200
    except Exception as e:
        logger.error("ideal revision restore failed arc=%s rev=%s: %s",
                     arc_id, revision, e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR",
                        "error": "Failed to restore"}), 500


@v2_bp.route("/explore/arc/<arc_id>/ideal-text/save", methods=["POST"])
@llm_limit
@require_auth
def v2_explore_save_ideal_text(arc_id):
    """SAVE = ACCEPT-AND-FREEZE (founder decision #3, 2026-07-22): the
    student accepts the master's current state as their script.

      * every UNACTIONED offer resolves as kept-mine (dismissed-
        remembered — Save must leave a clean document, not hidden
        pending state);
      * the current version is stamped as a save row (the FE hides the
        take badges and gates the re-read button on it);
      * the frozen snapshot rides the existing per-version history lane.

    200 { saved: true, saved_version } · 404 · 409 NOTHING_TO_SAVE · 500
    """
    try:
        from services.ideal_text_block import _living_transcript_enabled
        from services.master_document import master_document_enabled
        if not (master_document_enabled() and _living_transcript_enabled()):
            return jsonify({"code": "NOT_FOUND", "error": "not found"}), 404
        owned, _ = _arc_owned_by_caller(arc_id)
        if not owned:
            return jsonify({"code": "NOT_FOUND", "error": "arc not found"}), 404

        # Resolve every unactioned offer as kept-mine. A failed block
        # READ must not freeze over unknown state, and a failed resolve
        # must not stamp a save that still has hidden pending offers
        # (review findings #8/#11/#18).
        rows = db.list_ideal_text_blocks(str(arc_id))
        if rows is None:
            return jsonify({"code": "V2_ERROR",
                            "error": "Could not read the document — "
                                     "try again."}), 500
        from services.master_document import decide_block
        # ── SAVE MUST NOT DECIDE WHAT THE LOCK HID (founder 2026-08-07) ──
        # R1 suppresses composition offers on a LOCKED part: the offer is
        # created and stored, just not surfaced, so unlocking brings it back.
        # Resolving it here as kept-mine would silently refuse an upgrade the
        # student never saw — writing a decision they never made into the one
        # signal §6 depends on, which is exactly what R3 refuses on the lock
        # button. Suppressed means PENDING, not refused.
        #
        # Best-effort: an unreadable parts list leaves `_locked` empty, so
        # nothing is skipped and Save behaves as it always did.
        _locked = []
        try:
            from services.ideal_text_parts import covered_by_locked_part
            _locked = [
                p for p in (db.get_ideal_text_parts(
                    arc_id, str(getattr(request, "user_id", "") or ""),
                    with_lock=True) or [])
                if isinstance(p, dict) and p.get("locked_at")
            ]
        except Exception as _lk_err:
            logger.warning("save: locked parts unreadable arc=%s: %s",
                           arc_id, _lk_err)

        def _block_text(row) -> str:
            return " ".join(
                (p.get("text") or "").strip()
                for p in (row.get("incumbent_pieces") or [])).strip()

        _resolve_failed = False
        _held = 0
        for r in rows:
            if _locked and covered_by_locked_part(_block_text(r), _locked):
                _held += 1
                continue
            if r.get("status") == "pending_upgrade":
                ok, _e = decide_block(
                    arc_id, int(r.get("block_key")), "keep",
                    r.get("challenger_take_session_id"), db)
                _resolve_failed = _resolve_failed or not ok
            elif r.get("status") == "candidate":
                ok, _e = decide_block(
                    arc_id, int(r.get("block_key")), "keep",
                    r.get("incumbent_take_session_id"), db)
                _resolve_failed = _resolve_failed or not ok
        if _held:
            logger.info("save: %d offer(s) held pending behind a lock arc=%s",
                        _held, arc_id)
        if _resolve_failed:
            return jsonify({"code": "V2_ERROR",
                            "error": "Could not resolve every open "
                                     "suggestion — try again."}), 500

        _row = db.get_coach_arc_ideal_text(arc_id) or {}
        _v = _row.get("version")
        if not isinstance(_v, int):
            return jsonify({"code": "NOTHING_TO_SAVE",
                            "error": "No ideal text to save yet."}), 409
        ok = db.insert_ideal_text_save(str(arc_id), _v)
        if not ok:
            return jsonify({"code": "V2_ERROR",
                            "error": "Could not save"}), 500
        return jsonify({"saved": True, "arc_id": arc_id,
                        "saved_version": _v}), 200
    except Exception as e:
        logger.error("ideal-text save failed arc=%s: %s", arc_id, e,
                     exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR",
                        "error": "Failed to save"}), 500


def _ideal_save_state(arc_id, current_version) -> dict:
    """{saved_version, saved_at, is_saved} from the latest save row —
    {} when the master flag is off or nothing was ever saved."""
    try:
        from services.master_document import master_document_enabled
        if not master_document_enabled():
            return {}
        row = db.get_latest_ideal_text_save(str(arc_id))
        if not row:
            return {}
        _pending = False
        try:
            _pending = any(
                r.get("status") in ("pending_upgrade", "candidate")
                for r in (db.list_ideal_text_blocks(str(arc_id)) or []))
        except Exception:
            _pending = False
        return {
            "saved_version": row.get("version"),
            "saved_at": row.get("saved_at"),
            # A saved document UN-saves when new offers arrive — an
            # offers-only take bumps no version, so the version match
            # alone left is_saved stuck true (review finding #28).
            "is_saved": bool(current_version is not None
                             and row.get("version") == current_version
                             and not _pending),
        }
    except Exception:
        return {}


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
        from services.ideal_text_parts import agrees_with_text, serve
        parts = serve(db.get_ideal_text_parts(arc_id, user_id,
                                              with_lock=True))
        if parts is None:
            return {}
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
        from services.best_presentation import spoken_arc_sessions
        spoken = spoken_arc_sessions(db.get_arc_sessions(arc_id) or [])
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
                           take_session_id="", review_version=None) -> dict:
    """The `changes` block of the SD student GET (founder 2026-07-20) —
    {} when the Living Transcript flag is off, so the key is simply
    ABSENT and the FE keeps rendering today's star layer.

    Anchors are resolved against the SERVED text: each piece of the take
    the document came from is located as an exact substring, then the
    change is narrowed inside that window. A piece whose words are no
    longer there (baked, coach-corrected, student-edited) yields NO
    change rather than a mis-pointed one (#219). Best-effort.

    THE MANAGER ENGINE IS THE SOLE GATEKEEPER (founder 2026-08-07). The
    three lanes below still PRODUCE candidates exactly as they did; none
    of them SERVES one. Everything they assemble goes through
    `intervention_candidates.select`, which applies the frozen exact-three
    family contract and collision resolution.
    Concatenating the lanes and serving the result — which is what this
    did — meant the budget the whole of Appendix H exists to enforce was
    not enforced anywhere, because `manager_engine` had no caller.

    THE CUE SHEET IS DEFERRED (founder 2026-08-07). E-1's `key_points`
    was a starting-point milestone per block — a verbatim opening phrase,
    working as designed — and it read on screen as an intervention that
    explained nothing. Real interventions replace it. `services/
    key_points.py` and its tests are kept; only the wiring is gone, so
    `KEY_POINTS_ENABLED` no longer does anything and should be deleted
    from Railway."""
    try:
        # Only a durable review identity activates the immutable Take
        # contract. The student GET always supplies it. Keeping the legacy
        # no-version mode is intentional for internal pre-review callers; it
        # cannot claim a set whose Take/version provenance it does not know.
        _take_contract_on = (
            bool(take_session_id)
            and isinstance(review_version, int)
            and not isinstance(review_version, bool)
            and review_version >= 1
        )
        from services.ideal_text_block import _living_transcript_enabled
        if not _living_transcript_enabled():
            return {}
        from services.intervention_candidates import (
            feedback_family_of,
            select as _select,
        )
        from services.tracked_changes import (
            build_tracked_changes, verify_changes,
        )
        from services.transcript_document import (
            build_transcript_document, relocate_pieces,
        )
        from services.master_document import (
            assemble_master_document, master_document_enabled,
            upgrade_changes,
        )
        _master_on = master_document_enabled()
        if _master_on:
            # MASTER MODEL (founder 2026-07-22): the document is the
            # persistent master; its pieces carry per-piece spans + the
            # origin take badge, so the star lane anchors unchanged. The
            # prior-take lane is superseded by block upgrade offers.
            _master = assemble_master_document(arc_id, database=db)
            if _master.get("ready"):
                doc = _master.get("document") or {}
                doc["text"] = _master.get("text")
            else:
                # No skeleton yet (flip-ON before the next take / pre-
                # migration): the star lane keeps anchoring on the
                # living-transcript document rather than going dark.
                _master_on = False
                doc = build_transcript_document(arc_id, database=db)
        else:
            doc = build_transcript_document(arc_id, database=db)
        if not doc:
            return {}
        # The served text may already carry approved bakes / coach text —
        # re-anchor the pieces onto it MONOTONICALLY (never a bare
        # first-occurrence search, the review's mis-anchor defect).
        # PARAGRAPH FALLBACK (founder 2026-08-12). This is the call that
        # was taking the feedback engine dark: lock a paragraph — even the
        # AI's own words, unedited — and the NEXT take's pieces no longer
        # match the composed text, so every one of them was dropped and
        # build_tracked_changes below received nothing to anchor to.
        # Unlocatable pieces now take their paragraph's span, tagged
        # anchor_grain='paragraph' so word-precise consumers decline.
        _pieces = relocate_pieces(served_text, doc.get("pieces") or [],
                                  paragraph_fallback=True)
        # The canonical Take-1 provenance stays beside the canonical words.
        # Later-Take feedback is evaluated against new audio, but its deck
        # route must come from the document actually being served — never from
        # whichever transcript happened to be latest when this GET ran.
        _canonical_pieces = []
        try:
            _canonical_row = db.get_coach_arc_ideal_text(arc_id) or {}
            _canonical_document = _canonical_row.get("document") or {}
            _canonical_pieces = relocate_pieces(
                served_text,
                _canonical_document.get("pieces") or [],
                paragraph_fallback=True,
            )
        except Exception as _canonical_err:
            logger.warning(
                "canonical feedback provenance failed arc=%s: %s",
                arc_id, _canonical_err)
        _sugs = db.get_moment_suggestions_by_arc(arc_id) or {}
        from services.ideal_decision_ledger import load_ledger
        _ledger = load_ledger(db, arc_id)
        _verdicts = db.get_star_verdicts_by_snippet_ids(
            list(_sugs.keys())) if _sugs else {}
        from services.star_verdicts import (
            filter_user_suggestions, released_user_verdicts,
        )
        # BLIND COACH / publish boundary: a saved coach verdict is still
        # private review state. It can suppress or supersede user feedback
        # only after that snippet's take has been published.
        _released_verdicts = released_user_verdicts(
            _verdicts, _pieces, db.get_arc_sessions(arc_id) or [])
        _user_sugs = filter_user_suggestions(_sugs, _released_verdicts)
        _applied = []
        try:
            # The master document spans takes: feed EVERY distinct origin
            # session, not the doc-level take_session_id (which is None
            # under the master flag and starved the applied map — review
            # findings #12/#16).
            _sess_ids = {p.get("take_session_id")
                         for p in (doc.get("pieces") or [])
                         if p.get("take_session_id")}
            if doc.get("take_session_id"):
                _sess_ids.add(doc.get("take_session_id"))
            _applied = [k for k, v in _moment_applied_map(
                sorted(_sess_ids)).items() if v]
        except Exception:
            _applied = []
        # T3 (founder 2026-07-23): an emphasis star bolds only its
        # KEY-PHRASE sub-span, not the whole fragment. The signal is the
        # snippet's say-it-stronger upgrade wordings — bulk-read once for
        # the emphasize snippets only (bounded; get_snippets_by_ids added
        # #232), never a per-snippet storm. Best-effort → no narrowing
        # falls back to the whole fragment (today's behavior).
        _kp_by_snip = {}
        try:
            from services.tracked_changes import (
                key_phrases_from_say_it_stronger,
            )
            _emph_ids = [k for k, v in (_user_sugs or {}).items()
                         if isinstance(v, dict)
                         and v.get("kind") == "emphasize"]
            if _emph_ids:
                for _srow in (db.get_snippets_by_ids(_emph_ids) or []):
                    _phr = key_phrases_from_say_it_stronger(
                        _srow.get("say_it_stronger"))
                    if _phr:
                        _kp_by_snip[str(_srow.get("id"))] = _phr
        except Exception as _kp_err:
            logger.warning("emphasis key-phrases failed arc=%s: %s",
                           arc_id, _kp_err)
        changes = build_tracked_changes(
            served_text, _pieces, _user_sugs, applied=_applied,
            key_phrases_by_snippet=_kp_by_snip)
        from services.tracked_changes import build_coach_revision_changes
        changes.extend(build_coach_revision_changes(
            served_text, _pieces, _sugs, _ledger, _released_verdicts))

        # REQUIRED CURRENT-TAKE CONFIDENT VOICE (founder 2026-08-26).
        # The canonical words may stay unchanged while Take 2/3 supplies a new
        # delivery.  Build one acoustic evaluation from that exact Take and
        # route it to the corresponding canonical slide.  Playback is the
        # evidence; a span marked slide_route is navigation only and is never
        # presented as words the user said.  Historical confident moments are
        # excluded from this Take's immutable set.
        _review_sid = str(take_session_id or doc.get("take_session_id") or "")
        _review_evidence_piece = None
        if _take_contract_on and _review_sid:
            try:
                from services.take_feedback_candidates import (
                    current_take_confident_voice_candidate,
                )
                _answered_confidence = {
                    str(row.get("snippet_id"))
                    for row in (db.list_owner_voice_album_routes(
                        str(arc_id)) or [])
                    if isinstance(row, dict) and row.get("snippet_id")
                }
                _review_doc = build_transcript_document(
                    arc_id, database=db, session_id=_review_sid)
                _review_cv, _review_evidence_piece = \
                    current_take_confident_voice_candidate(
                        served_text,
                        canonical_pieces=(_canonical_pieces or _pieces),
                        take_document=_review_doc,
                        suggestions=_user_sugs,
                        excluded_snippet_ids=_answered_confidence,
                    )
                changes = [
                    c for c in changes
                    if not (isinstance(c, dict)
                            and c.get("source") == "confident_voice"
                            and str(c.get("take_session_id") or "")
                            != _review_sid)
                ]
                if _review_cv is not None:
                    # One suggestion row owns one identity. Replace any direct
                    # relocation of the same snippet with the explicit
                    # Take-scoped candidate, then put the reserved family at
                    # the front of the Manager pool.
                    changes = [
                        c for c in changes
                        if not (isinstance(c, dict)
                                and c.get("source") == "confident_voice")
                    ]
                    changes.insert(0, _review_cv)
            except Exception as _review_cv_err:
                logger.warning(
                    "current-Take Confident Voice failed arc=%s take=%s: %s",
                    arc_id, _review_sid, _review_cv_err)

        # ── HEAR IT (founder 2026-08-15) ──────────────────────────────────
        # "in the justification of the positive feedback give them the
        # playback of that phrase emphasising that it was said really well."
        #
        # The praise lane is the ONE lane whose claim is about the SOUND, so
        # it is the one lane that cannot be taken on trust: "you delivered
        # this beautifully" over words the student cannot replay is an
        # assertion, and the whole point of citing the cues is that it should
        # be evidence. Playback makes it checkable in one tap.
        #
        # FREE, and deliberately from the free map: `_moment_playback_map`
        # exists precisely because the star sheet plays a student's own
        # recording ABOVE the paywall (audit 2026-07-18). Sourcing it from
        # the paid moments read would put a paywall between somebody and
        # their own voice.
        #
        # ONLY the praise device gets it. Every other change is a claim about
        # WORDS and reads fine without audio; attaching a player to all of
        # them would be a per-snippet resolve on every serve for no reason.
        try:
            _praise = [c for c in changes
                       if isinstance(c, dict)
                       and (c.get("source") == "confident_voice"
                            or c.get("device") == "impeccable")
                       and c.get("take_session_id")]
            if _praise:
                _pb = _moment_playback_map(
                    sorted({c["take_session_id"] for c in _praise}))
                for _c in _praise:
                    _row = _pb.get(str(_c.get("snippet_id") or ""))
                    if _row and _row.get("snippet_audio_ref"):
                        _c.update(_row)
        except Exception as _pb_err:
            # No player is a smaller loss than no praise. The line still
            # renders and still names its cues.
            logger.warning("praise playback failed arc=%s: %s",
                           arc_id, _pb_err)

        # ── CROSS-TAKE DISCERNMENT (founder decision 2026-07-20 #4):
        # where the PREVIOUS take said the same thing better, its wording
        # comes back as an approvable change on this document. The
        # ranking blend does the judging (L2 untouched); a fragment the
        # student already decided on is never re-offered. Best-effort. ──
        _additions: list = []
        if _master_on:
            # Block-level upgrade offers — the master model's cross-take lane.
            try:
                changes.extend(upgrade_changes(arc_id, served_text, db))
            except Exception as _up_err:
                logger.warning("upgrade changes failed arc=%s: %s",
                               arc_id, _up_err)
            # MATERIAL RECOVERY, a separate lane on purpose. A candidate block
            # is a decked slide the master has never seen, carrying the words
            # the speaker actually said over it. It is NOT a span-anchored
            # edit — there is nothing in the document to anchor to — and while
            # it was forced into the `changes` shape as a zero-width `insert`
            # it reached nobody at all.
            try:
                from services.master_document import block_additions
                _additions = block_additions(arc_id, served_text, db)
            except Exception as _add_err:
                logger.warning("block additions failed arc=%s: %s",
                               arc_id, _add_err)
        try:
            _prev = None if _master_on else _previous_spoken_session(
                arc_id, doc.get("take_session_id"))
            if _prev:
                from services.prior_take_changes import (
                    build_prior_take_changes,
                )
                from services.ideal_decision_ledger import load_ledger
                _prev_doc = build_transcript_document(
                    arc_id, database=db, session_id=_prev)
                if _prev_doc:
                    # ONLY cross-take decisions suppress a cross-take
                    # offer — a star-lane decision on the same snippet
                    # must not silence it (review finding).
                    _decided = {
                        str(r.get("snippet_id"))
                        for r in (load_ledger(db, arc_id) or [])
                        if r.get("snippet_id")
                        and r.get("source") == "prior_take"
                    }
                    changes.extend(build_prior_take_changes(
                        {"text": served_text, "pieces": _pieces},
                        _prev_doc, database=db, decided_ids=_decided))
        except Exception as _pt_err:
            logger.warning("prior-take changes failed arc=%s: %s",
                           arc_id, _pt_err)

        # ── THE GATE. Every lane above has now PROPOSED; nothing has been
        # served. The manager builds the exact-three family set from all of
        # them, resolves collisions (which subsumes the old
        # `drop_overlaps` sweep — see intervention_candidates.select) and
        # returns the survivors in document order. A lane that is not
        # declared there does not reach the user. ──
        # THE SESSION KEY, and it is not doc-level. Under the master flag
        # `doc["take_session_id"]` is None (the same starvation review
        # findings #12/#16 hit on the applied map), which would make
        # `is_withheld` short-circuit to False — the withhold arm NEVER firing
        # — and every arm row carry an empty session_id, which the writer
            # drops. Flipping the controls on that would produce exactly the
            # failure the module warns about: a table that looks like a working
            # experiment while recording nothing. The caller passes the arc's
        # latest spoken take instead: the take this arbitration is about.
        _arm_sid = _review_sid
        # Classify the COMPLETE pool before selection, then add only honest
        # weak fallbacks for genuinely absent text lanes. Fallbacks are exact
        # document slices; they invent neither lexical content nor certainty.
        # This full pool, not merely the winners, is snapshotted for later
        # ranking evaluation.
        if _take_contract_on and _arm_sid:
            for _candidate in changes:
                if not isinstance(_candidate, dict):
                    continue
                _family = feedback_family_of(_candidate)
                if _family:
                    _candidate["feedback_family"] = _family
            _candidate_sid = (
                (_review_evidence_piece or {}).get("snippet_id")
                if isinstance(_review_evidence_piece, dict) else None
            )
            if not _candidate_sid:
                _current_doc = locals().get("_review_doc")
                _candidate_sid = next((
                    p.get("snippet_id")
                    for p in ((_current_doc or {}).get("pieces") or [])
                    if isinstance(p, dict) and p.get("snippet_id")
                ), None)
            from services.take_feedback_manager import (
                evidence_backed_rewrite_candidates,
                ensure_required_families,
                exposure_snapshot,
            )
            # Structural deletion scars are a real candidate lane, not an
            # emergency fallback. Add the complete exact-text pool before the
            # Manager ranks it, so the presence of any weaker model rewrite
            # cannot suppress an obvious word-preserving repair.
            changes.extend(evidence_backed_rewrite_candidates(
                served_text,
                take_session_id=_arm_sid,
                snippet_id=_candidate_sid,
            ))
            changes = ensure_required_families(
                served_text,
                changes,
                take_session_id=_arm_sid,
                snippet_id=_candidate_sid,
            )
            _feedback_exposure = exposure_snapshot(changes)
        else:
            _feedback_exposure = []
        _learning_presentations: dict[str, list[dict]] = {}
        # IMMUTABLE TAKE MEMBERSHIP (founder 2026-08-26). The first complete
        # Manager result is claimed in the database; every later GET may only
        # rebuild those identities. Playback URLs refresh and decided items
        # disappear, but accepting item one can never reveal item four.
        from services.take_feedback_set import (
            claim_feedback_set,
            filter_candidates_to_selected,
            filter_to_selected,
            has_required_families,
            load_feedback_set,
            selected_keys,
        )
        _feedback_set = (
            load_feedback_set(db, str(arc_id), _arm_sid)
            if _take_contract_on and _arm_sid else None
        )
        _feedback_response_count = 0
        if _feedback_set is not None:
            changes = filter_candidates_to_selected(
                changes, _feedback_set["selected_keys"])
            _response_rows = db.list_take_feedback_self_reports(
                _arm_sid, str(user_id))
            # DECISION BACKFILL-ON-READ. A compatibility response may have
            # landed during the brief backend-first window before migration
            # 0294 existed. Because that legacy response is first-write-final,
            # the user cannot safely be asked to tap it again. Rebuilding the
            # typed canonical decision from its explicit family/response is
            # deterministic and idempotent; ambiguous editor-open actions
            # intentionally remain unresolved.
            try:
                from services.feedback_data_contract import (
                    canonical_feedback_decision,
                )

                _decision_session = db.v2_get_session_by_id(_arm_sid) or {}
                if _decision_session.get("project_id"):
                    for _response_row in _response_rows:
                        if not isinstance(_response_row, dict):
                            continue
                        _canonical_decision = canonical_feedback_decision(
                            take_id=_arm_sid,
                            rater_id=str(user_id),
                            feedback_id=str(
                                _response_row.get("feedback_id") or ""),
                            feedback_family=str(
                                _response_row.get("feedback_family") or ""),
                            response=str(
                                _response_row.get("response") or ""),
                        )
                        if _canonical_decision is not None:
                            db.record_canonical_feedback_decision(
                                project_id=str(
                                    _decision_session["project_id"]),
                                take_id=_arm_sid,
                                rater_id=str(user_id),
                                decision=_canonical_decision,
                            )
            except Exception as _decision_backfill_error:
                logger.warning(
                    "canonical decision backfill failed arc=%s take=%s: %s",
                    arc_id, _arm_sid, _decision_backfill_error,
                )
            _responded_ids = {
                str(row.get("feedback_id")) for row in _response_rows
                if isinstance(row, dict) and row.get("feedback_id")
            }
            _feedback_response_count = len(_responded_ids)
            if _responded_ids:
                changes = [row for row in changes
                           if str(row.get("id") or "") not in _responded_ids]
        # THE TAKE'S SPENT BUDGET (founder 2026-08-10: "each feedback needs
        # to be there; full and end to end and waiting; not that it appears
        # once the other is accepted"). Decided interventions keep their
        # slots: the count rides into the gate, which subtracts it from
        # the frozen three, so the set on screen is chosen once and only
        # shrinks. A count miss reads 0 and degrades to per-read arbitration.
        from services.intervention_spend import (
            spent_by_paragraph, spent_count, style_spend,
        )
        # THE STYLE LANE'S OWN LEDGER (founder 2026-08-12). Its ≤3-per-take /
        # ≤2-per-slide cap is cumulative like the budgeted one, so it needs
        # the decisions the two reads above deliberately exclude. One read,
        # both numbers — this lands on the polled ideal-text GET.
        _style_spent = style_spend(db, arc_id, _arm_sid, served_text)
        # SINGLE-POINT FOCUS (founder 2026-08-12): the one paragraph feedback
        # is routed to until it comes onboard. None on cold start — no
        # baseline, a first take, or a document whose worst part is already at
        # the speaker's own level — and None means "behave exactly as before",
        # never "suppress everything".
        from services.part_acoustics import current_focus
        _sel = _select(changes, user_id=user_id,
                       session_id=_arm_sid,
                       # Under the immutable three-family contract, only an
                       # explicit self-report consumes a frozen slot. The
                       # legacy mutation endpoint may also write a spend row
                       # for Apply/Keep; counting both would make one action
                       # look like two resolved feedback items.
                       decided_count=(
                           _feedback_response_count if _take_contract_on
                           else spent_count(db, arc_id, _arm_sid)
                       ),
                       focus_part_id=current_focus(arc_id, user_id,
                                                   database=db),
                       # PER SLIDE, UP TO 1. The served
                       # text is the unit map: one paragraph per slide, and
                       # the paragraph is the chunk the student decides on.
                       # `decided_count` rides along untouched so a caller
                       # without the text still gets the flat cap.
                       served_text=served_text,
                       spent_by_paragraph=spent_by_paragraph(
                           db, arc_id, _arm_sid, served_text),
                       # Historical style spend remains a separate ledger
                       # lane, but its count is subtracted before the current
                       # whole-Take exact-three selection. This preserves provenance
                       # without granting style an extra allowance.
                       style_decided_count=(
                           0 if _take_contract_on else _style_spent["count"]
                       ),
                       style_spent_by_paragraph=_style_spent["by_paragraph"],
                       mvp_feedback_contract=_take_contract_on,
                       # R1 gen-3 — the layer filter runs inside the gate,
                       # BEFORE the budget: an open part takes everything;
                       # a locked part takes the STYLE LANE (bold only) plus
                       # a pending Confident Voice. Both still enter the same
                       # whole-Take exact-three selection after admissibility.
                       parts=_locked_parts(arc_id, user_id, served_text))
        changes = _sel["changes"]
        # Style has a distinct payload only because it has a distinct action;
        # its membership was already selected inside the same frozen Take set.
        # It is span-verified against the same served text.
        _styles = _sel.get("style_changes") or []

        # Exact evidence coordinates are part of the feedback item, not an
        # optional UI convenience. Verbal feedback stops at text evidence;
        # only Confident Voice carries playback. A row whose project/take/
        # slide/paragraph cannot be proven is withheld rather than guessed.
        _evidence_pieces = [
            p for p in [
                _review_evidence_piece,
                *_canonical_pieces,
                *_pieces,
            ] if isinstance(p, dict)
        ]
        evidence_args = {
            "arc_id": arc_id,
            "served_text": served_text,
            "pieces": _evidence_pieces,
        }
        changes = _with_evidence_coordinates(changes, **evidence_args)
        _styles = _with_evidence_coordinates(_styles, **evidence_args)
        # OPTIONAL CONFIDENT VOICE MICRO-PRACTICE.  This runs only after the
        # Feedback Manager has selected the Take's final three interactions, so
        # the exercise cannot become a fourth card or bypass the manager's
        # feedback mix.  It annotates at most one already-selected Confident
        # Voice row; no new intervention is created.  Missing migration/config
        # is a clean no-offer, never a reason to lose the feedback itself.
        try:
            from services.confident_voice_practice import attach_exercise_offer
            changes = attach_exercise_offer(
                changes, take_session_id=_arm_sid, database=db)
        except Exception as _practice_err:
            logger.warning(
                "confident voice practice offer failed arc=%s take=%s: %s",
                arc_id, _arm_sid, _practice_err)
        if _styles and not verify_changes(served_text, _styles):
            logger.warning("style lane: span check failed arc=%s "
                           "(serving none)", arc_id)
            _styles = []
        _style = {"style_changes": _styles} if _styles else {}
        # Additions ride OUTSIDE the budget and outside the span check — they
        # have no span. Absent when there are none, so the FE draws nothing
        # rather than an empty section. See master_document.block_additions for
        # why they are not arbitrated: the exact three are FEEDBACK, and
        # this is material the speaker already said going missing from their
        # own script.
        _add = {"additions": _additions} if _additions else {}
        if not verify_changes(served_text, changes):
            logger.warning("tracked changes: span check failed arc=%s "
                           "(serving none)", arc_id)
            from services.take_feedback_manager import strip_internal_evidence
            _styles = strip_internal_evidence(_styles)
            return {
                "changes": [],
                **_add,
                **({"style_changes": _styles} if _styles else {}),
            }

        # Claim only the FINAL, coordinate-proven, span-verified rows. The set
        # spans both the budgeted and style lanes and is therefore capped at
        # three for the whole Take. A set without Confident Voice is refused —
        # the required evaluation cannot be silently replaced by a third
        # rewrite. On a concurrent first open, the database returns the one
        # winner and this response immediately conforms to it.
        if _feedback_set is not None:
            changes = filter_to_selected(
                changes, _feedback_set["selected_keys"])
            _styles = filter_to_selected(
                _styles, _feedback_set["selected_keys"])
        elif _take_contract_on and _arm_sid:
            _session = db.v2_get_session_by_id(_arm_sid) or {}
            _take_index = _session.get("take_index")
            _version_int = (
                review_version if isinstance(review_version, int)
                and not isinstance(review_version, bool) else _take_index
            )
            _combined = [*changes, *_styles]
            _keys = selected_keys(_combined)
            if (not isinstance(_take_index, int)
                    or isinstance(_take_index, bool)
                    or _version_int != _take_index
                    or not has_required_families(_keys)):
                logger.error(
                    "feedback set not claimable arc=%s take=%s index=%s "
                    "version=%s families=%s",
                    arc_id, _arm_sid, _take_index, _version_int,
                    [key.get("feedback_family") for key in _keys])
                changes, _styles = [], []
            else:
                _feedback_set = claim_feedback_set(
                    db,
                    arc_id=str(arc_id),
                    owner_user_id=str(user_id),
                    take_session_id=_arm_sid,
                    take_index=_take_index,
                    review_version=_version_int,
                    changes=_combined,
                )
                if _feedback_set is None:
                    logger.error(
                        "feedback set claim failed arc=%s take=%s",
                        arc_id, _arm_sid)
                    changes, _styles = [], []
                else:
                    from services.take_feedback_manager import POLICY_VERSION
                    _selected_ids = {
                        str(key.get("id") or "")
                        for key in _feedback_set["selected_keys"]
                    }
                    for _snapshot_row in _feedback_exposure:
                        _snapshot_row["selected"] = (
                            str(_snapshot_row.get("id") or "")
                            in _selected_ids
                        )
                    db.insert_take_feedback_exposure(
                        arc_id=str(arc_id),
                        take_session_id=_arm_sid,
                        review_version=_version_int,
                        policy_version=POLICY_VERSION,
                        candidate_set=_feedback_exposure,
                        selected_keys=_feedback_set["selected_keys"],
                    )
                    changes = filter_to_selected(
                        changes, _feedback_set["selected_keys"])
                    _styles = filter_to_selected(
                        _styles, _feedback_set["selected_keys"])
        # CANONICAL DUAL-WRITE / BACKFILL-ON-READ. This deliberately runs for
        # both a newly claimed compatibility set and an already frozen set.
        # During a backend-first rollout the canonical migration may be
        # briefly unavailable on the first GET; limiting this write to the
        # claim branch would then leave a permanent provenance hole because
        # the compatibility set is insert-once. The canonical RPC is itself
        # idempotent, so every later read safely ensures parity without
        # changing membership or user-visible behavior.
        from services.take_lifecycle import confidence_canonical_writes_enabled

        if (_feedback_set is not None and _take_contract_on and _arm_sid
                and not confidence_canonical_writes_enabled()):
            try:
                from services.feedback_data_contract import (
                    build_feedback_exposure_bundle,
                )
                from services.take_feedback_manager import POLICY_VERSION

                _canonical_session = locals().get("_session")
                if not isinstance(_canonical_session, dict):
                    _canonical_session = db.v2_get_session_by_id(
                        _arm_sid) or {}
                _selected_ids = {
                    str(key.get("id") or "")
                    for key in _feedback_set["selected_keys"]
                }
                for _snapshot_row in _feedback_exposure:
                    _snapshot_row["selected"] = (
                        str(_snapshot_row.get("id") or "")
                        in _selected_ids
                    )
                _canonical_doc = locals().get("_review_doc")
                if not isinstance(_canonical_doc, dict):
                    _canonical_doc = build_transcript_document(
                        arc_id, database=db, session_id=_arm_sid)
                _canonical_bundle = build_feedback_exposure_bundle(
                    session=_canonical_session,
                    transcript_document=_canonical_doc,
                    served_text=served_text,
                    candidates=_feedback_exposure,
                    selected_keys=_feedback_set["selected_keys"],
                    manager_rules_version=POLICY_VERSION,
                )
                if _canonical_bundle is None:
                    logger.warning(
                        "canonical feedback bundle unavailable "
                        "arc=%s take=%s", arc_id, _arm_sid,
                    )
                else:
                    _canonical_result = db.record_canonical_feedback_exposure(
                        _canonical_bundle)
                    if _canonical_result is None:
                        logger.warning(
                            "canonical feedback dual-write missing "
                            "arc=%s take=%s", arc_id, _arm_sid,
                        )
                    else:
                        try:
                            from services.learning_exposures import (
                                prepare_feedback_presentations,
                            )

                            _learning_presentations = (
                                prepare_feedback_presentations(
                                    database=db,
                                    bundle=_canonical_bundle,
                                    actor_id=str(user_id),
                                    delivery_mode="canary",
                                )
                            )
                        except Exception as _presentation_error:
                            # The feedback remains a valid product result, but
                            # it is not silently counted as exposed learning
                            # data. Readiness reports the missing ACK coverage.
                            logger.warning(
                                "learning presentation preparation failed "
                                "arc=%s take=%s: %s",
                                arc_id, _arm_sid, _presentation_error,
                            )
                        # Selection and exposure are separate durable stages:
                        # the first proves which three won, the second proves
                        # the complete selected/unselected ledger committed.
                        from services.processing_stages import (
                            recorder_for_take,
                        )
                        _feedback_stage_recorder = recorder_for_take(
                            database=db,
                            session=_canonical_session,
                            input_provenance={
                                "candidate_set_id": _canonical_bundle[
                                    "candidate_set_id"],
                                "input_hash": _canonical_bundle["input_hash"],
                            },
                        )
                        if _feedback_stage_recorder is not None:
                            _feedback_stage_recorder.record(
                                "manager_selection", "succeeded",
                                output=_feedback_set["selected_keys"],
                            )
                            _feedback_stage_recorder.record(
                                "exposure", "succeeded",
                                output={
                                    "candidate_set_id": _canonical_result.get(
                                        "candidate_set_id"),
                                    "candidate_count": len(
                                        _canonical_bundle["candidates"]),
                                    "selected_count": 3,
                                },
                            )
                        # If this GET just repaired a missing canonical
                        # exposure, replay any already-final compatibility
                        # responses now as well; one reopen reaches parity.
                        from services.feedback_data_contract import (
                            canonical_feedback_decision,
                        )
                        for _response_row in locals().get(
                                "_response_rows", []) or []:
                            if not isinstance(_response_row, dict):
                                continue
                            _canonical_decision = canonical_feedback_decision(
                                take_id=_arm_sid,
                                rater_id=str(user_id),
                                feedback_id=str(
                                    _response_row.get("feedback_id") or ""),
                                feedback_family=str(
                                    _response_row.get("feedback_family") or ""),
                                response=str(
                                    _response_row.get("response") or ""),
                            )
                            if _canonical_decision is not None:
                                db.record_canonical_feedback_decision(
                                    project_id=str(
                                        _canonical_session["project_id"]),
                                    take_id=_arm_sid,
                                    rater_id=str(user_id),
                                    decision=_canonical_decision,
                                )
            except Exception as _canonical_feedback_error:
                logger.warning(
                    "canonical feedback dual-write failed arc=%s "
                    "take=%s: %s", arc_id, _arm_sid,
                    _canonical_feedback_error,
                )
        _style = {"style_changes": _styles} if _styles else {}
        # THE EXPERIMENT'S RECORD — after the span check on purpose: a row
        # stamped surfaced=True for a serve the guard then zeroed would claim
        # notes the student never saw. Only when the arms actually ran: rows
        # written with the controls inert would stamp the policy (gamma,
        # withhold_rate) as if an assignment had happened when none did.
        if ((changes or _styles) and _sel.get("controls")
                and _sel.get("result") is not None):
            _record_arms(_sel["result"], _arm_sid, user_id)
        from services.take_feedback_manager import strip_internal_evidence
        changes = strip_internal_evidence(changes)
        _styles = strip_internal_evidence(_styles)
        for _visible_row in [*changes, *_styles]:
            _visible_key = str(_visible_row.get("id") or "")
            _packets = _learning_presentations.get(_visible_key) or []
            if _packets:
                _visible_row["learning_exposures"] = _packets
        _style = {"style_changes": _styles} if _styles else {}
        return {"changes": changes, **_add, **_style}
    except Exception as e:
        logger.warning("tracked changes failed arc=%s: %s", arc_id, e)
        return {}


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

    R3 — a part with UNDECIDED interventions cannot be locked, and R5 applies it
    in reverse for unlock. Locking makes composition illegal on this part, so a
    pending rewrite there becomes unreachable — the alternative, auto-
    disregarding it, would write a decision the student never made into the one
    signal §6 depends on. Undecided is a real third state (R4), not a refusal.

    200 {locked, part_id} · 400 · 404 · 409 STALE_DOCUMENT / UNDECIDED · 500
    """
    try:
        from services.ideal_text_parts import agrees_with_text, part_spans
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
        if not parts:
            # Either no identity is stored, or it no longer describes this
            # document. Both mean the same thing to the caller: refetch.
            return jsonify({"code": "STALE_DOCUMENT",
                            "error": "document moved"}), 409
        if not agrees_with_text(parts, echo):
            return jsonify({"code": "STALE_DOCUMENT",
                            "error": "document moved"}), 409
        target = next((p for p in parts if p["id"] == str(part_id).lower()),
                      None)
        if target is None:
            return jsonify({"code": "NOT_FOUND", "error": "part not found"}), 404

        # R3 / R5 — is anything on this part still undecided?
        #
        # DERIVED FROM THE SERVED INTERVENTIONS, not from a second count.
        # Every lane already drops what the student decided (`applied` ids, the
        # cross-take ledger, settled blocks), so a change still on screen IS an
        # undecided one. Reading the same pipeline the student is looking at is
        # what stops the gate and the button disagreeing.
        try:
            # THE SAME ARBITRATION KEY AS THE SERVE — without it this gate
            # runs a different policy than the screen: the withhold arm
            # never fires on an empty session key, and the take's spent
            # budget counts a different epoch, so the gate could see three
            # changes where the student sees two and 409 a lock the screen
            # says is ready.
            from services.intervention_spend import latest_spoken_take_sid
            _lock_review_version = (
                (db.get_coach_arc_ideal_text(arc_id) or {}).get("version")
            )
            _served = (_tracked_changes_block(
                arc_id,
                echo,
                user_id,
                latest_spoken_take_sid(_lock_sessions),
                review_version=_lock_review_version,
            )
                .get("changes") or [])
            _lo, _hi, _ = next(
                (s for s in part_spans(parts) if s[2]["id"] == target["id"]),
                (None, None, None))
            _pending = [
                c for c in _served
                if _lo is not None
                and c.get("span", {}).get("start", -1) >= _lo
                and c.get("span", {}).get("end", -1) <= _hi
            ]
        except Exception as _pe:
            # A gate that cannot read the interventions must not pass. Locking
            # over an unknown pending set is precisely the corruption R3 exists
            # to prevent.
            logger.warning("part lock gate failed arc=%s: %s", arc_id, _pe)
            return jsonify({"code": "V2_ERROR",
                            "error": "Could not check this part — "
                                     "try again."}), 500
        if _pending:
            return jsonify({
                "code": "UNDECIDED",
                "error": "decide every suggestion on this part first",
                "pending": len(_pending),
            }), 409

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


@v2_bp.route("/explore/arc/<arc_id>/parts/<part_id>/root", methods=["PUT"])
@require_auth
def v2_explore_set_part_root(arc_id, part_id):
    """Accept, replace, or skip the orange exact-span prompt after a lock."""
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
        if not target.get("locked"):
            return jsonify({"code": "PART_NOT_LOCKED",
                            "error": "Lock this paragraph first."}), 409
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
                    "error": "Choose exact words from this locked paragraph.",
                }), 400
        if not db.set_ideal_text_part_root(
                arc_id=arc_id, user_id=user_id, part_id=str(part_id),
                phrase=(valid or {}).get("text"),
                start=(valid or {}).get("start"),
                end=(valid or {}).get("end")):
            return jsonify({"code": "V2_ERROR",
                            "error": "Could not save the rooting phrase"}), 500
        try:
            from services.feedback_data_contract import (
                canonical_root_phrase,
                canonical_root_phrase_skip,
                content_hash,
            )
            from services.intervention_spend import latest_spoken_take_sid

            _root_take_id = latest_spoken_take_sid(_sessions)
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
        body = request.get_json(silent=True) or {}
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

        # ── PARTS (SPEC-parts-locking-and-layers §3.1, Step 0). OPTIONAL: an
        # absent key is today's behaviour byte for byte. Present, it carries
        # the document's IDENTITY — the stable ids a lock will hang on in
        # PR 3 — and `text` must be its join.
        #
        # REFUSED, NEVER REPAIRED, and never accepted in part. Storing parts
        # that disagree with the stored text would leave an identity map
        # pointing at words the student is not looking at, and a lock set
        # against it would guard the wrong paragraph. That is unrecoverable
        # once written, because a wrong anchor is indistinguishable from a
        # right one afterwards — the same argument that refuses a mis-pointed
        # tracked change (#219) rather than nudging it into place.
        #
        # Each part is stripped with the SAME expression as `text`, on the
        # adjacent line, because the two must survive identically or the join
        # check fails on a document that is actually fine. ──
        _parts = None
        if "parts" in body:
            from services.ideal_text_parts import (
                InvalidParts, agrees_with_text, validate,
            )
            _raw = body.get("parts")
            if isinstance(_raw, list):
                _raw = [
                    {**p, "text": re.sub(r"<[^>]*>", "", p.get("text"))}
                    if isinstance(p, dict) and isinstance(p.get("text"), str)
                    else p
                    for p in _raw
                ]
            try:
                _parts = validate(_raw)
            except InvalidParts as e:
                return jsonify({"code": "INVALID_INPUT",
                                "error": str(e)}), 400
            if not agrees_with_text(_parts, text):
                return jsonify({
                    "code": "INVALID_INPUT",
                    "error": "parts do not join to text",
                }), 400

        # The current version — the edit only sticks against it. A newer
        # version having assembled since → 409 so the FE refetches + re-offers.
        _row = db.get_coach_arc_ideal_text(arc_id) or {}
        _machine = ((_row.get("auto_text") or "").strip()
                    or ((_row.get("text") or "").strip()
                        if not (_row.get("updated_by")
                                or _row.get("approved_at")) else ""))
        current = _row.get("version") or (1 if _machine else None)
        if not isinstance(current, int):
            return jsonify({"code": "NOTHING_TO_EDIT",
                            "error": "No ideal text to edit yet."}), 409
        if _v != current:
            return jsonify({
                "code": "VERSION_SUPERSEDED",
                "current_version": current,
            }), 409

        ok = db.upsert_user_ideal_edit(
            arc_id, str(request.user_id), text, current)
        if not ok:
            return jsonify({"code": "V2_ERROR",
                            "error": "Could not save"}), 500
        # Identity follows the words, and only AFTER they landed. Writing
        # parts first would leave ids for a document that failed to save.
        # Best-effort in the other direction: the words are what matter, so a
        # parts write that fails does not fail the edit — the GET then omits
        # the key, the FE re-mints, and the next save stores them.
        #
        # EXPLICIT VERSION STATE (founder 2026-08-26): editing and locking are
        # separate. A current client sends `locked` on every Paragraph; false
        # reopens the same identity after its words change, true preserves the
        # original commit timestamp. Older clients omit the field, so omission
        # preserves the stored lock instead of silently changing it. The whole
        # write is version-gated above, preventing stale state from reopening a
        # newer document.
        if _parts is not None:
            try:
                _prev_lk = {
                    str(r.get("id")): r.get("locked_at")
                    for r in (db.get_ideal_text_parts(
                        arc_id, str(request.user_id), with_lock=True) or [])
                    if isinstance(r, dict) and r.get("locked_at")}
            except Exception:
                _prev_lk = {}
            _rows = []
            for p in _parts:
                _previous_lock = _prev_lk.get(p["id"])
                if "locked" not in p:
                    _locked_at = _previous_lock
                elif p.get("locked"):
                    _locked_at = (_previous_lock
                                  or datetime.now(timezone.utc).isoformat())
                else:
                    _locked_at = None
                _rows.append({**p, "locked_at": _locked_at})
            if not db.replace_ideal_text_parts(
                    arc_id, str(request.user_id), _rows,
                    revision_action="user_edit"):
                logger.warning("ideal parts not stored arc=%s", arc_id)
        # RE-APPLY TELEMETRY (founder 2026-07-28): one log line per
        # successful one-click re-apply of a superseded edit — the
        # decision metric for the PARKED versioning change (how often do
        # users re-apply an addition a new take dropped?). Log-only:
        # never persisted, never surfaced; only boolean true counts.
        if body.get("reapplied") is True:
            logger.info("ideal_edit.reapplied arc=%s version=%s chars=%d",
                        arc_id, current, len(text))
        # ── EDIT INHERITANCE (founder 2026-07-20, rule 4b): decompose the
        # edit into phrase decisions on the ledger (source='user_edit',
        # approved) so the NEXT version bakes the student's wording
        # forward — their edit is never reversed by a new take. The base
        # is the version's served base (verified snapshot when current,
        # else the machine copy); a wholesale rewrite decomposes to
        # nothing and simply stays the wholesale edit. Best-effort. ──
        try:
            _vv = _row.get("verified_version")
            _vtext = (_row.get("verified_text") or "").strip()
            _base = _vtext if (_vv == current and _vtext) else _machine
            if _base:
                from services.protected_phrases import (
                    record_user_edit_decisions,
                )
                record_user_edit_decisions(
                    db, arc_id, base_text=_base, user_text=text,
                    version=current)
        except Exception as _led_err:
            logger.warning("ideal user-edit: ledger failed arc=%s: %s",
                           arc_id, _led_err)
        # ── VARIANT CAPTURE (founder 2026-08-03, fear #1): under the
        # master model the edit ALSO lands BLOCK-LEVEL in the variant
        # pool (source='user_edit') — a first-class picker citizen a new
        # take can never supersede, beside the whole-blob lane above.
        # Only when the base the student edited against IS the master
        # text (a verified snapshot that diverged would make the diff
        # attribute coach changes to the student). Best-effort. ──
        try:
            from services.master_document import (
                assemble_master_document, master_document_enabled,
            )
            if master_document_enabled():
                _m = assemble_master_document(arc_id, database=db)
                _mtext = (_m.get("text") or "")
                _vbase = ((_row.get("verified_text") or "").strip()
                          if _row.get("verified_version") == current
                          else "") or _machine
                if _m.get("ready") and _mtext and _vbase and \
                        re.sub(r"\s+", " ", _mtext).strip().lower() == \
                        re.sub(r"\s+", " ", _vbase).strip().lower():
                    from services.ideal_text_variants import (
                        capture_user_edit_variants,
                    )
                    capture_user_edit_variants(
                        db, str(arc_id), str(request.user_id), _mtext,
                        ((_m.get("document") or {}).get("pieces") or []),
                        text)
        except Exception as _var_err:
            logger.warning("ideal user-edit: variant capture failed "
                           "arc=%s: %s", arc_id, _var_err)
        return jsonify({"saved": True, "arc_id": arc_id,
                        "version": current}), 200
    except Exception as e:
        logger.error("ideal user-edit PUT failed arc=%s: %s", arc_id, e,
                     exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to save"}), 500
