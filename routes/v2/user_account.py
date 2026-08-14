"""The signed-in user's account surface: profile/intake, consent flags,
credits, KPI timeline, recording progress, last setup, audits, game history.

Moved verbatim out of ``routes/v2_routes.py`` (god-file split, phase 3);
bodies are byte-identical. Routes register on the SAME ``v2_bp`` object, so
endpoint names and the URL map are unchanged.

Re-exported from ``routes.v2_routes`` for import compatibility.
"""
import logging

import sentry_sdk
from flask import jsonify, request

from auth import require_auth
from config import Config
from routes.admin import is_coach
from routes.v2.blueprint import v2_bp
from routes.v2.common import _client_ip_from_request
from services.db import db

logger = logging.getLogger(__name__)
config = Config()


@v2_bp.route("/user/consent", methods=["GET", "PUT"])
@require_auth
def v2_user_consent():
    """Unified consent surface for the four prompted moments.

    Returns / accepts the four boolean consent flags the frontend
    surfaces during onboarding: mic-access, share-voice-clone,
    email-notifications, and Terms-of-Service acceptance. The first
    three are runtime preferences stored on user_settings; the
    fourth reads the immutable user_consents ledger against
    ``Config.CURRENT_TERMS_VERSION`` so the historical audit trail
    stays intact (we never UPDATE the ledger, only INSERT a new row
    on re-accept).

    Response shape (200, both GET and PUT)::

        {
          "has_answered":           bool,    # true once any flag
                                              # has been answered
          "mic_consent":            true|false|null,
          "mic_consent_set_at":     "ISO8601"|null,
          "share_consent":          true|false|null,
          "share_consent_set_at":   "ISO8601"|null,
          "email_consent":          true|false|null,
          "email_consent_set_at":   "ISO8601"|null,
          "terms_consent":          bool,     # true iff a
                                               # user_consents row
                                               # at the current
                                               # terms_version exists
          "terms_version_current":  "1.0",
          "terms_version_accepted": "1.0"|null,
          "terms_accepted_at":      "ISO8601"|null
        }

    NULL semantics:
      • mic/share/email = NULL  ⇒ user has never been asked. The
        frontend uses this to decide whether to surface the prompt
        in the first place. has_answered also stays false until at
        least one is non-NULL (or the user has accepted terms).
      • mic/share/email = true / false ⇒ user has explicitly
        answered. *_set_at is stamped at the moment of the answer.
      • terms_consent is computed, not stored on user_settings —
        it's a boolean derived from the ledger lookup.

    PUT body — every field is optional; only included keys are
    written (PATCH-style semantics)::

        {
          "mic_consent":   true | false | null,
          "share_consent": true | false | null,
          "email_consent": true | false | null,
          "terms_consent": true      # ONLY true is accepted —
                                      # accepting terms inserts a
                                      # ledger row at the current
                                      # version. false / null are
                                      # rejected since the ledger
                                      # is append-only and you
                                      # cannot un-accept.
        }

    Setting mic/share/email to null is a valid "clear" — the
    preference column goes back to NULL and the frontend re-prompts
    on the next visit. set_at is also cleared.

    Setting terms_consent=true is idempotent — if the user already
    has a row at the current version, no new row is written and
    the existing terms_accepted_at is preserved (the underlying
    upsert uses on_conflict=do_nothing).

    Responses:
      200 — full state echoed back (single round trip on PUT)
      400 INVALID_INPUT — bad body shape or terms_consent not true
      500 V2_ERROR / PERSIST_FAILED — DB hiccup
    """
    user_id = request.user_id

    try:
        if request.method == "PUT":
            body = request.get_json(silent=True)
            if not isinstance(body, dict):
                return jsonify({
                    "code": "INVALID_INPUT",
                    "error": "Request body must be a JSON object",
                }), 400

            # Validate the three runtime flags. None is a valid
            # "clear"; anything other than bool/None is rejected.
            def _validate(key: str):
                if key not in body:
                    return False, None
                value = body[key]
                if value is None or isinstance(value, bool):
                    return True, value
                return None, None  # signals invalid

            mic_present, mic_val = _validate("mic_consent")
            if mic_present is None:
                return jsonify({
                    "code": "INVALID_INPUT",
                    "error": "mic_consent must be true, false, or null",
                }), 400
            share_present, share_val = _validate("share_consent")
            if share_present is None:
                return jsonify({
                    "code": "INVALID_INPUT",
                    "error": "share_consent must be true, false, or null",
                }), 400
            email_present, email_val = _validate("email_consent")
            if email_present is None:
                return jsonify({
                    "code": "INVALID_INPUT",
                    "error": "email_consent must be true, false, or null",
                }), 400

            # Terms is append-only: only `true` is meaningful. We
            # reject `false`/`null` explicitly so callers don't
            # quietly assume they can rescind acceptance via this
            # endpoint (compliance: the ledger has no concept of
            # "un-accept" and the audit row stays once written).
            terms_consent_write = False
            if "terms_consent" in body:
                tc = body["terms_consent"]
                if tc is not True:
                    return jsonify({
                        "code": "INVALID_INPUT",
                        "error": (
                            "terms_consent only accepts true (accept "
                            "current terms). The legal ledger is "
                            "append-only — false/null are not valid."
                        ),
                    }), 400
                terms_consent_write = True

            # Persist the three runtime preferences first; terms
            # second so a terms-write failure doesn't leave the
            # frontend thinking it landed when only the prefs did.
            ok = db.set_user_consent_preferences(
                user_id=user_id,
                mic=mic_val,
                share=share_val,
                email=email_val,
                update_mic=bool(mic_present),
                update_share=bool(share_present),
                update_email=bool(email_present),
            )
            if not ok:
                return jsonify({
                    "code": "PERSIST_FAILED",
                    "error": (
                        "Could not save consent preferences. "
                        "Please retry."
                    ),
                }), 500

            if terms_consent_write:
                ip = (
                    request.headers.get("X-Forwarded-For", "")
                    .split(",")[0]
                    .strip()
                    or request.remote_addr
                )
                ua = request.headers.get("User-Agent")
                ledger_row = db.record_user_consent(
                    user_id=user_id,
                    terms_version=config.CURRENT_TERMS_VERSION,
                    ip_address=ip,
                    user_agent=ua,
                )
                if ledger_row is None:
                    return jsonify({
                        "code": "PERSIST_FAILED",
                        "error": (
                            "Could not record terms acceptance. "
                            "Please retry."
                        ),
                    }), 500

            # Fall through to the GET read-back so the response is
            # always the full current state — caller doesn't need a
            # follow-up fetch.

        state = db.get_user_consent_state(
            user_id,
            current_terms_version=config.CURRENT_TERMS_VERSION,
        )
        return jsonify(state), 200

    except Exception as e:
        logger.error(
            "user/consent %s failed: %s",
            request.method, e, exc_info=True,
        )
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR",
            "error": "Failed to load consent state",
        }), 500


