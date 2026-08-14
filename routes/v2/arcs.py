"""The arc domain: an arc's lifecycle, entitlement, moments and setup.

  /v2/explore/*        enter an arc, its moments/breakthroughs/progress,
                       per-take feedback, setup + context document
  /v2/arc/*            checkout, redeem, unlock, unlock-moments, the game
                       + snippet-library stubs

Plus the arc leaves the other domain modules depend on: deck identity and
arc continuation (the Lab upload path), entitlement, and the moment maps the
ideal-text read folds in.

Moved verbatim out of ``routes/v2_routes.py`` (phases 1-2 for the helpers,
phase 4 for the routes); bodies are byte-identical. Routes register on the
SAME ``v2_bp`` object, so endpoint names and the URL map are unchanged.

Imported by routes/v2/explore_ideal_text.py, lab_recording.py, coach.py and
user_sessions.py -- so this module must never import from them.

Re-exported from ``routes.v2_routes`` for import compatibility.
"""
import hashlib
import logging
import os
import re

import sentry_sdk
from flask import jsonify, request

from auth import optional_auth, require_auth
from config import Config
from routes.admin import is_admin, is_coach
from routes.v2.blueprint import v2_bp
from routes.v2.common import _is_valid_uuid, _resolve_snippet_audio_url
from services.db import db

logger = logging.getLogger(__name__)
config = Config()


def _resolve_feedback_audio(ref):
    """One storage ref → a playable URL (services/audio_ref_resolver, the
    #378 bucket-authoritative branch hoisted — founder 2026-08-10: only
    the coach queue resolved while user surfaces served raw refs)."""
    from services.audio_ref_resolver import resolve_playable_ref
    return resolve_playable_ref(ref)


def _presentation_id_from_slides(slides) -> str:
    """Stable content hash of a deck's slides, independent of the served PDF
    URL (which changes on every re-upload). Same deck text → same id → same
    presentation group. Uses normalized title+body so cosmetic re-uploads
    don't split the take history."""
    if not slides:
        return ""
    parts = []
    for s in slides:
        if not isinstance(s, dict):
            continue
        t = (s.get("title") or "").strip()
        b = (s.get("body") or "").strip()
        parts.append(f"{t}\n{b}")
    canonical = "\n---\n".join(parts)
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:16]


def _continue_deck_arc(user_id, slides, fresh_arc_id, fresh_take_index):
    """Continue-one-arc (single-deliverable, founder 2026-07-17): every take of
    the SAME deck (same user) joins that deck's most-developed arc — takes
    append forever (the old 3-take batch cap is retired).

    Matches by the stable deck-hash across the user's lab sessions and continues
    the deck's MOST-developed arc (consistent with the /strengths group arc,
    #132). Returns (arc_id, take_index). Falls back to the freshly-minted arc
    for a NEW deck / deckless / guest / a full batch / any error — never raises
    into the record path. The current session is skipped because its arc_id
    isn't set yet.
    """
    if not user_id or not slides:
        return fresh_arc_id, fresh_take_index
    try:
        pid = _presentation_id_from_slides(slides)
        if not pid:
            return fresh_arc_id, fresh_take_index
        counts: dict = {}
        for s in (db.v2_list_user_lab_sessions(user_id) or []):
            ctx = s.get("intake_context") if isinstance(
                s.get("intake_context"), dict) else {}
            s_slides = (ctx or {}).get("slides") or []
            aid = s.get("arc_id")
            if not s_slides or not aid:
                continue
            if _presentation_id_from_slides(s_slides) == pid:
                counts[aid] = counts.get(aid, 0) + 1
        # Batch cap (founder re-lock 2026-07-11): only arcs with an OPEN
        # batch are joinable — the most-developed open one wins (so take 5
        # fills batch 2 instead of minting a third arc). All full → the
        # fresh arc starts the next batch, counter back to take 1.
        # SINGLE DELIVERABLE (founder re-shape 2026-07-17, cap lock
        # overturned): takes append to the presentation FOREVER — one deck =
        # one presentation; only a new deck/topic mints a new one.
        open_arcs = dict(counts)
        if not open_arcs:
            return fresh_arc_id, fresh_take_index
        best_arc = max(open_arcs.items(), key=lambda kv: kv[1])[0]
        return best_arc, open_arcs[best_arc] + 1
    except Exception as e:
        logger.warning("continue_deck_arc failed user=%s: %s", user_id, e)
        return fresh_arc_id, fresh_take_index


def _continue_topic_arc(user_id, topic, fresh_arc_id, fresh_take_index):
    """Continue-one-arc for DECKLESS takes (founder bug #4/#6, 2026-07-06):
    the conversational practice flow has no deck, so the deck-hash continue
    never matched and every take minted a FRESH arc — splitting one training
    across arcs (wrong counter, cadence mismatch, coach saw one take per arc).

    Same doctrine as _continue_deck_arc, keyed on the NORMALIZED TOPIC (the
    "same talk"): re-recording the same-titled talk joins its most-developed
    existing arc — takes append forever (the old 3-take batch cap is retired).
    New topic / guest / no topic / any error → the fresh arc.
    Never raises into the record path."""
    if not user_id or not isinstance(topic, str) or not topic.strip():
        return fresh_arc_id, fresh_take_index
    try:
        norm = " ".join(topic.strip().lower().split())
        counts: dict = {}
        for s in (db.v2_list_user_lab_sessions(user_id) or []):
            ctx = s.get("intake_context") if isinstance(
                s.get("intake_context"), dict) else {}
            s_topic = (ctx or {}).get("topic")
            aid = s.get("arc_id")
            if not aid or not isinstance(s_topic, str):
                continue
            # DECKLESS candidates only (review): a deckless take must not join
            # a DECK arc that happens to share the topic — mixing alignment-
            # less takes into a per-slide best-presentation arc.
            if (ctx or {}).get("slides"):
                continue
            if " ".join(s_topic.strip().lower().split()) == norm:
                counts[aid] = counts.get(aid, 0) + 1
        # Batch cap — same open-batch rule as _continue_deck_arc; lifted
        # entirely under the single deliverable (takes append forever).
        open_arcs = dict(counts)
        if not open_arcs:
            return fresh_arc_id, fresh_take_index
        best_arc = max(open_arcs.items(), key=lambda kv: kv[1])[0]
        return best_arc, open_arcs[best_arc] + 1
    except Exception as e:
        logger.warning("continue_topic_arc failed user=%s: %s", user_id, e)
        return fresh_arc_id, fresh_take_index


def _arc_audit_paid(arc_id, user_id):
    """Phase-1 per-arc paid flag (the FE's ``audit_paid``). True when the scope
    should be FULL: a non-arc / standalone session (no paywall concept), an
    admin/coach (always sees everything), or an entitled arc. False only for an
    unpaid arc — the free-take teaser scope."""
    from services.arc_entitlement import is_arc_entitled
    if not arc_id:
        return True
    if user_id and (is_admin(user_id) or is_coach(user_id)):
        return True
    return is_arc_entitled(db, arc_id, user_id)


def _spoken_takes_and_reads(sessions):
    """Split an arc's sessions into spoken takes (ordered by take_index) and
    a {spoken_session_id: [read_session, ...]} map — a take can carry SEVERAL
    mid-take re-reads and ALL of them fold into it (founder 2026-07-16),
    oldest first. Rows without recording_kind (pre-migration / legacy) read
    as spoken."""
    spoken, reads = [], {}
    for s in sessions:
        if (s.get("recording_kind") == "read") or s.get("paired_session_id"):
            if s.get("paired_session_id"):
                reads.setdefault(str(s.get("paired_session_id")), []).append(s)
        else:
            spoken.append(s)
    spoken.sort(key=lambda x: (x.get("take_index") or 0))
    for _lst in reads.values():
        _lst.sort(key=lambda x: (x.get("created_at") or ""))
    return spoken, reads


