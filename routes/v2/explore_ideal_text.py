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
from services.rate_limits import llm_limit

logger = logging.getLogger(__name__)
config = Config()


@v2_bp.route("/talks/<talk_id>/ideal-text", methods=["GET"])
@require_auth
def v2_talk_ideal_text(talk_id):
    """The Ideal-Text report for a talk (Paid Audits A7). A talk IS an arc, so
    talk_id == arc_id.

    Ownership-gated + paywall (the report is the paid deliverable). L1: the
    idealText is the verbatim-selected best take of each slide, never re-
    summarised — but it is a COACH correction now (founder 2026-07-06): the
    raw auto-assembled draft is NEVER served here. ``coachFinalized`` is a
    SEPARATE, harder gate on content past the 402 — every slide's idealText is
    "" until the coach has corrected EVERY slide, regardless of payment. The
    FE shows "still being prepared by your coach" when paid but not finalized.
    AC-9: no score/verdict.

    Response 200 { talkId, talkTitle, ready, coachReviewed, coachFinalized,
                   presentationRef,
                   slides:[ {index, label, title, body, thumbnailUrl,
                             idealText, takeRoute, breakthrough} ] }
             402 PAYMENT_REQUIRED · 404 NOT_FOUND · 500 V2_ERROR
    """
    try:
        from services.ideal_text_report import build_ideal_text_report
        owned, _ = _arc_owned_by_caller(talk_id)
        if not owned:
            return jsonify({"code": "NOT_FOUND", "error": "talk not found"}), 404
        # Past the gate → entitled (or admin/coach); echo audit_paid (Phase-1).
        return jsonify({
            "audit_paid": True, **build_ideal_text_report(talk_id),
        }), 200
    except Exception as e:
        logger.error("talk ideal-text failed talk=%s: %s", talk_id, e,
                     exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR", "error": "Failed to build ideal text",
        }), 500


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


def _ideal_piece_provenance(arc_id):
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
            out = []
            for r in rows:
                inc = r.get("incumbent_pieces") or []
                out.append({
                    "slide_index": r.get("slide_index"),
                    # The KEYED pill→picker join (FE picker handoff
                    # 2026-08-03): the FE deep-links a paragraph's pill
                    # into the variants sheet by block_key — never by
                    # index-zipping two lists that merely happen to be
                    # sorted the same way.
                    "block_key": r.get("block_key"),
                    "snippet_id": (inc[0].get("snippet_id")
                                   if inc else None),
                    "take_session_id": r.get("incumbent_take_session_id"),
                    "take_index": r.get("incumbent_take_index"),
                    "status": r.get("status") or "settled",
                    "challenger": r.get("challenger_take_index"),
                })
            return out
        # No skeleton yet → the living-transcript document, exactly the
        # fallback the assembly itself makes.
    if _living_transcript_enabled():
        from services.transcript_document import build_transcript_document
        doc = build_transcript_document(arc_id, database=db)
        pieces = (doc or {}).get("pieces") or []
        if not pieces:
            return []
        sid = doc.get("take_session_id")
        snips = {str(s.get("id")): s
                 for s in (db.get_snippets_by_session(sid) or [])} \
            if sid else {}
        return [{
            "slide_index": _snip_slide(snips.get(str(p.get("snippet_id")))),
            "snippet_id": p.get("snippet_id"),
            "take_session_id": p.get("take_session_id"),
            "take_index": p.get("take_index"),
            "status": "settled",
            "challenger": None,
        } for p in pieces]
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


