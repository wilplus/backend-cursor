from flask import Blueprint, request, jsonify
from supabase import create_client
from config import Config
import logging
import sentry_sdk
import services.db as db_module

logger = logging.getLogger(__name__)

auth_bp = Blueprint("auth", __name__)
config = Config()

# The version string must match the "Last updated" date in the published
# Terms of Service / Privacy Policy. Bump this when documents change so
# returning users are asked to re-accept the updated terms.
CURRENT_TERMS_VERSION = "1.0"


@auth_bp.route("/signup", methods=["POST"])
def signup():
    """Register a new user.

    Required body fields:
        email          (str)  — user's email address
        password       (str)  — min 6 characters
        terms_accepted (bool) — MUST be true; user has read and accepted the
                                Terms of Service and Privacy Policy

    Optional body fields:
        name           (str)  — display name stored in Supabase user_metadata
        sex            (str)  — "female" | "male" | "prefer_not_to_say".
                                Routes the cue weights of the voice-confidence
                                composite, where pitch variability reverses
                                direction by speaker sex
                                (services/voice_confidence.py). OPTIONAL on
                                purpose: omitted simply means "not answered",
                                and the composite then falls back to sex-blind
                                weights. Also settable later via
                                POST /v2/user/profile.

    On success (201):
        { user: { id, email }, access_token, refresh_token, expires_in,
          terms_recorded: bool }

    On validation failure (400):
        { code: "TERMS_NOT_ACCEPTED" | "INVALID_INPUT", error: str }
    """
    try:
        # ── 0. Payload shape ─────────────────────────────────────────────
        # Reject anything that isn't a JSON object up front so a malformed
        # body (string, list, null, non-JSON content-type) yields a 400
        # with a specific code instead of crashing the field extraction
        # below and bubbling out as a generic 500.
        body = request.get_json(silent=True)
        if not isinstance(body, dict):
            return jsonify({
                "code": "INVALID_PAYLOAD",
                "error": "Request body must be a JSON object.",
            }), 400

        email_raw = body.get("email")
        password_raw = body.get("password")
        name_raw = body.get("name", "")
        terms_accepted = body.get("terms_accepted")

        # Type guards on the stringly-typed fields. Without these, a client
        # sending `password: 123` would AttributeError on `.strip()` later
        # and surface as a 500 SIGNUP_ERROR.
        if not isinstance(email_raw, str) or not isinstance(password_raw, str):
            return jsonify({
                "code": "INVALID_PAYLOAD",
                "error": "email and password must be strings.",
            }), 400
        if name_raw is not None and not isinstance(name_raw, str):
            return jsonify({
                "code": "INVALID_PAYLOAD",
                "error": "name must be a string when provided.",
            }), 400

        email = email_raw.strip()
        password = password_raw
        name = (name_raw or "").strip()

        # ── 1. Input validation ──────────────────────────────────────────
        if not email or not password:
            return jsonify({
                "code": "INVALID_INPUT",
                "error": "Email and password are required.",
            }), 400

        if len(password) < 6:
            return jsonify({
                "code": "INVALID_INPUT",
                "error": "Password must be at least 6 characters.",
            }), 400

        # ── 2. Consent gate — MUST be true before user is created ────────
        # Strict identity check (`is not True`) so truthy-but-not-true
        # values like 1 or "true" don't slip through. The frontend always
        # sends a real boolean.
        if terms_accepted is not True:
            return jsonify({
                "code": "TERMS_NOT_ACCEPTED",
                "error": (
                    "You must accept the Terms of Service and Privacy Policy "
                    "to create an account."
                ),
            }), 400

        # Speaker sex — validated HERE: after the consent gate, so that gate
        # keeps its precedence, but before create_user, so a typo is a clean
        # 400 rather than an orphaned Supabase account plus an error.
        from services.voice_confidence import normalize_sex
        raw_sex = body.get("sex")
        sex = None
        if raw_sex is not None:
            sex = normalize_sex(raw_sex)
            if sex is None:
                return jsonify({
                    "code": "INVALID_INPUT",
                    "error": (
                        "sex must be one of female, male, prefer_not_to_say."
                    ),
                }), 400

        # ── 3. Create Supabase user ───────────────────────────────────────
        supabase = create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_ROLE_KEY)

        user_metadata: dict = {}
        if name:
            user_metadata["name"] = name
            user_metadata["display_name"] = name
        # Record the terms version in Supabase user_metadata as a fast
        # secondary reference (the authoritative record is user_consents).
        user_metadata["terms_version"] = CURRENT_TERMS_VERSION

        create_resp = supabase.auth.admin.create_user({
            "email": email,
            "password": password,
            "email_confirm": True,
            "user_metadata": user_metadata,
        })

        if not create_resp.user:
            return jsonify({
                "code": "SIGNUP_FAILED",
                "error": "Failed to create user account.",
            }), 400

        user_id = create_resp.user.id

        # ── 4. Record consent in user_consents table ──────────────────────
        # Capture request context for the GDPR compliance audit trail.
        ip_address = (
            request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
            or request.remote_addr
        )
        user_agent = request.headers.get("User-Agent", "")[:512]  # cap length

        db = db_module.db
        consent_row = db.record_user_consent(
            user_id=user_id,
            terms_version=CURRENT_TERMS_VERSION,
            ip_address=ip_address or None,
            user_agent=user_agent or None,
        )
        terms_recorded = consent_row is not None

        # ── 4b. Speaker sex (optional) ────────────────────────────────────
        # BEST-EFFORT, and deliberately not part of the response contract.
        # The account already exists at this point; failing the signup over a
        # weight-routing hint would be absurd, and the user can set it later
        # via POST /v2/user/profile. Silence here costs the composite nothing
        # more than sex-blind weights.
        if sex:
            try:
                db.set_user_speaker_sex(user_id, sex)
            except Exception as sex_err:
                logger.warning(
                    "signup: speaker-sex persist failed user=%s: %s "
                    "(non-fatal)", user_id, sex_err,
                )

        # ── 5. Sign in to get session tokens for the new user ────────────
        # The frontend will call supabase.auth.setSession() with these tokens
        # so the browser client is immediately authenticated without a second
        # round-trip to Supabase.
        session_resp = supabase.auth.sign_in_with_password({
            "email": email,
            "password": password,
        })

        if not session_resp.session:
            # User was created successfully — return 201 without tokens.
            # The frontend can fall back to signing in separately.
            return jsonify({
                "user": {"id": user_id, "email": email},
                "terms_recorded": terms_recorded,
            }), 201

        return jsonify({
            "user": {
                "id": session_resp.user.id,
                "email": session_resp.user.email,
            },
            "access_token": session_resp.session.access_token,
            "refresh_token": session_resp.session.refresh_token,
            "expires_in": session_resp.session.expires_in,
            "terms_recorded": terms_recorded,
        }), 201

    except Exception as e:
        sentry_sdk.capture_exception(e)
        # Surface duplicate-email errors clearly.
        msg = str(e)
        if "already registered" in msg.lower() or "already been registered" in msg.lower():
            return jsonify({
                "code": "EMAIL_IN_USE",
                "error": "An account with this email already exists.",
            }), 409
        return jsonify({"code": "SIGNUP_ERROR", "error": "Registration failed. Please try again."}), 500

