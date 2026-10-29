import os
from urllib.parse import urlparse

from dotenv import load_dotenv

from services.secrets import resolve as _secret

load_dotenv()

# Secrets go through services.secrets.resolve, which honours the
# `<NAME>_FILE` indirection every managed secret store speaks (Docker
# secrets, Kubernetes projected volumes, Vault Agent, the AWS Secrets
# Manager CSI driver) before falling back to the plain env var. It also
# strips the trailing newline a mounted file or `echo >` leaves behind —
# the classic silent auth failure. Non-secret settings below keep using
# os.getenv directly; the seam lives only where the sensitive values are.
# See services/secrets.py + docs/OPS-SECRETS-AND-STAGING.md.


# The production app origin — CODE-guaranteed in the CORS allow-list
# (2026-07-15): browser-direct calls (big deck uploads past the Vercel BFF
# body cap → POST /v2/lab/presentation/extract) must never depend on a
# Railway env var being set correctly to pass preflight.
_PROD_APP_ORIGIN = "https://www.willpowerlab.com"


def _env_int(name: str, default: int) -> int:
    """Integer env var with a safe fallback: unset, blank, or malformed
    values return the default instead of raising — a bad env value must
    never crash import (live loop)."""
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_flag(name: str, default: str = "0") -> bool:
    """Boolean env var, F1-module convention: blank means ``default``; on is
    exactly one of "1", "true", "yes". Same never-crash contract."""
    return (os.getenv(name) or default).strip().lower() in ("1", "true", "yes")


def _env_not_off(name: str, default: str = "1") -> bool:
    """Default-ON kill switch: anything but an explicit "0", "false", "no"
    or "off" keeps it on (the SENTENCE_BOUNDARY_SPLIT_ENABLED convention)."""
    return (os.getenv(name) or default).strip().lower() not in ("0", "false", "no", "off")


def _env_float(name: str, default: float) -> float:
    """Float env var with a safe fallback — same never-crash contract as
    _env_int (live loop)."""
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _merge_cors_origins() -> list:
    """Comma-separated CORS_ORIGINS plus FRONTEND_URL origin (so admin browsers
    can poll the API when only FRONTEND_URL is set) plus the hard-coded
    production app origin."""
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
    if _PROD_APP_ORIGIN not in origins:
        origins.append(_PROD_APP_ORIGIN)
    return origins or ["http://localhost:3000"]