def _ideal_text_pieces(arc_id, served_text, presentation_ref):
    """The slide-linkage `pieces[]` of the SD student GET (FE handoff
    2026-08-03, FE PR #222): one entry per "\\n\\n"-paragraph of the
    SERVED text, each carrying the deck page its words were bucketed to.

    `slide_index` attaches ONLY when the mapping is structural — the
    machine assembly's piece list lines up 1:1 with the served
    paragraphs (the FE's own provability bar: it zips or hides on
    anything weaker). A reshaped text (user rewrite, coach restructure,
    stale cache) misaligns the counts and every slide_index degrades to
    null — the FE falls back to its exact-count zip, never a guessed
    attachment. A deckless arc (no presentation_ref) never attaches:
    the deckless compose keys picks by SECTION index, which is not a
    deck page. Provenance only, no scores (AC-9). Best-effort; []."""
    try:
        paragraphs = [p.strip() for p in (served_text or "").split("\n\n")
                      if p.strip()]
        if not paragraphs:
            return []
        prov = _ideal_piece_provenance(arc_id) if presentation_ref else []
        aligned = bool(prov) and len(prov) == len(paragraphs)
        out = []
        for i, para in enumerate(paragraphs):
            src = prov[i] if aligned else {}
            si = src.get("slide_index")
            if isinstance(si, bool) or not isinstance(si, int) or si < 0:
                si = None
            _snip = src.get("snippet_id")
            _sess = src.get("take_session_id")
            _bk = src.get("block_key")
            out.append({
                "piece_key": i,
                "text": para,
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
        _r = row or {}
        _coach_owned = bool(_r.get("updated_by") or _r.get("approved_at"))
        _machine = ((_r.get("auto_text") or "").strip()
                    or ((_r.get("text") or "").strip()
                        if not _coach_owned else ""))
        _version = _r.get("version") or (1 if _machine else None)

        # ── HISTORICAL view, ?version=N (founder 2026-07-20): an old
        # version bubble opens ITS OWN step — the frozen text + that
        # step's reasoning, read-only. N == current falls through to
        # the live notebook. No snapshot (pre-migration / assembled
        # before history existed) → historical_unavailable and the FE
        # falls back to the live view. Free, owner-only (same gate as
        # the live read). ──
        _hv_raw = request.args.get("version")
        if _hv_raw not in (None, ""):
            try:
                _hv = int(_hv_raw)
            except (TypeError, ValueError):
                return jsonify({
                    "code": "INVALID_INPUT",
                    "error": "version must be an integer",
                }), 400
            if _version is None or _hv != _version:
                _snap = db.get_ideal_text_version(arc_id, _hv)
                if not _snap or not (_snap.get("text") or "").strip():
                    return jsonify({
                        "arc_id": arc_id,
                        "historical_unavailable": True,
                        "requested_version": _hv,
                        "current_version": _version,
                    }), 200
                from services.ideal_text_block import (
                    extract_key_moments, sanitize_markers,
                    strip_moment_markers,
                )
                _s_text = _snap["text"]
                _s_moments = extract_key_moments(_s_text)
                _s_sugs = {
                    str(m.get("snippet_id")): m
                    for m in (_snap.get("moments") or [])
                    if isinstance(m, dict) and m.get("snippet_id")
                }
                # The star is EXPLICIT on historical payloads too (FE
                # relay 2026-07-20): the device guard is BE-owned
                # contract logic (#218/#219 pin — the FE renders copy
                # purely from device and must never infer star
                # semantics). Same rule as live: an unknown kind or
                # device yields NO star and NO suggestion.
                from services.delivery_stars import (
                    DELIVERY_DEVICES as _H_DELIVERY,
                )
                from services.moment_suggestions import (
                    _STRUCT_DEVICES as _H_STRUCT,
                )
                _s_out = []
                for m in _s_moments:
                    _e = {
                        "id": m.get("snippet_id"),
                        "snippet_id": m.get("snippet_id"),
                        "anchor": m.get("anchor") or "",
                        "take_session_id": m.get("take_session_id"),
                    }
                    _sm = _s_sugs.get(str(m.get("snippet_id")))
                    if _sm:
                        _kind = _sm.get("kind")
                        _dev = _sm.get("device")
                        _star_ok = (
                            _kind in ("emphasize", "replace")
                            or (_kind == "structure"
                                and _dev in _H_STRUCT)
                            or (_kind == "delivery"
                                and _dev in _H_DELIVERY)
                        )
                        if _star_ok:
                            _e["star"] = "suggestion"
                            _e["suggestion"] = {
                                k: _sm.get(k)
                                for k in ("kind", "device", "quote",
                                          "replacement", "why",
                                          "trigger")
                                if k in _sm
                            }
                    _s_out.append(_e)
                return jsonify({
                    "arc_id": arc_id,
                    "version": _hv,
                    "historical": True,
                    "status": "superseded",
                    "current_version": _version,
                    "created_at": _snap.get("created_at"),
                    # A snapshot was baked before wrap_accent existed, so
                    # an old version can still carry a newline-straddling
                    # accent — sanitize on the way out too.
                    "text": sanitize_markers(strip_moment_markers(_s_text)),
                    "key_moments": _s_out,
                }), 200
        _vv = _r.get("verified_version")
        _vtext = (_r.get("verified_text") or "").strip()
        _verified = bool(_version is not None
                         and _vv == _version and _vtext)
        _base_text = _vtext if _verified else _machine
        # The student's in-place edit WINS display while it was made
        # against the CURRENT version (BE-2). A new take supersedes it —
        # the edit is retained (coach signal) but the fresh machine text
        # shows. `status` still reflects the coach's verification of the
        # version, independent of the student's own tweaks on top.
        _edit = db.get_user_ideal_edit(arc_id, request.user_id)
        _user_edited = bool(
            _edit and _version is not None
            and _edit.get("version") == _version
            and (_edit.get("text") or "").strip())
        _text = _edit["text"] if _user_edited else _base_text
        # ── SUPERSEDED-EDIT RE-OFFER (founder 2026-07-28): when a newer
        # version has superseded the student's edit, serve the retained
        # copy as `prior_edit` so the FE can offer one-click "re-apply
        # your additions" across reload / device switch. The lane
        # semantics are UNCHANGED (the versioning change stays parked:
        # additions/moves never bake forward) — this only exposes the
        # already-retained row to its owner. Best-effort: absent on any
        # hiccup, never breaks the GET. Owner-keyed by the read above.
        _prior_edit = None
        try:
            if not _user_edited and _edit and _version is not None:
                _pe_text = (_edit.get("text") or "").strip()
                _pe_ver = _edit.get("version")
                if _pe_text and isinstance(_pe_ver, int) \
                        and not isinstance(_pe_ver, bool) \
                        and _pe_ver != _version:
                    _prior_edit = {"text": _pe_text, "version": _pe_ver}
        except Exception:
            _prior_edit = None
        from services.ideal_text_block import extract_key_moments

        # ── Star suggestions (2026-07-18, flag-gated). Fold APPLIED
        # suggestions into the DISPLAYED text FIRST (unless the user's
        # free-form edit won — that wins wholesale), then extract the
        # anchors from the folded text so they always match what's
        # served. The canonical row is never touched (L1). ──
        _stars_on = _moment_suggestions_enabled()
        _sugs = db.get_moment_suggestions_by_arc(arc_id) \
            if _stars_on else {}
        # The ONLY two structural devices the FE has copy for — an
        # unknown spelling must yield no star (FE contract pin).
        from services.moment_suggestions import _STRUCT_DEVICES
        from services.delivery_stars import (
            DELIVERY_DEVICES as _DELIVERY_DEVICES,
        )
        _applied = {}
        if _stars_on and _sugs:
            _pre = extract_key_moments(_text)
            _applied = _moment_applied_map(
                [m.get("take_session_id") for m in _pre])
            if not _user_edited and _applied:
                _fold_info = []
                for m in _pre:
                    _mid = str(m.get("snippet_id"))
                    if _mid in _sugs and _applied.get(_mid):
                        _s = _sugs[_mid]
                        _fold_info.append({
                            "id": m.get("snippet_id"),
                            "take_session_id": m.get("take_session_id"),
                            "applied": True,
                            "suggestion": {
                                "kind": _s.get("kind"),
                                "replacement": _s.get("replacement_text"),
                            },
                        })
                _text = _fold_applied_moments(_text, _fold_info)

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
        _has_expl = _moment_explanations_map(
            [m.get("take_session_id") for m in _moments])
        _playback = _moment_playback_map(
            [m.get("take_session_id") for m in _moments])
        # Ticket 6: resolve every attached post ONCE per request, not once per
        # moment (see _moment_reference_map — the per-moment form is an N+1).
        # isinstance-guarded: this map's values are dicts in production, but
        # callers (and tests) legitimately hand back a truthy marker instead,
        # and a bare .get() there is an AttributeError that takes the whole
        # ideal-text response down with it.
        _refs = _moment_reference_map([
            v.get("reference_post_slug") if isinstance(v, dict) else None
            for v in _has_expl.values()
        ])

        def _decorate(m):
            _mid = str(m.get("snippet_id"))
            entry = {
                "id": m.get("snippet_id"),
                # Both keys on purpose: `id` is the moment-explanation
                # identity, `snippet_id` is what the Approve/Revert
                # feedback POST keys on (audit 2026-07-18 — its absence
                # sent an EMPTY snippet id and Approve never persisted).
                "snippet_id": m.get("snippet_id"),
                # The literal text fragment the FE underlines + taps
                # (SD contract pin — a moment with no anchor is dropped).
                "anchor": m.get("anchor") or "",
                "take_session_id": m.get("take_session_id"),
                "has_explanation": bool(_has_expl.get(_mid)),
                # FREE playback of the student's own recording (parent+
                # offset → the FE clamps to [start, start+duration]).
                **(_playback.get(_mid) or {}),
            }
            if not _stars_on:
                return entry
            if _has_expl.get(_mid):
                # Coach override wins: the ORANGE verified star —
                # permanent, re-openable; message content stays behind
                # the paid moments GET.
                entry["star"] = "verified"
                entry["coach"] = {
                    "has_message": True,
                    "has_video": bool(
                        _has_expl[_mid].get("has_video")),
                }
                # Ticket 6: further reading the coach attached to THIS moment.
                # Key omitted entirely when there is none, or when the post is
                # no longer published — the FE renders the link only when the
                # key is present. Not gated behind the paid moments GET: a
                # public blog link is not the coach's message.
                _expl = _has_expl[_mid]
                _slug = _expl.get("reference_post_slug") if isinstance(_expl, dict) else None
                _ref = _refs.get(_slug.strip()) if isinstance(_slug, str) else None
                if _ref:
                    entry["coach"]["reference"] = _ref
            elif _mid in _sugs and _sugs[_mid].get("kind") == "delivery" \
                    and _sugs[_mid].get("trigger") in _DELIVERY_DEVICES:
                # MEASURED delivery star (founder decisions 2026-07-18):
                # a behavioural prompt, not an edit — no approve/fold;
                # the modal's action is the FE's snippet re-record mic.
                # The FE renders the approved copy PURELY from `device`
                # (same pinned dependency as structural: unknown device
                # → no star), and nothing numeric rides this payload
                # (AC-9: the z-scores stay server-side).
                entry["star"] = "suggestion"
                entry["suggestion"] = {
                    "kind": "delivery",
                    "device": _sugs[_mid].get("trigger"),
                    "quote": None,
                    "why": None,
                }
            elif _mid in _sugs and _sugs[_mid].get("kind") == "structure" \
                    and _sugs[_mid].get("trigger") in _STRUCT_DEVICES:
                # STRUCTURAL star (founder 2026-07-18): a delivery
                # prompt, not an edit — never applied, never folded,
                # always shown. The FE renders fixed signed-off copy
                # from `device`; NO generated prose is served. `quote`
                # is the user's own verbatim words.
                # The device guard is the FE's pinned dependency: it
                # renders the sheet copy PURELY from `device`, so an
                # unknown spelling must yield NO star rather than a
                # star with no copy behind it.
                _s = _sugs[_mid]
                entry["star"] = "suggestion"
                entry["suggestion"] = {
                    "kind": "structure",
                    "device": _s.get("trigger"),
                    "quote": _s.get("why"),
                    "why": None,
                }
            elif _mid in _sugs \
                    and _sugs[_mid].get("kind") not in (
                        "structure", "delivery") \
                    and not _applied.get(_mid):
                # TEXT suggestions only — a structure/delivery row with
                # an unknown device must yield NO star (the FE renders
                # copy purely from device), never fall through here.
                # An APPLIED suggestion is CONSUMED: its result is
                # already folded into the served text, so no star is
                # emitted (audit 2026-07-18 — the FE documents exactly
                # this expectation; keeping the star re-offered work
                # the student had already accepted).
                _s = _sugs[_mid]
                # Quote narrowing (founder 2026-07-20): underline the
                # PHRASE, not the piece. Deterministic per trigger —
                # polish → the trimmed verbatim-vs-polished diff span;
                # a profanity replace → the carrying sentence; anything
                # else → None = star icon only, NO underline (the FE
                # contract). Guarded: a quote must be an exact
                # substring of the anchor (and so of the served text)
                # or it is dropped (the #219 lesson).
                _anchor_txt = m.get("anchor") or ""
                _quote = None
                try:
                    from services.suggestion_quotes import (
                        diff_quote, profanity_sentence,
                    )
                    from services.text_flags import has_profanity
                    if _s.get("trigger") == "polish":
                        _quote = diff_quote(
                            _anchor_txt, _s.get("replacement_text"))
                    elif _s.get("kind") == "replace" \
                            and has_profanity(_anchor_txt):
                        _quote = profanity_sentence(_anchor_txt)
                except Exception:
                    _quote = None
                if _quote and _quote not in _anchor_txt:
                    _quote = None
                entry["star"] = "suggestion"
                entry["suggestion"] = {
                    "kind": _s.get("kind"),
                    "quote": _quote,
                    "replacement": _s.get("replacement_text"),
                    "why": _s.get("why"),
                    # CLAMPED to 'polish'|None (adversarial review
                    # 2026-07-18): the FE only needs to distinguish a
                    # flow-polish replace from the rest; the raw trigger
                    # vocabulary (threat/charisma/…) is INTERNAL —
                    # surfacing it would breach the CONSTRUCT/AC-9
                    # fences (a classifier verdict on a user payload).
                    "trigger": ("polish" if _s.get("trigger") == "polish"
                                else None),
                }
                entry["applied"] = False
            return entry

        _notes = db.get_user_arc_ideal_notes(arc_id, request.user_id)

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
        _spoken_rows = [
            _s for _s in (_sessions or [])
            if _s.get("recording_kind") != "read"
            and not _s.get("paired_session_id")
        ]
        _spoken_rows.sort(key=lambda s: (s.get("take_index") or 0))
        _title = None
        for _s in _spoken_rows:   # latest take wins (trainings parity)
            _ctx = _s.get("intake_context") if isinstance(
                _s.get("intake_context"), dict) else {}
            _t = _ctx.get("topic")
            if isinstance(_t, str) and _t.strip():
                _title = _t.strip()
        _latest_take_sid = (str(_spoken_rows[-1].get("id"))
                            if _spoken_rows else None)
        # ── NEXT TAKE (founder 2026-07-24, T1 · 1.2): available the
        # moment this project has a spoken take, so a finished recording
        # drops the student straight back here ready to record again.
        # Same continuable-project rule as GET /explore/arc/<id>/setup,
        # so the two can never disagree about whether a take can start.
        _can_record_take = bool(_spoken_rows)

        # ── SLIDE LINKAGE (FE handoff 2026-08-03, FE PR #222): the deck
        # url + per-paragraph slide identity, so the reading view can
        # interleave slide → its words exactly, cross-device (the FE's
        # localStorage fallback only covered the recording device). The
        # FIRST non-null presentation_ref across takes in take order —
        # the same never-clobbered-by-a-deckless-retake resolution
        # build_best_presentation uses for its canonical deck ref. Zero
        # extra queries (the ownership read already has the sessions). ──
        _pres_ref = None
        for _s in _spoken_rows:
            _ctx = _s.get("intake_context") if isinstance(
                _s.get("intake_context"), dict) else {}
            if _ctx.get("presentation_ref"):
                _pres_ref = _ctx.get("presentation_ref")
                break

        return jsonify({
            "arc_id": arc_id,
            "version": _version,
            "status": "verified" if _verified else "unverified",
            "title": _title,
            "updated_at": _r.get("updated_at"),
            "latest_take_session_id": _latest_take_sid,
            # The project's OFFICIAL-TAKE count (founder 2026-07-23):
            # the FE renders the document badge as "<take_count>.0".
            # PER-PROJECT by construction (spoken takes of THIS arc;
            # reads excluded) — never a global tally, and it grows on
            # every recorded take (unlike `version`, which bumps only
            # when the text actually changes). continue_arc_id is what
            # keeps a new take appending here so this count climbs.
            "take_count": len(_spoken_rows),
            # IMMEDIATE next-take affordance (founder 2026-07-24, T1 ·
            # 1.2): the FE can offer "record another take" as soon as
            # this is true. True once the project has a spoken take
            # (same continuable-project rule as /setup).
            "can_record_take": _can_record_take,
            "text": _text,
            # The arc's served deck PDF (FE handoff 2026-08-03) — null on
            # a deckless arc; the FE treats anything but a non-empty
            # string as absent.
            "presentation_ref": _pres_ref or None,
            # One entry per "\n\n"-paragraph of `text`, carrying the deck
            # page (`slide_index`) its words were bucketed to when the
            # mapping is provable — null degrades the FE to its
            # exact-count zip, never a guessed attachment.
            "pieces": _ideal_text_pieces(arc_id, _text, _pres_ref),
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
            **_ideal_parts_block(arc_id, getattr(request, "user_id", ""),
                                 _text),
            # True when the served text is the student's own edit of the
            # current version (the FE labels it).
            "user_edited": _user_edited,
            # The retained edit a NEWER version superseded (founder
            # 2026-07-28) — the FE's one-click "re-apply your additions".
            # Absent when there is nothing to re-offer.
            **({"prior_edit": _prior_edit} if _prior_edit else {}),
            "key_moments": [_decorate(m) for m in _moments],
            "moments_unlocked": _moments_entitled(arc_id),
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
            **_tracked_changes_block(arc_id, _text,
                                     getattr(request, "user_id", "") or ""),
            # The moments-unlock price, top level (the FE reads it here
            # for the locked-moment prompt — the only paid item).
            "price_credits": int(getattr(
                config, "MOMENTS_UNLOCK_CREDITS", 5) or 5),
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
        owned, _ = _arc_owned_by_caller(arc_id)
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
        owned, _ = _arc_owned_by_caller(arc_id)
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
        _resolve_failed = False
        for r in rows:
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


def _tracked_changes_block(arc_id, served_text, user_id="") -> dict:
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
    `intervention_candidates.select`, which applies Appendix H's budget
    (≤3 per take, across every lane together) and collision resolution.
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
        from services.ideal_text_block import _living_transcript_enabled
        if not _living_transcript_enabled():
            return {}
        from services.intervention_candidates import select as _select
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
        _pieces = relocate_pieces(served_text, doc.get("pieces") or [])
        _sugs = db.get_moment_suggestions_by_arc(arc_id) or {}
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
            _emph_ids = [k for k, v in (_sugs or {}).items()
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
            served_text, _pieces, _sugs, applied=_applied,
            key_phrases_by_snippet=_kp_by_snip)

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
        # served. The manager applies the flat ≤3 budget across all of them
        # together, resolves collisions (which subsumes the old
        # `drop_overlaps` sweep — see intervention_candidates.select) and
        # returns the survivors in document order. A lane that is not
        # declared there does not reach the user. ──
        changes = _select(changes, user_id=user_id,
                          session_id=str(doc.get("take_session_id") or ""),
                          # R1 — the layer filter runs inside the gate, BEFORE
                          # the budget. A locked part takes accentuation only;
                          # an open one takes composition only.
                          parts=_locked_parts(arc_id, user_id, served_text),
                          )["changes"]
        # Additions ride OUTSIDE the budget and outside the span check — they
        # have no span. Absent when there are none, so the FE draws nothing
        # rather than an empty section. See master_document.block_additions for
        # why they are not arbitrated: the ≤3 is a load limit on FEEDBACK, and
        # this is material the speaker already said going missing from their
        # own script.
        _add = {"additions": _additions} if _additions else {}
        if not verify_changes(served_text, changes):
            logger.warning("tracked changes: span check failed arc=%s "
                           "(serving none)", arc_id)
            return {"changes": [], **_add}
        return {"changes": changes, **_add}
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
        owned, _ = _arc_owned_by_caller(arc_id)
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
            _served = (_tracked_changes_block(arc_id, echo, user_id)
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

        if not db.set_ideal_text_part_lock(arc_id, user_id, str(part_id),
                                           locked):
            return jsonify({"code": "V2_ERROR",
                            "error": "Could not save"}), 500
        return jsonify({"locked": locked, "part_id": str(part_id)}), 200
    except Exception as e:
        logger.error("part lock failed arc=%s part=%s: %s", arc_id, part_id, e,
                     exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR",
                        "error": "Failed to set the lock"}), 500


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
        if _parts is not None:
            if not db.replace_ideal_text_parts(
                    arc_id, str(request.user_id), _parts):
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
