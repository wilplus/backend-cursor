"""The internal publish path: /v2/internal/*.

The Willab publish contract that delivers canonical exact-evidence
FeedbackItems, and the whisper-health probe. Called by
the internal webhook tier, never by a browser.

Moved verbatim out of ``routes/v2_routes.py`` (god-file split, phase 5);
bodies are byte-identical. Routes register on the SAME ``v2_bp`` object, so
endpoint names and the URL map are unchanged.

Re-exported from ``routes.v2_routes`` for import compatibility.
"""
import logging

import sentry_sdk
from flask import jsonify, request

import os
import uuid

from routes.admin import require_admin_or_coach
from routes.v2.coach import _save_coach_snippet_lanes
from routes.v2.common import _is_valid_uuid
from utils.errors import safe_error
from config import Config
from routes.v2.blueprint import v2_bp
from services.db import db
from services.feedback_repository import (
    FeedbackContractError,
    FeedbackRepository,
    normalize_coach_overall_message,
)

logger = logging.getLogger(__name__)
config = Config()


@v2_bp.route("/internal/whisper-health", methods=["GET"])
def v2_internal_whisper_health():
    """Diagnostic: does the running process actually have OPENAI_API_KEY?

    Hit this from a browser or curl. The response tells us deterministically
    whether the OpenAI client can be constructed at runtime AND whether a
    real API call to OpenAI succeeds — without needing to trigger a real
    recording or sift through Railway logs.

    Auth: intentionally none — leaks no secret material; only metadata
    (length, first 7 chars masked, model count) about whether the integration
    is wired up.
    """
    try:
        from services.openai_service import OpenAIService
        svc = OpenAIService()
        key = (config.OPENAI_API_KEY or "")

        # Live API reachability check — list models. Cheap call (one
        # request, ~100ms), proves the key is valid AND the network can
        # reach api.openai.com from this Railway container.
        api_reachable = False
        api_error: str | None = None
        api_model_count = 0
        if svc.client:
            try:
                models = svc.client.models.list()
                api_reachable = True
                # `data` is a list of Model objects on the response
                api_model_count = len(getattr(models, "data", []) or [])
            except Exception as call_err:
                api_error = f"{type(call_err).__name__}: {call_err}"

        # Also verify which git commit this process is running. Helps
        # confirm Railway has picked up the latest deploy (e.g. the
        # explicit transcription log in e7271b8). Read from RAILWAY_GIT_COMMIT_SHA
        # (Railway-injected) or fall back to RAILWAY_DEPLOYMENT_ID.
        git_sha = (
            os.environ.get("RAILWAY_GIT_COMMIT_SHA")
            or os.environ.get("RAILWAY_DEPLOYMENT_ID")
            or None
        )

        return jsonify({
            "client_initialized": svc.client is not None,
            "api_key_present": bool(key),
            "api_key_length": len(key),
            "api_key_prefix": (key[:7] + "...") if key else None,
            "api_reachable": api_reachable,
            "api_error": api_error,
            "api_model_count": api_model_count,
            "git_sha": git_sha,
            # Echo back which env vars are actually visible at runtime so we
            # can spot Railway-scoped misses (preview vs production env).
            "env_visible": {
                "OPENAI_API_KEY": bool(os.environ.get("OPENAI_API_KEY")),
                "BACKEND_URL_INTERNAL": bool(os.environ.get("BACKEND_URL_INTERNAL")),
                "R2_PUBLIC_BASE_URL": bool(os.environ.get("R2_PUBLIC_BASE_URL")),
            },
        }), 200
    except Exception as e:
        logger.error("whisper-health failed: %s", e, exc_info=True)
        return safe_error("INTERNAL_ERROR", 500, exc=e)