def _reassemble_after_decision(arc_id) -> None:
    """A decision that CHANGES the document must take effect at once
    (founder: "when I approve it the crossed text disappears and only
    the new one stays").

    The bake runs at ASSEMBLY, and the student GET serves the PERSISTED
    document — so without this an approval would only show up after the
    next take (the review's most-confirmed defect). Reassembling here
    re-bakes, re-anchors, bumps the version and snapshots it, exactly as
    a new take would. Best-effort: the decision is already saved."""
    try:
        from services.ideal_text_block import (
            _living_transcript_enabled, maybe_assemble_ideal_text,
        )
        if not _living_transcript_enabled():
            return
        maybe_assemble_ideal_text(str(arc_id), require_target=False)
    except Exception as e:
        logger.warning("living_transcript: post-decision reassembly "
                       "failed arc=%s: %s", arc_id, e)


@v2_bp.route("/explore/start", methods=["POST"])
@require_auth
def v2_explore_start():
    """Enter an explore session (willab Prompt A §6 C3 — BEAT 0 on-ramp).

    Mints the arc_id BEFORE take 1 and fires the framing cadence bubble
    (rendered in the user's language, goal-woven) so the FE never has to
    hardcode that copy (§7 language fence). The FE then POSTs the first
    /lab/recordings with this arc_id + take_index=1.

    Body (optional JSON): nothing required today; reserved for future
    spark/appetite hints.

    Response 200 { arc_id, take_index, take_count }.
    """
    try:
        from services.explore_arc import resolve_arc
        from services.session_cadence import fire_arc_start

        arc_id, take_index = resolve_arc(True, None, None)  # mint a fresh arc
        goal = (db.get_user_profile(request.user_id) or {}).get("goal")
        # Best-effort: the arc is valid even if the framing render fails.
        fire_arc_start(request.user_id, arc_id, goal=goal)
        return jsonify({
            "arc_id": arc_id,
            "take_index": take_index,
            "take_count": 0,
        }), 200
    except Exception as e:
        logger.error("explore/start failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to start explore session"}), 500


@v2_bp.route("/explore/arc/<arc_id>/moments", methods=["GET"])
@require_auth
def v2_explore_arc_moments(arc_id):
    """Cross-take selection payoff (willab Prompt A §5) — the arc's strongest
    material to study.

    The payload carries a `granularity` discriminator (§5.3) so the FE renders
    the matching surface:
      • "take" — each take's own strongest moments (§5.2; what ships today).
      • "line" — strongest delivery of EACH line (§5.1; behind the §5.0
        alignment gate, currently data-blocked / off).

    AC-9 (§7): score-FREE — text + audio + which take + a plain-language
    rationale; never a number, verdict, or trajectory.

    Ownership: the arc must contain a session owned by the caller, else 404
    (the arc_id is otherwise unattributable — explore takes are claimed to the
    user via the normal guest→signed claim flow).

    Response 200 { arc_id, granularity, take_count, takes:[...] }
             404 NOT_FOUND — no such arc for this user
             500 V2_ERROR
    """
    try:
        from services.cross_take_selection import select_cross_take
        sessions = db.get_arc_sessions(arc_id)
        owned = any(
            str(s.get("user_id")) == str(request.user_id) for s in sessions
        )
        if not owned:
            return jsonify({
                "code": "NOT_FOUND", "error": "arc not found",
            }), 404
        payload = select_cross_take(arc_id)
        return jsonify(payload), 200
    except Exception as e:
        logger.error("explore/arc moments failed arc=%s: %s", arc_id, e,
                     exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR", "error": "Failed to load arc moments",
        }), 500


def _arc_owned_by_caller(arc_id):
    """True iff the arc has a session owned by request.user_id. Returns
    (owned, sessions) so callers reuse the read."""
    sessions = db.get_arc_sessions(arc_id)
    owned = any(
        str(s.get("user_id")) == str(request.user_id) for s in sessions
    )
    return owned, sessions


@v2_bp.route("/explore/arc/<arc_id>/voice-album", methods=["GET"])
@require_auth
def v2_explore_arc_voice_album(arc_id):
    """The Voice Album read — the arc's aligned moments (SPEC F2; the
    founder's entry rule 2026-08-14: acoustic + user + coach, mirrored to
    current state).

    DATA ONLY. The surface copy and UI are the founder's (LIVE LOOP);
    this serves what any compliant surface needs and nothing it must not
    show: each entry carries the moment's verbatim words, playback for
    its own audio span, and its position (slide, take) plus entered_at.
    NO confidence, NO tags, NO scores (AC-9). The FACT of entry is
    post-publish and three-way agreed, so it reveals no blind label
    (BLIND COACH holds by construction).

    Response 200 {"arc_id", "entries": [{snippet_id, take_session_id,
    take_index, slide_index, entered_at, text, audio_url,
    start_offset_ms, duration_ms}]} — PRESENTATION order (founder
    2026-08-14): slide_index ascending, entries without a slide last,
    entered_at ascending within a slide.
    404 NOT_FOUND · 500 V2_ERROR
    """
    try:
        owned, sessions = _arc_owned_by_caller(arc_id)
        if not owned:
            return jsonify({"code": "NOT_FOUND",
                            "error": "arc not found"}), 404
        entries = db.list_voice_album(str(arc_id)) or []

        # The DB's entered_at base order is CAPTURE order — lock slide 7's
        # moment before slide 2's and the album would read 7-then-2 forever.
        # The album reads in DECK position; same-slide ties keep earn order.
        def _deck_pos(e):
            si = e.get("slide_index") if isinstance(e, dict) else None
            positioned = isinstance(si, int) and not isinstance(si, bool)
            return (0 if positioned else 1, si if positioned else 0,
                    str(e.get("entered_at") or "") if isinstance(e, dict)
                    else "")
        entries = sorted(entries, key=_deck_pos)
        take_index_by_sid = {str(s.get("id")): s.get("take_index")
                             for s in sessions}
        snips_by_sid: dict = {}
        out = []
        for e in entries:
            if not isinstance(e, dict):
                continue
            sid = str(e.get("take_session_id") or "")
            snip = None
            if sid:
                if sid not in snips_by_sid:
                    try:
                        snips_by_sid[sid] = {
                            str(s.get("id")): s
                            for s in (db.get_snippets_by_session(sid)
                                      or [])}
                    except Exception:
                        snips_by_sid[sid] = {}
                snip = snips_by_sid[sid].get(str(e.get("snippet_id")))
            _s = snip or {}
            out.append({
                "snippet_id": e.get("snippet_id"),
                "take_session_id": e.get("take_session_id"),
                "take_index": take_index_by_sid.get(sid),
                "slide_index": e.get("slide_index"),
                "entered_at": e.get("entered_at"),
                # The student's own words, verbatim — never a paraphrase.
                "text": (_s.get("transcript")
                         or _s.get("transcription_text") or "").strip(),
                "audio_url": (_resolve_snippet_audio_url(_s)
                              if snip else None),
                "start_offset_ms": _s.get("start_offset_ms"),
                "duration_ms": _s.get("duration_ms"),
            })
        return jsonify({"arc_id": arc_id, "entries": out}), 200
    except Exception as e:
        logger.error("explore/arc voice-album failed arc=%s: %s", arc_id,
                     e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "failed"}), 500


