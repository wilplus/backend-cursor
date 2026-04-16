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
    # Staging only: if Resend send fails, still run v2_mark_tutor_feedback_sent so the student can open homework (no real email).
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
    
    # Frontend URL (for email links)
    FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")

    # Optional: shared secret for POST /v2/internal/student-credits/increment (Stripe webhook / BFF).
    INTERNAL_CREDITS_WEBHOOK_SECRET = (os.getenv("INTERNAL_CREDITS_WEBHOOK_SECRET") or "").strip()

    # Stripe Checkout → credits (POST /v2/internal/stripe/webhook). Webhook signing secret from Stripe Dashboard.
    STRIPE_WEBHOOK_SECRET = (os.getenv("STRIPE_WEBHOOK_SECRET") or "").strip()
    # Secret key used to expand/verify Checkout Session line items in the webhook handler.
    STRIPE_SECRET_KEY = (os.getenv("STRIPE_SECRET_KEY") or "").strip()
    # JSON object: Stripe Price id → integer credits to add, e.g. {"price_abc":15,"price_def":40}
    STRIPE_CHECKOUT_PRICE_CREDITS_JSON = (os.getenv("STRIPE_CHECKOUT_PRICE_CREDITS_JSON") or "").strip()

    # Optional: annotation event export (cron / internal). See POST /v2/internal/annotation-export
    ANNOTATION_EXPORT_CRON_SECRET = (os.getenv("ANNOTATION_EXPORT_CRON_SECRET") or "").strip()
    ANNOTATION_EXPORT_BUCKET = (os.getenv("ANNOTATION_EXPORT_BUCKET") or "").strip() or None
    ANNOTATION_EXPORT_PREFIX = (os.getenv("ANNOTATION_EXPORT_PREFIX") or "annotation-events").strip() or "annotation-events"
    ANNOTATION_EXPORT_OUTPUT_DIR = (os.getenv("ANNOTATION_EXPORT_OUTPUT_DIR") or "").strip() or None
    STRESS_BASELINE_MODEL_PATH = (os.getenv("STRESS_BASELINE_MODEL_PATH") or "").strip() or None
    STRESS_MODEL_TRAIN_SECRET = (os.getenv("STRESS_MODEL_TRAIN_SECRET") or "").strip()
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

    # Reference video → Whisper: for .mov/.avi/.mkv, extract audio via ffmpeg (must be on PATH or FFMPEG_PATH).
    FFMPEG_PATH = (os.getenv("FFMPEG_PATH") or "ffmpeg").strip() or "ffmpeg"
    REFERENCE_VIDEO_FFMPEG_EXTRACT = (os.getenv("REFERENCE_VIDEO_FFMPEG_EXTRACT", "true").strip().lower() == "true")
    # Cap extracted audio length for Whisper (API max ~25MB); first N seconds only if longer.
    REFERENCE_VIDEO_WHISPER_MAX_AUDIO_SECONDS = int(os.getenv("REFERENCE_VIDEO_WHISPER_MAX_AUDIO_SECONDS", "3600"))

    @property
    def is_production(self):
        return self.ENV == "production"