def publish_one_session(session_id, actor_user_id):
    """Publish ONE take, end to end. Returns
    ``{session_id, published: bool, reason: str|None}`` and NEVER raises.

    THE SHARED CORE OF EVERY PUBLISH DOOR. Extracted 2026-08-14 when the
    coach panel's "Publish the full analysis" button was found to be a dead
    end: it POSTed to /v2/coach/arc/<id>/publish-analysis, which had been a
    410 tombstone since publish was replaced by verify (2026-07-17), while
    the ONLY code that sets ``results_published_at`` sat behind
    /v2/internal/publish-session-results — a route the frontend has no BFF
    path to. So nothing the coach could click published anything, which is
    why 46 August sessions were recorded and none delivered.

    Rather than give the arc route its own copy of the sequence (the exact
    drift the shared contract helper exists to prevent), both doors now call
    this: contract → flip the flag → refresh the album.

    NO EMAIL HERE, deliberately. The internal door owns the results-ready
    email because it owns the address lookup and the unsubscribe pipeline;
    the in-app Lounge card fires inside the contract helper either way, so a
    coach-panel publish still nudges the student.
    """
    out = {"session_id": str(session_id), "published": False, "reason": None}
    try:
        contract = _apply_willab_publish_contract(
            session_id, {"notify_client": False}, actor_user_id,
        )
        if contract is not None:
            try:
                _resp, _status = contract
                _payload = _resp.get_json() or {}
                out["reason"] = str(_payload.get("code") or f"HTTP_{_status}")
            except Exception:
                out["reason"] = "CONTRACT_FAILED"
            return out

        db.v2_publish_session_results(session_id)

        # THE VOICE ALBUM — publish releases the coach signal, so this is the
        # moment an aligned moment can land. Best-effort: an album miss never
        # blocks a publish (LIVE LOOP).
        try:
            _sess = db.v2_get_session_by_id(str(session_id)) or {}
            _arc = _sess.get("arc_id")
            if _arc:
                from services.voice_album import refresh_voice_album
                refresh_voice_album(_arc, database=db)
                # ANNOUNCE IT (founder 2026-08-15). The album filled silently
                # until today — capture-only, because its read surface needed
                # signed copy. Only on an actual insert, and the bubble is
                # idempotent per ARC, so a second moment on a later take does
                # not re-announce it.
                if _sess.get("user_id"):
                    from services.arc_notifications import (
                        fire_voice_album_ready,
                    )
                    fire_voice_album_ready(db, _sess.get("user_id"), _arc)
        except Exception as _va_err:
            logger.warning("voice_album: publish hook failed sid=%s: %s",
                           session_id, _va_err)

        out["published"] = True
        return out
    except Exception as e:
        logger.error("publish_one_session failed sid=%s: %s", session_id, e,
                     exc_info=True)
        sentry_sdk.capture_exception(e)
        out["reason"] = "PUBLISH_FAILED"
        return out