@v2_bp.route("/explore/arc/<arc_id>/best-presentation", methods=["GET"])
@require_auth
def v2_explore_arc_best_presentation(arc_id):
    """Best-Presentation (willab Prompt D) — REPLACES the audit. After the arc's
    3 takes, the user's strongest-rated delivery of each slide (challenge lifts
    the rating, threat lowers it), lightly stitched into 'ideal presentation'
    text, with coach-confirmed breakthrough markers.

    SCORE-FREE (AC-9). Ownership: the arc must contain a session owned by the
    caller, else 404. Not-ready (<3 takes) still returns 200 with populated
    slides + progress.takes_remaining — the FE drives its 'need 3 takes' notice
    off ready / takes_remaining (not off a 404 or an empty body).

    Founder 2026-07-06: 402 gates this endpoint (paid deliverable). PAST the
    gate, ``coach_finalized`` is a SEPARATE, harder gate on CONTENT — the raw
    auto-assembled draft is NEVER served to the student; every slide's `text`
    is "" until the coach has corrected EVERY slide (build_best_presentation
    handles this transparently), regardless of payment. The FE shows "still
    being prepared by your coach" when paid but not yet coach_finalized —
    distinct from the 402 paywall.

    Response 200 {
        arc_id, ready, coach_finalized, presentation_ref,
        progress: { takes_done, takes_target, takes_remaining, ready },
        slides: [ { index, title, body, text, audio_ref,
                    start_offset_ms, duration_ms, take_index,
                    breakthrough, breakthrough_note, coach_edited, edited } ]
    }
             404 NOT_FOUND · 500 V2_ERROR
    """
    try:
        from services.best_presentation import build_best_presentation
        owned, _ = _arc_owned_by_caller(arc_id)
        if not owned:
            return jsonify({"code": "NOT_FOUND", "error": "arc not found"}), 404
        # Single-deliverable (founder 2026-07-17): the best presentation is
        # free — no paywall. (audit_paid stays true for FE back-compat.)
        return jsonify({
            "arc_id": arc_id, "audit_paid": True,
            **build_best_presentation(arc_id),
        }), 200
    except Exception as e:
        logger.error("explore/arc best-presentation failed arc=%s: %s", arc_id,
                     e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR", "error": "Failed to build best presentation",
        }), 500


@v2_bp.route("/explore/arc/<arc_id>/breakthroughs", methods=["GET"])
@require_auth
def v2_explore_arc_breakthroughs(arc_id):
    """ALL coach-confirmed breakthrough moments in this arc, newest → oldest
    (founder #5 — the "explore my breakthrough moments" list behind the button
    below the best presentation). Same gate as the best-presentation badge (a
    threat→challenge turn on the coach's OWN labels, never a model guess), but
    every breakthrough snippet across all takes, not just the per-slide winner.

    SCORE-FREE (AC-9). Ownership: the arc must contain a session owned by the
    caller, else 404. An empty list (no coach-confirmed breakthroughs yet) is a
    200 with breakthroughs=[] — the FE shows an empty-state, not an error.

    Response 200 {
        arc_id, count,
        breakthroughs: [ { snippet_id, session_id, take_index, created_at,
                           slide_index, transcript, audio_ref,
                           start_offset_ms, duration_ms, note } ]
    }
             404 NOT_FOUND · 500 V2_ERROR
    """
    try:
        from services.best_presentation import build_arc_breakthroughs
        owned, _ = _arc_owned_by_caller(arc_id)
        if not owned:
            return jsonify({"code": "NOT_FOUND", "error": "arc not found"}), 404
        # Single-deliverable (founder 2026-07-17): the breakthroughs list is
        # free — no paywall.
        return jsonify({"arc_id": arc_id, **build_arc_breakthroughs(arc_id)}), 200
    except Exception as e:
        logger.error("explore/arc breakthroughs failed arc=%s: %s", arc_id,
                     e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR", "error": "Failed to load breakthroughs",
        }), 500


@v2_bp.route("/explore/arc/<arc_id>/best-presentation/slides/<int:index>",
             methods=["PUT"])
@require_auth
def v2_explore_arc_edit_slide(arc_id, index):
    """Save the user's edited best-presentation text for one slide (Prompt D —
    the pencil). Overrides the composed text + sticks across recompositions.
    Ownership-checked.

    Rich formatting (backlog 1.7, founder 2026-07-11): the FE's ideal-text
    editor persists a tiny marker subset — **bold**, *italic*, __underline__,
    ==highlight== — INSIDE this same text field. The markers pass through as
    plain text (they degrade readably on every other surface); raw HTML tags
    are stripped server-side so markup can never round-trip into a renderer.

    Body: { "text": str }.  200 { ok, arc_id, index } · 400 · 404 · 500
    """
    try:
        owned, _ = _arc_owned_by_caller(arc_id)
        if not owned:
            return jsonify({"code": "NOT_FOUND", "error": "arc not found"}), 404
        body = request.get_json(silent=True) or {}
        text = (body.get("text") or "").strip() if isinstance(body.get("text"), str) else ""
        # Strip HTML tags (keep the marker subset — it's plain text). Length
        # is checked AFTER stripping so tags can't smuggle past the cap.
        text = re.sub(r"<[^>]*>", "", text).strip()
        if not text:
            return jsonify({"code": "INVALID_INPUT", "error": "text is required"}), 400
        if len(text) > 2000:
            return jsonify({"code": "INVALID_INPUT", "error": "text too long"}), 400
        ok = db.upsert_best_presentation_edit(arc_id, index, text, request.user_id)
        if not ok:
            return jsonify({"code": "V2_ERROR", "error": "Could not save the edit"}), 500
        return jsonify({"ok": True, "arc_id": arc_id, "index": index}), 200
    except Exception as e:
        logger.error("explore/arc edit-slide failed arc=%s idx=%s: %s",
                     arc_id, index, e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to save edit"}), 500


@v2_bp.route("/explore/arc/<arc_id>/progress", methods=["GET"])
@optional_auth
def v2_explore_arc_progress(arc_id):
    """Cheap poll for the 'X takes to your ideal presentation' bar (Prompt D §5).

    coach_finalized (backlog 4.2, 2026-07-11): whether the coach has corrected
    EVERY slide of the ideal text — at 3/3 takes with coach_finalized=false the
    FE shows "Now we are waiting for the coach to assemble your speech!".
    Computed cheaply here (one edits read + the deck size from the sessions
    already loaded), mirroring services/best_presentation.py's definition —
    the ideal-text payload stays the authoritative gate.

    GUEST-capable since 2026-07-16 (the signed-out-first flow polls this from
    the instant readout — it was 401-ing): a FULLY-UNCLAIMED arc (every
    session user_id NULL) is readable to the bare arc id — the same
    capability-by-uuid rule as the guest readout; any claimed session in the
    arc → owner-only (404 to any other/no caller, no existence leak).

    Response 200 { arc_id, takes_done, takes_target, takes_remaining, ready,
                   coach_finalized }
             · 404 · 500
    """
    try:
        from services.best_presentation import presentation_progress
        sessions = db.get_arc_sessions(arc_id)
        if not sessions:
            return jsonify({"code": "NOT_FOUND", "error": "arc not found"}), 404
        _caller = getattr(request, "user_id", None)
        _owners = {str(s.get("user_id")) for s in sessions if s.get("user_id")}
        _owned = bool(_caller) and str(_caller) in _owners
        _guest_ok = not _owners  # fully-unclaimed arc → capability by uuid
        if not (_owned or _guest_ok):
            return jsonify({"code": "NOT_FOUND", "error": "arc not found"}), 404
        # Canonical deck size = the most-complete deck across takes (same
        # rule as compose); deckless arcs (no deck) are never "finalized".
        _n_slides = 0
        for _s in sessions:
            _ctx = _s.get("intake_context") if isinstance(
                _s.get("intake_context"), dict) else {}
            _n_slides = max(_n_slides, len((_ctx or {}).get("slides") or []))
        _coach_finalized = False
        if _n_slides:
            _edits = db.get_coach_best_presentation_edits(arc_id) or {}
            _coach_finalized = all(
                isinstance(_edits.get(i), str) and _edits[i].strip()
                for i in range(_n_slides)
            )
        from services.best_presentation import spoken_arc_sessions
        return jsonify({
            # SPOKEN takes only (2026-07-15) — a read never inflates N/3.
            "arc_id": arc_id,
            **presentation_progress(len(spoken_arc_sessions(sessions))),
            "coach_finalized": _coach_finalized,
        }), 200
    except Exception as e:
        logger.error("explore/arc progress failed arc=%s: %s", arc_id, e,
                     exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR", "error": "Failed to load progress",
        }), 500


