import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    ENV = os.getenv("ENV", "development")
    # When true, coach receives email at ADMIN_EMAIL when a student completes homework; assignment emails are sent. Set SEND_EMAILS=true to receive reports.
    SEND_EMAILS = os.getenv("SEND_EMAILS", "false").lower() == "true"

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
    
    # CORS
    CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:3000").split(",")
    
    # Audio limits
    MAX_AUDIO_SIZE_MB = 25
    MAX_RECORDING_DURATION_SECONDS = 300
    
    # Storage
    AUDIO_BUCKET_NAME = "audio_recordings"
    SIGNED_URL_EXPIRY_SECONDS = 3600
    
    # Frontend URL (for email links)
    FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")

    # Coach name and photo in assignment email (for artur@willonski.com / default admin)
    COACH_NAME = os.getenv("COACH_NAME", "Artur")
    COACH_IMAGE_URL = (os.getenv("COACH_IMAGE_URL") or "").strip() or None  # Optional; if set, used as coach avatar in email.
    BACKEND_URL = (os.getenv("BACKEND_URL") or "").strip() or None  # Optional; if set and COACH_IMAGE_URL not set, email uses BACKEND_URL/static/coach-avatar.png as coach avatar.

    # Tutor feedback window: time the tutor has to send feedback and assign new homework after a lesson is completed (hours)
    TUTOR_FEEDBACK_WINDOW_HOURS = float(os.getenv("TUTOR_FEEDBACK_WINDOW_HOURS", "24"))

    # Step 0 intro exercise: when the "0-intro" exercise has no video_url/description in the DB, use these.
    # Default intro video for first-time / newly registered users. Override with INTRO_0_VIDEO_URL in .env if needed.
    INTRO_0_VIDEO_URL = (os.getenv("INTRO_0_VIDEO_URL") or "").strip() or "https://vimeo.com/1167696503?fl=ip&fe=ec"
    INTRO_0_DESCRIPTION = (os.getenv("INTRO_0_DESCRIPTION") or "").strip() or None
    
    @property
    def is_production(self):
        return self.ENV == "production"