# ── Chat-surface consent flags (Phase Single-Slot-Chat) ──────────
#
# GET / PUT /v2/user/sharing-consent — four-flag fan-out (Option A
# from the BE prompt). Each flag corresponds to one YesNoPills
# consent moment in the chat funnel:
#   mic_consent    — microphone permission
#   share_consent  — share recorded snippets with the human coach
#   email_consent  — receive weekly progress emails
#   terms_consent  — accept Terms & Privacy
#
# Storage: nullable booleans on user_settings (added by
# migrations/add_consent_flags_to_user_settings.sql). NULL = not
# yet answered → FE shows the prompt for that slot. TRUE/FALSE =
# answered.
#
# Legacy ``opt_in`` alias (response echo + PUT body acceptance)
# was removed in the Week-1 cleanup. The four canonical fields
# above are the only contract now. Stragglers that PUT ``opt_in``
# get a warning log and the field is silently ignored.

_CONSENT_FIELDS_FE = (
    "mic_consent",
    "share_consent",
    "email_consent",
    "terms_consent",
)


def _shape_consent_response(state: dict) -> dict:
    """Compose the GET/PUT response body from a consent state
    dict (as returned by ``db.get_consent_state``).

    has_answered = any of the four is non-null. FE uses it as a
    coarse "has the user been through the funnel at all" check;
    per-moment gating uses the individual fields.
    """
    has_answered = any(
        state.get(field) is not None
        for field in _CONSENT_FIELDS_FE
    )
    out = {
        "has_answered": has_answered,
        "mic_consent": state.get("mic_consent"),
        "share_consent": state.get("share_consent"),
        "email_consent": state.get("email_consent"),
        "terms_consent": state.get("terms_consent"),
    }
    return out