@v2_bp.route("/explore/arc/<arc_id>/take-comparison", methods=["GET"])
@require_auth
def v2_explore_arc_take_comparison(arc_id):
    """Take-1-vs-take-2 comparison (Paid Audits A6) — the NEUTRAL teaser at the
    paywall. RAW acoustic aggregates (mean pitch, speech rate, pitch range,
    mean pause) for take 1 vs take 2 + a neutral pitch-range movement word
    (widened / narrowed / steadied).

    FREE on purpose — this is the unpaid teaser, so it is NOT behind the A2
    paywall (only ownership-gated). AC-9 / D8: no score, ratio, verdict word, or
    charisma vocabulary; raw values + neutral movement only.

    Response 200 { arc_id, take_count, takes:[...], comparison|null }
             404 NOT_FOUND · 500 V2_ERROR
    """
    try:
        from services.take_comparison import build_take_comparison
        owned, _ = _arc_owned_by_caller(arc_id)
        if not owned:
            return jsonify({"code": "NOT_FOUND", "error": "arc not found"}), 404
        return jsonify(build_take_comparison(arc_id)), 200
    except Exception as e:
        logger.error("explore/arc take-comparison failed arc=%s: %s", arc_id, e,
                     exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR", "error": "Failed to load take comparison",
        }), 500


@v2_bp.route("/arc/<arc_id>/checkout", methods=["POST"])
@require_auth
def v2_arc_checkout(arc_id):
    """Start Stripe Checkout for ONE audit = this arc (Paid Audits A3).

    Ownership-gated (the arc must be the caller's). Already-entitled arcs short-
    circuit (no duplicate charge). Body (optional): { success_url, cancel_url }.

    Response 200 { checkout_url, checkout_session_id, arc_id }
             200 { already_entitled: true, arc_id }   (purchase exists)
             404 NOT_FOUND · 4xx/5xx from Stripe/config
    """
    try:
        from services.arc_entitlement import is_arc_entitled
        from services.arc_checkout import create_arc_checkout_session
        owned, _ = _arc_owned_by_caller(arc_id)
        if not owned:
            return jsonify({"code": "NOT_FOUND", "error": "arc not found"}), 404
        if is_arc_entitled(db, arc_id, request.user_id):
            return jsonify({"already_entitled": True, "arc_id": arc_id}), 200
        body = request.get_json(silent=True) or {}
        result = create_arc_checkout_session(
            str(arc_id), str(request.user_id), config,
            success_url=(body.get("success_url") or None),
            cancel_url=(body.get("cancel_url") or None),
        )
        return jsonify(result.payload), result.http_status
    except Exception as e:
        logger.error("arc checkout failed arc=%s: %s", arc_id, e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR", "error": "Failed to start checkout",
        }), 500


@v2_bp.route("/arc/<arc_id>/redeem", methods=["POST"])
@require_auth
def v2_arc_redeem(arc_id):
    """Redeem a founding free-pass invite code for this arc (Paid Audits A4).

    Ownership-gated. Body: { code }. An active code with uses < max_uses mints a
    'founding_pass' purchase (source='invite_code') and burns one use.

    Response 200 { ok: true, arc_id, kind: 'founding_pass' }
             200 { already_entitled: true, arc_id }
             400 INVALID_INPUT (no code) · 404 NOT_FOUND (arc)
             409 CODE_INVALID (unknown / inactive / exhausted) · 500
    """
    try:
        from services.arc_entitlement import is_arc_entitled
        owned, _ = _arc_owned_by_caller(arc_id)
        if not owned:
            return jsonify({"code": "NOT_FOUND", "error": "arc not found"}), 404
        if is_arc_entitled(db, arc_id, request.user_id):
            return jsonify({"already_entitled": True, "arc_id": arc_id}), 200
        body = request.get_json(silent=True) or {}
        code = (body.get("code") or "").strip() if isinstance(body.get("code"), str) else ""
        if not code:
            return jsonify({"code": "INVALID_INPUT", "error": "code is required"}), 400
        if not db.consume_arc_invite_code(code):
            return jsonify({
                "code": "CODE_INVALID",
                "error": "That code is not valid, inactive, or fully used.",
            }), 409
        purchase = db.create_arc_purchase(
            str(arc_id), str(request.user_id),
            kind="founding_pass", source="invite_code",
        )
        if not purchase:
            # The use was burned but the purchase failed — log loudly; the user
            # can retry with another code (rare; arc_purchases table missing).
            logger.error(
                "arc redeem: code consumed but purchase failed arc=%s code=%s",
                arc_id, code,
            )
            return jsonify({
                "code": "V2_ERROR", "error": "Could not record the pass",
            }), 500
        return jsonify({"ok": True, "arc_id": arc_id, "kind": "founding_pass"}), 200
    except Exception as e:
        logger.error("arc redeem failed arc=%s: %s", arc_id, e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR", "error": "Failed to redeem code",
        }), 500


# ── willab — $25/25-credit arc unlock (founder re-price 2026-07-06) ─────

@v2_bp.route("/arc/<arc_id>/unlock", methods=["POST"])
@require_auth
def v2_arc_unlock(arc_id):
    """RETIRED (single-deliverable, founder 2026-07-17). The $25 arc unlock is
    gone; this route is a 410 tombstone (the ideal text + deliverables are free,
    the only paid item is the 5-credit key-moment explanations). 410 GONE."""
    # RETIRED (single-deliverable, founder 2026-07-17): the $25 arc unlock is
    # gone — the ideal text + its deliverables are free; the only paid item is
    # the 5-credit key-moment explanations (POST /arc/<id>/unlock-moments). Kept
    # as a 410 tombstone so any lingering client gets a clear signal.
    return jsonify({
        "code": "GONE",
        "error": "This product was retired. The ideal text is free; "
                 "key-moment explanations unlock for 5 credits.",
    }), 410