@auth_bp.route("/login", methods=["POST"])
def login():
    """Login user via Supabase password grant"""
    try:
        data = request.get_json()
        email = data.get("email")
        password = data.get("password")
        
        if not email or not password:
            return jsonify({"code": "INVALID_INPUT", "error": "Email and password required"}), 400
        
        # Use Supabase client for password grant
        supabase = create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_ROLE_KEY)
        
        # Sign in
        response = supabase.auth.sign_in_with_password({
            "email": email,
            "password": password
        })
        
        if not response.session:
            return jsonify({"code": "LOGIN_FAILED", "error": "Invalid credentials"}), 401
        
        # Return Supabase session tokens
        return jsonify({
            "access_token": response.session.access_token,
            "refresh_token": response.session.refresh_token,
            "expires_in": response.session.expires_in,
            "user": {
                "id": response.user.id,
                "email": response.user.email
            }
        }), 200
        
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "LOGIN_ERROR", "error": str(e)}), 500

@auth_bp.route("/reset-password", methods=["POST"])
def reset_password():
    """Trigger password reset email via Supabase"""
    try:
        data = request.get_json()
        email = data.get("email")
        
        if not email:
            return jsonify({"code": "INVALID_INPUT", "error": "Email required"}), 400
        
        supabase = create_client(config.SUPABASE_URL, config.SUPABASE_SERVICE_ROLE_KEY)
        
        # Send reset email
        supabase.auth.reset_password_for_email(email)
        
        return jsonify({"message": "Password reset email sent"}), 200
        
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "RESET_ERROR", "error": str(e)}), 500