@v2_bp.route("/user/sharing-consent", methods=["GET"])
@require_auth
def v2_user_get_sharing_consent():
    """Return the user's four-flag consent state.

    Response 200::

        {
          "has_answered": bool,
          "mic_consent":   bool | null,
          "share_consent": bool | null,
          "email_consent": bool | null,
          "terms_consent": bool | null
        }
    """
    try:
        state = db.get_consent_state(str(request.user_id))
        return jsonify(_shape_consent_response(state)), 200
    except Exception as e:
        logger.error(
            "user_sharing_consent.get_error user=%s err=%s",
            getattr(request, "user_id", None), e, exc_info=True,
        )
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR",
            "error": "Failed to read consent state",
        }), 500


@v2_bp.route("/user/sharing-consent", methods=["PUT"])
@require_auth
def v2_user_put_sharing_consent():
    """Update any subset of the four consent flags.

    Body (JSON): any subset of mic_consent / share_consent /
    email_consent / terms_consent (each must be bool).

    Note: the legacy ``opt_in`` alias (which previously mapped to
    ``share_consent``) was removed in the Week-1 cleanup. If a
    caller still sends ``opt_in``, we log a warning and silently
    ignore it — use ``share_consent`` directly.

    Response 200: same shape as GET, echoing the post-write state.
    """
    try:
        user_id = str(request.user_id)
        body = request.get_json(silent=True) or {}
        if not isinstance(body, dict):
            return jsonify({
                "code": "INVALID_INPUT",
                "error": "Body must be a JSON object",
            }), 400

        # Legacy-caller detection — log once so we can spot
        # FE stragglers still sending opt_in. Silently ignored.
        if "opt_in" in body:
            logger.warning(
                "user_sharing_consent.legacy_field_ignored "
                "field=opt_in user=%s — use share_consent",
                user_id,
            )

        patch: dict = {}
        for field in _CONSENT_FIELDS_FE:
            if field in body:
                val = body[field]
                if val is not None and not isinstance(val, bool):
                    return jsonify({
                        "code": "INVALID_INPUT",
                        "error": f"{field} must be a boolean or null",
                    }), 400
                patch[field] = val

        if not patch:
            return jsonify({
                "code": "INVALID_INPUT",
                "error": (
                    "Body must include at least one of: "
                    "mic_consent, share_consent, email_consent, "
                    "terms_consent"
                ),
            }), 400

        new_state = db.upsert_consent_fields(user_id, patch)
        if new_state is None:
            return jsonify({
                "code": "V2_ERROR",
                "error": "Failed to write consent state",
            }), 500

        # ── Task 8 — append-only GDPR audit ledger ─────────────────
        # One row per changed field in user_consent_events. Failure-
        # tolerant: the preference upsert above already succeeded
        # and we don't want a ledger hiccup to look like the PUT
        # itself failed (the helper logs to Sentry instead).
        client_ip = _client_ip_from_request()
        user_agent = (request.headers.get("User-Agent") or "")[:512] or None
        for field, value in patch.items():
            try:
                db.insert_user_consent_event(
                    user_id=user_id,
                    consent_type=field,
                    consent_value=value,
                    ip_address=client_ip,
                    user_agent=user_agent,
                )
            except Exception as ledger_err:
                logger.warning(
                    "user_sharing_consent.ledger_failed "
                    "user=%s field=%s err=%s (non-fatal)",
                    user_id, field, ledger_err,
                )

        logger.info(
            "user_sharing_consent.put user=%s fields=%s",
            user_id, sorted(patch.keys()),
        )
        return jsonify(_shape_consent_response(new_state)), 200

    except Exception as e:
        logger.error(
            "user_sharing_consent.put_error user=%s err=%s",
            getattr(request, "user_id", None), e, exc_info=True,
        )
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR",
            "error": "Failed to update consent state",
        }), 500