@v2_bp.route("/arc/<arc_id>/unlock-moments", methods=["POST"])
@require_auth
def v2_unlock_moments(arc_id):
    """THE one paid item under the single deliverable (founder re-shape
    2026-07-17): open the presentation's key-moment EXPLANATIONS (the coach's
    note/video per moment) — one-time per presentation, covering all current
    AND future moments. The ideal text itself is always free. ARC-KEYED path —
    the FE contract pin (their 748c33d).

    Charged in TOKENS (2,500) since the 2026-08-12 pivot. The charge is keyed
    on the arc, so the claim below needs no refund arm: the retired credits
    ordering was deduct → insert → refund-on-conflict, three round trips with
    a window where the money was gone and the entitlement was not. `charge` is
    idempotent on (user, action, ref_id) — a raced second claim comes back ok
    with charged=0, so a retry costs nothing and there is nothing to hand back.

    200 { unlocked: true, arc_id, tokens_remaining }
    200 { already_entitled: true, arc_id }
    402 { code: INSUFFICIENT_TOKENS, required, current, reason }
    404 · 500
    """
    try:
        owned, _ = _arc_owned_by_caller(arc_id)
        if not owned:
            return jsonify({"code": "NOT_FOUND",
                            "error": "presentation not found"}), 404
        if _moments_entitled(arc_id):
            return jsonify({"already_entitled": True,
                            "arc_id": arc_id}), 200

        # TOKENS ARE THE CURRENCY (founder 2026-08-12, the pricing pivot).
        # Key-moment explanations cost 2,500 tokens ($0.25), not the legacy 5
        # credits ($5) — a 20× cut approved 2026-07-27, because the
        # explanations were already generated during the take and cost us
        # nothing to unlock.
        #
        # The legacy branch that sat below this is gone. It was reachable only
        # with TOKEN_PRICING_ENABLED off, and the flag is on in prod on both
        # web and worker (founder 2026-08-12). Keeping a second charging path
        # alive behind a flag nobody intends to flip back is how two
        # currencies drift apart: the legacy one stops being exercised, stops
        # being tested against reality, and is still the thing that runs on
        # the day someone clears an env var.
        #
        # `charge` never raises and is soft by contract (fence §6.1), so the
        # unforked path degrades exactly as it did — it does not need the flag
        # to be safe, only to be correct about the price.
        from services.token_account import charge as _charge
        res = _charge(str(request.user_id), "moment_explanation",
                      ref_id=str(arc_id))
        if not res.ok:
            return jsonify({
                "code": "INSUFFICIENT_TOKENS",
                "required": res.charged or 2500,
                "current": res.balance,
                "reason": res.reason,
            }), 402
        unlock = db.insert_moment_unlock(str(arc_id),
                                         str(request.user_id), 0)
        if not unlock and not _moments_entitled(arc_id):
            return jsonify({"code": "V2_ERROR",
                            "error": "Could not start the unlock"}), 500
        return jsonify({"unlocked": True, "arc_id": arc_id,
                        "tokens_remaining": res.balance}), 200
    except Exception as e:
        logger.error("unlock-moments failed arc=%s: %s", arc_id, e,
                     exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to unlock"}), 500


@v2_bp.route("/explore/arc/<arc_id>/moments/<moment_id>", methods=["GET"])
@require_auth
def v2_get_moment_explanation(arc_id, moment_id):
    """ONE key moment's EXPLANATION (single deliverable, founder 2026-07-17;
    per-moment path = the FE contract pin, their 748c33d): the coach's note
    text and/or video + playback span for the tapped moment. Gated by the
    5-credit moments unlock; the 402 carries the price so the unlock prompt
    renders from this response alone. AC-9: qualitative content only — no
    scores, and the private direction label never serializes (it only
    selects, same rule as the feedback page).

    Response is FLAT (the FE reads top-level `note` + `video_ref`):
    200 { arc_id, id, note, video_ref, transcript, audio_ref,
          start_offset_ms, duration_ms, slide_index, recording_kind }
    402 { code: MOMENTS_LOCKED, price_credits } · 404 · 500
    """
    try:
        owned, sessions = _arc_owned_by_caller(arc_id)
        if not owned:
            return jsonify({"code": "NOT_FOUND",
                            "error": "presentation not found"}), 404
        if not _moments_entitled(arc_id):
            return jsonify({
                "code": "MOMENTS_LOCKED",
                "price_credits": int(getattr(
                    config, "MOMENTS_UNLOCK_CREDITS", 5) or 5),
            }), 402
        spoken, reads = _spoken_takes_and_reads(sessions)
        _want = str(moment_id)
        for s in spoken:
            sid = str(s.get("id"))
            read_rows = reads.get(sid) or []
            for m in _take_key_moments(
                    sid, [str(r.get("id")) for r in read_rows if r.get("id")]):
                if str(m.get("snippet_id")) != _want:
                    continue
                # FLAT top-level note/video_ref (the FE reads exactly these);
                # the playback fields ride along for the moment player.
                return jsonify({
                    "arc_id": arc_id,
                    "id": m.get("snippet_id"),
                    "note": (m.get("comment_text") or None),
                    "video_ref": (m.get("comment_video_ref") or None),
                    "take_session_id": m.get("take_session_id"),
                    "transcript": m.get("transcript"),
                    "audio_ref": m.get("audio_ref"),
                    "start_offset_ms": m.get("start_offset_ms"),
                    "duration_ms": m.get("duration_ms"),
                    "slide_index": m.get("slide_index"),
                    "recording_kind": m.get("recording_kind"),
                }), 200
        return jsonify({"code": "MOMENT_NOT_FOUND",
                        "error": "Not a key moment of this presentation"}), 404
    except Exception as e:
        logger.error("moment explanation failed arc=%s moment=%s: %s",
                     arc_id, moment_id, e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR",
                        "error": "Failed to load the moment"}), 500


# ── willab — delivery layer (founder 2026-07-15) ────────────────────────
#
# The post-core delivery: per-take FEEDBACK (full text + key moments), the
# one-block IDEAL TEXT (coach-approved, $25-gated), the coach Save/Publish
# flow, and the 4-bubble delivery (3 grey feedback + 1 purple ideal text).
# Supersedes the #186 single batch card (kept below, deprecated, until the
# FE switches) and the per-slide coach ideal-text editing (same deal).


def _moment_suggestions_enabled() -> bool:
    """Star suggestions on the SD ideal text (founder 2026-07-18): grey
    suggestion stars (emphasize / replace) resolved coach-label-first, else
    the deterministic potentiometer (NEVER the shadow model — blind coach);
    orange verified stars carry the coach message. DEFAULT OFF."""
    return (os.getenv("MOMENT_SUGGESTIONS_ENABLED") or "0").strip().lower() \
        in ("1", "true", "yes")


def _take_full_text(session_id):
    """A take's feedback text: pieces in speech order, per piece the coach
    correction > the user's approved edit > the raw transcript (locked
    assumption A1). Plain text, no playback, no scores."""
    snips = db.get_snippets_by_session(session_id) or []
    corrections = {}
    for d in (db.get_coach_snippet_drafts(session_id) or []):
        _sid = str(d.get("snippet_id"))
        _tx = (d.get("transcript_corrected") or "").strip()
        if _sid and _tx:
            corrections[_sid] = _tx
    edits = {}
    try:
        for e in (db.get_user_transcript_edits(session_id) or []):
            if e.get("snippet_id") and (e.get("text") or "").strip():
                edits[str(e["snippet_id"])] = e["text"].strip()
    except Exception:
        pass
    parts = []
    for s in sorted(snips, key=lambda x: (x.get("start_offset_ms") or 0)):
        _sid = str(s.get("id"))
        txt = (corrections.get(_sid) or edits.get(_sid)
               or s.get("transcript") or s.get("transcription_text") or "")
        txt = txt.strip()
        if txt:
            parts.append(txt)
    return " ".join(parts)


def _take_key_moments(session_id, read_session_ids=None):
    """A take's key moments (locked assumption A2/A3): coach-SURFACED snippets
    marked 'challenge' OR 'threat' (founder 2026-07-16: the coach's video may
    ride a threat-labeled moment too — 'challenge' alone remains the
    breakthrough badge), from the spoken take AND ALL its paired mid-take
    re-reads. Each: playback span + the coach's comment (text and/or video) +
    recording_kind + slide_index. No scores (AC-9); the private direction
    label itself is never serialized — it only SELECTS."""
    _reads = read_session_ids or []
    if isinstance(_reads, str):
        _reads = [_reads]
    out = []
    for sid, kind_default in ([(session_id, "spoken")]
                              + [(r, "read") for r in _reads]):
        if not sid:
            continue
        labels = {
            str(r.get("snippet_id")): r.get("value")
            for r in (db.get_training_labels(sid) or [])
        }
        drafts = {
            str(d.get("snippet_id")): d
            for d in (db.get_coach_snippet_drafts(sid) or [])
            if d.get("snippet_id")
        }
        for s in sorted(db.get_snippets_by_session(sid) or [],
                        key=lambda x: (x.get("start_offset_ms") or 0)):
            _sid = str(s.get("id"))
            d = drafts.get(_sid)
            if not d or not d.get("surfaced"):
                continue
            if labels.get(_sid) not in ("challenge", "threat"):
                continue
            m = s.get("metrics") if isinstance(s.get("metrics"), dict) else {}
            _piece = m.get("piece") if isinstance(m.get("piece"), dict) else {}
            out.append({
                "snippet_id": s.get("id"),
                "take_session_id": sid,
                "slide_index": _piece.get("slide_index"),
                "recording_kind": m.get("recording_kind") or kind_default,
                "transcript": (
                    (d.get("transcript_corrected") or "").strip()
                    or s.get("transcript") or s.get("transcription_text") or ""
                ),
                # Resolved (founder 2026-08-10): an s3:// fallback ref
                # renders a dead player; the resolver signs it against
                # its own bucket and passes healthy URLs through.
                "audio_ref": _resolve_feedback_audio(
                    s.get("audio_segment_path")),
                "start_offset_ms": s.get("start_offset_ms"),
                "duration_ms": s.get("duration_ms"),
                "comment_text": (d.get("note") or "").strip() or None,
                # Resolved for the SAME reason the audio above is, and it was
                # the one ref still going out raw (founder 2026-08-11, deck
                # slice 4 — the coach's video moves into the chunk modal, so
                # a dead one is now dead in front of the student's own text).
                # A coach video is minted as a PUBLIC URL on the coach bucket's
                # base, and R2 only answers on that base once the bucket's dev
                # URL is enabled or a custom domain is attached — the exact
                # 403-on-every-play class the resolver exists for. Signing is
                # bucket-authoritative and works regardless of public access.
                "comment_video_ref": _resolve_feedback_audio(
                    d.get("breakthrough_video_ref")),
            })
    return out