class Config:
    @staticmethod
    def current_env(names) -> dict[str, str]:
        """The values these variables hold RIGHT NOW, stripped.

        Every attribute on this class resolves once, at import. That is
        correct for configuration and wrong for the CONFIG-FIRST boot
        summary (J1-4), whose whole job is to report what the process has at
        the moment it prints — in a worker, that is long after this module
        was first imported.

        Deliberately narrow: it takes a list of NAMES and returns their
        values, so it cannot become a general escape hatch from the rule
        that `os.environ` is read here and in `services/secrets.py` and
        nowhere else (audit Q-A5, `tests/test_config_reads_fence.py`).
        Its one caller is `services/gate_flags.py`.
        """
        return {name: (os.getenv(name) or "").strip() for name in names}

    ENV = os.getenv("ENV", "development")
    # When true, coach receives email at ADMIN_EMAIL when a student completes homework; assignment emails are sent. Set SEND_EMAILS=true to receive reports.
    SEND_EMAILS = os.getenv("SEND_EMAILS", "false").lower() == "true"

    # Supabase
    SUPABASE_URL = _secret("SUPABASE_URL")
    SUPABASE_SERVICE_ROLE_KEY = _secret("SUPABASE_SERVICE_ROLE_KEY")
    SUPABASE_JWT_SECRET = _secret("SUPABASE_JWT_SECRET")
    
    # OpenAI (strip so .env newlines/quotes don't break the key)
    OPENAI_API_KEY = _secret("OPENAI_API_KEY") or ""

    # Strict OpenAI client timeouts (async-queue work 2026-08-03). The SDK
    # default is 600s — one hung call used to park a gunicorn worker (half
    # of --workers 2) for 10 minutes. LLM/chat calls get the client-wide
    # OPENAI_TIMEOUT_SECONDS; Whisper transcription overrides per-call with
    # the larger OPENAI_TRANSCRIBE_TIMEOUT_SECONDS (a long take's
    # transcription legitimately runs minutes). Malformed env values fall
    # back to the defaults — never crash import (live loop).
    OPENAI_TIMEOUT_SECONDS = _env_float("OPENAI_TIMEOUT_SECONDS", 120.0)
    OPENAI_TRANSCRIBE_TIMEOUT_SECONDS = _env_float(
        "OPENAI_TRANSCRIBE_TIMEOUT_SECONDS", 600.0)
    OPENAI_MAX_RETRIES = _env_int("OPENAI_MAX_RETRIES", 2)
    # Chat model overrides (runtime_config in the database wins; these are the
    # env fallbacks OpenAIService._chat_model reads before its hard default).
    OPENAI_CHAT_MODEL = (os.getenv("OPENAI_CHAT_MODEL") or "").strip() or None
    OPENAI_COPILOT_MODEL = (os.getenv("OPENAI_COPILOT_MODEL") or "").strip() or None

    # ── F1 flags and tunables (audit Q-A5, 2026-09-14) ──────────────────────
    # These used to be os.getenv reads scattered through the F1 modules
    # (transcription, Ideal Text, Manager). They are read ONCE, here, at boot:
    # a Railway variable change restarts the process, so nothing is lost, and
    # the CONFIG-FIRST rule (set the variable before merging the code) now has
    # one place to look. Tests toggle them with patch.object(Config, NAME, …).
    # Defaults are the modules' own; the parsing conventions are preserved
    # exactly (_env_flag: on = "1"/"true"/"yes"; _env_not_off: default-on).
    INSTANT_IDEAL_TEXT_ENABLED = _env_flag("INSTANT_IDEAL_TEXT_ENABLED", "0")
    MOMENT_SUGGESTIONS_ENABLED = _env_flag("MOMENT_SUGGESTIONS_ENABLED", "0")
    # THE PRAISE DETECTORS' OWN SWITCH (founder 2026-10-06, Navigation Panel
    # QA3 A: "praise detectors get their own switch, turned on in a reviewed
    # change"; ledger A045, A053b). It gates ONLY detector praise -- the
    # structural device and the impeccable delivery read: whether the worker
    # runs them (`moment_suggestions.generate_praise_for_session`, when
    # MOMENT_SUGGESTIONS_ENABLED is off) and whether the read path stamps
    # their evidence so the Manager may serve them
    # (`tracked_changes._detector_praise_evidence`). Independent of
    # MOMENT_SUGGESTIONS_ENABLED, which keeps the rest of the star lane.
    # DEFAULT ON IN CODE, so a service that never got the variable (web,
    # worker or cron) still reads it on (CONFIG-FIRST); "0" switches it off.
    PRAISE_DETECTORS_ENABLED = _env_flag("PRAISE_DETECTORS_ENABLED", "1")
    POLISH_AS_SUGGESTIONS_ENABLED = _env_flag("POLISH_AS_SUGGESTIONS_ENABLED", "0")
    LIVING_TRANSCRIPT_ENABLED = _env_flag("LIVING_TRANSCRIPT_ENABLED", "0")
    # ON since #595, on evidence rather than on hope this time.
    #
    # The bake caused three real defects and one imagined one. The three are
    # fixed and each is pinned by a test that fails without its fix:
    #
    #   #583  an empty lane stored as a bake, served as "no bookmarks"
    #         -> the writer requires a non-empty `changes`
    #   #589  the READER kept the guard #583 had just replaced, so the same
    #         empty block was served anyway -> `is_a_bake`, asked by both
    #   #590  a stored six-hour signed clip URL served long after it died
    #         -> `_with_fresh_playback` re-signs on every serve
    #
    # The fourth was mine. #593 and #594 blamed a saturated worker queue for
    # processing the founder called stale. `processing_jobs` then showed
    # `waited_s` of 2 to 3 seconds on every row, today and yesterday: there
    # was never a jam. The wait was a frontend marker that never cleared
    # (frontend #421), and I turned a feature off on evidence I had not
    # checked.
    #
    # FOUNDER, on being shown that: "if baking was not the reason, please
    # bring it back. So that we have it faster than 30 seconds, we have it
    # 17 seconds."
    #
    # WHAT IS STILL TRUE FROM #593. One queue serves everything
    # (`job_queue.queue_name()`), so a bake really does sit in the same line
    # as `run_processing_job`. At one speaker that costs nothing — the
    # measured wait is three seconds. With several recording at once a
    # forty-second bake ahead of a take would delay it, and the fix then is
    # a queue of its own via PIPELINE_QUEUE_NAME, not this flag.
    #
    # Defaulted in code rather than set per service on purpose: the worker
    # writes the bake and the web process reads it, and a flag that is true
    # on one and false on the other is the CONFIG-FIRST failure in miniature.
    # One default cannot disagree with itself — and the founder does not have
    # this variable in Railway, which is the other half of the same argument.
    IDEAL_TEXT_FEEDBACK_BAKE_ENABLED = _env_flag(
        "IDEAL_TEXT_FEEDBACK_BAKE_ENABLED", "1")
    # WHERE BAKES QUEUE, and where a worker container listens (#596).
    #
    # Blank means "the pipeline queue" for both, so unset they behave exactly
    # as before and this ships without needing the config to land first
    # (CONFIG-FIRST: the config leads the cutover, the code never assumes it
    # already happened). Set BAKE_QUEUE_NAME on web+worker and WORKER_QUEUE on
    # a second worker service, matching, and a forty-second Manager run stops
    # sitting in the line a speaker is waiting in.
    BAKE_QUEUE_NAME = (os.getenv("BAKE_QUEUE_NAME") or "").strip()
    WORKER_QUEUE = (os.getenv("WORKER_QUEUE") or "").strip()
    # THE REASON LAYER (contract 24j). Off means the Confident Voice ordering
    # is byte-for-byte what it was; on means what the words did outranks how
    # the delivery sounded, sequenced and never blended.
    #
    # CONFIG-FIRST, and here it bites harder than usual: this decides which
    # moment is SELECTED, and the selection is FROZEN with the Take. A worker
    # that ranks one way while web ranks another would freeze one order and
    # serve the other, and the difference would be invisible — both answers
    # are well-formed items. Set it on web, worker AND cron together, or not
    # at all.
    REASONABLE_CONFIDENCE_ENABLED = _env_flag("REASONABLE_CONFIDENCE_ENABLED", "0")
    MANAGER_CONTROLS_ENABLED = _env_flag("MANAGER_CONTROLS_ENABLED", "1")
    COACH_PREFILL_ENABLED = _env_flag("COACH_PREFILL_ENABLED", "0")
    SENTENCE_BOUNDARY_SPLIT_ENABLED = _env_not_off("SENTENCE_BOUNDARY_SPLIT_ENABLED", "1")
    SENTENCE_SPLIT_MIN_GAP_MS = _env_int("SENTENCE_SPLIT_MIN_GAP_MS", 600)
    SENTENCE_SPLIT_MIN_CHARS = _env_int("SENTENCE_SPLIT_MIN_CHARS", 60)
    PIPELINE_JOB_STALE_MINUTES = _env_int("PIPELINE_JOB_STALE_MINUTES", 5)
    PIPELINE_JOB_HEARTBEAT_SECONDS = _env_int("PIPELINE_JOB_HEARTBEAT_SECONDS", 60)
    PIPELINE_JOB_MAX_ATTEMPTS = _env_int("PIPELINE_JOB_MAX_ATTEMPTS", 3)
    # The wall clock on ONE attempt. The heartbeat proves the PROCESS is
    # alive, never that the job is progressing, so a runner wedged on a
    # provider socket heartbeats forever and no recovery path can see it.
    PIPELINE_JOB_MAX_RUNTIME_MINUTES = _env_int(
        "PIPELINE_JOB_MAX_RUNTIME_MINUTES", 20)
    PIPELINE_ORPHAN_STALE_MINUTES = _env_int("PIPELINE_ORPHAN_STALE_MINUTES", 30)
    PIPELINE_SWEEP_INTERVAL_SECONDS = _env_int("PIPELINE_SWEEP_INTERVAL_SECONDS", 60)
    # TAKE FEEDBACK V3 SHADOW-WRITE MODE. J1-3 (audit 2026-09-22): the old
    # comment here read "Take Feedback V3 dark mode", which made this look
    # like the switch between the V2 and V3 policies. IT IS NOT, and an
    # operator who set it to "off" during an incident expecting V2 back would
    # have got V3 anyway.
    #
    # What it actually gates, through its one reader
    # `take_feedback_policy_v3.dark_enabled`, is a founder-scoped SHADOW
    # FRAME WRITE (`take_feedback_policy_v3_shadow_frames`, dataset_eligible
    # false by CHECK). It cannot add, remove or change one row a speaker sees.
    #
    # The flag that decides whether V3 serves is MLC3_SERVICE_ENABLED, via
    # `coach_guidance_delivery.runtime_is_enabled`. Kept under the old
    # variable name because it is set on live Railway services; renaming the
    # environment variable is a config-first cutover, not a comment fix.
    # `tests/test_take_feedback_policy_selection.py` holds both halves.
    TAKE_FEEDBACK_POLICY_V3_SHADOW_WRITE_MODE = (
        os.getenv("TAKE_FEEDBACK_POLICY_V3_MODE") or "off"
    ).strip()
    # The Python alias `TAKE_FEEDBACK_POLICY_V3_MODE` is removed (contract
    # 52: aliases are removed, not kept; audit 2026-10-05). The ENVIRONMENT
    # variable keeps its name above, because it is set on live Railway
    # services (config-first); only the duplicate attribute is gone.
    TAKE_FEEDBACK_POLICY_V3_FOUNDER_PRINCIPAL_ID = (
        os.getenv("TAKE_FEEDBACK_POLICY_V3_FOUNDER_PRINCIPAL_ID") or ""
    ).strip()
    # The deployed code's commit, for feedback provenance rows. Railway sets
    # the first; the others are the fallbacks the two F1 readers used to try
    # separately (their union, so neither reader loses a source).
    CODE_COMMIT_SHA = (
        os.getenv("RAILWAY_GIT_COMMIT_SHA")
        or os.getenv("GIT_COMMIT_SHA")
        or os.getenv("SOURCE_COMMIT")
        or os.getenv("SOURCE_VERSION")
        or ""
    ).strip()
    
    # Email (Resend)
    RESEND_API_KEY = _secret("RESEND_API_KEY")
    RESEND_FROM_EMAIL = os.getenv("RESEND_FROM_EMAIL")
    ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "artur@willonski.com")

    # The data-foundation canary's three doors (DATA_FOUNDATION_CANARY_ENABLED,
    # the founder email, MLC2_CONFIDENCE_CANARY_PRINCIPAL_ID) were retired on
    # 2026-09-29: whose Takes get a canonical row is the `canonical_take_rows`
    # ring row (0394), its kill switch is the row's kill. A Railway panel that
    # still carries them sets nothing.
    # THE LEARNING DOORS' SWITCHES WERE REMOVED on 2026-10-12 (founder: "remove
    # the learning doors"), each with the value it held: the training switch
    # (door 1), pair releases (door 2), training (door 3), promotion (door 4),
    # the training-corpus copy and the corpus import were on and now simply
    # run; the retired DPO dataset-release export was off and its code was
    # deleted. Consent is untouched: every training use still needs the
    # speaker's own training yes, checked in code and refused by the database.
    #
    # DOOR 2, PER SURFACE (founder 2026-09-30, L5; build plan ML-9). The
    # weekly job exports a pair surface only when the surface is named here,
    # each by a reviewed change carrying the founder's sentence ("open door 2
    # for surface S"). Opened 2026-10-01 for exercise_script (N16),
    # praise_line and clearer_version (C4, N18); the coach-word surfaces of
    # Phase 7 (coach_moment_line, coach_take_word) were named here and in
    # doors 3 and 4 from 2026-10-08 (founder: "turn it all ON"), under
    # Privacy/Terms 3.5 signed 2026-10-08 (N68) and published that evening.
    # CLOSED AGAIN 2026-10-19 (founder, chat: "Close them for now"; N79):
    # they are a coach's direct messages to one speaker, and they train only
    # once names and specifics are scrubbed. Until the scrub step, the one
    # privacy update and the versioned coach agreement exist, both surfaces
    # are still recorded but leave by no door. Reopening them is a reviewed
    # change carrying the founder's sentence, here and in doors 3 and 4.
    PAIR_RELEASE_SURFACES: frozenset = frozenset({
        "exercise_script", "praise_line", "clearer_version",
    })
    # Where a release goes and what signs its manifest (ML-9). Unset, the
    # exporter refuses and says why; nothing leaves.
    R2_PAIR_RELEASE_BUCKET = (os.getenv("R2_PAIR_RELEASE_BUCKET") or "").strip()
    PAIR_RELEASE_SIGNING_KEY = _secret("PAIR_RELEASE_SIGNING_KEY") or ""
    PAIR_RELEASE_SIGNING_KEY_ID = (os.getenv("PAIR_RELEASE_SIGNING_KEY_ID") or "pair-release-key-1").strip()
    # DOORS 3 AND 4, PER SURFACE (founder 2026-09-30, L6 to L9; build plan
    # ML-11, ML-12). The weekly job starts a fine-tune for a surface only when
    # the surface is named here ("open door 3 for surface S"); a promotion
    # writes runtime_config, and a promoted model is served, only when the
    # surface is named here ("open door 4 for surface S"). Both were empty
    # until 2026-10-08; both are reviewed changes.
    # Named 2026-10-08 (founder: "turn it all ON"): the three answer
    # surfaces. The two coach-word surfaces were named the same day and
    # closed again 2026-10-19 with door 2 (N79, above).
    TRAINING_SURFACES: frozenset = frozenset({
        "exercise_script", "praise_line", "clearer_version",
    })
    PROMOTION_SURFACES: frozenset = frozenset({
        "exercise_script", "praise_line", "clearer_version",
    })
    # The base model a run fine-tunes (ML-11). An environment choice, not a
    # door: changing it opens nothing.
    OPENAI_FINE_TUNE_BASE_MODEL = (os.getenv("OPENAI_FINE_TUNE_BASE_MODEL")
                                   or "gpt-4.1-mini-2025-04-14").strip()

    # Q4-A (founder 2026-10-02): the share switch is written into both
    # Terms and Privacy, in a new Phase-1 policy version everyone re-accepts
    # before the switch appears (the 1 October path: Terms 3.2 + Privacy 3.2
    # → phase1-2026-10-01 → re-acceptance). This names that policy version:
    # phase1-2026-10-02, Privacy 3.3 + Terms 3.3 (scripts/
    # phase1_policy_publish_3_3.sql, N24). The share route refuses until the
    # speaker's current authorization is on it or a later one, so setting it
    # before the publish runs is the safe order: until then nobody is on it.
    PEER_SHARE_POLICY_VERSION: str | None = "phase1-2026-10-02"
    # 6a: the same version carries the blind check's Privacy §4 purpose
    # (15 §1). A clip is sampled only from a speaker whose current
    # authorization is on it or later (services/error_presence_audit.py,
    # _on_notice_version): the balancing test holds only for a speaker who
    # has read the line, never before the publish.
    BLIND_CHECK_POLICY_VERSION: str | None = "phase1-2026-10-02"

    # CM2 B (founder 2026-10-06, N53.2; Q-B6 A, N62): sharing switches on
    # with the sharing screen, under the founder's own signed words for it
    # (N54, WQ5 A / WQ6 A), without waiting for counsel; the founder took the
    # risk stated on the panel ("people's voices reach others under words
    # counsel has not checked, in the EU"). Sharing names the CURRENT
    # Privacy/Terms: the Phase-1 policy version below (phase1-2026-10-02,
    # Privacy 3.3 + Terms 3.3, scripts/phase1_policy_publish_3_3.sql). The
    # share route refuses (409 TERMS_REACCEPT_REQUIRED) until the speaker's
    # current authorization is on it or later; "None" still revokes without
    # any version. Each share row is stamped with it (take_shares.
    # consent_version) and with the version of the sharing screen's words
    # the speaker saw (take_shares.share_words_version, 0443), which the
    # screen sends. Communities are on (N67; their switch was deleted
    # 2026-10-11).
    COMMUNITY_SHARE_POLICY_VERSION: str | None = "phase1-2026-10-02"
    # The versions of the sharing screen's words a share may record (0443):
    # the server's own list, so a share can only name words that were really
    # signed and shown. "sharing-screen-2026-10-06" is the founder's signed
    # sharing words (N54, WQ5 A / WQ6 A; docs/SIGNED-line-bank-2026-10-06.md,
    # "Sharing"). When counsel or the founder changes those words, the new
    # version is added here in the same PR as the screen that shows it; an
    # old version stays listed while a screen that shows it may still be open.
    # Any other version is refused (400 SHARE_WORDS_VERSION_UNKNOWN).
    # 2026-10-12: the question asked before the next recording ("Do you agree
    # to share your next take with others?", founder lock of the moment and
    # feedback chat, section 9).
    SHARE_WORDS_VERSIONS: tuple[str, ...] = ("sharing-screen-2026-10-06", "sharing-screen-2026-10-12")

    # 6d: fitting a learned detector on audit answers. ON from 2026-10-02
    # (founder: "You have my go on each of the flips"; N26): the AI Act
    # determination is document 02 v1.1 (the founder's own, Q7, signed
    # 2026-10-02, N24; registered by its hash once uploaded), and the only
    # input is the blind-check answers, each from a speaker on Privacy 3.3
    # whose §4 line says the answer corrects the software (N25). The tuned
    # thresholds (no fit) run in shadow regardless. OFF again from
    # 2026-10-03 (founder, F1 Repair Plan Phase 0, N29): LearnedDetector.fit
    # does not exist yet (NotImplementedError, no caller), and document 02
    # v1.1 §9 keeps this gate off until counsel confirms. It comes back on
    # with counsel's confirmation and a fit that exists.
    # ON again from 2026-10-08 (founder: "turn it all ON"): the fit exists
    # (#973, shadow only, consenting speakers' blind answers) and document 02
    # v1.2 is signed (N68, counsel not yet consulted, as the founder signed).
    DETECTOR_TRAINING_AUTHORISED = True
    # Slice 6 readiness replaces the ambiguous bool with an irreversible
    # three-state contract.  ``dark`` was the pre-cutover behavior;
    # ``founder_canary`` is THE FLIP (founder 2026-09-29, after the
    # readiness cron read READY with no blocker: the ring row present and
    # not killed, one bundled consent grant, monitor and alert sink on,
    # every downstream capability disabled); ``killed`` disables both
    # canonical and retired learning writes so an incident rollback can
    # never resurrect the old supervision path. One-way: this constant goes
    # dark → founder_canary → killed and never back.
    # Deliberately not environment-controlled: activation required review,
    # code change and deployment rather than an unreviewed dashboard toggle.
    # The rings panel can only CLOSE this state: killing the one-way
    # `confidence_learning_writes` row makes configured_confidence_cutover()
    # read `killed` on every service (services/mlc2_confidence_cutover.py).
    # Nothing outside a reviewed code change can make it read more open.
    MLC2_CONFIDENCE_CUTOVER_MODE = "founder_canary"
    # The chain's "who" is the `confidence_learning_writes` ring row (0394);
    # readiness reads the row and the ring-eligible principals. The founder
    # email constant and the canary principal variable that used to say it
    # were retired on 2026-09-29.
    # Non-production recipient redirect. When set (and ENV != production),
    # services.email_service.send_email_resend sends EVERY message here
    # instead of the real recipient, subject-tagged with who it was for.
    # This is what makes a prod-mirroring staging environment safe to run
    # against a copy of the user table. Unset = today's behaviour.
    EMAIL_REDIRECT_TO = (os.getenv("EMAIL_REDIRECT_TO") or "").strip()

    # WhatsApp "the feedback from your coach is in", through Meta's WhatsApp
    # Cloud API. Off unless WHATSAPP_NOTIFICATIONS=true; numbers are still
    # saved while it is off. A message the business starts needs a template
    # Meta approved: WHATSAPP_TEMPLATE_NAME names it (without it the plain
    # text is sent, which WhatsApp only delivers within 24 hours of the
    # person's last message). WHATSAPP_REDIRECT_TO is EMAIL_REDIRECT_TO's
    # twin for non-production.
    WHATSAPP_NOTIFICATIONS = os.getenv("WHATSAPP_NOTIFICATIONS", "false").lower() == "true"
    WHATSAPP_ACCESS_TOKEN = _secret("WHATSAPP_ACCESS_TOKEN") or ""
    WHATSAPP_PHONE_NUMBER_ID = (os.getenv("WHATSAPP_PHONE_NUMBER_ID") or "").strip()
    WHATSAPP_TEMPLATE_NAME = (os.getenv("WHATSAPP_TEMPLATE_NAME") or "").strip()
    WHATSAPP_TEMPLATE_LANGUAGE = (os.getenv("WHATSAPP_TEMPLATE_LANGUAGE") or "en").strip()
    # The public image for a template with an image header (e.g. the logo at
    # https://willpowerlab.com/brand/...png); unset for a text-only template.
    WHATSAPP_TEMPLATE_HEADER_IMAGE_URL = (os.getenv("WHATSAPP_TEMPLATE_HEADER_IMAGE_URL") or "").strip()
    WHATSAPP_REDIRECT_TO = (os.getenv("WHATSAPP_REDIRECT_TO") or "").strip()
    # True once the template's first button is a dynamic URL
    # (https://www.willpowerlab.com/{{1}}): each message then fills it with the
    # project's feedback address. Off = the template's link as Meta stores it.
    WHATSAPP_TEMPLATE_LINK_BUTTON = os.getenv("WHATSAPP_TEMPLATE_LINK_BUTTON", "false").lower() == "true"
    # The booking's one WhatsApp message (N144, N165, N189): the reminder 10
    # minutes before, a template Meta approved (`booking_reminder`) with the
    # Meet link as {{1}} (N200). Unset, the plain text is sent, which WhatsApp
    # only delivers within 24 hours of the person's last message. Same switch,
    # number and language as the coach's message.
    WHATSAPP_BOOKING_REMINDER_TEMPLATE = (os.getenv("WHATSAPP_BOOKING_REMINDER_TEMPLATE") or "").strip()
    # The booking's reminder to the number saved on the account (founder
    # 2026-10-26, N207; the booking form asks for none). On once the privacy
    # version names the reminder; off, only a booking that carries a number
    # (made before N207) gets it.
    BOOKING_WHATSAPP_TO_ACCOUNT = os.getenv("BOOKING_WHATSAPP_TO_ACCOUNT", "false").lower() == "true"
    # Replies to our WhatsApp number reach /v2/whatsapp/webhook (founder
    # 2026-10-28, N237): STOP turns the messages off. The verify token is any
    # string, typed in both here and Meta's webhook settings; the app secret
    # is the Meta app's, which signs every delivery. Both unset, the door is
    # shut (503).
    WHATSAPP_WEBHOOK_VERIFY_TOKEN = (os.getenv("WHATSAPP_WEBHOOK_VERIFY_TOKEN") or "").strip()
    WHATSAPP_APP_SECRET = (os.getenv("WHATSAPP_APP_SECRET") or "").strip()
    # The plan's own yes (founder 2026-10-27, N211): the worry question, the
    # two ratings, "How did it go?" and the feelings check are asked only after
    # a yes to a question of its own. On since Privacy 3.9, which names it, was
    # published (2026-10-28, N217); PLAN_CONSENT_ENABLED=false turns it off,
    # and off, the plan asks as it did before.
    PLAN_CONSENT_ENABLED = os.getenv("PLAN_CONSENT_ENABLED", "true").lower() != "false"

    # Current published Terms / Privacy Policy version. Must match the
    # "Last updated" date in the live legal docs (e.g. "1.0" = Terms
    # dated 7 May 2026; bump when docs are materially revised). The
    # /v2/user/consent endpoint reads this to decide whether the user
    # is "behind" on terms acceptance (terms_consent=false means the
    # frontend prompts a re-accept). Hardcoded default mirrors the
    # migration's user_consents.terms_version default; override via
    # env once docs change so behavior shifts without a redeploy.
    CURRENT_TERMS_VERSION = os.getenv("CURRENT_TERMS_VERSION", "1.2")

    # Sentry
    SENTRY_DSN = os.getenv("SENTRY_DSN")
    # Performance tracing sample rate. Was hardcoded 1.0 in app.py + worker.py
    # — a transaction per request, health checks included, which exhausts the
    # quota on noise and then costs us ERROR visibility on the live loop.
    # 5% in production is plenty for latency trends; 0 elsewhere so local and
    # CI runs send nothing. ERROR capture is never sampled by this.
    SENTRY_TRACES_SAMPLE_RATE = _env_float(
        "SENTRY_TRACES_SAMPLE_RATE",
        0.05 if (os.getenv("ENV", "development") or "").strip().lower()
        in ("production", "prod") else 0.0,
    )
    # Profiling multiplies on top of tracing (it samples sampled traces).
    # Off by default — turn it on deliberately when chasing a CPU question.
    SENTRY_PROFILES_SAMPLE_RATE = _env_float("SENTRY_PROFILES_SAMPLE_RATE", 0.0)
    # Deploy identifier for Sentry release tagging. Railway injects
    # RAILWAY_GIT_COMMIT_SHA; anything else can set RELEASE_SHA directly.
    RELEASE_SHA = (
        os.getenv("RELEASE_SHA")
        or os.getenv("RAILWAY_GIT_COMMIT_SHA")
        or ""
    ).strip()
    
    # CORS (browser admin UI → backend; include production app origin or set CORS_ORIGINS explicitly)
    CORS_ORIGINS = _merge_cors_origins()
    
    # Audio limits
    MAX_AUDIO_SIZE_MB = 25
    # Long-take SOFT CAUTION (founder 2026-07-27). At or above this target
    # length the setup wizard shows a caution — practise the beginning and the
    # ending in short takes instead — and the user proceeds anyway if they
    # want. NOT a limit: nothing server-side truncates, rejects or caps on it.
    # Served on GET /v2/config/recording and GET /v2/explore/arc/<id>/setup so
    # the number lives in ONE place instead of an FE hardcode.
    LONG_TAKE_CAUTION_SECONDS = int(
        os.getenv("LONG_TAKE_CAUTION_SECONDS", "600"))
    # Admin reference video upload limit (Training Studio)
    MAX_REFERENCE_VIDEO_SIZE_MB = int(os.getenv("MAX_REFERENCE_VIDEO_SIZE_MB", "500"))
    
    # Storage
    AUDIO_BUCKET_NAME = "audio_recordings"
    SIGNED_URL_EXPIRY_SECONDS = 3600
    COACH_FEEDBACK_VIDEO_BUCKET = (os.getenv("COACH_FEEDBACK_VIDEO_BUCKET") or "coach_feedback_videos").strip() or "coach_feedback_videos"
    # Upload size cap (MB) for the per-take coach summary video.
    # Env-tunable so the cap can move without a deploy; a malformed value
    # falls back to 100 (never crash import — live loop).
    COACH_FEEDBACK_VIDEO_MAX_MB = _env_int("COACH_FEEDBACK_VIDEO_MAX_MB", 100)
    # Single deliverable (founder re-shape 2026-07-17): the ONLY paid item —
    # opening a presentation's key-moment explanations. 5 credits ($5),
    # one-time per presentation. Env-tunable, malformed → 5.
    MOMENTS_UNLOCK_CREDITS = _env_int("MOMENTS_UNLOCK_CREDITS", 5)
    # Star suggestions (founder 2026-07-18): a slide-stickiness composite at
    # or below this low band triggers a REPLACE suggestion ("highly
    # inadequate" relatedness). 0..1 scale; stored ×100 as an int so the
    # env stays simple (15 = 0.15). Malformed → 15.
    MOMENT_REPLACE_STICKINESS_MAX_PCT = _env_int(
        "MOMENT_REPLACE_STICKINESS_MAX_PCT", 15)
    # Cap on suggestion LLM generations per take (cost bound).
    MOMENT_SUGGESTIONS_MAX_PER_TAKE = _env_int(
        "MOMENT_SUGGESTIONS_MAX_PER_TAKE", 8)
    # Measured delivery stars (founder 2026-07-18): |z| vs the speaker's own
    # baseline before a delivery suggestion fires. Deliberately looser than
    # the 2.0 outside-normal-range triage bar — a coaching nudge, not an
    # anomaly flag. Deterministic, no LLM.
    DELIVERY_STAR_Z = _env_float("DELIVERY_STAR_Z", 1.2)
    DELIVERY_STARS_MAX_PER_TAKE = _env_int("DELIVERY_STARS_MAX_PER_TAKE", 3)
    # Structural stars (founder 2026-07-18): amber "practice this" prompts on
    # a contrast / list-of-three, on snippets with no acoustic star. Applied
    # AFTER the acoustic cap so acoustic stars are never displaced.
    STRUCTURAL_STARS_MAX_PER_TAKE = _env_int(
        "STRUCTURAL_STARS_MAX_PER_TAKE", 3)   # founder 2026-07-18: 2-3 → 3
    # Cloudflare R2 (S3 API) for coach/reference/feedback videos — set all four to use R2 instead of Supabase Storage.
    R2_ACCOUNT_ID = (os.getenv("R2_ACCOUNT_ID") or "").strip()
    R2_ACCESS_KEY_ID = _secret("R2_ACCESS_KEY_ID") or ""
    R2_SECRET_ACCESS_KEY = _secret("R2_SECRET_ACCESS_KEY") or ""
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


    # General-user MLC-3 serving. Legacy pilot configuration must never
    # broaden the rollout-aware database authorization boundary. Disabled is
    # the only safe default.
    MLC3_SERVICE_ENABLED = (
        (os.getenv("MLC3_SERVICE_ENABLED") or "0").strip().lower()
        in ("1", "true", "yes", "on")
    )
    # Coach-side drafting is intentionally separable from user serving.
    # The database still requires the complete blind-review/reveal contract.
    MLC3_COACH_INLINE_AUTHORING_ENABLED = (
        (os.getenv("MLC3_COACH_INLINE_AUTHORING_ENABLED") or "0")
        .strip().lower() in ("1", "true", "yes", "on")
    )

    # ── Confident Moment Coaching Bundle v1 (Chunk 3) ────────────────────────
    # Local disabled-gate implementation only. These flags never imply
    # dataset eligibility, training, evaluation, promotion, or serving of
    # any learned model. Both must remain false until separately authorized
    # activation readiness review. See Interface Manifest D6 and Contract
    # Delta D3.
    CONFIDENT_MOMENT_BUNDLE_V1_ENABLED = (
        (os.getenv("CONFIDENT_MOMENT_BUNDLE_V1_ENABLED") or "0")
        .strip().lower() in ("1", "true", "yes", "on")
    )
    ROOTING_COVERAGE_V1_ENABLED = (
        (os.getenv("ROOTING_COVERAGE_V1_ENABLED") or "0")
        .strip().lower() in ("1", "true", "yes", "on")
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

    # ── Cloudflare R2 — WILLAB LAB AUDIO (the user's takes) ──────────────
    # P0 audit 2026-08-03: lab takes were landing in coach_feedback_videos,
    # mixing the user's voice with the coach's curated (effectively public)
    # media under one access policy and one lifecycle rule. Own bucket, own
    # public base, own retention.
    #
    # BOTH must be set for the split to activate (services.lab_audio_storage
    # .lab_audio_segregated). Setting only the bucket would write to the new
    # location while still minting URLs against the OLD public domain, so
    # every new take's audio_url would 404. With either unset, behaviour is
    # byte-for-byte what it was before — reads always fall back across
    # buckets, so nothing written pre-cutover becomes unreadable, and
    # unsetting these rolls the change back.
    R2_LAB_AUDIO_BUCKET = (os.getenv("R2_LAB_AUDIO_BUCKET") or "").strip()
    R2_LAB_AUDIO_PUBLIC_BASE_URL = (
        os.getenv("R2_LAB_AUDIO_PUBLIC_BASE_URL") or ""
    ).strip()

    # Wall-clock budget (seconds) for the SYNCHRONOUS upload→analysis path,
    # checked at stage boundaries (services.upload_guard.Deadline). Bounds
    # the SUM of the per-step timeouts: without it a run where every stage
    # is merely slow parks a gunicorn worker until --timeout 1800 reaps it,
    # and the client sees a dead socket instead of an error. 0 disables.
    # Well under Railway's proxy timeout so the 504 is OURS, with a code
    # the FE can act on.
    SYNC_UPLOAD_DEADLINE_SECONDS = _env_int("SYNC_UPLOAD_DEADLINE_SECONDS", 600)

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


    
    # Frontend URL (for email links)
    FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")

    # UNSUBSCRIBE_TOKEN_SECRET — dedicated HS256 signing key for the
    #                        unsubscribe JWTs. Distinct from the auth
    #                        JWT secret so a leak here doesn't burn
    #                        session credentials.
    UNSUBSCRIBE_TOKEN_SECRET = (os.getenv("UNSUBSCRIBE_TOKEN_SECRET") or "").strip()

    # Optional: shared secret for POST /v2/internal/student-credits/increment (Stripe webhook / BFF).
    INTERNAL_CREDITS_WEBHOOK_SECRET = (os.getenv("INTERNAL_CREDITS_WEBHOOK_SECRET") or "").strip()
    # Shared secret for POST /v2/internal/learning/weekly (the weekly learning
    # job's cron, founder 2026-09-30; ML-3). Unset = the route answers 503.
    LEARNING_WEEKLY_SECRET = (os.getenv("LEARNING_WEEKLY_SECRET") or "").strip()
    # Shared secret for POST /v2/internal/deletion/complete-due (deletions
    # that complete by themselves after seven days, founder 2026-10-05,
    # N48.4 Q14 A / Q17 A). Unset = the route answers 503.
    DELETION_COMPLETION_SECRET = (
        os.getenv("DELETION_COMPLETION_SECRET") or ""
    ).strip()
    # The purge kill switch scripts/run_phase1_data_purge.py also reads.
    # Only "true" executes; anything else makes the completion run a dry run
    # that reports what is due and writes nothing.
    PHASE1_PURGE_EXECUTION_ENABLED = (
        (os.getenv("PHASE1_PURGE_EXECUTION_ENABLED") or "").strip().lower()
        == "true"
    )
    # Shared secret for POST /v2/internal/retention/clean (the scheduled
    # clean-up's daily cron, founder 2026-10-05, N48.4 Q16 A). Unset = the
    # route answers 503. It never decides whether anything is deleted: that is
    # RETENTION_CLEANER_LIVE in services/retention_cleaner.py.
    RETENTION_CLEANER_SECRET = (os.getenv("RETENTION_CLEANER_SECRET") or "").strip()
    # Sign up and sign in with WhatsApp (founder 2026-10-27, N214): Supabase's
    # Send SMS hook signs each request with this secret (Supabase shows it as
    # "v1,whsec_..."); unset, the hook's door is shut (503). The code goes out
    # with the Authentication template Meta approved, named here.
    SEND_SMS_HOOK_SECRET = (os.getenv("SEND_SMS_HOOK_SECRET") or "").strip()
    WHATSAPP_LOGIN_TEMPLATE = (os.getenv("WHATSAPP_LOGIN_TEMPLATE") or "login_code").strip()

    # willab — upfront free credit grant seeded on a user's first ledger touch
    # (founder testing 2026-07-13: bumped 15 → 25 so every user can unlock one
    # $25 arc during testing). Env-tunable so it can move without a deploy.
    WILLAB_FREE_CREDIT_GRANT = int(os.getenv("WILLAB_FREE_CREDIT_GRANT") or "25")

    # Password for the testing-phase credits admin page (body field, not a
    # header — the browser page sends it). Blank ⇒ the endpoints 503 (disabled).
    CREDIT_ADMIN_PASSWORD = (os.getenv("CREDIT_ADMIN_PASSWORD") or "").strip()

    # Journal CMS (founder 2026-07-25) — same body-password pattern as the
    # credits admin above, so the /admin/journal browser page can send it from
    # a form field. Blank ⇒ every /v2/internal/journal/* endpoint 503s
    # (disabled); the PUBLIC /v2/journal/* read endpoints are unaffected.
    JOURNAL_ADMIN_PASSWORD = (os.getenv("JOURNAL_ADMIN_PASSWORD") or "").strip()

    # Community Content Studio (founder 2026-07-26) — the one button in the
    # CMS that derives the three community post formats from a Journal post.
    # DEFAULT ON; this is a kill switch for the LLM cost, not a rollout gate.
    # Off ⇒ /v2/internal/journal/community/generate 503s, while list/update/
    # delete keep working so drafts already generated stay readable and
    # copyable. Auth is JOURNAL_ADMIN_PASSWORD above — there is no separate
    # password for this surface.
    COMMUNITY_CONTENT_ENABLED = (
        (os.getenv("COMMUNITY_CONTENT_ENABLED") or "1").strip().lower()
        in ("1", "true", "yes", "on")
    )

    # Generated journal covers (founder 2026-07-28) — the "Draw a cover"
    # button in the CMS. DEFAULT ON; a kill switch for the image bill, not a
    # rollout gate. Off ⇒ /v2/internal/journal/image/generate 503s, while
    # list/select/delete keep working so covers already drawn stay usable.
    # Auth is JOURNAL_ADMIN_PASSWORD above.
    JOURNAL_IMAGE_ENABLED = (
        (os.getenv("JOURNAL_IMAGE_ENABLED") or "1").strip().lower()
        in ("1", "true", "yes", "on")
    )
    # gpt-image-1 is the default: it is what the live endpoint is built around
    # and it always returns bytes. The PINNED SDK (openai==1.59.2) predates it
    # and types only DALL·E's vocabulary, but forwards model/size/quality as
    # plain strings without enforcing its Literal hints, so the call goes
    # through (verified live 2026-07-28). Falling back to dall-e-3 means
    # setting SIZE and QUALITY to ITS vocabulary (1792x1024 / standard) — a
    # value the chosen model does not accept falls back to the family default
    # with a warning, rather than 400ing every draw.
    JOURNAL_IMAGE_MODEL = (os.getenv("JOURNAL_IMAGE_MODEL") or "").strip()
    JOURNAL_IMAGE_SIZE = (os.getenv("JOURNAL_IMAGE_SIZE") or "").strip()
    JOURNAL_IMAGE_QUALITY = (os.getenv("JOURNAL_IMAGE_QUALITY") or "").strip()

    # ── The Life Panel (founder-directed, 2026-07-26) ────────────────────
    # A personal life-governance surface (/v2/life/*). Two-tier gate:
    #
    #   LIFE_PANEL_ENABLED    global kill switch, DEFAULT OFF. Off ⇒ every
    #                         /v2/life/* route 404s and the chat router hook
    #                         is never reached, so chat is byte-identical to
    #                         today. Flip it only after the FE deploys.
    #   LIFE_PANEL_ALLOWLIST  comma-separated user ids for the FOUNDER-ONLY
    #                         surfaces (anything coach-only). NOT the
    #                         principles engine — that one is public behind
    #                         the consent screen (L-6). The prayer link it was
    #                         built for is retired (2026-08-04); prayer is a
    #                         separate app on pompeiana.willpowerlab.com.
    #
    # Allowlisted entries are ABSENT from the payload and their endpoints 404
    # rather than 403: a 403 confirms the surface exists.
    LIFE_PANEL_ENABLED = (
        (os.getenv("LIFE_PANEL_ENABLED") or "0").strip().lower()
        in ("1", "true", "yes", "on")
    )
    LIFE_PANEL_ALLOWLIST = tuple(
        uid.strip() for uid in (os.getenv("LIFE_PANEL_ALLOWLIST") or "").split(",")
        if uid.strip()
    )
    # The hour (0-23, UTC) at or after which the evening pass may generate.
    # Read on the API path so a card opened at 09:00 does not stamp
    # evening_generated_at and open the evening section twelve hours early —
    # the FE branches on that stamp. The cron is the primary trigger; this is
    # what keeps a read from pre-empting it.
    #
    # UTC, not local: there is no per-user timezone in the schema, and
    # inventing one for a single-user feature would be the wrong thing to
    # guess. Set it to the UTC hour that corresponds to 23:00 where the user
    # actually is — 21 for Poland in summer, 22 in winter.
    LIFE_PANEL_EVENING_HOUR_UTC = _env_int("LIFE_PANEL_EVENING_HOUR_UTC", 21)

    # BE-10: "use an API path with no training retention". OpenAI's retention
    # posture is a PROJECT/ORG setting, not a request parameter — so the code
    # side of that requirement is the ability to point life derivations at a
    # separate zero-data-retention project key. Unset ⇒ falls back to the
    # shared OPENAI_API_KEY (dev), which is why the operator step is called
    # out in the migration notes rather than assumed.
    LIFE_PANEL_OPENAI_API_KEY = (
        os.getenv("LIFE_PANEL_OPENAI_API_KEY") or ""
    ).strip().strip('"').strip("'")

    # Bumped whenever the consent copy changes materially. A user who accepted
    # an older version is re-asked before any further life row is written
    # (L-6) — which is the point of versioning it rather than storing a bool.
    LIFE_PANEL_CONSENT_VERSION = (
        os.getenv("LIFE_PANEL_CONSENT_VERSION") or "1.0"
    ).strip() or "1.0"

    # Journal cover media in R2 (presigned direct-to-storage upload). Reuses
    # the shared R2_ACCOUNT_ID / R2_ACCESS_KEY_ID / R2_SECRET_ACCESS_KEY above.
    # Both unset ⇒ services.journal_media falls back to the user-media bucket
    # so dev environments work; presign refuses when no public base URL
    # resolves, rather than stranding an unreferenceable upload.
    R2_JOURNAL_BUCKET = (os.getenv("R2_JOURNAL_BUCKET") or "").strip()
    R2_JOURNAL_PUBLIC_BASE_URL = (
        os.getenv("R2_JOURNAL_PUBLIC_BASE_URL") or ""
    ).strip()

    # Stripe → one-time token packages (POST /v2/internal/stripe/webhook,
    # services/token_packages.py). Webhook signing secret from Stripe Dashboard.
    # The credit-pack map (STRIPE_CHECKOUT_PRICE_CREDITS_JSON) and the
    # subscription tier map (STRIPE_PRICE_TIER_JSON) are retired with their
    # paths (founder 2026-10-05, N48.3 Q13 A) and read by nothing.
    STRIPE_WEBHOOK_SECRET = _secret("STRIPE_WEBHOOK_SECRET") or ""
    # Secret key: opens package Checkout Sessions and re-reads them in the webhook.
    STRIPE_SECRET_KEY = _secret("STRIPE_SECRET_KEY") or ""

    # Master switch for the whole token-pricing surface. Default OFF — unlike
    # the Phase 0 cost ledger, this one can refuse a user's action, so it ships
    # dark and is flipped once the FE can render a balance.
    TOKEN_PRICING_ENABLED = (os.getenv("TOKEN_PRICING_ENABLED") or "0").strip()

    # ── willab — Paid Audits. An "audit" = an explore arc (3 takes + the
    # coach-corrected ideal text). Re-priced 2026-07-06: $25, spent as
    # ARC_UNLOCK_CREDITS from the existing credits balance (NOT a second
    # Stripe SKU — see POST /v2/arc/<arc_id>/unlock). AUDIT_PRICE_AMOUNT_MINOR/
    # CURRENCY are kept ONLY as the display-price the credits are worth. The
    # Stripe-direct arc checkout (STRIPE_AUDIT_PRICE_ID, AUDIT_CHECKOUT_*_URL)
    # is removed (founder 2026-10-05, N48.3 Q13 A).
    AUDIT_PRICE_CURRENCY = (os.getenv("AUDIT_PRICE_CURRENCY") or "usd").strip().lower() or "usd"
    AUDIT_PRICE_AMOUNT_MINOR = int(os.getenv("AUDIT_PRICE_AMOUNT_MINOR") or "2500")
    # THE live price (2026-07-06): credits spent by POST /v2/arc/<arc_id>/unlock.
    # 1 credit = $1 (this model's founding peg — no Stripe pack pricing was
    # configured in env before this, so there is no prior peg to violate).
    #
    # ⚠️ SUPERSEDED 2026-07-31 — CREDITS ARE BEING DROPPED, tokens only. The
    # instruction that used to sit here ("at least one Stripe credit pack must
    # map a Price id to >=25 credits before this ships live") is now the exact
    # opposite of the direction: the credit-pack path is removed (N48.3 Q13 A).
    # Do not re-add a pack to satisfy a comment. The legacy `credits` column and this constant stay put (standing
    # constraint: never auto-drop); real users still hold balances, and the
    # conversion rate is unsettled — see PRICING-TOKENS-PLAN.md §16.
    ARC_UNLOCK_CREDITS = int(os.getenv("ARC_UNLOCK_CREDITS") or "25")

    # ── dev-bugs internal collector (dev.willpowerlab.com) ───────────────
    # Small founder-only bug jotter (text/voice/image) -> dev_bugs table,
    # emailed to DEV_BUGS_TO every 3 days by a Railway cron. See
    # routes/dev_bugs.py, services/dev_bugs.py, bin/railway-devbugs-cron.sh.
    # Shared secret the frontend sends as `x-dev-key` on every /api/dev-bugs
    # call (and the cron sends when POSTing /api/dev-bugs/send). Empty = the
    # API is disabled (503); set a long random string to switch it on.
    DEV_BUGS_KEY = (os.getenv("DEV_BUGS_KEY") or "").strip()
    # Digest recipient (defaults to the founder / ADMIN_EMAIL).
    DEV_BUGS_TO = (os.getenv("DEV_BUGS_TO") or os.getenv("ADMIN_EMAIL") or "artur@willonski.com").strip()
    # Host that serves the collector page at "/" (so dev.willpowerlab.com/ works).
    DEV_BUGS_HOST = (os.getenv("DEV_BUGS_HOST") or "dev.willpowerlab.com").strip().lower()
    # When true, saving a dev-bug also fires a BACKGROUND GPT-4o call that turns it
    # into a user-story-centered task in the "user stories · tasks" view (see
    # services/dev_tasks.py). Default OFF — flip on once the tasks UI ships. It is
    # best-effort and threaded, so it never blocks or breaks the bug save.
    DEV_TASKS_ENABLED = (os.getenv("DEV_TASKS_ENABLED") or "false").strip().lower() in ("1", "true", "yes", "on")
    # Level-1 re-evaluation: when a NEW P1/P2 task is generated, bump UP a few
    # RELATED existing tasks (the new one makes them more urgent). Pins are never
    # touched, bumps only (never demotes), capped, and each is stamped with a
    # reason. Default OFF — flip on once you trust the auto-generation. See
    # services/dev_tasks.reevaluate.
    DEV_TASKS_REEVAL_ENABLED = (os.getenv("DEV_TASKS_REEVAL_ENABLED") or "false").strip().lower() in ("1", "true", "yes", "on")
    DEV_TASKS_REEVAL_MAX_CHANGES = _env_int("DEV_TASKS_REEVAL_MAX_CHANGES", 3)

    # Where the annotation export writes; the bundled-era erasure reads it.
    ANNOTATION_EXPORT_BUCKET = (os.getenv("ANNOTATION_EXPORT_BUCKET") or "").strip() or None
    ANNOTATION_EXPORT_PREFIX = (os.getenv("ANNOTATION_EXPORT_PREFIX") or "annotation-events").strip() or "annotation-events"
    # STRESS_BASELINE_MODEL_PATH / STRESS_MODEL_TRAIN_SECRET / STRESS_MODEL_BUCKET
    # are GONE (founder 2026-08-03, stress-lane deletion). The first was a
    # local-file-path model ref — on Railway that path is dyno-ephemeral and
    # dies at the next deploy; the other two configured the in-request trainer
    # and its artifact bucket. Nothing loads a stress model any more: clip
    # selection runs on heuristic suspicion scoring, permanently.


    # Reference video → Whisper: extract compact mono MP3 via ffmpeg before transcription
    # for video/common containers (and large inputs), to stay under OpenAI ~25MB request limit.
    FFMPEG_PATH = (os.getenv("FFMPEG_PATH") or "ffmpeg").strip() or "ffmpeg"
    REFERENCE_VIDEO_FFMPEG_EXTRACT = (os.getenv("REFERENCE_VIDEO_FFMPEG_EXTRACT", "true").strip().lower() == "true")
    # MediaRecorder WebM carries no Cues and no Duration, so Safari cannot
    # seek a clip inside its parent Take. On upload, BEFORE storage and
    # analysis, a lossless remux (`-c copy -copyts`) adds both and keeps every
    # packet timestamp; any failure, timeout or timestamp difference keeps the
    # original bytes (services/webm_remux.py). A code constant, not an env var:
    # set False here to turn it off.
    WEBM_REMUX_ON_UPLOAD = True
    WEBM_REMUX_TIMEOUT_SEC = 8
    # Safari (iPhone and Mac) does not play the WebM/Opus recordings reliably
    # (founder 2026-10-10: Pause shown, nothing heard). Beside each spoken
    # recording an AAC/MP4 playback copy is kept, made in the background
    # after upload or on the first play, and players are handed it once it
    # exists; the original stays the record (services/playback_copy.py).
    PLAYBACK_COPY_ENABLED = True


    # willab Prompt D — the audit is REPLACED by the Best-Presentation. Default
    # OFF retires the audit chat surface (the "audit" suggested_action button);
    # the endpoints/tables stay DORMANT (recoverable — flip ON to restore).
    AUDIT_SURFACE_ENABLED = (os.getenv("AUDIT_SURFACE_ENABLED") or "false").strip().lower() == "true"

    # ── The AI version of your voice (founder lock 2026-10-12, N71) ──────
    # docs/FOUNDER-LOCK-ai-voice-practice-2026-10-12.md; docs/AI-VOICE-PRACTICE.md.
    # ALWAYS ON for every speaker (founder 2026-10-12): it works whenever
    # ELEVENLABS_API_KEY is set, and does nothing without it. No switch to
    # set. AI_VOICE_ENABLED=0 exists only as an emergency off.
    # AI_VOICE_ALLOWLIST (user ids), when set, narrows it; empty = everyone.
    ELEVENLABS_API_KEY = _secret("ELEVENLABS_API_KEY") or ""
    ELEVENLABS_MODEL_ID = (os.getenv("ELEVENLABS_MODEL_ID") or "eleven_v4").strip()
    ELEVENLABS_API_BASE = (os.getenv("ELEVENLABS_API_BASE")
                           or "https://api.elevenlabs.io").strip().rstrip("/")
    ELEVENLABS_TIMEOUT_SECONDS = _env_int("ELEVENLABS_TIMEOUT_SECONDS", 30)
    AI_VOICE_ENABLED = _env_not_off("AI_VOICE_ENABLED")
    AI_VOICE_ALLOWLIST = frozenset(
        part.strip() for part in (os.getenv("AI_VOICE_ALLOWLIST") or "").split(",")
        if part.strip())
    # The plan's month (Starter: 40,000 credits). The app warns at the first
    # and stops making clips at the second; the plan itself caps the third.
    AI_VOICE_MONTHLY_CREDITS = _env_int("AI_VOICE_MONTHLY_CREDITS", 40000)
    AI_VOICE_WARN_CREDITS = _env_int("AI_VOICE_WARN_CREDITS", 28000)
    AI_VOICE_STOP_CREDITS = _env_int("AI_VOICE_STOP_CREDITS", 38000)
    # Credits per generated character, an estimate until the smoke test
    # reads the provider's real cost header; never a promotional price.
    AI_VOICE_CREDITS_PER_CHARACTER = _env_float("AI_VOICE_CREDITS_PER_CHARACTER", 1.0)
    AI_VOICE_USD_PER_1000_CREDITS = _env_float("AI_VOICE_USD_PER_1000_CREDITS", 0.0)
    # Founder 2026-10-26 (N188): 3 a day and 20 a month for each speaker,
    # so no one speaker uses up the plan's month. It was 10 a day with no
    # monthly limit (founder 2026-10-15). The month is the calendar month.
    AI_VOICE_DAILY_CLIPS_PER_SPEAKER = _env_int("AI_VOICE_DAILY_CLIPS_PER_SPEAKER", 3)
    AI_VOICE_MONTHLY_CLIPS_PER_SPEAKER = _env_int("AI_VOICE_MONTHLY_CLIPS_PER_SPEAKER", 20)
    AI_VOICE_DAILY_CLIPS_TOTAL = _env_int("AI_VOICE_DAILY_CLIPS_TOTAL", 30)
    AI_VOICE_DAILY_CLONES_TOTAL = _env_int("AI_VOICE_DAILY_CLONES_TOTAL", 3)
    # The plan's voice slots (Starter: 10; N188). Each speaker's AI voice
    # holds one; no new voice is made while they are full.
    AI_VOICE_VOICE_SLOTS = _env_int("AI_VOICE_VOICE_SLOTS", 10)
    AI_VOICE_MAX_SENTENCE_CHARACTERS = _env_int("AI_VOICE_MAX_SENTENCE_CHARACTERS", 600)
    # Founder 2026-10-13: the whole sentence, and no AI clip longer than 17
    # seconds. A sentence too long to say slowly in that time is never sent;
    # a longer clip fails its check and is never shown. (The smoke script
    # runs at 12 s.)
    AI_VOICE_MAX_CLIP_SECONDS = _env_float("AI_VOICE_MAX_CLIP_SECONDS", 17.0)
    AI_VOICE_MAX_PRACTICE_SECONDS = _env_int("AI_VOICE_MAX_PRACTICE_SECONDS", 45)
    # Founder 2026-10-15: half the line, so a clip is made for a moment that
    # only leans towards a problem; 0.4 was the line itself.
    AI_VOICE_MIN_SEVERITY = _env_float("AI_VOICE_MIN_SEVERITY", 0.2)
    # The normalization ranges each severity is read on (services/
    # ai_voice_severity.py): where 0.4 is reached, in the problem's own unit,
    # against the speaker's own usual. Tuning them is a config change.
    AI_VOICE_PACE_LINE_NO_MEDIAN = _env_float("AI_VOICE_PACE_LINE_NO_MEDIAN", 175.0)
    AI_VOICE_PACE_COMFORT_NO_MEDIAN = _env_float("AI_VOICE_PACE_COMFORT_NO_MEDIAN", 155.0)
    AI_VOICE_PACE_OVER_MEDIAN_WPM = _env_float("AI_VOICE_PACE_OVER_MEDIAN_WPM", 18.0)
    AI_VOICE_PACE_OVER_MEDIAN_RATIO = _env_float("AI_VOICE_PACE_OVER_MEDIAN_RATIO", 1.12)
    AI_VOICE_PAUSE_FLOOR_RATIO = _env_float("AI_VOICE_PAUSE_FLOOR_RATIO", 0.08)
    AI_VOICE_PAUSE_GAP_RATIO = _env_float("AI_VOICE_PAUSE_GAP_RATIO", 0.06)
    AI_VOICE_STRESS_GAP_DB = _env_float("AI_VOICE_STRESS_GAP_DB", 4.0)
    # Fillers (founder 2026-10-18): hesitations per 100 words above the
    # speaker's own usual at which the fillers exercise reaches the line.
    AI_VOICE_FILLER_GAP_PER_100 = _env_float("AI_VOICE_FILLER_GAP_PER_100", 5.0)
    # The share of picks that take the runner-up problem, so the stored
    # cycles can later tell which exercise helps (never a trained model now).
    AI_VOICE_EXPLORE_SHARE = _env_float("AI_VOICE_EXPLORE_SHARE", 0.15)
    # Founder 2026-10-21 (N93): a clip that fails its check is made once more
    # with a new seed, never a third time; until then it was one generation
    # (2026-10-12). The stress clip of 2026-10-20 came out flat (0.02 dB of
    # contrast; the two that passed had about 2.4). 0 turns it back off.
    # (A provider refusal that made nothing, a 429 or a 5xx, is asked once
    # more anyway: it uses no credits.)
    AI_VOICE_GENERATION_RETRIES = _env_int("AI_VOICE_GENERATION_RETRIES", 1)

    @property
    def is_production(self):
        return self.ENV == "production"

    @property
    def is_staging(self):
        """A prod-shaped deploy that is NOT prod (docs/OPS-SECRETS-AND-STAGING.md).

        Deliberately separate from ``is_production``: staging must keep
        every production-only safety OFF (no live Stripe, no real user
        email) while still exercising the production code paths. Anything
        that asks "am I allowed to touch the real world?" checks
        ``is_production``; anything that asks "am I the rehearsal?" checks
        this.
        """
        return self.ENV == "staging"