@v2_bp.route("/user/kpi/timeline", methods=["GET"])
@require_auth
def v2_user_kpi_timeline():
    """Return the user's session-by-session KPI trajectory.

    M1.1 raw mode — per-session scores, no smoothing, no per-intent
    cuts. The smoothing layer ships in a follow-up once we have
    real distributions; the `smoothed_kpi` field will be additive
    so FE chart code keeps rendering across the rollout.

    Query params:
      limit (int, optional, default 200) — max series length

    Response 200:
      Shape documented in services.kpi_timeline.build_user_kpi_timeline.

    Response 401: missing auth (handled by decorator).
    Response 500: unexpected (FE should fall back to empty chart).
    """
    try:
        user_id = request.user_id
        limit_raw = request.args.get("limit")
        limit = 200
        if limit_raw:
            try:
                limit = max(1, min(int(limit_raw), 500))
            except ValueError:
                pass  # silently coerce to default; non-blocking

        from services.kpi_timeline import build_user_kpi_timeline
        payload = build_user_kpi_timeline(user_id, limit=limit)
        return jsonify(payload), 200

    except Exception as e:
        logger.error(
            "user/kpi/timeline failed: %s", e, exc_info=True,
        )
        sentry_sdk.capture_exception(e)
        # Soft-fail: return an empty payload so the FE chart renders
        # its empty state rather than an error banner. Shape mirrors
        # build_user_kpi_timeline — KPI fields removed per AC-9 (KPI
        # is private-lane / coach-side; never user-facing).
        return jsonify({
            "series": [],
            "summary": {
                "sessions_count": 0,
            },
        }), 200


# ── willab beta — user profile / intake (design §2, contract §3.1) ──
#
# The one-time, non-recording intake: the user picks a domain (one of
# five chips) + states a goal in their own words. Stored on
# user_settings (profile_domain + profile_goal), distinct from the
# admin-authored v2_speaker_profiles. Domain is metadata, never a flow
# fork. GET prefills the form / the Lab's read-only goal reminder.

_PROFILE_GOAL_MAX_LEN = 500


@v2_bp.route("/user/profile", methods=["GET"])
@require_auth
def v2_user_get_profile():
    """Read the user's intake profile.

    Response 200:
      { "domain": "<enum>" | null, "goal": "<str>" | null,
        "sex": "female"|"male"|"prefer_not_to_say" | null,
        "domain_vocabulary_default": [ ...seed for domain... ],
        "is_coach": bool }

    `domain_vocabulary_default` is the editable seed the Lab pre-fills
    `session_context.domain_vocabulary` from (empty list when no
    domain is set yet). Both domain + goal null pre-intake.

    `sex` is the self-declared speaker sex. It exists for ONE reason: it
    routes the cue weights of the voice-confidence composite, where pitch
    variability reverses direction between male and female speakers
    (services/voice_confidence.py). null = never asked, which is how the
    FE knows to show the question; "prefer_not_to_say" = asked and
    declined, so do NOT re-ask. It is not part of any score the user sees.

    `is_coach` (F.9b) is RENDER-ONLY — it lets the FE show/hide the coach
    surface. It is NEVER the authorization gate: every coach route is
    server-enforced via require_admin_or_coach against the coach_users
    allowlist. Append-only field; existing consumers ignore it.
    """
    try:
        from services.domains import default_domain_vocabulary
        profile = db.get_user_profile(request.user_id) or {
            "domain": None, "goal": None,
        }
        return jsonify({
            "domain": profile.get("domain"),
            "goal": profile.get("goal"),
            "sex": db.get_user_speaker_sex(request.user_id),
            "domain_vocabulary_default": default_domain_vocabulary(
                profile.get("domain"),
            ),
            "is_coach": is_coach(request.user_id),
        }), 200
    except Exception as e:
        logger.error(
            "user/profile GET failed: %s", e, exc_info=True,
        )
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR",
            "error": "Failed to fetch profile",
        }), 500