def _moments_entitled(arc_id) -> bool:
    """Single deliverable: is the presentation's key-moment unlock owned?
    Reads ONLY moment_unlocks — the retired $25 arc_purchases never grants
    this (founder-explicit: no grandfathering)."""
    try:
        return bool(db.get_moment_unlock(arc_id))
    except Exception:
        return False


def _moment_explanations_map(session_ids) -> dict:
    """snippet_id → {"has_video": bool} for every coach EXPLANATION (a
    surfaced draft carrying a note and/or video). Key presence = an
    explanation exists (the ORANGE verified star); has_video drives the
    blurred-video affordance. Batch per session; best-effort."""
    out: dict = {}
    for sid in {str(s) for s in (session_ids or []) if s}:
        try:
            for d in (db.get_coach_snippet_drafts(sid) or []):
                _snip = d.get("snippet_id")
                if _snip is None or not d.get("surfaced"):
                    continue
                if (d.get("note") or "").strip() \
                        or d.get("breakthrough_video_ref"):
                    out[str(_snip)] = {
                        "has_video": bool(d.get("breakthrough_video_ref")),
                        # Ticket 6: a blog post the coach attached by hand.
                        # Carried as the raw slug here; resolved to
                        # {slug,title,url} by _moment_reference (which drops it
                        # when the post is a draft or gone).
                        "reference_post_slug": (
                            d.get("reference_post_slug") or None),
                    }
        except Exception:
            continue
    return out


def _moment_reference_map(slugs):
    """{slug: {slug,title,url}} for the DISTINCT slugs on this arc's moments.

    Batched deliberately. The obvious implementation resolves inside the
    per-moment decorator, which is an N+1: a talk with ten verified moments
    would issue ten post lookups on every ideal-text GET — the exact shape the
    load-time ticket is about. Distinct slugs on one arc are typically 0–2, so
    one lookup each is effectively constant.
    """
    out: dict = {}
    for slug in {s for s in (slugs or []) if isinstance(s, str) and s.strip()}:
        ref = _moment_reference(slug)
        if ref:
            out[slug.strip()] = ref
    return out


def _moment_reference(slug):
    """{slug, title, url} for a coach-attached blog post, or None.

    Resolved at READ time, never stored as a URL: the public path is moving
    (/journal -> /blog) and the title can be edited, so resolving late keeps
    both correct. Returns None — i.e. the FE renders nothing — when the slug is
    empty, the post was unpublished, or it was deleted. Serving a dead link to a
    student is worse than serving no link.

    `published_only=True` is the load-bearing argument: it reuses the Journal's
    own draft-invisibility rule, so an in-progress post the coach attached early
    cannot leak.
    """
    slug = (slug or "").strip() if isinstance(slug, str) else ""
    if not slug:
        return None
    try:
        row = db.get_journal_post_by_slug(slug, published_only=True)
    except Exception as e:
        logger.warning("moment reference lookup failed slug=%s: %s", slug, e)
        return None
    if not isinstance(row, dict) or not row.get("slug"):
        return None
    return {
        "slug": row.get("slug"),
        "title": row.get("title") or "",
        "url": f"/blog/{row.get('slug')}",
    }


def _moment_playback_map(session_ids) -> dict:
    """snippet_id → {snippet_audio_ref, start_offset_ms, duration_ms} for
    FREE in-modal playback of the student's own recording (audit
    2026-07-18: the star sheet plays the snippet above the paywall, so this
    can NEVER come from the paid moments GET).

    Parent+offset model: the ref is usually the WHOLE take's audio, so the
    offsets ride along and the FE must clamp to [start, start+duration].
    Uses the shared column-resolver so post-finalize rows (audio_segment_
    path NULL) still play. Batched per session; best-effort → no player."""
    out: dict = {}
    for sid in {str(s) for s in (session_ids or []) if s}:
        try:
            for s in (db.get_snippets_by_session(sid) or []):
                _snip = s.get("id")
                if _snip is None:
                    continue
                try:
                    _url = _resolve_snippet_audio_url(s)
                except Exception:
                    _url = s.get("audio_segment_path")
                if not _url:
                    continue
                out[str(_snip)] = {
                    "snippet_audio_ref": _url,
                    "start_offset_ms": s.get("start_offset_ms"),
                    "duration_ms": s.get("duration_ms"),
                }
        except Exception:
            continue
    return out


def _moment_applied_map(session_ids) -> dict:
    """snippet_id → True when the LAST moment_* suggestion action was
    'applied' (Approve is reversible; last action wins). Best-effort."""
    out: dict = {}
    for sid in {str(s) for s in (session_ids or []) if s}:
        try:
            rows = db.get_suggestion_feedback_by_session(sid) or []
        except Exception:
            continue
        for r in rows:   # rows assumed chronological; last write wins
            if r.get("target") not in ("moment_emphasize", "moment_replace",
                                       "document_replace", "document_bold"):
                continue
            _snip = r.get("snippet_id")
            if _snip is None:
                continue
            out[str(_snip)] = (r.get("action") == "applied")
    return {k: v for k, v in out.items() if v}


def _fold_applied_moments(text, moments) -> str:
    """Serve-time fold of APPLIED star suggestions into the displayed text
    (founder sign-off 2026-07-18 — the canonical ideal text is NEVER
    mutated; this rewrites the response string only):
      * emphasize → the moment's inner span wraps in {{orange:…}}
        ("these words hold particular value");
      * replace   → the inner span is swapped for the generated replacement
        (not bold, not orange — just replaced).
    The [[moment:…]] anchor survives (revert stays addressable). Pure."""
    from services.ideal_text_block import accent_span, within_accent_window
    if not isinstance(text, str) or not text:
        return text
    for m in moments or []:
        if not m.get("applied"):
            continue
        sug = m.get("suggestion") or {}
        _id, _sid = m.get("id"), m.get("take_session_id")
        if not _id or not _sid:
            continue
        _pat = re.compile(
            r"\[\[moment:" + re.escape(str(_id)) + r"\|"
            + re.escape(str(_sid)) + r"\]\](?P<inner>.*?)\[\[/moment\]\]",
            re.DOTALL,
        )
        if sug.get("kind") == "replace" and (sug.get("replacement") or "").strip():
            _new = sug["replacement"].strip()
            text = _pat.sub(
                lambda mt: f"[[moment:{_id}|{_sid}]]{_new}[[/moment]]",
                text, count=1)
        elif sug.get("kind") == "emphasize":
            text = _pat.sub(
                # SINGLE marker, never nested (audit 2026-07-18): the FE's
                # rich-marker parser is FLAT — a nested `**{{orange:…}}**`
                # printed its raw syntax to the student. The accent marker
                # alone carries "these words hold particular value". A span
                # already carrying the marker (BAKED by the decision ledger,
                # 2026-07-20) folds to itself — never double-wrapped.
                # accent_span, never an f-string wrap (2026-07-27): a
                # moment's inner span can run across a paragraph break,
                # and a marker that straddles a newline printed a bare
                # `{{orange:` line into the student's text.
                #
                # THE F.4 WINDOW, HERE TOO (SPEC §12.2, founder 2026-08-14
                # — field report #3, "my saved text went all orange"). A
                # moment's inner span is the WHOLE snippet transcript — a
                # whole chunk — and this fold painted all of it. bake_piece
                # has refused that since §F.4 (within_accent_window); the
                # serve fold was the second writer with the rule missing.
                # Over the window: the moment folds to ITSELF — the applied
                # decision stands, only the paint is refused, words
                # untouched — exactly bake_piece's rule.
                lambda mt: (
                    mt.group(0) if "{{orange:" in mt.group("inner")
                    or not within_accent_window(mt.group("inner"))
                    else (f"[[moment:{_id}|{_sid}]]"
                          f"{accent_span(mt.group('inner'))}[[/moment]]")),
                text, count=1)
    return text


