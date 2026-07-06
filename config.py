import os
from urllib.parse import urlparse

from dotenv import load_dotenv

load_dotenv()


def _merge_cors_origins() -> list:
    """Comma-separated CORS_ORIGINS plus FRONTEND_URL origin (so admin browsers can poll the API when only FRONTEND_URL is set)."""
    raw = os.getenv("CORS_ORIGINS", "http://localhost:3000")
    origins = [o.strip().rstrip("/") for o in raw.split(",") if o.strip()]
    fe = (os.getenv("FRONTEND_URL") or "").strip()
    if fe:
        try:
            p = urlparse(fe)
            if p.scheme and p.netloc:
                origin = f"{p.scheme}://{p.netloc}".rstrip("/")
                if origin not in origins:
                    origins.append(origin)
        except Exception:
            pass
    return origins or ["http://localhost:3000"]


class Config:
    ENV = os.getenv("ENV", "development")
    # When true, coach receives email at ADMIN_EMAIL when a student completes homework; assignment emails are sent. Set SEND_EMAILS=true to receive reports.
    SEND_EMAILS = os.getenv("SEND_EMAILS", "false").lower() == "true"
    # Deprecated: homework delivery always unlocks after the email attempt (see _deliver_homework_assignment_core).
    HOMEWORK_UNLOCK_WHEN_EMAIL_FAILS = os.getenv("HOMEWORK_UNLOCK_WHEN_EMAIL_FAILS", "false").lower() == "true"

    # Supabase
    SUPABASE_URL = os.getenv("SUPABASE_URL")
    SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    SUPABASE_JWT_SECRET = os.getenv("SUPABASE_JWT_SECRET")
    
    # OpenAI (strip so .env newlines/quotes don't break the key)
    OPENAI_API_KEY = (os.getenv("OPENAI_API_KEY") or "").strip().strip('"').strip("'")
    
    # Email (Resend)
    RESEND_API_KEY = os.getenv("RESEND_API_KEY")
    RESEND_FROM_EMAIL = os.getenv("RESEND_FROM_EMAIL")
    ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "artur@willonski.com")

    # Current published Terms / Privacy Policy version. Must match the
    # "Last updated" date in the live legal docs (e.g. "1.0" = Terms
    # dated 7 May 2026; bump when docs are materially revised). The
    # /v2/user/consent endpoint reads this to decide whether the user
    # is "behind" on terms acceptance (terms_consent=false means the
    # frontend prompts a re-accept). Hardcoded default mirrors the
    # migration's user_consents.terms_version default; override via
    # env once docs change so behavior shifts without a redeploy.
    CURRENT_TERMS_VERSION = os.getenv("CURRENT_TERMS_VERSION", "1.0")

    # Sentry
    SENTRY_DSN = os.getenv("SENTRY_DSN")
    
    # CORS (browser admin UI → backend; include production app origin or set CORS_ORIGINS explicitly)
    CORS_ORIGINS = _merge_cors_origins()
    
    # Audio limits
    MAX_AUDIO_SIZE_MB = 25
    MAX_RECORDING_DURATION_SECONDS = 300
    # Admin reference video upload limit (Training Studio)
    MAX_REFERENCE_VIDEO_SIZE_MB = int(os.getenv("MAX_REFERENCE_VIDEO_SIZE_MB", "500"))
    
    # Storage
    AUDIO_BUCKET_NAME = "audio_recordings"
    SIGNED_URL_EXPIRY_SECONDS = 3600
    COACH_FEEDBACK_VIDEO_BUCKET = (os.getenv("COACH_FEEDBACK_VIDEO_BUCKET") or "coach_feedback_videos").strip() or "coach_feedback_videos"
    # Cloudflare R2 (S3 API) for coach/reference/feedback videos — set all four to use R2 instead of Supabase Storage.
    R2_ACCOUNT_ID = (os.getenv("R2_ACCOUNT_ID") or "").strip()
    R2_ACCESS_KEY_ID = (os.getenv("R2_ACCESS_KEY_ID") or "").strip()
    R2_SECRET_ACCESS_KEY = (os.getenv("R2_SECRET_ACCESS_KEY") or "").strip()
    # Optional; defaults to COACH_FEEDBACK_VIDEO_BUCKET (e.g. coach-feedback-videos).
    R2_BUCKET_NAME = (os.getenv("R2_BUCKET_NAME") or "").strip()
    # Optional public or custom domain base for stable <video src> URLs, no trailing slash (e.g. https://videos.example.com).
    R2_PUBLIC_BASE_URL = (os.getenv("R2_PUBLIC_BASE_URL") or "").strip()

    # ── Cloudflare R2 — USER MEDIA UPLOADS (audio + video) ─────────────────
    # Separate bucket from coach videos / interview audio because the
    # access policy + retention differ: user-uploaded media is owned
    # by the user, surfaced in the admin Files tab, and lifecycled
    # per-user. The same R2 credentials above are reused.
    # When unset, services.user_media_storage falls back to the
    # coach video bucket so dev environments still function.
    R2_USER_MEDIA_BUCKET = (
        os.getenv("R2_USER_MEDIA_BUCKET")
        or os.getenv("VIDEO_FILES_REPOSITORY")
        or ""
    ).strip()
    R2_USER_MEDIA_PUBLIC_BASE_URL = (
        os.getenv("R2_USER_MEDIA_PUBLIC_BASE_URL") or ""
    ).strip()

    # File size cap for the user-facing /v2/user/upload-media endpoint.
    # Higher than MAX_AUDIO_SIZE_MB (25) because video is the primary
    # use case here. 200 MB matches the in-browser MediaRecorder ceiling
    # most clients hit before we'd want a chunked-upload strategy.
    MAX_USER_MEDIA_SIZE_MB = int(
        os.getenv("MAX_USER_MEDIA_SIZE_MB", "200")
    )

    # ── Cloudflare R2 — USER INTERVIEW AUDIO ─────────────────────────────────
    # Deliberately a separate bucket from coach feedback videos because the
    # content type, lifecycle, and access policy differ:
    #   - coach_feedback_videos: long-lived public videos created by coaches
    #   - user-interview-audio:  short-lived per-user audio + concat'd session
    #                            recordings, possibly under stricter retention
    # Set both R2_AUDIO_BUCKET_NAME and R2_AUDIO_PUBLIC_BASE_URL to enable R2
    # for audio. The same R2_ACCOUNT_ID / R2_ACCESS_KEY_ID / R2_SECRET_ACCESS_KEY
    # are reused — no new credentials needed, just a different bucket on the
    # same R2 account.
    # When unset (dev / non-R2 environments), services.audio_storage falls
    # back to Supabase Storage at AUDIO_BUCKET_NAME ("audio_recordings"),
    # matching the codebase's pre-migration default.
    R2_AUDIO_BUCKET_NAME = (os.getenv("R2_AUDIO_BUCKET_NAME") or "").strip()
    R2_AUDIO_PUBLIC_BASE_URL = (os.getenv("R2_AUDIO_PUBLIC_BASE_URL") or "").strip()

    # ── Phase 1: tenant-scoped few-shot pool ─────────────────────────────
    # When TRUE, services.db.get_top_followup_examples scopes exemplars
    # to the viewer's company (joined via user_settings.company_id) plus
    # any 'canonical' rows admins have explicitly promoted. When FALSE
    # (default), behaviour matches the pre-Phase-1 cross-tenant retrieval
    # so the flag flip is the only thing the rollout depends on.
    # Flip to TRUE only after:
    #   1. The companies / sharing_scope migration has run.
    #   2. The discovery SQL (in the Phase 1 plan) returns at least one
    #      candidate tenant with ≥3 active users + ≥50 commented snippets.
    #   3. Pool-depth backtest confirms the candidate tenant gets a
    #      non-empty few-shot block on most retrievals.
    FEW_SHOT_TENANT_SCOPED = (
        (os.getenv("FEW_SHOT_TENANT_SCOPED") or "").strip().lower()
        in ("1", "true", "yes", "on")
    )

    # ── Phase 2: 1:N coaching attempts history ───────────────────────────
    # When TRUE (default), every outcome write also lands in the legacy
    # charisma_snippets.follow_up_outcome JSONB so admin views and the
    # backfill script still see the latest attempt. Flip to FALSE only
    # after the migration is fully cut over and consumers exclusively
    # read from coaching_attempts. Two consumers known today:
    #   - the admin snippet card outcome strip (reads follow_up_outcome)
    #   - get_top_followup_examples (reads coaching_attempts already)
    # Until the admin strip is re-pointed, leaving dual-write on is the
    # safer default.
    COACHING_ATTEMPTS_DUAL_WRITE = (
        (os.getenv("COACHING_ATTEMPTS_DUAL_WRITE") or "true").strip().lower()
        in ("1", "true", "yes", "on")
    )

    # ── Phase 3: inferred learner profile injection ──────────────────────
    # When TRUE, _augment_coaching_system_prompt appends a [LEARNER
    # INSIGHTS] block derived from the user's last 10 coaching_attempts
    # (weakest dimension, score trend, self-rating gap, etc.) on top of
    # the existing custom_llm_instructions + behavioral_profile block.
    # The block is also gated by services.learner_profile.MIN_ATTEMPTS_
    # TO_INJECT — a user with <3 attempts gets no insights regardless of
    # the flag, because trait estimates are too noisy.
    #
    # Default OFF: the recompute runs (so admins can read the JSONB
    # via the diagnostic endpoint) but the prompt augmentation is
    # silent until we flip this on after backtesting the injection.
    LEARNER_PROFILE_INJECTION_ENABLED = (
        (os.getenv("LEARNER_PROFILE_INJECTION_ENABLED") or "").strip().lower()
        in ("1", "true", "yes", "on")
    )

    # ── Phase 15: longitudinal first-question generation ────────────────
    # When TRUE, the contextual_init branch of _generate_llm_question
    # enriches its system prompt with:
    #   - the user's last 3 coaching_attempts on THIS snippet (so the
    #     LLM can avoid repeating prior angles and acknowledge progress)
    #   - the user's inferred_learner_profile (learner type + recurring
    #     themes) for tone shaping
    #   - the user's current learner_mirror narrative (continuity across
    #     the system as a whole)
    # And bumps temperature 0.7 → 0.85 so even identical inputs vary.
    # Default ON — the contextual chat ("infinite flywheel") relies on
    # the longitudinal block to make Session 2+ feel like the system
    # remembers the user. Set LONGITUDINAL_FIRST_QUESTION_ENABLED=false
    # in env to opt back out (kill switch preserved for incident
    # response).
    LONGITUDINAL_FIRST_QUESTION_ENABLED = (
        (os.getenv("LONGITUDINAL_FIRST_QUESTION_ENABLED") or "true")
        .strip().lower() in ("1", "true", "yes", "on")
    )

    # ── Phase 16: pre-baked baseline summary ────────────────────────────
    # When TRUE, the first time a user reaches turn 5 of the EBCP run we
    # fire a dedicated LLM call that digests turns 1-4 into a structured
    # baseline_summary (headline, themes, aspirational_archetype, tension,
    # coaching_handle) on user_settings. Every subsequent question
    # generator for this user (interview turn 5+, contextual /chat
    # first-question) reads that summary INSTEAD of having to re-derive
    # who-this-user-is from raw transcripts on every call — which is
    # where shallow openers leak in.
    # Default ON — same rationale as LONGITUDINAL_FIRST_QUESTION_ENABLED:
    # the baseline digest is the single source-of-truth for who-the-
    # user-is by the time Session 2+ kicks in. Set
    # BASELINE_SUMMARY_ENABLED=false in env to opt back out.
    BASELINE_SUMMARY_ENABLED = (
        (os.getenv("BASELINE_SUMMARY_ENABLED") or "true")
        .strip().lower() in ("1", "true", "yes", "on")
    )

    # ── Phase 6: on-demand learner mirror ────────────────────────────────
    # When TRUE the user-facing mirror endpoints (GET /v2/user/mirror,
    # POST /v2/user/mirror/generate) accept requests and the generate
    # path makes an LLM call. When FALSE both endpoints respond with
    # FEATURE_DISABLED so the frontend can show a "coming soon" state
    # without breaking. Default OFF: the LLM cost is per user click,
    # so we gate it until the UX is ready end-to-end.
    LEARNER_MIRROR_ENABLED = (
        (os.getenv("LEARNER_MIRROR_ENABLED") or "").strip().lower()
        in ("1", "true", "yes", "on")
    )
    
    # Frontend URL (for email links)
    FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")

    # ── Phase 14: PostSessionResultsEmail rollout ────────────────────────
    # PUBLIC_FRONTEND_URL  — base for user-facing links baked into emails
    #                        (e.g. /unsubscribe?token=...). Falls back to
    #                        FRONTEND_URL so a single env var still works
    #                        in dev / preview deploys.
    # FRONTEND_BASE_URL    — base for server-to-server calls into the
    #                        Next.js render endpoint
    #                        (/api/internal/emails/post-session-results).
    #                        Same value as PUBLIC_FRONTEND_URL in prod;
    #                        kept distinct so private-network deploys
    #                        can point the server-to-server hop at an
    #                        internal hostname.
    # EMAIL_RENDER_SECRET  — shared secret the frontend's render
    #                        endpoint checks. Backend sends it in the
    #                        x-internal-secret header.
    # UNSUBSCRIBE_TOKEN_SECRET — dedicated HS256 signing key for the
    #                        unsubscribe JWTs. Distinct from the auth
    #                        JWT secret so a leak here doesn't burn
    #                        session credentials.
    PUBLIC_FRONTEND_URL = (
        os.getenv("PUBLIC_FRONTEND_URL") or FRONTEND_URL
    ).rstrip("/")
    FRONTEND_BASE_URL = (
        os.getenv("FRONTEND_BASE_URL") or PUBLIC_FRONTEND_URL
    ).rstrip("/")
    EMAIL_RENDER_SECRET = (os.getenv("EMAIL_RENDER_SECRET") or "").strip()
    UNSUBSCRIBE_TOKEN_SECRET = (os.getenv("UNSUBSCRIBE_TOKEN_SECRET") or "").strip()

    # Optional: shared secret for POST /v2/internal/student-credits/increment (Stripe webhook / BFF).
    INTERNAL_CREDITS_WEBHOOK_SECRET = (os.getenv("INTERNAL_CREDITS_WEBHOOK_SECRET") or "").strip()

    # Stripe Checkout → credits (POST /v2/internal/stripe/webhook). Webhook signing secret from Stripe Dashboard.
    STRIPE_WEBHOOK_SECRET = (os.getenv("STRIPE_WEBHOOK_SECRET") or "").strip()
    # Secret key used to expand/verify Checkout Session line items in the webhook handler.
    STRIPE_SECRET_KEY = (os.getenv("STRIPE_SECRET_KEY") or "").strip()
    # JSON object: Stripe Price id → integer credits to add, e.g. {"price_abc":15,"price_def":40}
    STRIPE_CHECKOUT_PRICE_CREDITS_JSON = (os.getenv("STRIPE_CHECKOUT_PRICE_CREDITS_JSON") or "").strip()

    # ── willab — Paid Audits. An "audit" = an explore arc (3 takes + the
    # coach-corrected ideal text). Re-priced 2026-07-06: $25, spent as
    # ARC_UNLOCK_CREDITS from the existing credits balance (NOT a second
    # Stripe SKU — see POST /v2/arc/<arc_id>/unlock). AUDIT_PRICE_AMOUNT_MINOR/
    # CURRENCY are kept ONLY as the display-price the credits are worth + to
    # honor legacy $50 Stripe-direct grandfathered arcs (services/arc_checkout.py
    # — dormant, no longer advertised for new purchases).
    AUDIT_PRICE_CURRENCY = (os.getenv("AUDIT_PRICE_CURRENCY") or "usd").strip().lower() or "usd"
    AUDIT_PRICE_AMOUNT_MINOR = int(os.getenv("AUDIT_PRICE_AMOUNT_MINOR") or "2500")
    # Stripe Price id for the LEGACY audit checkout (mode=payment). Dormant.
    STRIPE_AUDIT_PRICE_ID = (os.getenv("STRIPE_AUDIT_PRICE_ID") or "").strip()
    # Delivery SLA surfaced in the 402 / paywall copy (hours).
    AUDIT_SLA_HOURS = int(os.getenv("AUDIT_SLA_HOURS") or "48")
    # Checkout redirect targets (legacy FE pages). Dormant alongside the above.
    AUDIT_CHECKOUT_SUCCESS_URL = (os.getenv("AUDIT_CHECKOUT_SUCCESS_URL") or "").strip() or None
    AUDIT_CHECKOUT_CANCEL_URL = (os.getenv("AUDIT_CHECKOUT_CANCEL_URL") or "").strip() or None
    # THE live price (2026-07-06): credits spent by POST /v2/arc/<arc_id>/unlock.
    # 1 credit = $1 (this model's founding peg — no Stripe pack pricing was
    # configured in env before this, so there is no prior peg to violate).
    # OPERATIONAL: at least one Stripe credit pack (STRIPE_CHECKOUT_PRICE_
    # CREDITS_JSON) must map a Price id to >=25 credits before this ships live.
    ARC_UNLOCK_CREDITS = int(os.getenv("ARC_UNLOCK_CREDITS") or "25")

    # Optional: annotation event export (cron / internal). See POST /v2/internal/annotation-export
    ANNOTATION_EXPORT_CRON_SECRET = (os.getenv("ANNOTATION_EXPORT_CRON_SECRET") or "").strip()
    ANNOTATION_EXPORT_BUCKET = (os.getenv("ANNOTATION_EXPORT_BUCKET") or "").strip() or None
    ANNOTATION_EXPORT_PREFIX = (os.getenv("ANNOTATION_EXPORT_PREFIX") or "annotation-events").strip() or "annotation-events"
    ANNOTATION_EXPORT_OUTPUT_DIR = (os.getenv("ANNOTATION_EXPORT_OUTPUT_DIR") or "").strip() or None
    STRESS_BASELINE_MODEL_PATH = (os.getenv("STRESS_BASELINE_MODEL_PATH") or "").strip() or None
    STRESS_MODEL_TRAIN_SECRET = (os.getenv("STRESS_MODEL_TRAIN_SECRET") or "").strip()
    # Graduated-autonomy floor for the shadow DIRECTION fallback (readiness rig
    # #3). 0.0 (default) = OFF: the shadow label is used whenever present, as
    # before. >0 = use the shadow fallback ONLY when its confidence >= this
    # floor; low-confidence snippets route to the human (no machine direction
    # term). Flip on (e.g. 0.8) only once the holdout agreement says it's ready.
    DIRECTION_SHADOW_MIN_CONFIDENCE = float(os.getenv("DIRECTION_SHADOW_MIN_CONFIDENCE") or "0")
    # Supabase Storage bucket for trained stress baseline JSON (see migrations/add_stress_models_storage_bucket.sql).
    STRESS_MODEL_BUCKET = (os.getenv("STRESS_MODEL_BUCKET") or "stress_models").strip() or "stress_models"

    # Coach name and photo in assignment email (for artur@willonski.com / default admin)
    COACH_NAME = os.getenv("COACH_NAME", "Artur")
    COACH_IMAGE_URL = (os.getenv("COACH_IMAGE_URL") or "").strip() or None  # Optional; if set, used as coach avatar in email.
    BACKEND_URL = (os.getenv("BACKEND_URL") or "").strip() or None  # Optional; if set and COACH_IMAGE_URL not set, email uses BACKEND_URL/static/coach-avatar.png as coach avatar.

    # Tutor feedback window: time the tutor has to send feedback and assign new homework after a lesson is completed (hours)
    TUTOR_FEEDBACK_WINDOW_HOURS = float(os.getenv("TUTOR_FEEDBACK_WINDOW_HOURS", "24"))

    # Agentic video pipeline (admin copilot async generation)
    COPILOT_VIDEO_PIPELINE_ENABLED = (os.getenv("COPILOT_VIDEO_PIPELINE_ENABLED") or "false").strip().lower() == "true"
    COPILOT_VIDEO_PIPELINE_SECRET = (os.getenv("COPILOT_VIDEO_PIPELINE_SECRET") or "").strip()
    COPILOT_VIDEO_RETRAIN_SECRET = (os.getenv("COPILOT_VIDEO_RETRAIN_SECRET") or "").strip()
    COPILOT_VIDEO_RETRAIN_WEBHOOK_URL = (os.getenv("COPILOT_VIDEO_RETRAIN_WEBHOOK_URL") or "").strip() or None

    METAVOICE_API_URL = (os.getenv("METAVOICE_API_URL") or "").strip() or None
    METAVOICE_API_KEY = (os.getenv("METAVOICE_API_KEY") or "").strip() or None
    METAVOICE_VOICE_ID = (os.getenv("METAVOICE_VOICE_ID") or "").strip() or None
    METAVOICE_OUTPUT_FORMAT = (os.getenv("METAVOICE_OUTPUT_FORMAT") or "wav").strip() or "wav"

    BYTEDANCE_API_URL = (os.getenv("BYTEDANCE_API_URL") or "").strip() or None
    BYTEDANCE_API_KEY = (os.getenv("BYTEDANCE_API_KEY") or "").strip() or None
    ARTUR_BASE_AVATAR_URL = (os.getenv("ARTUR_BASE_AVATAR_URL") or "").strip() or None

    # Reference video → Whisper: extract compact mono MP3 via ffmpeg before transcription
    # for video/common containers (and large inputs), to stay under OpenAI ~25MB request limit.
    FFMPEG_PATH = (os.getenv("FFMPEG_PATH") or "ffmpeg").strip() or "ffmpeg"
    REFERENCE_VIDEO_FFMPEG_EXTRACT = (os.getenv("REFERENCE_VIDEO_FFMPEG_EXTRACT", "true").strip().lower() == "true")
    # Cap extracted audio length for Whisper (API max ~25MB); first N seconds only if longer.
    REFERENCE_VIDEO_WHISPER_MAX_AUDIO_SECONDS = int(os.getenv("REFERENCE_VIDEO_WHISPER_MAX_AUDIO_SECONDS", "3600"))

    # Recommendation engine v1 hook: when true, _complete_session_from_recording
    # runs diagnose_session_state() and persists ai_suggested_profile /
    # ai_suggested_task_id on v2_sessions. Failures are logged and swallowed
    # (never abort session completion).
    DIAGNOSE_SESSION_STATE_ENABLED = (os.getenv("DIAGNOSE_SESSION_STATE_ENABLED") or "false").strip().lower() == "true"

    # Curiosity Gate (anonymous-first acquisition funnel). When true, exposes
    # POST /v2/public/shaky-voice/{upload,claim}. Anonymous uploads only store
    # bytes + a v2_sessions row; the paid Whisper / OpenAI pipeline does NOT
    # run until the user signs in and claims the session.
    GUEST_FUNNEL_ENABLED = (os.getenv("GUEST_FUNNEL_ENABLED") or "false").strip().lower() == "true"
    # Per-IP cap (uploads/hour). Cheap insurance against scripted abuse.
    GUEST_FUNNEL_RATE_LIMIT_PER_IP_PER_HOUR = int(os.getenv("GUEST_FUNNEL_RATE_LIMIT_PER_IP_PER_HOUR", "5"))
    # willab Prompt D — the audit is REPLACED by the Best-Presentation. Default
    # OFF retires the audit chat surface (the "audit" suggested_action button);
    # the endpoints/tables stay DORMANT (recoverable — flip ON to restore).
    AUDIT_SURFACE_ENABLED = (os.getenv("AUDIT_SURFACE_ENABLED") or "false").strip().lower() == "true"
    # Global cap across all IPs (uploads/hour). Stops a botnet from saturating.
    GUEST_FUNNEL_RATE_LIMIT_GLOBAL_PER_HOUR = int(os.getenv("GUEST_FUNNEL_RATE_LIMIT_GLOBAL_PER_HOUR", "200"))
    # Hard size cap on the anonymous upload (smaller than admin's 25 MB —
    # the funnel is 15 seconds of speech, not a TED talk).
    GUEST_FUNNEL_MAX_AUDIO_SIZE_MB = int(os.getenv("GUEST_FUNNEL_MAX_AUDIO_SIZE_MB", "5"))
    # TTL for unclaimed guest sessions before the daily cleanup job purges them.
    GUEST_FUNNEL_TTL_HOURS = int(os.getenv("GUEST_FUNNEL_TTL_HOURS", "24"))
    # Max file size for afterwards funnel video upload
    FUNNEL_AFTERWARDS_VIDEO_MAX_MB = int(os.getenv("FUNNEL_AFTERWARDS_VIDEO_MAX_MB", "100"))

    @property
    def is_production(self):
        return self.ENV == "production"