@v2_bp.route("/user/profile", methods=["POST"])
@require_auth
def v2_user_set_profile():
    """Submit the intake profile (design §3.1) — non-recording.

    Body:
      { "domain": "public_speaking|sales|executive_presence|
                   customer_service|interview_prep" | null,
        "goal":   "free text" | null,
        "sex":    "female|male|prefer_not_to_say" | null }

    All optional so a partial intake (domain picked, goal skipped, or
    vice-versa) is accepted — the intake is two bounded turns, but the
    store doesn't force both. `domain` (when present) must be one of
    the five enum keys; `goal` is trimmed, ≤500 chars, empty→null.

    KEY PRESENCE MATTERS for `sex` vs `{domain, goal}`. The pair is
    written as a FULL SET (posting only `domain` still clears `goal` —
    long-standing behaviour, unchanged), whereas `sex` is written on its
    own partial upsert. So a sex-only body — which is what the signup
    screen sends — leaves an existing intake alone, and an intake post
    from the Lab leaves a previously-declared sex alone. A body carrying
    neither `domain` nor `goal` no longer touches them at all; it echoes
    what is stored.

    `sex` routes the voice-confidence cue weights and nothing else — see
    the GET docstring and services/voice_confidence.py. Explicit null
    clears the answer back to "never asked".

    Responses:
      200 — same shape as GET (echoes persisted state + vocab default)
      422 INVALID_INPUT — bad domain/sex enum or over-long goal
      500 V2_ERROR — persist failed
    """
    try:
        from services.domains import (
            default_domain_vocabulary, is_valid_domain,
        )

        body = request.get_json(silent=True) or {}
        if not isinstance(body, dict):
            return jsonify({
                "code": "INVALID_INPUT", "error": "Body must be a JSON object",
            }), 422

        raw_domain = body.get("domain")
        domain: str | None = None
        if raw_domain is not None:
            if not is_valid_domain(raw_domain):
                return jsonify({
                    "code": "INVALID_INPUT",
                    "error": (
                        "domain: must be one of public_speaking, sales, "
                        "executive_presence, customer_service, interview_prep"
                    ),
                }), 422
            domain = raw_domain

        raw_goal = body.get("goal")
        goal: str | None = None
        if raw_goal is not None:
            if not isinstance(raw_goal, str):
                return jsonify({
                    "code": "INVALID_INPUT", "error": "goal: must be a string",
                }), 422
            cleaned = raw_goal.strip()
            if cleaned:
                if len(cleaned) > _PROFILE_GOAL_MAX_LEN:
                    return jsonify({
                        "code": "INVALID_INPUT",
                        "error": (
                            f"goal: must be {_PROFILE_GOAL_MAX_LEN} "
                            "characters or fewer"
                        ),
                    }), 422
                goal = cleaned

        from services.voice_confidence import normalize_sex
        sex_present = "sex" in body
        raw_sex = body.get("sex")
        sex: str | None = None
        if raw_sex is not None:
            sex = normalize_sex(raw_sex)
            if sex is None:
                return jsonify({
                    "code": "INVALID_INPUT",
                    "error": (
                        "sex: must be one of female, male, prefer_not_to_say"
                    ),
                }), 422

        # {domain, goal} is a full set; only write it when the body actually
        # carries one of them, otherwise a sex-only post would null the intake.
        if "domain" in body or "goal" in body:
            if not db.set_user_profile(
                request.user_id, domain=domain, goal=goal,
            ):
                return jsonify({
                    "code": "V2_ERROR", "error": "Failed to persist profile",
                }), 500
        else:
            stored = db.get_user_profile(request.user_id) or {}
            domain, goal = stored.get("domain"), stored.get("goal")

        if sex_present:
            if not db.set_user_speaker_sex(request.user_id, sex):
                return jsonify({
                    "code": "V2_ERROR", "error": "Failed to persist profile",
                }), 500
        else:
            sex = db.get_user_speaker_sex(request.user_id)

        # The VALUE of sex is deliberately not logged — it buys nothing
        # operationally and it is the one field here nobody needs in a log.
        logger.info(
            "user/profile.set user=%s domain=%s goal_len=%d sex_set=%s",
            request.user_id, domain or "-", len(goal or ""), sex_present,
        )
        return jsonify({
            "domain": domain,
            "goal": goal,
            "sex": sex,
            "domain_vocabulary_default": default_domain_vocabulary(domain),
        }), 200

    except Exception as e:
        logger.error(
            "user/profile POST failed: %s", e, exc_info=True,
        )
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR",
            "error": "Failed to save profile",
        }), 500