@v2_bp.route("/explore/arc/<arc_id>/feedback", methods=["GET"])
@require_auth
def v2_explore_arc_feedback(arc_id):
    """The per-take FEEDBACK the user opens from the grey bubbles (founder
    2026-07-15): the take's full text all together (NO playback) + the KEY
    MOMENTS (grouped by slide on the FE), each with its snippet playback and
    the coach's comment (text or video). No suggestions, no scores.

    Single-deliverable (founder 2026-07-17): every take's feedback is FREE —
    the $25 arc unlock is retired, so no take is locked. Reads fold into
    their paired take.

    Response 200 { arc_id, takes:[{take_index, session_id, free,
        locked?, full_text?, key_moments?:[…]}], ideal_ready, paywall? }
    404 · 500
    """
    try:
        owned, sessions = _arc_owned_by_caller(arc_id)
        if not owned:
            return jsonify({"code": "NOT_FOUND", "error": "arc not found"}), 404
        # Single-deliverable (founder 2026-07-17): every take's feedback is
        # FREE — the $25 arc unlock is retired, so nothing here is gated.
        spoken, reads = _spoken_takes_and_reads(sessions)
        takes = []
        for s in spoken:
            sid = str(s.get("id"))
            ti = s.get("take_index") or (len(takes) + 1)
            read_rows = reads.get(sid) or []
            takes.append({
                "take_index": ti, "session_id": sid,
                "free": (ti == 1), "locked": False,
                "full_text": _take_full_text(sid),
                "key_moments": _take_key_moments(
                    sid, [str(r.get("id")) for r in read_rows if r.get("id")]),
            })
        ideal = db.get_coach_arc_ideal_text(arc_id)
        if takes:
            # Once per arc, and only when there is feedback to read. Fail-open
            # by construction — the charge result is not consulted.
            _charge_arc_deliverable(request.user_id, "insights", arc_id)
        return jsonify({
            "arc_id": arc_id,
            "takes": takes,
            "ideal_ready": bool(ideal and ideal.get("approved_at")),
        }), 200
    except Exception as e:
        logger.error("explore/arc feedback failed arc=%s: %s", arc_id, e,
                     exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR", "error": "Failed to load feedback",
        }), 500


@v2_bp.route("/explore/arc/<arc_id>/setup", methods=["GET"])
@require_auth
def v2_explore_arc_setup(arc_id):
    """The saved SETUP of a project, so continuing it never re-asks the
    student (founder 2026-07-22, context-aware recording).

    Deliberately MINIMAL — only what the setup screen would otherwise
    ask for, read from the arc's latest SPOKEN take's intake_context:

      200 { arc_id, topic, audience, strategic_context,
            target_length_seconds, slides, presentation_ref }

    `topic` is load-bearing (the record POST rejects a take without
    one); `slides`/`presentation_ref` are load-bearing for a DECKED
    project — the master-document skeleton is keyed on slide index, so
    continuing a decked talk without its deck would produce unmappable
    takes. No scores, no take data, no counts (AC-9).

    Global recording constants deliberately do NOT live here (2026-07-27):
    `long_take_caution_sec` and the min-content floor are properties of the
    product, not of this project, and they have one home —
    GET /v2/config/recording. This payload stays exactly the setup fields
    (there is a test pinning that set).

    404 when the arc isn't the caller's or has no spoken take.
    """
    try:
        owned, sessions = _arc_owned_by_caller(arc_id)
        if not owned:
            return jsonify({"code": "NOT_FOUND",
                            "error": "project not found"}), 404
        from services.best_presentation import spoken_arc_sessions
        spoken = spoken_arc_sessions(sessions or [])
        if not spoken:
            return jsonify({"code": "NOT_FOUND",
                            "error": "project not found"}), 404
        spoken.sort(key=lambda s: (s.get("take_index") or 0,
                                   s.get("created_at") or ""))
        # The LATEST take's context is the live setup (a later take may
        # have added the deck or changed the audience).
        ctx = {}
        for s in reversed(spoken):
            _c = s.get("intake_context")
            if isinstance(_c, dict) and _c.get("topic"):
                ctx = _c
                break
        if not ctx:
            _last = spoken[-1].get("intake_context")
            ctx = _last if isinstance(_last, dict) else {}
        return jsonify({
            "arc_id": arc_id,
            "topic": ctx.get("topic"),
            "audience": ctx.get("audience"),
            "strategic_context": ctx.get("strategic_context"),
            "target_length_seconds": ctx.get("target_length_seconds"),
            "slides": ctx.get("slides") or [],
            "presentation_ref": ctx.get("presentation_ref"),
        }), 200
    except Exception as e:
        logger.error("arc setup failed arc=%s: %s", arc_id, e,
                     exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR",
                        "error": "Failed to load the setup"}), 500