def _apply_willab_publish_contract(session_id, body, actor_user_id):
    """Publish exact-evidence FeedbackItems and preserve delivery effects.

    Paragraph feedback is validated and persisted through the canonical
    repository. Zero surfaced items is a successful professional verdict:
    "no changes needed". The optional take-level summary and video remain a
    separate coach-review layer; neither can mutate accepted user text.

    Returns
    -------
    None
        Success.
    (flask_response, status_int)
        Return this directly from the caller. Nothing has been flipped or
        emailed at that point.
    """
    if "insights_payload" in body:
        return jsonify({
            "code": "INVALID_INPUT",
            "error": (
                "insights_payload is retired; save exact-evidence feedback "
                "items and send overall_message separately"
            ),
        }), 422

    session = db.v2_get_session_by_id(session_id) or {}
    if not session:
        return jsonify({"code": "NOT_FOUND", "error": "Take not found"}), 404

    overall_message = session.get("coach_overall_message")
    try:
        if "overall_message" in body:
            overall_message = normalize_coach_overall_message(
                body.get("overall_message"))
            if not db.set_session_coach_overall_message(
                session_id, overall_message,
            ):
                return jsonify({
                    "code": "V2_ERROR",
                    "error": "Failed to persist coach review summary",
                }), 500
        feedback_items = FeedbackRepository(db).publish(
            str(session_id), actor_user_id=str(actor_user_id),
        )
    except (ValueError, FeedbackContractError) as error:
        return jsonify({
            "code": "PUBLISH_CONTRACT_VIOLATION", "error": str(error),
        }), 422

    logger.info(
        "publish_contract.willab session=%s feedback_items=%d overall=%s",
        session_id, len(feedback_items), bool(overall_message),
    )

    # Arc lifecycle (founder #1, 2026-07-06): a publish may complete the
    # "coach-reviewed" condition — fire the right >=3-takes card now
    # (best_presentation_ready only when reviewed AND paid; else
    # transcript_ready). Idempotent per (arc, kind); best-effort.
    try:
        _pub_sess = db.v2_get_session_by_id(session_id) or {}
        _pub_arc = _pub_sess.get("arc_id")
        if _pub_arc:
            from services.arc_notifications import (
                maybe_fire_best_presentation_ready,
            )
            maybe_fire_best_presentation_ready(db, _pub_arc)
    except Exception as _an_err:
        logger.warning(
            "publish_contract.arc_card_failed session=%s err=%s (non-fatal)",
            session_id, _an_err,
        )

    # Subsystem V — freeze the FINAL delivered comment onto each current coach
    # take-level video (write-once; the comment→video pair as delivered).
    # Best-effort: never affects the publish.
    try:
        _cur_assets = db.get_current_coach_video_assets_for_session(session_id)
        if _cur_assets:
            _overall = (overall_message or "").strip() or None
            for _a in _cur_assets:
                if _a.get("comment_text_at_publish"):
                    continue  # already frozen
                if _a.get("content_type") == "take_summary" and _overall:
                    db.set_coach_video_comment_at_publish(
                        _a.get("id"), _overall,
                    )
    except Exception as _cv_err:
        logger.warning(
            "publish_contract.coach_video_snapshot_failed session=%s err=%s "
            "(non-fatal)", session_id, _cv_err,
        )

    # ── User nudge: Lounge "insights ready" card (best-effort, idempotent). ──
    # suppress_lounge_card (founder 2026-07-13): the ARC-BATCH publish door
    # publishes every take in one action and fires ONE arc-level card instead
    # — it opts out of the per-take card here. Per-take doors never set it.
    try:
        from datetime import datetime as _dt, timezone as _tz
        _sess = db.v2_get_session_by_id(session_id) or {}
        _owner = _sess.get("user_id")
        if body.get("suppress_lounge_card") is True:
            _owner = None  # skip the card; everything else unchanged
        if _owner:
            _ctx = _sess.get("intake_context") if isinstance(
                _sess.get("intake_context"), dict) else {}
            db.insert_lounge_messages(str(_owner), [{
                "client_id": str(uuid.uuid5(
                    uuid.NAMESPACE_URL, f"willab-insight:{session_id}",
                )),
                "role": "bot",
                "kind": "insight",
                "body": "Your coach's insights are ready.",
                "metadata": {
                    "session_id": session_id, "insight_ref": session_id,
                    # F4 — so the card reads "Feedback on {topic} (Take N)"
                    # instead of the date fallback.
                    "topic": _ctx.get("topic"),
                    "take_index": _sess.get("take_index"),
                },
                "client_created_at": _dt.now(_tz.utc).isoformat(),
            }])
            logger.info(
                "publish_contract.lounge_card session=%s owner=%s",
                session_id, _owner,
            )
    except Exception as _le:
        logger.warning(
            "publish_contract.lounge_append_failed session=%s err=%s "
            "(non-fatal)", session_id, _le,
        )

    # ── METER THE COACH REVIEW (v3, founder 2026-08-14). This publish IS the
    # delivery — exact-evidence feedback published plus the "insights ready"
    # card above — so it consumes ONE of the tier's monthly coach slots and ZERO
    # tokens. Human work is metered in reviews; tokens meter machine work.
    #
    # TWO DEFECTS FIXED HERE, both of which made the allowance fictional:
    #
    #   1. `coach_feedback` used to sit OUTSIDE COACH_ACTIONS while the only
    #      member, `coach_review`, had no call site anywhere. So no publish in
    #      production ever moved `coach_reviews_used`, and a tier selling
    #      "3 coach reviews" metered nothing at all.
    #   2. ARC SESSIONS WERE SKIPPED ENTIRELY — and the coached product runs
    #      on arcs, so the flagship flow delivered founder time for free. The
    #      old justification (arcs are "monetized per-arc") does not survive
    #      v3: the per-arc token actions buy machine deliverables, never a
    #      sitting of the founder's time.
    #
    # STILL SOFT, and that rule is untouched: nothing below branches on the
    # result. A student past their allowance still receives work the coach has
    # already done — the gate belongs on STARTING a review, never on
    # delivering one that exists. A refusal is logged loudly instead, because
    # an over-allowance review is a real cost to the founder's calendar and
    # must not be silent.
    #
    # IDEMPOTENT PER SESSION via ref_id — a re-publish never double-counts.
    #
    # Best-effort: a billing hiccup must never unwind a published session.
    try:
        _sess_for_charge = db.v2_get_session_by_id(session_id) or {}
        _charge_owner = _sess_for_charge.get("user_id")
        if _charge_owner:
            from services.token_account import charge as _charge
            _res = _charge(str(_charge_owner), "coach_feedback",
                           ref_id=str(session_id))
            if _res.reason == "coach_cap_reached":
                logger.warning(
                    "publish_contract.coach_review_over_allowance "
                    "session=%s user=%s — DELIVERED anyway (soft); the "
                    "tier's monthly coach slots are spent",
                    session_id, _charge_owner,
                )
            else:
                logger.info(
                    "publish_contract.coach_review_metered session=%s ok=%s "
                    "reason=%s", session_id, _res.ok, _res.reason or "-",
                )
    except Exception as _ce:
        logger.warning(
            "publish_contract.coach_review_meter_failed session=%s err=%s "
            "(non-fatal)", session_id, _ce,
        )

    return None