@v2_bp.route("/user/recording-progress", methods=["GET"])
@require_auth
def v2_user_recording_progress():
    """willab recording progress toward the first audit (UX Wave 3 C-2 / S2).

    GET → {recorded_seconds:int, threshold_seconds:int, unlocked:bool}.
    recorded_seconds = the SERVER's cumulative sum of the user's Lab recording
    durations (the FE renders bar = recorded/threshold and NEVER sums snippet
    durations — those are selected windows, not total recorded time).
    """
    from services.user_audit import AUDIT_UNLOCK_SECONDS
    try:
        recorded = int(db.v2_get_cumulative_recorded_seconds(str(request.user_id)) or 0)
        return jsonify({
            "recorded_seconds": recorded,
            "threshold_seconds": AUDIT_UNLOCK_SECONDS,
            "unlocked": recorded >= AUDIT_UNLOCK_SECONDS,
        }), 200
    except Exception as e:
        logger.error("user/recording-progress GET failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to fetch progress"}), 500


@v2_bp.route("/user/last-setup", methods=["GET"])
@require_auth
def v2_user_last_setup():
    """willab "do the same as last time" — the user's most-recent training
    set-up, prefillable into the set-up form. Read-only; cross-device (sources
    the last session's intake_context server-side, not localStorage).

    Returns the prefillable subset (NOT slide_advances — the tap timeline is
    per-recording, the new run generates its own):
      200 { available: true, topic, audience, target_length_seconds,
            domain_vocabulary, slides, presentation_ref }
      200 { available: false }   — no prior session
    """
    try:
        sessions = db.v2_list_user_lab_sessions(str(request.user_id), limit=1) or []
        if not sessions:
            return jsonify({"available": False}), 200
        ctx = sessions[0].get("intake_context")
        ctx = ctx if isinstance(ctx, dict) else {}
        return jsonify({
            "available": True,
            "topic": ctx.get("topic"),
            "audience": ctx.get("audience"),
            "target_length_seconds": ctx.get("target_length_seconds"),
            "domain_vocabulary": ctx.get("domain_vocabulary") or [],
            "slides": ctx.get("slides") or [],
            "presentation_ref": ctx.get("presentation_ref"),
        }), 200
    except Exception as e:
        logger.error("user/last-setup GET failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to fetch last setup"}), 500


@v2_bp.route("/user/audits", methods=["GET"])
@require_auth
def v2_user_get_audits():
    """willab Audit Delivery (Prompt C §3 C2) — the signed-in user's audits,
    newest first, each with a short-lived signed PDF URL. Empty list when none
    (NEVER 404).

    200 { audits: [ { id, name, date, pdf_url } ] }
    """
    try:
        from services.coach_video_storage import (
            coach_media_public_url, presigned_get_coach_object,
        )
        rows = db.list_user_audits(request.user_id) or []
        audits = []
        for r in rows:
            key = r.get("storage_path") or ""
            url = coach_media_public_url(key) if key else None
            if not url and key:
                url = presigned_get_coach_object(
                    "coach_feedback_videos", key, expires_in=604800,
                )
            audits.append({
                "id": r.get("id"),
                "name": r.get("name"),
                "date": r.get("audit_date"),
                "pdf_url": url,
            })
        return jsonify({"audits": audits}), 200
    except Exception as e:
        logger.error("user/audits GET failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to load audits"}), 500


@v2_bp.route("/user/game-sessions", methods=["GET"])
@require_auth
def v2_user_game_sessions():
    """The Game tab's archive — saved practice sessions by date, newest
    first (Engine 5 / backlog 3.3). 200 { sessions: [{arc_id, saved_date,
    created_at}] } · 500"""
    try:
        return jsonify({
            "sessions": db.list_game_saves(str(request.user_id)),
        }), 200
    except Exception as e:
        logger.error("user game-sessions failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to list"}), 500