@v2_bp.route("/explore/arc/<arc_id>/context-document", methods=["POST"])
@require_auth
def v2_explore_upload_context_document(arc_id):
    """Upload a supplementary CONTEXT document (X-1, founder 2026-07-24) — a
    report / case metrics / Q&A (up to ~20 pages) ALONGSIDE the deck. We
    extract its plain text and store it against the arc so the assembly and
    feedback can draw on the background.

    L1: BACKGROUND only — its facts inform feedback/continuity, never the
    verbatim ideal text. multipart `file` (PDF, or UTF-8 text/markdown).

    200 { ok, pages, chars, truncated } · 400 INVALID_INPUT / NO_TEXT ·
    404 · 413 FILE_TOO_LARGE · 500
    """
    try:
        owned, _ = _arc_owned_by_caller(arc_id)
        if not owned:
            return jsonify({"code": "NOT_FOUND",
                            "error": "project not found"}), 404
        _max_bytes = max(1, int(
            getattr(config, "CONTEXT_DOC_MAX_MB", 25) or 25)) * 1024 * 1024
        if (request.content_length or 0) > _max_bytes:
            return jsonify({"code": "FILE_TOO_LARGE",
                            "error": "the document is too large"}), 413
        f = request.files.get("file")
        if f is None:
            return jsonify({"code": "INVALID_INPUT",
                            "error": "file is required"}), 400
        data = f.read() or b""
        if not data:
            return jsonify({"code": "INVALID_INPUT",
                            "error": "the file is empty"}), 400
        if len(data) > _max_bytes:
            return jsonify({"code": "FILE_TOO_LARGE",
                            "error": "the document is too large"}), 413
        from services.context_document import extract_context_text
        parsed = extract_context_text(
            data, content_type=getattr(f, "content_type", None),
            filename=getattr(f, "filename", None))
        if not parsed.get("text"):
            return jsonify({
                "code": "NO_TEXT",
                "error": "no readable text found in the document"}), 400
        db.upsert_arc_context_document(
            arc_id, parsed["text"], parsed["pages"], parsed["chars"],
            filename=getattr(f, "filename", None),
            truncated=parsed["truncated"])
        return jsonify({"ok": True, "pages": parsed["pages"],
                        "chars": parsed["chars"],
                        "truncated": parsed["truncated"]}), 200
    except Exception as e:
        logger.error("context-document upload failed arc=%s: %s", arc_id, e,
                     exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to upload"}), 500


@v2_bp.route("/explore/arc/<arc_id>/context-document", methods=["GET"])
@require_auth
def v2_explore_get_context_document(arc_id):
    """Whether a context document is attached (X-1) — the FE renders the chip
    + a 'replace' affordance. The text itself is NOT returned (background
    only). 200 { has_document, pages?, chars?, truncated?, filename? } · 404
    """
    try:
        owned, _ = _arc_owned_by_caller(arc_id)
        if not owned:
            return jsonify({"code": "NOT_FOUND",
                            "error": "project not found"}), 404
        row = db.get_arc_context_document(arc_id)
        if not row or not (row.get("text") or "").strip():
            return jsonify({"has_document": False}), 200
        return jsonify({
            "has_document": True,
            "pages": row.get("pages"),
            "chars": row.get("chars"),
            "truncated": bool(row.get("truncated")),
            "filename": row.get("filename"),
        }), 200
    except Exception as e:
        logger.error("context-document GET failed arc=%s: %s", arc_id, e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to load"}), 500


# ── willab — game + snippet library (founder 2026-07-06: PAID, STUBBED) ─
#
# Neither feature exists yet — these are gated stubs so the FE can wire the
# paywall now: unpaid → 402 (drives purchase intent pre-launch); PAID → an
# honest 501 "not yet available" (never a fake unlock).


def _charge_arc_deliverable(user_id, action, arc_id):
    """Charge a once-per-arc deliverable. NEVER raises, NEVER blocks.

    Token pricing Phase 1. Returns the ChargeResult-ish dict or None; callers
    IGNORE the outcome by design. These deliverables are reads of content the
    take already generated — the marginal cost to us is zero — so refusing to
    serve one on a low balance would withhold something already produced and
    paid for, which is exactly the failure fence §6.1 exists to prevent.

    ref_id=arc_id makes it idempotent: re-opening the game or the insights for
    the same presentation charges once, ever. The ledger's partial unique index
    on (user_id, action, ref_id) is the real guard.
    """
    try:
        from services.token_account import charge
        return charge(str(user_id), action, ref_id=str(arc_id)).as_dict()
    except Exception as e:
        logger.warning("token charge failed action=%s arc=%s err=%s",
                       action, arc_id, e)
        return None


@v2_bp.route("/arc/<arc_id>/game", methods=["GET"])
@require_auth
def v2_arc_game(arc_id):
    # NOTE: token charge is applied below, after the arc is confirmed to
    # belong to the caller — see _charge_arc_deliverable.
    """Engine 5 (founder 2026-07-11) — the key-moments game, replacing the
    501 stub. Free (the $25 gate is retired, single-deliverable 2026-07-17).

    Rounds mix the arc's coach-confirmed key moments with the user's OWN
    coach-unmarked moments as decoys; truth is NEVER in this payload (the
    FE learns it by answering). Deterministic order; ?snippet=<id> pins
    that round first (deep links from the Key-moment button / PDF).

    Response 200 { arc_id, rounds:[{round, snippet_id, transcript,
                   audio_ref, start_offset_ms, duration_ms}] }
             200 { arc_id, rounds: [], reason: "NO_KEY_MOMENTS_YET" }
             402 · 404 · 500
    """
    try:
        owned, _ = _arc_owned_by_caller(arc_id)
        if not owned:
            return jsonify({"code": "NOT_FOUND", "error": "arc not found"}), 404
        from services.game_engine import build_game_rounds
        rounds = build_game_rounds(
            db, arc_id, request.user_id,
            first_snippet=(request.args.get("snippet") or None),
        )
        body = {"arc_id": arc_id, "rounds": rounds}
        if not rounds:
            # honest empty state — the coach hasn't confirmed key moments yet
            body["reason"] = "NO_KEY_MOMENTS_YET"
        else:
            # Charge only when there is actually a game to play. An empty
            # NO_KEY_MOMENTS_YET response is the user finding out the coach
            # hasn't marked anything yet — billing them for that would charge
            # for our latency.
            _charge_arc_deliverable(request.user_id, "game", arc_id)
        return jsonify(body), 200
    except Exception as e:
        logger.error("arc game failed arc=%s: %s", arc_id, e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to load game"}), 500


@v2_bp.route("/arc/<arc_id>/game/answers", methods=["POST"])
@require_auth
def v2_arc_game_answer(arc_id):
    """One game answer → verdict + the "Here is why" content (Engine 5).

    Persists the answer into snippet_peer_labels (source='game') as
    SECOND-ORDER signal below coach truth (L2/L3 — never joined into the
    coach corpus). The why paragraphs are qualitative-only (AC-9): the
    moment's load-bearing words, this user's mined acoustic patterns
    (Engine 4), and the moment's delivery technique; plus the coach's
    breakthrough video when one is attached.

    Body: { "round_id": uuid, "answer": bool }
      (round_id IS the moment's snippet id, echoed from the game GET;
       `snippet_id` / `answer_is_key` accepted as aliases.)
    200 { correct, truth_is_key, why: [str], keywords: [str], video_ref }
    400 · 402 · 404 · 500
    """
    try:
        owned, _ = _arc_owned_by_caller(arc_id)
        if not owned:
            return jsonify({"code": "NOT_FOUND", "error": "arc not found"}), 404
        body = request.get_json(silent=True) or {}
        snippet_id = body.get("round_id") or body.get("snippet_id")
        if not isinstance(snippet_id, str) or not _is_valid_uuid(snippet_id):
            return jsonify({
                "code": "INVALID_INPUT", "error": "round_id must be a UUID",
            }), 400
        answer = body.get("answer")
        if answer is None:
            answer = body.get("answer_is_key")
        # bool = the legacy wire; the ternary instrument is the contract
        # now (founder 2026-08-10: "yes / no / idk" — idk rides as
        # 'neutral', the same vocabulary every other label lane uses).
        if not isinstance(answer, bool) and answer not in ("yes", "no",
                                                           "neutral"):
            return jsonify({
                "code": "INVALID_INPUT",
                "error": "answer must be a boolean or yes/no/neutral",
            }), 400
        from services.game_engine import answer_round
        result = answer_round(
            db, arc_id, request.user_id, snippet_id, answer,
        )
        if result is None:
            return jsonify({
                "code": "SNIPPET_NOT_FOUND",
                "error": "That moment is not part of this training",
            }), 404
        return jsonify(result), 200
    except Exception as e:
        logger.error("arc game answer failed arc=%s: %s", arc_id, e,
                     exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to judge answer"}), 500


@v2_bp.route("/arc/<arc_id>/game/save", methods=["POST"])
@require_auth
def v2_arc_game_save(arc_id):
    """"Save to daily practice" — bookmark this game under today's date
    (Engine 5 / backlog 3.3). Idempotent per (user, arc, day).
    200 { saved } · 402 · 404 · 500"""
    try:
        owned, _ = _arc_owned_by_caller(arc_id)
        if not owned:
            return jsonify({"code": "NOT_FOUND", "error": "arc not found"}), 404
        if not db.insert_game_save(str(request.user_id), str(arc_id)):
            return jsonify({
                "code": "V2_ERROR", "error": "Could not save the practice",
            }), 500
        return jsonify({"saved": True, "arc_id": arc_id}), 200
    except Exception as e:
        logger.error("arc game save failed arc=%s: %s", arc_id, e,
                     exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to save"}), 500


@v2_bp.route("/arc/<arc_id>/snippet-library", methods=["GET"])
@require_auth
def v2_arc_snippet_library(arc_id):
    """Stub — the per-user snippet library (not yet built). 501 until it
    ships."""
    try:
        owned, _ = _arc_owned_by_caller(arc_id)
        if not owned:
            return jsonify({"code": "NOT_FOUND", "error": "arc not found"}), 404
        return jsonify({
            "code": "NOT_YET_AVAILABLE",
            "message": "Your snippet library is coming soon.",
        }), 501
    except Exception as e:
        logger.error("arc snippet-library failed arc=%s: %s", arc_id, e,
                     exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR", "error": "Failed to load snippet library",
        }), 500