@v2_bp.route("/internal/publish-session-results", methods=["POST"])
@require_admin_or_coach
def v2_internal_publish_session_results():
    """willab publish door — the coach (or admin) publishes a session's
    insights. (Re-gated to require_admin_or_coach: the old /admin/sessions/
    <id>/publish door was excised, so this is the sole surviving publish path
    that runs the shared _apply_willab_publish_contract; the FE's
    publishWillabSession already POSTs here.)

    Sends the results-ready email with a CTA to /results — GATED on
    notify_client (the in-app Lounge nudge always fires in the contract
    helper; only the email is opt-out).
    """

    try:
        body = request.get_json(silent=True) or {}
        session_id = (body.get("session_id") or "").strip()

        if not _is_valid_uuid(session_id):
            return jsonify({
                "code": "INVALID_INPUT",
                "error": "session_id must be a valid UUID",
            }), 400

        # Fetch session to get user email
        session = db.v2_get_session_by_id(session_id)
        if not session:
            return jsonify({
                "code": "NOT_FOUND",
                "error": "Session not found",
            }), 404

        # Save-at-publish (founder 2026-07-13): the FE no longer autosaves
        # per keystroke — it may send the coach's full per-snippet authoring
        # inline as ``snippets: [{id, note?, tag?, surfaced?, ...}]``. Persist
        # each through the same helper as /coach/sessions/<id>/snippets/<id>
        # (validators/caps/
        # stores shared — the doors cannot drift), BEFORE the contract runs
        # so assemble-mode reads the fresh drafts. Optional + backward-
        # compatible: absent → today's behavior (pre-saved coach_state).
        _inline_snips = body.get("snippets")
        if isinstance(_inline_snips, list) and _inline_snips:
            _known_ids = {
                str(s.get("id"))
                for s in (db.get_snippets_by_session(session_id) or [])
                if s.get("id")
            }
            for _entry in _inline_snips:
                if not isinstance(_entry, dict):
                    return jsonify({
                        "code": "INVALID_INPUT",
                        "error": "snippets: entries must be objects",
                    }), 422
                _snip_id = str(_entry.get("id") or "").strip()
                if _snip_id not in _known_ids:
                    return jsonify({
                        "code": "SNIPPET_NOT_FOUND",
                        "error": f"snippet {_snip_id or '(missing id)'} "
                                 "not in this session",
                    }), 404
                _fields = dict(_entry)
                _fields.pop("id", None)
                _lane_err = _save_coach_snippet_lanes(
                    session_id, _snip_id, _fields,
                )
                if _lane_err is not None:
                    return _lane_err

        # Canonical publish gate: validates exact evidence, permits an empty
        # "no changes needed" verdict, and fires the existing delivery effects
        # before the session is flipped or emailed.
        _contract_err = _apply_willab_publish_contract(
            session_id, body, request.user_id,
        )
        if _contract_err is not None:
            return _contract_err

        # Phase 10 — emit RLHF annotation events for every snippet in
        # this session BEFORE the status flip + email. Each row in
        # admin_annotation_events captures (ai_draft, admin_final) for
        # admin_comment, follow_up_question, and stress coach_label_
        # notes. Approved-as-is gets reason_chip='approved_as_is';
        # edits get the diff. Best-effort — never blocks the publish.
        try:
            events_written = db.record_snippet_publish_annotations(
                session_id=session_id,
                admin_user_id=str(request.user_id),
            )
            logger.info(
                "publish-results: rlhf events emitted session=%s count=%d",
                session_id, events_written,
            )
        except Exception as annot_err:
            logger.warning(
                "publish-results: rlhf emit failed session=%s err=%s "
                "(non-fatal)", session_id, annot_err,
            )

        # Flip results status so frontend transitions from waiting → results
        try:
            db.v2_update_session_status_unscoped(session_id, "completed")
        except Exception as flip_err:
            logger.warning("publish-results: status flip failed (non-fatal): %s", flip_err)

        user_id = session.get("user_id")
        if not user_id:
            return jsonify({
                "code": "NO_USER",
                "error": "Session has no associated user (not yet claimed)",
            }), 400

        # Fetch user email from Supabase auth
        try:
            import httpx
            auth_headers = {
                "Authorization": f"Bearer {config.SUPABASE_SERVICE_ROLE_KEY}",
                "apikey": config.SUPABASE_SERVICE_ROLE_KEY,
            }
            user_url = f"{config.SUPABASE_URL.rstrip('/')}/auth/v1/admin/users/{user_id}"
            resp = httpx.get(user_url, headers=auth_headers, timeout=10)
            if resp.status_code != 200:
                logger.warning("publish-results: failed to fetch user %s from auth", user_id)
                return jsonify({
                    "code": "AUTH_ERROR",
                    "error": "Could not fetch user email",
                }), 502
            user_data = resp.json()
            user_email = user_data.get("email")
        except Exception as fetch_err:
            logger.error("publish-results: fetch user error: %s", fetch_err)
            return jsonify({
                "code": "AUTH_ERROR",
                "error": "Could not fetch user email",
            }), 502

        if not user_email:
            return jsonify({
                "code": "NO_EMAIL",
                "error": "User has no email",
            }), 400

        # Flip the session status so /results page shows snippets.
        # Done BEFORE the email send so a failed send never blocks
        # the user from reaching their results via direct link.
        db.v2_publish_session_results(session_id)

        # THE VOICE ALBUM (founder 2026-08-14): publish releases the coach
        # signal, so this is the moment an aligned moment can land —
        # acoustic emphasize + user approved + coach CONFIDENCE QUORUM, now
        # public. Best-effort: an album miss never blocks a publish (LIVE LOOP).
        try:
            _arc_for_album = (session or {}).get("arc_id") \
                if isinstance(session, dict) else None
            if _arc_for_album:
                from services.voice_album import refresh_voice_album
                refresh_voice_album(_arc_for_album, database=db)
                # ANNOUNCE IT (founder 2026-08-15) — same rule as the shared
                # helper: only on a real insert, idempotent per arc.
                if user_id:
                    from services.arc_notifications import (
                        fire_voice_album_ready,
                    )
                    fire_voice_album_ready(db, user_id, _arc_for_album)
        except Exception as _va_err:
            logger.warning("voice_album: publish hook failed sid=%s: %s",
                           session_id, _va_err)

        # (Old charisma-profile compute removed in the old-subsystem
        # excision — willab publishes never used the result, and AC-9
        # already strips charisma_profile from user payloads. The legacy
        # admin compute-metrics route still computes it on demand.)

        # ── Phase 14 — new PostSessionResultsEmail render pipeline ──
        # Replaces the inline HTML build. The render service handles:
        #   - per-user pref check (skip if unsubscribed)
        #   - server-to-server render call into Next.js
        #   - RFC 8058 List-Unsubscribe headers
        #   - unsubscribe token mint + URL
        # Props for the template:
        first_name: str | None = None
        try:
            details = db.v2_get_student_details(user_id) or {}
            full_name = (details.get("name") or "").strip()
            if full_name:
                first_name = full_name.split()[0]
        except Exception as e:
            logger.warning(
                "publish-results: name lookup failed user=%s err=%s",
                user_id, e,
            )

        snippet_count = 0
        try:
            commented = db.get_snippets_with_comments_by_session(session_id)
            snippet_count = len(commented or [])
        except Exception as e:
            logger.warning(
                "publish-results: snippet count lookup failed "
                "session=%s err=%s", session_id, e,
            )

        top_theme: str | None = None
        try:
            sess_row = db.v2_get_session_by_id(session_id) or {}
            top_theme = (
                (sess_row.get("stickiness_top_topic") or "").strip() or None
            )
        except Exception:
            pass

        from services.post_session_results_email import (
            send_publish_results_email,
        )

        # Deep-link → the arc's ideal text (founder 2026-08-15). Same URL the
        # email's CTA carries, built the same way, because this value is
        # echoed to the caller and a response that disagreed with the email
        # would be two different answers to "where did we send them".
        from urllib.parse import quote as _q
        _arc_for_link = str((sess_row or {}).get("arc_id") or "").strip()
        _fe = config.PUBLIC_FRONTEND_URL.rstrip("/")
        results_url = (
            f"{_fe}/chat?idealArc={_q(_arc_for_link, safe='')}"
            if _arc_for_link else f"{_fe}/chat"
        )

        # notify_client gate (C): the in-app Lounge nudge already fired in the
        # shared contract helper (always). Only the EMAIL is opt-out; default
        # true preserves the pre-notify_client behaviour (FE sets first-publish
        # = true, edit = false per S.2-G).
        if not bool(body.get("notify_client", True)):
            logger.info(
                "publish-results: email suppressed (notify_client=false) "
                "session_id=%s", session_id,
            )
            return jsonify({
                "status": "ok",
                "email_sent_to": None,
                "results_url": results_url,
                "email_suppressed": True,
            }), 200

        send_result = send_publish_results_email(
            user_id=user_id,
            user_email=user_email,
            user_first_name=first_name,
            arc_id=_arc_for_link or None,
            snippet_count=snippet_count,
            top_theme=top_theme,
            session_id=session_id,
        )
        status = send_result.get("status")

        if status == "sent":
            logger.info(
                "publish-results: email sent session_id=%s user_id=%s "
                "email=%s", session_id, user_id, user_email,
            )
            return jsonify({
                "status": "ok",
                "email_sent_to": user_email,
                "results_url": results_url,
            }), 200

        if status == "skipped":
            reason = send_result.get("reason") or "unknown"
            logger.info(
                "publish-results: email skipped session_id=%s user_id=%s "
                "reason=%s", session_id, user_id, reason,
            )
            return jsonify({
                "status": "ok",
                "email_sent_to": None,
                "results_url": results_url,
                "email_skipped_reason": reason,
            }), 200

        # render_failed / send_failed — publish itself succeeded
        # (the session is already flipped to completed) so we return
        # 200 with a warning rather than blocking on the email step.
        logger.error(
            "publish-results: email %s session_id=%s user_id=%s err=%s",
            status, session_id, user_id, send_result.get("error"),
        )
        return jsonify({
            "status": "ok",
            "email_sent_to": None,
            "results_url": results_url,
            "warning": (
                "Results published but email delivery failed: "
                f"{send_result.get('error') or status}"
            ),
        }), 200

    except Exception as e:
        logger.error("publish-results: failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to publish results"}), 500
