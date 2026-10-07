from supabase import create_client, Client
from config import Config
from typing import Any, Dict, List, Optional, Tuple, Callable
from datetime import datetime, timedelta, timezone
import json
import logging
import os
import re
import time

import sentry_sdk
from services.snippet_tables import SNIPPETS_TABLE
from services.take_repository import TakeHasLineageError

config = Config()
logger = logging.getLogger(__name__)


# Volatile stamps stripped from Say-It-Stronger cards before they are compared
# and serialized as annotation-event text: model/generated_at ride only the
# auto draft, edited_by_coach rides only the final, and version can differ
# between them — none is content, and any one of them would turn a genuinely
# untouched card into false "corrected" signal.
_SIS_VOLATILE_KEYS = ("model", "generated_at", "version", "edited_by_coach")


def _sis_annotation_text(card: Any) -> Optional[str]:
    """A Say-It-Stronger card as canonical annotation-event text.

    Deterministic (sorted keys) so that draft-vs-final equality — and
    therefore the approved_as_is chip — compares CONTENT, not dict ordering
    or the volatile stamps. None for anything that isn't a dict with content.
    """
    if not isinstance(card, dict):
        return None
    slim = {k: v for k, v in card.items() if k not in _SIS_VOLATILE_KEYS}
    if not slim:
        return None
    try:
        return json.dumps(slim, ensure_ascii=False, sort_keys=True)
    except (TypeError, ValueError):
        return None


def _session_preview_row(
    session: dict, session_fields: tuple,
    recordings_by_id: dict, sniper_metrics_by_session: dict,
) -> dict:
    """Normalize one admin-session preview from already-batched data."""
    rec = {key: value for key, value in session.items()
           if key in session_fields}
    recording_id = session.get("recording_id")
    rec["recording_id"] = recording_id
    rec["recording_preview"] = None
    rec["report_preview"] = None

    if recording_id and recording_id in recordings_by_id:
        row = recordings_by_id[recording_id]
        raw_duration_ms = row.get("duration_ms")
        if raw_duration_ms is None and row.get("duration") is not None:
            try:
                raw_duration_ms = int(float(row.get("duration")) * 1000.0)
            except (TypeError, ValueError):
                raw_duration_ms = None
        rec["recording_preview"] = {
            "performance_score_v2": row.get("performance_score_v2"),
            "transcription_preview": (row.get("transcription_text") or "")[:300],
            "words_per_minute": row.get("words_per_minute"),
            "filler_words_count": row.get("filler_words_count"),
            "performance_metrics_v2": row.get("performance_metrics_v2"),
            "duration_ms": raw_duration_ms,
        }

    rec["sniper_metrics"] = sniper_metrics_by_session.get(session["id"])
    recording_wpm = (rec.get("recording_preview") or {}).get(
        "words_per_minute")
    sniper_wpm = None
    if isinstance(rec.get("sniper_metrics"), dict):
        sniper_wpm = rec["sniper_metrics"].get("wpm")
    merged_wpm = None
    if sniper_wpm is not None:
        try:
            merged_wpm = round(float(sniper_wpm), 1)
        except (TypeError, ValueError):
            pass
    if merged_wpm is None and recording_wpm is not None:
        try:
            merged_wpm = round(float(recording_wpm), 1)
        except (TypeError, ValueError):
            pass
    rec["words_per_minute"] = merged_wpm
    if isinstance(rec.get("sniper_metrics"), dict) \
            and rec["sniper_metrics"].get("wpm") is None \
            and merged_wpm is not None:
        rec["sniper_metrics"] = {**rec["sniper_metrics"], "wpm": merged_wpm}

    rec["wpm"] = merged_wpm
    filler_obj = (rec.get("recording_preview") or {}).get(
        "filler_words_count")
    if isinstance(filler_obj, dict):
        filler_total = filler_obj.get("total")
    elif isinstance(filler_obj, (int, float)):
        filler_total = filler_obj
    else:
        filler_total = None
    rec["filler_words_count"] = filler_total

    rec["duration_seconds"] = None
    duration_ms = (rec.get("recording_preview") or {}).get("duration_ms")
    if duration_ms is not None:
        try:
            rec["duration_seconds"] = round(float(duration_ms) / 1000.0, 1)
        except (TypeError, ValueError):
            pass

    sniper = rec.get("sniper_metrics") \
        if isinstance(rec.get("sniper_metrics"), dict) else {}
    rec["pause_ms"] = sniper.get("pause_ms")
    rec["dynamic_db"] = sniper.get("dynamic_db")
    rec["pitch_center_st"] = sniper.get("pitch_center_st")
    rec["energy_ratio"] = sniper.get("energy_ratio")
    student_rating = sniper.get("student_rating_1_10")
    if student_rating is None and session.get("student_self_rating") is not None:
        try:
            student_rating = int(session["student_self_rating"])
        except (TypeError, ValueError):
            student_rating = sniper.get("student_rating_1_10")
    rec["student_rating_1_10"] = student_rating
    rec["self_rating"] = student_rating
    submitted_at = session.get("self_rating_submitted_at")
    rec["self_rating_skipped"] = bool(submitted_at) and student_rating is None
    if student_rating is not None:
        try:
            rec["self_rating_label"] = str(int(student_rating))
        except (TypeError, ValueError):
            rec["self_rating_label"] = str(student_rating)
    elif rec["self_rating_skipped"]:
        rec["self_rating_label"] = "Skipped"
    else:
        rec["self_rating_label"] = None
    return rec


def _sessions_with_schema_fallback(
    database, user_id: str, limit: int, all_columns: list,
) -> tuple[list, tuple]:
    """Query session rows while learning columns absent on older schemas."""
    result = None
    columns = [column for column in all_columns
               if column not in database._v2_sessions_missing_columns]
    session_fields = tuple(columns)
    for _ in range(max(1, len(all_columns))):
        if not columns:
            raise Exception(
                "v2_get_sessions_with_previews: no selectable "
                "v2_sessions columns available")
        session_fields = tuple(columns)
        try:
            result = (
                database.client.table("v2_sessions")
                .select(", ".join(columns))
                .eq("user_id", user_id)
                .order("completed_at", desc=True)
                .limit(limit)
                .execute()
            )
            break
        except Exception as error:
            message = str(error).lower()
            missing_error = (
                "42703" in message or "does not exist" in message
                or "undefined_column" in message
            )
            if not missing_error:
                raise
            missing = [column for column in all_columns
                       if f"v2_sessions.{column}" in message
                       or f"column {column}" in message]
            if not missing:
                match = re.search(
                    r"column\s+v2_sessions\.([a-z0-9_]+)\s+does not exist",
                    message,
                )
                if match:
                    missing = [match.group(1)]
            if not missing:
                raise
            newly_missing = [column for column in missing
                             if column not in database._v2_sessions_missing_columns]
            database._v2_sessions_missing_columns.update(missing)
            if newly_missing:
                logger.warning(
                    "v2_get_sessions_with_previews: columns missing %s, "
                    "retrying without them: %s", newly_missing, error,
                )
            columns = [column for column in all_columns
                       if column not in database._v2_sessions_missing_columns]
    if result is None:
        raise Exception(
            "v2_get_sessions_with_previews: failed to query sessions after "
            "schema fallback retries")
    return result.data or [], session_fields


# Codes that genuinely mean "the object is not there", and nothing else.
#
#   42P01 undefined_table        42703 undefined_column
#   42883 undefined_function     42P10 is NOT here on purpose: an invalid
#                                column reference / bad ON CONFLICT arbiter
#                                means the object EXISTS and the statement is
#                                wrong, which is a different fix entirely.
#   PGRST205 table not found in the schema cache
#   PGRST204 column not found in the schema cache
#   PGRST202 function not found in the schema cache
#
# The three PGRST codes are cache misses, not absences — the object can be
# perfectly present and the API still cannot see it until
# `NOTIFY pgrst, 'reload schema'`. They belong here because the CALLER's next
# move is the same (make the object visible), but the hint must say so.
_MISSING_OBJECT_CODES = frozenset({
    "42P01", "42703", "42883", "PGRST205", "PGRST204", "PGRST202",
})

_PG_CODE_RE = re.compile(r"\b(PGRST\d{3}|[0-9A-Z]{5})\b")


def _pg_error_code(exc: Any) -> str:
    """The Postgres SQLSTATE or PostgREST code on an exception, or "".

    Supabase raises APIError with a `code` attribute; psycopg2 uses `pgcode`;
    everything else has to be read out of the message. Pure, and never raises
    — an error path that can itself fail is worse than no error path.

    WHY THIS EXISTS: a best-effort writer swallows its failures, so the log
    line is the only account of why a table stopped filling. Matching on
    prose ("does not exist", or worse, the table's own name) turns every
    distinct failure into one wrong sentence — see the 2026-08-12 note in
    record_dimension_evaluations.
    """
    for attr in ("code", "pgcode"):
        v = getattr(exc, attr, None)
        if isinstance(v, str) and v.strip():
            return v.strip()
    try:
        m = _PG_CODE_RE.search(str(exc))
    except Exception:      # pragma: no cover - defensive
        return ""
    return m.group(1) if m else ""


def _free_credit_grant() -> int:
    """The upfront free credit grant (config.WILLAB_FREE_CREDIT_GRANT, 25 for
    the testing phase, env-tunable). Single source of truth for both the lazy
    seed AND every "unseeded user" balance fallback, so they can never drift
    apart (a mismatch would wrongly tell a new user 'insufficient')."""
    try:
        from config import Config
        return int(getattr(Config, "WILLAB_FREE_CREDIT_GRANT", 25) or 25)
    except Exception:
        return 25


def _freezable_selection(selected_keys: Any) -> bool:
    """The shape `claim_ideal_text_feedback_set_v1` accepts, checked here too.

    One to sixty-four identities, at least one of them Confident Voice. Not
    a budget: V2 froze exactly three, V3 freezes one per valid block plus
    its anchored items (24f), and the Manager decides which. A guard that
    re-litigates the budget is a second arbiter, and a silent one.
    """
    from services.take_feedback_set import MAX_SELECTED_KEYS
    if not isinstance(selected_keys, list):
        return False
    if not 1 <= len(selected_keys) <= MAX_SELECTED_KEYS:
        return False
    return any(
        isinstance(key, dict)
        and str(key.get("feedback_family")) == "confident_voice"
        for key in selected_keys
    )



def _carried_root(previous: Optional[dict], text: str) -> dict:
    """The helper-word columns a rewritten part keeps (contract 14).

    The phrase and its selection time carry across any change to the words.
    The span is kept while it still proves the same words, re-found when the
    words occur exactly once in the new text, and otherwise cleared — the
    `ideal_text_part_root_span` CHECK allows a phrase without a span since
    migrations/helper_words_are_their_own_text.sql."""
    from services.ideal_text_parts import root_span_in

    prev = previous or {}
    phrase = prev.get("root_phrase")
    if not isinstance(phrase, str) or not phrase:
        return {"root_phrase": None, "root_start": None, "root_end": None,
                "root_selected_at": None}
    span = root_span_in(text, phrase, prev.get("root_start"),
                        prev.get("root_end"))
    return {
        "root_phrase": phrase,
        "root_start": span[0] if span else None,
        "root_end": span[1] if span else None,
        "root_selected_at": prev.get("root_selected_at"),
    }


#: K9 (decisions log K9; W6 2026-10-05): why a clip was in front of the
#: rater, stamped on the rating server-side and never shown before it.
SELECTION_COLUMNS = ("selection_policy_version", "selection_reason",
                     "sampling_probability")


def _selection_columns(selection: Any) -> dict:
    """The K9 stamps from a stamp dict, only those set; a probability
    outside (0, 1] is dropped, never coerced (the column's CHECK)."""
    if not isinstance(selection, dict):
        return {}
    out: dict = {}
    for key in ("selection_policy_version", "selection_reason"):
        value = selection.get(key)
        if isinstance(value, str) and value.strip():
            out[key] = value.strip()
    p = selection.get("sampling_probability")
    if isinstance(p, (int, float)) and not isinstance(p, bool) and 0 < float(p) <= 1:
        out["sampling_probability"] = float(p)
    return out


class IdealTextCoreReadError(RuntimeError):
    """The cold-open Ideal Text read FAILED, as opposed to finding nothing.

    Founder 2026-09-26, from real use: a dropped database connection
    ("Server disconnected") made the core read return ``None``, the route
    answered ``404 IDEAL_TEXT_DOCUMENT_PENDING``, and the client showed a
    project that has an Ideal Text a screen saying it did not have one yet.
    "Could not read it" and "there is none" must never share an answer.
    """

class DatabaseService:
    def __init__(self):
        self.client: Client = self._build_supabase_client()
        # The F1 table access lives in repository modules that take THIS
        # service and read its client through a property, so a rebuilt
        # client (reset_connections) is seen everywhere. The methods below
        # that read `return self.<repo>.<name>(...)` are delegates kept so
        # every caller and every `patch.object(db, "<name>")` site is
        # unchanged (audit Q-A1 step 2 / Q-A2). Imported here, not at module
        # top, because the repositories never import this module.
        # (the repositories are lazy properties below, so an instance built
        # without __init__ — the test suites do that — still delegates)
        # Cache missing optional columns discovered at runtime on older schemas.
        self._v2_sessions_missing_columns: set[str] = set()
        self._student_profile_table = "student_profile"
        self._legacy_student_profile_table = "user_sniper_profile"

    # ── F1 repositories (audit Q-A1 step 2 / Q-A2) ──────────────────────
    # Lazy, cached on the instance's own dict, imported on first use: the
    # repositories never import this module, and an instance created without
    # __init__ (several suites build one with __new__ or a bare subclass)
    # still reaches them.
    @property
    def recordings(self):
        repo = self.__dict__.get("_recordings_repo")
        if repo is None:
            from services.recording_repository import RecordingRepository
            repo = self.__dict__["_recordings_repo"] = RecordingRepository(self)
        return repo

    @property
    def takes(self):
        repo = self.__dict__.get("_takes_repo")
        if repo is None:
            from services.take_repository import TakeRepository
            repo = self.__dict__["_takes_repo"] = TakeRepository(self)
        return repo

    @property
    def ideal_text(self):
        repo = self.__dict__.get("_ideal_text_repo")
        if repo is None:
            from services.ideal_text_repository import IdealTextRepository
            repo = self.__dict__["_ideal_text_repo"] = IdealTextRepository(self)
        return repo

    def reset_connections(self) -> None:
        """Rebuild the client. MUST be called in a freshly forked child.

        `db = DatabaseService()` runs at IMPORT, so the TLS connection to
        Supabase is established in the parent — worker.py's `_warm_analysis_
        stack()` and its boot sweep both touch the DB before forking. A
        `fork` context then hands that one live socket to every slot, and two
        processes writing into a single TLS session produce exactly what the
        worker logs showed:

            [SSL: SSLV3_ALERT_BAD_RECORD_MAC] sslv3 alert bad record mac
            EOF occurred in violation of protocol
            Server disconnected

        Those are caught and logged as warnings, so the reads simply return
        nothing and the sweep quietly does no work — the same silent-failure
        shape as the telemetry writes. `job_queue.reset_connections()` already
        handles this for Redis and says why; the httpx/TLS half was missed.
        """
        self.client = self._build_supabase_client()

    def _build_supabase_client(self) -> Client:
        """Create the Supabase client.

        Earlier this method tried to force HTTP/1.1 transport via a
        custom httpx.Client passed through ClientOptions(http_client=…)
        — supabase-py 2.7.0+ accepts that kwarg, our pin is 2.6.0, so
        every boot raised TypeError and we fell through to the
        default client anyway. The noisy warning ("ClientOptions
        unexpected keyword argument 'http_client'") was the
        fallback firing on each worker boot — not an actual error.

        Application-level retry in ``_execute_with_retry`` /
        ``_is_transient_postgrest_disconnect`` already handles the
        transient HTTP/2 disconnects that motivated the HTTP/1.1
        transport tweak, so we drop the dead code and let the default
        transport do its thing.
        """
        return create_client(
            config.SUPABASE_URL,
            config.SUPABASE_SERVICE_ROLE_KEY,
        )

    def _is_transient_postgrest_disconnect(self, err: Exception) -> bool:
        msg = str(err).lower()
        if "remoteprotocolerror" in msg and "server disconnected" in msg:
            return True
        if "server disconnected" in msg:
            return True
        if "connection reset by peer" in msg:
            return True
        if "http2" in msg and "disconnected" in msg:
            return True
        return False

    def _execute_with_retry(self, query_factory: Callable[[], Any], *, label: str, max_attempts: int = 3):
        """Execute a PostgREST query with reconnect + backoff on transient transport drops."""
        attempt = 1
        while True:
            try:
                query = query_factory()
                return query.execute()
            except Exception as e:
                if attempt >= max_attempts or not self._is_transient_postgrest_disconnect(e):
                    raise
                sleep_s = 0.2 * (2 ** (attempt - 1))
                logger.warning(
                    "%s transient DB disconnect (attempt %s/%s): %s; retrying in %.1fs",
                    label,
                    attempt,
                    max_attempts,
                    e,
                    sleep_s,
                )
                # Recreate client to avoid reusing a broken pooled connection/session.
                try:
                    self.client = self._build_supabase_client()
                except Exception:
                    pass
                time.sleep(sleep_s)
                attempt += 1

    def _is_relation_missing_error(self, err: Exception) -> bool:
        msg = str(err).lower()
        return ("42p01" in msg) or ("does not exist" in msg) or ("undefined_table" in msg)

    def set_recording_transcription_language_if_missing(
        self,
        recording_id: str,
        language: str,
    ) -> Optional[str]:
        """Freeze one recording language without overwriting prior evidence.

        The conditional update is the concurrency boundary. Exact retries are
        idempotent; competing values preserve and return the committed winner
        so callers can fail closed instead of silently relabelling audio.
        """
        if not recording_id or not language:
            return None
        try:
            from services.rater_languages import normalize_provider_language

            result = (
                self.client.table("recordings")
                .update({"transcription_language": language})
                .eq("id", recording_id)
                .is_("transcription_language", "null")
                .execute()
            )
            if result.data:
                return normalize_provider_language(
                    result.data[0].get("transcription_language")
                )
            current = self.get_recording(recording_id)
            value = current.get("transcription_language") if current else None
            return normalize_provider_language(value)
        except Exception as error:
            logger.warning(
                "set_recording_transcription_language_if_missing failed "
                "recording_id=%s err=%s",
                recording_id,
                error,
            )
            return None
    
    def get_recording(self, recording_id: str, user_id: str = None):
        """Get a recording by ID, optionally verifying ownership"""
        def _query():
            query = self.client.table("recordings").select("*").eq("id", recording_id)
            if user_id:
                query = query.eq("user_id", user_id)
            return query

        result = self._execute_with_retry(_query, label="get_recording")
        
        return result.data[0] if result.data else None

    def get_user_admin_context(self, user_id: str):
        """Return admin context for report generation. V2: no professional_notes tables; minimal dict.

        Note: the legacy V1 admin-instructions field (tied to the
        deleted professional_notes_report_tech table) was removed
        from this stub when the FE killed its corresponding surface
        in commit ed9ed70. The downstream prompt branch in
        services.openai_service was always reading None here, so
        the branch was dead code; both ends were dropped together.
        """
        return {
            "general_notes": None,
            "max_words": 120,
            "specific_questions": [],
        }
    
    def create_signed_url(self, bucket: str, path: str, expires_in: int = 3600):
        """Create a signed URL for a file in Supabase Storage"""
        import logging
        logger = logging.getLogger(__name__)
        
        try:
            # Supabase Python client create_signed_url returns a response object
            response = self.client.storage.from_(bucket).create_signed_url(
                path, expires_in
            )
            
            logger.debug("create_signed_url bucket=%s path=%s response_type=%s", bucket, path, type(response).__name__)

            signed_url = None

            if isinstance(response, dict):
                signed_url = response.get("signedUrl") or response.get("signedURL") or response.get("signed_url") or response.get("url")
            # Try accessing .data attribute if it exists
            elif hasattr(response, 'data'):
                data = response.data
                if isinstance(data, dict):
                    signed_url = data.get("signedUrl") or data.get("signedURL") or data.get("signed_url") or data.get("url")
                elif isinstance(data, str):
                    signed_url = data
            # Try string
            elif isinstance(response, str):
                signed_url = response
            # Try object attributes
            else:
                signed_url = getattr(response, "signedUrl", None) or getattr(response, "signedURL", None) or getattr(response, "signed_url", None) or getattr(response, "url", None)
            
            if not signed_url:
                logger.warning("Could not extract signed URL for %s/%s (response_type=%s)", bucket, path, type(response).__name__)
                raise Exception(f"Could not extract signed URL for {bucket}/{path}")

            if not signed_url.startswith("http"):
                raise Exception(f"Signed URL for {bucket}/{path} is not a full URL")

            logger.debug("Signed URL created for %s/%s (expires_in=%s)", bucket, path, expires_in)
            return signed_url
        except Exception as e:
            logger.error("Error creating signed URL for %s/%s: %s", bucket, path, type(e).__name__)
            sentry_sdk.capture_exception(e)
            raise Exception(f"Failed to create signed URL for {bucket}/{path}")

    def _absolute_signed_upload_url(self, raw: str | None) -> str | None:
        """Storage may return a host-relative path; browsers must PUT the full Supabase URL or the app origin gets 404."""
        if not raw or not isinstance(raw, str):
            return None
        s = raw.strip()
        if not s:
            return None
        if s.startswith("http://") or s.startswith("https://"):
            return s
        base = (config.SUPABASE_URL or "").rstrip("/")
        if not base:
            return None
        storage_root = f"{base}/storage/v1"
        if s.startswith("/storage/v1/"):
            return f"{base}{s}"
        if s.startswith("storage/v1/"):
            return f"{base}/{s}"
        if s.startswith("/object/"):
            return f"{storage_root}{s}"
        if s.startswith("object/"):
            return f"{storage_root}/{s}"
        return f"{storage_root}/{s.lstrip('/')}"

    def create_signed_upload_url(self, bucket: str, path: str) -> Optional[Dict[str, str]]:
        """Mint a signed upload URL for browser uploads.

        Returns ``{"signed_url": "<https...>", "token": "<jwt>"}`` or None.
        Supabase Storage expects the upload as **multipart** PUT (same as
        ``@supabase/storage-js`` ``uploadToSignedUrl``). A raw binary PUT
        typically returns **404** (route not matched for that content type).
        """
        from urllib.parse import parse_qs, urlparse

        path_clean = path.lstrip("/")
        sign_segment = f"{bucket}/{path_clean}"

        def _finalize(raw_url: Optional[str], token: Optional[str] = None) -> Optional[Dict[str, str]]:
            signed = self._absolute_signed_upload_url(raw_url) if raw_url else None
            if not signed:
                return None
            if not token:
                vals = parse_qs(urlparse(signed).query).get("token") or []
                token = vals[0] if vals else None
            out: Dict[str, str] = {"signed_url": signed}
            if token:
                out["token"] = token
            return out

        def _from_sdk_result(result: Any) -> Optional[Dict[str, str]]:
            if result is None:
                return None
            if isinstance(result, dict):
                u = (
                    result.get("signedUrl")
                    or result.get("signed_url")
                    or result.get("signedURL")
                    or result.get("url")
                )
                tok = result.get("token")
                tok_s = tok if isinstance(tok, str) else None
                if isinstance(u, str):
                    return _finalize(u, tok_s)
                return None
            for attr in ("signed_url", "signedUrl", "signedURL", "url"):
                u = getattr(result, attr, None)
                if isinstance(u, str):
                    return _finalize(u)
            return None

        try:
            bucket_api = self.client.storage.from_(bucket)
            create_upload = getattr(bucket_api, "create_signed_upload_url", None)
            if callable(create_upload):
                result = create_upload(path_clean)
                normalized = _from_sdk_result(result)
                if normalized:
                    return normalized
        except Exception as e:
            logger.debug("create_signed_upload_url SDK path failed: %s", e)

        try:
            import httpx

            base = (config.SUPABASE_URL or "").rstrip("/")
            key = config.SUPABASE_SERVICE_ROLE_KEY or ""
            if not base or not key:
                return None
            # Match storage-js/storage-py: POST .../object/upload/sign/{bucketId}/{objectPath} (no JSON body).
            resp = httpx.post(
                f"{base}/storage/v1/object/upload/sign/{sign_segment}",
                headers={"Authorization": f"Bearer {key}", "apikey": key},
                timeout=10.0,
            )
            if resp.status_code != 200:
                logger.warning(
                    "create_signed_upload_url POST sign failed status=%s body=%s",
                    resp.status_code,
                    (resp.text or "")[:200],
                )
                return None
            data = resp.json()
            if not isinstance(data, dict):
                return None
            rel = data.get("url") or data.get("signedURL") or data.get("signedUrl") or data.get("signed_url")
            tok = data.get("token")
            tok_s = tok if isinstance(tok, str) else None
            return _finalize(rel if isinstance(rel, str) else None, tok_s)
        except Exception as e:
            logger.warning("create_signed_upload_url httpx path failed: %s", e)
            return None

    def upload_audio(self, bucket: str, path: str, file_data: bytes, content_type: str = "audio/webm"):
        """Upload audio file to Supabase Storage"""
        import logging
        logger = logging.getLogger(__name__)
        
        try:
            # Ensure file_data is bytes
            if not isinstance(file_data, bytes):
                if isinstance(file_data, bool):
                    raise ValueError(f"file_data cannot be a boolean. Got: {type(file_data)}, value: {file_data}")
                file_data = bytes(file_data)
            
            # Ensure path is a string
            if not isinstance(path, str):
                if isinstance(path, bool):
                    raise ValueError(f"path cannot be a boolean. Got: {type(path)}, value: {path}")
                path = str(path)
            
            # Ensure bucket is a string
            if not isinstance(bucket, str):
                if isinstance(bucket, bool):
                    raise ValueError(f"bucket cannot be a boolean. Got: {type(bucket)}, value: {bucket}")
                bucket = str(bucket)
            
            # Ensure content_type is a string
            if not isinstance(content_type, str):
                if isinstance(content_type, bool):
                    raise ValueError(f"content_type cannot be a boolean. Got: {type(content_type)}, value: {content_type}")
                content_type = str(content_type) if content_type else "audio/webm"
            
            logger.debug("upload_audio bucket=%s path=%s size=%d content_type=%s", bucket, path, len(file_data), content_type)

            file_options = {"content-type": str(content_type)}

            result = self.client.storage.from_(bucket).upload(
                path=path,
                file=file_data,
                file_options=file_options
            )
            return result
        except Exception as e:
            logger.error("Upload failed for %s/%s: %s", bucket, path, type(e).__name__)
            sentry_sdk.capture_exception(e)
            raise Exception(f"Failed to upload to {bucket}/{path}: {e}") from e

    def download_audio(self, bucket: str, path: str) -> bytes:
        """Download audio file from Supabase Storage. Used when client uploads by URL (storage_path) and backend fetches for transcription."""
        import logging
        logger = logging.getLogger(__name__)
        try:
            if not isinstance(bucket, str) or not isinstance(path, str):
                raise ValueError("bucket and path must be strings")
            result = self.client.storage.from_(bucket).download(path)
            if isinstance(result, bytes):
                return result
            if hasattr(result, "content"):
                return result.content if isinstance(result.content, bytes) else bytes(result.content)
            if hasattr(result, "read"):
                data = result.read()
                return data if isinstance(data, bytes) else bytes(data)
            raise Exception(f"Unexpected download result type: {type(result)}")
        except Exception as e:
            logger.error("Download failed for %s/%s: %s", bucket, path, type(e).__name__)
            sentry_sdk.capture_exception(e)
            raise Exception(f"Failed to download from {bucket}/{path}: {e}") from e

    # --- v1 planned session flow ---
    def get_incomplete_sessions_older_than(self, days: float) -> List[dict]:
        """Return recording_sessions that are not completed and created_at is older than days (for cleanup)."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        result = self.client.table("recording_sessions")\
            .select("id, created_at, status")\
            .neq("status", "completed")\
            .lt("created_at", cutoff)\
            .execute()
        return result.data or []

    def cleanup_incomplete_sessions(self, days: float = 10, dry_run: bool = False) -> Tuple[int, List[str]]:
        """
        Delete incomplete sessions (and their recordings, pre/post answers, command options, exposures) older than days.
        Incomplete = not concluded with a report (status != 'completed').
        Returns (deleted_count, list of deleted session ids).
        For testing without waiting 10 days: use days=0.04 (≈1 hour) or days=0.001 (≈1.4 min) with dry_run=True first.
        """
        sessions = self.get_incomplete_sessions_older_than(days)
        ids = [s["id"] for s in sessions]
        if dry_run:
            return len(ids), ids
        if not ids:
            return 0, []
        deleted_ids = []
        for session_id in ids:
            try:
                # Delete recordings for this session first (CASCADE will remove performance_scores, post_recording_answers by recording_id)
                self.client.table("recordings").delete().eq("session_id", session_id).execute()
                # Delete session (CASCADE: pre_recording_answers, post_recording_answers, session_command_options, content_exposures)
                self.client.table("recording_sessions").delete().eq("id", session_id).execute()
                deleted_ids.append(session_id)
            except Exception as e:
                sentry_sdk.capture_exception(e)
        return len(deleted_ids), deleted_ids

    # ---------- V2 flow ----------
    def v2_get_student_overrides(self, user_id: str):
        """Overrides for user (tasks, prompts, metric/skip flags, pending tutor video)."""
        result = self.client.table("v2_student_overrides").select("*").eq("user_id", user_id).execute()
        rows = result.data or []
        for row in rows:
            if str(row.get("user_id") or "") == str(user_id):
                return row
        return None

    def v2_cleanup_incomplete_sessions(self, hours: float = 1.0, dry_run: bool = False) -> Tuple[int, List[str]]:
        """
        Delete incomplete v2_sessions (status != 'completed') older than hours.
        Uses v2_delete_session per row so recordings get session_v2_id set to NULL and v2_reports CASCADE.
        Returns (deleted_count, list of deleted session ids). Default 1 hour.
        """
        sessions = self.takes.v2_get_incomplete_sessions_older_than(hours)
        ids = [s["id"] for s in sessions]
        if dry_run:
            return len(ids), ids
        deleted_ids = []
        for s in sessions:
            session_id = s.get("id")
            user_id = s.get("user_id")
            if session_id and user_id:
                try:
                    if self.takes.v2_delete_session(session_id, user_id):
                        deleted_ids.append(session_id)
                except TakeHasLineageError:
                    # A canonical Take: the refusal changed nothing, and the
                    # governed purge owns it. Not an error to page on.
                    logger.info("cleanup: take has lineage, kept sid=%s", session_id)
                except Exception as e:
                    sentry_sdk.capture_exception(e)
        return len(deleted_ids), deleted_ids

    def claim_coach_review(
        self, session_id: str, actor_user_id: str, *, actor_is_admin: bool = False,
    ) -> Optional[dict]:
        """Atomically assign an owner-bound review to its first coach."""
        result = self.client.rpc("claim_coach_review_v1", {
            "p_session_id": str(session_id),
            "p_actor_user_id": str(actor_user_id),
            "p_actor_is_admin": bool(actor_is_admin),
        }).execute()
        data = result.data
        if isinstance(data, list):
            return data[0] if data else None
        return data if isinstance(data, dict) else None

    def get_coach_review_revision(self, revision_id: str) -> Optional[dict]:
        """One published coach-review revision (what the speaker was actually
        sent), or None. Best-effort."""
        if not revision_id:
            return None
        try:
            res = (self.client.table("coach_review_revisions")
                   .select("id,session_id,overall_message,published_at")
                   .eq("id", str(revision_id)).limit(1).execute())
            return (res.data or [None])[0]
        except Exception as e:
            logger.warning("get_coach_review_revision failed id=%s: %s",
                           revision_id, e)
            return None

    def refund_coach_review_credit(
        self, user_id: str, session_id: str,
    ) -> Optional[dict]:
        result = self.client.rpc("refund_coach_review_credit_v1", {
            "p_user_id": str(user_id),
            "p_session_id": str(session_id),
        }).execute()
        data = result.data
        if isinstance(data, list):
            return data[0] if data else None
        return data if isinstance(data, dict) else None

    def v2_get_session_by_id(self, session_id: str):
        """Get v2 session by id only (no user filter). For debugging 404: check if session exists and which user_id owns it."""
        return self.takes.v2_get_session(session_id, None)

    def v2_get_charisma_snippet_for_user(self, snippet_id: str, user_id: str) -> Optional[dict]:
        """Fetch a charisma_snippets row, scoped to the authenticated owner."""
        result = (
            self.client.table(SNIPPETS_TABLE)
            .select("*")
            .eq("id", snippet_id)
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None

    def v2_get_results_snippets_for_session(self, session_id: str, user_id: str) -> List[dict]:
        """Snippets for the /results page.

        Owner-scoped, non-skipped, AND require admin_comment to be
        populated. The /results page's whole point is delivering coach
        insight to the student — a snippet without a comment has
        nothing meaningful to render, so we hide it here rather than
        having the frontend skip-render it. Matches what
        get_snippets_with_comments_by_session already does for the
        with_admin_comment counter that powers session-state.
        """
        result = (
            self.client.table(SNIPPETS_TABLE)
            .select("*")
            .eq("session_id", session_id)
            .eq("user_id", user_id)
            .eq("is_skipped", False)
            .not_.is_("admin_comment", "null")
            .order("turn_number", desc=False)
            .order("start_offset_ms", desc=False)
            .execute()
        )
        rows = result.data or []
        # Belt-and-suspenders: whitespace-only admin_comment is treated
        # as no comment (PostgREST's NOT NULL filter doesn't catch this).
        return [r for r in rows if (r.get("admin_comment") or "").strip()]

    def v2_count_session_snippets(self, session_id: str) -> dict:
        """Count snippets for a session, split by review state.

        Returns:
            {
                "total": int,             # all non-skipped snippets
                "with_admin_comment": int # admin has reviewed and written feedback
            }

        The "with_admin_comment" count is what powers the pending_review →
        completed transition in the routing-status endpoint: a session has
        snippets ready to show only when at least one has admin_comment set.

        Implementation note: we fetch the rows and count in Python rather
        than using `select("id", count="exact")`. The supabase-py SDK
        version on the deployed runtime treats the count kwarg differently
        from what the docs suggest and threw
        "'SyncSelectRequestBuilder' object is not callable" on .execute().
        Volume here is tiny (snippets-per-session), so the cost of
        materialising the rows is negligible and the code is bulletproof
        across SDK versions.
        """
        try:
            result = (
                self.client.table(SNIPPETS_TABLE)
                .select("id, admin_comment, is_skipped")
                .eq("session_id", session_id)
                .execute()
            )
            rows = result.data or []
            non_skipped = [r for r in rows if not r.get("is_skipped")]
            total = len(non_skipped)
            with_comment = sum(
                1 for r in non_skipped if r.get("admin_comment")
            )
            return {"total": total, "with_admin_comment": with_comment}
        except Exception as e:
            logger.warning("v2_count_session_snippets failed: %s", e)
            return {"total": 0, "with_admin_comment": 0}

    # ------------------------------------------------------------------
    # Coaching sessions — micro-coaching loop on a single snippet
    # ------------------------------------------------------------------


    # ------------------------------------------------------------------
    # End coaching sessions
    # ------------------------------------------------------------------


    # ------------------------------------------------------------------
    # Charisma snippets
    # ------------------------------------------------------------------

    def v2_delete_lab_snippets_for_recording(self, recording_id: str) -> int:
        """willab re-cut (UX Wave 3 BE-6): delete the auto-cut Lab snippets for
        a recording so process_lab_recording can re-insert a fresh set. willab
        snippets are created via create_charisma_snippet with source_type NULL
        (snippet_type 'unlabeled'), so this targets EXACTLY those.

        THE `source_type IS NULL` FILTER STAYS EVEN THOUGH THE ML GENERATOR IS
        GONE (deleted 2026-08-10 with its paired cleanup,
        v2_delete_charisma_snippets_for_recording). Its rows — source_type
        'student' / 'internet' — are still IN the table; nothing was dropped.
        Widening this delete to "all rows for the recording" would destroy
        them, and would also start eating interview-turn and funnel rows that
        happen to share a recording_id. The filter is what keeps four
        producers' rows in one table from deleting each other.

        Coach authoring lives in coach_snippet_drafts; those rows are left
        as-is (orphaned by snippet_id, invisible to the new cut). Returns the
        delete count."""
        if not recording_id:
            return 0
        try:
            res = (
                self.client.table(SNIPPETS_TABLE)
                .delete()
                .eq("recording_id", recording_id)
                .is_("source_type", "null")
                .execute()
            )
            return len(res.data or [])
        except Exception as e:
            logger.warning(
                "v2_delete_lab_snippets_for_recording failed rec=%s err=%s",
                recording_id, e,
            )
            return 0

    def v2_insert_charisma_snippets(self, snippets: list[dict]) -> list[dict]:
        """Bulk insert charisma snippet candidates."""
        if not snippets:
            return []
        result = (
            self.client.table(SNIPPETS_TABLE)
            .insert(snippets)
            .execute()
        )
        return result.data or []

    def v2_get_charisma_snippet(self, snippet_id: str) -> Optional[dict]:
        """Return one charisma snippet row by id."""
        result = (
            self.client.table(SNIPPETS_TABLE)
            .select("*")
            .eq("id", snippet_id)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None


    # ---------- Sniper adaptive (user_sniper_profile, session_sniper_metrics) ----------

    # ---------- Homework tasks (per-student public.tasks; pool public.tasks_pool) ----------
    DEFAULT_STUDENT_TASK_TEXT = "Do you think you are a good communicator? Why?"
    TASK_TEMPLATE_ALLOWED_PROFILES = {
        "The Overwhelmed",
        "The Stressor",
        "The Drifter",
        "The Master",
    }
    TASK_TEMPLATE_DEFAULT_PROFILE = "The Overwhelmed"
    TASK_TEMPLATE_DEFAULT_LEVEL = 1
    TASK_TEMPLATE_DEFAULT_STEP = 1

    def v2_ensure_default_student_task(self, user_id: str) -> bool:
        """If user has no homework tasks, create the default one. Idempotent."""
        import logging
        log = logging.getLogger(__name__)
        tasks = self.v2_get_student_tasks(user_id)
        if tasks:
            return True
        data = {
            "user_id": user_id,
            "text": self.DEFAULT_STUDENT_TASK_TEXT,
            "order_index": 0,
            "max_performance_score": 1,
        }
        try:
            self.v2_insert_student_task(data)
            return True
        except Exception as e:
            log.warning("v2_ensure_default_student_task insert failed for user_id=%s: %s", user_id, e)
            return False

    def v2_apply_coach_homework_task_text(self, user_id: str, task_text: str | None) -> None:
        """After coach sends assignment, persist task text to public.tasks so session/start sees NO_TASK_CONFIGURED=false.

        Updates the student's first task by order_index; inserts one row if none exist.
        No-op if task_text is empty.
        """
        text = (task_text or "").strip()
        if not text:
            return
        text = text[:8000]
        try:
            rows = self.v2_get_student_tasks(user_id)
            if not rows:
                self.v2_insert_student_task(
                    {
                        "user_id": user_id,
                        "text": text,
                        "order_index": 0,
                        "max_performance_score": 1,
                    }
                )
                return
            first = rows[0]
            tid = first.get("id")
            if tid and (first.get("text") or "").strip() != text:
                self.v2_update_student_task(str(tid), {"text": text})
        except Exception as e:
            logger.warning("v2_apply_coach_homework_task_text failed user_id=%s: %s", user_id, e)

    def v2_get_student_tasks(self, user_id: str):
        result = (
            self.client.table("tasks")
            .select("*")
            .eq("user_id", user_id)
            .order("order_index")
            .order("created_at")
            .execute()
        )
        return result.data or []

    def v2_insert_student_task(self, data: dict):
        result = self.client.table("tasks").insert(data).execute()
        return result.data[0] if result.data else None

    def v2_update_student_task(self, task_id: str, data: dict):
        payload = {}
        if "text" in data:
            payload["text"] = data["text"]
        if "order_index" in data:
            payload["order_index"] = int(data["order_index"])
        if "max_performance_score" in data:
            try:
                payload["max_performance_score"] = float(data["max_performance_score"])
            except (TypeError, ValueError):
                payload["max_performance_score"] = 1.0
        if not payload:
            result = self.client.table("tasks").select("*").eq("id", task_id).execute()
            return result.data[0] if result.data else None
        result = self.client.table("tasks").update(payload).eq("id", task_id).execute()
        return result.data[0] if result.data else None

    def _normalize_task_template_fields(self, data: dict, *, partial: bool = False) -> dict:
        payload = {}
        if "target_profile" in data or not partial:
            raw_profile = data.get("target_profile", self.TASK_TEMPLATE_DEFAULT_PROFILE)
            profile = (raw_profile or "").strip()
            if profile not in self.TASK_TEMPLATE_ALLOWED_PROFILES:
                raise ValueError("INVALID_TARGET_PROFILE")
            payload["target_profile"] = profile
        if "level" in data or not partial:
            raw_level = data.get("level", self.TASK_TEMPLATE_DEFAULT_LEVEL)
            try:
                level = int(raw_level)
            except (TypeError, ValueError):
                raise ValueError("INVALID_LEVEL")
            if level < 1:
                raise ValueError("INVALID_LEVEL")
            payload["level"] = level
        if "step_in_level" in data or not partial:
            raw_step = data.get("step_in_level", self.TASK_TEMPLATE_DEFAULT_STEP)
            try:
                step = int(raw_step)
            except (TypeError, ValueError):
                raise ValueError("INVALID_STEP_IN_LEVEL")
            if step < 1 or step > 10:
                raise ValueError("INVALID_STEP_IN_LEVEL")
            payload["step_in_level"] = step
        if "is_active" in data or not partial:
            payload["is_active"] = bool(data.get("is_active", True))
        if "replaces_task_id" in data:
            payload["replaces_task_id"] = data.get("replaces_task_id") or None
        return payload

    def v2_get_task_pool_by_id(self, pool_id: str):
        result = self.client.table("tasks_pool").select("*").eq("id", pool_id).execute()
        return result.data[0] if result.data else None

    def v2_insert_task_pool(self, data: dict):
        data = dict(data)
        data.setdefault("order_index", 0)
        data.setdefault("max_performance_score", 1.0)
        data.setdefault("updated_at", datetime.now(timezone.utc).isoformat())
        data.update(self._normalize_task_template_fields(data, partial=False))
        result = self.client.table("tasks_pool").insert(data).execute()
        return result.data[0] if result.data else None

    def v2_delete_task_pool(self, pool_id: str, *, hard_delete: bool = False):
        if hard_delete:
            self.client.table("tasks_pool").delete().eq("id", pool_id).execute()
            return
        try:
            self.client.table("tasks_pool").update(
                {
                    "is_active": False,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
            ).eq("id", pool_id).execute()
            return
        except Exception:
            # Backward compatibility for old schema (no is_active).
            self.client.table("tasks_pool").delete().eq("id", pool_id).execute()

    def v2_sync_student_tasks_from_pool(self, user_id: str, pool_task_ids: list):
        """Replace student's tasks from tasks_pool ids (display order)."""
        self.client.table("tasks").delete().eq("user_id", user_id).execute()
        if not pool_task_ids:
            return []
        inserted = []
        for idx, pool_id in enumerate(pool_task_ids):
            row = self.v2_get_task_pool_by_id(pool_id)
            if not row:
                continue
            raw_score = row.get("max_performance_score", 1.0)
            try:
                score = round(float(raw_score), 2)
            except (TypeError, ValueError):
                score = 1.0
            data = {
                "user_id": user_id,
                "pool_task_id": pool_id,
                "text": row["text"],
                "order_index": int(idx),
                "max_performance_score": score,
            }
            new_row = self.v2_insert_student_task(data)
            if new_row:
                inserted.append(new_row)
        return inserted

    def v2_get_next_active_task_pool_template(
        self,
        *,
        target_profile: str,
        level: int,
        exclude_pool_task_ids: Optional[List[str]] = None,
        limit: int = 1,
        is_behavioral: Optional[bool] = None,
    ) -> List[dict]:
        """Deterministic template lookup: active rows ordered by step_in_level then creation.

        `is_behavioral` scopes the lookup to one partition of `tasks_pool`:
          * True  -> only the 12 canonical behavioral recommendation-engine tasks
          * False -> only legacy warm-up tasks
          * None  -> no filter (historical behavior; may return mixed rows)
        """
        q = (
            self.client.table("tasks_pool")
            .select("*")
            .eq("is_active", True)
            .eq("target_profile", target_profile)
            .eq("level", int(level))
        )
        if is_behavioral is not None:
            q = q.eq("is_behavioral", bool(is_behavioral))
        q = (
            q.order("step_in_level")
            .order("created_at")
            .limit(max(1, int(limit)))
        )
        result = q.execute()
        rows = result.data or []
        if exclude_pool_task_ids:
            excluded = {str(x) for x in exclude_pool_task_ids if x}
            rows = [r for r in rows if str(r.get("id")) not in excluded]
        return rows

    # ── Canonical owner / project compatibility repository ─────────────

    def get_owner_principal(self, principal_id: str) -> Optional[dict]:
        try:
            result = (self.client.table("owner_principals")
                      .select("*").eq("id", str(principal_id))
                      .limit(1).execute())
            return result.data[0] if result.data else None
        except Exception as e:
            logger.warning("get_owner_principal failed id=%s: %s",
                           principal_id, e)
            return None

    def get_owner_principal_for_user(self, user_id: str) -> Optional[dict]:
        try:
            result = (self.client.table("owner_principals")
                      .select("*").eq("user_id", str(user_id))
                      .limit(1).execute())
            return result.data[0] if result.data else None
        except Exception as e:
            logger.warning("get_owner_principal_for_user failed user=%s: %s",
                           user_id, e)
            return None

    def create_user_owner_principal(self, user_id: str) -> Optional[dict]:
        try:
            result = (self.client.table("owner_principals")
                      .upsert({"user_id": str(user_id),
                               "guest_secret_hash": None},
                              on_conflict="user_id").execute())
            return result.data[0] if result.data else \
                self.get_owner_principal_for_user(user_id)
        except Exception as e:
            logger.warning("create_user_owner_principal failed user=%s: %s",
                           user_id, e)
            return None

    @staticmethod
    def _rpc_row(data: Any) -> Optional[dict]:
        """Normalize PostgREST composite/JSON RPC responses to one mapping."""
        if isinstance(data, dict):
            return data
        if isinstance(data, list) and data and isinstance(data[0], dict):
            return data[0]
        return None

    def get_mlc2_principal_consent_status(
        self, acquisition_principal_id: str,
    ) -> Optional[dict]:
        result = self.client.rpc(
            "get_mlc2_principal_consent_status_v1",
            {"p_acquisition_principal_id": str(acquisition_principal_id)},
        ).execute()
        return self._rpc_row(result.data)

    def record_mlc2_consent_withdrawal(
        self,
        *,
        acquisition_principal_id: str,
        grant_event_id: str,
        source_route: str,
        client_version: str,
        affirmative_action: dict,
        occurred_at: str,
        idempotency_key: str,
    ) -> Optional[dict]:
        result = self.client.rpc("record_mlc2_consent_withdrawal_v1", {
            "p_acquisition_principal_id": str(acquisition_principal_id),
            "p_grant_event_id": str(grant_event_id),
            "p_source_route": str(source_route),
            "p_client_version": str(client_version),
            "p_affirmative_action": dict(affirmative_action),
            "p_occurred_at": str(occurred_at),
            "p_idempotency_key": str(idempotency_key),
        }).execute()
        return self._rpc_row(result.data)

    def create_guest_owner_principal(
        self, principal_id: str, secret_hash: str,
    ) -> Optional[dict]:
        try:
            result = self.client.table("owner_principals").insert({
                "id": str(principal_id),
                "user_id": None,
                "guest_secret_hash": str(secret_hash),
            }).execute()
            return result.data[0] if result.data else None
        except Exception as e:
            logger.warning("create_guest_owner_principal failed id=%s: %s",
                           principal_id, e)
            return None

    def claim_guest_owner_principal(
        self, principal_id: str, secret_hash: str, user_id: str,
    ) -> Optional[dict]:
        try:
            result = self.client.rpc("claim_guest_owner", {
                "p_owner_principal_id": str(principal_id),
                "p_guest_secret_hash": str(secret_hash),
                "p_user_id": str(user_id),
            }).execute()
            if isinstance(result.data, list):
                return result.data[0] if result.data else None
            return result.data if isinstance(result.data, dict) else None
        except Exception as e:
            logger.warning("claim_guest_owner_principal failed id=%s: %s",
                           principal_id, e)
            return None

    def create_project(self, payload: dict) -> Optional[dict]:
        try:
            result = self.client.table("projects").insert(payload).execute()
            return result.data[0] if result.data else None
        except Exception as e:
            logger.warning("create_project failed id=%s: %s",
                           payload.get("id"), e)
            return None

    def get_project_owner_principal(self, project_id: str) -> str:
        """The project's owner principal — the AUTHORITATIVE one.

        projects.owner_principal_id is NOT NULL, so a project always has one.
        v2_sessions.owner_principal_id is a nullable denormalised copy and is
        absent on most rows, which is why anything needing a take's owner must
        be able to fall back here rather than trusting the copy. The recording
        path has always resolved from the project (routes/v2/lab_recording.py
        passes upload.project.principal.id); this lets the practice path read
        the same source.

        Deliberately NOT get_project_for_owner: that one takes the owner as an
        argument, which is the answer, not the question."""
        if not project_id:
            return ""
        try:
            result = (self.client.table("projects")
                      .select("owner_principal_id")
                      .eq("id", str(project_id)).limit(1).execute())
            row = (result.data or [None])[0]
            return str((row or {}).get("owner_principal_id") or "")
        except Exception as e:
            logger.warning("get_project_owner_principal failed project=%s: %s",
                           project_id, e)
            return ""

    def get_project_for_owner(
        self, project_id: str, owner_principal_id: str,
    ) -> Optional[dict]:
        try:
            result = (self.client.table("projects").select("*")
                      .eq("id", str(project_id))
                      .eq("owner_principal_id", str(owner_principal_id))
                      .limit(1).execute())
            row = result.data[0] if result.data else None
            # An erased project is kept only as an empty receipt (N9); it is
            # no longer the owner's to open or record into.
            if row and row.get("tombstoned_at"):
                return None
            return row
        except Exception as e:
            logger.warning("get_project_for_owner failed project=%s: %s",
                           project_id, e)
            return None

    def bind_take_to_project(
        self,
        take_id: str,
        project_id: str,
        owner_principal_id: str,
    ) -> Optional[int]:
        try:
            result = self.client.rpc("bind_project_take", {
                "p_take_id": str(take_id),
                "p_project_id": str(project_id),
                "p_owner_principal_id": str(owner_principal_id),
            }).execute()
            value = result.data
            if isinstance(value, list):
                value = value[0] if value else None
            return int(value) if value is not None else None
        except Exception as e:
            logger.warning("bind_take_to_project failed take=%s: %s", take_id, e)
            return None

    def bind_recording_variant_to_project(
        self,
        variant_id: str,
        project_id: str,
        owner_principal_id: str,
        paired_take_id: str,
    ) -> Optional[int]:
        try:
            result = self.client.rpc("bind_project_recording_variant", {
                "p_variant_id": str(variant_id),
                "p_project_id": str(project_id),
                "p_owner_principal_id": str(owner_principal_id),
                "p_paired_take_id": str(paired_take_id),
            }).execute()
            value = result.data
            if isinstance(value, list):
                value = value[0] if value else None
            return int(value) if value is not None else None
        except Exception as e:
            logger.warning(
                "bind_recording_variant_to_project failed variant=%s: %s",
                variant_id,
                e,
            )
            return None

    # Context fields: context_short (session summary), context_long (report text), coach_notes (speaker_profile). See docs/CONTEXT-FIELDS.md.

    # ---------- Metric questions (2 questions for AI task block; admin Metrics section) ----------
    def v2_get_metric_questions(self):
        """All rows from v2_metric_questions ordered by position (the 3 task-block questions)."""
        result = (
            self.client.table("v2_metric_questions")
            .select("*")
            .order("position")
            .execute()
        )
        return result.data or []

    def v2_update_metric_question_by_position(self, position: int, text: str):
        """Update the single row with this position (1, 2, or 3)."""
        result = self.client.table("v2_metric_questions").update({"text": (text or "").strip()}).eq("position", position).execute()
        return result.data[0] if result.data else None

    _V2_OVERRIDES_COLUMNS = {
        "intended_emotion_prompt", "keywords_prompt", "emotion_check_question_text",
        "assigned_task_id",
        "pitch_variance_ideal",
        "pending_tutor_video_url",
        "pending_tutor_video_description",
        "pending_tutor_video_bucket",
        "pending_tutor_video_storage_path",
        "skip_metric_questions",
    }

    def v2_get_user_metric_questions(self, user_id: str):
        """Get the 3 metric questions from v2_metric_questions and pitch_variance_ideal from overrides."""
        rows = self.v2_get_metric_questions()
        by_pos = {r.get("position"): (r.get("text") or "").strip() for r in rows}
        override_result = self.client.table("v2_student_overrides").select("pitch_variance_ideal").eq("user_id", user_id).execute()
        override_row = override_result.data[0] if override_result.data else None
        pitch = override_row.get("pitch_variance_ideal") if override_row else None
        return {
            "metric_question_1": by_pos.get(1, ""),
            "metric_question_2": by_pos.get(2, ""),
            "metric_question_3": by_pos.get(3, ""),
            "pitch_variance_ideal": pitch,
        }

    def v2_update_user_metric_questions(self, user_id: str, data: dict):
        """Update the 3 metric questions in v2_metric_questions (by position) and optionally pitch_variance_ideal in overrides."""
        for pos, key in [(1, "metric_question_1"), (2, "metric_question_2"), (3, "metric_question_3")]:
            if key in data:
                self.v2_update_metric_question_by_position(pos, data.get(key))
        if "pitch_variance_ideal" in data:
            try:
                val = float(data["pitch_variance_ideal"]) if data["pitch_variance_ideal"] is not None else None
            except (TypeError, ValueError):
                val = None
            payload = {"user_id": user_id, "updated_at": datetime.now(timezone.utc).isoformat(), "pitch_variance_ideal": val}
            self.client.table("v2_student_overrides").upsert(payload, on_conflict="user_id").execute()
        return self.v2_get_user_metric_questions(user_id)

    def v2_upsert_student_overrides(self, user_id: str, data: dict):
        """Atomic column-specific upsert — only touches columns present in *data*.

        PostgREST ``ON CONFLICT (user_id) DO UPDATE`` only sets the columns
        included in the payload, so untouched columns keep their current
        value.  This removes the old read-merge-write cycle that was
        vulnerable to concurrent-write races.
        """
        payload: dict = {}
        for col in self._V2_OVERRIDES_COLUMNS:
            if col not in data:
                continue
            val = data[col]
            if col == "assigned_task_id" and val == "":
                val = None
            payload[col] = val
        if "skip_metric_questions" in payload and payload["skip_metric_questions"] is None:
            payload["skip_metric_questions"] = False
        if not payload:
            return self.v2_get_student_overrides(user_id)
        payload["user_id"] = user_id
        payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        result = self.client.table("v2_student_overrides").upsert(payload, on_conflict="user_id").execute()
        rows = result.data or []
        for row in rows:
            if str(row.get("user_id") or "") == str(user_id):
                return row
        return self.v2_get_student_overrides(user_id)

    def v2_list_auth_users(self, limit: int = 50, offset: int = 0):
        """List all auth users (id, email) via Supabase Auth Admin API so new students appear in admin list.
        Returns list of dicts with user_id and email (email may be None if not present)."""
        try:
            import httpx
            base = f"{config.SUPABASE_URL.rstrip('/')}/auth/v1/admin/users"
            # GoTrue list users: per_page and page (1-based)
            page = (offset // limit) + 1
            resp = httpx.get(
                base,
                params={"per_page": min(limit, 1000), "page": page},
                headers={
                    "Authorization": f"Bearer {config.SUPABASE_SERVICE_ROLE_KEY}",
                    "apikey": config.SUPABASE_SERVICE_ROLE_KEY,
                },
                timeout=10,
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
            users = data.get("users") or (data.get("data") or {}).get("users") or []
            out = []
            for u in users:
                uid = u.get("id")
                if not uid:
                    continue
                meta = u.get("user_metadata") or {}
                raw_name = meta.get("name") or meta.get("display_name")
                out.append({
                    "user_id": uid,
                    "email": u.get("email") or (u.get("user_metadata") or {}).get("email"),
                    "name": (str(raw_name).strip() if raw_name is not None and str(raw_name).strip() else None),
                    "created_at": u.get("created_at"),
                    "last_sign_in_at": u.get("last_sign_in_at"),
                    "email_confirmed_at": u.get("email_confirmed_at"),
                })
            return out
        except Exception:
            return None

    def get_student_names(self, user_ids: list) -> dict:
        """{user_id: name} from v2_student_details for the ids that have a
        non-empty name, in one query (Phase 0b, coach students)."""
        ids = [str(u) for u in (user_ids or []) if u]
        if not ids:
            return {}
        result = (
            self.client.table("v2_student_details")
            .select("user_id, name")
            .in_("user_id", ids)
            .execute()
        )
        out: dict = {}
        for row in result.data or []:
            name = str(row.get("name") or "").strip()
            if row.get("user_id") and name:
                out[str(row["user_id"])] = name
        return out

    def v2_get_student_details(self, user_id: str):
        """Get student details row (name, price_per_live_lesson, credits, is_archived) or None."""
        result = (
            self.client.table("v2_student_details")
            .select("user_id, name, price_per_live_lesson, credits, is_archived")
            .eq("user_id", user_id)
            .execute()
        )
        return result.data[0] if result.data else None

    def v2_increment_student_credits(self, user_id: str, delta: int) -> int | None:
        """Add delta to credits (e.g. Stripe payment). Negative delta allowed for corrections; result floors at 0. Returns new balance or None on failure."""
        try:
            d = int(delta)
            details = self.v2_get_student_details(user_id)
            current = (details or {}).get("credits")
            if current is None:
                current = _free_credit_grant()
            new_credits = max(0, int(current) + d)
            result = (
                self.client.table("v2_student_details")
                .upsert(
                    {"user_id": user_id, "credits": new_credits, "updated_at": datetime.now(timezone.utc).isoformat()},
                    on_conflict="user_id",
                )
                .execute()
            )
            return (result.data[0] or {}).get("credits") if result.data else new_credits
        except Exception as e:
            logger.warning(
                "v2_increment_student_credits failed user_id=%s delta=%s: %s",
                user_id,
                d,
                e,
                exc_info=True,
            )
            return None

    def v2_find_user_id_by_email(self, email: str) -> Optional[str]:
        """Resolve a Supabase auth user_id from an email (case-insensitive) —
        for the testing credits-admin page (founder enters an email, not a
        UUID). Scans the Auth Admin user list; fine for the testing user count.
        None when not found / on error."""
        target = (email or "").strip().lower()
        if not target:
            return None
        try:
            offset = 0
            for _ in range(20):  # up to 20 * 50 = 1000 users, then give up
                page = self.v2_list_auth_users(limit=50, offset=offset) or []
                for u in page:
                    if (u.get("email") or "").strip().lower() == target:
                        return u.get("user_id") or u.get("id")
                if len(page) < 50:
                    break
                offset += 50
            return None
        except Exception as e:
            logger.warning("v2_find_user_id_by_email failed: %s", e)
            return None

    def v2_charge_lab_credits_once(self, session_id: str, user_id: str, amount: int = 1) -> None:
        """Deduct `amount` credits once per willab Lab session at SEND.

        willab "uses credits" — UX Wave v2 relocated the charge from publish
        to send-success (1/session, soft). Idempotent: sets
        lab_credits_charged_at only when NULL (a re-send / re-claim / OAuth
        re-callback never double-charges — all resolve to one session_id),
        then deducts SOFTLY — v2_deduct_session_credits floors at 0, so it
        never hard-blocks. On deduct failure, clears the flag so a retry can
        succeed. Best-effort: never raises into the send path; degrades to a
        no-op if the column is missing.
        """
        if not session_id or not user_id:
            return
        now = datetime.now(timezone.utc).isoformat()
        try:
            result = (
                self.client.table("v2_sessions")
                .update({"lab_credits_charged_at": now})
                .eq("id", session_id)
                .is_("lab_credits_charged_at", "null")
                .execute()
            )
            if not result.data:
                return  # already charged (idempotent no-op), or no such row
        except Exception as e:
            err_low = str(e).lower()
            if "lab_credits_charged_at" in err_low and (
                "does not exist" in err_low or "pgrst" in err_low
            ):
                logger.warning(
                    "v2_charge_lab_credits_once: column missing (run "
                    "migrations/add_lab_credits_charged_at.sql) sid=%s",
                    session_id,
                )
            else:
                logger.warning(
                    "v2_charge_lab_credits_once: flag update failed sid=%s err=%s",
                    session_id, e,
                )
            return
        new_bal = self.v2_deduct_session_credits(user_id, amount=amount)
        if new_bal is None:
            logger.warning(
                "v2_charge_lab_credits_once: deduct failed after flag; "
                "clearing flag sid=%s user=%s", session_id, user_id,
            )
            try:
                self.client.table("v2_sessions").update(
                    {"lab_credits_charged_at": None}
                ).eq("id", session_id).execute()
            except Exception:
                pass
        else:
            logger.info(
                "v2_charge_lab_credits_once: charged %d sid=%s user=%s new_balance=%s",
                amount, session_id, user_id, new_bal,
            )

    def v2_ensure_credits_initialized(self, user_id: str, grant: Optional[int] = None) -> int:
        """willab credit grant — lazy first-touch seed (UX Wave v2 C1/S.2).

        Grants `grant` credits ONCE per user, the first time we touch their
        ledger (balance read or first send). `grant` defaults to
        config.WILLAB_FREE_CREDIT_GRANT (25 for the testing phase, env-tunable).
        Idempotent via the DEDICATED
        credits_initialized_at flag — never keyed on credits==0/NULL, so a
        user who spends down to 0 is never re-granted. Preserves any existing
        balance (e.g. purchased credits): seeds `grant` only when there is no
        credits value yet; otherwise just stamps the flag. Best-effort —
        returns the resolved balance; degrades to `grant` if the column is
        missing (pre-migration) so the balance endpoint still works.
        """
        if grant is None:
            grant = _free_credit_grant()
        if not user_id:
            return grant
        now = datetime.now(timezone.utc).isoformat()
        try:
            res = (
                self.client.table("v2_student_details")
                .select("credits, credits_initialized_at")
                .eq("user_id", user_id)
                .execute()
            )
            row = res.data[0] if res.data else None
        except Exception as e:
            err_low = str(e).lower()
            if "credits_initialized_at" in err_low and (
                "does not exist" in err_low or "pgrst" in err_low
            ):
                logger.warning(
                    "v2_ensure_credits_initialized: column missing (run "
                    "migrations/add_credits_initialized_at.sql) user=%s", user_id,
                )
            else:
                logger.warning(
                    "v2_ensure_credits_initialized: read failed user=%s err=%s",
                    user_id, e,
                )
            # Fall back to the legacy implicit default so balance still resolves.
            try:
                d = self.v2_get_student_details(user_id)
                cur = (d or {}).get("credits")
                return int(cur) if cur is not None else int(grant)
            except Exception:
                return int(grant)

        # Already initialized → return the current balance (coerced).
        if row and row.get("credits_initialized_at"):
            cur = row.get("credits")
            return int(cur) if cur is not None else 0

        if row is None:
            # No row yet → create with the grant (on_conflict survives a race).
            try:
                self.client.table("v2_student_details").upsert(
                    {"user_id": user_id, "credits": int(grant),
                     "credits_initialized_at": now, "updated_at": now},
                    on_conflict="user_id",
                ).execute()
            except Exception as e:
                logger.warning(
                    "v2_ensure_credits_initialized: seed-insert failed user=%s err=%s",
                    user_id, e,
                )
            logger.info("v2_ensure_credits_initialized: granted %d user=%s", grant, user_id)
            return int(grant)

        # Row exists, flag NULL → seed once. Preserve an existing balance; the
        # `.is_(... null)` guard means a concurrent send that already flagged +
        # decremented this row is NOT clobbered (the update matches nothing).
        existing = row.get("credits")
        seed = int(existing) if existing is not None else int(grant)
        try:
            self.client.table("v2_student_details").update(
                {"credits": seed, "credits_initialized_at": now, "updated_at": now}
            ).eq("user_id", user_id).is_("credits_initialized_at", "null").execute()
        except Exception as e:
            logger.warning(
                "v2_ensure_credits_initialized: seed-update failed user=%s err=%s",
                user_id, e,
            )
        if existing is None:
            logger.info("v2_ensure_credits_initialized: granted %d user=%s", grant, user_id)
        return seed

    def v2_get_cumulative_recorded_seconds(self, user_id: str) -> int:
        """Sum of the user's Lab recording durations (seconds) — the
        recording-progress signal (BE-1 / S2). Sums recordings.duration over
        the recordings linked to the user's Lab sessions. Recordings predating
        the duration-persistence fix (UX Wave 3) carry duration=0, so
        historical time undercounts; going forward it is exact. Best-effort:
        0 on hiccup."""
        if not user_id:
            return 0
        try:
            sessions = self.takes.v2_list_user_lab_sessions(user_id)
            rec_ids = [
                s.get("recording_id") for s in sessions if s.get("recording_id")
            ]
            if not rec_ids:
                return 0
            total = 0
            for i in range(0, len(rec_ids), 100):  # keep the IN() list sane
                chunk = rec_ids[i:i + 100]
                res = (
                    self.client.table("recordings")
                    .select("id, duration")
                    .in_("id", chunk)
                    .execute()
                )
                for r in (res.data or []):
                    try:
                        total += int(round(float(r.get("duration") or 0)))
                    except (TypeError, ValueError):
                        pass
            return total
        except Exception as e:
            logger.warning(
                "v2_get_cumulative_recorded_seconds failed user=%s err=%s",
                user_id, e,
            )
            return 0

    def v2_get_sessions_with_previews(self, user_id: str, limit: int = 50):
        """Get v2 sessions for a user with full report text and all analytics previews for admin session history."""
        all_session_columns = [
            "id", "created_at", "completed_at", "status",
            "recording_id", "report_id", "report_grade",
            "student_completion_email_sent_at",
            "self_rating_submitted_at",
            "student_self_rating",
            "score", "task_score",
            "ai_draft_grade", "ai_draft_comment",
            "question_1_score", "question_2_score", "question_3_score",
            "realtime_level_at_session", "realtime_step_at_session",
            "ai_task_score", "ai_scoring_justification", "coach_override_score", "coach_override_justification",
            "session_task_id",
            "session_task_text",
        ]
        sessions, session_fields = _sessions_with_schema_fallback(
            self, user_id, limit, all_session_columns,
        )
        session_ids = [s["id"] for s in sessions]

        # Batch: context_long for report fallback
        context_long_by_id = {}
        if session_ids:
            try:
                ctx = self.client.table("v2_sessions").select("id, context_long, context_long_entries").in_("id", session_ids).execute()
                for row in (ctx.data or []):
                    text = (row.get("context_long") or "").strip()
                    if not text and row.get("context_long_entries"):
                        entries = row["context_long_entries"]
                        if isinstance(entries, list) and entries:
                            last = entries[-1]
                            if isinstance(last, dict) and last.get("text"):
                                text = (last["text"] or "").strip()
                    if text:
                        context_long_by_id[row["id"]] = text
            except Exception:
                pass

        # Batch: session_sniper_metrics
        sniper_metrics_by_session: dict = {}
        if session_ids:
            try:
                sm = (
                    self.client.table("session_sniper_metrics")
                    .select("session_id, wpm, pause_ms, dynamic_db, emphasis_per_min, energy_ratio, voiced_duration_sec, pitch_center_st, pitch_frame_count, stage_score, student_rating_1_10")
                    .in_("session_id", session_ids)
                    .execute()
                )
                for row in (sm.data or []):
                    sniper_metrics_by_session[row["session_id"]] = row
            except Exception:
                pass

        # Batch: recordings (keyed by recording id)
        recording_ids = list({s.get("recording_id") for s in sessions if s.get("recording_id")})
        recordings_by_id: dict = {}
        if recording_ids:
            try:
                rec_select = "id, performance_score_v2, transcription_text, words_per_minute, filler_words_count, performance_metrics_v2, duration_ms"
                try:
                    recs = (
                        self.client.table("recordings")
                        .select(rec_select)
                        .in_("id", recording_ids)
                        .execute()
                    )
                except Exception as rec_err:
                    # Legacy schema uses `duration` (seconds) instead of `duration_ms`.
                    rec_msg = str(rec_err).lower()
                    if "duration_ms" in rec_msg and ("does not exist" in rec_msg or "42703" in rec_msg or "undefined_column" in rec_msg):
                        recs = (
                            self.client.table("recordings")
                            .select("id, performance_score_v2, transcription_text, words_per_minute, filler_words_count, performance_metrics_v2, duration")
                            .in_("id", recording_ids)
                            .execute()
                        )
                    else:
                        raise
                for row in (recs.data or []):
                    recordings_by_id[row["id"]] = row
            except Exception:
                pass

        out = []
        for s in sessions:
            rec = _session_preview_row(
                s, session_fields, recordings_by_id,
                sniper_metrics_by_session,
            )

            report_text = None
            if s.get("report_id"):
                r = self.client.table("v2_reports").select("report_text").eq("id", s["report_id"]).execute()
                if r.data:
                    report_text = r.data[0].get("report_text") or ""
            if report_text is None and s.get("id"):
                try:
                    r2 = self.client.table("v2_reports").select("report_text").eq("session_v2_id", s["id"]).order("created_at", desc=True).limit(1).execute()
                    if r2.data:
                        report_text = (r2.data[0].get("report_text") or "").strip() or None
                except Exception:
                    pass
            if report_text is None:
                report_text = context_long_by_id.get(s["id"])
            rec["report_delivered"] = bool((report_text or "").strip())
            if report_text:
                rec["report_preview"] = {"report_text_preview": (report_text or "").strip()}
            out.append(rec)
        return out

    def v2_get_speaker_profile(self, user_id: str):
        """Get speaker profile for admin panel (main_goal, motivation, coach_notes, etc.)."""
        result = self.client.table("v2_speaker_profiles").select("*").eq("user_id", user_id).execute()
        rows = result.data or []
        for row in rows:
            if str(row.get("user_id") or "") == str(user_id):
                return row
        return None

    def get_user_email_from_auth(self, user_id: str) -> str | None:
        """Fetch user email from Supabase Auth (admin API). Returns None if not found or on error."""
        try:
            import httpx
            url = f"{config.SUPABASE_URL.rstrip('/')}/auth/v1/admin/users/{user_id}"
            resp = httpx.get(
                url,
                headers={
                    "Authorization": f"Bearer {config.SUPABASE_SERVICE_ROLE_KEY}",
                    "apikey": config.SUPABASE_SERVICE_ROLE_KEY,
                },
                timeout=5,
            )
            if resp.status_code == 200:
                data = resp.json()
                email = data.get("email") or (data.get("user", {}).get("email"))
                if email and str(email).strip():
                    return str(email).strip()
            # Fallback: some Supabase setups don't expose /admin/users/{id}; use list endpoint and find by id.
            base = f"{config.SUPABASE_URL.rstrip('/')}/auth/v1/admin/users"
            for page in range(1, 11):
                list_resp = httpx.get(
                    base,
                    params={"per_page": 1000, "page": page},
                    headers={
                        "Authorization": f"Bearer {config.SUPABASE_SERVICE_ROLE_KEY}",
                        "apikey": config.SUPABASE_SERVICE_ROLE_KEY,
                    },
                    timeout=10,
                )
                if list_resp.status_code != 200:
                    break
                payload = list_resp.json()
                users = payload.get("users") or (payload.get("data") or {}).get("users") or []
                if not users:
                    break
                for u in users:
                    if str(u.get("id") or "") == str(user_id):
                        found = (u.get("email") or (u.get("user_metadata") or {}).get("email") or "").strip()
                        return found or None
                if len(users) < 1000:
                    break
            return None
        except Exception:
            return None

    # ---------- Coach AI Conversations ----------

    def get_coach_ai_conversation(self, user_id: str) -> dict | None:
        """Get the coach AI conversation history for a student."""
        try:
            result = (
                self.client.table("coach_ai_conversations")
                .select("*")
                .eq("user_id", user_id)
                .execute()
            )
            return result.data[0] if result.data else None
        except Exception as e:
            logger.warning("get_coach_ai_conversation failed for %s: %s", user_id, e)
            return None

    def upsert_coach_ai_conversation(self, user_id: str, messages: list) -> dict | None:
        """Save/update the coach AI conversation history for a student.
        messages: list of {role, content, timestamp} dicts."""
        now = datetime.now(timezone.utc).isoformat()
        payload = {
            "user_id": user_id,
            "messages": json.dumps(messages) if isinstance(messages, list) else messages,
            "updated_at": now,
        }
        try:
            result = (
                self.client.table("coach_ai_conversations")
                .upsert(payload, on_conflict="user_id")
                .execute()
            )
            return result.data[0] if result.data else None
        except Exception as e:
            logger.error("upsert_coach_ai_conversation failed for %s: %s", user_id, e)
            raise

    def clear_coach_ai_conversation(self, user_id: str) -> bool:
        """Clear (delete) the coach AI conversation for a student."""
        try:
            self.client.table("coach_ai_conversations").delete().eq("user_id", user_id).execute()
            return True
        except Exception as e:
            logger.warning("clear_coach_ai_conversation failed for %s: %s", user_id, e)
            return False

    # ---------- Admin Copilot Inbox ----------

    def create_admin_annotation_event(
        self,
        *,
        user_id: str,
        session_id: Optional[str],
        section_type: str,
        field_name: str,
        ai_original_text: Optional[str],
        coach_final_text: Optional[str],
        reason_chip: Optional[str],
        custom_reason: Optional[str],
        created_by: str,
        draft_id: Optional[str] = None,
        previous_value_hash: Optional[str] = None,
        new_value_hash: Optional[str] = None,
    ) -> None:
        payload = {
            "user_id": user_id,
            "session_id": session_id,
            "section_type": section_type,
            "field_name": field_name,
            "ai_original_text": ai_original_text,
            "coach_final_text": coach_final_text,
            "reason_chip": reason_chip,
            "custom_reason": custom_reason,
            "created_by": created_by,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "draft_id": draft_id,
            "previous_value_hash": previous_value_hash,
            "new_value_hash": new_value_hash,
        }
        try:
            self.client.table("admin_annotation_events").insert(payload).execute()
        except Exception:
            # Backward compatibility for DBs without hash/draft_id columns.
            payload.pop("draft_id", None)
            payload.pop("previous_value_hash", None)
            payload.pop("new_value_hash", None)
            self.client.table("admin_annotation_events").insert(payload).execute()

    def list_admin_student_send_drafts(self, *, status: Optional[str] = None) -> List[Dict[str, Any]]:
        q = (
            self.client.table("admin_student_send_drafts")
            .select("*")
            .order("updated_at", desc=True)
            .order("created_at", desc=True)
        )
        if status:
            q = q.eq("status", status)
        res = q.execute()
        return res.data or []

    def try_claim_admin_send_draft_delivery_in_progress(self, draft_id: str, user_id: str) -> Optional[Dict[str, Any]]:
        """Atomically move lifecycle idle|failed → delivering. Returns row if claim succeeded."""
        now = datetime.now(timezone.utc).isoformat()
        try:
            res = (
                self.client.table("admin_student_send_drafts")
                .update(
                    {
                        "delivery_lifecycle": "delivering",
                        "delivery_started_at": now,
                        "delivery_failed_step": None,
                        "updated_at": now,
                    }
                )
                .eq("id", draft_id)
                .eq("user_id", user_id)
                .in_("delivery_lifecycle", ["idle", "failed"])
                .execute()
            )
            return res.data[0] if res.data else None
        except Exception as e:
            logger.warning("try_claim_admin_send_draft_delivery_in_progress: %s", e)
            return None

    def create_admin_uploaded_reference_video(
        self,
        *,
        draft_id: Optional[str],
        user_id: str,
        session_id: Optional[str],
        storage_path: str,
        source_video_url: Optional[str],
        transcript_text: Optional[str],
        feature_metadata: Optional[Dict[str, Any]],
        tags: Optional[List[str]],
        is_universal: bool,
        created_by: Optional[str],
        transcription_status: Optional[str] = None,
        transcription_error: Optional[str] = None,
        title: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        clean_title = (title or "").strip() or None
        fm = dict(feature_metadata or {})
        # Mirror fields that may be missing at top-level into feature_metadata.
        # Some prod DBs pre-date migrations adding title/transcription_status/transcription_error.
        if clean_title and "title" not in fm:
            fm["title"] = clean_title
        if transcription_status and "transcription_status" not in fm:
            fm["transcription_status"] = transcription_status
        if transcription_error and "transcription_error" not in fm:
            fm["transcription_error"] = transcription_error
        payload = {
            "draft_id": draft_id,
            "user_id": user_id,
            "session_id": session_id,
            "storage_path": storage_path,
            "source_video_url": source_video_url,
            "transcript_text": transcript_text,
            "feature_metadata": fm,
            "tags": tags or [],
            "is_universal": bool(is_universal),
            "created_by": created_by,
            "transcription_status": (transcription_status or "pending"),
            "transcription_error": transcription_error,
            "title": clean_title,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        # Columns that may be absent from older prod schemas. Retry without them
        # when PostgREST reports PGRST204 "could not find column" for any of these.
        _OPTIONAL_COLS = ("title", "transcription_status", "transcription_error", "updated_at")
        import re as _re
        res = None
        for _attempt in range(len(_OPTIONAL_COLS) + 1):
            try:
                res = self.client.table("admin_uploaded_reference_videos").insert(payload).execute()
                break
            except Exception as e:
                msg = str(e)
                if "PGRST204" not in msg and "schema cache" not in msg:
                    raise
                dropped = False
                for col in _OPTIONAL_COLS:
                    if col in payload and f"'{col}'" in msg:
                        payload.pop(col, None)
                        dropped = True
                        break
                if not dropped:
                    m = _re.search(r"'([A-Za-z_][A-Za-z0-9_]*)'", msg)
                    if m and m.group(1) in payload:
                        payload.pop(m.group(1), None)
                        dropped = True
                if not dropped:
                    raise
        return res.data[0] if (res and res.data) else None

    def list_admin_uploaded_reference_videos_for_training(
        self,
        *,
        since_iso: Optional[str] = None,
        limit: int = 500,
    ) -> List[Dict[str, Any]]:
        q = (
            self.client.table("admin_uploaded_reference_videos")
            .select("*")
            .eq("is_active", True)
            .order("created_at", desc=False)
            .limit(max(1, min(5000, int(limit))))
        )
        if since_iso:
            q = q.gt("created_at", since_iso)
        res = q.execute()
        return res.data or []

    def get_latest_universal_welcome_video(self) -> Optional[Dict[str, Any]]:
        """Return the most recent reference video flagged is_universal=true.

        Used as a fallback "welcome video" on the student's step-0 screen when
        the coach has not yet sent a personal assignment. Admins mark a video
        as universal by checking the "Universal video" box in Training Studio
        on upload (body field `is_universal_video=true`).

        Returns None if no universal video exists or the table is missing.
        """
        try:
            res = (
                self.client.table("admin_uploaded_reference_videos")
                .select("*")
                .eq("is_universal", True)
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
            return (res.data or [None])[0]
        except Exception as e:
            logger.warning("get_latest_universal_welcome_video: %s", e)
            return None

    def find_duplicate_admin_uploaded_reference_video(
        self,
        user_id: str,
        *,
        original_filename: str,
        draft_id: Optional[str] = None,
        session_id: Optional[str] = None,
        within_minutes: int = 60,
    ) -> Optional[Dict[str, Any]]:
        """Return an existing reference video row that looks like a duplicate of
        the one the admin is about to upload. Used to short-circuit re-uploads
        of the same file for the same student/draft within *within_minutes*.

        Match rules (all must hold):
          - same user_id
          - same original_filename (stored in feature_metadata.original_filename
            AND/OR the tail of storage_path)
          - created within the last *within_minutes*
          - same draft_id if provided, else same session_id if provided
        """
        try:
            from datetime import timedelta
            cutoff = (datetime.now(timezone.utc) - timedelta(minutes=max(1, within_minutes))).isoformat()
            q = (
                self.client.table("admin_uploaded_reference_videos")
                .select("*")
                .eq("user_id", user_id)
                .gte("created_at", cutoff)
                .order("created_at", desc=True)
                .limit(20)
            )
            if draft_id:
                q = q.eq("draft_id", draft_id)
            elif session_id:
                q = q.eq("session_id", session_id)
            res = q.execute()
            rows = res.data or []
        except Exception as e:
            logger.warning("find_duplicate_admin_uploaded_reference_video: %s", e)
            return None
        needle = (original_filename or "").strip()
        if not needle:
            return None
        for row in rows:
            fm = row.get("feature_metadata") or {}
            fm_name = (fm.get("original_filename") or "").strip() if isinstance(fm, dict) else ""
            sp_tail = os.path.basename((row.get("storage_path") or "").strip())
            # storage_path tail is "{uuid}{ext}", so compare extensions only there.
            if fm_name and fm_name == needle:
                return row
            if sp_tail and os.path.splitext(sp_tail)[1].lower() == os.path.splitext(needle)[1].lower() and fm_name == needle:
                return row
        return None

    def get_latest_admin_uploaded_reference_video_for_user(
        self,
        user_id: str,
        *,
        session_id: Optional[str] = None,
        draft_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Most-recent admin-uploaded reference video for this student.

        Preference order: (draft_id match) → (session_id match) → any row for user.
        Used as a fallback on "Approve & Send" when the draft has no explicit
        video attached — so the Training-Studio upload still surfaces on the
        student's step-0 screen.
        """
        def _query(filters: Dict[str, Any]) -> Optional[Dict[str, Any]]:
            try:
                q = self.client.table("admin_uploaded_reference_videos").select("*")
                for k, v in filters.items():
                    q = q.eq(k, v)
                q = q.order("created_at", desc=True).limit(1)
                res = q.execute()
                return res.data[0] if res.data else None
            except Exception as e:
                logger.warning("get_latest_admin_uploaded_reference_video_for_user filter=%s: %s", filters, e)
                return None
        if draft_id:
            hit = _query({"user_id": user_id, "draft_id": draft_id})
            if hit:
                return hit
        if session_id:
            hit = _query({"user_id": user_id, "session_id": session_id})
            if hit:
                return hit
        return _query({"user_id": user_id})

    def update_admin_uploaded_reference_video(
        self,
        reference_video_id: str,
        fields: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        payload = dict(fields or {})
        payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        res = (
            self.client.table("admin_uploaded_reference_videos")
            .update(payload)
            .eq("id", reference_video_id)
            .execute()
        )
        return res.data[0] if res.data else None

    def update_copilot_reference_upload_job(
        self,
        job_id: str,
        fields: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        payload = dict(fields or {})
        payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        res = (
            self.client.table("copilot_reference_upload_jobs")
            .update(payload)
            .eq("id", job_id)
            .execute()
        )
        return res.data[0] if res.data else None

    def mark_stale_upload_jobs_failed(self, stale_minutes: int = 30) -> int:
        """Mark upload jobs stuck in a non-terminal state as failed.

        Should be called on app startup to recover from worker restarts
        that killed in-flight daemon threads.  Returns count of affected rows.
        """
        from datetime import timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=max(5, stale_minutes))).isoformat()
        try:
            res = (
                self.client.table("copilot_reference_upload_jobs")
                .select("id, stage, updated_at")
                .lt("updated_at", cutoff)
                .neq("stage", "completed")
                .neq("stage", "failed")
                .limit(200)
                .execute()
            )
            stale = res.data or []
            for row in stale:
                self.update_copilot_reference_upload_job(
                    str(row["id"]),
                    {
                        "stage": "failed",
                        "error": "Server restarted while job was in progress",
                        "message": "Interrupted — please retry the upload",
                    },
                )
            return len(stale)
        except Exception as e:
            logger.warning("mark_stale_upload_jobs_failed: %s", e)
            return 0

    # ── processing_jobs — durable state for the async recording pipeline ──
    # (migrations/add_processing_jobs.sql). Postgres is the source of truth;
    # Redis only delivers. All writers here are exact-shape (no phantom
    # columns — the PGRST204 whole-update-rejected lesson from
    # v2_update_session_status_unscoped applies to every method below).

    def create_processing_job(
        self,
        *,
        kind: str,
        user_id: Optional[str],
        session_id: Optional[str],
        dedup_key: Optional[str],
        payload: Dict[str, Any],
        max_attempts: int = 3,
    ) -> Optional[Dict[str, Any]]:
        """Insert a pending job row. Returns the row, or None on failure
        (including a dedup conflict — caller checks for an active twin)."""
        row = {
            "kind": kind,
            "user_id": user_id,
            "session_id": session_id,
            "dedup_key": dedup_key,
            "status": "pending",
            "attempts": 0,
            "max_attempts": max(1, int(max_attempts)),
            "payload": payload or {},
        }
        try:
            res = self.client.table("processing_jobs").insert(row).execute()
            return res.data[0] if res.data else None
        except Exception as e:
            logger.warning("create_processing_job failed kind=%s sid=%s: %s",
                           kind, session_id, e)
            return None

    def get_processing_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        try:
            res = (
                self.client.table("processing_jobs")
                .select("*")
                .eq("id", job_id)
                .limit(1)
                .execute()
            )
            return res.data[0] if res.data else None
        except Exception as e:
            logger.warning("get_processing_job failed job=%s: %s", job_id, e)
            return None

    def get_active_processing_job_by_dedup(
        self, dedup_key: str,
    ) -> Optional[Dict[str, Any]]:
        """The pending/processing job holding this dedup_key, if any."""
        try:
            res = (
                self.client.table("processing_jobs")
                .select("*")
                .eq("dedup_key", dedup_key)
                .in_("status", ["pending", "processing"])
                .limit(1)
                .execute()
            )
            return res.data[0] if res.data else None
        except Exception as e:
            logger.warning("get_active_processing_job_by_dedup failed: %s", e)
            return None

    def get_latest_processing_job_by_session(
        self, session_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Latest durable progress row for a submitted recording.

        Read-only and best-effort: older deployments without the table simply
        omit real progress while the session state remains authoritative.
        """
        try:
            res = (
                self.client.table("processing_jobs")
                .select("*")
                .eq("session_id", session_id)
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
            return res.data[0] if res.data else None
        except Exception as e:
            logger.warning("get_latest_processing_job_by_session failed: %s", e)
            return None

    def reset_processing_job_for_manual_retry(self, job_id: str) -> bool:
        """Re-open one terminal failed job without replacing its audio."""
        now = datetime.now(timezone.utc).isoformat()
        try:
            res = (
                self.client.table("processing_jobs")
                .update({
                    "status": "pending", "attempts": 0,
                    "stage": "processing_recording", "percent": 0,
                    "error": None, "result": None,
                    "started_at": None, "finished_at": None,
                    "heartbeat_at": None, "updated_at": now,
                })
                .eq("id", job_id)
                .eq("status", "failed")
                .execute()
            )
            return bool(res.data)
        except Exception as e:
            logger.warning("reset_processing_job_for_manual_retry failed: %s", e)
            return False

    def claim_processing_job(
        self, job_id: str, expected_attempts: int,
    ) -> Optional[Dict[str, Any]]:
        """Atomically claim a job for one run: pending|processing →
        processing, attempts+1 — guarded by eq(attempts, expected) so of two
        racing claimers (double delivery, sweeper vs live worker) exactly
        one wins. Returns the claimed row or None if the CAS lost."""
        now = datetime.now(timezone.utc).isoformat()
        try:
            res = (
                self.client.table("processing_jobs")
                .update({
                    "status": "processing",
                    "attempts": int(expected_attempts) + 1,
                    "started_at": now,
                    "heartbeat_at": now,
                    "updated_at": now,
                })
                .eq("id", job_id)
                .eq("attempts", int(expected_attempts))
                .in_("status", ["pending", "processing"])
                .execute()
            )
            return res.data[0] if res.data else None
        except Exception as e:
            logger.warning("claim_processing_job failed job=%s: %s", job_id, e)
            return None

    def update_processing_job(
        self, job_id: str, fields: Dict[str, Any],
    ) -> bool:
        """Generic best-effort field update (heartbeat / stage / percent)."""
        try:
            payload = dict(fields)
            payload["updated_at"] = datetime.now(timezone.utc).isoformat()
            self.client.table("processing_jobs").update(payload).eq(
                "id", job_id
            ).execute()
            return True
        except Exception as e:
            logger.warning("update_processing_job failed job=%s: %s", job_id, e)
            return False

    def finish_processing_job(
        self,
        job_id: str,
        status: str,
        *,
        error: Optional[str] = None,
        result: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Terminal transition → completed | failed."""
        if status not in ("completed", "failed"):
            return False
        now = datetime.now(timezone.utc).isoformat()
        fields: Dict[str, Any] = {
            "status": status,
            "finished_at": now,
            "updated_at": now,
        }
        if status == "completed":
            fields["percent"] = 100
            fields["stage"] = "completed"
            fields["error"] = None
        if error is not None:
            fields["error"] = str(error)[:500]
        if result is not None:
            fields["result"] = result
        try:
            self.client.table("processing_jobs").update(fields).eq(
                "id", job_id
            ).execute()
            return True
        except Exception as e:
            logger.warning("finish_processing_job failed job=%s: %s", job_id, e)
            return False

    def release_processing_job_for_retry(
        self, job_id: str, error: Optional[str] = None,
    ) -> bool:
        """processing → pending (a failed run that still has attempts left,
        or a sweeper-recovered orphan). The attempts counter is NOT reset —
        it is the lifetime run count the cap applies to."""
        now = datetime.now(timezone.utc).isoformat()
        fields: Dict[str, Any] = {
            "status": "pending",
            "heartbeat_at": None,
            "updated_at": now,
        }
        if error is not None:
            fields["error"] = str(error)[:500]
        try:
            res = (
                self.client.table("processing_jobs")
                .update(fields)
                .eq("id", job_id)
                .eq("status", "processing")
                .execute()
            )
            return bool(res.data)
        except Exception as e:
            logger.warning("release_processing_job_for_retry failed job=%s: %s",
                           job_id, e)
            return False

    def list_stale_processing_jobs(
        self, stale_minutes: int = 15, max_rows: int = 100,
        max_runtime_minutes: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Jobs the sweeper should look at:

        1. 'processing' rows whose HEARTBEAT is older than the cutoff — the
           worker was killed mid-job;
        2. 'pending' rows untouched for the same window — the enqueue was
           lost (e.g. Redis wiped);
        3. when `max_runtime_minutes` is given, 'processing' rows that have
           been running longer than that REGARDLESS of heartbeat.

        (3) is the wedged case and the only one a heartbeat cannot reach:
        `_Heartbeat` is a timer thread, so a runner blocked forever on a
        socket keeps the row looking healthy to (1) indefinitely. Without
        this query such a take is unrecoverable by any code path.
        """
        from datetime import timedelta
        now = datetime.now(timezone.utc)
        cutoff = (now - timedelta(minutes=max(2, stale_minutes))).isoformat()
        out: List[Dict[str, Any]] = []
        try:
            res = (
                self.client.table("processing_jobs")
                .select("*")
                .eq("status", "processing")
                .lt("heartbeat_at", cutoff)
                .limit(max_rows)
                .execute()
            )
            out.extend(res.data or [])
        except Exception as e:
            logger.warning("list_stale_processing_jobs (processing): %s", e)
        try:
            res = (
                self.client.table("processing_jobs")
                .select("*")
                .eq("status", "pending")
                .lt("updated_at", cutoff)
                .limit(max_rows)
                .execute()
            )
            out.extend(res.data or [])
        except Exception as e:
            logger.warning("list_stale_processing_jobs (pending): %s", e)
        if max_runtime_minutes:
            deadline = (
                now - timedelta(minutes=int(max_runtime_minutes))
            ).isoformat()
            try:
                res = (
                    self.client.table("processing_jobs")
                    .select("*")
                    .eq("status", "processing")
                    .lt("started_at", deadline)
                    .limit(max_rows)
                    .execute()
                )
                out.extend(res.data or [])
            except Exception as e:
                logger.warning("list_stale_processing_jobs (wedged): %s", e)
        # A long-dead job matches both the heartbeat and the wall-clock query.
        # De-duplicate here rather than in the sweeper: handling one row twice
        # would burn two of its three attempts in a single sweep.
        seen: set = set()
        unique: List[Dict[str, Any]] = []
        for row in out:
            key = str(row.get("id"))
            if key in seen:
                continue
            seen.add(key)
            unique.append(row)
        return unique

    def list_active_processing_jobs(
        self, max_rows: int = 500,
    ) -> List[Dict[str, Any]]:
        """Everything in flight — the queue-depth half of the ops signal."""
        try:
            res = (
                self.client.table("processing_jobs")
                .select("id, status, enqueued_at, started_at")
                .in_("status", ["pending", "processing"])
                .limit(max_rows)
                .execute()
            )
            return res.data or []
        except Exception as e:
            logger.warning("list_active_processing_jobs: %s", e)
            return []

    # The admin panel's projection. NEVER add `payload` or `result` to it.
    #
    # `payload` holds storage paths and upload flags; `result` holds pipeline
    # output. The panel needs neither, and the smallest safe projection is the
    # one that cannot leak a field nobody reviewed. A future `select("*")`
    # here would silently widen an admin surface. (The admin pipeline panel
    # that read it was deleted on 2026-09-15, audit Q-A7; the projection
    # stays the smallest safe one for any future reader.)
    _ADMIN_JOB_FIELDS = (
        "id, kind, status, stage, percent, message, error, attempts, "
        "max_attempts, user_id, session_id, enqueued_at, started_at, "
        "finished_at, created_at"
    )

    def list_processing_jobs(
        self, *, status: Optional[str] = None, limit: int = 50,
        before: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Recent jobs for the admin panel, newest first. [] on any failure.

        KEYSET PAGINATION on `enqueued_at`, not OFFSET. The queue mutates
        while you page — jobs finish, new ones arrive — and OFFSET silently
        skips rows when the set shifts underneath it, so page 2 would be
        missing work that page 1 no longer holds. `before` is the previous
        page's oldest `enqueued_at`.

        BOUNDED BY CONSTRUCTION: limit is clamped to 100 here, at the data
        layer, rather than trusted from the caller. An ops surface must never
        be able to table-scan production, and a cap enforced only in the route
        is one refactor away from being absent.
        """
        try:
            capped = max(1, min(int(limit or 50), 100))
        except (TypeError, ValueError):
            capped = 50
        try:
            q = (self.client.table("processing_jobs")
                 .select(self._ADMIN_JOB_FIELDS))
            if status:
                q = q.eq("status", str(status))
            if before:
                q = q.lt("enqueued_at", str(before))
            res = (q.order("enqueued_at", desc=True)
                    .limit(capped).execute())
            return res.data or []
        except Exception as e:
            logger.warning("list_processing_jobs: %s", e)
            return []

    def list_recent_finished_processing_jobs(
        self, max_rows: int = 200,
    ) -> List[Dict[str, Any]]:
        """Recent terminal jobs — the latency half of the ops signal."""
        try:
            res = (
                self.client.table("processing_jobs")
                .select("id, status, enqueued_at, started_at, finished_at, "
                        "error")
                .in_("status", ["completed", "failed"])
                .order("finished_at", desc=True)
                .limit(max_rows)
                .execute()
            )
            return res.data or []
        except Exception as e:
            logger.warning("list_recent_finished_processing_jobs: %s", e)
            return []

    def create_model_training_run(
        self,
        *,
        run_type: str,
        status: str,
        input_count: int = 0,
        metadata: Optional[Dict[str, Any]] = None,
        created_by: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        now = datetime.now(timezone.utc).isoformat()
        payload = {
            "run_type": run_type,
            "status": status,
            "input_count": max(0, int(input_count)),
            "metadata": metadata or {},
            "created_by": created_by,
            "created_at": now,
            "updated_at": now,
        }
        if status == "running":
            payload["started_at"] = now
        if status in ("completed", "failed", "skipped"):
            payload["finished_at"] = now
        res = self.client.table("model_training_runs").insert(payload).execute()
        return res.data[0] if res.data else None

    def update_model_training_run(
        self,
        run_id: str,
        *,
        status: str,
        input_count: Optional[int] = None,
        output_artifact_ref: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        now = datetime.now(timezone.utc).isoformat()
        payload: Dict[str, Any] = {"status": status, "updated_at": now}
        if status == "running":
            payload["started_at"] = now
            payload["finished_at"] = None
        if status in ("completed", "failed", "skipped"):
            payload["finished_at"] = now
        if input_count is not None:
            payload["input_count"] = max(0, int(input_count))
        if output_artifact_ref is not None:
            payload["output_artifact_ref"] = output_artifact_ref
        if metadata is not None:
            payload["metadata"] = metadata
        if error is not None:
            payload["error"] = error
        res = self.client.table("model_training_runs").update(payload).eq("id", run_id).execute()
        return res.data[0] if res.data else None

    def get_latest_model_training_run(self, run_type: str) -> Optional[Dict[str, Any]]:
        res = (
            self.client.table("model_training_runs")
            .select("*")
            .eq("run_type", run_type)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        return res.data[0] if res.data else None

    # ---------- Runtime config ----------

    def get_runtime_config(self, key: str) -> Optional[str]:
        try:
            res = (
                self.client.table("runtime_config")
                .select("value")
                .eq("key", key)
                .limit(1)
                .execute()
            )
            if not res.data:
                return None
            value = res.data[0].get("value")
            if value is None:
                return None
            text = str(value).strip()
            return text or None
        except Exception as e:
            if self._is_relation_missing_error(e):
                return None
            logger.warning("get_runtime_config failed for key=%s: %s", key, e)
            return None

    def upsert_runtime_config(
        self,
        *,
        key: str,
        value: str,
        updated_by: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        payload = {
            "key": key,
            "value": value,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "updated_by": updated_by,
            "metadata": metadata or {},
        }
        try:
            res = (
                self.client.table("runtime_config")
                .upsert(payload, on_conflict="key")
                .execute()
            )
            return res.data[0] if res.data else payload
        except Exception as e:
            if self._is_relation_missing_error(e):
                logger.warning("runtime_config table missing; run migrations/add_runtime_model_config.sql")
                return None
            raise

    def promote_runtime_surface_model(
        self,
        *,
        key: str,
        value: str,
        updated_by: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Write one runtime_config MODEL key, through the only door there is.

        LEGACY-1 / R-13 (audit 2026-09-22). Migration 0352 put a BEFORE
        INSERT OR UPDATE trigger on `runtime_config` that refuses a write to
        any `openai_surface_model_%`, `openai_chat_model` or
        `openai_copilot_model` row unless the transaction carries a GUC only
        `promote_runtime_surface_model_v1` sets. `upsert_runtime_config`
        above therefore no longer reaches these keys, by design: a table this
        table's writes can change the words in a speaker's Ideal Text should
        not have a generic writer.

        Returns None when the RPC is absent (a database that has not taken
        0352 yet) so the caller can name the migration; PostgREST reports
        that as PGRST202 rather than as a missing relation, so both shapes
        are matched. Every other failure — the guard refusing, a malformed
        prompt binding — is raised, because a promotion that silently did
        nothing is the failure mode this whole change exists to remove.
        """
        try:
            res = self.client.rpc(
                "promote_runtime_surface_model_v1",
                {
                    "p_key": key,
                    "p_value": value,
                    "p_updated_by": updated_by,
                    "p_metadata": metadata or {},
                },
            ).execute()
        except Exception as e:
            text = str(e).lower()
            if self._is_relation_missing_error(e) or "pgrst202" in text or (
                "could not find the function" in text
            ):
                logger.warning(
                    "promote_runtime_surface_model_v1 missing; run "
                    "migrations/guard_runtime_config_model_keys.sql",
                )
                return None
            raise
        return res.data if isinstance(res.data, dict) else None

    def v2_list_all_auth_user_ids(self, cap: int = 2000) -> List[str]:
        """Paginate GoTrue admin users; return ids (up to cap). Same pool as admin student list."""
        try:
            import httpx

            base = f"{config.SUPABASE_URL.rstrip('/')}/auth/v1/admin/users"
            out: List[str] = []
            seen: set[str] = set()
            page = 1
            per_page = min(1000, max(1, cap))
            while len(out) < cap:
                resp = httpx.get(
                    base,
                    params={"per_page": per_page, "page": page},
                    headers={
                        "Authorization": f"Bearer {config.SUPABASE_SERVICE_ROLE_KEY}",
                        "apikey": config.SUPABASE_SERVICE_ROLE_KEY,
                    },
                    timeout=30,
                )
                if resp.status_code != 200:
                    logger.warning(
                        "v2_list_all_auth_user_ids: auth list page %s failed: %s %s",
                        page,
                        resp.status_code,
                        resp.text[:200],
                    )
                    break
                data = resp.json()
                users = data.get("users") or (data.get("data") or {}).get("users") or []
                if not users:
                    break
                for u in users:
                    uid = u.get("id")
                    if not uid or uid in seen:
                        continue
                    seen.add(uid)
                    out.append(str(uid))
                    if len(out) >= cap:
                        break
                if len(users) < per_page:
                    break
                page += 1
            return out
        except Exception as e:
            logger.warning("v2_list_all_auth_user_ids: %s", e)
            return []

    def create_charisma_snippet(
        self,
        session_id: str,
        user_id: str | None,
        recording_id: str,
        start_offset_ms: int,
        duration_ms: int,
        audio_segment_path: str,
        metrics: dict | None = None,
        transcript: str | None = None,
        words: list | None = None,
    ) -> dict | None:
        """Create a new charisma snippet record (unlabeled by default).

        Args:
            user_id: Real user UUID, or None for internal annotation data.
            metrics: Optional JSONB dict of pre-computed acoustic metrics
                     (wpm, pause_ms, dynamic_db, emphasis_per_min, energy_ratio,
                      pitch_center_st, pitch_frame_count, voiced_duration_sec).
            words: Optional word-level Whisper timestamps [{word, start, end}]
                   (seconds), for #6 per-slide transcript sync. Stored in the
                   `words` JSONB column (migrations/add_snippet_transcripts.sql).
                   If that column isn't applied yet, the insert retries WITHOUT
                   words so a recording is never lost to a pending migration.
        """
        def _insert(payload):
            res = (
                self.client.table(SNIPPETS_TABLE)
                .insert(payload)
                .execute()
            )
            return res.data[0] if res.data and len(res.data) > 0 else None

        try:
            payload = {
                "session_id": session_id,
                "recording_id": recording_id,
                "start_offset_ms": start_offset_ms,
                "duration_ms": duration_ms,
                "audio_segment_path": audio_segment_path,
                "snippet_type": "unlabeled",
            }
            if user_id:
                payload["user_id"] = user_id
            if metrics:
                payload["metrics"] = metrics
            if transcript:
                payload["transcript"] = transcript
            if words:
                payload["words"] = words
            try:
                return _insert(payload)
            except Exception as col_err:
                # The `words` column may not be migrated in this env yet — never
                # let it cost us the snippet. Retry without words (#6 degrades to
                # the legacy whole-snippet per-slide bucketing).
                if "words" in payload:
                    logger.warning(
                        "create_charisma_snippet: retry without words "
                        "(run add_snippet_transcripts.sql?): %s", col_err,
                    )
                    payload.pop("words", None)
                    return _insert(payload)
                raise
        except Exception as e:
            logger.error(f"create_charisma_snippet failed: {e}")
            return None

    def create_charisma_snippets_bulk(self, rows: list | None) -> list:
        """Bulk-insert charisma_snippets in ONE round-trip (pieces-canonical
        2026-07-14 — a long take is ~270 pieces; N sequential inserts would
        add 15-40s to the synchronous upload). Each row dict mirrors
        create_charisma_snippet's payload keys (session_id, user_id?,
        recording_id, start_offset_ms, duration_ms, audio_segment_path,
        metrics?, transcript?, words?).

        Returns the inserted ids in INPUT ORDER (Supabase preserves insert
        order in the returned rows). On a bulk failure it retries the whole
        batch WITHOUT the `words` column (pending migration), then finally
        falls back to per-row create_charisma_snippet so a recording is never
        lost. Missing ids come back as None (aligned by index)."""
        rows = rows or []
        if not rows:
            return []

        def _payload(r, with_words=True):
            p = {
                "session_id": r.get("session_id"),
                "recording_id": r.get("recording_id"),
                "start_offset_ms": r.get("start_offset_ms"),
                "duration_ms": r.get("duration_ms"),
                "audio_segment_path": r.get("audio_segment_path"),
                "snippet_type": "unlabeled",
            }
            if r.get("user_id"):
                p["user_id"] = r["user_id"]
            if r.get("metrics"):
                p["metrics"] = r["metrics"]
            if r.get("transcript"):
                p["transcript"] = r["transcript"]
            if with_words and r.get("words"):
                p["words"] = r["words"]
            return p

        def _bulk(with_words):
            res = (
                self.client.table(SNIPPETS_TABLE)
                .insert([_payload(r, with_words) for r in rows])
                .execute()
            )
            data = res.data or []
            return [d.get("id") for d in data]

        try:
            ids = _bulk(True)
            if len(ids) == len(rows):
                return ids
            # Partial/empty return → fall through to the safe per-row path.
            raise RuntimeError(f"bulk returned {len(ids)} of {len(rows)}")
        except Exception as bulk_err:
            _e = str(bulk_err).lower()
            if "words" in _e:
                try:
                    ids = _bulk(False)
                    if len(ids) == len(rows):
                        logger.warning(
                            "create_charisma_snippets_bulk: inserted without "
                            "words (run add_snippet_transcripts.sql?)")
                        return ids
                except Exception as e2:
                    logger.warning(
                        "create_charisma_snippets_bulk: no-words retry "
                        "failed: %s", e2)
            logger.warning(
                "create_charisma_snippets_bulk: bulk failed (%s) — per-row "
                "fallback", bulk_err)
            out = []
            for r in rows:
                row = self.create_charisma_snippet(
                    session_id=r.get("session_id"), user_id=r.get("user_id"),
                    recording_id=r.get("recording_id"),
                    start_offset_ms=r.get("start_offset_ms"),
                    duration_ms=r.get("duration_ms"),
                    audio_segment_path=r.get("audio_segment_path"),
                    metrics=r.get("metrics"), transcript=r.get("transcript"),
                    words=r.get("words"),
                )
                out.append(row.get("id") if row else None)
            return out

    def insert_candidate_windows(self, rows: list | None) -> int:
        """Persist the FULL candidate-window pool for a recording (automation-
        audit fix #1 — the 'offered vs chosen' selection signal). Append-only,
        training-bound (never read by any user/coach surface; AC-9: storing !=
        surfacing). Idempotent per (recording_id, start_offset_ms) — a re-process
        no-ops via ON CONFLICT DO NOTHING.

        Best-effort: returns the count written; 0 on missing table / bad input /
        error — NEVER raises (live-loop fence: capture must not break the
        recording pipeline). See migrations/add_candidate_windows.sql."""
        if not rows:
            return 0
        clean = [
            r for r in rows
            if isinstance(r, dict) and r.get("start_offset_ms") is not None
        ]
        if not clean:
            return 0
        try:
            res = self.client.table("candidate_windows").upsert(
                clean,
                on_conflict="recording_id,start_offset_ms",
                ignore_duplicates=True,
            ).execute()
            # Report ACTUAL inserted rows when the client returns them (a
            # re-process skips dups via ON CONFLICT DO NOTHING) so the telemetry
            # doesn't overcount; fall back to attempted on older clients.
            data = getattr(res, "data", None)
            return len(data) if isinstance(data, list) else len(clean)
        except Exception as e:
            err_low = str(e).lower()
            if "candidate_windows" in err_low and (
                "does not exist" in err_low or "pgrst" in err_low
                or "42p01" in err_low
            ):
                logger.warning(
                    "insert_candidate_windows: table missing (run "
                    "migrations/add_candidate_windows.sql) — pool not captured",
                )
                return 0
            logger.warning("insert_candidate_windows failed: %s", e)
            return 0

    def insert_rejected_take(
        self, *, reason: str | None,
        duration_sec=None, voiced_sec=None, thresholds=None,
        user_id=None, owner_principal_id=None, project_id=None,
    ) -> bool:
        """Log a gate-rejected take's METRICS (automation-audit fix #2c —
        survivorship: gate-failed takes were dropped before any storage, so we
        had no 'bad take' record). Metrics ONLY, never audio. Best-effort,
        append-only, missing-table-safe; NEVER raises (live-loop fence). See
        migrations/add_rejected_takes.sql."""
        row: dict = {"reason": reason}
        if user_id:
            row["user_id"] = user_id
        if owner_principal_id:
            row["owner_principal_id"] = str(owner_principal_id)
        if project_id:
            row["project_id"] = str(project_id)
        for k, v in (("duration_sec", duration_sec), ("voiced_sec", voiced_sec)):
            if v is not None:
                try:
                    row[k] = float(v)
                except (TypeError, ValueError):
                    pass
        if isinstance(thresholds, dict):
            row["thresholds"] = thresholds
        try:
            self.client.table("rejected_takes").insert(row).execute()
            return True
        except Exception as e:
            err_low = str(e).lower()
            if "rejected_takes" in err_low and (
                "does not exist" in err_low or "pgrst" in err_low
                or "42p01" in err_low
            ):
                logger.warning(
                    "insert_rejected_take: table missing (run "
                    "migrations/add_rejected_takes.sql) — reject not captured",
                )
                return False
            logger.warning("insert_rejected_take failed: %s", e)
            return False

    # ── willab — coach-video corpus (Subsystem V) ─────────────────────────
    #
    # Private/training-bound lane (RLS service-role only). Capture only; never
    # read by a user surface. See migrations/add_coach_video_assets.sql +
    # services/coach_video_capture.py. All best-effort: NEVER raise into the
    # video-upload path (live-loop fence).

    def get_coach_video_asset_by_idempotency_key(
        self, key: Optional[str],
    ) -> Optional[dict]:
        """The asset for a client record-action key (retry dedupe). None on
        missing table / unknown key / error."""
        if not key:
            return None
        try:
            res = (
                self.client.table("coach_video_assets")
                .select("*")
                .eq("upload_idempotency_key", str(key))
                .limit(1)
                .execute()
            )
            rows = res.data or []
            return rows[0] if rows else None
        except Exception as e:
            err_low = str(e).lower()
            if "coach_video_assets" in err_low and (
                "does not exist" in err_low or "pgrst" in err_low
                or "42p01" in err_low
            ):
                return None
            logger.warning("get_coach_video_asset_by_idempotency_key failed: %s", e)
            return None

    def get_current_coach_video_asset(
        self, session_id: str, content_type: str,
        snippet_id: Optional[str] = None,
    ) -> Optional[dict]:
        """The CURRENT (is_current) take for a session/content (+snippet for
        breakthrough). None on missing table / none / error."""
        if not session_id or not content_type:
            return None
        try:
            q = (
                self.client.table("coach_video_assets")
                .select("*")
                .eq("session_id", session_id)
                .eq("content_type", content_type)
                .eq("is_current", True)
            )
            if snippet_id:
                q = q.eq("snippet_id", snippet_id)
            else:
                q = q.is_("snippet_id", "null")
            res = q.limit(1).execute()
            rows = res.data or []
            return rows[0] if rows else None
        except Exception as e:
            err_low = str(e).lower()
            if "coach_video_assets" in err_low and (
                "does not exist" in err_low or "pgrst" in err_low
                or "42p01" in err_low
            ):
                return None
            logger.warning("get_current_coach_video_asset failed: %s", e)
            return None

    def insert_coach_video_asset(self, row: dict) -> Optional[dict]:
        """Append a coach-video TAKE. Returns the created row (with id) or None on
        missing table / error. Best-effort — never raises."""
        if not isinstance(row, dict) or not row.get("session_id"):
            return None
        try:
            res = self.client.table("coach_video_assets").insert(row).execute()
            return (res.data or [None])[0]
        except Exception as e:
            err_low = str(e).lower()
            if "coach_video_assets" in err_low and (
                "does not exist" in err_low or "pgrst" in err_low
                or "42p01" in err_low
            ):
                logger.warning(
                    "insert_coach_video_asset: table missing (run "
                    "migrations/add_coach_video_assets.sql) — not captured",
                )
                return None
            logger.warning("insert_coach_video_asset failed: %s", e)
            return None

    def supersede_coach_video_asset(
        self, prev_id: str, new_id: str,
    ) -> bool:
        """Mark a prior take as superseded by a new one (is_current=false +
        superseded_by). Best-effort → False on error."""
        if not prev_id or not new_id:
            return False
        try:
            self.client.table("coach_video_assets").update(
                {"is_current": False, "superseded_by": str(new_id)}
            ).eq("id", str(prev_id)).execute()
            return True
        except Exception as e:
            logger.warning("supersede_coach_video_asset failed prev=%s: %s", prev_id, e)
            return False

    def update_coach_video_transcript(
        self, asset_id: str, transcript: Optional[str], status: str,
    ) -> bool:
        """Backfill the async transcript + status. Best-effort → False on error."""
        if not asset_id:
            return False
        try:
            self.client.table("coach_video_assets").update(
                {"transcript": transcript, "transcription_status": status}
            ).eq("id", str(asset_id)).execute()
            return True
        except Exception as e:
            logger.warning("update_coach_video_transcript failed asset=%s: %s", asset_id, e)
            return False

    def get_current_coach_video_assets_for_session(
        self, session_id: str,
    ) -> list[dict]:
        """All CURRENT takes for a session (publish snapshot). [] on missing
        table / none / error."""
        if not session_id:
            return []
        try:
            res = (
                self.client.table("coach_video_assets")
                .select("id, content_type, snippet_id, comment_text_at_publish")
                .eq("session_id", session_id)
                .eq("is_current", True)
                .execute()
            )
            return res.data or []
        except Exception as e:
            err_low = str(e).lower()
            if "coach_video_assets" in err_low and (
                "does not exist" in err_low or "pgrst" in err_low
                or "42p01" in err_low
            ):
                return []
            logger.warning("get_current_coach_video_assets_for_session failed: %s", e)
            return []

    def set_coach_video_comment_at_publish(
        self, asset_id: str, text: Optional[str],
    ) -> bool:
        """Write-once the FINAL delivered comment at publish (only when currently
        NULL, so a re-publish never clobbers the first delivered text).
        Best-effort → False on error/no-op."""
        if not asset_id or not text:
            return False
        try:
            res = (
                self.client.table("coach_video_assets")
                .update({"comment_text_at_publish": text})
                .eq("id", str(asset_id))
                .is_("comment_text_at_publish", "null")
                .execute()
            )
            return bool(res.data)
        except Exception as e:
            logger.warning("set_coach_video_comment_at_publish failed asset=%s: %s", asset_id, e)
            return False

    def get_snippets_by_session(self, session_id: str, *,
                                strict: bool = False) -> List[dict]:
        """Get all snippets for a session, ordered by start time.

        ``strict=True`` re-raises a failed read instead of returning [] (the
        Album refresh must not read "could not read" as "no moments")."""
        try:
            result = self._execute_with_retry(
                lambda: (
                    self.client.table(SNIPPETS_TABLE)
                    .select("*")
                    .eq("session_id", session_id)
                    .order("start_offset_ms", desc=False)
                ),
                label="get_snippets_by_session",
            )
            return result.data if result.data else []
        except Exception as e:
            logger.error(f"get_snippets_by_session failed: {e}")
            if strict:
                raise
            return []

    def get_snippets_by_sessions(
        self, session_ids, *, include_words: bool = False,
    ) -> dict:
        """Batch read — ALL snippets for many sessions in ONE query per 100 ids
        (kills the N+1 on /v2/user/strengths). Returns
        {session_id: [snippets ordered by start_offset_ms]}.

        Excludes the heavy `words` JSONB by default — the Trainings list reads
        the precomputed slide_transcripts (#A), so per-snippet words aren't
        needed there. Pass include_words=True where the per-snippet split is
        used. Best-effort: {} on hiccup; falls back to select(*) if the slim
        projection trips a missing column."""
        ids = [str(s) for s in (session_ids or []) if s]
        if not ids:
            return {}
        slim = ("id, session_id, start_offset_ms, duration_ms, transcript, "
                "audio_segment_path, metrics, snippet_type")
        cols = "*" if include_words else slim
        # Pieces-canonical (2026-07-14): a session can carry ~15-270 piece
        # rows (was ≤10 windows), so 100 sessions per query can exceed
        # PostgREST's server-side max-rows (default 1000) — which TRUNCATES
        # SILENTLY, and because rows are ordered by start_offset_ms the
        # dropped rows are systematically the ENDS of talks. Two guards:
        # smaller id chunks + explicit .range() pagination until a short page.
        _page = 1000
        out: dict = {}
        try:
            for i in range(0, len(ids), 20):
                chunk = ids[i:i + 20]
                offset = 0
                while True:
                    try:
                        res = (
                            self.client.table(SNIPPETS_TABLE)
                            .select(cols)
                            .in_("session_id", chunk)
                            .order("start_offset_ms", desc=False)
                            .order("id", desc=False)  # total order for paging
                            .range(offset, offset + _page - 1)
                            .execute()
                        )
                    except Exception:
                        # Slim projection hit a missing column → fall back to *
                        # for the rest of the batch (still paged).
                        cols = "*"
                        res = (
                            self.client.table(SNIPPETS_TABLE)
                            .select("*")
                            .in_("session_id", chunk)
                            .order("start_offset_ms", desc=False)
                            .order("id", desc=False)
                            .range(offset, offset + _page - 1)
                            .execute()
                        )
                    rows = res.data or []
                    for r in rows:
                        out.setdefault(str(r.get("session_id")), []).append(r)
                    if len(rows) < _page:
                        break
                    offset += _page
            return out
        except Exception as e:
            logger.warning(
                "get_snippets_by_sessions failed (%d ids): %s", len(ids), e,
            )
            return {}

    def get_snippets_by_user(self, user_id: str, limit: int = 100, offset: int = 0) -> List[dict]:
        """Get all snippets for a user, paginated, ordered by creation date (newest first)."""
        try:
            result = (
                self.client.table(SNIPPETS_TABLE)
                .select("*")
                .eq("user_id", user_id)
                .order("created_at", desc=True)
                .limit(limit)
                .offset(offset)
                .execute()
            )
            return result.data if result.data else []
        except Exception as e:
            logger.error(f"get_snippets_by_user failed: {e}")
            return []

    def get_snippets_with_comments_by_session(self, session_id: str) -> List[dict]:
        """Get only snippets that have admin comments (used for /results page).

        Per docs/ARCHITECTURE_SINGLE_SOURCE_OF_TRUTH.md §6: whitespace-
        only admin_comment is treated as "no comment". PostgREST's
        NOT NULL filter can't express TRIM(...) <> '' so we apply the
        strip-filter in Python after the DB query.
        """
        try:
            result = (
                self.client.table(SNIPPETS_TABLE)
                .select("*")
                .eq("session_id", session_id)
                .not_.is_("admin_comment", "null")
                .order("start_offset_ms", desc=False)
                .execute()
            )
            rows = result.data or []
            return [r for r in rows if (r.get("admin_comment") or "").strip()]
        except Exception as e:
            logger.error(f"get_snippets_with_comments_by_session failed: {e}")
            return []

    def get_snippet_by_id(
        self,
        snippet_id: str,
        user_id: str | None = None,
    ) -> dict | None:
        """Owner-scoped fetch of one charisma_snippets row by id.

        When user_id is provided we filter on it for ownership; pass None
        from admin contexts that need to read any snippet.
        """
        try:
            q = self.client.table(SNIPPETS_TABLE).select("*").eq("id", snippet_id)
            if user_id:
                q = q.eq("user_id", user_id)
            result = q.limit(1).execute()
            return result.data[0] if result.data else None
        except Exception as e:
            logger.warning(f"get_snippet_by_id failed: {e}")
            return None

    def update_snippet_comment(
        self,
        snippet_id: str,
        admin_comment: str | None,
        snippet_type: str,
        admin_user_id: str | None,
        acceptance_mode: str | None = None,
    ) -> dict | None:
        """Update a snippet's comment, type, admin user, and
        optional RLHF acceptance_mode.

        ``acceptance_mode``:
          'accepted_as_is'  — admin saved the AI draft without
                              changing it (positive RLHF signal).
          'admin_corrected' — admin edited the draft before saving
                              (correction trajectory; paired with
                              ai_draft_admin_comment as the
                              training (predicted, final) row).
          None              — caller didn't classify; column stays
                              unchanged (or NULL on first write).
                              Used by legacy callers + the
                              auto-promote-drafts path that
                              doesn't have admin intent to
                              record.

        ``admin_comment_acceptance_set_at`` is stamped iff
        acceptance_mode is not None.
        """
        try:
            patch: dict = {
                "admin_comment": admin_comment,
                "snippet_type": snippet_type,
                "admin_user_id": admin_user_id,
            }
            if acceptance_mode is not None:
                patch["admin_comment_acceptance_mode"] = acceptance_mode
                patch["admin_comment_acceptance_set_at"] = (
                    datetime.now(timezone.utc).isoformat()
                )
            result = (
                self.client.table(SNIPPETS_TABLE)
                .update(patch)
                .eq("id", snippet_id)
                .execute()
            )
            if result.data and len(result.data) > 0:
                return result.data[0]
            return None
        except Exception as e:
            err_low = str(e).lower()
            if (
                "admin_comment_acceptance_mode" in err_low
                or "admin_comment_acceptance_set_at" in err_low
                or "pgrst204" in err_low
            ):
                # Migration not yet run in this environment — retry
                # without the new columns so existing admin tooling
                # keeps working. The acceptance signal is lost for
                # this row, which is the expected pre-migration
                # behaviour.
                logger.warning(
                    "update_snippet_comment: acceptance columns "
                    "missing (migration pending?), retrying "
                    "without — sid=%s",
                    snippet_id,
                )
                try:
                    fallback = {
                        "admin_comment": admin_comment,
                        "snippet_type": snippet_type,
                        "admin_user_id": admin_user_id,
                    }
                    result = (
                        self.client.table(SNIPPETS_TABLE)
                        .update(fallback)
                        .eq("id", snippet_id)
                        .execute()
                    )
                    if result.data and len(result.data) > 0:
                        return result.data[0]
                    return None
                except Exception as e2:
                    logger.error(
                        f"update_snippet_comment fallback failed: {e2}"
                    )
                    return None
            logger.error(f"update_snippet_comment failed: {e}")
            return None

    def update_snippet_follow_up_question(
        self,
        snippet_id: str,
        follow_up_question: str | None,
    ) -> dict | None:
        """Store (or clear) the pre-generated follow-up question on a snippet.

        Called automatically after labeling, or manually from the admin panel.
        Returns the updated row, or None on failure.
        """
        try:
            result = (
                self.client.table(SNIPPETS_TABLE)
                .update({
                    "follow_up_question": follow_up_question,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                })
                .eq("id", snippet_id)
                .execute()
            )
            return result.data[0] if result.data else None
        except Exception as e:
            logger.error("update_snippet_follow_up_question failed for %s: %s", snippet_id, e)
            return None

    # ── Phase 10: AI-draft + implicit-approval helpers ────────────────

    def create_user_uploaded_file(
        self,
        *,
        user_id: str,
        session_id: str | None,
        r2_bucket: str,
        r2_key: str,
        r2_url: str | None,
        file_name: str,
        file_type: str,
        content_type: str | None,
        file_size_bytes: int | None,
    ) -> Optional[dict]:
        """Insert a user_uploaded_files row.

        Owner-scoping is enforced at the row level via ``user_id``;
        the caller (route handler) is responsible for taking
        ``user_id`` from the authenticated request, not from the
        request body.

        Returns the inserted row on success, ``None`` on failure
        (logs the error so the upload endpoint can surface a
        generic 500 without leaking schema details).
        """
        try:
            payload = {
                "user_id": user_id,
                "session_id": session_id,
                "r2_bucket": r2_bucket,
                "r2_key": r2_key,
                "r2_url": r2_url,
                "file_name": file_name,
                "file_type": file_type,
                "content_type": content_type,
                "file_size_bytes": file_size_bytes,
            }
            result = (
                self.client.table("user_uploaded_files")
                .insert(payload)
                .execute()
            )
            if result.data and len(result.data) > 0:
                return result.data[0]
            return None
        except Exception as e:
            logger.error("create_user_uploaded_file failed: %s", e)
            return None

    def list_user_uploaded_files_for_user(
        self,
        user_id: str,
        *,
        limit: int = 200,
        offset: int = 0,
    ) -> list[dict]:
        """Return user_uploaded_files rows for ``user_id``, newest first.

        Backs the admin Files tab. Soft-deleted rows (deleted_at
        not null, per Task 9's DELETE endpoint) are excluded so the
        admin never sees them in the list.

        Task 9 pagination — caller passes the FE's ``limit`` AND we
        fetch ``limit + 1`` so the route handler can compute
        ``has_more`` without a second count query. Caller is
        responsible for truncating the response slice to ``limit``
        before serialising. Default limit of 200 matches the
        pre-pagination behaviour for callers that don't paginate.
        """
        try:
            lim = max(1, int(limit))
            off = max(0, int(offset))
            # Fetch one extra so the caller can compute has_more
            # without a separate count() — saves one round-trip.
            fetch_count = lim + 1
            result = (
                self.client.table("user_uploaded_files")
                .select("*")
                .eq("user_id", user_id)
                .is_("deleted_at", "null")
                .order("created_at", desc=True)
                .range(off, off + fetch_count - 1)
                .execute()
            )
            rows = result.data or []
            # The deleted_at column may not exist yet during the
            # rollout window. Re-issue the query without the
            # filter so the page keeps working pre-migration.
            return rows
        except Exception as e:
            # Detect the "column doesn't exist" case (migration
            # pending) and retry without the soft-delete filter.
            err_low = str(e).lower()
            if "deleted_at" in err_low or "pgrst204" in err_low:
                logger.warning(
                    "list_user_uploaded_files_for_user: deleted_at "
                    "column missing (run migrations/add_deleted_"
                    "at_to_user_uploaded_files.sql) — falling back "
                    "to unfiltered list user=%s",
                    user_id,
                )
                try:
                    lim = max(1, int(limit))
                    off = max(0, int(offset))
                    fetch_count = lim + 1
                    result = (
                        self.client.table("user_uploaded_files")
                        .select("*")
                        .eq("user_id", user_id)
                        .order("created_at", desc=True)
                        .range(off, off + fetch_count - 1)
                        .execute()
                    )
                    return result.data or []
                except Exception as fallback_err:
                    logger.warning(
                        "list_user_uploaded_files_for_user fallback "
                        "failed user=%s err=%s",
                        user_id, fallback_err,
                    )
                    return []
            logger.warning(
                "list_user_uploaded_files_for_user failed user=%s err=%s",
                user_id, e,
            )
            return []

    def soft_delete_user_uploaded_file(
        self,
        file_id: str,
        user_id: str,
    ) -> Optional[dict]:
        """Owner-scoped soft delete on user_uploaded_files.

        Marks the row with ``deleted_at = NOW()`` instead of
        DELETE'ing — the weekly hard-delete cron sweeps soft-
        deleted rows + their R2 bytes. Two-phase delete:

          (1) admin clicks → row.deleted_at set; the API filters
              it out of the Files list immediately, user-facing
              surfaces stop linking to it.
          (2) ~weekly cron → object removed from R2, row removed
              from DB.

        Owner scope is enforced inline (user_id eq) so a request
        body that targets a different user's file_id with the
        wrong user_id quietly no-ops. Caller must verify the
        admin-context user_id matches the path user_id BEFORE
        calling this — admins delete other users' files, but only
        through the admin-scoped route, which provides the
        authoritative user_id.

        Returns the updated row on success, None on failure or no-
        match. None is sufficient information for the route to
        return 404 — admin doesn't need to distinguish "not yours"
        from "doesn't exist" (existence leak protection).
        """
        if not file_id or not user_id:
            return None
        try:
            from datetime import timezone, datetime
            now_utc = datetime.now(timezone.utc).isoformat()
            result = (
                self.client.table("user_uploaded_files")
                .update({"deleted_at": now_utc})
                .eq("id", file_id)
                .eq("user_id", user_id)
                .is_("deleted_at", "null")
                .execute()
            )
            if result.data and len(result.data) > 0:
                return result.data[0]
            return None
        except Exception as e:
            err_low = str(e).lower()
            if "deleted_at" in err_low or "pgrst204" in err_low:
                logger.warning(
                    "soft_delete_user_uploaded_file: deleted_at "
                    "column missing (run migrations/add_deleted_"
                    "at_to_user_uploaded_files.sql) file=%s user=%s",
                    file_id, user_id,
                )
                return None
            logger.error(
                "soft_delete_user_uploaded_file failed file=%s "
                "user=%s err=%s",
                file_id, user_id, e,
            )
            return None

    def get_pending_review_session_for_user(
        self,
        user_id: str,
    ) -> Optional[dict]:
        """Return the user's existing pending-admin-review session,
        if any.

        Pending = bound to this user_id AND results_published_at IS
        NULL AND has at least one non-skipped snippet (so a freshly-
        aborted upload that never made it to snippet extraction
        doesn't block new attempts indefinitely).

        Used by upload endpoints (chat/upload-answer + coaching/
        trial-recording) to prevent the user from stacking a
        second session on top of the first while the coach is
        still reviewing. The frontend's PENDING_COACH state should
        already gate the mic, but the backend check is the
        defence-in-depth layer for cases where the frontend is
        stale, the user has two tabs open, or a third-party
        client bypasses the UI.

        Returns the most-recent qualifying session row or None.
        Failure logs + returns None — the caller treats None as
        "no block, proceed with upload" so a transient query
        failure doesn't lock the user out.
        """
        try:
            sessions = (
                self.client.table("v2_sessions")
                .select("id, created_at, status, results_published_at")
                .eq("user_id", user_id)
                .is_("results_published_at", "null")
                .order("created_at", desc=True)
                .limit(10)
                .execute()
                .data
            ) or []
        except Exception as e:
            logger.warning(
                "get_pending_review_session_for_user query failed "
                "uid=%s err=%s — allowing upload to proceed", user_id, e,
            )
            return None

        if not sessions:
            return None

        # Confirm at least one of those sessions has actual snippet
        # content. A session row with zero snippets is either a
        # freshly-aborted upload OR a placeholder created by the
        # endpoint just before snippet extraction failed — neither
        # should block a clean retry.
        session_ids = [s["id"] for s in sessions]
        try:
            snip_rows = (
                self.client.table(SNIPPETS_TABLE)
                .select("session_id")
                .in_("session_id", session_ids)
                .eq("is_skipped", False)
                .limit(50)
                .execute()
                .data
            ) or []
        except Exception as e:
            logger.warning(
                "get_pending_review_session_for_user snippet probe "
                "failed uid=%s err=%s — allowing upload", user_id, e,
            )
            return None

        sessions_with_snippets = {r.get("session_id") for r in snip_rows if r.get("session_id")}
        for s in sessions:
            if s["id"] in sessions_with_snippets:
                return s
        return None

    # ── Casual Voice Benchmarks (Phase Stress-Contrast / BE-3) ──────
    #
    # Silent acoustic snapshots of the user speaking casually during
    # /v2/chat/query (multipart path). Paired with
    # services.casual_voice_analytics.analyze_casual_audio_async (the
    # daemon-thread writer) and surfaced by compute_stress_contrast
    # below.

    def insert_casual_voice_benchmark(
        self,
        *,
        user_id: str,
        session_id: Optional[str],
        metrics: dict,
        transcript_source: str,
        audio_duration_ms: Optional[int],
        audio_storage_path: Optional[str] = None,
    ) -> Optional[dict]:
        """Persist one casual-voice metrics row. Returns the inserted
        row, or None on any failure (caller is the fire-and-forget
        daemon thread — losing one row is non-fatal).
        """
        payload = {
            "user_id": user_id,
            "session_id": session_id,
            "metrics": metrics,
            "transcript_source": transcript_source,
            "audio_duration_ms": audio_duration_ms,
            "audio_storage_path": audio_storage_path,
        }
        try:
            result = (
                self.client.table("casual_voice_benchmarks")
                .insert(payload)
                .execute()
            )
            return result.data[0] if result.data else None
        except Exception as e:
            err_low = str(e).lower()
            if (
                "casual_voice_benchmarks" in err_low
                and ("does not exist" in err_low or "pgrst" in err_low)
            ):
                # Migration not yet applied in this environment —
                # silently no-op so /v2/chat/query keeps working
                # while the table catches up. Production has it; dev
                # branches that pulled the code before running the
                # SQL would otherwise spam Sentry on every chat send.
                logger.warning(
                    "insert_casual_voice_benchmark: table missing "
                    "(migration pending?) user=%s — skipping",
                    user_id,
                )
                return None
            logger.warning(
                "insert_casual_voice_benchmark failed user=%s err=%s",
                user_id, e,
            )
            return None

    def get_recent_casual_voice_metrics(
        self,
        user_id: str,
        limit: int = 5,
    ) -> List[dict]:
        """Last N casual-voice metric blobs for this user, newest
        first. Returns a list of the ``metrics`` JSONB dicts (just
        the metrics, not the wrapping row). Empty list on no rows or
        on failure (caller is the contrast aggregator, which already
        handles the empty case as "not enough samples").
        """
        try:
            result = (
                self.client.table("casual_voice_benchmarks")
                .select("metrics")
                .eq("user_id", user_id)
                .order("created_at", desc=True)
                .limit(int(limit))
                .execute()
            )
            return [
                r["metrics"]
                for r in (result.data or [])
                if isinstance(r.get("metrics"), dict)
            ]
        except Exception as e:
            logger.warning(
                "get_recent_casual_voice_metrics failed user=%s err=%s",
                user_id, e,
            )
            return []

    def get_recent_published_snippet_metrics(
        self,
        user_id: str,
        limit: int = 5,
    ) -> List[dict]:
        """Last N PUBLISHED charisma_snippets metric blobs for this
        user. "Published" = coach_label IS NOT NULL (admin has
        reviewed and labeled the snippet). This is the "official /
        high-stakes" side of the stress contrast.

        Returns dicts with the same keys
        /v2/user/results/<session_id> exposes:
        {wpm, fillers, pause_ms, dynamic_db, pitch_center, energy}.
        Empty list on failure or no rows.
        """
        try:
            # PM-9: this selected ONLY the six denormalized columns, which are
            # dead on the live path (services/snippet_values) — so every row
            # came back all-NULL and the caller's shared-key check below found
            # nothing, quietly reporting the contrast as underpowered forever.
            # `metrics`, `transcript` and `duration_ms` are what actually hold
            # the values, so they have to be selected for the resolver to work.
            from services.snippet_values import resolve_all
            result = (
                self.client.table(SNIPPETS_TABLE)
                # The six denormalized metric columns are NOT selected: they
                # are always NULL (nothing writes them) and migration 0254
                # drops them, at which point naming one here would make this
                # query error. resolve_all reads the blob; its column lookups
                # simply miss, before and after the drop.
                .select("metrics, transcript, duration_ms, created_at")
                .eq("user_id", user_id)
                .not_.is_("coach_label", "null")
                .order("created_at", desc=True)
                .limit(int(limit))
                .execute()
            )
            return [resolve_all(r) for r in result.data or []]
        except Exception as e:
            logger.warning(
                "get_recent_published_snippet_metrics failed "
                "user=%s err=%s",
                user_id, e,
            )
            return []

    def compute_stress_contrast(
        self,
        user_id: str,
    ) -> Optional[dict]:
        """median(last 5 published snippet metrics) − median(last 5
        casual voice metrics) for the keys that exist on both
        sides.

        Sign convention (PIN; documented in
        docs/PANEL-STATE-MATRIX.md): positive delta means OFFICIAL >
        CASUAL. So +wpm_delta = user speaks faster under pressure
        than when casual = likely a stress tell. Frontend renders
        accordingly.

        Returns None when EITHER side has fewer than 3 samples
        (insufficient signal for a meaningful median). Frontend uses
        None to omit the Stress Contrast section entirely — no
        "not enough data" placeholder.

        Pitch is intentionally OMITTED from the delta in v1:
        ``charisma_snippets.pitch_center`` is in Hz, while
        ``analyze_audio.pitch_center_st`` is in semitones. Comparing
        them directly produces nonsense. A future revision can
        unit-harmonize and add ``pitch_delta_st``.
        """
        import statistics

        official = self.get_recent_published_snippet_metrics(user_id, limit=5)
        casual = self.get_recent_casual_voice_metrics(user_id, limit=5)

        if len(official) < 3 or len(casual) < 3:
            return None

        def _median(rows: List[dict], key: str) -> Optional[float]:
            vals = [
                r.get(key)
                for r in rows
                if isinstance(r.get(key), (int, float))
            ]
            return float(statistics.median(vals)) if vals else None

        deltas: dict = {}
        # Keys that exist on BOTH sides with compatible units.
        # See docstring re: pitch omission.
        for key in ("wpm", "pause_ms", "dynamic_db"):
            o = _median(official, key)
            c = _median(casual, key)
            if o is not None and c is not None:
                deltas[f"{key}_delta"] = round(o - c, 3)

        if not deltas:
            # Samples on both sides but no shared metric keys had
            # numeric values — happens on legacy rows with NULL
            # metric columns. Treat as underpowered.
            return None

        return {
            "samples": {
                "official": len(official),
                "casual": len(casual),
            },
            "deltas": deltas,
            "sign_convention": "positive_delta_means_official_greater_than_casual",
        }

    # ── Coaching Directives Queue (Phase Directives-Queue / BE) ────
    #
    # User-level 5-step coaching arc. Admins POST an ordered list of
    # 5 questions via /v2/admin/users/<id>/directives-queue; the
    # chat / interview surface pops them one at a time via
    # pop_next_directive() and marks each exhausted. When the queue
    # is empty, those surfaces fall back to _generate_llm_question.
    #
    # Replaces the per-user single-question
    # user_settings.queued_override_question (removed in Week-1
    # cleanup) and the conceptually-misplaced snippet-level
    # next_question_1..5 columns (which never shipped to this
    # branch).

    def list_directives_queue(
        self,
        user_id: str,
    ) -> List[dict]:
        """Return the user's current arc, ordered by position ASC.
        Returns empty list when no queue exists OR the table is
        missing (pre-migration env).
        """
        try:
            result = (
                self.client.table("coaching_directives_queue")
                .select(
                    "id, position, intent_tag, question, "
                    "exhausted, created_at, created_by_admin_id"
                )
                .eq("user_id", user_id)
                .order("position", desc=False)
                .execute()
            )
            return list(result.data or [])
        except Exception as e:
            err_low = str(e).lower()
            if (
                "coaching_directives_queue" in err_low
                and ("does not exist" in err_low or "pgrst" in err_low)
            ):
                logger.warning(
                    "list_directives_queue: table missing "
                    "(migration pending?) user=%s — returning []",
                    user_id,
                )
                return []
            logger.warning(
                "list_directives_queue failed user=%s err=%s",
                user_id, e,
            )
            return []

    def replace_directives_queue(
        self,
        *,
        user_id: str,
        rows: List[dict],
        admin_user_id: Optional[str],
    ) -> List[dict]:
        """Atomic-ish replace: DELETE existing rows for user_id,
        then INSERT the new arc. Returns the inserted rows on
        success; empty list on failure.

        ``rows`` must each carry ``position`` (1..5), ``intent_tag``
        (non-empty str), ``question`` (non-empty str). The caller
        is responsible for validation; this method just persists
        what it's given.

        Atomicity caveat: Supabase python-postgrest doesn't expose
        BEGIN/COMMIT, so DELETE and INSERT are two HTTP round-trips.
        If the INSERT fails after the DELETE succeeded, the user
        ends up with NO queue — admin will see an empty list on
        the next GET and can re-POST. We log the half-state at
        WARNING so support can spot it. Acceptable for an
        admin-driven workflow (no concurrent writers).
        """
        try:
            (
                self.client.table("coaching_directives_queue")
                .delete()
                .eq("user_id", user_id)
                .execute()
            )
        except Exception as del_err:
            err_low = str(del_err).lower()
            if (
                "coaching_directives_queue" in err_low
                and ("does not exist" in err_low or "pgrst" in err_low)
            ):
                logger.warning(
                    "replace_directives_queue: table missing "
                    "(migration pending?) user=%s — skipping",
                    user_id,
                )
                return []
            logger.warning(
                "replace_directives_queue: DELETE failed user=%s err=%s",
                user_id, del_err,
            )
            return []

        if not rows:
            # POST with empty rows == effectively DELETE. Honor
            # silently so the admin UI can implement "clear" via
            # POST [] as an alternative to DELETE.
            return []

        payload = [
            {
                "user_id": user_id,
                "position": int(r["position"]),
                "intent_tag": (r.get("intent_tag") or "").strip(),
                "question": (r.get("question") or "").strip(),
                "exhausted": False,
                "created_by_admin_id": admin_user_id,
            }
            for r in rows
        ]
        try:
            result = (
                self.client.table("coaching_directives_queue")
                .insert(payload)
                .execute()
            )
            return list(result.data or [])
        except Exception as ins_err:
            logger.error(
                "replace_directives_queue: INSERT failed AFTER "
                "successful DELETE user=%s err=%s — user now has "
                "EMPTY queue; admin should re-POST",
                user_id, ins_err,
            )
            return []

    def clear_directives_queue(self, user_id: str) -> bool:
        """Delete the user's current arc. Returns True on success
        (including the "nothing to delete" case), False on real
        failure. Idempotent — calling on an empty queue is a no-op
        success.
        """
        try:
            (
                self.client.table("coaching_directives_queue")
                .delete()
                .eq("user_id", user_id)
                .execute()
            )
            return True
        except Exception as e:
            err_low = str(e).lower()
            if (
                "coaching_directives_queue" in err_low
                and ("does not exist" in err_low or "pgrst" in err_low)
            ):
                logger.warning(
                    "clear_directives_queue: table missing "
                    "(migration pending?) user=%s — treating as "
                    "no-op success",
                    user_id,
                )
                return True
            logger.warning(
                "clear_directives_queue failed user=%s err=%s",
                user_id, e,
            )
            return False

    def pop_next_directive(
        self,
        user_id: str,
    ) -> Optional[dict]:
        """Atomic-ish: find the lowest-position un-exhausted row
        for ``user_id``, mark it exhausted, return its
        ``{id, position, intent_tag, question}``. Returns None when
        the queue is empty OR fully exhausted OR the table is
        missing.

        Atomicity caveat: SELECT then UPDATE on two HTTP calls.
        Race window between them = "if two next-question requests
        for the same user fire in parallel, both might consume the
        same row." Acceptable today because: (a) chat & interview
        surfaces are user-driven and serial per session; (b) an
        admin watching this in production can re-POST if the queue
        gets weirdly out of order. If we ever need stricter
        guarantees, promote to an RPC stored function with
        SELECT ... FOR UPDATE SKIP LOCKED.

        Called from the next-question splice in /v2/user/chat/
        first-question and /v2/public/interview/next-question
        BEFORE the LLM fallback. (The legacy queued_override_question
        consumer was removed in the Week-1 cleanup.)
        """
        try:
            picked = (
                self.client.table("coaching_directives_queue")
                .select("id, position, intent_tag, question")
                .eq("user_id", user_id)
                .eq("exhausted", False)
                .order("position", desc=False)
                .limit(1)
                .execute()
            )
            rows = picked.data or []
            if not rows:
                return None
            row = rows[0]
        except Exception as sel_err:
            err_low = str(sel_err).lower()
            if (
                "coaching_directives_queue" in err_low
                and ("does not exist" in err_low or "pgrst" in err_low)
            ):
                # Table not yet present — silently fall through to
                # legacy / LLM path so the next-question handler
                # doesn't 500 just because the migration is
                # pending.
                return None
            logger.warning(
                "pop_next_directive: select failed user=%s err=%s "
                "— falling through",
                user_id, sel_err,
            )
            return None

        try:
            (
                self.client.table("coaching_directives_queue")
                .update({"exhausted": True})
                .eq("id", row["id"])
                .execute()
            )
        except Exception as upd_err:
            # The UPDATE failed but we already have the row in
            # memory. Returning it means the chat surface will use
            # this question — but the row is still flagged
            # un-exhausted in the DB, so the NEXT turn will also
            # pick the same row. Worse than dropping the row.
            # Safer: log + return None, let the LLM fallback fire.
            logger.warning(
                "pop_next_directive: mark-exhausted failed "
                "user=%s row=%s err=%s — falling through to LLM "
                "to avoid double-firing the same directive",
                user_id, row.get("id"), upd_err,
            )
            return None

        return {
            "id": row.get("id"),
            "position": row.get("position"),
            "intent_tag": row.get("intent_tag"),
            "question": row.get("question"),
        }

    def insert_admin_annotation_log(
        self,
        *,
        user_id: str,
        session_id: str,
        ai_predicted_comment: Optional[str],
        ai_predicted_question: Optional[str],
        final_human_comment: Optional[str],
        final_human_question: Optional[str],
        was_corrected: bool,
        question_position: Optional[int] = None,
        intent_tag: Optional[str] = None,
        surface: Optional[str] = None,
    ) -> Optional[dict]:
        """Write one RLHF training row to admin_annotations_log.

        Called from the admin Publish handler and the session-
        level KPI narrative PATCH handler. Returns the inserted
        row or None on failure — failure logs but does NOT raise
        to the route, because the publish / save itself has
        already succeeded by the time we write the log and we
        won't undo it for a training-pipeline side-effect.

        ``question_position`` (1..5) + ``intent_tag`` are set
        for the per-position rows that capture each Director's
        Script question's (predicted, final) pair. Left NULL for
        the session-level admin_comment row and for legacy
        single-question rows.

        ``surface`` tags the write path so downstream RLHF
        analytics can filter by edit type. Values currently
        emitted:
          "session_kpi_narrative"  — PATCH /kpi-narrative
          "publish_session_comment" — publish's session-level row
          "publish_question_p1".."p5" — publish's per-position rows
        None when the column is missing (graceful fallback below)
        or when an unmigrated caller doesn't set it.

        Graceful fallback when per-position / surface columns
        aren't in the schema yet (migration pending): retries the
        insert without them. The session-level signal still
        lands; the missing-column granularity just isn't
        available until the matching migration runs.
        """
        try:
            payload: dict = {
                "user_id": user_id,
                "session_id": session_id,
                "ai_predicted_comment": ai_predicted_comment,
                "ai_predicted_question": ai_predicted_question,
                "final_human_comment": final_human_comment,
                "final_human_question": final_human_question,
                "was_corrected": bool(was_corrected),
            }
            if question_position is not None:
                payload["question_position"] = int(question_position)
            if intent_tag is not None:
                payload["intent_tag"] = intent_tag
            if surface is not None:
                payload["surface"] = surface

            result = (
                self.client.table("admin_annotations_log")
                .insert(payload)
                .execute()
            )
            if result.data and len(result.data) > 0:
                return result.data[0]
            return None
        except Exception as e:
            err_low = str(e).lower()
            if (
                "question_position" in err_low
                or "intent_tag" in err_low
                or "surface" in err_low
                or "pgrst204" in err_low
            ):
                logger.warning(
                    "insert_admin_annotation_log: optional column(s) "
                    "missing (migration pending?), retrying without — "
                    "sid=%s pos=%s surface=%s",
                    session_id, question_position, surface,
                )
                try:
                    fallback = {
                        k: v for k, v in payload.items()
                        if k not in (
                            "question_position",
                            "intent_tag",
                            "surface",
                        )
                    }
                    result = (
                        self.client.table("admin_annotations_log")
                        .insert(fallback)
                        .execute()
                    )
                    if result.data and len(result.data) > 0:
                        return result.data[0]
                    return None
                except Exception as e2:
                    logger.warning(
                        "insert_admin_annotation_log fallback failed sid=%s err=%s",
                        session_id, e2,
                    )
                    return None
            logger.warning(
                "insert_admin_annotation_log failed sid=%s uid=%s err=%s",
                session_id, user_id, e,
            )
            return None

    def promote_ai_drafts_to_admin_comments(self, session_id: str) -> int:
        """Copy ai_draft_admin_comment → admin_comment for every snippet
        in ``session_id`` that has a draft but no human comment yet.

        Used by the auto-publish flow for coaching trial recordings —
        there's no admin in the loop to review drafts, so we ship the
        AI's first take as the comment. Existing admin_comment rows
        are NOT overwritten (idempotent: a manual review later wins
        over a previous auto-promotion if the admin edits the row).

        Returns the number of rows promoted. Zero is a valid outcome:
        snippets without drafts, or already-commented rows, both fall
        outside the filter.
        """
        try:
            # PostgREST has no UPDATE … FROM, so we read first then
            # write per-row. The N here is bounded by snippets-per-
            # session (typically 1-5 for a trial recording) so the
            # extra round-trip cost is fine.
            sel = (
                self.client.table(SNIPPETS_TABLE)
                .select("id, ai_draft_admin_comment, admin_comment")
                .eq("session_id", session_id)
                .execute()
            )
            candidates = sel.data or []
            promoted = 0
            now = datetime.now(timezone.utc).isoformat()
            for row in candidates:
                existing = (row.get("admin_comment") or "").strip()
                if existing:
                    continue
                draft = (row.get("ai_draft_admin_comment") or "").strip()
                if not draft:
                    continue
                try:
                    (
                        self.client.table(SNIPPETS_TABLE)
                        .update({
                            "admin_comment": draft,
                            "updated_at": now,
                        })
                        .eq("id", row["id"])
                        .execute()
                    )
                    promoted += 1
                except Exception as upd_err:
                    logger.warning(
                        "promote_ai_drafts: row update failed sid=%s sn=%s err=%s",
                        session_id, row["id"], upd_err,
                    )
            return promoted
        except Exception as e:
            logger.warning(
                "promote_ai_drafts_to_admin_comments failed sid=%s: %s",
                session_id, e,
            )
            return 0

    def set_charisma_snippet_ai_draft_comment(
        self,
        snippet_id: str,
        draft: str | None,
    ) -> bool:
        """Persist an AI-suggested admin_comment draft on a charisma snippet.

        Phase 10. Written once when the snippet is first extracted; the
        admin then keeps it, edits it, or replaces it via the normal
        admin_comment save path. The draft column is intentionally
        immutable from the admin UI — at publish time we compare
        admin_comment vs this column to emit the RLHF pair.

        Returns True on success. Failure logs + returns False so the
        snippet pipeline that triggered this can keep running.
        """
        try:
            now = datetime.now(timezone.utc).isoformat()
            (
                self.client.table(SNIPPETS_TABLE)
                .update({
                    "ai_draft_admin_comment": draft,
                    "ai_draft_admin_comment_generated_at": now,
                    "updated_at": now,
                })
                .eq("id", snippet_id)
                .execute()
            )
            return True
        except Exception as e:
            logger.warning(
                "set_charisma_snippet_ai_draft_comment failed %s: %s",
                snippet_id, e,
            )
            return False

    def set_charisma_snippet_ai_draft_coach_note(
        self,
        snippet_id: str,
        draft: str | None,
    ) -> bool:
        """Persist the AI-Commentator coach-note draft on a charisma snippet,
        FROZEN: written only when ai_draft_coach_note is currently NULL, so a
        re-process never overwrites a draft the coach is already editing
        against (preserves the (draft, coach-final) diff). willab Phase 4 /
        Prompt 2. Returns True on a write, False on skip/failure (best-effort;
        the drafting pipeline keeps running)."""
        try:
            existing = (
                self.client.table(SNIPPETS_TABLE)
                .select("ai_draft_coach_note")
                .eq("id", snippet_id)
                .limit(1)
                .execute()
            )
            rows = existing.data or []
            if rows and (rows[0].get("ai_draft_coach_note") or "").strip():
                return False  # frozen — already has a draft
            now = datetime.now(timezone.utc).isoformat()
            (
                self.client.table(SNIPPETS_TABLE)
                .update({
                    "ai_draft_coach_note": draft,
                    "ai_draft_coach_note_generated_at": now,
                    "updated_at": now,
                })
                .eq("id", snippet_id)
                .execute()
            )
            return True
        except Exception as e:
            err_low = str(e).lower()
            if "ai_draft_coach_note" in err_low and (
                "does not exist" in err_low or "pgrst204" in err_low
            ):
                logger.warning(
                    "set_charisma_snippet_ai_draft_coach_note: column missing "
                    "(run migrations/add_ai_draft_coach_note.sql)",
                )
                return False
            logger.warning(
                "set_charisma_snippet_ai_draft_coach_note failed %s: %s",
                snippet_id, e,
            )
            return False

    def set_charisma_snippet_say_it_stronger(
        self,
        snippet_id: str,
        payload: Optional[dict],
    ) -> bool:
        """Persist the 'Say It Stronger' suggestion on a charisma snippet,
        write-once (only when say_it_stronger is currently NULL) so duplicate
        daemon runs are idempotent. Best-effort — missing column (run
        migrations/add_say_it_stronger.sql) or any error returns False and
        never breaks the generation loop."""
        if not snippet_id or not isinstance(payload, dict):
            return False
        try:
            existing = (
                self.client.table(SNIPPETS_TABLE)
                .select("say_it_stronger")
                .eq("id", snippet_id)
                .limit(1)
                .execute()
            )
            rows = existing.data or []
            if rows and rows[0].get("say_it_stronger"):
                return False  # write-once — already generated
            (
                self.client.table(SNIPPETS_TABLE)
                .update({"say_it_stronger": payload})
                .eq("id", snippet_id)
                .execute()
            )
            return True
        except Exception as e:
            err_low = str(e).lower()
            if "say_it_stronger" in err_low and (
                "does not exist" in err_low or "pgrst204" in err_low
            ):
                logger.warning(
                    "set_charisma_snippet_say_it_stronger: column missing "
                    "(run migrations/add_say_it_stronger.sql)",
                )
                return False
            logger.warning(
                "set_charisma_snippet_say_it_stronger failed %s: %s",
                snippet_id, e,
            )
            return False

    def set_charisma_snippet_say_it_stronger_final(
        self,
        snippet_id: str,
        payload: Optional[dict],
    ) -> bool:
        """Persist the COACH-corrected 'Say It Stronger' card (Engine 1,
        founder 2026-07-11). Plain update — RE-editable (unlike the write-once
        auto draft; the coach may revise until publish). Best-effort — missing
        column (run migrations/add_say_it_stronger_final.sql) → False."""
        if not snippet_id or not isinstance(payload, dict):
            return False
        try:
            (
                self.client.table(SNIPPETS_TABLE)
                .update({"say_it_stronger_final": payload})
                .eq("id", snippet_id)
                .execute()
            )
            return True
        except Exception as e:
            err_low = str(e).lower()
            if "say_it_stronger_final" in err_low and (
                "does not exist" in err_low or "pgrst204" in err_low
            ):
                logger.warning(
                    "set_charisma_snippet_say_it_stronger_final: column "
                    "missing (run migrations/add_say_it_stronger_final.sql)",
                )
                return False
            logger.warning(
                "set_charisma_snippet_say_it_stronger_final failed %s: %s",
                snippet_id, e,
            )
            return False

    def get_ai_draft_coach_notes_by_session(self, session_id: str) -> dict:
        """{snippet_id: ai_draft_coach_note} for a session — the AI-Commentator
        pre-fills the coach read serves. Coach-only. {} on missing column/table
        (pre-migration → coach sees blank fields, same as today)."""
        if not session_id:
            return {}
        try:
            res = (
                self.client.table(SNIPPETS_TABLE)
                .select("id, ai_draft_coach_note")
                .eq("session_id", session_id)
                .execute()
            )
            return {
                str(r.get("id")): r.get("ai_draft_coach_note")
                for r in (res.data or [])
                if r.get("ai_draft_coach_note")
            }
        except Exception as e:
            if "ai_draft_coach_note" in str(e).lower():
                return {}
            logger.warning(
                "get_ai_draft_coach_notes_by_session failed sid=%s: %s",
                session_id, e,
            )
            return {}

    def set_charisma_snippet_ai_draft_follow_up(
        self,
        snippet_id: str,
        draft: str | None,
    ) -> bool:
        """Persist the original AI-generated follow_up_question, frozen.

        Phase 10. follow_up_question itself may be edited by the admin
        — this column preserves the pre-edit version so the publish-
        time annotation can pair the two.
        """
        try:
            now = datetime.now(timezone.utc).isoformat()
            (
                self.client.table(SNIPPETS_TABLE)
                .update({
                    "ai_draft_follow_up_question": draft,
                    "ai_draft_follow_up_question_generated_at": now,
                    "updated_at": now,
                })
                .eq("id", snippet_id)
                .execute()
            )
            return True
        except Exception as e:
            logger.warning(
                "set_charisma_snippet_ai_draft_follow_up failed %s: %s",
                snippet_id, e,
            )
            return False

    def has_ideal_text_annotations(self, arc_uuid: Optional[str]) -> bool:
        """Any ideal-text annotation rows for this arc yet?

        The idempotency probe for the APPROVE-route capture hook: the shipped
        FE's Verify button posts /ideal-text/approve (never /verify), and
        approve has no re-approve guard — so its capture fires only when this
        probe finds nothing. First approve captures; re-approves skip. The
        /verify route keeps its own per-VERSION exactly-once and does not use
        this probe. Probe failure → True (never double-write on
        uncertainty)."""
        if not arc_uuid:
            return True
        try:
            rows = (
                self.client.table("admin_annotation_events")
                .select("id")
                .eq("draft_id", str(arc_uuid))
                .in_("field_name", ["ideal_text_sentence", "ideal_text_block"])
                .limit(1)
                .execute()
                .data
            ) or []
            return bool(rows)
        except Exception as e:
            logger.warning(
                "has_ideal_text_annotations: probe failed arc=%s: %s — "
                "treating as captured", arc_uuid, e,
            )
            return True

    def get_user_company_id(self, user_id: str) -> Optional[str]:
        """Lookup the user's company_id from user_settings.

        Returns None when:
          - the row doesn't exist (user never edited any setting), OR
          - the column isn't migrated yet (PGRST204), OR
          - the value is genuinely NULL (user in personal sandbox).
        Callers must treat all three uniformly — no company == personal
        sandbox, snippet retrieval scoped to viewer only.
        """
        try:
            result = (
                self.client.table("user_settings")
                .select("company_id")
                .eq("user_id", user_id)
                .limit(1)
                .execute()
            )
            if result.data and len(result.data) > 0:
                return (result.data[0].get("company_id") or None)
            return None
        except Exception as e:
            logger.warning("get_user_company_id failed for %s: %s", user_id, e)
            return None

    def log_few_shot_retrieval(
        self,
        *,
        user_id: str,
        requesting_snippet_id: Optional[str],
        exemplar_snippet_ids: List[str],
        intent: str,
        scope_mode: str,
        company_id: Optional[str],
    ) -> None:
        """Fire-and-forget audit log entry for a few-shot retrieval.

        Compliance + telemetry. ``scope_mode`` documents the rollout
        path:
          - 'cross_tenant_legacy' — flag off, pre-Phase-1 behaviour
          - 'tenant_scoped'      — flag on, viewer has a company_id
          - 'canonical_topup'    — flag on, no company / cold start;
                                     limited to canonical rows
        Failures swallow — the retrieval already happened in memory
        and we don't want an audit-log write to delay the LLM call.
        """
        try:
            self.client.table("few_shot_retrievals").insert({
                "user_id": user_id,
                "requesting_snippet_id": requesting_snippet_id,
                "exemplar_snippet_ids": list(exemplar_snippet_ids),
                "intent": intent,
                "scope_mode": scope_mode,
                "company_id": company_id,
            }).execute()
        except Exception as e:
            logger.warning("log_few_shot_retrieval failed: %s", e)


    def set_user_current_learner_mirror(
        self,
        user_id: str,
        mirror: Optional[dict],
    ) -> Optional[dict]:
        """Upsert the current learner mirror JSONB for ``user_id``.

        Phase 6 — replaces (does not append) the prior mirror so the
        user always sees the most recent reflection. Passing
        ``mirror=None`` clears the column, which is useful if we
        ever want a "discard my reflection" button.

        Upsert because the row may not exist yet — same reasoning as
        set_user_inferred_learner_profile. Failure returns None;
        the caller (services.learner_mirror) maps that to a
        PERSIST_FAILED error code so the user sees a clear retry
        signal rather than a silent no-op.
        """
        try:
            result = (
                self.client.table("user_settings")
                .upsert({
                    "user_id": user_id,
                    "current_learner_mirror": mirror,
                    "current_learner_mirror_generated_at": (
                        datetime.now(timezone.utc).isoformat()
                    ),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                })
                .execute()
            )
            if result.data and len(result.data) > 0:
                return result.data[0]
            return None
        except Exception as e:
            logger.warning(
                "set_user_current_learner_mirror failed user=%s err=%s",
                user_id, e,
            )
            return None

    # ── Phase 9: admin RLHF on coaching attempts ──────────────────────

    def insert_coaching_attempt_annotation(
        self,
        *,
        coaching_attempt_id: str,
        admin_user_id: str,
        admin_action: str,
        admin_score: float | None = None,
        admin_components: dict | None = None,
        admin_note: str | None = None,
        ai_score_was_correct: bool | None = None,
        reason_chip: str | None = None,
    ) -> Optional[dict]:
        """Append an admin annotation onto a coaching_attempts row.

        Phase 9 — one row per review action so multi-admin review
        stays cleanly queryable. The caller (the admin route) is
        responsible for verifying the requester is actually an
        admin; this helper does not re-check.

        Returns the inserted row on success, None when:
          - the migration hasn't run yet,
          - the coaching_attempt_id doesn't exist (FK violation),
          - any Supabase error.
        """
        payload = {
            "coaching_attempt_id": coaching_attempt_id,
            "admin_user_id": admin_user_id,
            "admin_action": admin_action,
            "admin_score": admin_score,
            "admin_components": admin_components,
            "admin_note": admin_note,
            "ai_score_was_correct": ai_score_was_correct,
            "reason_chip": reason_chip,
        }
        try:
            result = (
                self.client.table("coaching_attempt_annotations")
                .insert(payload)
                .execute()
            )
            return result.data[0] if result.data else None
        except Exception as e:
            logger.warning(
                "insert_coaching_attempt_annotation failed attempt=%s "
                "admin=%s err=%s",
                coaching_attempt_id, admin_user_id, e,
            )
            return None

    def list_annotations_for_coaching_attempt(
        self,
        coaching_attempt_id: str,
    ) -> List[dict]:
        """All annotations on one attempt, newest first.

        Returns [] on any error so the review UI can render the
        attempt page even if the annotations table is missing.
        """
        try:
            return (
                self.client.table("coaching_attempt_annotations")
                .select("*")
                .eq("coaching_attempt_id", coaching_attempt_id)
                .order("created_at", desc=True)
                .execute()
                .data
            ) or []
        except Exception as e:
            logger.warning(
                "list_annotations_for_coaching_attempt failed "
                "attempt=%s err=%s", coaching_attempt_id, e,
            )
            return []

    def count_annotations_by_admin(self, admin_user_id: str) -> int:
        """How many coaching-attempt annotations has this admin written?

        Phase 9 — the bulk-approve threshold (default: unlock at
        100 reviews per admin) is read off this number by the
        admin UI. We use count='exact' so the response carries the
        total without fetching rows.

        Returns 0 on any error — failure mode is "feature stays
        locked", which is safe.
        """
        try:
            result = (
                self.client.table("coaching_attempt_annotations")
                .select("id", count="exact")
                .eq("admin_user_id", admin_user_id)
                .limit(1)
                .execute()
            )
            return int(result.count or 0)
        except Exception as e:
            logger.warning(
                "count_annotations_by_admin failed admin=%s err=%s",
                admin_user_id, e,
            )
            return 0

    def set_user_admin_profile_override(
        self,
        *,
        user_id: str,
        override: Optional[dict],
        set_by: Optional[str],
    ) -> Optional[dict]:
        """Upsert the admin override of the learner profile.

        Pass ``override=None`` to clear (admin "reset to inferred"
        action). ``set_by`` is the admin's user id — recorded for
        audit; can be None when the system itself clears the
        override (e.g. via a future cron job).

        Returns the upserted row, or None on failure.
        """
        try:
            payload: dict[str, Any] = {
                "user_id": user_id,
                "admin_profile_override": override,
                "admin_profile_override_set_at": (
                    datetime.now(timezone.utc).isoformat() if override is not None
                    else None
                ),
                "admin_profile_override_set_by": set_by,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            result = (
                self.client.table("user_settings")
                .upsert(payload)
                .execute()
            )
            if result.data and len(result.data) > 0:
                return result.data[0]
            return None
        except Exception as e:
            logger.warning(
                "set_user_admin_profile_override failed user=%s err=%s",
                user_id, e,
            )
            return None

    def get_top_followup_examples(
        self,
        intent: str,
        *,
        limit: int = 3,
        min_score: float = 0.65,
        exclude_snippet_id: str | None = None,
        viewer_user_id: str | None = None,
    ) -> List[dict]:
        """Highest-scoring past contextual exchanges for a given intent.

        Powers the few-shot retrieval layer of the coaching-effectiveness
        loop: when the user clicks a CTA, the LLM that generates the
        first question receives the TOP-N past exchanges where the same
        intent produced a high-quality answer. That nudges the model
        toward wording patterns that have already worked, instead of
        generating from scratch every time.

        Phase 2 rewrite: reads from ``coaching_attempts`` (1:N) rather
        than the latest-wins ``charisma_snippets.follow_up_outcome``
        JSONB. The retrieval picks the BEST attempt per snippet (group
        by snippet_id, keep MAX score) and then joins the snippet
        context. The downstream consumer (``_build_few_shot_block``)
        still expects a ``follow_up_outcome``-shaped dict on each row,
        so we synthesize one from the chosen attempt — that keeps the
        prompt-builder unchanged through the migration.

        Filters applied (all must hold):
          - charisma_snippets.snippet_type = intent ("charisma"/"stress")
          - admin_comment non-null (need the coach's framing)
          - transcript non-null
          - attempt.score >= ``min_score``
          - attempt.is_eligible_for_few_shot = TRUE (Phase 5 guard)
          - snippet_id != exclude_snippet_id

        Falls back to [] on any error (e.g. coaching_attempts table not
        yet migrated) so the LLM prompt builder degrades gracefully to
        context-free generation.
        """
        try:
            normalised = (intent or "").strip().lower()
            if normalised not in ("charisma", "stress"):
                return []

            # ── Phase 1 tenant-scoping setup ───────────────────────
            # Resolved BEFORE the query so the audit log captures the
            # company_id that was actually used.
            from config import Config
            tenant_scoping_on = bool(Config().FEW_SHOT_TENANT_SCOPED)
            viewer_company_id: str | None = None
            scope_mode = "cross_tenant_legacy"
            if tenant_scoping_on and viewer_user_id:
                viewer_company_id = self.get_user_company_id(viewer_user_id)

            # ── Step 1: pull top-scoring attempts ──────────────────
            # Fetch a generous pool — same snippet may have many
            # attempts so we need headroom to dedupe to the best-per-
            # snippet without losing the requested limit.
            try:
                attempts = (
                    self.client.table("coaching_attempts")
                    .select(
                        "snippet_id, user_id, attempt_number, score, "
                        "components, question_text, user_answer_text, "
                        "user_answer_duration_ms, user_answer_word_count, "
                        "rationale, is_eligible_for_few_shot, "
                        "evaluator_model, fact_check, created_at"
                    )
                    .eq("is_eligible_for_few_shot", True)
                    .gte("score", min_score)
                    .order("score", desc=True)
                    .limit(max(limit * 10, 40))
                    .execute()
                    .data
                ) or []
            except Exception as e:
                # Table missing / not migrated — degrade to empty pool
                # rather than crash the first-question endpoint.
                logger.warning(
                    "get_top_followup_examples: coaching_attempts query "
                    "failed (table missing?): %s", e
                )
                return []

            # Best attempt per snippet. attempts is already score-DESC,
            # so the first occurrence of each snippet_id is the best.
            best_by_snippet: dict[str, dict] = {}
            for a in attempts:
                sid = a.get("snippet_id")
                if not sid or sid == exclude_snippet_id:
                    continue
                if sid in best_by_snippet:
                    continue
                best_by_snippet[sid] = a
            if not best_by_snippet:
                if viewer_user_id:
                    self.log_few_shot_retrieval(
                        user_id=viewer_user_id,
                        requesting_snippet_id=exclude_snippet_id,
                        exemplar_snippet_ids=[],
                        intent=normalised,
                        scope_mode=scope_mode,
                        company_id=viewer_company_id,
                    )
                return []

            # ── Step 2: join snippet context ───────────────────────
            snippet_ids = list(best_by_snippet.keys())
            try:
                snippet_rows = (
                    self.client.table(SNIPPETS_TABLE)
                    .select(
                        "id, snippet_type, transcript, admin_comment, "
                        "follow_up_question, sharing_scope, user_id, "
                        "created_at"
                    )
                    .in_("id", snippet_ids)
                    .eq("snippet_type", normalised)
                    .not_.is_("admin_comment", "null")
                    .not_.is_("transcript", "null")
                    .execute()
                    .data
                ) or []
            except Exception as e:
                logger.warning(
                    "get_top_followup_examples: snippet join failed: %s", e
                )
                return []

            # Merge attempt + snippet; synthesize a follow_up_outcome
            # dict so _build_few_shot_block doesn't need to change.
            merged: list[dict] = []
            for s in snippet_rows:
                if not (s.get("admin_comment") or "").strip():
                    continue
                if not (s.get("transcript") or "").strip():
                    continue
                attempt = best_by_snippet.get(s.get("id"))
                if not attempt:
                    continue
                answer_text = (attempt.get("user_answer_text") or "").strip()
                if not answer_text:
                    continue
                merged_row = dict(s)
                merged_row["follow_up_outcome"] = {
                    "score": attempt.get("score"),
                    "evaluator": {
                        "components": attempt.get("components") or {},
                        "rationale": attempt.get("rationale"),
                        "model": attempt.get("evaluator_model"),
                    },
                    "user_answer": {
                        "text": answer_text,
                        "duration_ms": attempt.get("user_answer_duration_ms"),
                        "word_count": attempt.get("user_answer_word_count"),
                    },
                    "question_text": attempt.get("question_text"),
                    "eligible_for_few_shot": bool(
                        attempt.get("is_eligible_for_few_shot")
                    ),
                    "fact_check": attempt.get("fact_check"),
                    "attempt_number": attempt.get("attempt_number"),
                }
                merged.append(merged_row)

            # Re-sort by the attempt score (descending). Snippet-IN
            # order isn't guaranteed by PostgREST.
            merged.sort(
                key=lambda r: float(
                    (r.get("follow_up_outcome") or {}).get("score") or 0
                ),
                reverse=True,
            )

            # ── Step 3: Phase 1 tenant filter ──────────────────────
            if tenant_scoping_on:
                if viewer_company_id:
                    scope_mode = "tenant_scoped"
                    merged = self._filter_by_tenant_or_canonical(
                        merged, viewer_company_id
                    )
                else:
                    scope_mode = "canonical_topup"
                    merged = [
                        r for r in merged
                        if (r.get("sharing_scope") or "tenant_only") == "canonical"
                    ]
            else:
                merged = [
                    r for r in merged
                    if (r.get("sharing_scope") or "tenant_only") != "private"
                ]

            kept = merged[:limit]

            # Fire-and-forget audit log.
            if viewer_user_id:
                self.log_few_shot_retrieval(
                    user_id=viewer_user_id,
                    requesting_snippet_id=exclude_snippet_id,
                    exemplar_snippet_ids=[str(r.get("id")) for r in kept if r.get("id")],
                    intent=normalised,
                    scope_mode=scope_mode,
                    company_id=viewer_company_id,
                )
            return kept
        except Exception as e:
            logger.warning("get_top_followup_examples failed: %s", e)
            return []

    def _filter_by_tenant_or_canonical(
        self,
        rows: list[dict],
        viewer_company_id: str,
    ) -> list[dict]:
        """Keep rows whose author is in the viewer's company OR whose
        sharing_scope is 'canonical'. Drop everything else.

        Single batched user_settings lookup for the candidate authors —
        we do NOT issue per-row queries. For typical pool sizes
        (limit * 4 == 12 candidates) the IN-list query is fast.
        """
        canonical_rows: list[dict] = []
        author_ids: set[str] = set()
        for r in rows:
            scope = (r.get("sharing_scope") or "tenant_only").lower()
            if scope == "private":
                continue
            if scope == "canonical":
                canonical_rows.append(r)
                continue
            uid = r.get("user_id")
            if uid:
                author_ids.add(str(uid))

        if not author_ids:
            return canonical_rows

        # Batch lookup: which of these authors share viewer_company_id?
        try:
            settings = (
                self.client.table("user_settings")
                .select("user_id, company_id")
                .in_("user_id", list(author_ids))
                .execute()
                .data
            ) or []
        except Exception as e:
            logger.warning(
                "_filter_by_tenant_or_canonical: settings lookup failed: %s", e
            )
            settings = []

        same_company = {
            str(s.get("user_id"))
            for s in settings
            if s.get("company_id") and str(s.get("company_id")) == str(viewer_company_id)
        }

        tenant_rows = [
            r for r in rows
            if (r.get("sharing_scope") or "tenant_only").lower() == "tenant_only"
            and str(r.get("user_id") or "") in same_company
        ]

        # Preserve order from the score-sorted source query, with
        # canonical rows interleaved naturally (they were already in
        # `rows` and we kept their original positions).
        return [r for r in rows if r in tenant_rows or r in canonical_rows]

    def set_snippet_evaluator_rationale_review(
        self,
        snippet_id: str,
        *,
        rationale_text: str,
        edited_by_admin: bool,
        reviewed_at: str,
        is_trivial_edit: bool = False,
    ) -> dict | None:
        """Persist an admin's review of the AI evaluator's rationale.

        Lives inside the existing ``follow_up_outcome.evaluator`` JSONB
        block (Phase 14.x — frontend's contract) rather than as a
        separate column, so we read the current outcome, mutate the
        review fields, and write the whole JSONB back.

        Semantics::

          edited_by_admin=True, is_trivial_edit=False
            → admin_corrected_rationale = rationale_text
              was_trivial_edit (cleared / not set)
              "Real correction; train on this."

          edited_by_admin=True, is_trivial_edit=True
            → admin_corrected_rationale = rationale_text
              was_trivial_edit = True
              "Admin's edit preserved as user-facing copy, but the
               diff was sub-threshold — publish-time annotation
               consumers MUST check the flag and treat as approval
               rather than correction. Set by the word-token diff
               gate (services.utils.changed_word_tokens) when the
               admin overrode a 422 with the 'trivial edit'
               checkbox."

          edited_by_admin=False (is_trivial_edit ignored)
            → admin_corrected_rationale = None
              "Admin approved the AI rationale verbatim; stored as
               null so the publish-time annotation logic falls back
               to the AI rationale and detects approved_as_is."

        ``admin_reviewed_at`` is always stamped — its presence is what
        distinguishes "admin reviewed and approved" from "admin never
        looked at this", and it's the gate the publish-time annotation
        loop uses to decide whether to emit a signal.

        Returns the updated outcome dict on success, or None when the
        snippet has no follow_up_outcome / no evaluator block (caller
        should respond 422 — there's no rationale to review yet).

        Race window: if a new coaching attempt overwrites
        follow_up_outcome between our read and write, we lose the
        attempt. Admin reviews are infrequent and coaching attempts
        are user-initiated, so the window is small in practice; if
        this becomes a problem we'll move admin review to a separate
        column or add a JSONB-merge SQL function.
        """
        if not snippet_id:
            return None
        try:
            existing = (
                self.client.table(SNIPPETS_TABLE)
                .select("follow_up_outcome")
                .eq("id", snippet_id)
                .limit(1)
                .execute()
            )
        except Exception as e:
            logger.error(
                "set_snippet_evaluator_rationale_review: select failed "
                "snippet=%s err=%s", snippet_id, e,
            )
            return None

        if not existing.data:
            return None
        outcome = (existing.data[0].get("follow_up_outcome") or None)
        if not isinstance(outcome, dict):
            # No coaching attempt has been recorded for this snippet yet —
            # nothing to review.
            return None
        evaluator = outcome.get("evaluator")
        if not isinstance(evaluator, dict):
            return None

        # Mutate in place — outcome is a fresh dict from the DB read.
        evaluator["admin_corrected_rationale"] = (
            (rationale_text or "").strip() if edited_by_admin else None
        )
        evaluator["admin_reviewed_at"] = reviewed_at
        # was_trivial_edit only carries meaning when edited_by_admin
        # is True (we actually saved corrected text). Set the flag
        # in both directions so explicit True/False is recoverable;
        # publish-time consumers default to False on absent key.
        if edited_by_admin:
            evaluator["was_trivial_edit"] = bool(is_trivial_edit)
        else:
            # Approval path discards corrected text — the trivial-
            # edit concept doesn't apply. Clear any stale flag from
            # a previous save so a re-review doesn't carry it over.
            evaluator.pop("was_trivial_edit", None)
        outcome["evaluator"] = evaluator

        try:
            result = (
                self.client.table(SNIPPETS_TABLE)
                .update({
                    "follow_up_outcome": outcome,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                })
                .eq("id", snippet_id)
                .execute()
            )
            if result.data:
                return result.data[0].get("follow_up_outcome") or outcome
            return outcome
        except Exception as e:
            logger.error(
                "set_snippet_evaluator_rationale_review: update failed "
                "snippet=%s err=%s", snippet_id, e,
            )
            return None

    def set_snippet_follow_up_outcome(
        self,
        snippet_id: str,
        outcome: dict | None,
    ) -> dict | None:
        """Persist the post-turn-1 evaluation JSONB onto a source snippet.

        Powers the first piece of the coaching-effectiveness learning
        loop: every contextual chat the user starts via a CTA produces
        one of these blobs (score + components + rationale + the user's
        actual answer). See services/coaching_outcomes.py for the
        evaluation logic.

        Latest-wins overwrite (the user may re-record turn 1).
        Requires the `follow_up_outcome JSONB` column on
        charisma_snippets. If the migration hasn't run yet the call
        fails cleanly (PGRST204) and the caller silently swallows.
        """
        try:
            result = (
                self.client.table(SNIPPETS_TABLE)
                .update({
                    "follow_up_outcome": outcome,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                })
                .eq("id", snippet_id)
                .execute()
            )
            return result.data[0] if result.data else None
        except Exception as e:
            logger.error(
                "set_snippet_follow_up_outcome failed for %s: %s",
                snippet_id, e,
            )
            return None

    def update_coach_ai_message(
        self,
        user_id: str,
        message_index: int,
        new_content: str,
    ) -> dict | None:
        """Edit the `content` of one message in the coach AI conversation history.

        The messages array is stored as JSONB. We update the element at
        `message_index` in-place and persist the full array back.

        Returns the updated conversation row, or None on failure / out-of-range.
        """
        try:
            conv = self.get_coach_ai_conversation(user_id)
            if not conv:
                return None
            raw = conv.get("messages") or "[]"
            messages = json.loads(raw) if isinstance(raw, str) else list(raw)
            if not (0 <= message_index < len(messages)):
                return None  # index out of range — caller should 404/422
            messages[message_index] = {
                **messages[message_index],
                "content": new_content,
                "edited_by_admin": True,
                "edited_at": datetime.now(timezone.utc).isoformat(),
            }
            return self.upsert_coach_ai_conversation(user_id, messages)
        except Exception as e:
            logger.error("update_coach_ai_message failed for %s idx=%s: %s", user_id, message_index, e)
            return None

    def update_snippets_user_id(self, session_id: str, user_id: str) -> int:
        """Update all snippets for a session to have the newly authenticated user_id.

        Called when a guest session is claimed post-signup. Matches rows where
        user_id is NULL or the placeholder UUID used during anonymous interview.
        Returns count of updated rows.
        """
        PLACEHOLDER_UID = "00000000-0000-0000-0000-000000000000"
        total = 0
        try:
            # Match placeholder user_id (from interview flow)
            r1 = (
                self.client.table(SNIPPETS_TABLE)
                .update({"user_id": user_id})
                .eq("session_id", session_id)
                .eq("user_id", PLACEHOLDER_UID)
                .execute()
            )
            total += len(r1.data) if r1.data else 0
        except Exception as e:
            logger.warning(f"update_snippets_user_id (placeholder): {e}")
        try:
            # Match NULL user_id (from legacy single-upload flow)
            r2 = (
                self.client.table(SNIPPETS_TABLE)
                .update({"user_id": user_id})
                .eq("session_id", session_id)
                .is_("user_id", None)
                .execute()
            )
            total += len(r2.data) if r2.data else 0
        except Exception:
            pass
        return total

    # ------------------------------------------------------------------
    # Snippet boundary adjustment & per-snippet metrics
    # ------------------------------------------------------------------

    def update_snippet_boundaries(
        self,
        snippet_id: str,
        start_time: float,
        end_time: float,
    ) -> Optional[dict]:
        """Update a snippet's time boundaries (admin +/- 2s adjust).

        Returns the updated snippet row.

        Schema reality check (2026-05-11):
            Production logs after df9def4 surfaced PGRST204:
              "Could not find the 'end_time' column of
               'charisma_snippets' in the schema cache"

            So contrary to the Expand-Contract assumption that there
            were two semantically-paired column representations of the
            same boundary, only ONE pair actually exists in this DB:

                start_offset_ms, duration_ms   (milliseconds, int)

            The `start_time` / `end_time` references in the codebase
            (this helper's prior version, the upload-answer INSERT
            payload at routes/v2_routes.py:8777-8778, the
            v2_admin_get_session response shape at L10384, the route
            handler at L9404+) are write-only artefacts of an aborted
            schema migration that landed in the code but never in the
            database. PostgREST silently drops them on INSERT (which
            is why fresh sessions still create snippet rows fine) but
            errors atomically on UPDATE (which is why ±2s adjusts
            started failing 404 after df9def4).

            The fix is just to write the columns that actually exist.
            The route handler keeps accepting (start_time, end_time)
            as its public contract — we convert at this single
            chokepoint. If a future migration adds the seconds-pair as
            real columns (or restores them), this is the one place to
            re-introduce the dual write.
        """
        try:
            start_offset_ms = max(0, int(round(start_time * 1000)))
            duration_ms = max(0, int(round((end_time - start_time) * 1000)))
            result = (
                self.client.table(SNIPPETS_TABLE)
                .update({
                    "start_offset_ms": start_offset_ms,
                    "duration_ms": duration_ms,
                })
                .eq("id", snippet_id)
                .execute()
            )
            if result.data and len(result.data) > 0:
                return result.data[0]
            return None
        except Exception as e:
            logger.error(f"update_snippet_boundaries failed: {e}")
            return None

    def update_snippet_metrics_blob(
        self, snippet_id: str, metrics_json: dict,
    ) -> bool:
        """Replace ONLY the ``metrics`` JSONB on a snippet.

        Deliberately narrow, and deliberately not update_snippet_metrics: that
        one also writes the six denormalized acoustic columns, so a caller who
        merely wants to re-stamp a derived field inside the blob would have to
        echo wpm/fillers/pause_ms/dynamic_db/pitch_center/energy back and would
        silently null any it got wrong. This is for re-stamping derived reads
        (scripts/backfill_voice_confidence.py); the measured columns are the
        recorder's to write, not a backfill's.

        Best-effort: returns False on any failure rather than raising."""
        if not snippet_id or not isinstance(metrics_json, dict):
            return False
        try:
            result = (
                self.client.table(SNIPPETS_TABLE)
                .update({"metrics": metrics_json})
                .eq("id", snippet_id)
                .execute()
            )
            return bool(getattr(result, "data", None))
        except Exception as e:
            logger.warning("update_snippet_metrics_blob failed sid=%s: %s",
                           snippet_id, e)
            return False

    def set_snippet_arousal(self, snippet_id: str, arousal_z: float) -> bool:
        """Capture the baseline-relative AROUSAL read on a snippet (founder
        2026-07-24, capture-first). A learning-loop signal only — it is never
        surfaced to a user and never fed into ranking. Best-effort: a missing
        ``arousal_z`` column (migration pending) or any other error just
        returns False and never raises into the analysis path."""
        try:
            result = (
                self.client.table(SNIPPETS_TABLE)
                .update({"arousal_z": arousal_z})
                .eq("id", snippet_id)
                .execute()
            )
            return bool(getattr(result, "data", None))
        except Exception as e:
            logger.warning("set_snippet_arousal failed sid=%s: %s",
                           snippet_id, e)
            return False

    def upsert_arc_context_document(self, arc_id, text, pages, chars, *,
                                    filename=None, truncated=False) -> bool:
        """Store the extracted context document for an arc (X-1, founder
        2026-07-24; one row per arc). Best-effort — a missing table (migration
        pending) or any error returns False, never raises into the upload."""
        try:
            self.client.table("arc_context_documents").upsert({
                "arc_id": str(arc_id),
                "text": text or "",
                "pages": int(pages or 0),
                "chars": int(chars or 0),
                "filename": filename,
                "truncated": bool(truncated),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }, on_conflict="arc_id").execute()
            return True
        except Exception as e:
            logger.error("upsert_arc_context_document failed arc=%s: %s",
                         arc_id, e)
            return False

    def get_arc_context_document(self, arc_id) -> Optional[dict]:
        """The stored context document for an arc — {text, pages, chars,
        filename, truncated} or None. Best-effort (missing table → None)."""
        try:
            res = (
                self.client.table("arc_context_documents")
                .select("text, pages, chars, filename, truncated")
                .eq("arc_id", str(arc_id))
                .limit(1)
                .execute()
            )
            rows = getattr(res, "data", None) or []
            return rows[0] if rows else None
        except Exception as e:
            logger.warning("get_arc_context_document failed arc=%s: %s",
                           arc_id, e)
            return None

    # ── Journal (blog) content + CMS (founder 2026-07-25) ─────────────────
    # A self-contained marketing surface: nothing in the record → transcribe
    # → coach → read loop reads or writes journal_post. Every helper is
    # best-effort so a missing table (migration pending) degrades to "no
    # posts" instead of 500ing a public page.
    #
    # UNIQUE-slug note: the table has a UNIQUE constraint on `slug`, so the
    # create/update helpers surface a collision as the sentinel string
    # "DUPLICATE_SLUG" and the route maps it to 409 (never a 500).

    _JOURNAL_COLUMNS = (
        "id, slug, title, excerpt, category, read_time_min, cover_kind, "
        "cover_image_url, cover_alt, media_url, media_duration_sec, body, "
        "author_name, author_avatar_url, status, published_at, sort_order, "
        "meta_title, meta_description, og_image_url, created_at, updated_at"
    )

    @staticmethod
    def journal_search_filter(search: Optional[str]) -> Optional[str]:
        """The PostgREST `or=(...)` filter for a title/excerpt search, or None.

        SINGLE source of truth for the needle sanitization (used by both the
        list and the count query, which must agree or paging goes wrong).

        `,` `(` `)` are the condition/group separators in PostgREST's filter
        grammar, so they are stripped — without them an injected value stays
        inside the single ilike pattern and cannot add a condition. Note the
        real guarantee against draft exposure is structural, not this: the
        public queries also apply `status=eq.published` as a SEPARATE filter,
        and PostgREST ANDs separate params, so no or-injection can widen the
        result set past published rows.
        """
        if not search:
            return None
        safe = str(search)
        for ch in (",", "(", ")"):
            safe = safe.replace(ch, " ")
        safe = safe.strip()
        if not safe:
            return None
        return f"title.ilike.%{safe}%,excerpt.ilike.%{safe}%"

    @staticmethod
    def _is_duplicate_slug(err: Exception) -> bool:
        """True when the error is the UNIQUE(slug) violation (Postgres 23505
        / PostgREST duplicate-key text), so the route can answer 409."""
        msg = str(err).lower()
        return (
            "23505" in msg
            or "duplicate key" in msg
            or ("unique" in msg and "slug" in msg)
        )

    def list_journal_posts(self, *, published_only: bool = True,
                           category: Optional[str] = None,
                           search: Optional[str] = None,
                           order_column: str = "published_at",
                           descending: bool = True,
                           tiebreak_column: str = "published_at",
                           limit: int = 50,
                           offset: int = 0) -> list:
        """Journal posts for the public index (published_only) or the CMS
        list (published_only=False). Best-effort → [] on any failure.

        `search` is a case-insensitive substring over title OR excerpt.
        The `curated` ordering passes order_column='sort_order'; a secondary
        order breaks ties within one sort_order.

        ``tiebreak_column`` picks that secondary order (FE amendment
        2026-07-25). The PUBLIC index keeps 'published_at' — every public row
        is published, so the date is non-NULL and is the meaningful order. The
        CMS list passes 'created_at' instead, because it INCLUDES DRAFTS: a
        draft's published_at is NULL, Postgres orders DESC as NULLS FIRST, and
        every new post starts at sort_order=0 — so a published_at tiebreak
        would float undated drafts above dated posts and shuffle the CMS list
        as dates get set. created_at is never NULL, so the CMS order is stable.
        """
        try:
            q = self.client.table("journal_post").select(self._JOURNAL_COLUMNS)
            if published_only:
                q = q.eq("status", "published")
            if category:
                q = q.eq("category", str(category))
            or_filter = self.journal_search_filter(search)
            if or_filter:
                q = q.or_(or_filter)
            # NOTE on NULL display dates: Postgres orders DESC as NULLS FIRST,
            # and this client cannot emit `nullslast` (order(nullsfirst=False)
            # emits no modifier at all, so the Postgres default stands). A
            # published row with published_at = NULL would therefore pin itself
            # to the top of the public index. That is prevented at the two
            # points where it can be enforced instead: validate_post_body
            # stamps a date whenever status becomes published, and the
            # migration backfills any row written directly via SQL.
            q = q.order(order_column, desc=bool(descending))
            if order_column != tiebreak_column:
                q = q.order(tiebreak_column, desc=True)
            res = q.range(int(offset), int(offset) + int(limit) - 1).execute()
            return getattr(res, "data", None) or []
        except Exception as e:
            logger.warning("list_journal_posts failed: %s", e)
            return []

    def count_journal_posts(self, *, published_only: bool = True,
                            category: Optional[str] = None,
                            search: Optional[str] = None) -> int:
        """Total matching posts, for the index's `total`. Best-effort → 0."""
        try:
            q = self.client.table("journal_post").select(
                "id", count="exact")
            if published_only:
                q = q.eq("status", "published")
            if category:
                q = q.eq("category", str(category))
            or_filter = self.journal_search_filter(search)
            if or_filter:
                q = q.or_(or_filter)
            res = q.execute()
            cnt = getattr(res, "count", None)
            if cnt is not None:
                return int(cnt)
            return len(getattr(res, "data", None) or [])
        except Exception as e:
            logger.warning("count_journal_posts failed: %s", e)
            return 0

    def get_journal_post_by_slug(self, slug: str, *,
                                 published_only: bool = True,
                                 strict: bool = False) -> Optional[dict]:
        """One post by slug, or None. `published_only` keeps a draft
        invisible on the public route (404, no existence leak).

        `strict=True` RE-RAISES an infrastructure error instead of returning
        None. The public by-slug route uses it: swallowing a Supabase blip
        into a None would render a live post as 404 "post not found", and the
        FE's ISR would then cache that 404 — a transient DB hiccup would take
        a real post off the site until the window expired. Missing row → None
        either way; only the error path differs.
        """
        if not slug:
            return None
        try:
            q = (
                self.client.table("journal_post")
                .select(self._JOURNAL_COLUMNS)
                .eq("slug", str(slug))
            )
            if published_only:
                q = q.eq("status", "published")
            res = q.limit(1).execute()
            rows = getattr(res, "data", None) or []
            return rows[0] if rows else None
        except Exception as e:
            logger.warning("get_journal_post_by_slug failed slug=%s: %s",
                           slug, e)
            if strict:
                raise
            return None

    def get_journal_post_by_id(self, post_id: str) -> Optional[dict]:
        """One post by id for the CMS editor (any status), or None."""
        if not post_id:
            return None
        try:
            res = (
                self.client.table("journal_post")
                .select(self._JOURNAL_COLUMNS)
                .eq("id", str(post_id))
                .limit(1)
                .execute()
            )
            rows = getattr(res, "data", None) or []
            return rows[0] if rows else None
        except Exception as e:
            logger.warning("get_journal_post_by_id failed id=%s: %s",
                           post_id, e)
            return None

    def create_journal_post(self, fields: dict):
        """Insert a post. Returns the created row, "DUPLICATE_SLUG" on a slug
        collision, or None on any other failure."""
        try:
            res = (
                self.client.table("journal_post")
                .insert(dict(fields or {}))
                .execute()
            )
            rows = getattr(res, "data", None) or []
            return rows[0] if rows else None
        except Exception as e:
            if self._is_duplicate_slug(e):
                return "DUPLICATE_SLUG"
            logger.error("create_journal_post failed: %s", e)
            return None

    def update_journal_post(self, post_id: str, fields: dict):
        """Patch a post. Returns the updated row, "DUPLICATE_SLUG" on a slug
        collision, or None when the row is missing / on any other failure."""
        if not post_id:
            return None
        payload = dict(fields or {})
        payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        try:
            res = (
                self.client.table("journal_post")
                .update(payload)
                .eq("id", str(post_id))
                .execute()
            )
            rows = getattr(res, "data", None) or []
            return rows[0] if rows else None
        except Exception as e:
            if self._is_duplicate_slug(e):
                return "DUPLICATE_SLUG"
            logger.error("update_journal_post failed id=%s: %s", post_id, e)
            return None

    def delete_journal_post(self, post_id: str) -> bool:
        """Delete a post. True on success. Best-effort."""
        if not post_id:
            return False
        try:
            self.client.table("journal_post").delete() \
                .eq("id", str(post_id)).execute()
            return True
        except Exception as e:
            logger.error("delete_journal_post failed id=%s: %s", post_id, e)
            return False

    def reorder_journal_posts(self, ids: list) -> int:
        """Assign sort_order by position in `ids` (the CMS's manual order).

        Returns how many updates were ACCEPTED without error — not how many
        rows matched, since PostgREST does not error on an update that hits
        zero rows. Best-effort per row, so one bad id cannot abort the rest.
        """
        written = 0
        for index, post_id in enumerate(ids or []):
            if not post_id:
                continue
            try:
                self.client.table("journal_post").update({
                    "sort_order": index,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }).eq("id", str(post_id)).execute()
                written += 1
            except Exception as e:
                logger.warning("reorder_journal_posts failed id=%s: %s",
                               post_id, e)
        return written

    def journal_category_counts(self) -> dict:
        """{category: published_count} for the optional categories endpoint.
        Counted in Python over the published slugs — the table is small and
        this avoids depending on a PostgREST group-by. Best-effort → {}."""
        try:
            res = (
                self.client.table("journal_post")
                .select("category")
                .eq("status", "published")
                .execute()
            )
            out: dict = {}
            for row in (getattr(res, "data", None) or []):
                key = (row or {}).get("category")
                if key:
                    out[key] = out.get(key, 0) + 1
            return out
        except Exception as e:
            logger.warning("journal_category_counts failed: %s", e)
            return {}

    # ── Community Content Studio (founder 2026-07-26) ─────────────────────
    # The three derived community posts hanging off a journal post. Same
    # best-effort discipline as the journal helpers above: a missing table
    # (migration pending) degrades to "no items" instead of 500ing the CMS.
    #
    # These rows are NEVER served by a public route — they carry no slug and
    # no status because they can never be published to the site.

    _COMMUNITY_COLUMNS = (
        "id, journal_post_id, kind, title, body, flags, pillar_id, "
        "pillar_name, theme, soft_cta_line, app_proof_line, model, "
        "generated_at, created_at, updated_at"
    )

    @staticmethod
    def _is_missing_community_table(error: Exception) -> bool:
        text = str(error).lower()
        return "journal_community_post" in text and (
            "does not exist" in text or "pgrst" in text
            or "could not find the table" in text
        )

    def upsert_journal_community_posts(self, journal_post_id: str,
                                       rows: list) -> list:
        """Write 1..3 derived posts, keyed on (journal_post_id, kind).

        Upsert rather than insert: regenerating a format REPLACES it instead
        of stacking duplicates, and a single-format reroll leaves its siblings
        alone. Returns the written rows, [] on failure.
        """
        if not journal_post_id or not rows:
            return []
        try:
            res = (
                self.client.table("journal_community_post")
                .upsert([dict(r) for r in rows],
                        on_conflict="journal_post_id,kind")
                .execute()
            )
            return getattr(res, "data", None) or []
        except Exception as e:
            if self._is_missing_community_table(e):
                logger.warning(
                    "upsert_journal_community_posts: table missing (run "
                    "migrations/add_journal_community_posts.sql) post=%s",
                    journal_post_id)
                return []
            logger.error("upsert_journal_community_posts failed post=%s: %s",
                         journal_post_id, e)
            return []

    def list_journal_community_posts(self,
                                     journal_post_id: Optional[str] = None
                                     ) -> list:
        """Derived posts for one parent, or ALL of them when the id is None —
        the CMS loads every item once and groups them client-side. []."""
        try:
            q = (
                self.client.table("journal_community_post")
                .select(self._COMMUNITY_COLUMNS)
            )
            if journal_post_id:
                q = q.eq("journal_post_id", str(journal_post_id))
            res = q.order("journal_post_id").order("kind").execute()
            return getattr(res, "data", None) or []
        except Exception as e:
            if self._is_missing_community_table(e):
                logger.warning(
                    "list_journal_community_posts: table missing (run "
                    "migrations/add_journal_community_posts.sql)")
                return []
            logger.warning("list_journal_community_posts failed: %s", e)
            return []

    def get_journal_community_post(self, item_id: str) -> Optional[dict]:
        """One derived post by id, or None."""
        if not item_id:
            return None
        try:
            res = (
                self.client.table("journal_community_post")
                .select(self._COMMUNITY_COLUMNS)
                .eq("id", str(item_id))
                .limit(1)
                .execute()
            )
            rows = getattr(res, "data", None) or []
            return rows[0] if rows else None
        except Exception as e:
            logger.warning("get_journal_community_post failed id=%s: %s",
                           item_id, e)
            return None

    def update_journal_community_post(self, item_id: str,
                                      changes: dict) -> Optional[dict]:
        """Patch the founder's manual edit (title/body). None on failure."""
        if not item_id or not changes:
            return None
        payload = dict(changes)
        payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        try:
            res = (
                self.client.table("journal_community_post")
                .update(payload)
                .eq("id", str(item_id))
                .execute()
            )
            rows = getattr(res, "data", None) or []
            return rows[0] if rows else None
        except Exception as e:
            logger.error("update_journal_community_post failed id=%s: %s",
                         item_id, e)
            return None

    def delete_journal_community_post(self, item_id: str) -> bool:
        """Delete one derived post. True on success. Best-effort."""
        if not item_id:
            return False
        try:
            self.client.table("journal_community_post").delete() \
                .eq("id", str(item_id)).execute()
            return True
        except Exception as e:
            logger.error("delete_journal_community_post failed id=%s: %s",
                         item_id, e)
            return False

    # ── Generated journal covers (founder 2026-07-28) ─────────────────────
    # Candidate cover images for a journal post. Same best-effort discipline
    # as the helpers above: a missing table (migration pending) degrades to
    # "no history" — the draw still works and still sets cover_image_url, the
    # founder just loses the strip of previous attempts.
    #
    # CMS-only rows. No public route reads this table; the site sees only the
    # promoted cover_image_url on journal_post.

    _POST_IMAGE_COLUMNS = (
        "id, journal_post_id, image_url, storage_key, alt_text, prompt, "
        "revised_prompt, notes, parent_image_id, flags, model, size, "
        "quality, created_at"
    )

    @staticmethod
    def _is_missing_post_image_table(error: Exception) -> bool:
        text = str(error).lower()
        return "journal_post_image" in text and (
            "does not exist" in text or "pgrst" in text
            or "could not find the table" in text
        )

    def insert_journal_post_image(self, row: dict) -> Optional[dict]:
        """Record one generated cover attempt. None on failure.

        Insert, never upsert: every attempt is kept so "Regenerate" is
        non-destructive and the founder can walk back to an earlier one.
        """
        if not row:
            return None
        try:
            res = (
                self.client.table("journal_post_image")
                .insert(dict(row))
                .execute()
            )
            rows = getattr(res, "data", None) or []
            return rows[0] if rows else None
        except Exception as e:
            if self._is_missing_post_image_table(e):
                logger.warning(
                    "insert_journal_post_image: table missing (run "
                    "migrations/add_journal_post_image.sql) post=%s",
                    row.get("journal_post_id"))
                return None
            logger.error("insert_journal_post_image failed post=%s: %s",
                         row.get("journal_post_id"), e)
            return None

    def list_journal_post_images(self, journal_post_id: str,
                                 limit: int = 24) -> list:
        """This post's cover attempts, newest first. []."""
        if not journal_post_id:
            return []
        try:
            res = (
                self.client.table("journal_post_image")
                .select(self._POST_IMAGE_COLUMNS)
                .eq("journal_post_id", str(journal_post_id))
                .order("created_at", desc=True)
                .limit(max(1, int(limit or 24)))
                .execute()
            )
            return getattr(res, "data", None) or []
        except Exception as e:
            if self._is_missing_post_image_table(e):
                logger.warning(
                    "list_journal_post_images: table missing (run "
                    "migrations/add_journal_post_image.sql)")
                return []
            logger.warning("list_journal_post_images failed post=%s: %s",
                           journal_post_id, e)
            return []

    def get_journal_post_image(self, image_id: str) -> Optional[dict]:
        """One cover attempt by id, or None."""
        if not image_id:
            return None
        try:
            res = (
                self.client.table("journal_post_image")
                .select(self._POST_IMAGE_COLUMNS)
                .eq("id", str(image_id))
                .limit(1)
                .execute()
            )
            rows = getattr(res, "data", None) or []
            return rows[0] if rows else None
        except Exception as e:
            if self._is_missing_post_image_table(e):
                logger.warning(
                    "get_journal_post_image: table missing (run "
                    "migrations/add_journal_post_image.sql)")
                return None
            logger.warning("get_journal_post_image failed id=%s: %s",
                           image_id, e)
            return None

    def delete_journal_post_image(self, image_id: str) -> bool:
        """Delete one cover attempt. True on success. Best-effort.

        The R2 object is intentionally left in place: the post may still point
        at this url (or a CDN may still be serving it), and an orphaned image
        is cheaper than a broken cover.
        """
        if not image_id:
            return False
        try:
            self.client.table("journal_post_image").delete() \
                .eq("id", str(image_id)).execute()
            return True
        except Exception as e:
            logger.error("delete_journal_post_image failed id=%s: %s",
                         image_id, e)
            return False

    def skip_snippet(self, snippet_id: str, is_skipped: bool = True) -> Optional[dict]:
        """Mark a snippet as skipped (hidden from user results)."""
        try:
            result = (
                self.client.table(SNIPPETS_TABLE)
                .update({"is_skipped": is_skipped})
                .eq("id", snippet_id)
                .execute()
            )
            if result.data and len(result.data) > 0:
                return result.data[0]
            return None
        except Exception as e:
            logger.error(f"skip_snippet failed: {e}")
            return None

    def hard_delete_charisma_snippet(self, snippet_id: str) -> Optional[dict]:
        """Permanently remove a charisma_snippets row.

        Phase 18.1 — admin "delete snippet" flow for garbage /
        misclassified extractions. Distinct from skip_snippet:
          - skip_snippet: soft-hide (is_skipped=TRUE), row remains
            in admin view + DB. Reversible.
          - hard_delete_charisma_snippet: row is GONE. coaching_
            attempts referencing it CASCADE-delete (per the FK
            in the Phase 2 migration); admin_annotation_events
            keyed on snippet_id stay in place (no FK) so the
            RLHF training signal isn't lost.

        Returns the deleted row dict on success (lets the caller
        log what was destroyed), None when nothing matched the
        id, or raises only on Supabase transport errors — the
        caller maps those to 500.

        Idempotent: deleting an already-gone row returns None
        cleanly, no exception, so the route layer can map to
        404 without retry.
        """
        try:
            # Read-before-delete so we can return the row in the
            # response AND tell "already gone" (None data) from
            # "Supabase rejected the delete" (exception).
            existing = (
                self.client.table(SNIPPETS_TABLE)
                .select("*")
                .eq("id", snippet_id)
                .limit(1)
                .execute()
            )
            if not (existing.data or []):
                return None
            self.client.table(SNIPPETS_TABLE).delete().eq(
                "id", snippet_id
            ).execute()
            return existing.data[0]
        except Exception as e:
            logger.error(
                "hard_delete_charisma_snippet failed snippet=%s err=%s",
                snippet_id, e,
            )
            raise

    # ------------------------------------------------------------------
    # Session-level global metrics & AI alignment
    # ------------------------------------------------------------------

    # ── Ticket 2 — Dad-joke onboarding opener ───────────────────────
    #
    # Two reads: one random pick (for /start), one by-id lookup (for
    # /next when FE returns the joke_id it was given). No writes —
    # admin curation endpoints (deactivate / edit / add) are out of
    # scope for v1.

    def get_random_dad_joke(self, locale: str = "en") -> Optional[dict]:
        """Pick one random active joke in the requested locale.

        Returns ``{id, setup, punchline, emoji}`` or None when:
          - dad_jokes table is missing (migration pending)
          - no active jokes in the locale
          - DB hiccup

        Approach: SELECT all active rows in the locale (small set,
        ≤ a few dozen at any plausible scale), pick one in Python
        with random.choice. Avoids the supabase-py limitation that
        ORDER BY random() isn't exposed cleanly, AND lets us seed
        the random in tests deterministically if we ever need to.
        """
        if not locale:
            locale = "en"
        try:
            res = (
                self.client.table("dad_jokes")
                .select("id, setup, punchline, emoji")
                .eq("locale", locale)
                .eq("active", True)
                .execute()
            )
            rows = res.data or []
        except Exception as e:
            err_low = str(e).lower()
            if (
                "dad_jokes" in err_low
                and ("does not exist" in err_low or "pgrst" in err_low)
            ):
                # Migration not yet run — caller falls back to no
                # opener (silent), which is the right UX: the joke
                # is decoration, never blocking.
                return None
            logger.warning(
                "get_random_dad_joke failed locale=%s err=%s",
                locale, e,
            )
            return None
        if not rows:
            return None

        import random
        return random.choice(rows)

    def dad_jokes_health(self) -> dict:
        """FIX.3 — Health probe for the dad_jokes table.

        Returns ``{table_exists, joke_count, sample_joke}`` so admin
        + FE can confirm the migration ran on Supabase. Catches the
        common deploy failure mode where the BE ships endpoints
        but the migration was forgotten — the opener silently
        skips (204) and nobody knows why.

        ``sample_joke`` is one active row (for visual confirmation
        the seed took), or None on empty table.
        """
        try:
            res = (
                self.client.table("dad_jokes")
                .select("id, setup, punchline, emoji, active")
                .eq("active", True)
                .limit(1)
                .execute()
            )
            rows = res.data or []
            # Re-query just the count without limit so the health
            # endpoint reflects actual seed size, not the limit-1.
            try:
                count_res = (
                    self.client.table("dad_jokes")
                    .select("id", count="exact")
                    .eq("active", True)
                    .execute()
                )
                total = count_res.count or len(rows)
            except Exception:
                total = len(rows)
            return {
                "table_exists": True,
                "joke_count": int(total),
                "sample_joke": rows[0] if rows else None,
            }
        except Exception as e:
            err_low = str(e).lower()
            if (
                "dad_jokes" in err_low
                and ("does not exist" in err_low or "pgrst" in err_low)
            ):
                return {
                    "table_exists": False,
                    "joke_count": 0,
                    "sample_joke": None,
                }
            logger.warning("dad_jokes_health failed err=%s", e)
            return {
                "table_exists": False,
                "joke_count": 0,
                "sample_joke": None,
                "error": str(e),
            }

    def get_dad_joke_by_id(self, joke_id: str) -> Optional[dict]:
        """Lookup a joke by id for the /next endpoint.

        The FE round-trips the joke_id from /start back to /next so
        the punchline endpoint can deliver the matching content
        without re-rolling random. Returns None when the id is
        unknown or the table is missing (caller falls back to
        skipping the punchline gracefully).
        """
        if not joke_id:
            return None
        try:
            res = (
                self.client.table("dad_jokes")
                .select("id, setup, punchline, emoji")
                .eq("id", joke_id)
                .limit(1)
                .execute()
            )
            rows = res.data or []
        except Exception as e:
            err_low = str(e).lower()
            if "dad_jokes" in err_low and (
                "does not exist" in err_low or "pgrst" in err_low
            ):
                return None
            logger.warning(
                "get_dad_joke_by_id failed jid=%s err=%s",
                joke_id, e,
            )
            return None
        if not rows:
            return None
        return rows[0]

    # ── tester-soft-v1 — KPI timeline + question pool ────────────────
    #
    # Two thin readers + one write path for the admin pool CRUD.
    # No business logic in db.py — services/kpi_timeline.py and
    # routes/v2_routes.py own the shaping.

    def list_chat_question_pool(
        self,
        *,
        intent: Optional[str] = None,
        locale: str = "en",
        active_only: bool = True,
    ) -> list[dict]:
        """Admin-facing read of the question pool.

        Filters: ``intent`` ('charisma' | 'stress' | 'trust' |
        'post_official'), ``locale``, ``active_only``. Returns
        ordered by ``created_at`` ascending so the admin sees the
        oldest entries first (matches insertion order for a
        sequentially-seeded pool).

        Returns [] on missing table — the foundation migration
        creates it but a stale env might miss the run.
        """
        try:
            query = (
                self.client.table("chat_question_pool")
                .select("*")
                .eq("locale", locale)
            )
            if intent is not None:
                query = query.eq("intent", intent)
            if active_only:
                query = query.eq("active", True)
            res = query.order("created_at", desc=False).execute()
            return res.data or []
        except Exception as e:
            err_low = str(e).lower()
            if (
                "chat_question_pool" in err_low
                and ("does not exist" in err_low or "pgrst" in err_low)
            ):
                return []
            logger.warning(
                "list_chat_question_pool failed err=%s", e,
            )
            return []

    def insert_chat_question(
        self,
        *,
        intent: str,
        text: str,
        weight: int = 100,
        locale: str = "en",
        position_hint: Optional[str] = None,
        created_by: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Optional[dict]:
        """Admin write: insert one question into the pool.

        Validation (intent / position_hint) is handled by the route
        layer's input validator; the DB-level CHECK constraint is
        the final gate and rejects bad enum values with a Postgres
        error that the route catches as 422.
        """
        payload: dict[str, Any] = {
            "intent": intent,
            "text": text,
            "weight": int(weight),
            "locale": locale,
            "active": True,
        }
        if position_hint is not None:
            payload["position_hint"] = position_hint
        if created_by:
            payload["created_by"] = created_by
        if notes:
            payload["notes"] = notes
        try:
            res = (
                self.client.table("chat_question_pool")
                .insert(payload)
                .execute()
            )
            rows = res.data or []
            return rows[0] if rows else None
        except Exception as e:
            logger.warning(
                "insert_chat_question failed intent=%s err=%s",
                intent, e,
            )
            return None

    def update_chat_question(
        self,
        question_id: str,
        *,
        text: Optional[str] = None,
        weight: Optional[int] = None,
        active: Optional[bool] = None,
        position_hint: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Optional[dict]:
        """Admin write: partial update of one question.

        Only fields explicitly passed are updated. intent + locale
        are intentionally NOT mutable here — those identify the
        question's pool slot; changing them is functionally a
        delete + re-insert and should be modeled that way to keep
        audit history honest.
        """
        payload: dict[str, Any] = {}
        if text is not None:
            payload["text"] = text
        if weight is not None:
            payload["weight"] = int(weight)
        if active is not None:
            payload["active"] = bool(active)
        if position_hint is not None:
            payload["position_hint"] = position_hint
        if notes is not None:
            payload["notes"] = notes
        if not payload:
            # No-op update; return current row.
            try:
                res = (
                    self.client.table("chat_question_pool")
                    .select("*")
                    .eq("id", question_id)
                    .limit(1)
                    .execute()
                )
                rows = res.data or []
                return rows[0] if rows else None
            except Exception:
                return None
        try:
            res = (
                self.client.table("chat_question_pool")
                .update(payload)
                .eq("id", question_id)
                .execute()
            )
            rows = res.data or []
            return rows[0] if rows else None
        except Exception as e:
            logger.warning(
                "update_chat_question failed qid=%s err=%s",
                question_id, e,
            )
            return None

    def soft_delete_chat_question(self, question_id: str) -> bool:
        """Admin write: flip ``active=False`` on one question.

        Soft-delete rather than hard-delete so the audit trail of
        "this question was previously asked of N users" stays
        intact. Reactivation is an update with active=True.
        """
        try:
            (
                self.client.table("chat_question_pool")
                .update({"active": False})
                .eq("id", question_id)
                .execute()
            )
            return True
        except Exception as e:
            logger.warning(
                "soft_delete_chat_question failed qid=%s err=%s",
                question_id, e,
            )
            return False

    # ── willab beta — Lab session source + history ──────────────────

    # ── willab — delivery layer (founder 2026-07-15) ────────────────────
    # Async analysis state · per-take coach Save · the one-block ideal text
    # · the user's notebook copy. See migrations/add_analysis_state.sql,
    # add_coach_feedback_saved.sql, add_coach_arc_ideal_text.sql,
    # add_user_arc_ideal_notes.sql.

    def publish_ideal_text_document_snapshot(
        self, *, arc_id: str, actor_id: str,
        acquisition_principal_id: str, project_id: str,
        source_take_session_id: str, version: int, source_generation: int,
        source_fingerprint_sha256: str, payload: dict,
        enrichment_seed: dict,
    ) -> Optional[dict]:
        """Atomically append and point at one immutable cold-open snapshot."""
        try:
            result = self.client.rpc(
                "publish_ideal_text_document_snapshot_v1", {
                    "p_arc_id": str(arc_id),
                    "p_actor_id": str(actor_id),
                    "p_acquisition_principal_id": str(
                        acquisition_principal_id),
                    "p_project_id": str(project_id),
                    "p_source_take_session_id": str(source_take_session_id),
                    "p_version": int(version),
                    "p_source_generation": int(source_generation),
                    "p_source_fingerprint_sha256": str(
                        source_fingerprint_sha256),
                    "p_payload": payload,
                    "p_enrichment_seed": enrichment_seed,
                }).execute()
            data = result.data
            if isinstance(data, list):
                data = data[0] if data else None
            return data if isinstance(data, dict) else None
        except Exception as error:
            logger.warning(
                "publish ideal-text document snapshot failed arc=%s: %s",
                arc_id, error)
            return None

    def get_ideal_text_document_generation(
        self, arc_id: str,
    ) -> Optional[int]:
        """Generation fence captured before snapshot materialisation."""
        if not arc_id:
            return None
        try:
            result = self.client.rpc(
                "read_ideal_text_document_generation_v1", {
                    "p_arc_id": str(arc_id),
                }).execute()
            data = result.data
            if isinstance(data, list):
                data = data[0] if data else None
            return int(data) if isinstance(data, int) else None
        except Exception as error:
            low = str(error).lower()
            if "read_ideal_text_document_generation_v1" in low and (
                    "does not exist" in low or "pgrst" in low):
                return None
            logger.warning("ideal-text generation read failed: %s", error)
            return None

    def write_ideal_text_feedback_bake(
        self, arc_id: str, actor_id: str, document_snapshot_id: str,
        payload: dict, computed_over_ms: int = 0,
    ) -> bool:
        """Store the Manager's block against one immutable document.

        ``computed_over_ms`` is how long the computation this block came out
        of actually took, measured by the caller. The row is dated from the
        START of that window (0351), because an answer committed while the
        Manager was running was NOT seen by it — and a bake dated at the write
        would outlive that answer and put a decided bookmark back on the page.
        Measured on the caller's own monotonic clock and sent as a duration,
        so no two machines' wall clocks are ever compared.

        Best-effort by contract: a failure here costs the next reader one live
        computation, which is what every reader did before this existed. It
        must never be able to fail a publish.
        """
        if not arc_id or not actor_id or not document_snapshot_id:
            return False
        if not isinstance(payload, dict):
            return False
        try:
            result = self.client.rpc(
                "write_ideal_text_feedback_bake_v1", {
                    "p_arc_id": str(arc_id),
                    "p_actor_id": str(actor_id),
                    "p_document_snapshot_id": str(document_snapshot_id),
                    "p_payload": payload,
                    "p_computed_over_ms": max(int(computed_over_ms or 0), 0),
                }).execute()
            return isinstance(result.data, dict)
        except Exception as error:
            logger.warning("ideal-text feedback bake write failed arc=%s: %s",
                           arc_id, error)
            return False

    def read_ideal_text_feedback_bake(
        self, arc_id: str, actor_id: str, document_snapshot_id: str,
    ) -> Optional[dict]:
        """The stored block for this exact document, or None.

        None means "compute it live" in every case — absent function, absent
        row, wrong snapshot, or a mutable-feedback write since the bake. The
        freshness rule lives in SQL (see the migration) so it cannot drift
        from the writer.
        """
        if not arc_id or not actor_id or not document_snapshot_id:
            return None
        try:
            result = self.client.rpc(
                "read_ideal_text_feedback_bake_v1", {
                    "p_arc_id": str(arc_id),
                    "p_actor_id": str(actor_id),
                    "p_document_snapshot_id": str(document_snapshot_id),
                }).execute()
            data = result.data
            if isinstance(data, list):
                data = data[0] if data else None
            if not isinstance(data, dict):
                return None
            payload = data.get("payload")
            return payload if isinstance(payload, dict) else None
        except Exception as error:
            low = str(error).lower()
            if "read_ideal_text_feedback_bake_v1" in low and (
                    "does not exist" in low or "pgrst" in low):
                return None
            logger.warning("ideal-text feedback bake read failed arc=%s: %s",
                           arc_id, error)
            return None

    def list_pending_ideal_text_document_publications(
        self, limit: int = 100,
    ) -> list[dict]:
        """Durable generation rows whose current snapshot is still absent."""
        try:
            result = self.client.rpc(
                "list_pending_ideal_text_document_publications_v1", {
                    "p_limit": max(1, min(int(limit), 500)),
                }).execute()
            return [row for row in (result.data or [])
                    if isinstance(row, dict) and row.get("arc_id")]
        except Exception as error:
            low = str(error).lower()
            if "list_pending_ideal_text_document_publications_v1" in low and (
                    "does not exist" in low or "pgrst" in low):
                return []
            logger.warning("ideal-text pending publication read failed: %s",
                           error)
            return []

    def get_ideal_text_document_snapshot(
        self, arc_id: str, actor_id: str,
        snapshot_id: Optional[str] = None,
    ) -> Optional[dict]:
        """One immutable snapshot, current by default; strictly read-only."""
        if not arc_id or not actor_id:
            return None
        try:
            if snapshot_id:
                rows = self._execute_with_retry(
                    lambda: (self.client.table("ideal_text_document_snapshots")
                             .select("*").eq("id", str(snapshot_id))
                             .eq("arc_id", str(arc_id))
                             .eq("actor_id", str(actor_id)).limit(1)),
                    label="ideal_text_snapshot_by_id").data or []
                return rows[0] if rows else None
            heads = self._execute_with_retry(
                lambda: (self.client.table("ideal_text_document_heads")
                         .select("snapshot_id").eq("arc_id", str(arc_id))
                         .eq("actor_id", str(actor_id)).limit(1)),
                label="ideal_text_snapshot_head").data or []
            if not heads:
                return None
            head_id = str(heads[0]["snapshot_id"])
            rows = self._execute_with_retry(
                lambda: (self.client.table("ideal_text_document_snapshots")
                         .select("*").eq("id", head_id).limit(1)),
                label="ideal_text_snapshot_current").data or []
            return rows[0] if rows else None
        except Exception as error:
            low = str(error).lower()
            if "ideal_text_document_" in low and (
                    "does not exist" in low or "pgrst" in low):
                return None
            # Same swallow as the core reads below: a broken snapshot read and
            # an arc with no snapshot both leave as `None`.
            from services.f1_observability import observe_f1_degrade
            observe_f1_degrade(
                "ideal_text_snapshot_read_failed", exc=error,
                arc_id=arc_id, error=error)
            return None

    def get_ideal_text_document_core(
        self, arc_id: str, actor_id: str, *, raise_on_failure: bool = False,
    ) -> Optional[dict]:
        """One owner-checked RPC read for the strict cold-open path.

        ``raise_on_failure``: the core GET passes True, so a read that FAILED
        raises ``IdealTextCoreReadError`` instead of returning the ``None``
        that means "no document". Every other caller keeps ``None``."""
        if not arc_id or not actor_id:
            return None
        try:
            # A dropped connection is retried on a fresh client (the same
            # helper every other hot read uses) before it counts as a failure.
            result = self._execute_with_retry(
                lambda: self.client.rpc(
                    "read_ideal_text_document_core_v1", {
                        "p_arc_id": str(arc_id),
                        "p_actor_id": str(actor_id),
                    }),
                label="ideal_text_core_v1")
            data = result.data
            if isinstance(data, list):
                data = data[0] if data else None
            return data if isinstance(data, dict) else None
        except Exception as error:
            low = str(error).lower()
            if "read_ideal_text_document_core_v1" in low and (
                    "does not exist" in low or "pgrst" in low):
                return None
            # The last read standing: when this one fails the arc has no
            # readable document at all, and `None` is indistinguishable from
            # the honest "this arc has no Ideal Text yet" — the core GET turns
            # both into `404 IDEAL_TEXT_DOCUMENT_PENDING, state=pending`. So a
            # total read outage is reported to the user as "not ready yet" and
            # to us as nothing. Keep the return (the recording loop must not
            # break on a read fault); report the fault.
            from services.f1_observability import observe_f1_degrade
            observe_f1_degrade(
                "ideal_text_core_read_failed", exc=error,
                arc_id=arc_id, error=error)
            # Only a DROPPED CONNECTION is "try again". Any other RPC error on
            # this read is what an arc without a readable head has always
            # answered (production 2026-09-26: raising on every error turned
            # such arcs into a 503 on every load), and stays "pending".
            if raise_on_failure and self._is_transient_postgrest_disconnect(error):
                raise IdealTextCoreReadError(str(error)) from error
            return None

    def get_ideal_text_document_core_v2(
        self, arc_id: str, actor_id: str,
    ) -> Optional[dict]:
        """One exact D29 core envelope; used only by the current core GET."""
        if not arc_id or not actor_id:
            return None
        try:
            result = self._execute_with_retry(
                lambda: self.client.rpc(
                    "read_ideal_text_document_core_v2", {
                        "p_arc_id": str(arc_id),
                        "p_actor_id": str(actor_id),
                    }),
                label="ideal_text_core_v2")
            data = result.data
            if isinstance(data, list):
                data = data[0] if data else None
            if data is None:
                return self._ideal_text_core_v1_fallback(
                    arc_id, actor_id, raise_on_failure=True)
            from services.confident_moment_bundle import (
                validate_ideal_text_core_v2,
            )
            return validate_ideal_text_core_v2(data)
        except Exception as error:
            low = str(error).lower()
            if "read_ideal_text_document_core_v2" in low and (
                    "does not exist" in low or "pgrst" in low):
                return self._ideal_text_core_v1_fallback(
                    arc_id, actor_id, raise_on_failure=True)
            # Never a 500 on the cold-open read. The v2 read introduced in #490
            # re-raised whatever its RPC or validator raised, and the RPC
            # raises (STRICT selects, explicit RAISE) for any arc without the
            # Point-7 rows — every older arc — so on 2026-09-15 every core
            # read in production was a 500 and the Ideal Text surface was
            # down (LIVE LOOP incident). The exception stays in the log with
            # its traceback, and the arc is served the way it was before #490:
            # the v1 read below, or "pending" when there is no document at
            # all. Nothing the v2 validator rejects is ever served as v2.
            logger.warning(
                "ideal-text core v2 read failed arc=%s: %s: %s",
                arc_id, type(error).__name__, error, exc_info=True)
            # ...and make that fallback COUNTABLE. The log line above is
            # written to a stream nobody watches, so the v2 read could degrade
            # to v1 for every arc in production — exactly what happened on
            # 2026-09-15 — and no signal would leave the box. Falling back is
            # correct; falling back silently, forever, is the failure mode.
            # `observe_f1_degrade` is the existing channel for precisely this
            # shape (see its module docstring); the Ideal Text read had simply
            # never been wired into it.
            from services.f1_observability import observe_f1_degrade
            observe_f1_degrade(
                "ideal_text_core_v2_read_failed", exc=error, arc_id=arc_id)
            # The core GET is this method's only caller, so a v1 read that
            # also FAILS raises rather than posing as "no document".
            return self._ideal_text_core_v1_fallback(
                arc_id, actor_id, raise_on_failure=True)

    def _ideal_text_core_v1_fallback(
        self, arc_id: str, actor_id: str, *, raise_on_failure: bool = False,
    ) -> Optional[dict]:
        """The pre-#490 cold-open document for an arc the v2 read cannot serve.

        ``read_ideal_text_document_core_v1`` still exists and returns the head
        snapshot for arcs that predate the Point-7 rows. It is served in the
        v2 envelope shape with an ``unavailable`` overlay (no owner-edit text,
        no Confident Moment summary), which is exactly what the core GET
        served before #490 plus the fields the FE mapper treats as optional.
        ``None`` when there is no document either way — the 404 "pending".
        """
        snapshot = self.get_ideal_text_document_core(
            arc_id, actor_id, raise_on_failure=raise_on_failure)
        if not isinstance(snapshot, dict) or not snapshot.get("payload"):
            return None
        logger.info(
            "ideal-text core served by the v1 fallback arc=%s snapshot=%s",
            arc_id, snapshot.get("id"))
        return {
            "ideal_text_core_read_contract_version":
                "ideal-text-document-core-v1-fallback",
            "snapshot": snapshot,
            "dynamic_overlay": {
                "owner_edit": None,
                "confident_moment_summary": None,
                "confident_moment_summary_status": {
                    "state": "unavailable",
                    "code": "core_v2_unavailable",
                    "retryable": False,
                },
            },
        }

    def persist_auto_ideal_text(self, arc_id: str, text: str,
                                *, take_count: Optional[int] = None,
                                document: Optional[dict] = None) -> bool:
        """Persist the MACHINE-assembled ideal-text draft (eager assembly at
        take 3, founder 2026-07-15; instant lane 2026-07-17).

        TWO copies since the instant lane:
          * ``auto_text`` — the frozen machine copy: ALWAYS refreshed (a
            re-record improves the free instant surface even after the coach
            starts editing). Never carries coach content.
          * ``text`` — the working/perfected copy: written only while the
            machine still owns it (updated_by IS NULL, unapproved). A coach's
            edit or approval is NEVER overwritten.
        updated_by stays NULL on machine writes (the machine's signature).
        Migration-pending fallback (auto_text column missing): the legacy
        single-column write with the legacy guard. Best-effort; False on
        guard-refuse / missing table / error.

        ``take_count`` — the arc's SPOKEN take count, which since founder
        2026-08-05 IS the version. See the versioning note below."""
        if not arc_id or not isinstance(text, str) or not text.strip():
            return False
        try:
            row = self.ideal_text.get_coach_arc_ideal_text(arc_id)
            coach_owned = bool(
                row and (row.get("updated_by") or row.get("approved_at")))
            _now = datetime.now(timezone.utc).isoformat()
            payload = {
                "arc_id": str(arc_id),
                "auto_text": text,
                "auto_updated_at": _now,
            }
            # PIECE PROVENANCE for the text we are writing, in the same upsert
            # so the two can never describe different documents. Character
            # offsets are only meaningful against the exact string they were
            # anchored to, so a document persisted a beat later than its text
            # is a document pointing at the wrong words.
            #
            # services/part_acoustics.fold_session reads this and had NOTHING
            # to read for its entire life — the column did not exist, the read
            # resolved to NULL, and the fold returned {} on every take without
            # a word in the log (fixed 2026-08-13, migrations/
            # add_coach_arc_ideal_text_document.sql).
            if isinstance(document, dict) and document.get("pieces"):
                payload["document"] = document
            # ── Versioning: THE VERSION IS THE TAKE COUNT (founder
            # 2026-08-05, "each take is different and each should be
            # verified"). Take 1 → 1.0, take 2 → 2.0, always. A bump
            # implicitly resets verification (verified_version < version
            # reads as unverified), which is the point: each take earns
            # its own coach pass.
            #
            # Pinning to the count rather than incrementing is what makes
            # this SAFE to call repeatedly. The old rule bumped whenever
            # the assembled text differed, so it had two failure modes at
            # once: a take that barely moved the text left the badge
            # frozen (the founder's "take 2 still says 1.0"), while an
            # idle re-open that did shift a character bumped the version
            # and silently un-verified a text nobody re-recorded. An
            # absolute count has neither — recompute it as often as you
            # like and it lands on the same number.
            #
            # take_count=None → the caller could not count (a failed read).
            # Fail CLOSED to the OLD change-detect rule rather than write a
            # wrong absolute: a stale number here would un-verify real
            # coach work. Pre-migration rows: the version key rides the
            # same upsert and the missing-column fallback below drops it.
            _old_auto = (row or {}).get("auto_text") or (
                (row or {}).get("text") if row and not coach_owned else None)
            if isinstance(take_count, int) and take_count >= 1:
                payload["version"] = take_count
            elif row is None:
                payload["version"] = 1
            elif (_old_auto or "").strip() != text.strip():
                _v = row.get("version")
                payload["version"] = (int(_v) + 1) if isinstance(_v, int) else 2
            if not coach_owned:
                payload.update({
                    "text": text,
                    "updated_by": None,
                    "updated_at": _now,
                })
            try:
                self.client.table("coach_arc_ideal_text").upsert(
                    payload, on_conflict="arc_id").execute()
                return True
            except Exception as _e_auto:
                _low = str(_e_auto).lower()
                if "document" in _low and "document" in payload:
                    # The provenance column is not migrated yet (run
                    # migrations/add_coach_arc_ideal_text_document.sql).
                    # Write the text anyway: a missing KPI input must never
                    # cost the student their assembled document.
                    payload.pop("document", None)
                    logger.warning(
                        "persist_auto_ideal_text: document column missing "
                        "(run migrations/add_coach_arc_ideal_text_document"
                        ".sql) — part acoustics will not fold arc=%s", arc_id,
                    )
                    self.client.table("coach_arc_ideal_text").upsert(
                        payload, on_conflict="arc_id").execute()
                    return True
                if "version" in _low and "version" in payload:
                    # Versioning columns not migrated yet (run
                    # migrations/add_ideal_text_versioning.sql) — write the
                    # copies without the version bump.
                    payload.pop("version", None)
                    self.client.table("coach_arc_ideal_text").upsert(
                        payload, on_conflict="arc_id").execute()
                    return True
                if "auto_text" not in _low and "auto_updated_at" not in _low:
                    raise
                # auto columns not migrated yet → the legacy behavior
                # (run migrations/add_ideal_text_auto_copy.sql).
                logger.warning(
                    "persist_auto_ideal_text: auto columns missing (run "
                    "migrations/add_ideal_text_auto_copy.sql) arc=%s", arc_id,
                )
                if coach_owned:
                    return False  # legacy guard: never clobber the coach
                self.client.table("coach_arc_ideal_text").upsert({
                    "arc_id": str(arc_id),
                    "text": text,
                    "updated_by": None,
                    "updated_at": _now,
                }, on_conflict="arc_id").execute()
                return True
        except Exception as e:
            _e = str(e).lower()
            if "coach_arc_ideal_text" in _e and (
                "does not exist" in _e or "pgrst" in _e
            ):
                logger.warning(
                    "persist_auto_ideal_text: table missing (run "
                    "migrations/add_coach_arc_ideal_text.sql) arc=%s", arc_id,
                )
                return False
            logger.warning("persist_auto_ideal_text failed arc=%s: %s",
                           arc_id, e)
            return False

    def finalize_ideal_text_take(
        self,
        arc_id: str,
        owner_user_id: str,
        take_session_id: str,
        take_index: int,
        moments: Any,
        auto_text: Optional[str] = None,
        document: Optional[dict] = None,
    ) -> Optional[dict]:
        """Atomically advance a later Take's review version.

        With ``auto_text`` (v2, founder 2026-09-25) the same transaction also
        writes the rebuilt words and their Slide map, superseding an owner
        edit and coach-verified text. Without it, v2 behaves exactly as v1.

        The SQL boundary preserves the canonical/owner-edited body, carries a
        current owner edit to the new review identity, and appends the matching
        historical snapshot in one transaction.  There is deliberately no
        direct-update fallback: reporting a successful Take between those
        writes is the lifecycle bug this RPC removes.
        """
        if (not arc_id or not owner_user_id or not take_session_id
                or isinstance(take_index, bool)
                or not isinstance(take_index, int) or take_index < 2):
            return None
        result = self.client.rpc("finalize_ideal_text_take_v2", {
            "p_arc_id": str(arc_id),
            "p_owner_user_id": str(owner_user_id),
            "p_take_session_id": str(take_session_id),
            "p_take_index": take_index,
            "p_moments": moments if isinstance(moments, list) else [],
            "p_auto_text": auto_text if isinstance(auto_text, str) else None,
            "p_document": document if isinstance(document, dict) else None,
        }).execute()
        data = result.data
        if isinstance(data, list):
            return data[0] if data and isinstance(data[0], dict) else None
        return data if isinstance(data, dict) else None

    def get_ideal_text_feedback_set(
        self, arc_id: Optional[str], take_session_id: Optional[str],
    ) -> Optional[dict]:
        """The immutable Manager selection for one Take, if already claimed."""
        if not arc_id or not take_session_id:
            return None
        try:
            res = (
                self.client.table("ideal_text_feedback_sets")
                .select("arc_id,take_session_id,take_index,review_version,"
                        "selected_keys,created_at")
                .eq("arc_id", str(arc_id))
                .eq("take_session_id", str(take_session_id))
                .limit(1)
                .execute()
            )
            rows = res.data or []
            return rows[0] if rows else None
        except Exception as e:
            low = str(e).lower()
            if "ideal_text_feedback_sets" in low and (
                    "does not exist" in low or "pgrst" in low):
                logger.warning(
                    "get_ideal_text_feedback_set: table missing (run "
                    "migrations/add_take_review_lifecycle.sql)")
                return None
            logger.warning(
                "get_ideal_text_feedback_set failed arc=%s take=%s: %s",
                arc_id, take_session_id, e)
            return None

    def claim_ideal_text_feedback_set(
        self,
        arc_id: str,
        owner_user_id: str,
        take_session_id: str,
        take_index: int,
        review_version: int,
        selected_keys: list,
    ) -> Optional[dict]:
        """Insert-once Manager selection; a racing caller receives the winner."""
        # THE CLIENT-SIDE COPY OF THE FREEZE RULE, and the one 0347 missed
        # (founder 2026-09-21: "still no bookmarks", V3 served items=4, then
        # "feedback set claim failed"). The migration and
        # `services.take_feedback_set` moved to V3's rule — a bounded set
        # that carries a Confident Voice item — while this guard still
        # demanded V2's exactly-three-families, returned None without a word,
        # and the caller wiped every bookmark V3 had just built. It mirrors
        # `claim_ideal_text_feedback_set_v1` now, and the Manager alone owns
        # the budget (L2).
        if (not arc_id or not owner_user_id or not take_session_id
                or isinstance(take_index, bool)
                or not isinstance(take_index, int) or take_index < 1
                or review_version != take_index
                or not _freezable_selection(selected_keys)):
            return None
        result = self.client.rpc("claim_ideal_text_feedback_set_v1", {
            "p_arc_id": str(arc_id),
            "p_owner_user_id": str(owner_user_id),
            "p_take_session_id": str(take_session_id),
            "p_take_index": take_index,
            "p_review_version": review_version,
            "p_selected_keys": selected_keys,
        }).execute()
        data = result.data
        row = (data[0] if isinstance(data, list) and data
               and isinstance(data[0], dict)
               else data if isinstance(data, dict) else None)
        if not isinstance(row, dict):
            return None
        if (str(row.get("arc_id") or "") != str(arc_id)
                or str(row.get("take_session_id") or "")
                != str(take_session_id)
                or row.get("take_index") != take_index
                or row.get("review_version") != review_version):
            logger.error(
                "claim_ideal_text_feedback_set returned conflicting "
                "provenance arc=%s take=%s row=%s",
                arc_id, take_session_id, row)
            return None
        return row

    def insert_take_feedback_exposure(
        self, *, arc_id: str, take_session_id: str, review_version: int,
        policy_version: str, candidate_set: list, selected_keys: list,
        model_version: Optional[str] = None,
        prompt_version: Optional[str] = None,
    ) -> bool:
        """Insert the complete ranking exposure once; never update history."""
        if (not arc_id or not take_session_id or not policy_version
                or not isinstance(candidate_set, list)
                or not _freezable_selection(selected_keys)):
            return False
        try:
            self.client.table("take_feedback_exposure").upsert({
                "arc_id": str(arc_id),
                "take_session_id": str(take_session_id),
                "review_version": int(review_version),
                "policy_version": str(policy_version),
                "model_version": model_version,
                "prompt_version": prompt_version,
                "candidate_set": candidate_set,
                "selected_keys": selected_keys,
            }, on_conflict="arc_id,take_session_id",
                ignore_duplicates=True).execute()
            return True
        except Exception as e:
            logger.warning("take feedback exposure insert failed: %s", e)
            return False

    def record_take_feedback_policy_v3_shadow(
        self, *, arc_id: str, take_session_id: str, recording_id: str,
        acquisition_principal_id: str, owner_user_id: str, take_index: int,
        policy_version: str, frame: dict, frame_hash: str,
    ) -> Optional[dict]:
        """Persist one immutable, non-rendered v3 comparison frame."""
        if (not all((arc_id, take_session_id, recording_id,
                     acquisition_principal_id,
                     owner_user_id, policy_version, frame_hash))
                or isinstance(take_index, bool)
                or not isinstance(take_index, int) or take_index < 1
                or not isinstance(frame, dict)
                or frame.get("serves_user_feedback") is not False
                or frame.get("dataset_eligible") is not False):
            return None
        try:
            result = self.client.rpc(
                "record_take_feedback_policy_v3_shadow_v3",
                {
                    "p_arc_id": str(arc_id),
                    "p_take_session_id": str(take_session_id),
                    "p_recording_id": str(recording_id),
                    "p_acquisition_principal_id": str(
                        acquisition_principal_id
                    ),
                    "p_owner_user_id": str(owner_user_id),
                    "p_take_index": take_index,
                    "p_policy_version": str(policy_version),
                    "p_frame": frame,
                    "p_frame_hash": str(frame_hash),
                },
            ).execute()
            data = result.data
            if isinstance(data, list):
                return data[0] if data and isinstance(data[0], dict) else None
            return data if isinstance(data, dict) else None
        except Exception as error:
            logger.warning("take feedback v3 dark frame failed: %s", error)
            return None

    def register_recording_attempt(
        self, *, attempt_id: str, owner_principal_id: str, project_id: str,
        upload_idempotency_key: str, recording_id: str,
        storage_bucket: str, storage_key: str, recording_kind: str,
        input_hash: str,
    ) -> Optional[dict]:
        """Register durable audio as an Attempt, never as a completed Take."""
        if not all((attempt_id, owner_principal_id, project_id,
                    upload_idempotency_key, recording_id, storage_bucket,
                    storage_key, recording_kind, input_hash)):
            return None
        try:
            result = self.client.rpc("register_recording_attempt_v1", {
                "p_attempt_id": str(attempt_id),
                "p_owner_principal_id": str(owner_principal_id),
                "p_project_id": str(project_id),
                "p_upload_idempotency_key": str(upload_idempotency_key),
                "p_recording_id": str(recording_id),
                "p_storage_bucket": str(storage_bucket),
                "p_storage_key": str(storage_key),
                "p_recording_kind": str(recording_kind),
                "p_input_hash": str(input_hash),
            }).execute()
            data = result.data
            if isinstance(data, list):
                return data[0] if data and isinstance(data[0], dict) else None
            return data if isinstance(data, dict) else None
        except Exception as error:
            logger.error(
                "recording attempt registration failed attempt=%s: %s",
                attempt_id, error,
            )
            return None

    def record_processing_transition(
        self, *, recording_attempt_id: str,
        processing_job_id: Optional[str], to_status: str, stage: str,
        attempt_count: int, input_hash: str, idempotency_key: str,
        output_hash: Optional[str] = None,
        error: Optional[dict] = None,
    ) -> Optional[dict]:
        """Append one lifecycle transition and advance the Attempt read model."""
        if (not all((recording_attempt_id, to_status, stage, input_hash,
                    idempotency_key)) or isinstance(attempt_count, bool)
                or attempt_count < 1):
            return None
        try:
            result = self.client.rpc("record_processing_transition_v1", {
                "p_recording_attempt_id": str(recording_attempt_id),
                "p_processing_job_id": (
                    str(processing_job_id) if processing_job_id else None
                ),
                "p_to_status": str(to_status),
                "p_stage": str(stage),
                "p_attempt_count": int(attempt_count),
                "p_input_hash": str(input_hash),
                "p_output_hash": str(output_hash) if output_hash else None,
                "p_error": error if isinstance(error, dict) else None,
                "p_idempotency_key": str(idempotency_key),
            }).execute()
            data = result.data
            if isinstance(data, list):
                return data[0] if data and isinstance(data[0], dict) else None
            return data if isinstance(data, dict) else None
        except Exception as transition_error:
            logger.error(
                "processing transition failed attempt=%s status=%s: %s",
                recording_attempt_id, to_status, transition_error,
            )
            return None

    def promote_recording_attempt_to_take(
        self, *, recording_attempt_id: str, completion_hash: str,
        processing_job_id: Optional[str], attempt_count: int,
        input_hash: str, output_hash: Optional[str], idempotency_key: str,
    ) -> Optional[dict]:
        """Atomically assign the next successful project Take ordinal."""
        if (not all((recording_attempt_id, completion_hash, input_hash,
                    idempotency_key)) or isinstance(attempt_count, bool)
                or attempt_count < 1):
            return None
        try:
            # Retried on a transient transport drop: the RPC is idempotent on
            # (attempt, completion_hash), so a replay returns the same Take.
            # Without this, one dropped connection at the very end threw the
            # whole attempt away and the job re-ran transcription and the
            # Ideal Text from the start (the founder's Takes of 2026-10-02
            # and 03, during the database incident).
            result = self._execute_with_retry(
                lambda: self.client.rpc(
                    "promote_recording_attempt_to_take_v1", {
                        "p_recording_attempt_id": str(recording_attempt_id),
                        "p_completion_hash": str(completion_hash),
                        "p_processing_job_id": (
                            str(processing_job_id) if processing_job_id else None
                        ),
                        "p_attempt_count": int(attempt_count),
                        "p_input_hash": str(input_hash),
                        "p_output_hash": str(output_hash) if output_hash else None,
                        "p_idempotency_key": str(idempotency_key),
                    }),
                label="promote_recording_attempt_to_take")
            data = result.data
            if isinstance(data, list):
                data = data[0] if data and isinstance(data[0], dict) else None
            if not isinstance(data, dict):
                return None
            take_id = data.get("take_id")
            try:
                import uuid as _uuid
                canonical_take_id = str(_uuid.UUID(str(take_id)))
            except (TypeError, ValueError):
                return None
            if canonical_take_id != take_id:
                return None
            try:
                from services.confident_moment_delivery_worker import (
                    arm_confident_moment_deliveries_for_take,
                )
                arm_confident_moment_deliveries_for_take(
                    canonical_take_id, idempotency_key
                )
            except Exception as arm_error:  # noqa: BLE001
                logger.warning(
                    "post-promotion Confident Moment arm failed: %s", arm_error
                )
            return data
        except Exception as promotion_error:
            logger.error(
                "recording attempt promotion failed attempt=%s: %s",
                recording_attempt_id, promotion_error,
            )
            return None

    def get_recording_attempt_owner_principal(self, attempt_id: str) -> str:
        """The attempt's owner principal, or "" (unknown reads as not
        eligible for the canonical producer; the plain promotion runs)."""
        if not attempt_id:
            return ""
        try:
            result = (self.client.table("recording_attempts")
                      .select("owner_principal_id")
                      .eq("id", str(attempt_id)).limit(1).execute())
            row = (result.data or [None])[0]
            return str((row or {}).get("owner_principal_id") or "")
        except Exception:
            logger.warning(
                "get_recording_attempt_owner_principal failed attempt=%s",
                attempt_id, exc_info=True)
            return ""

    def promote_recording_attempt_with_confidence_outbox(
        self, *, recording_attempt_id: str, completion_hash: str,
        processing_job_id: Optional[str], attempt_count: int,
        input_hash: str, output_hash: Optional[str], idempotency_key: str,
        source_manifest: dict,
    ) -> Optional[dict]:
        """Atomically promote one Take and enqueue its MLC-2 source event.

        This RPC is unreachable while the code-level confidence cutover flag
        is false.  Product state and its outbox event commit or roll back
        together; a worker failure later never reverses the successful Take.
        """
        if (not all((recording_attempt_id, completion_hash, input_hash,
                     idempotency_key)) or isinstance(attempt_count, bool)
                or attempt_count < 1 or not isinstance(source_manifest, dict)):
            return None
        try:
            # Same transient-drop retry as the plain promotion: idempotent on
            # (attempt, completion_hash); the outbox event is written in the
            # same transaction, so a replay neither doubles nor loses it.
            result = self._execute_with_retry(
                lambda: self.client.rpc(
                    "promote_recording_attempt_with_mlc2_confidence_v1", {
                        "p_recording_attempt_id": str(recording_attempt_id),
                        "p_completion_hash": str(completion_hash),
                        "p_processing_job_id": (
                            str(processing_job_id) if processing_job_id else None
                        ),
                        "p_attempt_count": int(attempt_count),
                        "p_input_hash": str(input_hash),
                        "p_output_hash": (
                            str(output_hash) if output_hash else None
                        ),
                        "p_idempotency_key": str(idempotency_key),
                        "p_source_manifest": source_manifest,
                    }),
                label="promote_recording_attempt_with_confidence_outbox")
            data = result.data
            if isinstance(data, list):
                return data[0] if data and isinstance(data[0], dict) else None
            return data if isinstance(data, dict) else None
        except Exception as promotion_error:
            logger.error(
                "recording attempt confidence promotion failed attempt=%s: %s",
                recording_attempt_id, promotion_error,
            )
            return None

    def record_canonical_feedback_exposure(self, bundle: dict) -> Optional[dict]:
        """Atomically dual-write one complete canonical candidate ledger.

        Compatibility tables remain the product read model during parity, so
        this method is deliberately best-effort. The SQL RPC itself is strict
        and all-or-nothing: it either records transcript/evidence/candidates/
        exposures together or writes none of them.
        """
        if not isinstance(bundle, dict):
            return None
        required = (
            "owner_principal_id", "project_id", "take_id", "candidates",
            "selected_keys", "versions", "input_hash", "idempotency_key",
        )
        if any(not bundle.get(key) for key in required):
            return None
        try:
            result = self.client.rpc("record_feedback_exposure_v1", {
                "p_owner_principal_id": str(bundle["owner_principal_id"]),
                "p_project_id": str(bundle["project_id"]),
                "p_take_id": str(bundle["take_id"]),
                "p_bundle": bundle,
            }).execute()
            data = result.data
            if isinstance(data, list):
                return data[0] if data and isinstance(data[0], dict) else None
            return data if isinstance(data, dict) else None
        except Exception as error:
            logger.warning(
                "canonical feedback exposure dual-write failed take=%s: %s",
                bundle.get("take_id"), error,
            )
            return None

    def create_learning_surface_presentation(
        self, presentation: dict,
    ) -> Optional[dict]:
        """Freeze an actor-specific packet; this is not an exposure receipt."""
        if not isinstance(presentation, dict):
            return None
        required = (
            "owner_principal_id", "project_id", "take_id",
            "learning_surface", "actor_role", "actor_id",
            "complete_candidate_set", "selected_candidate",
            "visible_payload", "versions", "content_hash",
            "delivery_mode", "idempotency_key",
        )
        if any(presentation.get(key) in (None, "") for key in required):
            return None
        try:
            result = self.client.rpc(
                "create_learning_surface_presentation_v1", {
                    "p_owner_principal_id": str(
                        presentation["owner_principal_id"]),
                    "p_project_id": str(presentation["project_id"]),
                    "p_take_id": str(presentation["take_id"]),
                    "p_evidence_span_id": presentation.get(
                        "evidence_span_id"),
                    "p_candidate_set_id": presentation.get(
                        "candidate_set_id"),
                    "p_generation_run_id": presentation.get(
                        "generation_run_id"),
                    "p_learning_surface": str(
                        presentation["learning_surface"]),
                    "p_actor_role": str(presentation["actor_role"]),
                    "p_actor_id": str(presentation["actor_id"]),
                    "p_complete_candidate_set": presentation[
                        "complete_candidate_set"],
                    "p_selected_candidate": presentation[
                        "selected_candidate"],
                    "p_visible_payload": presentation["visible_payload"],
                    "p_versions": presentation["versions"],
                    "p_content_hash": str(presentation["content_hash"]),
                    "p_delivery_mode": str(presentation["delivery_mode"]),
                    "p_idempotency_key": str(
                        presentation["idempotency_key"]),
                }).execute()
            data = result.data
            if isinstance(data, list):
                return data[0] if data and isinstance(data[0], dict) else None
            return data if isinstance(data, dict) else None
        except Exception as error:
            logger.warning(
                "learning presentation write failed take=%s surface=%s: %s",
                presentation.get("take_id"),
                presentation.get("learning_surface"), error,
            )
            return None

    def acknowledge_learning_surface_exposure(
        self, acknowledgement: dict,
    ) -> Optional[dict]:
        """Record a true post-render receipt for one exact actor."""
        if not isinstance(acknowledgement, dict):
            return None

        required = (
            "presentation_id", "acknowledgement_token", "actor_role",
            "actor_id", "render_instance_id", "idempotency_key",
        )
        if any(not acknowledgement.get(key) for key in required):
            return None
        try:
            result = self.client.rpc(
                "ack_learning_surface_exposure_v1", {
                    "p_presentation_id": str(
                        acknowledgement["presentation_id"]),
                    "p_acknowledgement_token": str(
                        acknowledgement["acknowledgement_token"]),
                    "p_actor_role": str(acknowledgement["actor_role"]),
                    "p_actor_id": str(acknowledgement["actor_id"]),
                    "p_render_instance_id": str(
                        acknowledgement["render_instance_id"]),
                    "p_client_rendered_at": acknowledgement.get(
                        "client_rendered_at"),
                    "p_idempotency_key": str(
                        acknowledgement["idempotency_key"]),
                }).execute()
            data = result.data
            if isinstance(data, list):
                return data[0] if data and isinstance(data[0], dict) else None
            return data if isinstance(data, dict) else None
        except Exception as error:
            logger.warning(
                "learning exposure acknowledgement failed presentation=%s: %s",
                acknowledgement.get("presentation_id"), error,
            )
            return None

    def get_seven_surface_readiness(self) -> Optional[dict]:
        """Read aggregate ML readiness; no row-level product data is returned."""
        try:
            result = self.client.rpc(
                "get_seven_surface_readiness_v1", {}).execute()
            data = result.data
            if isinstance(data, list):
                data = data[0] if data else None
            return data if isinstance(data, dict) else None
        except Exception as error:
            logger.warning("seven-surface readiness unavailable: %s", error)
            return None

    def record_canonical_feedback_decision(
        self, *, project_id: str, take_id: str, rater_id: str,
        decision: dict,
    ) -> Optional[dict]:
        """Write one typed owner decision against a selected exposure."""
        if not all((project_id, take_id, rater_id)) or not isinstance(
                decision, dict):
            return None
        try:
            result = self.client.rpc("record_feedback_human_decision_v1", {
                "p_project_id": str(project_id),
                "p_take_id": str(take_id),
                "p_rater_id": str(rater_id),
                "p_feedback_membership_id": str(
                    decision["feedback_membership_id"]),
                "p_candidate_id": str(decision["candidate_id"]),
                "p_feedback_exposure_id": str(
                    decision["feedback_exposure_id"]),
                "p_feedback_family": str(decision["feedback_family"]),
                "p_value": str(decision["value"]),
                "p_taxonomy_version": str(decision["taxonomy_version"]),
                "p_idempotency_key": str(decision["idempotency_key"]),
            }).execute()
            data = result.data
            if isinstance(data, list):
                return data[0] if data and isinstance(data[0], dict) else None
            return data if isinstance(data, dict) else None
        except Exception as error:
            logger.warning(
                "canonical feedback decision dual-write failed take=%s "
                "feedback=%s: %s",
                take_id, decision.get("feedback_id"), error,
            )
            return None

    def record_canonical_paragraph_decision(
        self, decision: dict,
    ) -> Optional[dict]:
        """Append an exact paragraph lock/evolve/reopen decision."""
        if not isinstance(decision, dict):
            return None
        try:
            result = self.client.rpc("record_paragraph_decision_v1", {
                "p_project_id": str(decision["project_id"]),
                "p_take_id": str(decision["take_id"]),
                "p_rater_id": str(decision["rater_id"]),
                "p_source_ideal_part_id": str(
                    decision["source_ideal_part_id"]),
                "p_exact_text": str(decision["exact_text"]),
                "p_value": str(decision["value"]),
                "p_taxonomy_version": str(decision["taxonomy_version"]),
                "p_evidence_id": str(decision["evidence_id"]),
                "p_evidence_hash": str(decision["evidence_hash"]),
                "p_input_hash": str(decision["input_hash"]),
                "p_idempotency_key": str(decision["idempotency_key"]),
            }).execute()
            data = result.data
            if isinstance(data, list):
                return data[0] if data and isinstance(data[0], dict) else None
            return data if isinstance(data, dict) else None
        except Exception as paragraph_error:
            logger.warning(
                "canonical paragraph decision dual-write failed "
                "take=%s part=%s: %s",
                decision.get("take_id"),
                decision.get("source_ideal_part_id"), paragraph_error,
            )
            return None

    def record_canonical_root_phrase(self, root: dict) -> Optional[dict]:
        """Append one exact orange phrase backed by the current lock."""
        if not isinstance(root, dict):
            return None
        try:
            result = self.client.rpc("record_root_phrase_v1", {
                "p_project_id": str(root["project_id"]),
                "p_take_id": str(root["take_id"]),
                "p_rater_id": str(root["rater_id"]),
                "p_source_ideal_part_id": str(
                    root["source_ideal_part_id"]),
                "p_exact_text": str(root["exact_text"]),
                "p_start_char": int(root["start"]),
                "p_end_char": int(root["end"]),
                "p_idempotency_key": str(root["idempotency_key"]),
            }).execute()
            data = result.data
            if isinstance(data, list):
                return data[0] if data and isinstance(data[0], dict) else None
            return data if isinstance(data, dict) else None
        except Exception as root_error:
            logger.warning(
                "canonical root phrase dual-write failed take=%s part=%s: %s",
                root.get("take_id"), root.get("source_ideal_part_id"),
                root_error,
            )
            return None

    def record_canonical_root_phrase_skip(
        self, skip: dict,
    ) -> Optional[dict]:
        """Append an explicit no-orange decision for one locked paragraph."""
        if not isinstance(skip, dict):
            return None
        try:
            result = self.client.rpc("record_root_phrase_skip_v1", {
                "p_project_id": str(skip["project_id"]),
                "p_take_id": str(skip["take_id"]),
                "p_rater_id": str(skip["rater_id"]),
                "p_source_ideal_part_id": str(
                    skip["source_ideal_part_id"]),
                "p_taxonomy_version": str(skip["taxonomy_version"]),
                "p_idempotency_key": str(skip["idempotency_key"]),
            }).execute()
            data = result.data
            if isinstance(data, list):
                return data[0] if data and isinstance(data[0], dict) else None
            return data if isinstance(data, dict) else None
        except Exception as skip_error:
            logger.warning(
                "canonical root phrase skip dual-write failed "
                "take=%s part=%s: %s",
                skip.get("take_id"), skip.get("source_ideal_part_id"),
                skip_error,
            )
            return None

    def record_canonical_coach_confidence_judgment(
        self, *, evidence_span_id: str, coach_id: str, value: str,
        taxonomy_version: str, blind_packet_hash: str,
        idempotency_key: str,
    ) -> Optional[dict]:
        """Append one blind coach judgment or a provenance-safe revision."""
        if not all((evidence_span_id, coach_id, value, taxonomy_version,
                    blind_packet_hash, idempotency_key)):
            return None
        try:
            result = self.client.rpc(
                "record_confidence_coach_judgment_v1", {
                    "p_evidence_span_id": str(evidence_span_id),
                    "p_coach_id": str(coach_id),
                    "p_value": str(value),
                    "p_taxonomy_version": str(taxonomy_version),
                    "p_blind_packet_hash": str(blind_packet_hash),
                    "p_idempotency_key": str(idempotency_key),
                }).execute()
            data = result.data
            if isinstance(data, list):
                return data[0] if data and isinstance(data[0], dict) else None
            return data if isinstance(data, dict) else None
        except Exception as error:
            logger.warning(
                "canonical coach confidence dual-write failed evidence=%s: %s",
                evidence_span_id, error,
            )
            return None

    def assign_canonical_coach_confidence_evidence(
        self, *, take_id: str, evidence_span_id: str, coach_id: str,
        blind_packet_hash: str, assignment_reason: str,
        idempotency_key: str,
    ) -> Optional[dict]:
        """Freeze the exact blind packet before accepting a coach label."""
        if not all((take_id, evidence_span_id, coach_id, blind_packet_hash,
                    assignment_reason, idempotency_key)):
            return None
        try:
            result = self.client.rpc(
                "assign_confidence_coach_evidence_v1", {
                    "p_take_id": str(take_id),
                    "p_evidence_span_id": str(evidence_span_id),
                    "p_coach_id": str(coach_id),
                    "p_blind_packet_hash": str(blind_packet_hash),
                    "p_assignment_reason": str(assignment_reason),
                    "p_idempotency_key": str(idempotency_key),
                }).execute()
            data = result.data
            if isinstance(data, list):
                return data[0] if data and isinstance(data[0], dict) else None
            return data if isinstance(data, dict) else None
        except Exception as assignment_error:
            logger.warning(
                "canonical coach evidence assignment failed "
                "take=%s evidence=%s: %s",
                take_id, evidence_span_id, assignment_error,
            )
            return None

    def record_canonical_processing_stage(
        self, *, processing_job_id: Optional[str], owner_principal_id: str,
        project_id: str, take_id: str, stage: str, status: str,
        attempt_count: int, input_hash: str,
        idempotency_key: str, output_hash: Optional[str] = None,
        error: Optional[dict] = None,
    ) -> Optional[dict]:
        """Create or advance one idempotent canonical stage attempt.

        The compatibility processing job remains the product polling model.
        This ledger is provenance only and is best-effort until parity gates
        promote it, while the SQL function strictly validates ownership,
        monotonic transitions and terminal immutability.
        """
        if (not all((owner_principal_id, project_id, take_id, stage, status,
                    input_hash, idempotency_key))
                or isinstance(attempt_count, bool) or attempt_count < 1):
            return None
        try:
            result = self.client.rpc("record_processing_stage_run_v1", {
                "p_processing_job_id": (
                    str(processing_job_id) if processing_job_id else None
                ),
                "p_owner_principal_id": str(owner_principal_id),
                "p_project_id": str(project_id),
                "p_take_id": str(take_id),
                "p_stage": str(stage),
                "p_status": str(status),
                "p_attempt_count": int(attempt_count),
                "p_input_hash": str(input_hash),
                "p_output_hash": str(output_hash) if output_hash else None,
                "p_idempotency_key": str(idempotency_key),
                "p_error": error if isinstance(error, dict) else None,
            }).execute()
            data = result.data
            if isinstance(data, list):
                return data[0] if data and isinstance(data[0], dict) else None
            return data if isinstance(data, dict) else None
        except Exception as stage_error:
            logger.warning(
                "canonical processing stage dual-write failed "
                "take=%s stage=%s status=%s: %s",
                take_id, stage, status, stage_error,
            )
            return None

    def insert_take_feedback_self_report(
        self, *, arc_id: str, take_session_id: str, owner_user_id: str,
        feedback_id: str, feedback_family: str, response: str,
        snippet_id: Optional[str] = None,
    ) -> Optional[dict]:
        """Validate frozen membership and append in one database transaction.

        Returns ``{outcome,row,selected_keys}``; same-value retries are replayed
        idempotently. There is deliberately no read/insert fallback because it
        would recreate the first-click race this boundary removes.
        """
        if not all((arc_id, take_session_id, owner_user_id, feedback_id,
                    feedback_family, response)):
            return None
        try:
            result = self.client.rpc("record_take_feedback_response_v1", {
                "p_arc_id": str(arc_id),
                "p_take_session_id": str(take_session_id),
                "p_owner_user_id": str(owner_user_id),
                "p_feedback_id": str(feedback_id),
                "p_feedback_family": str(feedback_family),
                "p_response": str(response),
                "p_supplied_snippet_id": (
                    str(snippet_id) if snippet_id else None
                ),
            }).execute()
            data = result.data
            if isinstance(data, list):
                return data[0] if data and isinstance(data[0], dict) else None
            return data if isinstance(data, dict) else None
        except Exception as e:
            logger.warning("atomic take feedback self-report failed: %s", e)
            return None

    def revise_take_feedback_self_report(
        self, *, take_session_id: str, owner_user_id: str, feedback_id: str,
        response: str,
    ) -> Optional[dict]:
        """A later answer to a Confident Voice judgement, kept beside the
        first (0440, D-FW-9; QA1 A). ``{outcome, row}``: 'revised',
        'replayed', 'not_answered' or 'not_revisable'; None on failure."""
        if not all((take_session_id, owner_user_id, feedback_id, response)):
            return None
        try:
            data = self.client.rpc("revise_take_feedback_response_v1", {
                "p_take_session_id": str(take_session_id),
                "p_owner_user_id": str(owner_user_id),
                "p_feedback_id": str(feedback_id),
                "p_response": str(response),
            }).execute().data
            if isinstance(data, list):
                data = data[0] if data else None
            return data if isinstance(data, dict) else None
        except Exception as e:
            logger.warning("take feedback revision failed: %s", e, exc_info=True)
            return None

    def _latest_self_reports(self, rows: Any) -> list:
        """The speaker's answers with each changed judgement at its latest
        (0440, D-FW-9). The first answer's row stays the row; `response`
        becomes the newest revision's and `first_response` keeps the first.
        Unreadable revisions leave the first answers, logged: the readers
        then see what they saw before 0440, never nothing."""
        rows = [row for row in (rows or []) if isinstance(row, dict)]
        ids = sorted({row["id"] for row in rows if row.get("id") is not None
                      and row.get("feedback_family") == "confident_voice"},
                     key=str)
        if not ids:
            return rows
        try:
            revisions = (self.client.table("take_feedback_self_report_revision")
                         .select("report_id,response,revision,created_at")
                         .in_("report_id", ids).execute().data) or []
        except Exception as e:
            logger.warning("judgement revisions unreadable: %s", e, exc_info=True)
            return rows
        def number(rev: dict) -> int:
            # A malformed revision counts as none, so it never raises into
            # the reader (GPT-0440 nit): the first answer stands instead.
            try:
                return int(rev.get("revision") or 0)
            except (TypeError, ValueError):
                return -1

        latest: dict[str, dict] = {}
        for rev in revisions:
            if not isinstance(rev, dict) or number(rev) < 1:
                continue
            key = str(rev.get("report_id"))
            if key not in latest or number(rev) > number(latest[key]):
                latest[key] = rev
        out = []
        for row in rows:
            rev = latest.get(str(row.get("id")))
            if rev is None:
                out.append(row)
                continue
            out.append({**row, "response": rev.get("response"),
                        "first_response": row.get("response"),
                        "revised_at": rev.get("created_at")})
        return out

    def list_take_feedback_self_reports(
        self, take_session_id: str, owner_user_id: Optional[str] = None,
    ) -> list:
        if not take_session_id:
            return []
        try:
            query = (self.client.table("take_feedback_self_report")
                     .select("*")
                     .eq("take_session_id", str(take_session_id)))
            if owner_user_id:
                query = query.eq("owner_user_id", str(owner_user_id))
            return self._latest_self_reports(
                query.order("created_at").execute().data or [])
        except Exception as e:
            if "take_feedback_self_report" not in str(e).lower():
                logger.warning("take feedback self-report read failed: %s", e)
            return []

    def list_feedback_v3_owner_response_keys(
        self, membership_ids: list,
    ) -> list:
        """(membership_id, candidate_id, response) rows the owner answered
        via the MLC-3 service route. Read-only; an empty list on any failure
        so the caller degrades to "not answered"."""
        ids = [str(value) for value in (membership_ids or []) if value]
        if not ids:
            return []
        try:
            result = (self.client.table("feedback_v3_owner_responses")
                      .select("membership_id,candidate_id,response")
                      .in_("membership_id", ids)
                      .execute())
        except Exception as error:
            logger.warning("feedback v3 owner responses read failed: %s",
                           error)
            return []
        rows = result.data if isinstance(result.data, list) else []
        return [row for row in rows if isinstance(row, dict)]

    def list_take_feedback_self_reports_by_snippet(
        self, snippet_id: str,
    ) -> list:
        """Exact-clip self-reports, separate from every coach-label table."""
        if not snippet_id:
            return []
        try:
            return self._latest_self_reports(
                (self.client.table("take_feedback_self_report")
                 .select("*")
                 .eq("snippet_id", str(snippet_id))
                 .order("created_at")
                 .execute().data) or [])
        except Exception as e:
            if "take_feedback_self_report" not in str(e).lower():
                logger.warning("clip self-report read failed: %s", e)
            return []

    def list_confident_voice_self_reports(self, arc_id: str, *,
                                          strict: bool = False) -> list:
        """``strict=True`` re-raises a failed read (a missing table is still
        an empty list)."""
        if not arc_id:
            return []
        try:
            return self._latest_self_reports(
                (self.client.table("take_feedback_self_report")
                 .select("*")
                 .eq("arc_id", str(arc_id))
                 .eq("feedback_family", "confident_voice")
                 .order("created_at")
                 .execute().data) or [])
        except Exception as e:
            if "take_feedback_self_report" not in str(e).lower():
                logger.warning("confident self-report read failed: %s", e)
                if strict:
                    raise
            return []

    def verify_ideal_text(self, arc_id: str, coach_id: Optional[str]) -> Optional[str]:
        """Coach VERIFY (single deliverable, founder 2026-07-17): snapshot the
        current best text as the VERIFIED copy of the CURRENT version — the
        coach's working copy when a human owns the row, else the machine copy.
        The snapshot keeps the served "verified" text stable even while the
        coach keeps editing afterwards; a later reassembly bumps `version`,
        which implicitly resets status to unverified.

        Returns 'verified' | 'already' (current version already verified) |
        None (nothing to verify / error)."""
        if not arc_id:
            return None
        try:
            row = self.ideal_text.get_coach_arc_ideal_text(arc_id)
            if not row:
                return None
            coach_owned = bool(row.get("updated_by") or row.get("approved_at"))
            best = ((row.get("text") or "") if coach_owned
                    else (row.get("auto_text") or row.get("text") or ""))
            best = best.strip()
            if not best:
                return None
            _v = row.get("version")
            version = int(_v) if isinstance(_v, int) else 1
            _vv = row.get("verified_version")
            if isinstance(_vv, int) and _vv == version:
                return "already"
            self.client.table("coach_arc_ideal_text").upsert({
                "arc_id": str(arc_id),
                "verified_version": version,
                "verified_text": best,
                "verified_at": datetime.now(timezone.utc).isoformat(),
                "verified_by": str(coach_id) if coach_id else None,
            }, on_conflict="arc_id").execute()
            return "verified"
        except Exception as e:
            logger.warning("verify_ideal_text failed arc=%s: %s", arc_id, e)
            return None

    def get_moment_unlock(self, arc_id: Optional[str]) -> Optional[dict]:
        """The presentation's key-moment unlock row (single deliverable,
        founder 2026-07-17 — the ONLY paid item: 5 credits, one-time per
        presentation, covers all current AND future moments). Deliberately a
        SEPARATE table from the retired $25 arc_purchases — no grandfathering
        (founder-explicit). None on missing table / no row / error."""
        if not arc_id:
            return None
        try:
            res = (
                self.client.table("moment_unlocks")
                .select("*")
                .eq("arc_id", str(arc_id))
                .limit(1)
                .execute()
            )
            rows = res.data or []
            return rows[0] if rows else None
        except Exception as e:
            _e = str(e).lower()
            if "moment_unlocks" in _e and (
                "does not exist" in _e or "pgrst" in _e
            ):
                return None  # migration pending → locked (never open)
            logger.warning("get_moment_unlock failed arc=%s: %s", arc_id, e)
            return None

    def insert_moment_unlock(
        self, arc_id: str, user_id: str, credits_spent: int,
    ) -> Optional[dict]:
        """Exclusive claim of the moments unlock — unique(arc_id) is the
        atomic double-charge guard (mirrors arc_purchases). Returns the row,
        or None on ANY conflict/error (the caller refunds)."""
        if not arc_id or not user_id:
            return None
        try:
            res = (
                self.client.table("moment_unlocks")
                .insert({
                    "arc_id": str(arc_id),
                    "user_id": str(user_id),
                    "credits_spent": int(credits_spent),
                })
                .execute()
            )
            rows = res.data or []
            return rows[0] if rows else None
        except Exception as e:
            logger.warning("insert_moment_unlock conflict/failure arc=%s: %s",
                           arc_id, e)
            return None

    def get_user_arc_ideal_notes(
        self, arc_id: Optional[str], user_id: Optional[str],
    ) -> Optional[str]:
        """The user's personal notebook copy of the ideal text (or None)."""
        if not arc_id or not user_id:
            return None
        try:
            res = (
                self.client.table("user_arc_ideal_notes")
                .select("text")
                .eq("arc_id", str(arc_id))
                .eq("user_id", str(user_id))
                .limit(1)
                .execute()
            )
            rows = res.data or []
            return rows[0].get("text") if rows else None
        except Exception as e:
            _e = str(e).lower()
            if "user_arc_ideal_notes" in _e and (
                "does not exist" in _e or "pgrst" in _e
            ):
                return None
            logger.warning("get_user_arc_ideal_notes failed arc=%s: %s",
                           arc_id, e)
            return None

    def upsert_user_arc_ideal_notes(
        self, arc_id: str, user_id: str, text: str,
    ) -> bool:
        """Save the user's personal notebook copy. NEVER touches the coach
        canonical (L1 — the deliverable stays the coach-approved select)."""
        if not arc_id or not user_id or not isinstance(text, str):
            return False
        try:
            self.client.table("user_arc_ideal_notes").upsert({
                "arc_id": str(arc_id),
                "user_id": str(user_id),
                "text": text,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }, on_conflict="arc_id,user_id").execute()
            return True
        except Exception as e:
            _e = str(e).lower()
            if "user_arc_ideal_notes" in _e and (
                "does not exist" in _e or "pgrst" in _e
            ):
                logger.warning(
                    "upsert_user_arc_ideal_notes: table missing (run "
                    "migrations/add_user_arc_ideal_notes.sql) arc=%s", arc_id,
                )
                return False
            logger.warning("upsert_user_arc_ideal_notes failed arc=%s: %s",
                           arc_id, e)
            return False

    def get_user_ideal_edit(
        self, arc_id: Optional[str], user_id: Optional[str],
    ) -> Optional[dict]:
        """The student's in-place SD edit of the ideal text (founder
        2026-07-17): {text, version, updated_at} or None. Sibling columns on
        user_arc_ideal_notes — never the legacy `text` notebook copy. Missing
        column (migration pending) / no row / error → None."""
        if not arc_id or not user_id:
            return None
        try:
            res = (
                self.client.table("user_arc_ideal_notes")
                .select("user_text, user_text_version, updated_at")
                .eq("arc_id", str(arc_id))
                .eq("user_id", str(user_id))
                .limit(1)
                .execute()
            )
            rows = res.data or []
            if not rows:
                return None
            r = rows[0]
            _text = r.get("user_text")
            if not isinstance(_text, str) or not _text.strip():
                return None
            return {
                "text": _text,
                "version": r.get("user_text_version"),
                "updated_at": r.get("updated_at"),
            }
        except Exception as e:
            _e = str(e).lower()
            if any(c in _e for c in (
                "user_text", "user_arc_ideal_notes",
            )) and ("does not exist" in _e or "pgrst" in _e):
                return None
            logger.warning("get_user_ideal_edit failed arc=%s: %s", arc_id, e)
            return None

    def upsert_user_ideal_edit(
        self, arc_id: str, user_id: str, text: str, version: Optional[int],
    ) -> bool:
        """Retired direct owner-lane writer.

        D21/D22 require the text, complete parts and immutable part revisions
        to commit through one CAS RPC. Returning false protects any stale
        application caller from recreating the former two-transaction path.
        """
        logger.warning("upsert_user_ideal_edit is retired; use CAS writer")
        return False

    def get_served_v3_rewrite(
        self, take_session_id: str, candidate_key: str,
    ) -> Optional[dict]:
        """The selected V3 rewrite this Take served under `candidate_key`:
        ``{source_ideal_part_id, generated_output}`` from the newest freeze,
        or None. Read-only (F1 Repair Plan Phase 4, P1-1): the accepted words
        come from what was served, never from the browser."""
        if not take_session_id or not candidate_key:
            return None
        try:
            memberships = (
                self.client.table("feedback_v3_memberships")
                .select("id, frozen_at")
                .eq("take_id", str(take_session_id))
                .order("frozen_at", desc=True)
                .execute().data or [])
            for membership in memberships:
                items = (
                    self.client.table("feedback_v3_membership_items")
                    .select("candidate_id, source_ideal_part_id")
                    .eq("membership_id", str(membership.get("id")))
                    .eq("candidate_key", str(candidate_key))
                    .eq("feedback_family", "rewrite_clarity")
                    .eq("selected", True)
                    .limit(1).execute().data or [])
                if not items:
                    continue
                candidates = (
                    self.client.table("feedback_candidates")
                    .select("generated_output")
                    .eq("id", str(items[0].get("candidate_id")))
                    .limit(1).execute().data or [])
                if not candidates:
                    return None
                return {
                    "source_ideal_part_id": items[0].get("source_ideal_part_id"),
                    "generated_output": candidates[0].get("generated_output") or {},
                }
            return None
        except Exception as e:
            logger.warning("served V3 rewrite unreadable take=%s: %s",
                           take_session_id, e, exc_info=True)
            return None

    def list_rewrite_declines(
        self, arc_id: str, owner_user_id: str,
    ) -> Optional[list]:
        """The owner's "Keep my words" on rewrites in this document
        (`rewrite_clarity` / `keep_wording`; N48.2, Q3 A), oldest first:
        take_session_id, feedback_id, created_at. None when unreadable, so
        the caller can tell "no decline" from "could not look"."""
        if not arc_id or not owner_user_id:
            return []
        try:
            return list(
                self.client.table("take_feedback_self_report")
                .select("take_session_id,feedback_id,created_at")
                .eq("arc_id", str(arc_id))
                .eq("owner_user_id", str(owner_user_id))
                .eq("feedback_family", "rewrite_clarity")
                .eq("response", "keep_wording")
                .order("created_at")
                .execute().data or [])
        except Exception as e:
            logger.warning("rewrite declines unreadable arc=%s: %s",
                           arc_id, e, exc_info=True)
            return None

    def read_declined_v3_rewrite_rows(
        self, take_session_ids: list[str], candidate_keys: list[str],
    ) -> Optional[dict]:
        """What the declined rewrites were, in four batch reads whatever
        their number (N48.2, Q3 A): the V3 freezes of these Takes, their
        selected rewrite items under these keys, those candidates' words,
        and the document each freeze served (its Paragraphs' words).
        ``{memberships, items, candidates, snapshots}``, or None when
        unreadable. The matching is ``services.rewrite_declines``'."""
        takes = sorted({str(t) for t in take_session_ids if t})
        keys = sorted({str(k) for k in candidate_keys if k})
        empty: dict = {"memberships": [], "items": [], "candidates": [],
                       "snapshots": []}
        if not takes or not keys:
            return empty
        try:
            memberships = list(
                self.client.table("feedback_v3_memberships")
                .select("id,take_id,frozen_at,document_snapshot_id")
                .in_("take_id", takes).execute().data or [])
            if not memberships:
                return empty
            items = list(
                self.client.table("feedback_v3_membership_items")
                .select("membership_id,candidate_key,candidate_id,"
                        "source_ideal_part_id")
                .in_("membership_id", [str(m.get("id")) for m in memberships])
                .in_("candidate_key", keys)
                .eq("feedback_family", "rewrite_clarity")
                .eq("selected", True).execute().data or [])
            if not items:
                return {**empty, "memberships": memberships}
            candidates = list(
                self.client.table("feedback_candidates")
                .select("id,generated_output")
                .in_("id", sorted({str(i.get("candidate_id")) for i in items}))
                .execute().data or [])
            served = {str(i.get("membership_id")) for i in items}
            snapshots = list(
                self.client.table("ideal_text_document_snapshots")
                .select("id,payload")
                .in_("id", sorted({
                    str(m.get("document_snapshot_id")) for m in memberships
                    if str(m.get("id")) in served}))
                .execute().data or [])
            return {"memberships": memberships, "items": items,
                    "candidates": candidates, "snapshots": snapshots}
        except Exception as e:
            logger.warning("declined V3 rewrites unreadable takes=%d: %s",
                           len(takes), e, exc_info=True)
            return None

    def compare_and_set_user_ideal_edit(
        self, *, owner_user_id: str, arc_id: str,
        source_document_version: int,
        expected_user_text_revision: Optional[int],
        expected_user_text_sha256: Optional[str], desired_user_text: str,
        desired_parts_lineage: Any, idempotency_key: Optional[str],
    ) -> Optional[dict]:
        """Atomically persist the ordinary owner edit and complete part graph."""
        result = self.client.rpc(
            "compare_and_set_user_ideal_edit_v1",
            {
                "p_owner_user_id": owner_user_id,
                "p_arc_id": arc_id,
                "p_source_document_version": source_document_version,
                "p_expected_user_text_revision": expected_user_text_revision,
                "p_expected_user_text_sha256": expected_user_text_sha256,
                "p_desired_user_text": desired_user_text,
                "p_desired_parts_lineage": desired_parts_lineage,
                "p_idempotency_key": idempotency_key,
            },
        ).execute()
        data = getattr(result, "data", result)
        if not isinstance(data, dict):
            raise TypeError("compare_and_set_user_ideal_edit_v1 returned non-object")
        return data

    def accept_rewrite_into_part(
        self, *, owner_user_id: str, arc_id: str, source_document_version: int,
        part_id: str, desired_user_text: str, desired_parts_lineage: Any,
    ) -> Optional[dict]:
        """The owner edit for an accepted rewrite (0418): the same writer,
        allowed to change the TEXT of the one protected Paragraph it names."""
        result = self.client.rpc(
            "accept_rewrite_into_part_v1",
            {
                "p_owner_user_id": owner_user_id,
                "p_arc_id": arc_id,
                "p_source_document_version": source_document_version,
                "p_part_id": part_id,
                "p_desired_user_text": desired_user_text,
                "p_desired_parts_lineage": desired_parts_lineage,
            },
        ).execute()
        data = getattr(result, "data", result)
        if not isinstance(data, dict):
            raise TypeError("accept_rewrite_into_part_v1 returned non-object")
        return data

    # ── ideal_text_part — the document as an ordered list with stable ids ──
    # SPEC-parts-locking-and-layers §3.1, Step 0. Identity only; PR 3 adds the
    # lock. Both of these are best-effort in the same sense as the edit lane
    # above: a missing table (migration 0255 not applied) degrades to "this
    # document has no parts", which is exactly the pre-migration behaviour.

    def get_ideal_text_parts(
        self, arc_id: Optional[str], user_id: Optional[str],
        *, with_lock: bool = False,
    ) -> list:
        """One document's parts, in `ord` order. [] on anything missing.

        Keyed (arc_id, user_id) to match `user_arc_ideal_notes` — the served
        document is derived per request, so arc_id alone does not name one.

        `with_lock` adds `locked_at` (migration 0256). OPT-IN rather than
        always selected: the student payload must never carry it (AC-9 is not
        the issue — a lock is not a score — but the parts block is a wire
        contract, and a field nobody asked for is a field someone renders).
        The layer filter asks for it; the serve path does not.
        """
        if not arc_id or not user_id:
            return []
        try:
            res = self._execute_with_retry(
                lambda: (
                    self.client.table("ideal_text_part")
                    .select("id, ord, text, locked_at, iteration, root_phrase, "
                            "root_start, root_end, root_selected_at"
                            if with_lock else "id, ord, text")
                    .eq("arc_id", str(arc_id))
                    .eq("user_id", str(user_id))
                    .order("ord")
                ),
                label="get_ideal_text_parts",
            )
            return res.data or []
        except Exception as e:
            _e = str(e).lower()
            if ("ideal_text_part" in _e or "locked_at" in _e) and (
                    "does not exist" in _e or "pgrst" in _e):
                # Two different pre-migration states, one degrade. Missing
                # TABLE (0255) → no identity; missing COLUMN (0256) → identity
                # without locks. Both mean "no locks to enforce", and the layer
                # filter treats an empty list as "everything is allowed" —
                # which is the safe direction, because R1 SUPPRESSES
                # interventions and a bad read must never silence the surface.
                logger.warning(
                    "get_ideal_text_parts: table/column missing (run "
                    "migrations/add_ideal_text_parts.sql, "
                    "add_ideal_text_part_lock.sql) arc=%s", arc_id)
                return []
            logger.warning("get_ideal_text_parts failed arc=%s: %s", arc_id, e)
            return []

    def set_ideal_text_part_lock(
        self, arc_id: str, user_id: str, part_id: str, locked: bool,
        *, revision_action: Optional[str] = None,
    ) -> bool:
        """Lock or unlock ONE part (SPEC §4, R5). True on success.

        Scoped to (arc_id, user_id) as well as the part id, so a caller cannot
        reach another document's part by guessing an id — the id alone is the
        primary key, and a route that trusted it would be an IDOR.

        UNLOCK CLEARS THE COLUMN rather than writing a history row (R5). The
        lock is live UI state, not an audit trail; what §6 needs recorded is
        the DECISION on each intervention, which lives on its own row and is
        never rewritten by a lock or an unlock.
        """
        if not arc_id or not user_id or not part_id:
            return False
        try:
            update: dict = {
                "locked_at": (datetime.now(timezone.utc).isoformat()
                              if locked else None),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            if not locked:
                update.update({
                    "root_phrase": None,
                    "root_start": None,
                    "root_end": None,
                    "root_selected_at": None,
                })
            part_text = ""
            # Every immutable revision must carry the exact paragraph body,
            # including unlock / keep-evolving decisions. Read it once for
            # both branches; an empty audit body would make the version graph
            # impossible to reconstruct.
            try:
                cur = (
                    self.client.table("ideal_text_part")
                    .select("iteration,text")
                    .eq("id", str(part_id))
                    .eq("arc_id", str(arc_id))
                    .eq("user_id", str(user_id))
                    .limit(1)
                    .execute()
                )
                row0 = (cur.data or [{}])[0] or {}
                part_text = str(row0.get("text") or "")
            except Exception:
                row0 = {}
            if locked:
                # The MATURITY counter (slice 2, founder 2026-08-11): +1 on
                # every lock-in, never on unlock. Read-then-write — this is
                # a single-student tap path, not a contended counter — and
                # best-effort: pre-migration the lock still lands, the
                # counter simply holds at nothing.
                try:
                    update["iteration"] = int(row0.get("iteration") or 0) + 1
                except Exception:
                    pass
            def _do(payload: dict):
                return (
                    self.client.table("ideal_text_part")
                    .update(payload)
                    .eq("id", str(part_id))
                    .eq("arc_id", str(arc_id))
                    .eq("user_id", str(user_id))
                    .execute()
                )
            try:
                res = _do(update)
            except Exception as inner:
                # Pre-migration column miss: the LOCK must land even when
                # the counter cannot — retry without it, never fail the tap
                # on a column that is not there yet.
                if "iteration" in update and (
                        "iteration" in str(inner).lower()
                        or "pgrst204" in str(inner).lower()):
                    update.pop("iteration", None)
                    res = _do(update)
                else:
                    raise
            # An update that matched NOTHING is not a success. Postgres has no
            # complaint to make about it, so without this a lock on a part that
            # does not belong to this document returns 200 and does nothing —
            # and the FE would draw a locked paragraph that is not locked.
            saved = bool(res.data)
            if saved:
                if not part_text:
                    part_text = str((res.data[0] or {}).get("text") or "") \
                        if res.data else ""
                self.append_ideal_text_part_revision(
                    arc_id=arc_id, user_id=user_id, part_id=part_id,
                    action=(revision_action
                            if revision_action in ("lock", "unlock",
                                                   "keep_evolving")
                            else "lock" if locked else "unlock"),
                    text=part_text,
                )
            return saved
        except Exception as e:
            _e = str(e).lower()
            if ("ideal_text_part" in _e or "locked_at" in _e) and (
                    "does not exist" in _e or "pgrst" in _e):
                logger.warning(
                    "set_ideal_text_part_lock: table/column missing (run "
                    "migrations/add_ideal_text_part_lock.sql) arc=%s", arc_id)
                return False
            logger.warning("set_ideal_text_part_lock failed arc=%s: %s",
                           arc_id, e)
            return False

    def set_ideal_text_part_root(
        self, *, arc_id: str, user_id: str, part_id: str,
        phrase: Optional[str], start: Optional[int], end: Optional[int],
    ) -> bool:
        """Set/skip the exact orange root on one part, locked or not."""
        if not arc_id or not user_id or not part_id:
            return False
        try:
            rows = (self.client.table("ideal_text_part")
                    .select("id,text,locked_at")
                    .eq("id", str(part_id))
                    .eq("arc_id", str(arc_id))
                    .eq("user_id", str(user_id))
                    .limit(1).execute().data) or []
            # THE LOCK IS NOT A PRECONDITION FOR THE PHRASE (founder
            # 2026-09-24). This required `locked_at`, and the route above it
            # refused an unlocked part with 409 PART_NOT_LOCKED, because the
            # phrase was once stored BY the lock. The ladder stopped working
            # that way in #442: the emphasis step saves on the step that chose
            # the words, and on "No", "Not sure" and "Audio unclear" the Lock
            # step is not built at all — "Just save the rooting phrases orange,
            # but do not let them lock that text." A precondition the speaker
            # cannot reach is not a guard but a dead end, and until this change
            # EVERY first-pass emphasis save answered 409 and showed an error.
            #
            # Nothing downstream loosens. The `ideal_text_part_root_span` CHECK
            # never tied a root to `locked_at`, so no migration is involved,
            # and `project_recording_roots` still yields locked roots only — an
            # unlocked phrase is recorded but not yet eligible, which is the
            # versioning the founder described: "if you record and see the
            # rooting phrases and say things before not locking it, it will be
            # gone, cause the new text will replace it."
            if not rows:
                return False
            text = str(rows[0].get("text") or "")
            now = datetime.now(timezone.utc).isoformat()
            payload = {
                "root_phrase": phrase,
                "root_start": start,
                "root_end": end,
                "root_selected_at": now if phrase is not None else None,
                "updated_at": now,
            }
            result = (self.client.table("ideal_text_part")
                      .update(payload)
                      .eq("id", str(part_id))
                      .eq("arc_id", str(arc_id))
                      .eq("user_id", str(user_id))
                      .execute())
            if not result.data:
                return False
            self.append_ideal_text_part_revision(
                arc_id=arc_id, user_id=user_id, part_id=part_id,
                action="root_set" if phrase is not None else "root_skipped",
                text=text, root_phrase=phrase,
            )
            return True
        except Exception as e:
            logger.warning("set ideal text part root failed: %s", e)
            return False

    # ── Helper words belong to the Slide (contract 13-14, Q12/Q14) ─────────
    # services/slide_helper_words.py owns the rule; these two are plain I/O.

    def get_slide_helper_words(self, arc_id: str, user_id: str) -> list:
        """Every Slide's helper-word rows for one document, [] on failure."""
        if not arc_id or not user_id:
            return []
        try:
            return (self.client.table("ideal_text_slide_helper_words")
                    .select("slide_index,ord,phrase,take_session_id,"
                            "source_part_id,locked_at,selected_at")
                    .eq("arc_id", str(arc_id))
                    .eq("user_id", str(user_id))
                    .order("slide_index").order("ord")
                    .execute().data) or []
        except Exception as e:
            logger.warning("get slide helper words failed arc=%s: %s",
                           arc_id, e)
            return []

    def _log_slide_helper_words(self, arc_id: str, user_id: str,
                                slide_index: int, rows: list) -> None:
        """Append the Slide's LOCKED set when it differs from the last one
        logged — the "which helper words were locked when" half of the
        Paragraph history. Best-effort: never fails the write it follows."""
        phrases = [str(r["phrase"]) for r in sorted(
            rows or [], key=lambda r: int(r.get("ord") or 0))
            if r.get("locked_at") and r.get("phrase")]
        try:
            last = (self.client.table("ideal_text_slide_helper_words_log")
                    .select("phrases")
                    .eq("arc_id", str(arc_id))
                    .eq("user_id", str(user_id))
                    .eq("slide_index", slide_index)
                    .order("id", desc=True).limit(1)
                    .execute().data) or []
            if last and last[0].get("phrases") == phrases:
                return
            if not last and not phrases:
                return
            self.client.table("ideal_text_slide_helper_words_log").insert({
                "arc_id": str(arc_id),
                "user_id": str(user_id),
                "slide_index": slide_index,
                "phrases": phrases,
            }).execute()
        except Exception as e:
            logger.warning("slide helper words log failed arc=%s slide=%s: "
                           "%s", arc_id, slide_index, e)

    def list_slide_helper_words_log(self, arc_id: str, user_id: str,
                                    slide_index: int) -> list:
        """One Slide's locked helper-word sets over time, oldest first."""
        try:
            return (self.client.table("ideal_text_slide_helper_words_log")
                    .select("phrases,created_at")
                    .eq("arc_id", str(arc_id))
                    .eq("user_id", str(user_id))
                    .eq("slide_index", slide_index)
                    .order("id")
                    .execute().data) or []
        except Exception as e:
            logger.warning("list slide helper words log failed arc=%s: %s",
                           arc_id, e)
            return []

    def replace_slide_helper_words(self, arc_id: str, user_id: str,
                                   slide_index: int, rows: list) -> bool:
        """Replace ONE Slide's rows wholesale (delete, then insert).

        Wholesale for the same reason as `replace_ideal_text_parts`: a pick
        or a lock can renumber every row of the Slide, and per-row upserts
        would transiently collide on the (slide, ord) slot."""
        if not arc_id or not user_id or not isinstance(slide_index, int):
            return False
        try:
            (self.client.table("ideal_text_slide_helper_words")
                .delete()
                .eq("arc_id", str(arc_id))
                .eq("user_id", str(user_id))
                .eq("slide_index", slide_index)
                .execute())
            if rows:
                self.client.table("ideal_text_slide_helper_words").insert([{
                    "arc_id": str(arc_id),
                    "user_id": str(user_id),
                    "slide_index": slide_index,
                    "ord": int(r["ord"]),
                    "phrase": str(r["phrase"]),
                    "take_session_id": r.get("take_session_id") or None,
                    "source_part_id": r.get("source_part_id") or None,
                    "locked_at": r.get("locked_at"),
                    "selected_at": r.get("selected_at"),
                } for r in rows]).execute()
            self._log_slide_helper_words(arc_id, user_id, slide_index, rows)
            return True
        except Exception as e:
            logger.warning("replace slide helper words failed arc=%s "
                           "slide=%s: %s", arc_id, slide_index, e)
            return False

    def append_ideal_text_part_revision(
        self, *, arc_id: str, user_id: str, part_id: str, action: str,
        text: str, root_phrase: Optional[str] = None,
        take_session_id: Optional[str] = None,
        review_version: Optional[int] = None,
    ) -> bool:
        try:
            self.client.table("ideal_text_part_revision").insert({
                "arc_id": str(arc_id),
                "user_id": str(user_id),
                "part_id": str(part_id),
                "action": str(action),
                "text": str(text or ""),
                "root_phrase": root_phrase,
                "take_session_id": take_session_id,
                "review_version": review_version,
            }).execute()
            return True
        except Exception as e:
            # Audit persistence is important but cannot make a successful
            # live lock appear failed after the state already landed.
            logger.warning("part revision append failed: %s", e)
            return False

    def get_latest_ideal_text_part_revision(
        self, *, arc_id: str, user_id: str, part_id: str,
    ) -> Optional[dict]:
        """Latest immutable compatibility revision for dual-write identity."""
        if not all((arc_id, user_id, part_id)):
            return None
        try:
            rows = (self.client.table("ideal_text_part_revision")
                    .select("id,action,created_at")
                    .eq("arc_id", str(arc_id))
                    .eq("user_id", str(user_id))
                    .eq("part_id", str(part_id))
                    .order("id", desc=True)
                    .limit(1).execute().data) or []
            return rows[0] if rows and isinstance(rows[0], dict) else None
        except Exception as revision_error:
            logger.warning(
                "latest part revision read failed arc=%s part=%s: %s",
                arc_id, part_id, revision_error,
            )
            return None

    def list_accepted_rewrite_revisions(
        self, arc_id: str, user_id: str, part_id: str,
    ) -> list:
        """One Paragraph's accepted-rewrite revisions (0421), oldest first:
        ``{text, created_at}``. [] on anything missing -- History then
        simply shows its Take rows."""
        if not all((arc_id, user_id, part_id)):
            return []
        try:
            return (self.client.table("ideal_text_part_revision")
                    .select("text,created_at")
                    .eq("arc_id", str(arc_id))
                    .eq("user_id", str(user_id))
                    .eq("part_id", str(part_id))
                    .eq("provenance", "accepted_rewrite")
                    .order("id")
                    .execute().data) or []
        except Exception as e:
            logger.warning("list_accepted_rewrite_revisions failed arc=%s "
                           "part=%s: %s", arc_id, part_id, e, exc_info=True)
            return []

    def replace_ideal_text_parts(
        self, arc_id: str, user_id: str, parts: list,
        revision_action: Optional[str] = None,
        revision_take_session_id: Optional[str] = None,
        revision_review_version: Optional[int] = None,
    ) -> bool:
        """Replace a document's parts wholesale. True on success.

        WHOLESALE, NOT PER-ROW UPSERT, and the unique index is why. A reorder
        changes many rows' `ord` at once; upserting them one at a time walks
        through states where two rows claim one slot, and
        `uq_ideal_text_part_slot` would reject whichever came second — leaving
        the document half-reordered. Delete-then-insert has no intermediate
        state to violate.

        The delete is the RISK in that trade: if the insert fails, the parts
        are gone. That is survivable and deliberately so — parts are pure
        identity, the canonical `text` is written separately and is untouched,
        and a document with no parts is a valid state the client re-mints from.
        Losing identity costs the ids; losing the words would cost the words.
        """
        if not arc_id or not user_id or not isinstance(parts, list):
            return False
        try:
            # ITERATION SURVIVES THE REPLACE (bug, found 2026-08-12).
            #
            # The insert below names the columns it writes, so EVERY column it
            # omits silently returns to its DEFAULT — and `iteration` (0265)
            # defaults to 0. Lock a chunk (iteration → 1), record another take,
            # open the readout: `compose_locked` reports `changed`, the parts
            # are replaced, and the founder's "Locked in · N iterations" kicker
            # is back to zero with nothing in the logs to say so.
            #
            # All three call sites carefully read `locked_at` back and thread
            # it through, and not one of them mentions `iteration` — which is
            # the shape of the hazard: preserving a column is opt-in and
            # forgetting is the default. So the preservation lives HERE, once,
            # where it cannot be forgotten by a fourth caller.
            #
            # Read before the delete: afterwards there is nothing to read.
            prev_iter: dict = {}
            prev_meta: dict = {}
            try:
                _res = (self.client.table("ideal_text_part")
                        .select("id, text, locked_at, iteration, root_phrase, "
                                "root_start, root_end, root_selected_at")
                        .eq("arc_id", str(arc_id))
                        .eq("user_id", str(user_id))
                        .execute())
                prev_iter = {str(r.get("id")): int(r.get("iteration") or 0)
                             for r in (_res.data or []) if isinstance(r, dict)}
                prev_meta = {str(r.get("id")): r for r in (_res.data or [])
                             if isinstance(r, dict)}
            except Exception as _it_err:
                # A pre-0265 database has no such column. Degrade to "no
                # maturity counters", never to a failed document write.
                logger.warning(
                    "replace_ideal_text_parts: iteration unreadable arc=%s: "
                    "%s (counters reset)", arc_id, _it_err)
            (self.client.table("ideal_text_part")
                .delete()
                .eq("arc_id", str(arc_id))
                .eq("user_id", str(user_id))
                .execute())
            if not parts:
                return True     # the student cleared the document
            self.client.table("ideal_text_part").insert([
                {
                    "id": str(p["id"]),
                    "arc_id": str(arc_id),
                    "user_id": str(user_id),
                    "ord": int(p["ord"]),
                    "text": str(p["text"]),
                    # The lock rides the replace so explicit paragraph commits
                    # survive document edits. Absent/None = open; a caller that
                    # wants to preserve an existing lock passes the original
                    # timestamp through (never re-stamped — a decision made
                    # before a lock and one after mean different things, §6).
                    "locked_at": p.get("locked_at"),
                    # An EXPLICIT caller value wins (a fresh part carries
                    # none); otherwise the stored counter is carried across.
                    "iteration": (p.get("iteration")
                                  if isinstance(p.get("iteration"), int)
                                  else prev_iter.get(str(p["id"]), 0)),
                    # THE HELPER WORDS ARE THEIR OWN TEXT (contract 14,
                    # founder 2026-09-25). They ride with the Paragraph id
                    # through any change to its words and persist until the
                    # user picks new ones. Only the span — a render hint — is
                    # recomputed against the new words; see `_carried_root`.
                    **_carried_root(prev_meta.get(str(p["id"])),
                                    str(p["text"])),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
                for p in parts
            ]).execute()
            if revision_action:
                for p in parts:
                    _previous = prev_meta.get(str(p["id"])) or {}
                    _text_changed = _previous.get("text") != str(p["text"])
                    _lock_changed = bool(_previous.get("locked_at")) != bool(
                        p.get("locked_at"))
                    if not _previous or _text_changed or _lock_changed:
                        self.append_ideal_text_part_revision(
                            arc_id=arc_id,
                            user_id=user_id,
                            part_id=str(p["id"]),
                            action=revision_action,
                            text=str(p["text"]),
                            root_phrase=_previous.get("root_phrase"),
                            take_session_id=revision_take_session_id,
                            review_version=revision_review_version,
                        )
            return True
        except Exception as e:
            _e = str(e).lower()
            if "ideal_text_part" in _e and (
                    "does not exist" in _e or "pgrst" in _e):
                logger.warning(
                    "replace_ideal_text_parts: table missing (run "
                    "migrations/add_ideal_text_parts.sql) arc=%s", arc_id)
                return False
            logger.warning("replace_ideal_text_parts failed arc=%s: %s",
                           arc_id, e)
            return False

    # ── the acoustic KPI (founder 2026-08-12) ──────────────────────────────
    # The speaker's own baseline, and the per-part moving average that is
    # measured against it. Best-effort in the same sense as everything above:
    # a missing table (migrations 0268/0269 not applied) degrades to "no
    # baseline / no history", which is the cold-start state the readers are
    # already written for and is exactly the pre-migration behaviour.

    def insert_user_acoustic_baseline(
        self, user_id: str, features: dict, *,
        n_sessions: int = 0, n_samples: int = 0,
        detector_version: str = "",
    ) -> Optional[str]:
        """Append a baseline snapshot; return its id, or None.

        APPEND-ONLY (founder immutability rule). The insert lands FIRST and
        the previous row is superseded after — interrupted between the two
        leaves two current rows, and the reader takes the newest, which is
        degraded but correct. The reverse order leaves a window with NO
        current baseline, which reads as cold start and would drop the user
        out of single-point focus for no reason at all.

        The supersede is best-effort ON TOP of a successful insert: failing to
        mark the old row must not lose the new one.
        """
        if not user_id or not isinstance(features, dict) or not features:
            return None
        try:
            res = (self.client.table("user_acoustic_baseline")
                   .insert({
                       "user_id": str(user_id),
                       "features": features,
                       "n_sessions": int(n_sessions),
                       "n_samples": int(n_samples),
                       "detector_version": str(detector_version),
                   })
                   .execute())
            rows = res.data or []
            new_id = str(rows[0].get("id")) if rows else None
        except Exception as e:
            _e = str(e).lower()
            if "user_acoustic_baseline" in _e and (
                    "does not exist" in _e or "pgrst" in _e):
                logger.warning(
                    "insert_user_acoustic_baseline: table missing (run "
                    "migrations/add_user_acoustic_baseline.sql) user=%s",
                    user_id)
                return None
            logger.warning("insert_user_acoustic_baseline failed user=%s: %s",
                           user_id, e)
            return None
        if not new_id:
            return None
        try:
            (self.client.table("user_acoustic_baseline")
                .update({"superseded_at": datetime.now(timezone.utc)
                         .isoformat()})
                .eq("user_id", str(user_id))
                .eq("detector_version", str(detector_version))
                .is_("superseded_at", "null")
                .neq("id", new_id)
                .execute())
        except Exception as e:
            logger.warning(
                "insert_user_acoustic_baseline: supersede failed user=%s: %s "
                "(new row %s stands)", user_id, e, new_id)
        return new_id

    def get_current_user_acoustic_baseline(
        self, user_id: str, *, detector_version: str = "",
    ) -> Optional[dict]:
        """This user's current baseline row for one regime, or None.

        Ordered newest-first and limited to one rather than assuming a single
        current row: the append-then-supersede order above can legitimately
        leave two, and "the newest wins" is the rule that makes that state
        correct instead of ambiguous.
        """
        if not user_id:
            return None
        try:
            res = (self.client.table("user_acoustic_baseline")
                   .select("id, features, n_sessions, n_samples, computed_at")
                   .eq("user_id", str(user_id))
                   .eq("detector_version", str(detector_version))
                   .is_("superseded_at", "null")
                   .order("computed_at", desc=True)
                   .limit(1)
                   .execute())
            rows = res.data or []
            return rows[0] if rows else None
        except Exception as e:
            _e = str(e).lower()
            if "user_acoustic_baseline" in _e and (
                    "does not exist" in _e or "pgrst" in _e):
                logger.warning(
                    "get_current_user_acoustic_baseline: table missing (run "
                    "migrations/add_user_acoustic_baseline.sql) user=%s",
                    user_id)
                return None
            logger.warning(
                "get_current_user_acoustic_baseline failed user=%s: %s",
                user_id, e)
            return None

    def get_arc_part_acoustics(
        self, arc_id: Optional[str], user_id: Optional[str],
    ) -> list:
        """One document's per-part acoustic rows. [] on anything missing.

        [] is the cold-start answer and the failure answer alike, and both are
        safe in the same direction: `focus_part_id([])` is None, and None
        means "no focus established — behave exactly as before". A bad read
        can therefore never SUPPRESS feedback, only decline to concentrate it.
        """
        if not arc_id or not user_id:
            return []
        try:
            res = (self.client.table("arc_part_acoustics")
                   .select("part_id, ema_z, n_takes, came_onboard_at, "
                           "baseline_id, last_take_session_id")
                   .eq("arc_id", str(arc_id))
                   .eq("user_id", str(user_id))
                   .order("ema_z")
                   .execute())
            return res.data or []
        except Exception as e:
            _e = str(e).lower()
            if "arc_part_acoustics" in _e and (
                    "does not exist" in _e or "pgrst" in _e):
                logger.warning(
                    "get_arc_part_acoustics: table missing (run "
                    "migrations/add_arc_part_acoustics.sql) arc=%s", arc_id)
                return []
            logger.warning("get_arc_part_acoustics failed arc=%s: %s",
                           arc_id, e)
            return []

    def upsert_arc_part_acoustics(self, rows: list) -> bool:
        """Write per-part acoustic rows. True on success.

        Per-row upsert on the PRIMARY KEY, NOT the wholesale delete-then-
        insert `replace_ideal_text_parts` uses. The two are different problems:
        parts are replaced together because a reorder moves many `ord` values
        at once and the slot index cannot survive the intermediate state.
        These rows have no ordering constraint between them, and a delete here
        would throw away the take history of every part the current take did
        not happen to cover — which is the exact hazard that put this table
        beside `ideal_text_part` instead of on it.

        `came_onboard_at` is stamped only on the TRANSITION. An already-onboard
        row keeps its original timestamp: the ratchet records when a part came
        onboard, and re-stamping it every take would erase that.
        """
        if not rows:
            return False
        try:
            now = datetime.now(timezone.utc).isoformat()
            prev = {}
            first = rows[0] if isinstance(rows[0], dict) else {}
            if first.get("arc_id") and first.get("user_id"):
                prev = {
                    str(r.get("part_id")): r.get("came_onboard_at")
                    for r in (self.get_arc_part_acoustics(
                        first["arc_id"], first["user_id"]) or [])
                    if isinstance(r, dict) and r.get("came_onboard_at")
                }
            payload = []
            for r in rows:
                if not isinstance(r, dict) or not r.get("part_id"):
                    continue
                pid = str(r["part_id"])
                onboard_at = prev.get(pid)
                if not onboard_at and r.get("came_onboard"):
                    onboard_at = now
                payload.append({
                    "part_id": pid,
                    "arc_id": str(r.get("arc_id") or ""),
                    "user_id": str(r.get("user_id") or ""),
                    "ema_z": float(r.get("ema_z") or 0.0),
                    "n_takes": int(r.get("n_takes") or 0),
                    "last_take_session_id": r.get("last_take_session_id"),
                    "came_onboard_at": onboard_at,
                    "baseline_id": r.get("baseline_id"),
                    "detector_version": str(r.get("detector_version") or ""),
                    "updated_at": now,
                })
            if not payload:
                return False
            (self.client.table("arc_part_acoustics")
                .upsert(payload, on_conflict="part_id")
                .execute())
            return True
        except Exception as e:
            _e = str(e).lower()
            if "arc_part_acoustics" in _e and (
                    "does not exist" in _e or "pgrst" in _e):
                logger.warning(
                    "upsert_arc_part_acoustics: table missing (run "
                    "migrations/add_arc_part_acoustics.sql)")
                return False
            logger.warning("upsert_arc_part_acoustics failed: %s", e)
            return False

    # The star-suggestion kinds. MUST mirror the moment_suggestions kind
    # CHECK (alter_moment_suggestions_kind_delivery.sql) — the 2026-07-20
    # lesson: #221 widened the DB CHECK but not this guard, so 'delivery'
    # rows were rejected HERE and the feature ran silently inert in prod.
    # Pinned by test_delivery_stars.
    SUGGESTION_KINDS = ("emphasize", "replace", "structure", "delivery")

    def upsert_moment_suggestion(
        self, snippet_id: str, arc_id: str, kind: str,
        replacement_text: Optional[str], why: Optional[str],
        trigger: Optional[str], *, emphasis_quote: Optional[str] = None,
        cue_keys: Any = None,
    ) -> bool:
        """One star suggestion per snippet (founder 2026-07-18). Idempotent
        on snippet_id (a reassembly regenerates in place). Best-effort.

        ``emphasis_quote`` — the verbatim words an emphasize star should
        accent (founder 2026-08-15, migrations/add_moment_emphasis_quote
        .sql). Keyword-only and defaulted: the delivery / structural /
        congruence / swap writers store no accent target and say so by not
        passing one.

        ``cue_keys`` — WHAT THE VOICE DID on this moment, as keys from
        services.delivery_cues.CUE_KEYS (founder 2026-08-15). The evidence a
        praise line cites; never a number, never free text (AC-9). Stored as
        given and never merged with a prior row's list: cues are a reading of
        ONE take's audio, and a detector's output is versioned, not
        accumulated."""
        if not snippet_id or not arc_id \
                or kind not in self.SUGGESTION_KINDS:
            return False
        _cues = None
        if isinstance(cue_keys, (list, tuple)):
            _cues = [str(k) for k in cue_keys if isinstance(k, str) and k] \
                or None
        row = {
            "snippet_id": str(snippet_id),
            "arc_id": str(arc_id),
            "kind": kind,
            "replacement_text": replacement_text,
            "why": why,
            "trigger": trigger,
            "emphasis_quote": emphasis_quote,
            "cue_keys": _cues,
        }
        try:
            self.client.table("moment_suggestions").upsert(
                row, on_conflict="snippet_id").execute()
            return True
        except Exception as e:
            _e = str(e).lower()
            # THE COLUMN-AHEAD-OF-THE-MIGRATION RETRY. The migration ships in
            # the same PR and MIGRATE_ON_BOOT applies it before the app
            # starts, so this should never fire — but a new column in a
            # write that is the ONLY way a star is ever stored is exactly the
            # shape that takes a live lane dark, and the star is worth more
            # than its accent target.
            if "emphasis_quote" in _e or "cue_keys" in _e:
                logger.warning(
                    "upsert_moment_suggestion: accent columns missing (run "
                    "migrations/add_moment_emphasis_quote.sql and "
                    "add_moment_cue_keys.sql) — storing the star without its "
                    "accent target and cues")
                try:
                    row.pop("emphasis_quote", None)
                    row.pop("cue_keys", None)
                    self.client.table("moment_suggestions").upsert(
                        row, on_conflict="snippet_id").execute()
                    return True
                except Exception as e2:
                    logger.warning(
                        "upsert_moment_suggestion retry failed snip=%s: %s",
                        snippet_id, e2)
                    return False
            if "moment_suggestions" in _e and (
                "does not exist" in _e or "pgrst" in _e
            ):
                logger.warning(
                    "upsert_moment_suggestion: table missing (run "
                    "migrations/add_moment_suggestions.sql)")
                return False
            logger.warning("upsert_moment_suggestion failed snip=%s: %s",
                           snippet_id, e)
            return False

    def get_moment_suggestions_by_arc(self, arc_id: Optional[str], *,
                                      strict: bool = False) -> dict:
        """{snippet_id: suggestion row} for one presentation. Best-effort:
        {} on missing table / error (no stars, never a break).

        ``strict=True`` RE-RAISES on a real read failure instead of returning
        {} (a genuinely missing table still returns {} — that is an empty
        ledger, not a broken one). Exists for the ONE caller that must not
        confuse "no suggestions" with "could not read": the swap lane's
        collision check writes through a snippet-keyed upsert, so treating a
        failed read as empty would let a praise offer REPLACE a correction
        the student was about to see (audit finding: the check failed open
        and its docstring claimed the opposite).

        FOLD (founder 2026-07-28, coach star-text corrections): the returned
        ``why`` / ``replacement_text`` are the coach's final WHEN one exists,
        else the machine draft — done HERE, at the one reader, so every
        consumer (the ideal-text serve, the decision ledger's phrase keying,
        the snapshot, tracked changes) shows the corrected wording without
        any of them knowing the twin columns exist. The raw drafts ride along
        as ``why_draft`` / ``replacement_text_draft`` for the two consumers
        that need the pair (the coach stars review + the corpus emission).
        Pre-migration rows simply have no *_final keys → the fold no-ops."""
        if not arc_id:
            return {}
        try:
            res = (
                self.client.table("moment_suggestions")
                .select("*")
                .eq("arc_id", str(arc_id))
                .execute()
            )
            out: dict = {}
            for r in (res.data or []):
                if not r.get("snippet_id"):
                    continue
                r = dict(r)
                r["why_draft"] = r.get("why")
                r["replacement_text_draft"] = r.get("replacement_text")
                if r.get("why_final"):
                    r["why"] = r["why_final"]
                if r.get("replacement_text_final"):
                    r["replacement_text"] = r["replacement_text_final"]
                out[str(r["snippet_id"])] = r
            return out
        except Exception as e:
            _e = str(e).lower()
            if "moment_suggestions" in _e and (
                "does not exist" in _e or "pgrst" in _e
            ):
                return {}
            logger.warning("get_moment_suggestions_by_arc failed arc=%s: %s",
                           arc_id, e)
            if strict:
                raise
            return {}

    # Sentinel for set_moment_suggestion_final: "this field was not sent —
    # leave the stored value alone". Distinct from None, which CLEARS.
    _FINAL_UNSET = object()

    def set_moment_suggestion_final(
        self, snippet_id: str, *, why_final: Any = _FINAL_UNSET,
        replacement_text_final: Any = _FINAL_UNSET,
        edited_by: Optional[str] = None,
    ) -> bool:
        """The coach's corrected star wording (founder 2026-07-28) — plain
        update, re-editable until they're done (mirrors
        set_charisma_snippet_say_it_stronger_final). The machine's draft
        columns are NEVER touched: the (draft, final) pair is the correction
        corpus.

        Three values per field: a string SETS the correction, an explicit
        None CLEARS it (revert to the draft — the full-state star-text PUT),
        and omitting the argument PRESERVES whatever is stored (the §4b
        verdict piggyback, whose wire only carries fields the coach actually
        changed). Both omitted → no-op, True. Best-effort,
        missing-column-safe; never raises."""
        if not snippet_id:
            return False
        payload: dict = {}
        if why_final is not self._FINAL_UNSET:
            payload["why_final"] = why_final
        if replacement_text_final is not self._FINAL_UNSET:
            payload["replacement_text_final"] = replacement_text_final
        if not payload:
            return True
        payload["text_final_updated_at"] = \
            datetime.now(timezone.utc).isoformat()
        if edited_by:
            payload["text_final_by"] = str(edited_by)
        try:
            (self.client.table("moment_suggestions")
                 .update(payload)
                 .eq("snippet_id", str(snippet_id)).execute())
            return True
        except Exception as e:
            _e = str(e).lower()
            if ("why_final" in _e or "replacement_text_final" in _e
                    or "text_final" in _e):
                logger.warning(
                    "set_moment_suggestion_final: columns missing (run "
                    "migrations/add_moment_suggestion_final.sql)",
                )
                return False
            logger.warning("set_moment_suggestion_final failed snip=%s: %s",
                           snippet_id, e)
            return False

    # ── ideal-text decision ledger (founder 2026-07-20) ──────────────
    # Phrase-keyed memory of approved/dismissed suggestions; see
    # services/ideal_decision_ledger.py + add_ideal_decision_ledger.sql.
    # All best-effort with the table-missing degradation (LIVE LOOP).

    def upsert_ideal_decision(self, *, arc_id: str, kind: str,
                              target_phrase: str,
                              display_phrase: Optional[str],
                              replacement_text: Optional[str],
                              decision: str, source: Optional[str],
                              snippet_id: Optional[str],
                              version: Optional[int],
                              slide_index: Optional[int] = None,
                              lane_class: Optional[str] = None) -> bool:
        """One decision per (arc, kind, phrase) — last write wins (an
        applied→dismissed flip updates in place). Best-effort.

        ``slide_index``/``lane_class`` are §12.3's intent key (cross-take
        location + suggestion class). Pre-migration the columns are
        missing: the payload retries WITHOUT them rather than dropping the
        decision — the phrase key must never be lost to the intent key."""
        if not arc_id or not target_phrase \
                or kind not in ("polish", "replace", "emphasize") \
                or decision not in ("approved", "dismissed"):
            return False
        payload = {
            "arc_id": str(arc_id),
            "kind": kind,
            "target_phrase": target_phrase,
            "display_phrase": display_phrase,
            "replacement_text": replacement_text,
            "decision": decision,
            "source": source,
            "snippet_id": snippet_id,
            "version": version,
            "slide_index": slide_index,
            "lane_class": lane_class,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        for _attempt in (1, 2):
            try:
                self.client.table("ideal_decision_ledger").upsert(
                    payload, on_conflict="arc_id,kind,target_phrase"
                ).execute()
                return True
            except Exception as e:
                _e = str(e).lower()
                if _attempt == 1 and ("slide_index" in _e
                                      or "lane_class" in _e):
                    logger.warning(
                        "upsert_ideal_decision: intent columns missing "
                        "(run migrations/add_ideal_decision_intent_key"
                        ".sql) — writing the phrase key only arc=%s",
                        arc_id)
                    payload.pop("slide_index", None)
                    payload.pop("lane_class", None)
                    continue
                if "ideal_decision_ledger" in _e and (
                    "does not exist" in _e or "pgrst" in _e
                ):
                    logger.warning(
                        "upsert_ideal_decision: table missing (run "
                        "migrations/add_ideal_decision_ledger.sql)")
                    return False
                logger.warning("upsert_ideal_decision failed arc=%s: %s",
                               arc_id, e)
                return False
        return False

    def insert_voice_album_entry(self, *, arc_id: str, snippet_id: str,
                                 take_session_id: Optional[str] = None,
                                 slide_index: Optional[int] = None) -> bool:
        """One album entry (SPEC F2 / founder 2026-08-14) — insert-if-
        missing on (arc, snippet); an existing entry is left untouched
        (append-only capture). Best-effort; False pre-migration."""
        if not arc_id or not snippet_id:
            return False
        try:
            self.client.table("voice_album").upsert({
                "arc_id": str(arc_id),
                "snippet_id": str(snippet_id),
                "take_session_id": take_session_id,
                "slide_index": slide_index,
            }, on_conflict="arc_id,snippet_id",
                ignore_duplicates=True).execute()
            return True
        except Exception as e:
            _e = str(e).lower()
            if "voice_album" in _e and (
                "does not exist" in _e or "pgrst" in _e
            ):
                logger.warning(
                    "insert_voice_album_entry: table missing (run "
                    "migrations/add_voice_album.sql) arc=%s", arc_id)
                return False
            logger.warning("insert_voice_album_entry failed arc=%s: %s",
                           arc_id, e)
            return False

    def delete_voice_album_entry(self, *, arc_id: str,
                                 snippet_id: str) -> bool:
        """Remove one album entry — the MIRROR ruling (founder
        2026-08-14): a withdrawn signal (a reverted approval) removes the
        moment; the album reflects current state, never a graveyard of
        changed minds. Best-effort."""
        if not arc_id or not snippet_id:
            return False
        try:
            (self.client.table("voice_album")
             .delete()
             .eq("arc_id", str(arc_id))
             .eq("snippet_id", str(snippet_id))
             .execute())
            return True
        except Exception as e:
            _e = str(e).lower()
            if "voice_album" in _e and (
                "does not exist" in _e or "pgrst" in _e
            ):
                return False
            logger.warning("delete_voice_album_entry failed arc=%s: %s",
                           arc_id, e)
            return False

    def list_voice_album(self, arc_id: Optional[str]) -> list:
        """All album entries for an arc, oldest first. [] pre-migration /
        on hiccup — the capture refresh then simply re-checks everything,
        and the insert's on-conflict keeps it idempotent."""
        if not arc_id:
            return []
        try:
            res = (
                self.client.table("voice_album")
                .select("*")
                .eq("arc_id", str(arc_id))
                .order("entered_at", desc=False)
                .execute()
            )
            original = [dict(row, source_kind="snippet")
                        for row in (res.data or [])]
            try:
                practice_res = (
                    self.client.table("voice_album_practice")
                    .select("*")
                    .eq("arc_id", str(arc_id))
                    .order("entered_at", desc=False)
                    .execute()
                )
                practice = [dict(row, source_kind="practice_attempt")
                            for row in (practice_res.data or [])]
            except Exception as practice_error:
                low = str(practice_error).lower()
                if not ("voice_album_practice" in low and (
                        "does not exist" in low or "pgrst" in low)):
                    logger.warning(
                        "list_voice_album practice read failed arc=%s: %s",
                        arc_id, practice_error)
                practice = []
            return sorted(
                original + practice,
                key=lambda row: str(row.get("entered_at") or ""),
            )
        except Exception as e:
            _e = str(e).lower()
            if "voice_album" in _e and (
                "does not exist" in _e or "pgrst" in _e
            ):
                return []
            logger.warning("list_voice_album failed arc=%s: %s", arc_id, e)
            return []

    def insert_voice_album_practice_entry(
        self, *, arc_id: str, practice_attempt_id: str,
        take_session_id: Optional[str] = None,
        slide_index: Optional[int] = None,
    ) -> bool:
        if not arc_id or not practice_attempt_id:
            return False
        try:
            self.client.table("voice_album_practice").upsert({
                "arc_id": str(arc_id),
                "practice_attempt_id": str(practice_attempt_id),
                "take_session_id": take_session_id,
                "slide_index": slide_index,
            }, on_conflict="arc_id,practice_attempt_id",
                ignore_duplicates=True).execute()
            return True
        except Exception as e:
            logger.warning(
                "insert_voice_album_practice_entry failed arc=%s: %s",
                arc_id, e)
            return False

    def delete_voice_album_practice_entry(
        self, *, arc_id: str, practice_attempt_id: str,
    ) -> bool:
        if not arc_id or not practice_attempt_id:
            return False
        try:
            (self.client.table("voice_album_practice")
             .delete()
             .eq("arc_id", str(arc_id))
             .eq("practice_attempt_id", str(practice_attempt_id))
             .execute())
            return True
        except Exception as e:
            logger.warning(
                "delete_voice_album_practice_entry failed arc=%s: %s",
                arc_id, e)
            return False

    def list_voice_album_notes(
        self, *, arc_id: str, moment_key: str, owner_user_id: str,
    ) -> list:
        """The owner's own notes on one Album moment, oldest first.

        Scoped to the writer on purpose: a note is the user talking to
        themselves, so it is never served to anyone else — not the coach, not
        another owner of a shared project. [] pre-migration / on hiccup.
        """
        if not arc_id or not moment_key or not owner_user_id:
            return []
        try:
            res = (
                self.client.table("voice_album_notes")
                .select("*")
                .eq("arc_id", str(arc_id))
                .eq("moment_key", str(moment_key))
                .eq("owner_user_id", str(owner_user_id))
                .order("created_at", desc=False)
                .execute()
            )
            return res.data or []
        except Exception as e:
            low = str(e).lower()
            if not ("voice_album_notes" in low
                    and ("does not exist" in low or "pgrst" in low)):
                logger.warning("list_voice_album_notes failed arc=%s: %s",
                               arc_id, e)
            return []

    def insert_voice_album_note(
        self, *, arc_id: str, moment_key: str, owner_user_id: str, body: str,
    ) -> Optional[dict]:
        """Append one owner note. Returns the stored row, or None on any miss.

        Append-only by design: the note is a record of what the user thought
        at that point in the moment's life, so a later note is a new row
        rather than an edit of the last one.
        """
        if not arc_id or not moment_key or not owner_user_id:
            return None
        text = str(body or "").strip()
        if not text:
            return None
        try:
            res = (
                self.client.table("voice_album_notes")
                .insert({
                    "arc_id": str(arc_id),
                    "moment_key": str(moment_key),
                    "owner_user_id": str(owner_user_id),
                    "body": text[:2000],
                })
                .execute()
            )
            return (res.data or [None])[0]
        except Exception as e:
            logger.warning("insert_voice_album_note failed arc=%s: %s",
                           arc_id, e)
            return None

    def get_moment_suggestion(self, snippet_id: Optional[str]) -> Optional[dict]:
        """The one suggestion row of a moment (moment_suggestions is keyed
        by snippet), or None. Raises on a real read failure."""
        if not snippet_id:
            return None
        res = (self.client.table("moment_suggestions")
               .select("snippet_id,kind,trigger,cue_keys")
               .eq("snippet_id", str(snippet_id)).limit(1).execute())
        return (res.data or [None])[0]

    def delete_moment_suggestion(self, snippet_id: Optional[str]) -> bool:
        """Drop one star row — a DISMISSED star must not survive to the
        next serve/anchor pass (founder 2026-07-20 rule 2; the ledger
        remembers the decision, this removes the offer). Best-effort."""
        if not snippet_id:
            return False
        try:
            (self.client.table("moment_suggestions")
             .delete()
             .eq("snippet_id", str(snippet_id))
             .execute())
            return True
        except Exception as e:
            logger.warning("delete_moment_suggestion failed snip=%s: %s",
                           snippet_id, e)
            return False

    def delete_ideal_decision(self, arc_id: str, kind: str,
                              target_phrase: str) -> bool:
        """A reverted approval wipes the row — the phrase becomes
        suggestible again. Best-effort."""
        if not arc_id or not kind or not target_phrase:
            return False
        try:
            (self.client.table("ideal_decision_ledger")
             .delete()
             .eq("arc_id", str(arc_id))
             .eq("kind", kind)
             .eq("target_phrase", target_phrase)
             .execute())
            return True
        except Exception as e:
            logger.warning("delete_ideal_decision failed arc=%s: %s",
                           arc_id, e)
            return False

    def list_intervention_decision_history(self, arc_id: Optional[str],
                                           limit: int = 50) -> list:
        """The arc's decided proposals THAT STILL CARRY THEIR TEXT — the
        deck editor's "proposals from earlier iterations" (slice 2,
        founder 2026-08-11). Rows written before the texts migration have
        no quote and are unlistable — filtered here, never invented.
        Newest first. [] pre-migration / on hiccup."""
        if not arc_id:
            return []
        try:
            res = (
                self.client.table("intervention_decisions")
                .select("change_key,decision,lane,intervention_type,"
                        "quote,proposed_text,why_key,updated_at")
                .eq("arc_id", str(arc_id))
                .order("updated_at", desc=True)
                .limit(max(1, int(limit)))
                .execute()
            )
            return [r for r in (res.data or [])
                    if isinstance(r, dict) and (r.get("quote")
                                                or r.get("proposed_text"))]
        except Exception as e:
            logger.warning(
                "list_intervention_decision_history failed arc=%s: %s",
                arc_id, e)
            return []

    def record_intervention_decision(self, *, arc_id: str,
                                     take_session_id: str,
                                     change_key: str,
                                     decision: str,
                                     lane: Optional[str] = None,
                                     intervention_type: Optional[str] = None,
                                     quote: Optional[str] = None,
                                     proposed_text: Optional[str] = None,
                                     why_key: Optional[str] = None,
                                     ) -> bool:
        """One decided intervention — SPEC §3.3's ground-truth row AND one
        spent budget slot (founder 2026-08-10: the ≤3 is PER TAKE, and a
        decided offer never frees its slot). Vocabulary is the SPEC's:
        approved / disregarded; absence of a row means UNDECIDED (R4).
        Upsert on the offer's identity so a re-tap updates in place rather
        than double-spending. lane/intervention_type ride along when the
        caller knows them — they are the §6 join to intervention_arms.
        Best-effort."""
        if not arc_id or not change_key \
                or decision not in ("approved", "disregarded"):
            return False
        try:
            row: dict = {
                "arc_id": str(arc_id),
                "take_session_id": str(take_session_id or ""),
                "change_key": str(change_key),
                "decision": decision,
                "lane": lane,
                "intervention_type": intervention_type,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            # The proposal texts (slice 2 history) ride only when the caller
            # HAS them: a re-tap without them must not null what an earlier
            # write stored. Pre-migration these keys would 400 the upsert, so
            # a schema-cache miss retries without them — the decision (the
            # spend) must never be lost to the history columns.
            texts = {k: v for k, v in (("quote", quote),
                                       ("proposed_text", proposed_text),
                                       ("why_key", why_key)) if v}
            try:
                self.client.table("intervention_decisions").upsert(
                    {**row, **texts},
                    on_conflict="arc_id,take_session_id,change_key").execute()
            except Exception as inner:
                if not texts:
                    raise
                _ie = str(inner).lower()
                if "quote" in _ie or "proposed_text" in _ie \
                        or "why_key" in _ie or "pgrst204" in _ie:
                    self.client.table("intervention_decisions").upsert(
                        row,
                        on_conflict="arc_id,take_session_id,change_key"
                    ).execute()
                else:
                    raise
            return True
        except Exception as e:
            _e = str(e).lower()
            if "intervention_decisions" in _e and (
                "does not exist" in _e or "pgrst" in _e
            ):
                logger.warning(
                    "record_intervention_decision: table missing (run "
                    "migrations/add_intervention_decisions.sql)")
                return False
            logger.warning("record_intervention_decision failed arc=%s: %s",
                           arc_id, e)
            return False

    def delete_intervention_decision(self, *, arc_id: str,
                                     take_session_id: str,
                                     change_key: str) -> bool:
        """A reverted decision returns its slot — the offer is undecided
        again and the take's budget grows back by one. Best-effort."""
        if not arc_id or not change_key:
            return False
        try:
            (self.client.table("intervention_decisions")
             .delete()
             .eq("arc_id", str(arc_id))
             .eq("take_session_id", str(take_session_id or ""))
             .eq("change_key", str(change_key))
             .execute())
            return True
        except Exception as e:
            logger.warning("delete_intervention_decision failed arc=%s: %s",
                           arc_id, e)
            return False

    # ── BLINDED A/B SLIDE VERDICTS (founder 2026-08-11) ──────────────────
    #
    # The corpus that unblocks piece (b) — see
    # migrations/add_slide_ab_verdicts.sql for what a row means and why the
    # sides are stored AS SHOWN rather than as winner/loser.

    def record_slide_ab_verdict(self, *, arc_id: str, slide_index: int,
                                session_left: str, session_right: str,
                                verdict: str,
                                winner_session_id: Optional[str] = None,
                                left_text: Optional[str] = None,
                                right_text: Optional[str] = None,
                                rated_by: Optional[str] = None) -> bool:
        """One blinded comparison. Append-only — a re-rating is a new row, so
        intra-rater reliability stays computable. Best-effort: a labelling
        write must never break the review it rides with."""
        if not arc_id or verdict not in ("left", "right", "tie"):
            return False
        try:
            self.client.table("slide_ab_verdicts").insert({
                "arc_id": str(arc_id),
                "slide_index": int(slide_index),
                "session_left": str(session_left),
                "session_right": str(session_right),
                "verdict": verdict,
                "winner_session_id": (
                    str(winner_session_id) if winner_session_id else None
                ),
                "left_text": left_text,
                "right_text": right_text,
                "rated_by": str(rated_by) if rated_by else None,
            }).execute()
            return True
        except Exception as e:
            logger.warning("record_slide_ab_verdict failed arc=%s: %s",
                           arc_id, e)
            return False

    def list_slide_ab_verdicts(self, arc_id: str) -> list:
        """Every verdict for an arc, newest first — the corpus AND the
        already-rated set the serve subtracts. [] pre-migration."""
        if not arc_id:
            return []
        try:
            res = (
                self.client.table("slide_ab_verdicts")
                .select("*")
                .eq("arc_id", str(arc_id))
                .order("created_at", desc=True)
                .execute()
            )
            return list(res.data or [])
        except Exception as e:
            _e = str(e).lower()
            if "slide_ab_verdicts" in _e and (
                "does not exist" in _e or "pgrst" in _e
            ):
                return []
            logger.warning("list_slide_ab_verdicts failed arc=%s: %s",
                           arc_id, e)
            return []

    # ── THE COACH'S WORD→SLIDE GROUND TRUTH (founder 2026-08-11) ─────────
    #
    # Append-only by design (migrations/add_snippet_slide_corrections.sql):
    # the latest row per snippet wins and the earlier ones stay as the audit
    # trail. Never an upsert — a silently overwritten label is a corpus
    # nobody can compare across time.

    def get_snippet_slide_corrections(self, session_id: str) -> dict:
        """{snippet_id: slide_index} for one session — the LATEST correction
        per snippet, reverts included as an explicit None.

        Returns {} pre-migration / on hiccup: the pipeline's own bucketing is
        the floor, so a missing table degrades to today's behaviour and never
        darkens a take. Ordered newest-first and taken first-seen, which is
        the append-only table's "latest wins" in one pass."""
        if not session_id:
            return {}
        try:
            res = (
                self.client.table("snippet_slide_corrections")
                .select("snippet_id,slide_index")
                .eq("session_id", str(session_id))
                .order("created_at", desc=True)
                .order("id", desc=True)
                .execute()
            )
            out: dict = {}
            for r in (res.data or []):
                sid = str((r or {}).get("snippet_id") or "")
                if sid and sid not in out:
                    out[sid] = (r or {}).get("slide_index")
            return out
        except Exception as e:
            _e = str(e).lower()
            if "snippet_slide_corrections" in _e and (
                "does not exist" in _e or "pgrst" in _e
            ):
                return {}
            logger.warning("get_snippet_slide_corrections failed sid=%s: %s",
                           session_id, e)
            return {}

    def list_snippet_slide_corrections(self, session_id: str) -> list:
        """Every row for a session, newest first — the audit trail + the
        training corpus (each row is one (speech window, slide) pair with
        what the pipeline said beside it). [] pre-migration."""
        if not session_id:
            return []
        try:
            res = (
                self.client.table("snippet_slide_corrections")
                .select("*")
                .eq("session_id", str(session_id))
                .order("created_at", desc=True)
                .execute()
            )
            return list(res.data or [])
        except Exception as e:
            _e = str(e).lower()
            if "snippet_slide_corrections" in _e and (
                "does not exist" in _e or "pgrst" in _e
            ):
                return []
            logger.warning("list_snippet_slide_corrections failed sid=%s: %s",
                           session_id, e)
            return []

    def count_intervention_decisions(self, arc_id: Optional[str],
                                     take_session_id: Optional[str]) -> int:
        """Spent slots for one take. 0 pre-migration / on hiccup — the
        serve degrades to the per-arbitration budget, never to silence.

        STYLE-LANE rows (lane == "lane:style") do NOT count: the post-lock
        style lane rides OUTSIDE the ≤3 budget (founder 2026-08-11, ruling
        4). Counted in Python rather than with .neq — PostgREST's neq
        drops NULL lanes too, and the star lane's rows carry lane NULL, so
        a server-side filter would silently free slots that were spent."""
        if not arc_id:
            return 0
        try:
            res = (
                self.client.table("intervention_decisions")
                .select("lane")
                .eq("arc_id", str(arc_id))
                .eq("take_session_id", str(take_session_id or ""))
                .execute()
            )
            return sum(1 for r in (res.data or [])
                       if (r or {}).get("lane") != "lane:style")
        except Exception as e:
            _e = str(e).lower()
            if "intervention_decisions" in _e and (
                "does not exist" in _e or "pgrst" in _e
            ):
                return 0
            logger.warning("count_intervention_decisions failed arc=%s: %s",
                           arc_id, e)
            return 0

    def list_spent_intervention_decisions(self, arc_id: Optional[str],
                                          take_session_id: Optional[str]
                                          ) -> list:
        """The take's spent slots WITH THE WORDS THEY WERE SPENT ON —
        [{quote}], style-lane rows excluded by the same rule
        `count_intervention_decisions` applies.

        The budget is counted per SLIDE now (founder 2026-08-11), and this
        table has no slide column: the quote is what places a spent slot in
        the document, which needs no migration and no backfill. A row whose
        quote predates the texts migration cannot be placed and is simply not
        counted against any slide — history is never invented, and the error
        runs toward offering MORE feedback rather than silently withholding
        it. [] pre-migration / on hiccup."""
        if not arc_id:
            return []
        try:
            res = (
                self.client.table("intervention_decisions")
                .select("lane,quote")
                .eq("arc_id", str(arc_id))
                .eq("take_session_id", str(take_session_id or ""))
                .execute()
            )
            return [r for r in (res.data or [])
                    if isinstance(r, dict)
                    and r.get("lane") != "lane:style"
                    and (r.get("quote") or "").strip()]
        except Exception as e:
            _e = str(e).lower()
            if "intervention_decisions" in _e and (
                "does not exist" in _e or "pgrst" in _e
            ):
                return []
            logger.warning(
                "list_spent_intervention_decisions failed arc=%s: %s",
                arc_id, e)
            return []

    def list_style_intervention_decisions(self, arc_id: Optional[str],
                                          take_session_id: Optional[str]
                                          ) -> list:
        """The take's spent STYLE slots — [{quote}], the exact rows the two
        methods above throw away.

        The style lane got its own ≤3-per-take / ≤2-per-slide budget
        (founder 2026-08-12) and needs its own ledger read, because
        `count_intervention_decisions` and `list_spent_intervention_decisions`
        both exclude `lane:style` on purpose: style rides OUTSIDE the ≤3
        (ruling 4). Two budgets, two reads, neither charging the other.

        Rows are kept even with a blank quote — the CALLER places what it can
        and counts everything, since a slot spent on words that have since
        been baked away is still spent against the take. Filtered in Python
        for the same reason its siblings are: PostgREST's `.eq` on `lane`
        would be fine here, but keeping all three on one code path means a
        future change to what "style" means cannot update two of them and
        miss the third. [] pre-migration / on hiccup — a ledger miss degrades
        to the per-serve cap, never to silence."""
        if not arc_id:
            return []
        try:
            res = (
                self.client.table("intervention_decisions")
                .select("lane,quote")
                .eq("arc_id", str(arc_id))
                .eq("take_session_id", str(take_session_id or ""))
                .execute()
            )
            return [r for r in (res.data or [])
                    if isinstance(r, dict) and r.get("lane") == "lane:style"]
        except Exception as e:
            _e = str(e).lower()
            if "intervention_decisions" in _e and (
                "does not exist" in _e or "pgrst" in _e
            ):
                return []
            logger.warning(
                "list_style_intervention_decisions failed arc=%s: %s",
                arc_id, e)
            return []

    def list_ideal_decisions(self, arc_id: Optional[str]) -> list:
        """All ledger rows of an arc. [] pre-migration / on hiccup —
        callers degrade to no-memory behavior."""
        if not arc_id:
            return []
        try:
            res = (
                self.client.table("ideal_decision_ledger")
                .select("*")
                .eq("arc_id", str(arc_id))
                .execute()
            )
            return res.data or []
        except Exception as e:
            _e = str(e).lower()
            if "ideal_decision_ledger" in _e and (
                "does not exist" in _e or "pgrst" in _e
            ):
                return []
            logger.warning("list_ideal_decisions failed arc=%s: %s",
                           arc_id, e)
            return []

    def upsert_ideal_text_version(self, arc_id: str, version: int,
                                  text: str, moments: Any,
                                  document: Optional[dict] = None) -> bool:
        """Append-only per-VERSION snapshot (founder 2026-07-20) — the text
        as this version assembled it + that step's sanitized reasoning.
        Idempotent per (arc, version). Best-effort."""
        if not arc_id or not isinstance(version, int) or version < 1 \
                or not (text or "").strip():
            return False
        try:
            self.client.table("ideal_text_versions").upsert({
                "arc_id": str(arc_id),
                "version": version,
                "text": text,
                "moments": moments,
                # The Slide map this version had (paragraph history, 3c).
                **({"document": document} if isinstance(document, dict)
                   else {}),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }, on_conflict="arc_id,version").execute()
            return True
        except Exception as e:
            _e = str(e).lower()
            if "ideal_text_versions" in _e and (
                "does not exist" in _e or "pgrst" in _e
            ):
                logger.warning(
                    "upsert_ideal_text_version: table missing (run "
                    "migrations/add_ideal_text_versions.sql)")
                return False
            logger.warning("upsert_ideal_text_version failed arc=%s: %s",
                           arc_id, e)
            return False

    def list_ideal_text_versions(self, arc_id: Optional[str]) -> list:
        """Every version snapshot of one document, oldest first; [] on any
        failure (the history then simply has nothing to show)."""
        if not arc_id:
            return []
        try:
            return (self.client.table("ideal_text_versions")
                    .select("version,text,document,created_at")
                    .eq("arc_id", str(arc_id))
                    .order("version")
                    .execute().data) or []
        except Exception as e:
            logger.warning("list_ideal_text_versions failed arc=%s: %s",
                           arc_id, e)
            return []

    def get_ideal_text_version(self, arc_id: Optional[str],
                               version: Any) -> Optional[dict]:
        """One historical snapshot, or None (pre-migration / never
        snapshotted / hiccup — callers fall back to the live view)."""
        if not arc_id or not isinstance(version, int):
            return None
        try:
            res = (
                self.client.table("ideal_text_versions")
                .select("*")
                .eq("arc_id", str(arc_id))
                .eq("version", version)
                .limit(1)
                .execute()
            )
            return (res.data or [None])[0]
        except Exception as e:
            _e = str(e).lower()
            if "ideal_text_versions" in _e and (
                "does not exist" in _e or "pgrst" in _e
            ):
                return None
            logger.warning("get_ideal_text_version failed arc=%s: %s",
                           arc_id, e)
            return None

    # ── master-document blocks + saves (founder 2026-07-22) ──────────
    # See services/master_document.py + add_ideal_text_blocks.sql.
    # All best-effort; list returns None on FAILURE ([] only on a real
    # empty read) — the read-fail ≠ empty lesson.

    def get_snippets_by_ids(self, snippet_ids: Any) -> list:
        """Bulk snippet read — ONE query instead of a round trip per
        piece (review 2026-07-22 perf finding). Carries `metrics` (the
        block-ranking judge) and `say_it_stronger` (the T3 emphasis
        key-phrase signal, 2026-07-23). Best-effort: on the
        column-missing case (say_it_stronger not migrated) it retries
        without it; [] on any other failure."""
        ids = [str(x) for x in (snippet_ids or []) if x]
        if not ids:
            return []
        try:
            try:
                res = (
                    self.client.table(SNIPPETS_TABLE)
                    .select("id, metrics, say_it_stronger")
                    .in_("id", ids)
                    .execute()
                )
                return res.data or []
            except Exception as _e_full:
                if "say_it_stronger" not in str(_e_full).lower():
                    raise
            res = (
                self.client.table(SNIPPETS_TABLE)
                .select("id, metrics")
                .in_("id", ids)
                .execute()
            )
            return res.data or []
        except Exception as e:
            logger.warning("get_snippets_by_ids failed (%d ids): %s",
                           len(ids), e)
            return []

    # ── variant pool + compositions (founder 2026-08-03) ─────────────
    # See services/ideal_text_variants.py + add_ideal_text_variant_pool
    # .sql. Append-only lanes; all best-effort; list reads return None
    # on FAILURE ([] only on a real empty read).

    def insert_ideal_text_block_variant(self, arc_id: str, block_key: int,
                                        fields: dict) -> Optional[dict]:
        """One APPEND-ONLY variant row; returns the inserted row (the
        caller needs its id for composition pointers) or None. A take-
        sourced duplicate (same arc/block/take — the partial unique
        index) returns None quietly: the pool already has it."""
        if not arc_id or not isinstance(block_key, int) \
                or not isinstance(fields, dict):
            return None
        try:
            payload = dict(fields)
            payload["arc_id"] = str(arc_id)
            payload["block_key"] = block_key
            res = (self.client.table("ideal_text_block_variants")
                   .insert(payload).execute())
            return (res.data or [None])[0]
        except Exception as e:
            _e = str(e).lower()
            if "duplicate" in _e or "unique" in _e or "23505" in _e:
                return None
            if "ideal_text_block_variants" in _e and (
                "does not exist" in _e or "pgrst" in _e
            ):
                logger.warning(
                    "insert_ideal_text_block_variant: table missing (run "
                    "migrations/add_ideal_text_variant_pool.sql)")
                return None
            logger.warning("insert_ideal_text_block_variant failed "
                           "arc=%s: %s", arc_id, e)
            return None

    def list_ideal_text_block_variants(
            self, arc_id: Optional[str]) -> Optional[list]:
        if not arc_id:
            return None
        try:
            res = (
                self.client.table("ideal_text_block_variants")
                .select("*")
                .eq("arc_id", str(arc_id))
                .order("created_at", desc=False)
                .execute()
            )
            return res.data or []
        except Exception as e:
            _e = str(e).lower()
            if not ("ideal_text_block_variants" in _e and (
                    "does not exist" in _e or "pgrst" in _e)):
                logger.warning("list_ideal_text_block_variants failed "
                               "arc=%s: %s", arc_id, e)
            return None

    def get_ideal_text_block_variant(self, arc_id: Optional[str],
                                     variant_id: Any) -> Optional[dict]:
        """One variant by id, ARC-SCOPED — the select route must never
        resolve another arc's variant id."""
        if not arc_id or not variant_id:
            return None
        try:
            res = (
                self.client.table("ideal_text_block_variants")
                .select("*")
                .eq("arc_id", str(arc_id))
                .eq("id", str(variant_id))
                .limit(1)
                .execute()
            )
            return (res.data or [None])[0]
        except Exception as e:
            logger.warning("get_ideal_text_block_variant failed arc=%s: %s",
                           arc_id, e)
            return None

    def insert_ideal_text_composition(self, arc_id: str, revision: int,
                                      selections: Any, reason: Any,
                                      created_by: Any) -> bool:
        """One APPEND-ONLY composition revision. A (arc, revision)
        conflict returns False — the caller retries with the next
        number; existing history is never overwritten."""
        if not arc_id or not isinstance(revision, int) or revision < 1:
            return False
        try:
            (self.client.table("ideal_text_compositions").insert({
                "arc_id": str(arc_id),
                "revision": revision,
                "selections": selections or [],
                "reason": reason,
                "created_by": (str(created_by) if created_by else None),
            }).execute())
            return True
        except Exception as e:
            _e = str(e).lower()
            if "ideal_text_compositions" in _e and (
                "does not exist" in _e or "pgrst" in _e
            ):
                logger.warning(
                    "insert_ideal_text_composition: table missing (run "
                    "migrations/add_ideal_text_variant_pool.sql)")
                return False
            if not ("duplicate" in _e or "unique" in _e or "23505" in _e):
                logger.warning("insert_ideal_text_composition failed "
                               "arc=%s: %s", arc_id, e)
            return False

    def get_ideal_text_composition(self, arc_id: Optional[str],
                                   revision: Any) -> Optional[dict]:
        if not arc_id or not isinstance(revision, int):
            return None
        try:
            res = (
                self.client.table("ideal_text_compositions")
                .select("*")
                .eq("arc_id", str(arc_id))
                .eq("revision", revision)
                .limit(1)
                .execute()
            )
            return (res.data or [None])[0]
        except Exception as e:
            logger.warning("get_ideal_text_composition failed arc=%s: %s",
                           arc_id, e)
            return None

    def list_ideal_text_compositions(self, arc_id: Optional[str],
                                     limit: int = 50) -> Optional[list]:
        """Newest first, bounded — the revisions timeline read."""
        if not arc_id:
            return None
        try:
            res = (
                self.client.table("ideal_text_compositions")
                .select("*")
                .eq("arc_id", str(arc_id))
                .order("revision", desc=True)
                .limit(max(1, int(limit)))
                .execute()
            )
            return res.data or []
        except Exception as e:
            _e = str(e).lower()
            if not ("ideal_text_compositions" in _e and (
                    "does not exist" in _e or "pgrst" in _e)):
                logger.warning("list_ideal_text_compositions failed "
                               "arc=%s: %s", arc_id, e)
            return None

    def get_ideal_text_composition_head(
            self, arc_id: Optional[str]) -> Optional[dict]:
        if not arc_id:
            return None
        try:
            res = (
                self.client.table("ideal_text_composition_head")
                .select("*")
                .eq("arc_id", str(arc_id))
                .limit(1)
                .execute()
            )
            return (res.data or [None])[0]
        except Exception:
            return None

    def set_ideal_text_composition_head(self, arc_id: str,
                                        revision: int) -> bool:
        """Repoint the one live pointer — undo/restore IS this write."""
        if not arc_id or not isinstance(revision, int) or revision < 1:
            return False
        try:
            self.client.table("ideal_text_composition_head").upsert({
                "arc_id": str(arc_id),
                "head_revision": revision,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }, on_conflict="arc_id").execute()
            return True
        except Exception as e:
            _e = str(e).lower()
            if "ideal_text_composition_head" in _e and (
                "does not exist" in _e or "pgrst" in _e
            ):
                logger.warning(
                    "set_ideal_text_composition_head: table missing (run "
                    "migrations/add_ideal_text_variant_pool.sql)")
                return False
            logger.warning("set_ideal_text_composition_head failed "
                           "arc=%s: %s", arc_id, e)
            return False

    def deduct_credits_strict(
        self, user_id: Optional[str], amount: int,
    ) -> Optional[int]:
        """HARD atomic deduct for the $25/25-credit arc unlock (2026-07-06) —
        unlike v2_deduct_session_credits (soft, floors at 0, read-then-write),
        this NEVER oversells: it fails (returns None) when the balance is
        insufficient, using a compare-and-swap so a concurrent write can never
        race it into a negative or double-spent balance.

        Returns the NEW balance on success, or None on insufficient funds / a
        db hiccup / exhausted CAS retries (the caller must treat None as
        "did not charge" and roll back whatever it reserved)."""
        if not user_id or not isinstance(amount, int) or amount <= 0:
            return None
        from datetime import datetime, timezone
        for _ in range(3):
            details = self.v2_get_student_details(str(user_id)) or {}
            current = details.get("credits")
            if current is None:
                # Unseeded user. Taking _free_credit_grant() as the balance here
                # is NOT enough: the CAS below is an UPDATE ... eq(credits, N),
                # and an UPDATE never creates a row, so it would match nothing
                # and the caller would report INSUFFICIENT_CREDITS to a user who
                # actually holds the grant. Write the row first (idempotent,
                # guarded by credits_initialized_at — a user who spent down to 0
                # is never re-granted), then CAS against the seeded value.
                current = self.v2_ensure_credits_initialized(str(user_id))
            current = int(current)
            if current < amount:
                return None  # genuinely insufficient — no point retrying
            new_val = current - amount
            try:
                res = (
                    self.client.table("v2_student_details")
                    .update({
                        "credits": new_val,
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    })
                    .eq("user_id", str(user_id))
                    .eq("credits", current)  # CAS guard on the value we read
                    .execute()
                )
            except Exception as e:
                logger.warning("deduct_credits_strict failed user=%s: %s",
                               user_id, e)
                return None
            if res.data:
                return new_val
            # Someone else changed the balance between our read and write —
            # benign race, not insufficiency. Retry with a fresh read.
        logger.warning(
            "deduct_credits_strict: CAS retries exhausted user=%s amount=%s",
            user_id, amount,
        )
        return None

    def get_coach_best_presentation_edits(self, arc_id: Optional[str]) -> dict:
        """Per-slide COACH corrections to an arc's ideal text (founder
        2026-07-06 — the coach-owned counterpart to the user's pencil-edit).
        Returns {slide_index: text}. {} on missing table / none / error."""
        if not arc_id:
            return {}
        try:
            res = (
                self.client.table("coach_best_presentation_edits")
                .select("slide_index, text")
                .eq("arc_id", arc_id)
                .execute()
            )
            return {
                r.get("slide_index"): r.get("text")
                for r in (res.data or [])
                if isinstance(r.get("slide_index"), int)
            }
        except Exception as e:
            err_low = str(e).lower()
            if "coach_best_presentation_edits" in err_low and (
                "does not exist" in err_low or "pgrst" in err_low
            ):
                return {}
            logger.warning("get_coach_best_presentation_edits failed arc=%s: %s",
                           arc_id, e)
            return {}

    def get_coach_best_presentation_edits_for_arcs(
        self, arc_ids: list[str],
    ) -> dict[str, dict]:
        """{arc_id: {slide_index: text}} for many arcs in ONE read (D-CS-4):
        the every-project read asks once instead of once per project. A
        missing table is {}; any other failure raises."""
        ids = sorted({str(a) for a in arc_ids or [] if a})
        if not ids:
            return {}
        try:
            res = (self.client.table("coach_best_presentation_edits")
                   .select("arc_id, slide_index, text")
                   .in_("arc_id", ids).execute())
        except Exception as e:
            err_low = str(e).lower()
            if "coach_best_presentation_edits" in err_low and (
                    "does not exist" in err_low or "pgrst205" in err_low):
                return {}
            raise
        out: dict[str, dict] = {}
        for r in res.data or []:
            if isinstance(r, dict) and isinstance(r.get("slide_index"), int):
                out.setdefault(str(r.get("arc_id")), {})[r["slide_index"]] = r.get("text")
        return out

    def get_coach_best_presentation_key_phrases(self, arc_id) -> dict:
        """{slide_index: [phrases]} — the coach-corrected key phrases (Engine
        2, 2026-07-11). {} on missing table/column / none / error (the auto-
        derived set serves)."""
        if not arc_id:
            return {}
        try:
            res = (
                self.client.table("coach_best_presentation_edits")
                .select("slide_index, key_phrases")
                .eq("arc_id", arc_id)
                .execute()
            )
            out = {}
            for r in (res.data or []):
                kp = r.get("key_phrases")
                if isinstance(r.get("slide_index"), int) and isinstance(kp, list):
                    phrases = [str(x).strip() for x in kp
                               if isinstance(x, str) and str(x).strip()]
                    if phrases:
                        out[r["slide_index"]] = phrases
            return out
        except Exception:
            return {}

    # (upsert_coach_best_presentation_edit DELETED 2026-07-15 — the per-
    #  slide coach editor was replaced by the ONE-block ideal text
    #  (coach_arc_ideal_text); the readers below stay: compose still
    #  folds edits saved before the switch.)

    def insert_recording_feeling(
        self, *, session_id: str, feeling: str,
        user_id: Optional[str] = None, recording_id: Optional[str] = None,
        arc_id: Optional[str] = None, take_index: Optional[int] = None,
    ) -> bool:
        """Persist a pre-recording feeling (U10 — split-sink, audit-stage
        correlation input). Best-effort + non-fatal: a missing table or a bad
        value never breaks the recording. The route pre-validates the enum."""
        if not session_id or not feeling:
            return False
        row = {"session_id": session_id, "feeling": feeling}
        if user_id:
            row["user_id"] = user_id
        if recording_id:
            row["recording_id"] = recording_id
        if arc_id:
            row["arc_id"] = arc_id
        if take_index is not None:
            row["take_index"] = take_index
        try:
            self.client.table("recording_feelings").insert(row).execute()
            return True
        except Exception as e:
            err_low = str(e).lower()
            if "recording_feelings" in err_low and (
                "does not exist" in err_low or "pgrst" in err_low
            ):
                logger.warning(
                    "insert_recording_feeling: table missing (run "
                    "migrations/add_recording_feelings.sql) session=%s",
                    session_id,
                )
                return False
            logger.warning(
                "insert_recording_feeling failed session=%s: %s", session_id, e,
            )
            return False

    def get_feelings_by_session(self, session_id: str) -> list[dict]:
        """The pre-recording feeling(s) the student named for a session (U10 —
        coach review read). Usually one row; [] on missing table / none /
        error. Coach-only — never serialised to the user."""
        if not session_id:
            return []
        try:
            res = (
                self.client.table("recording_feelings")
                .select("feeling, take_index, recording_id, created_at")
                .eq("session_id", session_id)
                .order("created_at", desc=False)
                .execute()
            )
            return res.data or []
        except Exception as e:
            err_low = str(e).lower()
            if "recording_feelings" in err_low and (
                "does not exist" in err_low or "pgrst" in err_low
            ):
                return []
            logger.warning("get_feelings_by_session failed sid=%s: %s",
                           session_id, e)
            return []

    def get_user_transcript_edits(self, session_id: Optional[str]) -> list:
        """The user's own transcript corrections for a session (founder
        2026-07-07) — display layer only, the coach keeps the original.
        Returns [{snippet_id, chunk_index, text}]; [] on missing table /
        none / error."""
        if not session_id:
            return []
        try:
            res = (
                self.client.table("user_transcript_edits")
                .select("snippet_id, chunk_index, text")
                .eq("session_id", session_id)
                .execute()
            )
            return [r for r in (res.data or []) if isinstance(r, dict)]
        except Exception as e:
            err_low = str(e).lower()
            if "user_transcript_edits" in err_low and (
                "does not exist" in err_low or "pgrst" in err_low
            ):
                return []
            logger.warning("get_user_transcript_edits failed sid=%s: %s",
                           session_id, e)
            return []

    def upsert_user_transcript_edit(
        self,
        session_id: str,
        *,
        snippet_id: Optional[str] = None,
        chunk_index: Optional[int] = None,
        text: str,
    ) -> bool:
        """Save the user's corrected transcript text for ONE target — a
        snippet (snippet_id) or a deckless full-transcript chunk
        (chunk_index). Exactly one target must be set.

        Manual select→update-or-insert rather than a single on_conflict
        upsert: the table serves TWO row kinds against two different
        unique pairs — (session_id, snippet_id) and (session_id,
        chunk_index) — and PostgREST's upsert takes one on_conflict target,
        so one call shape can't serve both kinds. The unique constraints DO
        enforce per-kind dedupe (the target column is non-NULL for its own
        kind), which means a concurrent first-save race surfaces as a
        unique-violation on our insert — caught below and retried as the
        update it really is. Best-effort; missing table → False."""
        has_snip = bool(snippet_id)
        has_chunk = isinstance(chunk_index, int) and chunk_index >= 0
        if not session_id or not text or has_snip == has_chunk:
            return False
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()

        def _select_existing():
            q = (
                self.client.table("user_transcript_edits")
                .select("id")
                .eq("session_id", session_id)
            )
            q = q.eq("snippet_id", snippet_id) if has_snip \
                else q.eq("chunk_index", chunk_index)
            return (q.limit(1).execute()).data or []

        def _update(row_id):
            (
                self.client.table("user_transcript_edits")
                .update({"text": text, "updated_at": now})
                .eq("id", row_id)
                .execute()
            )

        try:
            rows = _select_existing()
            if rows:
                _update(rows[0]["id"])
                return True
            row = {"session_id": session_id, "text": text, "updated_at": now}
            if has_snip:
                row["snippet_id"] = snippet_id
            else:
                row["chunk_index"] = chunk_index
            try:
                self.client.table("user_transcript_edits").insert(row).execute()
                return True
            except Exception as ins_err:
                ins_low = str(ins_err).lower()
                if "23505" in ins_low or "duplicate key" in ins_low \
                        or "unique" in ins_low:
                    # Lost a concurrent first-save race — the row exists now;
                    # this request becomes the update it really is.
                    rows = _select_existing()
                    if rows:
                        _update(rows[0]["id"])
                        return True
                raise
        except Exception as e:
            err_low = str(e).lower()
            if "user_transcript_edits" in err_low and (
                "does not exist" in err_low or "pgrst" in err_low
            ):
                logger.warning(
                    "upsert_user_transcript_edit: table missing (run "
                    "migrations/add_user_transcript_edits.sql) sid=%s",
                    session_id,
                )
                return False
            logger.error("upsert_user_transcript_edit failed sid=%s: %s",
                         session_id, e)
            return False

    def get_best_presentation_cache(self, arc_id: Optional[str]) -> Optional[dict]:
        """The cached composed best-presentation for an arc (Part B — skip the
        ~2-4s LLM compose when nothing changed). Returns {signature, payload} or
        None on miss / missing table / error (caller recomputes)."""
        if not arc_id:
            return None
        try:
            res = (
                self.client.table("best_presentation_cache")
                .select("signature, payload")
                .eq("arc_id", arc_id)
                .limit(1)
                .execute()
            )
            return (res.data or [None])[0]
        except Exception as e:
            err_low = str(e).lower()
            if "best_presentation_cache" in err_low and (
                "does not exist" in err_low or "pgrst" in err_low
            ):
                return None
            logger.warning("get_best_presentation_cache failed arc=%s: %s",
                           arc_id, e)
            return None

    def get_feelings_by_sessions(self, session_ids: list) -> list[dict]:
        """Pre-recording feelings for a BATCH of sessions (U10 — the coach
        roster rollup). One query, mapped by the caller. [] on missing table /
        empty input / error."""
        if not session_ids:
            return []
        try:
            res = (
                self.client.table("recording_feelings")
                .select("session_id, feeling, take_index, created_at")
                .in_("session_id", list(session_ids))
                .order("created_at", desc=False)
                .execute()
            )
            return res.data or []
        except Exception as e:
            err_low = str(e).lower()
            if "recording_feelings" in err_low and (
                "does not exist" in err_low or "pgrst" in err_low
            ):
                return []
            logger.warning("get_feelings_by_sessions failed: %s", e)
            return []

    # ── willab — arc batch delivery (founder 2026-07-13) ────────────────
    #
    # arc_batch_deliveries: one row per arc, stamped by the coach's explicit
    # "Publish arc" action — the WHOLE training (all takes' labelled snippets
    # + the finalized ideal text) delivered to the student as ONE batch.
    # Coexists with the per-take publish. See
    # migrations/add_arc_batch_deliveries.sql.

    def mark_arc_batch_delivered(
        self, arc_id: str, user_id: Optional[str], coach_id: Optional[str],
    ) -> bool:
        """Upsert the one-row-per-arc batch-delivery marker. Idempotent — a
        re-publish refreshes published_at (the batch simply went out again)."""
        if not arc_id:
            return False
        try:
            self.client.table("arc_batch_deliveries").upsert({
                "arc_id": str(arc_id),
                "user_id": str(user_id) if user_id else None,
                "coach_id": str(coach_id) if coach_id else None,
                "published_at": datetime.now(timezone.utc).isoformat(),
            }, on_conflict="arc_id").execute()
            return True
        except Exception as e:
            _e = str(e).lower()
            if "arc_batch_deliveries" in _e and (
                "does not exist" in _e or "pgrst" in _e
            ):
                logger.warning(
                    "mark_arc_batch_delivered: table missing (run "
                    "migrations/add_arc_batch_deliveries.sql) arc=%s", arc_id,
                )
                return False
            logger.warning("mark_arc_batch_delivered failed arc=%s: %s",
                           arc_id, e)
            return False

    def get_arc_batch_delivery(self, arc_id: Optional[str]) -> Optional[dict]:
        """The batch-delivery row for an arc, or None. None on missing table /
        error — the batch defaults to NOT delivered (the student view shows
        'waiting for your coach', never a phantom delivery)."""
        if not arc_id:
            return None
        try:
            res = (
                self.client.table("arc_batch_deliveries")
                .select("*")
                .eq("arc_id", str(arc_id))
                .limit(1)
                .execute()
            )
            rows = res.data or []
            return rows[0] if rows else None
        except Exception as e:
            _e = str(e).lower()
            if "arc_batch_deliveries" in _e and (
                "does not exist" in _e or "pgrst" in _e
            ):
                return None  # pre-migration → never delivered
            logger.warning("get_arc_batch_delivery failed arc=%s: %s",
                           arc_id, e)
            return None

    def list_arc_batch_deliveries(self, arc_ids: list) -> dict:
        """{arc_id: row} for the given arcs — ONE read for the trainings
        list (no per-arc N+1). {} on missing table / error (not delivered)."""
        ids = [str(a) for a in (arc_ids or []) if a]
        if not ids:
            return {}
        try:
            res = (
                self.client.table("arc_batch_deliveries")
                .select("*")
                .in_("arc_id", ids)
                .execute()
            )
            return {str(r.get("arc_id")): r for r in (res.data or [])
                    if r.get("arc_id")}
        except Exception as e:
            _e = str(e).lower()
            if "arc_batch_deliveries" in _e and (
                "does not exist" in _e or "pgrst" in _e
            ):
                return {}
            logger.warning("list_arc_batch_deliveries failed: %s", e)
            return {}

    # ── willab — Paid Audits / arc entitlement (BE chunk A1/A4/A5) ──────
    #
    # arc_purchases: one row per PAID/passed arc ("audit"). The row IS the
    # entitlement — take-1 is always free; a purchase unlocks take-2 feedback,
    # take-3, and the ideal-text report. Distinct from credits + user_audits.
    # See migrations/add_arc_purchases.sql.

    def get_arc_purchase(self, arc_id: Optional[str]) -> Optional[dict]:
        """The purchase row for an arc, or None. None on missing table /
        no purchase / error — never raises (entitlement defaults to NOT
        entitled, so a hiccup keeps the paywall up, never opens it)."""
        if not arc_id:
            return None
        try:
            res = (
                self.client.table("arc_purchases")
                .select("*")
                .eq("arc_id", str(arc_id))
                .limit(1)
                .execute()
            )
            rows = res.data or []
            return rows[0] if rows else None
        except Exception as e:
            err_low = str(e).lower()
            if "arc_purchases" in err_low and (
                "does not exist" in err_low or "pgrst" in err_low
                or "42p01" in err_low
            ):
                logger.warning(
                    "get_arc_purchase: table missing (run "
                    "migrations/add_arc_purchases.sql) arc=%s", arc_id,
                )
                return None
            logger.warning("get_arc_purchase failed arc=%s: %s", arc_id, e)
            return None

    def create_arc_purchase(
        self, arc_id: str, user_id: str, *,
        kind: str = "paid", source: str = "stripe",
        currency: Optional[str] = None, amount_minor: Optional[int] = None,
        stripe_session_id: Optional[str] = None,
    ) -> Optional[dict]:
        """Record a paid/passed arc. IDEMPOTENT: unique(arc_id) means a second
        purchase for the same arc (or a replayed stripe webhook on the same
        stripe_session_id) no-ops — on conflict we return the EXISTING row, so
        the caller treats a duplicate exactly like a fresh grant. Returns the
        row or None on real failure."""
        if not arc_id or not user_id:
            return None
        row = {
            "arc_id": str(arc_id), "user_id": str(user_id),
            "kind": kind, "source": source,
        }
        if currency:
            row["currency"] = str(currency).lower()
        if amount_minor is not None:
            try:
                row["amount_minor"] = int(amount_minor)
            except (TypeError, ValueError):
                pass
        if stripe_session_id:
            row["stripe_session_id"] = str(stripe_session_id)
        try:
            res = self.client.table("arc_purchases").insert(row).execute()
            created = (res.data or [None])[0]
            if created:
                return created
            return self.get_arc_purchase(arc_id)
        except Exception as e:
            err_low = str(e).lower()
            # Unique conflict (arc already purchased / replayed webhook) →
            # return the existing row; that's the idempotent success path.
            if (
                "duplicate" in err_low or "unique" in err_low
                or "23505" in err_low or "conflict" in err_low
            ):
                existing = self.get_arc_purchase(arc_id)
                if existing:
                    return existing
                # conflict was on stripe_session_id for a different arc — fall
                # through to a best-effort lookup by that session id.
                if stripe_session_id:
                    return self.get_arc_purchase_by_stripe_session(
                        stripe_session_id,
                    )
                return None
            if "arc_purchases" in err_low and (
                "does not exist" in err_low or "pgrst" in err_low
                or "42p01" in err_low
            ):
                logger.warning(
                    "create_arc_purchase: table missing (run "
                    "migrations/add_arc_purchases.sql) arc=%s", arc_id,
                )
                return None
            logger.warning("create_arc_purchase failed arc=%s: %s", arc_id, e)
            return None

    def create_arc_purchase_exclusive(
        self, arc_id: str, user_id: str, *,
        kind: str = "paid", source: str = "credits",
        credits_charged: Optional[int] = None,
    ) -> Optional[dict]:
        """Purpose-built for the credits unlock (2026-07-06): unlike
        ``create_arc_purchase`` (which returns the EXISTING row on a unique
        conflict — the right idempotent behavior for a replayed Stripe
        webhook), this returns None on ANY conflict, so the caller can tell
        "I just created the entitlement" from "someone else already has it" —
        the caller MUST NOT deduct credits unless this returns a fresh row
        (else a race could charge twice for one arc)."""
        if not arc_id or not user_id:
            return None
        row = {
            "arc_id": str(arc_id), "user_id": str(user_id),
            "kind": kind, "source": source,
        }
        if credits_charged is not None:
            try:
                row["credits_charged"] = int(credits_charged)
            except (TypeError, ValueError):
                pass
        try:
            res = self.client.table("arc_purchases").insert(row).execute()
            return (res.data or [None])[0]
        except Exception as e:
            err_low = str(e).lower()
            if "arc_purchases" in err_low and (
                "does not exist" in err_low or "pgrst" in err_low
                or "42p01" in err_low
            ):
                logger.warning(
                    "create_arc_purchase_exclusive: table missing (run "
                    "migrations/add_arc_purchases.sql) arc=%s", arc_id,
                )
            # Any conflict (unique(arc_id)) or other error → None, deliberately
            # (never the existing row) so the caller never double-charges.
            return None

    def get_arc_purchase_by_stripe_session(
        self, stripe_session_id: Optional[str],
    ) -> Optional[dict]:
        """Purchase row keyed by Stripe Checkout Session id (webhook
        idempotency lookup). None on missing/none/error."""
        if not stripe_session_id:
            return None
        try:
            res = (
                self.client.table("arc_purchases")
                .select("*")
                .eq("stripe_session_id", str(stripe_session_id))
                .limit(1)
                .execute()
            )
            rows = res.data or []
            return rows[0] if rows else None
        except Exception as e:
            logger.warning(
                "get_arc_purchase_by_stripe_session failed sid=%s: %s",
                stripe_session_id, e,
            )
            return None

    def mark_arc_delivered(self, arc_id: Optional[str]) -> bool:
        """Stamp delivered_at when the coach has delivered the arc's audit.
        Idempotent (sets only when NULL). Best-effort → False on any hiccup."""
        if not arc_id:
            return False
        now = datetime.now(timezone.utc).isoformat()
        try:
            res = (
                self.client.table("arc_purchases")
                .update({"delivered_at": now})
                .eq("arc_id", str(arc_id))
                .is_("delivered_at", "null")
                .execute()
            )
            return bool(res.data)
        except Exception as e:
            logger.warning("mark_arc_delivered failed arc=%s: %s", arc_id, e)
            return False

    # arc_invite_codes — founding free-pass codes (A4).

    def get_arc_invite_code(self, code: Optional[str]) -> Optional[dict]:
        """An invite code row, or None. None on missing table / unknown
        code / error."""
        if not code:
            return None
        try:
            res = (
                self.client.table("arc_invite_codes")
                .select("*")
                .eq("code", str(code).strip())
                .limit(1)
                .execute()
            )
            rows = res.data or []
            return rows[0] if rows else None
        except Exception as e:
            err_low = str(e).lower()
            if "arc_invite_codes" in err_low and (
                "does not exist" in err_low or "pgrst" in err_low
                or "42p01" in err_low
            ):
                logger.warning(
                    "get_arc_invite_code: table missing (run "
                    "migrations/add_arc_invite_codes.sql) code=%s", code,
                )
                return None
            logger.warning("get_arc_invite_code failed code=%s: %s", code, e)
            return None

    def consume_arc_invite_code(self, code: Optional[str]) -> bool:
        """Atomically claim ONE use of an active code with uses < max_uses.
        Guards on uses (conditional update) so two concurrent redeems can't
        over-spend a code. Returns True iff a use was claimed. Caller mints the
        purchase only on True."""
        if not code:
            return False
        row = self.get_arc_invite_code(code)
        if not row or not row.get("active"):
            return False
        try:
            uses = int(row.get("uses") or 0)
            max_uses = int(row.get("max_uses") or 0)
        except (TypeError, ValueError):
            return False
        if uses >= max_uses:
            return False
        try:
            # Conditional update: only bump when uses still equals what we read
            # (optimistic lock). A racing redeem changed uses → 0 rows → retry
            # is the caller's choice; here we just report no-claim.
            res = (
                self.client.table("arc_invite_codes")
                .update({"uses": uses + 1})
                .eq("code", str(code).strip())
                .eq("uses", uses)
                .eq("active", True)
                .execute()
            )
            return bool(res.data)
        except Exception as e:
            logger.warning("consume_arc_invite_code failed code=%s: %s", code, e)
            return False

    def create_arc_invite_code(
        self, code: str, *, max_uses: int = 1, note: Optional[str] = None,
    ) -> Optional[dict]:
        """Mint an invite code (admin/seed, A4). Idempotent: a re-run of the
        same code returns the existing row. None on real failure."""
        if not code:
            return None
        row = {"code": str(code).strip(), "max_uses": int(max_uses)}
        if note:
            row["note"] = str(note)
        try:
            res = self.client.table("arc_invite_codes").insert(row).execute()
            created = (res.data or [None])[0]
            return created or self.get_arc_invite_code(code)
        except Exception as e:
            err_low = str(e).lower()
            if (
                "duplicate" in err_low or "unique" in err_low
                or "23505" in err_low or "conflict" in err_low
            ):
                return self.get_arc_invite_code(code)
            logger.warning("create_arc_invite_code failed code=%s: %s", code, e)
            return None

    # ── willab — Audit Delivery (Prompt C §2/§3) ───────────────────────
    #
    # Coach-curated PDF audits, one row per uploaded PDF. Distinct from the
    # lab Readout ('audit_upload' sessions) — see migrations/add_user_audits.sql.


    def list_user_audits(self, user_id: str) -> list[dict]:
        """A user's audits, newest first. [] on missing table / none / error."""
        if not user_id:
            return []
        try:
            res = (
                self.client.table("user_audits")
                .select("id, name, audit_date, storage_path, created_at")
                .eq("user_id", user_id)
                .order("audit_date", desc=True)
                .execute()
            )
            return res.data or []
        except Exception as e:
            err_low = str(e).lower()
            if "user_audits" in err_low and (
                "does not exist" in err_low or "pgrst" in err_low
            ):
                return []
            logger.warning("list_user_audits failed user=%s: %s", user_id, e)
            return []

    def get_user_audit(self, audit_id: str, user_id: str) -> Optional[dict]:
        """One audit row, OWNERSHIP-scoped to user_id (None if not theirs)."""
        if not audit_id or not user_id:
            return None
        try:
            res = (
                self.client.table("user_audits")
                .select("id, name, audit_date, storage_path, created_at")
                .eq("id", audit_id)
                .eq("user_id", user_id)
                .limit(1)
                .execute()
            )
            return (res.data or [None])[0]
        except Exception as e:
            logger.warning("get_user_audit failed id=%s: %s", audit_id, e)
            return None

    # ── Confidence labels (founder 2026-07-28) ─────────────────────────
    # The corpus for the app's core function, keyed per RATER so agreement can
    # be measured without contaminating the product decision path.

    def upsert_confidence_label(
        self, *, snippet_id: str, row: dict, rater_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> bool:
        """Store (or replace) one rater's confidence call on one snippet.
        ``row`` is the validated shape from validate_confidence_label — this
        method does no validation of its own. Best-effort, missing-table-safe;
        NEVER raises."""
        if not snippet_id or not isinstance(row, dict):
            return False
        # FULL-STATE upsert: an omitted intensity CLEARS the stored one.
        # The FE saves yes/no first and the grade second, so a coach who
        # flips their answer sends {confident} alone — carrying the previous
        # answer's intensity forward would leave a 5 attached to a "no"
        # nobody graded. Stale training data is worse than absent training
        # data, so absence wins.
        payload: dict = {
            "snippet_id": str(snippet_id),
            "confident": bool(row.get("confident")),
            "source": row.get("source") or "coach",
            "intensity": row.get("intensity"),
            "note": row.get("note"),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if rater_id:
            payload["rater_id"] = str(rater_id)
        if session_id:
            payload["session_id"] = str(session_id)
        try:
            (self.client.table("confidence_labels")
                 .upsert(payload,
                         on_conflict="snippet_id,rater_id").execute())
            return True
        except Exception as e:
            err_low = str(e).lower()
            # 42P10: ON CONFLICT (snippet_id, rater_id) found no matching
            # unique constraint. The arbiter cannot match an expression
            # index, so a database still carrying the original
            # COALESCE-index shape of the migration fails every save here.
            if "42p10" in err_low or "on conflict" in err_low:
                logger.warning(
                    "upsert_confidence_label: unique constraint shape does "
                    "not match ON CONFLICT — re-run the current "
                    "migrations/add_confidence_labels.sql (it swaps the "
                    "expression index for a plain composite constraint)",
                )
                return False
            if "confidence_labels" in err_low and (
                "does not exist" in err_low or "pgrst" in err_low
                or "42p01" in err_low
            ):
                logger.warning(
                    "upsert_confidence_label: table missing (run "
                    "migrations/add_confidence_labels.sql)",
                )
                return False
            logger.warning("upsert_confidence_label failed snip=%s: %s",
                           snippet_id, e)
            return False

    def upsert_state_rating(
        self, *, snippet_id: str, row: dict, rater_id: Optional[str] = None,
        session_id: Optional[str] = None, lane: str = "coach",
        intensity: Optional[int] = None,
        model_version_at_time: Optional[str] = None,
        probe_score_at_time: Optional[float] = None,
        machine_value: Optional[str] = None,
        self_report: bool = False,
        selection: Optional[dict] = None,
    ) -> bool:
        """Store (or replace) one rater's TERNARY rating on one snippet
        (SPEC.md v3 §3.2). ``row`` is the validated shape from
        services.state_ratings.validate_rating — no validation happens here.

        Writes the SAME physical table as upsert_confidence_label
        (confidence_labels, extended by add_state_generic_ratings.sql), so the
        two instruments share the per-rater uniqueness and a coach who
        re-rates replaces their own row rather than doubling it.

        The legacy ``confident`` boolean is written alongside for continuity —
        yes/no map onto it, and NEUTRAL WRITES NULL. Neutral is the one answer
        the binary instrument could never express, so a null is the honest
        record; coercing it to false would fabricate a negative label, and
        every reader of that column already tolerates a null row.

        ``intensity`` is written ONLY when the caller passes it explicitly in
        the same request that carried the answer — i.e. a legacy body where
        both came from one judgment. It is never carried forward from a
        previous row: a stale 1-5 grade attached to an answer nobody graded is
        the failure the FULL-STATE upsert above exists to prevent, and absent
        training data beats wrong training data.

        ``machine_value`` is the model's PROPOSAL (rule 1, founder 2026-08-11)
        — the read that routed this clip to a rater. It lands in its own
        column BESIDE ``value`` and is never blended into it: the machine
        picks WHICH clip gets rated, it never holds one of the two votes.
        Callers pass it from services.label_quorum.machine_proposal, i.e.
        SERVER-SIDE off the stored acoustic read — never from a request body,
        because a client-supplied proposal would mean the rater's screen could
        have carried it (I1, and ``saw_model_output`` would be a lie).

        ``self_report`` marks the rater as the OWNER of the clip (rule 2).
        Excluded from the 2-peer quorum, kept for rater calibration. Distinct
        from ``lane='game_owner'``: lane records the surface, this records
        whose recording it was, and a coach rating their own session is a
        self-report on the coach lane.

        Best-effort, missing-column-safe; NEVER raises.

        ``selection`` is the K9 stamp (founder 2026-10-05, W6): the policy
        version, the reason and the sampling probability that put this clip
        in front of the rater, computed server-side, never shown before the
        judgment (services.coach_moments_queue.selection_stamp)."""
        if not snippet_id or not isinstance(row, dict):
            return False
        payload = self._rating_payload(
            snippet_id=snippet_id, row=row, rater_id=rater_id,
            session_id=session_id, lane=lane, intensity=intensity,
            model_version_at_time=model_version_at_time,
            probe_score_at_time=probe_score_at_time,
            machine_value=machine_value, self_report=self_report,
            selection=selection)
        try:
            (self.client.table("confidence_labels")
                 .upsert(payload,
                         on_conflict="snippet_id,rater_id").execute())
            # The append-only shadow (SPEC-immutable-provenance §3.2). AFTER
            # the upsert succeeds, never instead of it and never gating it:
            # confidence_labels remains the current-answer read, this is the
            # history the upsert destroys.
            self._append_label_revision(payload)
            return True
        except Exception as e:
            err_low = str(e).lower()
            # LEDGER COLUMNS MISSING -> RETRY WITHOUT THEM, don't lose the
            # rating. The migration lands on web boot (MIGRATE_ON_BOOT), so a
            # worker or a cron container can legitimately run this code for a
            # few seconds against the older schema. The human answer is the
            # irreplaceable half; the provenance stamps are re-derivable
            # (machine_value from the stored acoustic read, self_report from
            # ownership). Dropping the answer to protect a stamp is backwards.
            retried = self._retry_rating_without_stamps(
                payload, snippet_id, err_low)
            if retried is not None:
                return retried
            if ("column" in err_low and (
                    "state_id" in err_low or "unrateable" in err_low
                    or "question_version" in err_low or "lane" in err_low)):
                logger.warning(
                    "upsert_state_rating: ternary columns missing (run "
                    "migrations/add_state_generic_ratings.sql)",
                )
                return False
            if "42p10" in err_low or "on conflict" in err_low:
                logger.warning(
                    "upsert_state_rating: unique constraint shape does not "
                    "match ON CONFLICT — re-run "
                    "migrations/add_confidence_labels.sql",
                )
                return False
            logger.warning("upsert_state_rating failed snip=%s: %s",
                           snippet_id, e)
            return False

    def _rating_payload(
        self, *, snippet_id: str, row: dict, rater_id: Optional[str],
        session_id: Optional[str], lane: str, intensity: Optional[int],
        model_version_at_time: Optional[str],
        probe_score_at_time: Optional[float], machine_value: Optional[str],
        self_report: bool, selection: Optional[dict],
    ) -> dict:
        """One rating write's row, as ``upsert_state_rating`` and
        ``append_label_reconsideration`` both store it (see the former for
        what each column means)."""
        value = row.get("value")
        payload: dict = {
            "snippet_id": str(snippet_id),
            "state_id": row.get("state_id") or "confidence",
            "value": value,
            "unrateable": bool(row.get("unrateable")),
            "question_id": row.get("question_id"),
            "question_version": row.get("question_version"),
            "saw_model_output": bool(row.get("saw_model_output")),
            # Paired with saw_model_output and written the same way: what the
            # rater could see when they answered (founder 2026-09-24 put the
            # slide on the coach's blind screen). It is a STAMP, so it joins
            # the ledger-column retry below rather than being allowed to take
            # a rating down with it — see that handler for why.
            "saw_slide": bool(row.get("saw_slide")),
            "latency_ms": row.get("latency_ms"),
            "note": row.get("note"),
            "lane": lane,
            # `source` predates `lane` and several readers still filter on it.
            # Both bootstrap and coach lanes ARE the coach rating; the lane
            # column is what separates them.
            "source": "coach" if lane in ("bootstrap", "coach") else "game",
            "confident": (True if value == "yes"
                          else False if value == "no" else None),
            # FULL-STATE, like the binary upsert: an omitted intensity CLEARS
            # the stored one rather than carrying the previous answer's grade
            # onto a new answer.
            "intensity": intensity,
            # Rule 2. Always written, never inferred at read time — an
            # unstamped row would fall back to the lane, which is right for
            # the game and wrong for every other surface.
            "self_report": bool(self_report),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if rater_id:
            payload["rater_id"] = str(rater_id)
            # Task 4 (0411): a coach's rating is blind unless this coach saw
            # the clip's non-blind side first; the stamp is computed here,
            # from the exposure record, never sent by a client. A row
            # stamped not blind counts for no quorum, no Album leg and no
            # measure. Game raters have no exposure record: always blind.
            if lane in ("bootstrap", "coach") and not self_report:
                from services.coach_exposure import rating_is_blind
                payload["blind"] = rating_is_blind(
                    self, coach_id=str(rater_id), snippet_id=str(snippet_id))
        if session_id:
            payload["session_id"] = str(session_id)
        if model_version_at_time:
            payload["model_version_at_time"] = str(model_version_at_time)
        if probe_score_at_time is not None:
            payload["probe_score_at_time"] = float(probe_score_at_time)
        # Rule 1: a proposal outside the perceptual domain is dropped rather than
        # coerced. The column's CHECK would reject it and take the whole
        # RATING down with it — the human answer is the thing worth saving.
        if machine_value in ("yes", "in_between", "no"):
            payload["machine_value"] = machine_value
        payload.update(_selection_columns(selection))
        return payload

    def append_label_reconsideration(
        self, *, snippet_id: str, row: dict, rater_id: str,
        session_id: Optional[str] = None, lane: str = "coach",
        intensity: Optional[int] = None,
        machine_value: Optional[str] = None,
        self_report: bool = False,
        selection: Optional[dict] = None,
    ) -> Optional[dict]:
        """A coach's later answer on a clip they already judged (LOCKIN
        §5c; contract 34; W6 2026-10-05): appended to ``label_revision`` as a
        reconsideration, superseding the newest revision of the same
        (snippet, rater, state), and NEVER written over the original
        judgment in ``confidence_labels``. Raises on failure: the route
        names it rather than report a revision it did not keep."""
        payload = self._rating_payload(
            snippet_id=snippet_id, row=row, rater_id=rater_id,
            session_id=session_id, lane=lane, intensity=intensity,
            model_version_at_time=None, probe_score_at_time=None,
            machine_value=machine_value, self_report=self_report,
            selection=selection)
        state_id = payload.get("state_id") or "confidence"
        prior = (self.client.table("label_revision").select("id")
                 .eq("snippet_id", str(snippet_id)).eq("state_id", state_id)
                 .eq("rater_id", str(rater_id))
                 .order("id", desc=True).limit(1).execute())
        revision = self._label_revision_row(payload)
        revision["reconsideration"] = True
        revision["supersedes_id"] = (prior.data or [{}])[0].get("id")
        res = self.client.table("label_revision").insert(revision).execute()
        return (res.data or [None])[0]

    def _retry_rating_without_stamps(
        self, payload: dict, snippet_id: str, err_low: str,
    ) -> Optional[bool]:
        """Re-send a rating whose PROVENANCE STAMPS the schema does not have.

        Returns None when the error was not a missing stamp column, so the
        caller keeps its own handlers; True/False when this path owned it.

        WHY IT IS A RETRY AND NOT A FAILURE. The migration lands on web boot
        (MIGRATE_ON_BOOT), so a worker or cron container legitimately runs this
        code against the older schema for a few seconds. The human answer is
        the irreplaceable half of the write; the stamps are re-derivable
        (machine_value from the stored acoustic read, self_report from
        ownership). Dropping the answer to protect a stamp is backwards.

        `saw_slide` joined them on 2026-09-24 with the founder's override of
        the blind-coach fence. What is lost when it is dropped is the ability
        to tell WHICH INSTRUMENT collected the row — voice alone, or voice and
        slide — so this logs loudly rather than quietly: a run of these means
        the migration has not landed and the corpus is mixing.

        Its own method because the caller is at the complexity ratchet's
        ceiling and adding the third column name tipped it over. The retry is
        one self-contained concern, so it is the right piece to lift out.
        """
        stamps = ("machine_value", "self_report", "saw_slide", "blind",
                  *SELECTION_COLUMNS)
        if not any(name in err_low for name in stamps):
            return None
        if "column" not in err_low and "pgrst204" not in err_low:
            return None
        logger.warning(
            "upsert_state_rating: stamp columns missing (run "
            "migrations/add_label_quorum_ledger.sql or "
            "the_rater_says_what_they_could_see.sql) — retrying without "
            "them snip=%s", snippet_id,
        )
        for name in stamps:
            payload.pop(name, None)
        try:
            (self.client.table("confidence_labels")
                 .upsert(payload, on_conflict="snippet_id,rater_id").execute())
            self._append_label_revision(payload)
            return True
        except Exception as retry_err:
            logger.warning("upsert_state_rating retry failed snip=%s: %s",
                           snippet_id, retry_err)
            return False

    @staticmethod
    def _label_revision_row(payload: dict) -> dict:
        """One ``label_revision`` row from a rating write's row (§3.2)."""
        row = {
            "snippet_id": payload["snippet_id"],
            "rater_id": payload.get("rater_id"),
            "state_id": payload.get("state_id") or "confidence",
            "value": payload.get("value"),
            "unrateable": bool(payload.get("unrateable")),
            "confident": payload.get("confident"),
            "intensity": payload.get("intensity"),
            "note": payload.get("note"),
            "lane": payload.get("lane"),
            "source": payload.get("source"),
            "question_id": payload.get("question_id"),
            "question_version": payload.get("question_version"),
            "saw_model_output": bool(payload.get("saw_model_output")),
            # Same stamp, same reason: the revision is the only record of
            # what the upsert replaced, so it must say which instrument
            # collected the row it is shadowing.
            "saw_slide": bool(payload.get("saw_slide")),
            "latency_ms": payload.get("latency_ms"),
            "session_id": payload.get("session_id"),
            "model_version_at_time": payload.get("model_version_at_time"),
            "probe_score_at_time": payload.get("probe_score_at_time"),
            # Ledger provenance (rules 1/2). The CURRENT row keeps only
            # the latest stamps, so without these the machine proposal a
            # rater actually disagreed with is lost the moment they
            # re-rate — which is exactly the row active learning wants.
            "machine_value": payload.get("machine_value"),
            "self_report": bool(payload.get("self_report")),
            "origin": "live",
            # The judgment's own timestamp — created_at is the INSERT's.
            "rated_at": payload.get("updated_at"),
        }
        # K9 (W6): why the clip was in front of the rater, where stamped.
        row.update({k: payload[k] for k in SELECTION_COLUMNS if k in payload})
        return row

    def _append_label_revision(self, payload: dict) -> None:
        """Append ONE revision row shadowing a rating write (§3.2).

        Coach labels are overwritten in place by design (the corpus wants the
        rater's CURRENT answer); this is the only record of what the upsert
        replaced. Nothing here is ever updated or deleted.

        `supersedes_id` is best-effort: the newest prior revision for the
        same (snippet, rater, state), NULL when the lookup fails or nothing
        precedes it. A missing pointer degrades to "order by id" — the chain
        is a convenience, the append is the guarantee.

        NEVER raises, and a failure never un-succeeds the rating write it
        shadows — the table may simply not be migrated yet (0258).
        """
        try:
            state_id = payload.get("state_id") or "confidence"
            rater_id = payload.get("rater_id")
            prev_id = None
            try:
                q = (self.client.table("label_revision").select("id")
                     .eq("snippet_id", payload["snippet_id"])
                     .eq("state_id", state_id))
                q = (q.eq("rater_id", rater_id) if rater_id
                     else q.is_("rater_id", "null"))
                res = q.order("id", desc=True).limit(1).execute()
                if res.data:
                    prev_id = res.data[0].get("id")
            except Exception:
                pass
            row = self._label_revision_row(payload)
            row["supersedes_id"] = prev_id
            self.client.table("label_revision").insert(row).execute()
        except Exception as e:
            err_low = str(e).lower()
            if "label_revision" in err_low and (
                    "does not exist" in err_low or "42p01" in err_low
                    or "pgrst" in err_low):
                logger.warning(
                    "label_revision: table missing (run "
                    "migrations/add_label_revision.sql) — rating saved, "
                    "revision NOT recorded")
                return
            logger.warning("_append_label_revision failed snip=%s: %s",
                           payload.get("snippet_id"), e)

    def record_dimension_evaluations(self, rows: list) -> int:
        """Store drift-monitoring evaluations (SPEC D26/D30, Appendix G).

        One row per (snippet, dimension, benchmark_version). Returns the
        number written; 0 on any failure.

        AC-9: nothing written here is user-facing. It feeds PSI and the
        p-chart, which are an INTERNAL audit surface.

        THREE STATES, and conflating any two of them corrupts the monitor:

            computed AND benchmarked   fired=True/False  insufficient=False
            computed, NO benchmark     fired=None        insufficient=False
            not computable             fired=None        insufficient=True

        The middle state is most of what exists today — wpm, pause_ms,
        dynamic_db, pitch_center and energy are measured on every snippet and
        none has a fire threshold in code yet. Those rows are still worth
        storing: PSI reads `decile`, not `fired`.

        So `fired` is passed through as None unless a real decision was made,
        and is forced to None whenever `insufficient_data` is set. Writing
        False for either of the other two states would book a decision nobody
        made, deflating every fire rate and leaving the monitor calm exactly
        when data goes missing.

        Best-effort, missing-column-safe; NEVER raises. Drift telemetry must
        never be able to break the scoring path it observes.
        """
        if not rows:
            return 0
        payload = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            if not row.get("dimension_id"):
                continue
            if not (row.get("snippet_id") or row.get("recording_id")
                    or row.get("session_id")):
                continue          # ck_dimension_evaluations_has_anchor
            insufficient = bool(row.get("insufficient_data"))
            fired = row.get("fired")
            # None stays None: "no benchmark defined" is a real state, not a
            # negative decision. Only an explicit bool becomes a decision.
            decision = None if (insufficient or fired is None) else bool(fired)
            # A SNIPPET-GRAIN ROW DOES NOT ALSO CLAIM THE RECORDING GRAIN
            # (23505, found in production 2026-08-12 the moment the error
            # handler above started printing real codes):
            #
            #   Key (recording_id, dimension_id, benchmark_version)
            #     = (97d982ea…, wpm, measure-v1) already exists.
            #   violates unique constraint "uq_dimension_evaluations_rec_dim_ver"
            #
            # `_windowed_rate_rows` sets snippet_id AND recording_id, so seven
            # windows of one recording produce seven rows sharing a
            # (recording_id, dimension_id, benchmark_version). The upsert's
            # arbiter names the SNIPPET index, so Postgres never treats the
            # recording-grain violation as a conflict to resolve — it raises,
            # and a best-effort writer swallows it. That is why this table
            # kept staying empty.
            #
            # 0249 already designed the way out: storage is SNIPPET grain
            # ("ANALYSIS must aggregate to session grain first"), and the
            # recording-grain index is PARTIAL — `WHERE recording_id IS NOT
            # NULL`. That partiality only does its job if snippet-grain rows
            # leave the column NULL, which is what this does. The row keeps
            # its anchor (ck_dimension_evaluations_has_anchor is satisfied by
            # snippet_id) and its session_id, which is the grain every reader
            # actually uses: `get_dimension_evaluations_since` does not select
            # recording_id at all, and the drift job aggregates to session
            # before it computes anything.
            #
            # Rows already written keep their recording_id. Backfilling would
            # rewrite historical calculations to fit a later understanding —
            # the one thing the founder's immutability rule forbids — and no
            # reader needs it.
            _snip = row.get("snippet_id")
            entry = {
                "snippet_id": _snip,
                "recording_id": None if _snip else row.get("recording_id"),
                "session_id": row.get("session_id"),
                "user_id": row.get("user_id"),
                "dimension_id": str(row["dimension_id"]),
                "raw_value": row.get("raw_value"),
                "decile": row.get("decile"),
                "fired": decision,
                "insufficient_data": insufficient,
                "benchmark_tier": row.get("benchmark_tier") or "CORPUS_REL",
                "benchmark_version": str(row.get("benchmark_version") or "v0"),
                "window_class": row.get("window_class"),
                "n_units": row.get("n_units"),
            }
            # The provenance stamp (SPEC-immutable-provenance §3.1): which
            # detector definition produced this number, and whether the live
            # code still hashed to it at write time. {} for dimensions with
            # no registered detector, or while detector_version is absent —
            # an unstamped row is the honest pre-provenance NULL.
            try:
                from services.provenance_check import stamp
                entry.update(stamp(entry["dimension_id"]))
            except Exception:
                pass          # the stamp must never break the write it rides
            payload.append(entry)
        if not payload:
            return 0
        # PostgREST upserts are all-or-nothing per batch: since every row in
        # a batch is built the same way, a payload either uniformly carries
        # the stamp keys or uniformly does not.
        stamped = any("provenance" in p for p in payload)
        try:
            (self.client.table("dimension_evaluations")
                 .upsert(payload,
                         on_conflict="snippet_id,dimension_id,benchmark_version")
                 .execute())
            return len(payload)
        except Exception as e:
            err_low = str(e).lower()
            # 0257 not applied yet but detector_version somehow readable (or
            # a schema cache lag): retry WITHOUT the stamp rather than losing
            # the measurements. Losing telemetry to the stamp would invert
            # the priority — provenance exists to protect the data, not to
            # gate it.
            if stamped and "column" in err_low and (
                    "provenance" in err_low or "detector_version" in err_low):
                logger.warning(
                    "record_dimension_evaluations: provenance columns missing "
                    "(run migrations/add_detector_version.sql) — writing "
                    "unstamped")
                for p in payload:
                    p.pop("provenance", None)
                    p.pop("detector_version", None)
                try:
                    (self.client.table("dimension_evaluations")
                         .upsert(payload,
                                 on_conflict=("snippet_id,dimension_id,"
                                              "benchmark_version"))
                         .execute())
                    return len(payload)
                except Exception as e2:
                    logger.warning(
                        "record_dimension_evaluations failed: %s", e2)
                    return 0
            # THE ERROR IS THE ERROR (2026-08-12). This branch used to read
            #
            #     if "does not exist" in err_low or "dimension_evaluations" in err_low
            #
            # — a substring match on the TABLE'S OWN NAME, which every
            # PostgREST error about this table contains. So a stale schema
            # cache (PGRST204, "could not find the 'snippet_id' column … in
            # the schema cache"), a bad arbiter (42P10) and a genuinely absent
            # table all printed the same sentence: "table/columns missing (run
            # …)". It sent a full afternoon after two migrations that had been
            # applied the whole time, on a table holding 145 rows.
            #
            # A best-effort writer swallows its failures by design (see the
            # docstring), so this log line is the ONLY thing that will ever
            # say why the table stopped filling. It has to say the true thing.
            # The migration hint survives, narrowed to the codes that actually
            # mean the object is absent.
            code = _pg_error_code(e)
            missing = code in _MISSING_OBJECT_CODES or (
                not code and "does not exist" in err_low)
            if missing:
                logger.warning(
                    "record_dimension_evaluations: %s — object missing (run "
                    "migrations/add_dimension_evaluations.sql then "
                    "add_dimension_evaluations_snippet_grain.sql; if those are "
                    "applied, the PostgREST schema cache is stale — "
                    "NOTIFY pgrst, 'reload schema')", code or "no code")
                return 0
            logger.warning("record_dimension_evaluations failed [%s]: %s",
                           code or "no code", e)
            return 0

    def record_intervention_arms(self, rows: list) -> int:
        """Store the manager engine's experiment arms (PM-8, Appendix H.12).

        One row per (session, dimension) CONSIDERED. Returns the number
        written; 0 on any failure. Best-effort and NEVER raises — the same
        rule as the drift telemetry: a recorder must not break the thing it
        records.

        THAT SWALLOW IS WHY THE CONTRACT IS TESTED STATICALLY. Twice on
        2026-08-06 a schema/code mismatch made every write fail silently and
        the table simply stayed empty — a partial index used as an ON CONFLICT
        arbiter (42P10), then an INTEGER column handed a fraction (22P02).
        `test_upsert_arbiters` and `test_schema_column_types` cover both
        shapes for this table too; nothing at runtime will ever complain.

        AC-9: internal only. Arm assignments and priority values are
        arbitration inputs and must never reach a client-facing schema.
        """
        if not rows:
            return 0
        payload = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            if not row.get("session_id") or not row.get("dimension_id"):
                continue
            arm = str(row.get("arm") or "")
            if arm not in ("CONTROL", "WITHHELD", "EXPLORE",
                           "TREATED", "NOT_SELECTED"):
                continue          # ck_intervention_arms_arm
            surfaced = bool(row.get("surfaced"))
            # Keep the CHECK satisfied here rather than letting Postgres
            # reject the whole batch: a caller bug must cost one row, not the
            # entire session's record.
            if surfaced != (arm in ("TREATED", "EXPLORE")):
                continue          # ck_intervention_arms_surfaced_agrees
            payload.append({
                "session_id": str(row["session_id"]),
                "user_id": row.get("user_id"),
                "dimension_id": str(row["dimension_id"]),
                "arm": arm,
                "priority": row.get("priority"),
                "would_have_surfaced": row.get("would_have_surfaced"),
                "surfaced": surfaced,
                "form": row.get("form"),
                "control_salt": row.get("control_salt"),
                "withhold_salt": row.get("withhold_salt"),
                "gamma": row.get("gamma"),
                "withhold_rate": row.get("withhold_rate"),
                "exploration_rate": row.get("exploration_rate"),
            })
        if not payload:
            return 0
        try:
            (self.client.table("intervention_arms")
                 .upsert(payload, on_conflict="session_id,dimension_id")
                 .execute())
            return len(payload)
        except Exception as e:
            err_low = str(e).lower()
            if "does not exist" in err_low or "intervention_arms" in err_low:
                logger.warning(
                    "record_intervention_arms: table/columns missing (run "
                    "migrations/add_intervention_arms.sql)",
                )
                return 0
            logger.warning("record_intervention_arms failed: %s", e)
            return 0

    def get_dimension_evaluations_since(self, *, weeks: int = 4,
                                        limit: int = 50000) -> list:
        """Evaluation rows for the drift job. [] on anything missing.

        Returns raw rows; SESSION-GRAIN AGGREGATION IS THE CALLER'S JOB and is
        not optional — snippets inside a session are not independent, and
        counting thirty of them as thirty observations narrows the p-chart's
        control limits by ~sqrt(30) and makes the monitor fire on its own
        sampling. services.drift_job does it.
        """
        try:
            from datetime import timedelta
            since = (datetime.now(timezone.utc)
                     - timedelta(weeks=int(weeks))).isoformat()
            res = (self.client.table("dimension_evaluations")
                   .select("session_id, dimension_id, raw_value, fired, "
                           "benchmark_tier, benchmark_version, "
                           "insufficient_data, evaluated_at")
                   .gte("evaluated_at", since)
                   .limit(int(limit)).execute())
            return res.data or []
        except Exception as e:
            logger.warning("get_dimension_evaluations_since failed: %s", e)
            return []

    def get_reference_distribution(self, version: str = "frozen_v1") -> list:
        """The frozen PSI baseline. [] when it has not been minted yet, which
        is a normal early state, not an error."""
        try:
            res = (self.client.table("reference_distribution")
                   .select("dimension_id, decile, pct, upper_bound, n_at_freeze")
                   .eq("version", str(version)).execute())
            return res.data or []
        except Exception as e:
            logger.warning("get_reference_distribution failed: %s", e)
            return []

    def insert_reference_distribution(self, rows: list) -> int:
        """Mint a frozen reference. Returns rows written; 0 on failure.

        NEVER UPDATES. reference_distribution blocks UPDATE by trigger — a
        reference recomputed on a rolling window tracks the drift it exists to
        detect, PSI reads ~0 forever, and the monitor becomes decorative WHILE
        APPEARING TO WORK. A refit inserts a new `version`.
        """
        if not rows:
            return 0
        try:
            (self.client.table("reference_distribution")
                 .insert(rows).execute())
            return len(rows)
        except Exception as e:
            err = str(e).lower()
            if "duplicate" in err or "unique" in err or "23505" in err:
                logger.info("insert_reference_distribution: version already "
                            "minted — refusing to overwrite a frozen "
                            "reference (this is the trigger doing its job)")
                return 0
            logger.warning("insert_reference_distribution failed: %s", e)
            return 0

    def refresh_clip_answer_counts(self, snippet_id: str) -> Optional[dict]:
        """Rebuild one clip's soft-label counts from the ledger (migration
        0442, V4 brief 1.7): the database function counts only the quorum's
        human lanes, never a self-report, never the machine. Returns the row.
        Raises on failure: the caller (services.clip_answer_counts.refresh)
        logs it and the rating stands."""
        result = self.client.rpc("refresh_clip_answer_counts_v1",
                                 {"p_snippet_id": str(snippet_id)}).execute()
        return self._rpc_row(result.data)

    def get_confidence_labels_by_snippet_ids(self, snippet_ids: list, *,
                                             strict: bool = False) -> dict:
        """{snippet_id: [label rows]} for the given snippets. {} on anything
        missing — the queue then renders every piece as unlabelled.
        ``strict=True`` re-raises a failed read instead."""
        ids = [str(s) for s in (snippet_ids or []) if s]
        if not ids:
            return {}
        try:
            rows = (self.client.table("confidence_labels")
                    .select("*").in_("snippet_id", ids).execute().data) or []
            out: dict = {}
            for r in rows:
                out.setdefault(str(r.get("snippet_id")), []).append(r)
            return out
        except Exception as e:
            logger.warning("get_confidence_labels_by_snippet_ids failed: %s", e)
            if strict:
                raise
            return {}

    def get_own_state_ratings_for_session(self, session_id: str,
                                          rater_id: str) -> dict:
        """{snippet_id: {value, unrateable}} — THIS rater's own ratings only.

        SCOPED TO ONE RATER ON PURPOSE, and that scope is the whole safety
        argument. Showing a coach their OWN prior answer is just resuming
        their work. Showing them ANOTHER rater's would anchor the next label
        and quietly destroy the independence that makes multi-rater agreement
        mean anything — the same reason the labeler card shows no machine
        read. A future "what did the panel say" surface is a different
        endpoint with a different audience, never this one.

        {} on anything missing, so the card renders every snippet as
        unanswered rather than failing the whole review read.
        """
        if not session_id or not rater_id:
            return {}
        try:
            rows = (self.client.table("confidence_labels")
                    .select("snippet_id, value, unrateable")
                    .eq("session_id", str(session_id))
                    .eq("rater_id", str(rater_id))
                    .execute().data) or []
            out: dict = {}
            for r in rows:
                snippet_id = r.get("snippet_id")
                if not snippet_id:
                    continue
                out[str(snippet_id)] = {
                    "value": r.get("value"),
                    "unrateable": bool(r.get("unrateable")),
                }
            return out
        except Exception as e:
            logger.warning(
                "get_own_state_ratings_for_session failed session=%s: %s",
                session_id, e)
            return {}

    def count_labelled_snippets_by_session_ids(self, session_ids: list) -> dict:
        """{session_id: how many DISTINCT snippets carry a confidence label}.

        The corpus index's "how much is labelled" badge (FE 2026-07-30) —
        one batched query for the whole list, where the FE's fallback costs
        one queue request per row. DISTINCT snippets, not label rows: two
        raters on one piece is still one labelled piece. {} on anything
        missing — the badge then falls back to the FE's queue read."""
        ids = [str(s) for s in (session_ids or []) if s]
        if not ids:
            return {}
        try:
            rows = (self.client.table("confidence_labels")
                    .select("session_id, snippet_id")
                    .in_("session_id", ids).execute().data) or []
            seen: dict = {}
            for r in rows:
                sid, snip = r.get("session_id"), r.get("snippet_id")
                if sid and snip:
                    seen.setdefault(str(sid), set()).add(str(snip))
            return {sid: len(snips) for sid, snips in seen.items()}
        except Exception as e:
            logger.warning(
                "count_labelled_snippets_by_session_ids failed: %s", e)
            return {}

    def get_confidence_label_corpus(self, *, source: Optional[str] = None,
                                    limit: int = 5000) -> list:
        """The training-side pull, newest first. [] on anything missing."""
        try:
            q = self.client.table("confidence_labels").select("*")
            if source:
                q = q.eq("source", str(source))
            return (q.order("created_at", desc=True)
                     .limit(int(limit)).execute().data) or []
        except Exception as e:
            logger.warning("get_confidence_label_corpus failed: %s", e)
            return []

    # ── Peer-review validation loop (founder 2026-08-03) ───────────────
    # A user/peer flags whether the AI's confidence choice was right. SEPARATE
    # table from confidence_labels on purpose: these are NON-BLIND (the
    # reviewer saw the AI's call first), and blending them indistinguishably
    # with the blind coach corpus would let the model grade its own homework.
    # See services/confidence_reviews.py + add_snippet_confidence_reviews.sql.

    def upsert_snippet_confidence_review(
        self, *, snippet_id: str, reviewer_user_id: str, ai_correct: bool,
        model_version: Optional[str] = None,
    ) -> bool:
        """Store (or REPLACE) one reviewer's flag on one snippet.

        Replace-on-reflag: (snippet_id, reviewer_user_id) is unique, so a
        reviewer who changes their mind updates their row rather than stacking
        a second one — duplicate rows from one rater are junk labels (the same
        N3 rule the voice game follows). Other reviewers' rows are untouched,
        so peer agreement stays computable.

        ``ai_correct`` is already a validated real boolean by the time it gets
        here (services/confidence_reviews.validate_confidence_review); this
        method does no validation of its own. Best-effort, missing-table-safe;
        NEVER raises."""
        if not snippet_id or not reviewer_user_id:
            return False
        payload: dict = {
            "snippet_id": str(snippet_id),
            "reviewer_user_id": str(reviewer_user_id),
            "ai_correct": bool(ai_correct),
            "model_version": model_version,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            (self.client.table("snippet_confidence_reviews")
                 .upsert(payload,
                         on_conflict="snippet_id,reviewer_user_id").execute())
            return True
        except Exception as e:
            err_low = str(e).lower()
            # 42P10: ON CONFLICT found no matching unique constraint — the
            # composite UNIQUE in the migration has not been applied.
            if "42p10" in err_low or "on conflict" in err_low:
                logger.warning(
                    "upsert_snippet_confidence_review: unique constraint does "
                    "not match ON CONFLICT — run "
                    "migrations/add_snippet_confidence_reviews.sql",
                )
                return False
            if "snippet_confidence_reviews" in err_low and (
                "does not exist" in err_low or "pgrst" in err_low
                or "42p01" in err_low
            ):
                logger.warning(
                    "upsert_snippet_confidence_review: table missing (run "
                    "migrations/add_snippet_confidence_reviews.sql)",
                )
                return False
            logger.warning("upsert_snippet_confidence_review failed snip=%s: %s",
                           snippet_id, e)
            return False

    def get_snippet_confidence_reviews(self, *, limit: int = 5000) -> list:
        """The peer-review corpus pull, newest first. [] on anything missing —
        the trace then reports zero peer_review rows rather than erroring."""
        try:
            return (self.client.table("snippet_confidence_reviews")
                    .select("snippet_id, reviewer_user_id, ai_correct, "
                            "model_version, created_at")
                    .order("created_at", desc=True)
                    .limit(int(limit)).execute().data) or []
        except Exception as e:
            err_low = str(e).lower()
            if "snippet_confidence_reviews" in err_low and (
                "does not exist" in err_low or "pgrst" in err_low
                or "42p01" in err_low
            ):
                return []
            logger.warning("get_snippet_confidence_reviews failed: %s", e)
            return []

    # ── Confident Voice → Voice Album routing (owner only) ───────────

    def upsert_owner_voice_album_route(
        self, *, snippet_id: str, owner_user_id: str, arc_id: str,
        response: str, slide_index: Optional[int] = None,
        model_version: Optional[str] = None,
    ) -> bool:
        """Persist routing only; never write a label or learning corpus.

        Accepts the instrument's five states (contract §29) plus the two
        legacy values. Since F-4 (2026-09-28) the Take-review route sends the
        answer itself; the legacy pair is still minted by one live route,
        ``PUT /v2/user/snippets/<id>/confidence-agree`` (a ternary instrument
        with no frontend caller), so narrowing this check is a founder
        decision about that route, not a hygiene fix. Widening the column's
        CHECK is
        ``migrations/widen_owner_voice_album_routing_to_five_states.sql``.
        """
        from services.voice_album_routing import FIVE_STATES
        if (not snippet_id or not owner_user_id or not arc_id
                or response not in FIVE_STATES + ("neutral", "unrateable")):
            return False
        payload = {
            "snippet_id": str(snippet_id),
            "owner_user_id": str(owner_user_id),
            "arc_id": str(arc_id),
            "response": response,
            "slide_index": (slide_index if isinstance(slide_index, int)
                            and not isinstance(slide_index, bool) else None),
            "model_version": model_version,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            (self.client.table("owner_voice_album_routing")
             .upsert(payload,
                     on_conflict="snippet_id,owner_user_id").execute())
            return True
        except Exception as e:
            err_low = str(e).lower()
            if "owner_voice_album_routing" in err_low and (
                    "does not exist" in err_low or "pgrst" in err_low
                    or "42p01" in err_low):
                logger.warning(
                    "owner Voice Album routing table missing (run "
                    "migrations/add_owner_voice_album_routing.sql)")
                return False
            logger.warning(
                "upsert_owner_voice_album_route failed snip=%s: %s",
                snippet_id, e)
            return False

    def list_owner_voice_album_routes(self, arc_id: str, *,
                                      strict: bool = False) -> list:
        """Current owner routing responses for one arc; [] pre-migration.
        ``strict=True`` re-raises any other failed read."""
        if not arc_id:
            return []
        try:
            return (
                self.client.table("owner_voice_album_routing")
                .select("snippet_id, owner_user_id, arc_id, slide_index, response, "
                        "updated_at")
                .eq("arc_id", str(arc_id))
                .execute().data
            ) or []
        except Exception as e:
            err_low = str(e).lower()
            if "owner_voice_album_routing" in err_low and (
                    "does not exist" in err_low or "pgrst" in err_low
                    or "42p01" in err_low):
                return []
            logger.warning(
                "list_owner_voice_album_routes failed arc=%s: %s", arc_id, e)
            if strict:
                raise
            return []

    def get_confidence_rereview(self, snippet_id: str) -> Optional[dict]:
        """Current operational second-listen state for one snippet."""
        try:
            rows = (self.client.table("confidence_rereview_queue")
                    .select("*").eq("snippet_id", str(snippet_id))
                    .limit(1).execute().data) or []
            return rows[0] if rows else None
        except Exception as e:
            if "confidence_rereview_queue" not in str(e).lower():
                logger.warning("get_confidence_rereview failed: %s", e)
            return None

    def upsert_confidence_rereview(
        self, *, snippet_id: str, session_id: str, arc_id: str,
        owner_user_id: str,
    ) -> bool:
        """Request a second listen. Idempotent while already pending."""
        try:
            now = datetime.now(timezone.utc).isoformat()
            (self.client.table("confidence_rereview_queue").upsert({
                "snippet_id": str(snippet_id),
                "session_id": str(session_id),
                "arc_id": str(arc_id),
                "owner_user_id": str(owner_user_id),
                "status": "pending",
                "coach_note": None,
                "resolved_at": None,
                "updated_at": now,
            }, on_conflict="snippet_id").execute())
            return True
        except Exception as e:
            logger.warning("upsert_confidence_rereview failed: %s", e)
            return False

    def resolve_confidence_rereview(
        self, snippet_id: str, *, confirmed_no: bool = False,
        coach_note: Optional[str] = None,
    ) -> bool:
        """Resolve a pending second listen, or remove it after agreement."""
        try:
            query = self.client.table("confidence_rereview_queue")
            if not confirmed_no:
                query.delete().eq("snippet_id", str(snippet_id)).execute()
                return True
            now = datetime.now(timezone.utc).isoformat()
            (query.update({
                "status": "confirmed_no",
                "coach_note": ((coach_note or "").strip() or None),
                "resolved_at": now,
                "updated_at": now,
            }).eq("snippet_id", str(snippet_id)).execute())
            return True
        except Exception as e:
            logger.warning("resolve_confidence_rereview failed: %s", e)
            return False

    def list_pending_confidence_rereviews(self, session_id: str) -> list:
        """Pending second listens for a session, oldest request first."""
        try:
            return ((self.client.table("confidence_rereview_queue")
                     .select("*").eq("session_id", str(session_id))
                     .eq("status", "pending").order("requested_at")
                     .execute().data) or [])
        except Exception as e:
            if "confidence_rereview_queue" not in str(e).lower():
                logger.warning(
                    "list_pending_confidence_rereviews failed: %s", e)
            return []
    # ── Coach star verdicts (founder 2026-07-27) ───────────────────────
    # The DECISION-layer correction corpus for the voice-text analytics: did
    # this star deserve to fire, and as this kind? Separate from
    # confidence-labeling by fence — see services/star_verdicts.py. Never
    # surfaced to a student (AC-9).

    def upsert_star_verdict(
        self, *, snippet_id: str, row: dict, session_id: Optional[str] = None,
        arc_id: Optional[str] = None, coach_user_id: Optional[str] = None,
    ) -> bool:
        """Store (or replace) the coach's judgment of ONE fired star.

        ``row`` is the validated shape from star_verdicts.validate_verdict —
        this method does no validation of its own so there is exactly one
        place that decides what a legal verdict is. Upsert on snippet_id: a
        re-judgment replaces, because the corpus wants the coach's current
        view, not their deliberation history.

        Best-effort, missing-table-safe; NEVER raises."""
        if not snippet_id or not isinstance(row, dict) or not row.get("verdict"):
            return False
        payload: dict = {"snippet_id": str(snippet_id)}
        for k in ("star_kind", "star_device", "verdict", "corrected_device",
                  "note", "star_version"):
            if row.get(k) is not None:
                payload[k] = row[k]
        if session_id:
            payload["session_id"] = str(session_id)
        if arc_id:
            payload["arc_id"] = str(arc_id)
        if coach_user_id:
            payload["coach_user_id"] = str(coach_user_id)
        payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        try:
            (self.client.table("star_verdicts")
                 .upsert(payload, on_conflict="snippet_id").execute())
            return True
        except Exception as e:
            err_low = str(e).lower()
            if "star_verdicts" in err_low and (
                "does not exist" in err_low or "pgrst" in err_low
                or "42p01" in err_low
            ):
                logger.warning(
                    "upsert_star_verdict: table missing (run "
                    "migrations/add_star_verdicts.sql)",
                )
                return False
            logger.warning("upsert_star_verdict failed: %s", e)
            return False

    def get_star_verdict(self, snippet_id: str) -> tuple:
        """One star's verdict row, error-distinguishing: ``(row_or_None, ok)``.

        The keep-flip emission guard needs "no verdict exists" and "the read
        FAILED" to be different answers (review finding): the by-ids reader
        returns {} for both, and treating an errored read as "no prior"
        re-emits the approved_as_is row on a re-keep — the exact double-write
        the guard exists to prevent. ok=False → the caller fails CLOSED
        (no emission)."""
        if not snippet_id:
            return None, False
        try:
            rows = (self.client.table("star_verdicts")
                    .select("*").eq("snippet_id", str(snippet_id))
                    .limit(1).execute().data) or []
            return (rows[0] if rows else None), True
        except Exception as e:
            err_low = str(e).lower()
            if "star_verdicts" in err_low and (
                "does not exist" in err_low or "pgrst" in err_low
                or "42p01" in err_low
            ):
                # Missing table = genuinely no verdict can exist yet — that
                # is a real "no prior", not an unknown.
                return None, True
            logger.warning("get_star_verdict failed snip=%s: %s",
                           snippet_id, e)
            return None, False

    def get_star_verdicts_by_snippet_ids(self, snippet_ids: list) -> dict:
        """{snippet_id: verdict_row} for the given snippets. {} on anything
        missing — the coach review simply renders every star as unjudged."""
        ids = [str(s) for s in (snippet_ids or []) if s]
        if not ids:
            return {}
        try:
            rows = (self.client.table("star_verdicts")
                    .select("*").in_("snippet_id", ids).execute().data) or []
            return {str(r.get("snippet_id")): r for r in rows
                    if r.get("snippet_id")}
        except Exception as e:
            err_low = str(e).lower()
            if "star_verdicts" in err_low and (
                "does not exist" in err_low or "pgrst" in err_low
                or "42p01" in err_low
            ):
                logger.warning(
                    "get_star_verdicts_by_snippet_ids: table missing (run "
                    "migrations/add_star_verdicts.sql)",
                )
                return {}
            logger.warning("get_star_verdicts_by_snippet_ids failed: %s", e)
            return {}

    def get_star_verdicts_for_corpus(self, *, star_kind: Optional[str] = None,
                                     limit: int = 5000) -> list:
        """The training-side pull: judged stars, newest first, optionally one
        family. [] on anything missing; NEVER raises."""
        try:
            q = self.client.table("star_verdicts").select("*")
            if star_kind:
                q = q.eq("star_kind", str(star_kind))
            return (q.order("created_at", desc=True)
                     .limit(int(limit)).execute().data) or []
        except Exception as e:
            logger.warning("get_star_verdicts_for_corpus failed: %s", e)
            return []

    def insert_snippet_peer_label(
        self, *, snippet_id: str, rater_id: Optional[str], label: Optional[str],
        source: Optional[str] = None, is_second_order: bool = True,
        weight: float = 1.0, shown_origin: Optional[str] = None,
    ) -> bool:
        """Record a SECOND-ORDER (non-coach) peer/self-verification label
        (Subsystem-S multi-rater lane). This is internal training/evaluation
        evidence only and cannot enter the user's coaching loop.
        Best-effort, append-only, missing-table-safe; NEVER raises."""
        if not snippet_id:
            return False
        row: dict = {
            "snippet_id": str(snippet_id),
            "is_second_order": bool(is_second_order),
            "weight": float(weight),
        }
        if rater_id:
            row["rater_id"] = str(rater_id)
        if label is not None:
            row["label"] = str(label)
        if source:
            row["source"] = str(source)
        if shown_origin:
            row["shown_origin"] = str(shown_origin)
        try:
            self.client.table("snippet_peer_labels").insert(row).execute()
            return True
        except Exception as e:
            err_low = str(e).lower()
            if "snippet_peer_labels" in err_low and (
                "does not exist" in err_low or "pgrst" in err_low
                or "42p01" in err_low
            ):
                logger.warning(
                    "insert_snippet_peer_label: table missing (run "
                    "migrations/add_synthetic_provenance_walls.sql)",
                )
                return False
            logger.warning("insert_snippet_peer_label failed: %s", e)
            return False

    def insert_user_suggestion_feedback(
        self, *, snippet_id: str, session_id: Optional[str],
        user_id: Optional[str], target: str, action: str,
        upgrade_index: Optional[int] = None,
        suggestion_version: Optional[str] = None,
    ) -> bool:
        """Record one Apply / ✓-prefer tap on a suggestion row (founder
        2026-07-14) — a SECOND-ORDER preference signal strictly below coach
        truth (mirrors insert_snippet_peer_label). Never surfaced back as a
        score (AC-9 — capture only). Best-effort, append-only,
        missing-table-safe; NEVER raises."""
        if not snippet_id or not target or not action:
            return False
        row: dict = {
            "snippet_id": str(snippet_id),
            "target": str(target),
            "action": str(action),
        }
        if session_id:
            row["session_id"] = str(session_id)
        if user_id:
            row["user_id"] = str(user_id)
        if isinstance(upgrade_index, int) and not isinstance(upgrade_index, bool):
            row["upgrade_index"] = upgrade_index
        if suggestion_version is not None:
            row["suggestion_version"] = str(suggestion_version)
        try:
            self.client.table("user_suggestion_feedback").insert(row).execute()
            return True
        except Exception as e:
            err_low = str(e).lower()
            if "user_suggestion_feedback" in err_low and (
                "does not exist" in err_low or "pgrst" in err_low
                or "42p01" in err_low
            ):
                logger.warning(
                    "insert_user_suggestion_feedback: table missing (run "
                    "migrations/add_user_suggestion_feedback.sql)",
                )
                return False
            logger.warning("insert_user_suggestion_feedback failed: %s", e)
            return False

    def get_suggestion_feedback_by_session(self, session_id: str) -> list[dict]:
        """All Apply/✓/revert taps for a session, CHRONOLOGICAL — the readout
        replays them into per-snippet applied_upgrade_indexes so the FE's
        Approve state (and its reversibility) survives reload (founder
        2026-07-15). [] on missing table / none / error."""
        if not session_id:
            return []
        try:
            res = (
                self.client.table("user_suggestion_feedback")
                .select("snippet_id, target, upgrade_index, action, created_at")
                .eq("session_id", str(session_id))
                .order("created_at", desc=False)
                .execute()
            )
            return res.data or []
        except Exception as e:
            _e = str(e).lower()
            if "user_suggestion_feedback" in _e and (
                "does not exist" in _e or "pgrst" in _e
            ):
                return []
            logger.warning("get_suggestion_feedback_by_session failed sid=%s: %s",
                           session_id, e)
            return []

    def delete_coach_snippet_drafts_for_session(self, session_id: str) -> int:
        """Delete ALL coach snippet drafts (note/tag/surfaced/when/examples)
        for a session during force re-cut. Returns the delete count;
        best-effort."""
        if not session_id:
            return 0
        try:
            res = (
                self.client.table("coach_snippet_drafts")
                .delete()
                .eq("session_id", session_id)
                .execute()
            )
            return len(res.data or [])
        except Exception as e:
            logger.warning(
                "delete_coach_snippet_drafts_for_session failed sid=%s err=%s",
                session_id, e,
            )
            return 0

    @staticmethod
    def fold_reads_out_of_queue(rows: list[dict]) -> list[dict]:
        """Founder 2026-07-16: a mid-take RE-READ is part of its parent take,
        never its own queue item — the coach packet folds its snippets in.
        Drops read rows (recording_kind='read' / paired_session_id set) and
        stamps has_reread=True on parents present in the same page. Pure
        (unit-tested directly); legacy rows without the columns pass through
        untouched."""
        parents_with_reads = {
            str(r.get("paired_session_id")) for r in rows
            if r.get("paired_session_id")
        }
        out = []
        for r in rows:
            if r.get("recording_kind") == "read" or r.get("paired_session_id"):
                continue
            if str(r.get("id")) in parents_with_reads:
                r = dict(r)
                r["has_reread"] = True
            out.append(r)
        return out

    def list_review_queue(self, *, limit: int = 100) -> list[dict]:
        """willab coach review queue (§3.8/§14): willab Lab sessions sent
        to the coach (status pending_admin_review, source audit_upload)
        and not yet published, newest-sent first. Returns raw rows; the
        route pseudonymizes user_id (§14 red-line 6 — never the real id in
        the list) + shapes the response. (results_published_at filtered in
        Python to avoid PostgREST is-null quirks.) Read rows are folded out
        (fold_reads_out_of_queue) — a re-read reviews INSIDE its parent
        take's packet, never as its own row.
        """
        # `recording_id` IS LOAD-BEARING (P2-19 follow-up, 0a): the coach
        # queue resolves a Take's language from intake_context, else the
        # recording's detected transcription_language, else the snippets.
        # Without the id here the recording fallback silently never ran and
        # a Take with no declared language was withheld from every coach.
        _full_cols = (
            "id, user_id, intake_context, review_requested_at, "
            "created_at, results_published_at, recording_id, "
            "recording_kind, paired_session_id, arc_id, take_index"
        )
        _base_cols = (
            "id, user_id, intake_context, review_requested_at, "
            "created_at, results_published_at, recording_id"
        )
        try:
            try:
                res = (
                    self.client.table("v2_sessions")
                    .select(_full_cols)
                    .eq("status", "pending_admin_review")
                    .eq("source", "audit_upload")
                    .order("review_requested_at", desc=True)
                    .limit(limit)
                    .execute()
                )
                rows = res.data or []
            except Exception as _e_full:
                _low = str(_e_full).lower()
                # Fold/arc columns not migrated yet → the legacy select
                # (no read rows can exist without the columns either).
                if not any(c in _low for c in (
                        "recording_kind", "paired_session_id",
                        "arc_id", "take_index")):
                    raise
                res = (
                    self.client.table("v2_sessions")
                    .select(_base_cols)
                    .eq("status", "pending_admin_review")
                    .eq("source", "audit_upload")
                    .order("review_requested_at", desc=True)
                    .limit(limit)
                    .execute()
                )
                rows = res.data or []
            rows = [r for r in rows if not r.get("results_published_at")]
            return self.fold_reads_out_of_queue(rows)
        except Exception as e:
            err_low = str(e).lower()
            if "source" in err_low and "pgrst" in err_low:
                logger.warning(
                    "list_review_queue: source column missing (run "
                    "migrations/add_foundation_discriminators.sql)",
                )
                return []
            logger.warning("list_review_queue failed err=%s", e)
            return []
    # ── Canonical take-level coach review summary ────────────────────────

    # ── willab beta — coach per-snippet DRAFT store (E1 / §B.3, USER lane) ─

    def upsert_coach_snippet_draft(
        self,
        session_id: str,
        snippet_id: str,
        fields: dict,
        updated_by: Optional[str] = None,
    ) -> Optional[dict]:
        """MERGE-upsert one coach per-snippet draft (note/tag/surfaced/
        when_context/examples) on (session_id, snippet_id).

        Only the keys present in ``fields`` change; the rest of the row is
        preserved (read-modify-write, so partial per-field saves accumulate —
        coach edits note now, tag later). E1 immediate-persist + resume.

        USER lane (split-sink §2): this is a DRAFT. Publish validates and stamps
        canonical exact-evidence fields on this row. Never the private label
        lane. Best-effort: missing table → None.
        """
        if not session_id or not snippet_id:
            return None
        from datetime import datetime, timezone
        now_iso = datetime.now(timezone.utc).isoformat()
        try:
            existing = (
                self.client.table("coach_snippet_drafts")
                .select("*")
                .eq("session_id", session_id)
                .eq("snippet_id", snippet_id)
                .limit(1)
                .execute()
            )
            base = (existing.data or [{}])[0] if getattr(existing, "data", None) else {}
            row = {
                "session_id": session_id,
                "snippet_id": snippet_id,
                "note": base.get("note"),
                "tag": base.get("tag"),
                # Default TRUE on first write (§1.A opt-out-surface, FE handoff
                # 2026-06-19): a snippet reaches the user by default; the coach
                # UN-surfaces the ones to hide (explicit surfaced=false persists
                # and is respected). Reverses the old opt-in-surface default.
                "surfaced": base.get("surfaced", True),
                "when_context": base.get("when_context"),
                "examples": base.get("examples") or [],
                "updated_by": updated_by,
                "updated_at": now_iso,
            }
            # transcript_corrected is only written when the coach actually sets
            # it. A normal note/tag save never references the column, and ON
            # CONFLICT preserves whatever was already there. reference_post_slug
            # joins the same
            # write-only-when-set group: a blog post the COACH manually attaches
            # to this verified moment. Never re-asserted from base, so a normal
            # note/tag save leaves it alone and coach saves keep working before
            # its migration runs.
            for k in (
                "note", "tag", "surfaced", "when_context", "examples",
                "transcript_corrected", "reference_post_slug",
                "feedback_family", "review_state", "evidence_locator",
            ):
                if k in fields:
                    row[k] = fields[k]
            res = (
                self.client.table("coach_snippet_drafts")
                .upsert(row, on_conflict="session_id,snippet_id")
                .execute()
            )
            return (res.data or [None])[0] if getattr(res, "data", None) else row
        except Exception as e:
            err_low = str(e).lower()
            if "coach_snippet_drafts" in err_low and (
                "does not exist" in err_low or "pgrst" in err_low
            ):
                logger.warning(
                    "upsert_coach_snippet_draft: table missing (run "
                    "migrations/add_coach_snippet_drafts_table.sql) sid=%s",
                    session_id,
                )
                return None
            logger.error(
                "upsert_coach_snippet_draft failed sid=%s snip=%s err=%s",
                session_id, snippet_id, e,
            )
            return None

    def get_coach_snippet_drafts(self, session_id: str) -> list[dict]:
        """All USER-lane per-snippet drafts for a session (resume read +
        publish assembly). Empty on missing table / DB hiccup."""
        if not session_id:
            return []
        try:
            res = (
                self.client.table("coach_snippet_drafts")
                .select("*")
                .eq("session_id", session_id)
                .execute()
            )
            return res.data or []
        except Exception as e:
            err_low = str(e).lower()
            if "coach_snippet_drafts" in err_low and (
                "does not exist" in err_low or "pgrst" in err_low
            ):
                return []
            logger.warning(
                "get_coach_snippet_drafts failed sid=%s err=%s", session_id, e,
            )
            return []

    def get_coach_snippet_drafts_by_sessions(self, session_ids) -> dict:
        """Batch read — drafts for many sessions, returned {session_id: rows}.

        Kills the N+1 on the coach queue, which called the singular once per
        queued take purely to decide a lifecycle pill.

        PAGED LIKE `get_snippets_by_sessions`, and for the same reason: a
        session carries one draft PER SNIPPET, so a wide chunk can exceed
        PostgREST's server-side max-rows, which truncates SILENTLY. A missing
        draft reads as "nothing authored" — a wrong pill rather than an
        error — so the guard matters more here than a loud failure would.
        """
        ids = [str(s) for s in (session_ids or []) if s]
        if not ids:
            return {}
        _page = 1000
        out: dict = {}
        try:
            for i in range(0, len(ids), 20):
                chunk = ids[i:i + 20]
                offset = 0
                while True:
                    res = (
                        self.client.table("coach_snippet_drafts")
                        .select("*")
                        .in_("session_id", chunk)
                        .order("snippet_id", desc=False)
                        .range(offset, offset + _page - 1)
                        .execute()
                    )
                    rows = res.data or []
                    for row in rows:
                        out.setdefault(str(row.get("session_id")), []).append(row)
                    if len(rows) < _page:
                        break
                    offset += _page
        except Exception as e:
            err_low = str(e).lower()
            if "coach_snippet_drafts" in err_low and (
                "does not exist" in err_low or "pgrst" in err_low
            ):
                return {}
            logger.warning(
                "get_coach_snippet_drafts_by_sessions failed n=%s err=%s",
                len(ids), e)
            return {}
        return out

    # ── willab beta — user profile (design §2 / contract §3.1) ──────
    #
    # One-time self-declared {domain, goal} on user_settings (co-located
    # with the derived inferred_learner_profile / baseline_summary it
    # feeds). Distinct from v2_speaker_profiles (admin coach-notes).

    def get_user_profile(self, user_id: str) -> Optional[dict]:
        """Read the user's intake profile: {domain, goal, previous_goal,
        goal_changed_at}.

        Returns all-None pre-intake. ``previous_goal`` / ``goal_changed_at``
        carry the LAST goal change (Prompt A §6 C4 follow-up) so the coach
        surface can show "goal: NEW (was PREVIOUS)". None (the whole return)
        only on a hard DB failure, which the route treats as "no profile yet".
        """
        if not user_id:
            return None
        # Goal-change columns are a later migration; select them separately so
        # a pre-migration env still returns {domain, goal} (graceful degrade).
        try:
            res = (
                self.client.table("user_settings")
                .select("profile_domain, profile_goal, profile_goal_previous, "
                        "profile_goal_changed_at")
                .eq("user_id", user_id)
                .limit(1)
                .execute()
            )
            if not res.data:
                return {"domain": None, "goal": None,
                        "previous_goal": None, "goal_changed_at": None}
            row = res.data[0]
            return {
                "domain": row.get("profile_domain"),
                "goal": row.get("profile_goal"),
                "previous_goal": row.get("profile_goal_previous"),
                "goal_changed_at": row.get("profile_goal_changed_at"),
            }
        except Exception as e:
            err_low = str(e).lower()
            if "profile_goal_previous" in err_low or "profile_goal_changed_at" in err_low:
                # Change-tracking migration not yet run — fall back to the
                # base profile so the goal still surfaces.
                return self._get_user_profile_base(user_id)
            if "profile_domain" in err_low or "pgrst204" in err_low:
                logger.warning(
                    "get_user_profile: column missing (run migrations/"
                    "add_profile_to_user_settings.sql) user=%s", user_id,
                )
                return {"domain": None, "goal": None,
                        "previous_goal": None, "goal_changed_at": None}
            logger.warning(
                "get_user_profile failed user=%s err=%s", user_id, e,
            )
            return None

    def get_user_profiles(self, user_ids) -> dict:
        """Batch read — {user_id: {domain, goal}} for many users in one query.

        Kills the N+1 on the coach's student list, which read a whole profile
        per student to render one field. Only the two DISPLAYED fields are
        selected: the coach surface shows domain, never a goal it did not ask
        for, and a narrow select cannot leak a column a later migration adds.

        A user with no row is simply absent from the result; callers already
        treat a missing profile as "not set yet". {} on any failure, which
        degrades every row to blank rather than failing the list.

        The singular carries a fallback for the goal-change columns
        (`profile_goal_previous` / `profile_goal_changed_at`) because a
        pre-migration env errors on them. This selects neither, so that gap
        cannot be reached from here — do not add one back "for symmetry".
        """
        ids = [str(u) for u in (user_ids or []) if u]
        if not ids:
            return {}
        out: dict = {}
        try:
            for i in range(0, len(ids), 100):
                chunk = ids[i:i + 100]
                res = (
                    self.client.table("user_settings")
                    .select("user_id, profile_domain, profile_goal")
                    .in_("user_id", chunk)
                    .execute()
                )
                for row in (res.data or []):
                    out[str(row.get("user_id"))] = {
                        "domain": row.get("profile_domain"),
                        "goal": row.get("profile_goal"),
                    }
        except Exception as e:
            logger.warning(
                "get_user_profiles failed n=%s err=%s", len(ids), e)
            return {}
        return out

    def _get_user_profile_base(self, user_id: str) -> Optional[dict]:
        """Pre-migration fallback — {domain, goal} only, change fields None."""
        try:
            res = (
                self.client.table("user_settings")
                .select("profile_domain, profile_goal")
                .eq("user_id", user_id)
                .limit(1)
                .execute()
            )
            row = (res.data or [{}])[0]
            return {
                "domain": row.get("profile_domain"),
                "goal": row.get("profile_goal"),
                "previous_goal": None, "goal_changed_at": None,
            }
        except Exception as e:
            logger.warning("get_user_profile base read failed user=%s: %s",
                           user_id, e)
            return None

    def update_user_goal(
        self, user_id: str, new_goal: str, previous_goal: Optional[str],
    ) -> bool:
        """Goal-ONLY update from the chat intercept (Prompt A §6 C4). Records
        the prior goal + change time so the coach sees old→new. Partial upsert:
        preserves profile_domain (not in the payload). Best-effort; missing
        change-columns → falls back to a plain goal write (still succeeds)."""
        if not user_id or not new_goal:
            return False
        from datetime import datetime, timezone
        now_iso = datetime.now(timezone.utc).isoformat()
        payload = {
            "user_id": user_id,
            "profile_goal": new_goal,
            "profile_goal_previous": previous_goal,
            "profile_goal_changed_at": now_iso,
            "updated_at": now_iso,
        }
        try:
            self.client.table("user_settings").upsert(payload).execute()
            return True
        except Exception as e:
            err_low = str(e).lower()
            if "profile_goal_previous" in err_low or "profile_goal_changed_at" in err_low:
                # Change-tracking migration not yet run — still persist the
                # goal so the update isn't lost (history just isn't tracked).
                try:
                    self.client.table("user_settings").upsert({
                        "user_id": user_id, "profile_goal": new_goal,
                        "updated_at": now_iso,
                    }).execute()
                    logger.warning(
                        "update_user_goal: change-cols missing (run migrations/"
                        "add_goal_change_tracking.sql) user=%s", user_id,
                    )
                    return True
                except Exception as e2:
                    logger.error("update_user_goal fallback failed user=%s: %s",
                                 user_id, e2)
                    return False
            logger.error("update_user_goal failed user=%s: %s", user_id, e)
            return False

    def set_user_profile(
        self,
        user_id: str,
        *,
        domain: Optional[str],
        goal: Optional[str],
    ) -> bool:
        """Upsert the user's intake profile on user_settings.

        Intake submits both fields together (design §2 — two-turn
        bounded), so this is a full set, not a partial patch. ``domain``
        is validated against the enum by the route layer; the DB CHECK
        constraint is the final gate. Returns True on success, False on
        any DB failure (route maps to 500).
        """
        if not user_id:
            return False
        from datetime import datetime, timezone
        payload = {
            "user_id": user_id,
            "profile_domain": domain,
            "profile_goal": goal,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            (
                self.client.table("user_settings")
                .upsert(payload)
                .execute()
            )
            return True
        except Exception as e:
            err_low = str(e).lower()
            if "profile_domain" in err_low or "pgrst204" in err_low:
                logger.warning(
                    "set_user_profile: column missing (run migrations/"
                    "add_profile_to_user_settings.sql) user=%s", user_id,
                )
                return False
            logger.error(
                "set_user_profile failed user=%s err=%s", user_id, e,
            )
            return False

    # ── blind-rater language eligibility ───────────────────────────

    def get_user_proficient_languages(self, user_id: str) -> Optional[list]:
        """Explicit languages this rater may receive; None = never set."""
        if not user_id:
            return None
        try:
            res = (
                self.client.table("user_settings")
                .select("profile_proficient_languages")
                .eq("user_id", user_id)
                .limit(1)
                .execute()
            )
            if not res.data:
                return None
            value = res.data[0].get("profile_proficient_languages")
            return value if isinstance(value, list) and value else None
        except Exception as e:
            logger.warning(
                "get_user_proficient_languages failed user=%s err=%s",
                user_id, e,
            )
            return None

    def set_user_proficient_languages(
        self, user_id: str, languages: list[str],
    ) -> bool:
        """Partial profile upsert; never touches intake or acoustic fields."""
        if not user_id or not languages:
            return False
        from datetime import datetime, timezone
        try:
            self.client.table("user_settings").upsert({
                "user_id": user_id,
                "profile_proficient_languages": languages,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }).execute()
            return True
        except Exception as e:
            logger.error(
                "set_user_proficient_languages failed user=%s err=%s",
                user_id, e,
            )
            return False

    # ── willab beta — lounge_messages (BE contract §3.15) ───────────
    #
    # Per-user Lounge chat thread. Text only, never audio, never in the
    # coach packet, never profiled. FE-append (incl. bot turns);
    # idempotent on (user_id, client_id); client_created_at is the
    # ordering key surviving the unsigned→signed merge.
    # See services/lounge_messages.py for validation + page shaping.

    def get_lounge_messages_page(
        self,
        user_id: str,
        *,
        limit: int,
        before: Optional[str] = None,
    ) -> list[dict]:
        """Fetch newest-first (DESC) rows for the thread, up to
        ``limit + 1`` so the caller can detect older pages.

        Returns the raw row list in DESC order; the route layer calls
        services.lounge_messages.shape_lounge_page to reverse to ASC +
        compute has_more + oldest_cursor.

        ``before`` (ISO-8601) pages older: rows strictly older than the
        cursor. Absent → the latest page (bottom of thread).

        Empty list on missing table (migration pending) / DB hiccup —
        the Lounge degrades to an empty thread rather than erroring.
        """
        if not user_id:
            return []
        try:
            query = (
                self.client.table("lounge_messages")
                .select(
                    "id, client_id, role, kind, body, metadata, "
                    "client_created_at"
                )
                .eq("user_id", user_id)
            )
            if before:
                query = query.lt("client_created_at", before)
            # +1 to detect whether an older page exists.
            res = (
                query.order("client_created_at", desc=True)
                .limit(limit + 1)
                .execute()
            )
            return res.data or []
        except Exception as e:
            err_low = str(e).lower()
            if (
                "lounge_messages" in err_low
                and ("does not exist" in err_low or "pgrst" in err_low)
            ):
                logger.warning(
                    "get_lounge_messages_page: table missing (run "
                    "migrations/add_lounge_messages_table.sql) user=%s",
                    user_id,
                )
                return []
            logger.warning(
                "get_lounge_messages_page failed user=%s err=%s",
                user_id, e,
            )
            return []

    def bump_latest_lounge_ideal_bubble(
        self,
        user_id: str,
        arc_id: str,
        variants: list[str],
        at_iso: str,
    ) -> bool:
        """Move one project's latest Ideal Text version bubble to ``at_iso``.

        The thread is ordered by client_created_at, so re-stamping it is what
        brings the bubble back to the bottom (founder 2026-09-25, Q41 A).
        True when a bubble moved; False when there is none (or on error)."""
        if not user_id or not arc_id:
            return False
        try:
            rows = (
                self.client.table("lounge_messages")
                .select("id, metadata, client_created_at")
                .eq("user_id", user_id)
                .eq("kind", "ideal_text")
                .eq("metadata->>arc_id", arc_id)
                .order("client_created_at", desc=True)
                .limit(20)
                .execute()
            ).data or []
            target = next(
                (r for r in rows
                 if (r.get("metadata") or {}).get("variant") in variants),
                None,
            )
            if not target:
                return False
            (
                self.client.table("lounge_messages")
                .update({"client_created_at": at_iso})
                .eq("id", target["id"])
                .eq("user_id", user_id)
                .execute()
            )
            return True
        except Exception as e:
            logger.warning(
                "bump_latest_lounge_ideal_bubble failed user=%s arc=%s err=%s",
                user_id, arc_id, e,
            )
            return False

    def insert_lounge_messages(
        self,
        user_id: str,
        messages: list[dict],
    ) -> list[dict]:
        """Idempotent batch append/merge of Lounge messages.

        Upserts on the (user_id, client_id) unique key — re-sending a
        stored client_id is a no-op, not a duplicate (covers append
        retry, double-tap, and double-merge-on-resignup). The same
        path serves both per-turn appends and the merge-on-signup
        replay (BE contract §3.5/§3.15, §7.8 — no separate /merge
        alias).

        ``messages`` are pre-validated rows from
        services.lounge_messages.validate_lounge_batch (each carries
        client_id, role, kind, body, metadata, client_created_at).
        BE stamps user_id here — the FE never sets it.

        Returns the persisted rows (with server id) or [] on failure.
        """
        if not user_id or not messages:
            return []
        rows = [
            {
                "user_id":           user_id,
                "client_id":         m["client_id"],
                "role":              m["role"],
                "kind":              m["kind"],
                "body":              m.get("body") or "",
                "metadata":          m.get("metadata"),
                "client_created_at": m["client_created_at"],
            }
            for m in messages
        ]
        try:
            res = (
                self.client.table("lounge_messages")
                .upsert(rows, on_conflict="user_id,client_id")
                .execute()
            )
            return res.data or []
        except Exception as e:
            err_low = str(e).lower()
            if (
                "lounge_messages" in err_low
                and ("does not exist" in err_low or "pgrst" in err_low)
            ):
                logger.warning(
                    "insert_lounge_messages: table missing (run "
                    "migrations/add_lounge_messages_table.sql) user=%s",
                    user_id,
                )
                return []
            logger.error(
                "insert_lounge_messages failed user=%s count=%d err=%s",
                user_id, len(rows), e,
            )
            return []

    def has_voice_album_introduction(self, user_id: str) -> bool:
        """Whether this user has already received Voice Album onboarding."""
        if not user_id:
            return False
        try:
            res = (
                self.client.table("user_settings")
                .select("voice_album_introduced_at")
                .eq("user_id", user_id)
                .limit(1)
                .execute()
            )
            return bool(
                res.data
                and res.data[0].get("voice_album_introduced_at")
            )
        except Exception as e:
            logger.warning(
                "has_voice_album_introduction failed user=%s: %s",
                user_id, e,
            )
            return False

    def mark_voice_album_introduced(self, user_id: str) -> bool:
        """Persist the one-time, user-scoped Voice Album introduction."""
        if not user_id:
            return False
        try:
            now = datetime.now(timezone.utc).isoformat()
            (
                self.client.table("user_settings")
                .upsert({
                    "user_id": user_id,
                    "voice_album_introduced_at": now,
                    "updated_at": now,
                }, on_conflict="user_id")
                .execute()
            )
            return True
        except Exception as e:
            logger.warning(
                "mark_voice_album_introduced failed user=%s: %s",
                user_id, e,
            )
            return False

    def list_user_product_discoveries(self, user_id: str) -> list[dict]:
        """Durable products introduced to this authenticated user."""
        if not user_id:
            return []
        try:
            res = (
                self.client.table("user_product_discoveries")
                .select("product,intent,source,schema_version,discovered_at")
                .eq("user_id", user_id)
                .execute()
            )
            return res.data or []
        except Exception as e:
            logger.warning(
                "list_user_product_discoveries failed user=%s: %s",
                user_id, e,
            )
            return []

    def get_lounge_message_by_client_id(
        self, user_id: str, client_id: str,
    ) -> Optional[Dict[str, Any]]:
        """One owner-scoped idempotent Lounge event, if it exists."""
        if not user_id or not client_id:
            return None
        try:
            res = (
                self.client.table("lounge_messages")
                .select("id,client_id,role,kind,body,metadata,client_created_at")
                .eq("user_id", user_id)
                .eq("client_id", client_id)
                .limit(1)
                .execute()
            )
            return res.data[0] if res.data else None
        except Exception as e:
            logger.warning("get_lounge_message_by_client_id failed: %s", e)
            return None

    def delete_lounge_message_by_client_id(
        self, user_id: str, client_id: str,
    ) -> bool:
        """Retract ONE owner-scoped Lounge row by its idempotency key.

        The narrow counterpart to the user-initiated thread clear below. It
        removes a single card that a later, stronger read of the database
        proved untrue -- today only the Ideal Text failure card, whose
        client_id is the Take's session UUID. Deliberately not a general
        moderation tool: the same idempotent upsert recreates the row if the
        failure it describes turns out to be real after all.
        """
        if not user_id or not client_id:
            return False
        try:
            (
                self.client.table("lounge_messages")
                .delete()
                .eq("user_id", user_id)
                .eq("client_id", client_id)
                .execute()
            )
            return True
        except Exception as e:
            logger.warning(
                "delete_lounge_message_by_client_id failed user=%s cid=%s "
                "err=%s", user_id, client_id, e,
            )
            return False

    def delete_lounge_messages_for_user(self, user_id: str) -> bool:
        """Delete the entire Lounge thread for a user (BE contract
        §3.14 — user-deletable privacy commitment). Account deletion
        is covered separately by the ON DELETE CASCADE FK; this is the
        explicit user-initiated 'clear my Lounge' path.
        """
        if not user_id:
            return False
        try:
            (
                self.client.table("lounge_messages")
                .delete()
                .eq("user_id", user_id)
                .execute()
            )
            return True
        except Exception as e:
            logger.warning(
                "delete_lounge_messages_for_user failed user=%s err=%s",
                user_id, e,
            )
            return False

    # ------------------------------------------------------------------
    # User settings (LLM instructions)
    # ------------------------------------------------------------------

    def get_user_settings(self, user_id: str) -> Optional[dict]:
        """Get user_settings row (custom LLM instructions, etc)."""
        try:
            result = (
                self.client.table("user_settings")
                .select("*")
                .eq("user_id", user_id)
                .limit(1)
                .execute()
            )
            if result.data and len(result.data) > 0:
                return result.data[0]
            return None
        except Exception as e:
            logger.warning(f"get_user_settings failed: {e}")
            return None

    # ── Chat-surface consent flags (Phase Single-Slot-Chat) ────────
    #
    # Four nullable boolean columns on user_settings powering
    # GET / PUT /v2/user/sharing-consent. NULL = not yet answered
    # (FE shows the prompt for that slot). TRUE/FALSE = answered.
    # Distinct from the user_consents GDPR audit ledger; that one
    # is immutable and written once at signup.

    _CONSENT_FIELDS = (
        "mic_consent",
        "share_consent",
        "email_consent",
        "terms_consent",
    )

    def get_consent_state(self, user_id: str) -> dict:
        """Returns the four-flag consent state for ``user_id``.

        Shape::
            {
              "mic_consent":   bool | None,
              "share_consent": bool | None,
              "email_consent": bool | None,
              "terms_consent": bool | None,
            }

        Returns all-None when the user has no user_settings row yet
        OR the consent columns haven't been migrated yet (silent
        degradation so pre-migration deploys don't 500). The route
        handler computes ``has_answered`` from these.
        """
        settings = self.get_user_settings(user_id) or {}
        out: dict = {}
        for field in self._CONSENT_FIELDS:
            val = settings.get(field)
            # Defensive: anything other than True/False/None is treated
            # as "not answered". Supabase JSON decode can occasionally
            # surface odd types; we'd rather show the prompt than
            # block on a malformed cell.
            if isinstance(val, bool):
                out[field] = val
            else:
                out[field] = None
        return out

    def upsert_consent_fields(
        self,
        user_id: str,
        patch: dict,
    ) -> Optional[dict]:
        """Partial upsert of the four consent flags. ``patch`` may
        contain any subset of mic_consent / share_consent /
        email_consent / terms_consent; missing keys are NOT touched.

        Returns the post-write consent state (same shape as
        ``get_consent_state``) on success, None on failure.

        Silently no-ops + warns when the columns are missing
        (pre-migration env). Matches the pattern used by
        ``insert_casual_voice_benchmark`` and others.
        """
        payload: dict = {
            "user_id": user_id,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        for field in self._CONSENT_FIELDS:
            if field in patch:
                val = patch[field]
                if val is not None and not isinstance(val, bool):
                    # Caller passed a non-bool / non-None — reject
                    # at this layer rather than silently coercing.
                    logger.warning(
                        "upsert_consent_fields: %s must be bool or "
                        "None, got %r — skipping that field",
                        field, type(val).__name__,
                    )
                    continue
                payload[field] = val
        if len(payload) <= 2:
            # Caller asked to update nothing — return current state.
            return self.get_consent_state(user_id)

        try:
            (
                self.client.table("user_settings")
                .upsert(payload)
                .execute()
            )
        except Exception as e:
            err_low = str(e).lower()
            if any(
                f in err_low for f in self._CONSENT_FIELDS
            ) and ("does not exist" in err_low or "pgrst204" in err_low):
                logger.warning(
                    "upsert_consent_fields: consent columns missing "
                    "(migration pending?) user=%s — skipping write",
                    user_id,
                )
                return self.get_consent_state(user_id)
            logger.warning(
                "upsert_consent_fields failed user=%s err=%s",
                user_id, e,
            )
            return None

        return self.get_consent_state(user_id)

    def upsert_user_settings(self, user_id: str, custom_llm_instructions: str | None) -> Optional[dict]:
        """Create or update user_settings.custom_llm_instructions."""
        try:
            result = (
                self.client.table("user_settings")
                .upsert({
                    "user_id": user_id,
                    "custom_llm_instructions": custom_llm_instructions,
                    "updated_at": "now()",
                })
                .execute()
            )
            if result.data and len(result.data) > 0:
                return result.data[0]
            return None
        except Exception as e:
            logger.error(f"upsert_user_settings failed: {e}")
            return None

    def upsert_admin_user_context_fields(
        self,
        *,
        user_id: str,
        custom_llm_instructions: Optional[str] = None,
        private_admin_notes: Optional[str] = None,
        coach_override_profile: Optional[str] = None,
        update_instructions: bool = False,
        update_notes: bool = False,
        update_override_profile: bool = False,
    ) -> Optional[dict]:
        """Partial upsert of admin-editable user context fields.

        Phase 12 — backs the PUT /v2/admin/user/<id>/context endpoint.
        Each ``update_*`` flag controls whether the matching value is
        included in the upsert payload, so the caller can update one
        card on the admin view without overwriting the others.

        Note: ``coach_override_profile`` lives on user_sniper_profile
        (the Phase 9 admin learner-type override), not user_settings.
        We persist it via the existing student-profile path so the
        precedence rule in _augment_coaching_system_prompt keeps
        working unchanged.

        Legacy ``queued_override_question`` parameter was removed in
        the Week-1 cleanup. The admin override path is now
        coaching_directives_queue (POST /v2/admin/users/<id>/
        directives-queue). Old data in the user_settings column
        persists in the DB but is no longer read or written here.

        Returns the updated user_settings row, or None on failure.
        """
        # ── user_settings side ────────────────────────────────────
        payload: dict[str, Any] = {
            "user_id": user_id,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if update_instructions:
            payload["custom_llm_instructions"] = custom_llm_instructions
        if update_notes:
            payload["private_admin_notes"] = private_admin_notes

        updated_row = None
        if len(payload) > 2:  # more than just user_id + updated_at
            try:
                result = (
                    self.client.table("user_settings")
                    .upsert(payload)
                    .execute()
                )
                if result.data:
                    updated_row = result.data[0]
            except Exception as e:
                logger.warning(
                    "upsert_admin_user_context_fields settings failed "
                    "user=%s err=%s", user_id, e,
                )
                return None
        else:
            # Caller didn't ask to update anything on user_settings;
            # we still want to return the current row.
            updated_row = self.get_user_settings(user_id)

        # ── user_sniper_profile side (coach_override_profile) ─────
        if update_override_profile:
            try:
                # The override column lives on user_sniper_profile (per
                # the precedence rule in routes/v2_routes.py::
                # _augment_coaching_system_prompt). Upsert keyed on
                # user_id; we only touch the override column so the
                # rest of the profile (behavioral_profile, etc.) stays
                # intact.
                self.client.table("user_sniper_profile").upsert({
                    "user_id": user_id,
                    "coach_override_profile": coach_override_profile,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }).execute()
            except Exception as e:
                logger.warning(
                    "upsert_admin_user_context_fields override failed "
                    "user=%s err=%s", user_id, e,
                )

        return updated_row

    def get_email_pref_publish_results(self, user_id: str) -> bool:
        """Phase 14 — is this user subscribed to the publish-results
        email? Defaults to TRUE on any error or missing row so a DB
        hiccup never accidentally drops emails to subscribed users.
        """
        if not user_id:
            return True
        try:
            result = (
                self.client.table("user_settings")
                .select("email_pref_publish_results")
                .eq("user_id", user_id)
                .limit(1)
                .execute()
            )
            if result.data:
                val = result.data[0].get("email_pref_publish_results")
                # Treat NULL as TRUE — schema default is TRUE; only an
                # explicit FALSE skips the send.
                return False if val is False else True
            return True
        except Exception as e:
            logger.warning(
                "get_email_pref_publish_results failed user=%s err=%s",
                user_id, e,
            )
            return True

    def set_email_pref_publish_results(
        self,
        *,
        user_id: str,
        subscribed: bool,
        source: str | None = None,
    ) -> bool:
        """Phase 14 — flip the publish-results email preference.

        When ``subscribed`` is False we also stamp ``unsubscribed_at``
        + ``unsubscribed_source`` for audit. Going back to True
        clears those fields so the audit trail reflects only the
        current opt-out state.

        Upsert so users without a settings row still record their
        opt-out (the row defaults the other settings columns to
        their schema defaults).

        Returns True on success.
        """
        if not user_id:
            return False
        try:
            now = datetime.now(timezone.utc).isoformat()
            payload: dict[str, Any] = {
                "user_id": user_id,
                "email_pref_publish_results": bool(subscribed),
                "updated_at": now,
            }
            if subscribed:
                payload["unsubscribed_at"] = None
                payload["unsubscribed_source"] = None
            else:
                payload["unsubscribed_at"] = now
                payload["unsubscribed_source"] = source or "unknown"
            (
                self.client.table("user_settings")
                .upsert(payload)
                .execute()
            )
            return True
        except Exception as e:
            logger.warning(
                "set_email_pref_publish_results failed user=%s err=%s",
                user_id, e,
            )
            return False

    def get_baseline_established(self, user_id: str) -> bool:
        """Phase 13 — has this user completed the EBCP baseline once?

        Defaults to False on any error or missing row so an
        infrastructure hiccup never accidentally bypasses the
        scripted opener.
        """
        if not user_id:
            return False
        try:
            result = (
                self.client.table("user_settings")
                .select("baseline_established")
                .eq("user_id", user_id)
                .limit(1)
                .execute()
            )
            if result.data:
                return bool(result.data[0].get("baseline_established"))
            return False
        except Exception as e:
            logger.warning(
                "get_baseline_established failed user=%s err=%s",
                user_id, e,
            )
            return False

    def mark_baseline_established(self, user_id: str) -> bool:
        """Phase 13 — flip the flag TRUE the first time a user
        graduates from the scripted EBCP turns (1-4) into the LLM
        regime. Upsert so the row exists even for users who never
        edited any other setting. Returns True on success.
        """
        if not user_id:
            return False
        try:
            (
                self.client.table("user_settings")
                .upsert({
                    "user_id": user_id,
                    "baseline_established": True,
                    "baseline_established_at": (
                        datetime.now(timezone.utc).isoformat()
                    ),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                })
                .execute()
            )
            return True
        except Exception as e:
            logger.warning(
                "mark_baseline_established failed user=%s err=%s",
                user_id, e,
            )
            return False

    def reset_baseline_established(self, user_id: str) -> bool:
        """Phase 13 — admin reset path. Flips ``baseline_established``
        back to FALSE so the user runs the scripted EBCP opener again
        on their next session. Clears ``baseline_established_at`` too
        for audit clarity ("when was the most recent graduation?").

        Phase 16: also clears any cached ``baseline_summary`` so the
        re-run produces a fresh digest. Otherwise an admin-triggered
        re-baseline would silently use the OLD summary on the new
        EBCP graduation — masking exactly the freshness an admin
        wanted.

        Upsert (not update) so this works on users who don't have a
        user_settings row yet — they just get a fresh row with FALSE,
        which is the schema default anyway.

        Returns True on success. Failure logs + returns False so the
        admin route can surface a proper error.
        """
        if not user_id:
            return False
        try:
            (
                self.client.table("user_settings")
                .upsert({
                    "user_id": user_id,
                    "baseline_established": False,
                    "baseline_established_at": None,
                    "baseline_summary": None,
                    "baseline_summary_computed_at": None,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                })
                .execute()
            )
            return True
        except Exception as e:
            logger.warning(
                "reset_baseline_established failed user=%s err=%s",
                user_id, e,
            )
            return False

    def get_user_baseline_summary(self, user_id: str) -> Optional[dict]:
        """Phase 16 — read the cached baseline_summary blob.

        Returns None when:
          - user_id missing,
          - no user_settings row yet,
          - column is NULL (user hasn't reached turn 5 yet),
          - any Supabase error.
        Caller falls through to raw previous_turns in those cases.
        """
        if not user_id:
            return None
        try:
            result = (
                self.client.table("user_settings")
                .select("baseline_summary")
                .eq("user_id", user_id)
                .limit(1)
                .execute()
            )
            if result.data:
                return result.data[0].get("baseline_summary") or None
            return None
        except Exception as e:
            logger.warning(
                "get_user_baseline_summary failed user=%s err=%s",
                user_id, e,
            )
            return None

    def set_user_baseline_summary(
        self,
        user_id: str,
        summary: Optional[dict],
    ) -> bool:
        """Phase 16 — persist the LLM-generated baseline digest.

        Upserts user_settings row + stamps baseline_summary_
        computed_at. Pass summary=None to clear (admin reset path
        uses reset_baseline_established, not this).

        Returns True on success.
        """
        if not user_id:
            return False
        try:
            now = datetime.now(timezone.utc).isoformat()
            (
                self.client.table("user_settings")
                .upsert({
                    "user_id": user_id,
                    "baseline_summary": summary,
                    "baseline_summary_computed_at": now if summary else None,
                    "updated_at": now,
                })
                .execute()
            )
            return True
        except Exception as e:
            logger.warning(
                "set_user_baseline_summary failed user=%s err=%s",
                user_id, e,
            )
            return False

    def list_snippets_for_sessions(
        self,
        session_ids: List[str],
    ) -> dict[str, List[dict]]:
        """Bulk load charisma_snippets grouped by session_id.

        Phase 12 — replaces N per-session queries with one IN-list
        query. Returns ``{session_id: [snippet, ...]}``. Sessions
        with no snippets are NOT included as empty entries; callers
        should default to [] when looking up a missing key.
        """
        if not session_ids:
            return {}
        try:
            rows = (
                self.client.table(SNIPPETS_TABLE)
                .select("*")
                .in_("session_id", session_ids)
                .order("turn_number", desc=False)
                .order("start_offset_ms", desc=False)
                .execute()
                .data
            ) or []
        except Exception as e:
            logger.warning(
                "list_snippets_for_sessions failed err=%s", e,
            )
            return {}

        grouped: dict[str, List[dict]] = {}
        for r in rows:
            sid = r.get("session_id")
            if not sid:
                continue
            grouped.setdefault(str(sid), []).append(r)
        return grouped

    # ``consume_queued_override_question`` was removed in the Week-1
    # cleanup. The admin override path is now
    # coaching_directives_queue (see db.pop_next_directive). The
    # legacy ``user_settings.queued_override_question`` column
    # persists in the DB for forensic safety but is neither read
    # nor written by application code.

    # ------------------------------------------------------------------
    # User timeline (admin: chronological interview view)
    # ------------------------------------------------------------------

    def get_user_interview_timeline(self, user_id: str, session_id: str | None = None) -> List[dict]:
        """Fetch a user's interview snippets in chronological order.

        Returns snippets (with question_text, turn_number, metrics) sorted by
        turn_number. If session_id is provided, filters to that session only.
        """
        try:
            query = (
                self.client.table(SNIPPETS_TABLE)
                .select("*")
                .eq("user_id", user_id)
            )
            if session_id:
                query = query.eq("session_id", session_id)
            result = query.order("turn_number", desc=False).order("created_at", desc=False).execute()
            return result.data if result.data else []
        except Exception as e:
            logger.error(f"get_user_interview_timeline failed: {e}")
            return []

    def update_turn_question_text(self, turn_id: str, text: str) -> Optional[dict]:
        """Update the question_text on a charisma_snippets row (admin HITL edit).

        A "turn" is a charisma_snippet row — each interview answer audio chunk
        stores the question asked in that turn as `question_text`.

        Returns the updated row, or None if not found.
        """
        try:
            result = (
                self.client.table(SNIPPETS_TABLE)
                .update({
                    "question_text": text,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                })
                .eq("id", turn_id)
                .execute()
            )
            return result.data[0] if result.data else None
        except Exception as e:
            logger.error("update_turn_question_text failed for turn_id=%s: %s", turn_id, e)
            return None

    # ------------------------------------------------------------------
    # Legal + runtime consent
    # ------------------------------------------------------------------

    def get_user_consent_state(
        self,
        user_id: str,
        *,
        current_terms_version: str,
    ) -> dict:
        """Compose the unified consent payload for /v2/user/consent.

        Reads three runtime preferences off user_settings (mic, share,
        email) AND the immutable user_consents ledger to derive a
        terms_consent flag against ``current_terms_version``.

        Returns a shape-complete dict — every field is always present
        so the route handler doesn't need to special-case missing
        rows. NULL preferences mean "user has never been asked"; the
        frontend uses NULL to decide whether to surface the prompt.

        Response shape::

            {
              "has_answered":            bool,
              "mic_consent":             True | False | None,
              "mic_consent_set_at":      "ISO8601" | None,
              "share_consent":           True | False | None,
              "share_consent_set_at":    "ISO8601" | None,
              "email_consent":           True | False | None,
              "email_consent_set_at":    "ISO8601" | None,
              "terms_consent":           True | False,
              "terms_version_current":   "1.0",
              "terms_version_accepted":  "1.0" | None,
              "terms_accepted_at":       "ISO8601" | None,
            }

        has_answered is True iff ANY of (mic / share / email is non-
        NULL) OR the user has a user_consents row at the current
        terms_version. Frontend reads this to skip the "ask anything"
        moment for users who have already engaged with consent.
        """
        settings = self.get_user_settings(user_id) or {}

        # Resolve the terms ledger lookup. Cheap (indexed on user_id +
        # terms_version, unique pair). On any error: default to
        # terms_consent=False so we under-claim acceptance rather than
        # over-claim — the frontend simply re-prompts.
        terms_row: Optional[dict] = None
        try:
            result = (
                self.client.table("user_consents")
                .select("terms_version, terms_accepted_at")
                .eq("user_id", user_id)
                .eq("terms_version", current_terms_version)
                .limit(1)
                .execute()
            )
            if result.data:
                terms_row = result.data[0]
        except Exception as e:
            logger.warning(
                "get_user_consent_state: terms lookup failed "
                "user=%s err=%s — defaulting terms_consent=False",
                user_id, e,
            )

        mic = settings.get("mic_consent_preference")
        share = settings.get("share_consent_preference")
        email = settings.get("email_consent_preference")
        terms_consent = bool(terms_row)

        has_answered = (
            mic is not None
            or share is not None
            or email is not None
            or terms_consent
        )

        return {
            "has_answered": has_answered,
            "mic_consent": mic,
            "mic_consent_set_at": settings.get("mic_consent_set_at"),
            "share_consent": share,
            "share_consent_set_at": settings.get("share_consent_set_at"),
            "email_consent": email,
            "email_consent_set_at": settings.get("email_consent_set_at"),
            "terms_consent": terms_consent,
            "terms_version_current": current_terms_version,
            "terms_version_accepted": (
                terms_row.get("terms_version") if terms_row else None
            ),
            "terms_accepted_at": (
                terms_row.get("terms_accepted_at") if terms_row else None
            ),
        }

    def set_user_consent_preferences(
        self,
        user_id: str,
        *,
        mic: Optional[bool] = None,
        share: Optional[bool] = None,
        email: Optional[bool] = None,
        update_mic: bool = False,
        update_share: bool = False,
        update_email: bool = False,
    ) -> bool:
        """Upsert the runtime consent preferences on user_settings.

        Only the flags whose ``update_*`` companion is True are
        written. This matches the existing partial-update convention
        used by upsert_admin_user_context_fields and lets the route
        send PATCH-style payloads (only included keys are written).

        Each ``update_*=True`` write also stamps the corresponding
        *_set_at column to NOW so the UI can show "you opted in on
        <date>". Setting a preference to None when update_*=True is
        a valid "clear" (the column goes back to NULL, set_at also
        cleared, the frontend re-prompts).

        Returns True on success, False on any DB error. The route
        handler maps False to 500 so the user retries rather than
        seeing a misleading 200.
        """
        if not (update_mic or update_share or update_email):
            # Nothing to write — caller sent an empty payload.
            return True

        from datetime import datetime, timezone
        now_iso = datetime.now(timezone.utc).isoformat()

        payload: dict[str, Any] = {
            "user_id": user_id,
            "updated_at": now_iso,
        }
        if update_mic:
            payload["mic_consent_preference"] = mic
            payload["mic_consent_set_at"] = now_iso if mic is not None else None
        if update_share:
            payload["share_consent_preference"] = share
            payload["share_consent_set_at"] = now_iso if share is not None else None
        if update_email:
            payload["email_consent_preference"] = email
            payload["email_consent_set_at"] = now_iso if email is not None else None

        try:
            (
                self.client.table("user_settings")
                .upsert(payload)
                .execute()
            )
            return True
        except Exception as e:
            logger.error(
                "set_user_consent_preferences failed user=%s err=%s",
                user_id, e,
            )
            return False

    def record_user_consent(
        self,
        user_id: str,
        terms_version: str = "1.0",
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> dict | None:
        """Insert a consent record into user_consents.

        Uses upsert with on-conflict-do-nothing so that calling this twice
        for the same (user_id, terms_version) pair is safe and idempotent —
        the original timestamp is preserved.

        Returns the stored row dict, or None on failure (non-fatal: the
        Supabase user has already been created by the time this is called,
        so a logging failure must not block registration).
        """
        try:
            from datetime import timezone, datetime
            now_utc = datetime.now(timezone.utc).isoformat()
            row = {
                "user_id": user_id,
                "terms_version": terms_version,
                "terms_accepted_at": now_utc,
                "ip_address": ip_address,
                "user_agent": user_agent,
            }
            result = (
                self.client.table("user_consents")
                .upsert(row, on_conflict="user_id,terms_version", ignore_duplicates=True)
                .execute()
            )
            return result.data[0] if result.data else row
        except Exception as e:
            logger.error(f"record_user_consent failed for user_id={user_id}: {e}")
            return None

    def insert_user_consent_event(
        self,
        *,
        user_id: str,
        consent_type: str,
        consent_value: Optional[bool],
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> Optional[dict]:
        """Append a row to the per-flip consent audit ledger.

        Companion to ``record_user_consent`` — that one is the
        single-row-per-(user, terms_version) TOS acceptance record;
        this one is the append-only event log of every per-toggle
        consent change (mic_consent / share_consent / email_consent
        / terms_consent).

        Called from POST /v2/user/sharing-consent for EACH field
        that the body actually patched. Migration:
        migrations/add_user_consent_events_table.sql.

        Failure-tolerant — a ledger-write failure does NOT unwind
        the user-facing PUT (the preference column is already
        updated and we don't want the admin to retry a successful
        consent change). Logs the failure so we can spot it in
        Sentry; returns None.

        Graceful fallback when the table doesn't exist yet
        (migration pending): the post-rollout PGRST204 is
        downgraded to a warning so the consent PUT keeps working
        during the deploy window.
        """
        if not user_id or not consent_type:
            return None
        try:
            from datetime import timezone, datetime
            now_utc = datetime.now(timezone.utc).isoformat()
            row = {
                "user_id": user_id,
                "consent_type": consent_type,
                "consent_value": consent_value,
                "set_at": now_utc,
                "ip_address": ip_address,
                "user_agent": user_agent,
            }
            result = (
                self.client.table("user_consent_events")
                .insert(row)
                .execute()
            )
            if result.data and len(result.data) > 0:
                return result.data[0]
            return None
        except Exception as e:
            err_low = str(e).lower()
            if (
                "user_consent_events" in err_low
                or "pgrst204" in err_low
            ):
                logger.warning(
                    "insert_user_consent_event: table missing "
                    "(run migrations/add_user_consent_events_"
                    "table.sql) user=%s type=%s",
                    user_id, consent_type,
                )
                return None
            logger.error(
                "insert_user_consent_event failed user=%s type=%s "
                "err=%s",
                user_id, consent_type, e,
            )
            return None

    # ── Read alignment (F1 handoff §3, 2026-08-03) ────────────────────
    def upsert_read_alignment(self, session_id: str, fields: dict) -> bool:
        """Persist one read's force-alignment result (aligned transcript,
        per-word timings, script deviations). One row per read session."""
        if not session_id or not isinstance(fields, dict):
            return False
        try:
            self.client.table("read_alignments").upsert({
                "session_id": str(session_id),
                **fields,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }, on_conflict="session_id").execute()
            return True
        except Exception as e:
            _e = str(e).lower()
            if "read_alignments" in _e and ("does not exist" in _e
                                            or "pgrst" in _e):
                logger.warning(
                    "upsert_read_alignment: table missing (run "
                    "migrations/add_read_alignments.sql)")
                return False
            logger.warning("upsert_read_alignment failed sid=%s: %s",
                           session_id, e)
            return False

    # ── Confident Voice micro-practice ────────────────────────────────
    # These tables are intentionally isolated from presentation text,
    # intervention decisions and state_ratings. Keeping an attempt does not
    # write Voice Album state; only the separate post-coach three-signal
    # reconciler may mirror the selected recording there.

    def get_confident_voice_practice_candidates(
        self, snippet_ids: Any,
    ) -> list[dict]:
        """Heavy fields needed only by the narrow exercise eligibility read.

        ``get_snippets_by_ids`` intentionally omits transcripts, word timing
        and audio references for the hot document-ranking path. Reusing it
        made every exercise candidate look unaligned. Keep this separate so
        ordinary Ideal Text reads do not pay for the larger JSONB payload.
        """
        ids = [str(value) for value in (snippet_ids or []) if value]
        if not ids:
            return []
        try:
            res = (self.client.table(SNIPPETS_TABLE)
                   .select("id, transcript, words, duration_ms, "
                           "start_offset_ms, audio_segment_path, metrics")
                   .in_("id", ids).execute())
            return res.data or []
        except Exception as e:
            logger.warning(
                "get_confident_voice_practice_candidates failed (%d ids): %s",
                len(ids), e)
            return []

    def get_active_diagnostic_exercise(
        self, exercise_id: str,
    ) -> Optional[dict]:
        if not exercise_id:
            return None
        try:
            res = (self.client.table("diagnostic_exercise").select("*")
                   .eq("exercise_id", str(exercise_id))
                   .eq("active", True).limit(1).execute())
            row = (res.data or [None])[0]
            # THE VIDEO IS THE ONLY REQUIRED ASSET (founder 2026-09-23,
            # migration 0353). The post used to be required here too, and
            # leaving that check in place would have made "publish without a
            # blog post" mean "saved and never served" — the outcome the
            # founder explicitly rejected. An exercise now stands on its video
            # and its instruction.
            if not row or not row.get("explanation_video_url"):
                return None
            # A post is optional, but one that IS attached must be live: half-
            # linking an exercise to a draft would show a learner a dead
            # address, which is worse than showing them none.
            post_id = row.get("journal_post_id")
            if post_id:
                post = self.get_journal_post_by_id(str(post_id))
                if not post or post.get("status") != "published":
                    return None
            return row
        except Exception as e:
            logger.warning("get_active_diagnostic_exercise failed id=%s: %s",
                           exercise_id, e)
            return None

    def list_diagnostic_exercises(self) -> list[dict]:
        try:
            res = (self.client.table("diagnostic_exercise").select("*")
                   .order("exercise_id").execute())
            return res.data or []
        except Exception as e:
            logger.warning("list_diagnostic_exercises failed: %s", e)
            return []

    def any_active_coach(self) -> Optional[bool]:
        """Is at least one coach on the panel? True / False, or None when
        the read failed (callers keep today's behaviour on None rather than
        deciding either way on a hiccup). Founder 2026-09-30, cold start:
        the sentence "Your coach is working on your exercise" is a promise,
        and with nobody on the panel it is false."""
        try:
            res = (self.client.table("coach_users").select("email")
                   .eq("is_active", True).limit(1).execute())
            return bool(res.data)
        except Exception as e:
            logger.warning("any_active_coach failed: %s", e, exc_info=True)
            return None

    def list_feedback_catalogue(self, active_only: bool = True) -> list[dict]:
        """The signed lines (migration 0401). [] means "no catalogue": the
        served rows keep their constants and the honest fallback."""
        try:
            query = self.client.table("feedback_catalogue").select("*")
            if active_only:
                query = query.eq("active", True)
            return (query.order("lane").order("pattern_kind")
                    .order("pattern_key").order("version")
                    .execute().data) or []
        except Exception as e:
            logger.warning("list_feedback_catalogue failed: %s", e,
                           exc_info=True)
            return []

    def insert_feedback_catalogue_line(
        self, *, lane: str, pattern_kind: str, pattern_key: str, text: str,
        signed_by: Optional[str],
    ) -> Optional[dict]:
        """A new VERSION of the line for one pattern (rows are never
        edited). None on failure."""
        try:
            prior = (self.client.table("feedback_catalogue")
                     .select("version").eq("lane", lane)
                     .eq("pattern_kind", pattern_kind)
                     .eq("pattern_key", pattern_key)
                     .order("version", desc=True).limit(1).execute().data) or []
            version = int((prior[0] or {}).get("version") or 0) + 1 if prior else 1
            res = self.client.table("feedback_catalogue").insert({
                "lane": lane, "pattern_kind": pattern_kind,
                "pattern_key": pattern_key, "text": text,
                "version": version, "signed_by": signed_by, "active": True,
            }).execute()
            return (res.data or [None])[0]
        except Exception as e:
            logger.warning("insert_feedback_catalogue_line failed key=%s/%s/%s: %s",
                           lane, pattern_kind, pattern_key, e, exc_info=True)
            return None

    def list_speaking_errors(self, active_only: bool = True) -> list[dict]:
        """The speaking error library (migrations/add_speaking_error_library).

        An EMPTY list means "no library available" — a pending migration, or a
        read that failed — and callers must treat it as "do not filter" rather
        than "no error is detectable". Reading it the other way would silently
        drop every problem tag and quietly undo exercise matching.

        `active_only=False` is for the authoring surface, which must be able to
        see a retired entry in order to bring it back.
        """
        try:
            query = self.client.table("speaking_error").select("*")
            if active_only:
                query = query.eq("active", True)
            return query.order("error_id").execute().data or []
        except Exception as e:
            logger.warning("list_speaking_errors failed: %s", e)
            return []

    def get_speaking_error(self, error_id: str) -> Optional[dict]:
        if not error_id:
            return None
        try:
            res = (self.client.table("speaking_error").select("*")
                   .eq("error_id", str(error_id)).limit(1).execute())
            return (res.data or [None])[0]
        except Exception as e:
            logger.warning("get_speaking_error failed id=%s: %s", error_id, e)
            return None

    def upsert_speaking_error(self, row: dict) -> Optional[dict]:
        """Write one library entry.

        The caller owns the rule that this may only ever write `observed`
        entries — an upsert that carried `status` would otherwise demote a
        detected error and silently stop it routing exercises.
        """
        if not isinstance(row, dict) or not row.get("error_id"):
            return None
        payload = dict(row)
        payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        try:
            res = (self.client.table("speaking_error")
                   .upsert(payload, on_conflict="error_id").execute())
            return (res.data or [None])[0]
        except Exception as e:
            logger.warning("upsert_speaking_error failed id=%s: %s",
                           row.get("error_id"), e)
            return None

    def get_diagnostic_exercise(self, exercise_id: str) -> Optional[dict]:
        """The live row whatever its state (the authoring read; the serving
        read is get_active_diagnostic_exercise)."""
        if not exercise_id:
            return None
        try:
            res = (self.client.table("diagnostic_exercise").select("*")
                   .eq("exercise_id", str(exercise_id)).limit(1).execute())
            return (res.data or [None])[0]
        except Exception as e:
            logger.warning("get_diagnostic_exercise failed id=%s: %s",
                           exercise_id, e, exc_info=True)
            return None

    def record_exercise_version(self, row: dict) -> Optional[dict]:
        """One immutable version row (migration 0399), insert-once. Raises
        on failure so the caller can log it; the live row stands."""
        result = self.client.rpc("record_exercise_version_v1",
                                 {"p_row": row}).execute()
        return self._rpc_row(result.data)

    def set_exercise_version_transcript(
        self, *, exercise_id: str, version: int, status: str,
        transcript: Optional[dict], language: Optional[str],
    ) -> Optional[dict]:
        """The transcript's one arrival on a pending version row (0399).
        Raises the database's refusal to the caller."""
        result = self.client.rpc("set_exercise_version_transcript_v1", {
            "p_exercise_id": str(exercise_id),
            "p_version": int(version),
            "p_status": str(status),
            "p_transcript": transcript,
            "p_language": language,
        }).execute()
        return self._rpc_row(result.data)

    def list_exercise_versions(self, exercise_id: str) -> list[dict]:
        """Every version row of one exercise, newest first, without the
        transcript body (0399)."""
        if not exercise_id:
            return []
        try:
            res = (self.client.table("diagnostic_exercise_version")
                   .select("id,exercise_id,version,title,source,created_by,"
                           "created_at,transcript_status,transcript_language,"
                           "video_sha256,video_bytes,explanation_video_url,"
                           "ai_draft_model_version")
                   .eq("exercise_id", str(exercise_id))
                   .order("version", desc=True).execute())
            return res.data or []
        except Exception as e:
            logger.warning("list_exercise_versions failed id=%s: %s",
                           exercise_id, e, exc_info=True)
            return []

    def get_exercise_version_transcript(
        self, exercise_id: str, version: int,
    ) -> Optional[dict]:
        """One version row's transcript state (0399): {transcript_status,
        transcript}. The walk's pair reads the video's transcript here as
        the second final. None when absent or unreadable."""
        if not exercise_id:
            return None
        try:
            res = (self.client.table("diagnostic_exercise_version")
                   .select("exercise_id,version,transcript_status,transcript")
                   .eq("exercise_id", str(exercise_id))
                   .eq("version", int(version)).limit(1).execute())
            return (res.data or [None])[0]
        except Exception as e:
            logger.warning("get_exercise_version_transcript failed id=%s v=%s: %s",
                           exercise_id, version, e, exc_info=True)
            return None

    def upsert_diagnostic_exercise(self, row: dict) -> Optional[dict]:
        if not isinstance(row, dict) or not row.get("exercise_id"):
            return None
        payload = dict(row)
        payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        try:
            res = (self.client.table("diagnostic_exercise")
                   .upsert(payload, on_conflict="exercise_id").execute())
            return (res.data or [None])[0]
        except Exception as e:
            logger.warning("upsert_diagnostic_exercise failed id=%s: %s",
                           row.get("exercise_id"), e)
            return None

    def set_diagnostic_exercise_active(self, exercise_id: str, active: bool) -> Optional[dict]:
        """Retire (False) or bring back (True) one exercise: the flag only,
        nothing else on the row changes (D-CP-9). None on failure."""
        try:
            res = (self.client.table("diagnostic_exercise")
                   .update({"active": bool(active),
                            "updated_at": datetime.now(timezone.utc).isoformat()})
                   .eq("exercise_id", str(exercise_id)).execute())
            return (res.data or [None])[0]
        except Exception as e:
            logger.warning("set_diagnostic_exercise_active failed id=%s: %s",
                           exercise_id, e, exc_info=True)
            return None

    # ── A coach names the error on one moment, and teaches the library ────
    # migrations/a_coach_names_the_error_and_teaches_the_library.sql. Every
    # method here degrades to "nothing" on failure — a pending migration, or a
    # read that failed — so the coach's save itself never depends on them.

    def list_coach_moment_error_events(self, practice_id: str) -> list[dict]:
        """Every naming event on one moment, in the order they happened."""
        if not practice_id:
            return []
        try:
            res = (self.client.table("coach_moment_error_event")
                   .select("error_id,action,coach_id,created_at,seq")
                   .eq("practice_id", str(practice_id))
                   .order("seq").execute())
            return res.data or []
        except Exception as e:
            logger.warning("list_coach_moment_error_events failed "
                           "practice=%s: %s", practice_id, e)
            return []

    def insert_coach_moment_error_event(
        self, practice_id: Optional[str], error_id: str, coach_id: str,
        action: str, *, snippet_id: Optional[str] = None,
        take_session_id: Optional[str] = None,
    ) -> Optional[dict]:
        """Append one naming event. Never an update: the history is the record.
        Keyed by the practice row, or (0402) by the moment itself."""
        if action not in ("named", "withdrawn"):
            return None
        if not practice_id and not snippet_id:
            return None
        try:
            payload: dict[str, Any] = {
                "practice_id": str(practice_id) if practice_id else None,
                "error_id": str(error_id),
                "coach_id": str(coach_id),
                "action": action,
            }
            if snippet_id:
                payload["snippet_id"] = str(snippet_id)
                payload["take_session_id"] = (str(take_session_id)
                                              if take_session_id else None)
            res = (self.client.table("coach_moment_error_event")
                   .insert(payload).execute())
            return (res.data or [None])[0]
        except Exception as e:
            logger.warning("insert_coach_moment_error_event failed "
                           "practice=%s error=%s: %s", practice_id, error_id, e)
            return None

    def teach_diagnostic_exercise(
        self, exercise_id: str, practice_id: str, coach_id: str,
        error_ids: list[str], source: str,
    ) -> Optional[list[dict]]:
        """Record that an exercise fixes these errors; None when it could not.

        One atomic call (teach_diagnostic_exercise_v1): the tag and its log row
        land together or not at all.
        """
        try:
            result = self.client.rpc("teach_diagnostic_exercise_v1", {
                "p_exercise_id": str(exercise_id),
                "p_practice_id": str(practice_id),
                "p_coach_id": str(coach_id),
                "p_error_ids": [str(e) for e in error_ids],
                "p_source": str(source),
            }).execute()
        except Exception as e:
            logger.warning("teach_diagnostic_exercise failed exercise=%s "
                           "practice=%s: %s", exercise_id, practice_id, e)
            return None
        data = result.data
        if isinstance(data, list):
            return [row for row in data if isinstance(row, dict)]
        return None

    def undo_diagnostic_exercise_teaching(
        self, teaching_id: str, practice_id: str, coach_id: str,
    ) -> Optional[dict]:
        try:
            result = self.client.rpc("undo_diagnostic_exercise_teaching_v1", {
                "p_teaching_id": str(teaching_id),
                "p_practice_id": str(practice_id),
                "p_coach_id": str(coach_id),
            }).execute()
        except Exception as e:
            logger.warning("undo_diagnostic_exercise_teaching failed id=%s: %s",
                           teaching_id, e)
            return None
        data = result.data
        if isinstance(data, list):
            data = data[0] if data else None
        return data if isinstance(data, dict) else None

    def list_diagnostic_exercise_teachings(self, practice_id: str) -> list[dict]:
        """Every teaching row made from one moment, taught and undone alike."""
        if not practice_id:
            return []
        try:
            res = (self.client.table("diagnostic_exercise_teaching")
                   .select("id,exercise_id,error_id,action,changed_tags,"
                           "undoes_id,seq")
                   .eq("practice_id", str(practice_id))
                   .order("seq").execute())
            return res.data or []
        except Exception as e:
            logger.warning("list_diagnostic_exercise_teachings failed "
                           "practice=%s: %s", practice_id, e)
            return []

    def get_mlc2_training_consent_status(
        self, acquisition_principal_id: str,
    ) -> Optional[dict]:
        """The one training-yes reader (0373). None when it cannot answer."""
        try:
            result = self.client.rpc("get_mlc2_training_consent_status_v2", {
                "p_acquisition_principal_id": str(acquisition_principal_id),
            }).execute()
            data = result.data
            return data if isinstance(data, dict) else self._rpc_row(data)
        except Exception as e:
            logger.warning("training consent status failed principal=%s: %s",
                           acquisition_principal_id, e)
            return None

    def record_training_corpus_item(self, item: dict) -> Optional[dict]:
        """One training copy (0374). Raises when the database refuses it."""
        result = self.client.rpc("record_training_corpus_item_v1", {
            "p_acquisition_principal_id": item["acquisition_principal_id"],
            "p_training_grant_event_id": item["training_grant_event_id"],
            "p_source_project_id": item["source_project_id"],
            "p_source_take_id": item["source_take_id"],
            "p_source_ref": item["source_ref"],
            "p_source_sha256": item["source_sha256"],
            "p_item_kind": item["item_kind"],
            "p_label_provenance": item.get("label_provenance"),
            "p_content": item.get("content"),
            "p_storage_provider": item.get("storage_provider"),
            "p_bucket": item.get("bucket"),
            "p_storage_key": item.get("storage_key"),
            "p_object_sha256": item.get("object_sha256"),
        }).execute()
        return self._rpc_row(result.data)

    def list_due_training_corpus_items(
        self, acquisition_principal_id: str,
    ) -> list[dict]:
        """A person's copies a withdrawal or the account purge made due."""
        try:
            return (self.client.table("training_corpus_items")
                    .select("id,state,storage_provider,bucket,storage_key,"
                            "object_sha256")
                    .eq("acquisition_principal_id", str(acquisition_principal_id))
                    .in_("state", ["purge_pending", "purged"])
                    .execute().data or [])
        except Exception as e:
            logger.warning("due training copies read failed principal=%s: %s",
                           acquisition_principal_id, e)
            return []

    def get_active_training_consent_policy(self) -> Optional[dict]:
        """The training-only policy in force now, with its approved switch
        wording (0373). None when there is none, or when it cannot be read."""
        now = datetime.now(timezone.utc).isoformat()
        try:
            policies = (self.client.table("ml_consent_policies")
                        .select("version,product_legal_approval_id,"
                                "active_from,retired_at")
                        .eq("grant_scope", "training_only")
                        .lte("active_from", now)
                        .execute().data or [])
            live = [row for row in policies
                    if not row.get("retired_at") or row["retired_at"] > now]
            if len(live) != 1:
                return None
            approval = (self.client.table("ml_product_legal_approvals")
                        .select("onboarding_copy,approved_copy_sha256,"
                                "terms_version,privacy_policy_version")
                        .eq("id", str(live[0]["product_legal_approval_id"]))
                        .limit(1).execute().data or [])
            if not approval:
                return None
            return {"version": live[0]["version"], **approval[0]}
        except Exception as e:
            logger.warning("training consent policy read failed: %s", e)
            return None

    def record_mlc2_training_consent_grant(
        self, *, acquisition_principal_id: str, consent_policy_version: str,
        terms_version: str, privacy_policy_version: str, source_route: str,
        client_version: str, affirmative_action: dict, occurred_at: str,
        idempotency_key: str,
    ) -> Optional[dict]:
        """The training yes (0373). Raises when the database refuses it."""
        result = self.client.rpc("record_mlc2_training_consent_grant_v2", {
            "p_acquisition_principal_id": str(acquisition_principal_id),
            "p_consent_policy_version": str(consent_policy_version),
            "p_jurisdiction": "PL/EU",
            "p_terms_version": str(terms_version),
            "p_privacy_policy_version": str(privacy_policy_version),
            "p_source_route": str(source_route),
            "p_client_version": str(client_version),
            "p_affirmative_action": dict(affirmative_action),
            "p_occurred_at": str(occurred_at),
            "p_idempotency_key": str(idempotency_key),
        }).execute()
        return self._rpc_row(result.data)

    def record_mlc2_training_consent_withdrawal(
        self, *, acquisition_principal_id: str, grant_event_id: str,
        source_route: str, client_version: str, affirmative_action: dict,
        occurred_at: str, idempotency_key: str,
    ) -> Optional[dict]:
        """Turning training off (0373, 0376: the copies become due in the
        same transaction). Raises when the database refuses it."""
        result = self.client.rpc("record_mlc2_consent_withdrawal_v2", {
            "p_acquisition_principal_id": str(acquisition_principal_id),
            "p_grant_event_id": str(grant_event_id),
            "p_purpose": "pooled_model_improvement",
            "p_source_route": str(source_route),
            "p_client_version": str(client_version),
            "p_affirmative_action": dict(affirmative_action),
            "p_occurred_at": str(occurred_at),
            "p_idempotency_key": str(idempotency_key),
        }).execute()
        return self._rpc_row(result.data)

    def accept_mlc2_training_consent(
        self, *, acquisition_principal_id: str, consent_policy_version: str,
        terms_version: str, privacy_policy_version: str, source_route: str,
        client_version: str, affirmative_action: dict, occurred_at: str,
        idempotency_key: str, identity_hash: str, identity_version: str,
        binding_proof_hash: str, bound_by: str,
    ) -> Optional[dict]:
        """The training yes and the speaker binding in one transaction
        (0430, N48.5 Q27 A; F-3). Raises when the database refuses the yes;
        every refusal of record_mlc2_training_consent_grant_v2 stands."""
        result = self.client.rpc("accept_mlc2_training_consent_v1", {
            "p_acquisition_principal_id": str(acquisition_principal_id),
            "p_consent_policy_version": str(consent_policy_version),
            "p_jurisdiction": "PL/EU",
            "p_terms_version": str(terms_version),
            "p_privacy_policy_version": str(privacy_policy_version),
            "p_source_route": str(source_route),
            "p_client_version": str(client_version),
            "p_affirmative_action": dict(affirmative_action),
            "p_occurred_at": str(occurred_at),
            "p_idempotency_key": str(idempotency_key),
            "p_identity_hash": str(identity_hash),
            "p_identity_version": str(identity_version),
            "p_binding_proof_hash": str(binding_proof_hash),
            "p_bound_by": str(bound_by),
        }).execute()
        data = result.data
        return data if isinstance(data, dict) else self._rpc_row(data)

    def bind_mlc2_training_speaker(
        self, *, acquisition_principal_id: str, identity_hash: str,
        identity_version: str, binding_proof_hash: str, bound_by: str,
    ) -> Optional[dict]:
        """Bind the speaker of a person who already holds an active training
        yes (0430). Writes nothing without a yes; keeps an existing binding.
        None when nothing is bound or the call fails (never raises)."""
        try:
            result = self.client.rpc("bind_mlc2_training_speaker_v1", {
                "p_acquisition_principal_id": str(acquisition_principal_id),
                "p_identity_hash": str(identity_hash),
                "p_identity_version": str(identity_version),
                "p_binding_proof_hash": str(binding_proof_hash),
                "p_bound_by": str(bound_by),
            }).execute()
        except Exception as e:
            logger.warning("training speaker binding failed principal=%s: %s",
                           acquisition_principal_id, e, exc_info=True)
            return None
        row = self._rpc_row(result.data)
        return row if row and row.get("id") else None

    def get_mlc2_blind_coach_ratings(
        self, take_id: str, snippet_ids: list[str],
    ) -> dict[str, str]:
        """``{snippet_id: decision}``: the latest blind coach judgement per
        snippet of one Take, from the chain's ml_judgments (0430). Empty on
        any failure. Never an owner, peer or machine answer."""
        ids = [str(s) for s in (snippet_ids or []) if s]
        if not take_id or not ids:
            return {}
        try:
            result = self.client.rpc("get_mlc2_blind_coach_ratings_v1", {
                "p_take_id": str(take_id), "p_snippet_ids": ids,
            }).execute()
        except Exception as e:
            logger.warning("blind coach ratings read failed take=%s: %s",
                           take_id, e, exc_info=True)
            return {}
        rows = result.data if isinstance(result.data, list) else []
        return {str(row["snippet_id"]): str(row["decision"]) for row in rows
                if isinstance(row, dict) and row.get("snippet_id")
                and row.get("decision")}

    def get_speaker_splits_for_principals(
        self, principal_ids: list[str], split_policy_version: str,
    ) -> dict[str, str]:
        """``{acquisition_principal_id: split}``: each principal's bound
        speaker's assignment under the split policy (MLC-2 F-3,
        ``get_mlc2_speaker_splits_v1``, 0430; services/speaker_split.py). A
        principal with no bound speaker is absent. Raises on a failed read;
        the caller names it."""
        ids = sorted({str(p) for p in (principal_ids or []) if p})
        out: dict[str, str] = {}
        for start in range(0, len(ids), 500):
            result = self.client.rpc("get_mlc2_speaker_splits_v1", {
                "p_acquisition_principal_ids": ids[start:start + 500],
                "p_split_policy_version": str(split_policy_version),
            }).execute()
            for row in result.data or []:
                if isinstance(row, dict) and row.get("acquisition_principal_id"):
                    out[str(row["acquisition_principal_id"])] = str(row.get("split") or "")
        return out

    def get_pair_release_manifests(self, release_ids: list[str]) -> dict[str, dict]:
        """``{release_id: manifest}`` for door 3, which trains each pair
        under the split its release used (F-3). Raises."""
        ids = sorted({str(r) for r in (release_ids or []) if r})
        rows: list[dict] = []
        for start in range(0, len(ids), 200):
            rows += (self.client.table("pair_releases")
                     .select("id,manifest")
                     .in_("id", ids[start:start + 200])
                     .execute().data or [])
        return {str(r["id"]): (r.get("manifest") if isinstance(r.get("manifest"), dict) else {})
                for r in rows if isinstance(r, dict) and r.get("id")}

    def list_principals_with_due_training_copies(self, limit: int = 20) -> list[str]:
        """People with copies a withdrawal or the account purge made due."""
        try:
            rows = (self.client.table("training_corpus_items")
                    .select("acquisition_principal_id")
                    .in_("state", ["purge_pending", "purged"])
                    .limit(max(1, int(limit)) * 20)
                    .execute().data or [])
        except Exception as e:
            logger.warning("due training copies scan failed: %s", e)
            return []
        out: list[str] = []
        for row in rows:
            principal = str(row.get("acquisition_principal_id") or "")
            if principal and principal not in out:
                out.append(principal)
        return out[:max(1, int(limit))]

    def list_training_moments(self, limit: int = 100) -> list[dict]:
        """Active training copies of a moment's words and of its coach label,
        newest first, for the late coach-label copy."""
        try:
            return (self.client.table("training_corpus_items")
                    .select("acquisition_principal_id,training_grant_event_id,"
                            "source_project_id,source_take_id,source_ref,"
                            "item_kind")
                    .eq("state", "active")
                    .in_("item_kind", ["transcript_span", "coach_label"])
                    .order("created_at", desc=True)
                    .limit(max(1, int(limit)))
                    .execute().data or [])
        except Exception as e:
            logger.warning("training moments read failed: %s", e)
            return []

    def erase_training_corpus_item(self, item_id: str) -> bool:
        """Erase one DUE copy's row. The state filter is the guard: an active
        copy is never erased here, only one a withdrawal or purge moved."""
        try:
            rows = (self.client.table("training_corpus_items").delete()
                    .eq("id", str(item_id))
                    .in_("state", ["purge_pending", "purged"])
                    .execute().data or [])
            return bool(rows)
        except Exception as e:
            logger.warning("training copy erase failed item=%s: %s", item_id, e)
            return False

    def get_take_audio_object(self, take_session_id: str) -> Optional[dict]:
        """The Take's own recording object (processing_audio_objects)."""
        if not take_session_id:
            return None
        try:
            rows = (self.client.table("processing_audio_objects")
                    .select("id,storage_provider,bucket,object_key,"
                            "exact_bytes_sha256")
                    .eq("recording_attempt_id", str(take_session_id))
                    .is_("deleted_at", "null")
                    .limit(1).execute().data or [])
            return rows[0] if rows else None
        except Exception as e:
            logger.warning("take audio object read failed sid=%s: %s",
                           take_session_id, e)
            return None

    def assign_confident_voice_exercise(
        self, *, owner_user_id: str, take_session_id: str, snippet_id: str,
        lane: str, matching_policy_version: str, candidates: list[dict],
        trace: Optional[dict] = None,
    ) -> Optional[dict]:
        """The moment's frozen 80/20 exercise choice (migration 0372), and
        with a ``trace``, why it was made (migration 0384, written by the same
        call that draws).

        Idempotent: the first call draws, every later call returns that row.
        Raises on failure so the caller can fall back to the best match.
        """
        params = {
            "p_owner_user_id": str(owner_user_id),
            "p_take_session_id": str(take_session_id),
            "p_snippet_id": str(snippet_id),
            "p_lane": str(lane),
            "p_matching_policy_version": str(matching_policy_version),
            "p_candidates": candidates,
        }
        if trace is not None:
            try:
                result = self.client.rpc(
                    "assign_confident_voice_exercise_v2",
                    {**params, "p_trace": trace}).execute()
                return self._rpc_row(result.data)
            except Exception as e:  # noqa: BLE001 — only "not installed" falls back
                # PGRST202: the function is not in PostgREST's schema cache,
                # i.e. 0384 has not been applied yet. Draw without the trace
                # rather than serve no exercise. Any other failure (a trace
                # the database refuses) is raised: a draw whose reasons were
                # rejected must not be made silently without them.
                if "PGRST202" not in str(e):
                    raise
                logger.warning(
                    "assign_confident_voice_exercise_v2 missing; drawing "
                    "without a match trace sid=%s", take_session_id)
        result = self.client.rpc(
            "assign_confident_voice_exercise_v1", params).execute()
        return self._rpc_row(result.data)

    def record_exercise_rendered(
        self, *, owner_user_id: str, take_session_id: str, snippet_id: str,
        exercise_id: str,
    ) -> Optional[dict]:
        """The exposure for one assignment (migration 0387), recorded once.
        Raises the database's refusal (EXERCISE_RENDERED_*) to the caller.

        v2 (0398) finds the assignment whose selected exercise is the
        rendered one under any policy, so a coach-shared card counts; v1 is
        the fallback only while 0398 is not applied (PGRST202)."""
        params = {
            "p_owner_user_id": str(owner_user_id),
            "p_take_session_id": str(take_session_id),
            "p_snippet_id": str(snippet_id),
            "p_exercise_id": str(exercise_id),
        }
        try:
            result = self.client.rpc("record_exercise_rendered_v2", params).execute()
            return self._rpc_row(result.data)
        except Exception as e:  # noqa: BLE001 — only "not installed" falls back
            if "PGRST202" not in str(e):
                raise
            logger.warning("record_exercise_rendered_v2 missing; using v1 "
                           "sid=%s", take_session_id)
        result = self.client.rpc("record_exercise_rendered_v1", params).execute()
        return self._rpc_row(result.data)

    def assign_coach_shared_exercise(
        self, *, owner_user_id: str, take_session_id: str, snippet_id: str,
        lane: str, matching_policy_version: str, exercise_id: str,
        exercise_version: int, trace: dict,
    ) -> Optional[dict]:
        """A coach-shared exercise frozen as the moment's coach assignment
        with its trace (migration 0398), insert-once: the first call writes,
        every later call returns that row. Raises on failure so the caller
        can serve without it."""
        result = self.client.rpc("assign_coach_shared_exercise_v1", {
            "p_owner_user_id": str(owner_user_id),
            "p_take_session_id": str(take_session_id),
            "p_snippet_id": str(snippet_id),
            "p_lane": str(lane),
            "p_matching_policy_version": str(matching_policy_version),
            "p_exercise_id": str(exercise_id),
            "p_exercise_version": int(exercise_version),
            "p_trace": trace,
        }).execute()
        return self._rpc_row(result.data)

    def get_coach_shared_exercise_assignment(
        self, take_session_id: str, snippet_id: str,
    ) -> Optional[dict]:
        """The moment's frozen coach assignment (0398), or None."""
        if not take_session_id or not snippet_id:
            return None
        try:
            res = (self.client.table("confident_voice_exercise_assignments")
                   .select("id,selected_exercise_id,selected_exercise_version,"
                           "selection_mode,exposure_policy_version,lane,"
                           "matching_policy_version")
                   .eq("take_session_id", str(take_session_id))
                   .eq("snippet_id", str(snippet_id))
                   .eq("exposure_policy_version", "exercise-coach-shared-v1")
                   .limit(1).execute())
            return (res.data or [None])[0]
        except Exception as e:
            logger.warning(
                "get_coach_shared_exercise_assignment failed sid=%s: %s",
                take_session_id, e, exc_info=True)
            return None

    def record_practice_more_confident(
        self, *, practice_id: str, attempt_id: str,
    ) -> Optional[dict]:
        """Recompute one practice's "sounds more confident" result from what
        is stored (migration 0388). Raises the database's refusal
        (PRACTICE_MORE_CONFIDENT_*) to the caller."""
        result = self.client.rpc("record_practice_more_confident_v1", {
            "p_practice_id": str(practice_id),
            "p_attempt_id": str(attempt_id),
        }).execute()
        return self._rpc_row(result.data)

    def get_exercise_match_trace(self, assignment_id: str) -> Optional[dict]:
        """The match trace frozen with one assignment (migration 0384), or
        None — also for an assignment drawn before traces existed."""
        if not assignment_id:
            return None
        try:
            res = (self.client.table("confident_voice_exercise_match_traces")
                   .select("trace,trace_sha256,created_at")
                   .eq("assignment_id", str(assignment_id))
                   .limit(1).execute())
            return (res.data or [None])[0]
        except Exception as e:
            logger.warning("get_exercise_match_trace failed asg=%s: %s",
                           assignment_id, e)
            return None

    def list_match_trace_tags(self, since: str) -> list[list[str]]:
        """The patterns that fired on each exercise moment traced since
        `since` (migration 0384): one list per assignment. Raises on
        failure — the gap view names an unreadable source instead of
        reading it as zero."""
        res = (self.client.table("confident_voice_exercise_match_traces")
               .select("observed_tags:trace->observed_tags")
               .gte("created_at", since).execute())
        return [row.get("observed_tags") or [] for row in res.data or []
                if isinstance(row, dict)]

    # ---- step 8 prep: the learning-readiness count ------------------------
    # Each read raises on failure: the count names an unreadable source
    # instead of reading it as zero (services/exercise_learning_readiness.py).

    @staticmethod
    def _chunks(ids: list[str], size: int = 100) -> list[list[str]]:
        return [ids[i:i + size] for i in range(0, len(ids), size)]

    def list_exercise_exposures(self) -> list[dict]:
        """Every confirmed exercise render (migration 0387), paged so the
        server's row cap can never cut the count short."""
        rows: list[dict] = []
        page = 1000
        while True:
            res = (self.client.table("confident_voice_exercise_exposures")
                   .select("assignment_id,owner_user_id,exercise_id,"
                           "exercise_version,rendered_at")
                   .order("rendered_at").order("assignment_id")
                   .range(len(rows), len(rows) + page - 1).execute())
            batch = list(res.data or [])
            rows.extend(batch)
            if len(batch) < page:
                return rows

    def get_exercise_assignments(self, ids: list[str]) -> dict[str, dict]:
        """The 80/20 facts of these assignments (0372), by id, with every
        candidate's stored probability (the fair test weights by it)."""
        out: dict[str, dict] = {}
        for chunk in self._chunks(ids):
            res = (self.client.table("confident_voice_exercise_assignments")
                   .select("id,selection_mode,below_minimum_probability,"
                           "candidates")
                   .in_("id", chunk).execute())
            out.update({str(r["id"]): r for r in res.data or []
                        if isinstance(r, dict) and r.get("id")})
        return out

    def get_exercise_match_traces(self, ids: list[str]) -> dict[str, dict]:
        """The frozen trace of each assignment (0384), by assignment id."""
        out: dict[str, dict] = {}
        for chunk in self._chunks(ids):
            res = (self.client.table("confident_voice_exercise_match_traces")
                   .select("assignment_id,trace")
                   .in_("assignment_id", chunk).execute())
            for row in res.data or []:
                if isinstance(row, dict) and isinstance(row.get("trace"), dict):
                    out[str(row["assignment_id"])] = row["trace"]
        return out

    def get_practices_for_assignments(self, ids: list[str]) -> dict[str, dict]:
        """The first practice opened on each assignment, by assignment id.

        A practice names its assignment two ways: the one it was started on
        (machine_assessment, the machine pick or the answered call) and the
        one a coach attached to it in the review (coach_shared_exercise,
        0398). Both are read; the earliest practice per assignment wins."""
        out: dict[str, dict] = {}
        for column in ("machine_assessment", "coach_shared_exercise"):
            for chunk in self._chunks(ids):
                res = (self.client.table("confident_voice_practice")
                       .select("id,created_at,"
                               f"assignment_id:{column}->>exercise_assignment_id")
                       .in_(f"{column}->>exercise_assignment_id", chunk)
                       .order("created_at").execute())
                for row in res.data or []:
                    key = str((row or {}).get("assignment_id") or "")
                    if key and (key not in out or str(row.get("created_at") or "")
                                < str(out[key].get("created_at") or "")):
                        out[key] = row
        return out

    def list_attempts_for_practices(self, ids: list[str]) -> dict[str, list[dict]]:
        """Each practice's saved attempts, without audio or transcript."""
        out: dict[str, list[dict]] = {}
        for chunk in self._chunks(ids):
            res = (self.client.table("confident_voice_practice_attempt")
                   .select("practice_id,attempt_index,duration_ms,audio_ref,"
                           "acoustic_metrics")
                   .in_("practice_id", chunk).execute())
            for row in res.data or []:
                if isinstance(row, dict) and row.get("practice_id"):
                    out.setdefault(str(row["practice_id"]), []).append(row)
        return out

    def list_exercise_coach_requests(self, since: str) -> list[dict]:
        """Coach requests made since `since` (migration 0385), without their
        traces. Raises on failure."""
        res = (self.client.table("exercise_coach_requests")
               .select("reason,observed_tags,resolution,created_at,"
                       "kind,answer_kind,raised_on")
               .gte("created_at", since).execute())
        return list(res.data or [])

    def count_verbal_cue_shadow(self, error_id: str, since: str) -> dict:
        """{clips_measured, clips_fired} for one shadow cue since `since`
        (migration 0386), at any detector version. Raises on failure."""
        def _count(fired: Optional[bool]) -> int:
            query = (self.client.table("verbal_cue_shadow_observations")
                     .select("id", count="exact")
                     .eq("error_id", error_id).gte("created_at", since))
            if fired is not None:
                query = query.eq("fired", fired)
            return int(query.limit(1).execute().count or 0)
        return {"clips_measured": _count(None), "clips_fired": _count(True)}

    def record_verbal_cue_shadow(self, rows: list[dict]) -> int:
        """One Take's shadow-stage verdicts (migration 0386), insert-once per
        (clip, cue, detector version). Returns how many were new. Raises on
        failure; the caller runs under DegradationLog."""
        result = self.client.rpc(
            "record_verbal_cue_shadow_v1", {"p_rows": rows}).execute()
        data = result.data
        if isinstance(data, list):
            data = data[0] if data else 0
        return int(data or 0)

    def list_verbal_cue_shadow_observations(
        self, error_id: str, detector_version: str,
    ) -> list[dict]:
        """Every logged verdict for one cue at one version (internal report)."""
        res = (self.client.table("verbal_cue_shadow_observations")
               .select("snippet_id,take_session_id,language,fired,created_at")
               .eq("error_id", error_id)
               .eq("detector_version", detector_version)
               .execute())
        return list(res.data or [])

    def list_coach_named_moments(self, error_id: str) -> list[dict]:
        """Every practice moment on which a coach's latest event for this error
        is 'named' — independent of any shadow verdict, which is never shown
        to them. Returns [{practice_id, snippet_id}]."""
        events = (self.client.table("coach_moment_error_event")
                  .select("practice_id,snippet_id,action,seq")
                  .eq("error_id", error_id)
                  .order("seq").execute()).data or []
        latest: dict[str, str] = {}
        by_snippet: dict[str, str] = {}
        for row in events:
            if row.get("practice_id"):
                latest[str(row.get("practice_id"))] = str(row.get("action"))
            elif row.get("snippet_id"):
                # Named on the moment itself (0402): no practice row to join.
                by_snippet[str(row.get("snippet_id"))] = str(row.get("action"))
        out = [{"practice_id": None, "snippet_id": sid}
               for sid, action in by_snippet.items() if action == "named"]
        named = [pid for pid, action in latest.items() if action == "named"]
        if not named:
            return out
        practices = (self.client.table("confident_voice_practice")
                     .select("id,snippet_id")
                     .in_("id", named).execute()).data or []
        return out + [{"practice_id": str(p.get("id")),
                       "snippet_id": str(p.get("snippet_id"))} for p in practices]

    def request_exercise_from_coach(
        self, *, owner_user_id: str, take_session_id: str, snippet_id: str,
        reason: str, pattern: Optional[str], observed_tags: list[str],
        request_trace: dict, kind: str = "error",
        raised_on: str = "judgement",
    ) -> Optional[dict]:
        """The moment's coach request (migration 0385; its kind, 0397; where
        it rose, 0408): recorded on the first call, returned unchanged — with
        any resolution since — on every later one. Raises on failure; the
        caller keeps the feedback regardless.

        A request raised at the open (F1, `raised_on` 'open') goes through
        v3; without 0408 (PGRST202) v2 records it as a judgement-time one,
        logged. Without 0397 (PGRST202 on v2) the v1 function records it
        without a kind, except a 'library_matched' request, which v1 cannot
        hold."""
        params = {
            "p_owner_user_id": str(owner_user_id),
            "p_take_session_id": str(take_session_id),
            "p_snippet_id": str(snippet_id),
            "p_reason": str(reason),
            "p_pattern": pattern,
            "p_observed_tags": list(observed_tags),
            "p_request_trace": request_trace,
        }
        if raised_on != "judgement":
            try:
                result = self.client.rpc(
                    "request_exercise_from_coach_v3",
                    {**params, "p_kind": str(kind),
                     "p_raised_on": str(raised_on)}).execute()
                return self._rpc_row(result.data)
            except Exception as e:  # noqa: BLE001 — only "not installed" falls back
                if "PGRST202" not in str(e):
                    raise
                logger.warning("request_exercise_from_coach_v3 missing; "
                               "recording as raised at the judgement sid=%s",
                               take_session_id, exc_info=True)
        try:
            result = self.client.rpc("request_exercise_from_coach_v2",
                                     {**params, "p_kind": str(kind)}).execute()
            return self._rpc_row(result.data)
        except Exception as e:  # noqa: BLE001 — only "not installed" falls back
            if "PGRST202" not in str(e):
                raise
            if reason == "library_matched":
                return None
            logger.warning("request_exercise_from_coach_v2 missing; recording "
                           "without a kind sid=%s", take_session_id, exc_info=True)
        result = self.client.rpc("request_exercise_from_coach_v1", params).execute()
        return self._rpc_row(result.data)

    def get_exercise_coach_request(
        self, take_session_id: str, snippet_id: str,
    ) -> Optional[dict]:
        if not take_session_id or not snippet_id:
            return None
        try:
            res = (self.client.table("exercise_coach_requests")
                   .select("*")
                   .eq("take_session_id", str(take_session_id))
                   .eq("snippet_id", str(snippet_id))
                   .limit(1).execute())
            return (res.data or [None])[0]
        except Exception as e:
            logger.warning("get_exercise_coach_request failed sid=%s: %s",
                           take_session_id, e)
            return None

    def get_exercise_coach_request_by_id(self, request_id: str) -> Optional[dict]:
        """One request by its id: the walk's exercise is filed under
        ``coach-request-<id>`` (the upload seam), and the server reads the
        model draft the pair stands on from the request itself, never from
        the client (C5, FL-L3). None when absent or unreadable."""
        if not request_id:
            return None
        try:
            res = (self.client.table("exercise_coach_requests").select("*")
                   .eq("id", str(request_id)).limit(1).execute())
            return (res.data or [None])[0]
        except Exception as e:
            logger.warning("get_exercise_coach_request_by_id failed id=%s: %s",
                           request_id, e, exc_info=True)
            return None

    def resolve_exercise_coach_request(
        self, *, request_id: str, coach_id: str, resolution: str,
        exercise_id: Optional[str], exercise_version: Optional[int],
        share: bool, answer_text: Optional[str] = None,
    ) -> Optional[dict]:
        """Resolve once, share once (migration 0385; in words 0402). Raises the
        database's refusal (e.g. EXERCISE_COACH_REQUEST_ALREADY_RESOLVED) to
        the caller."""
        params = {
            "p_request_id": str(request_id),
            "p_coach_id": str(coach_id),
            "p_resolution": str(resolution),
            "p_exercise_id": exercise_id,
            "p_exercise_version": exercise_version,
            "p_share": bool(share),
        }
        if answer_text is None:
            result = self.client.rpc(
                "resolve_exercise_coach_request_v1", params).execute()
        else:
            # An answer in words (0402): a praise line or a clearer version.
            result = self.client.rpc("resolve_exercise_coach_request_v2", {
                **params, "p_answer_text": str(answer_text)}).execute()
        return self._rpc_row(result.data)

    def set_exercise_coach_request_draft(
        self, *, request_id: str, surface: str, text: str,
        model_version: Optional[str],
    ) -> Optional[dict]:
        """Keep the model's draft on the request row (0402), coach-only; a
        re-draft replaces it. Raises on failure: the caller logs and the
        draft still shows."""
        res = (self.client.table("exercise_coach_requests")
               .update({"draft_surface": str(surface), "draft_text": str(text),
                        "draft_model_version": model_version or None,
                        "drafted_at": datetime.now(timezone.utc).isoformat()})
               .eq("id", str(request_id)).execute())
        return (res.data or [None])[0]

    def list_exercise_coach_requests_for_sessions(
        self, session_ids: list[str],
    ) -> dict[tuple[str, str], dict]:
        """Every request on these takes, keyed (take_session_id, snippet_id),
        without traces. {} on anything missing: the queue still draws."""
        ids = [str(i) for i in session_ids if i]
        if not ids:
            return {}
        try:
            res = (self.client.table("exercise_coach_requests")
                   .select("id,take_session_id,snippet_id,kind,answer_kind,"
                           "reason,resolution,resolved_at,shared_at,created_at")
                   .in_("take_session_id", ids).execute())
        except Exception as e:
            logger.warning("list_exercise_coach_requests_for_sessions failed: %s",
                           e, exc_info=True)
            return {}
        return {(str(r.get("take_session_id")), str(r.get("snippet_id"))): r
                for r in (res.data or []) if isinstance(r, dict)}

    def set_exercise_coach_request_video(
        self, *, request_id: str, video_ref: str,
    ) -> Optional[dict]:
        """The video a coach added to a written answer (0403). Raises on
        failure; the route names it."""
        res = (self.client.table("exercise_coach_requests")
               .update({"answer_video_ref": str(video_ref)})
               .eq("id", str(request_id)).execute())
        return (res.data or [None])[0]

    def set_exercise_coach_request_answer_kind(
        self, *, take_session_id: str, snippet_id: str, answer_kind: str,
        only_if_unset: bool = False,
    ) -> Optional[dict]:
        """The speaker's side of the moment's request (0408): the matrix's
        kind once they judged. `only_if_unset` leaves a kind already written
        (a first disagreement stays). None when no row changed. Raises on
        failure; the caller logs."""
        query = (self.client.table("exercise_coach_requests")
                 .update({"answer_kind": str(answer_kind),
                          "answered_at": datetime.now(timezone.utc).isoformat()})
                 .eq("take_session_id", str(take_session_id))
                 .eq("snippet_id", str(snippet_id)))
        if only_if_unset:
            query = query.is_("answer_kind", "null")
        res = query.execute()
        return (res.data or [None])[0]

    def record_moment_event(
        self, *, owner_user_id: str, take_session_id: str, snippet_id: str,
        event: str, co_exposed: dict,
    ) -> bool:
        """The speaker opened or skipped a bookmark (0408), once per (Take,
        moment, event). True when THIS call recorded it. Raises on failure."""
        res = (self.client.table("moment_events").upsert(
            {"owner_user_id": str(owner_user_id),
             "take_session_id": str(take_session_id),
             "snippet_id": str(snippet_id), "event": str(event),
             "co_exposed": co_exposed if isinstance(co_exposed, dict) else {}},
            on_conflict="take_session_id,snippet_id,event",
            ignore_duplicates=True).execute())
        return bool(res.data)

    def list_moment_events_for_take(self, take_session_id: str) -> list[dict]:
        """Every open and skip on this Take (0408), oldest first. Raises on
        failure."""
        res = (self.client.table("moment_events")
               .select("snippet_id,event,created_at")
               .eq("take_session_id", str(take_session_id))
               .order("created_at").execute())
        return list(res.data or [])

    def list_moment_events_for_sessions(
        self, take_session_ids: list[str],
    ) -> list[dict]:
        """Every open and skip on these Takes (0408): which moments reached
        the speaker, for the coach's queue (N48.2, Q1 A). Raises on failure:
        the queue then fails visibly rather than listing moments no speaker
        met."""
        ids = [str(i) for i in take_session_ids if i]
        if not ids:
            return []
        res = (self.client.table("moment_events")
               .select("take_session_id,snippet_id,event")
               .in_("take_session_id", ids).execute())
        return list(res.data or [])

    def list_confident_voice_answered_moments(
        self, take_session_ids: list[str],
    ) -> list[dict]:
        """Which Confident Voice moments the speaker ANSWERED on these Takes
        (N48.2, Q1 A): (take_session_id, snippet_id) only. The answer itself
        is never selected, so nothing here can carry it toward a coach
        (BLIND COACH). Raises on failure, like the read beside it."""
        ids = [str(i) for i in take_session_ids if i]
        if not ids:
            return []
        res = (self.client.table("take_feedback_self_report")
               .select("take_session_id,snippet_id")
               .in_("take_session_id", ids)
               .eq("feedback_family", "confident_voice")
               .execute())
        return list(res.data or [])

    def count_moment_events(self, event: str, since: str) -> int:
        """How many bookmarks were opened (or skipped) since `since` (0408).
        Raises on failure."""
        res = (self.client.table("moment_events")
               .select("id", count="exact")
               .eq("event", str(event)).gte("created_at", since)
               .limit(1).execute())
        return int(res.count or 0)

    def list_confident_voice_practice_for_take(
        self, take_session_id: str, owner_user_id: Optional[str] = None,
    ) -> list[dict]:
        """Every practice on this Take (one per moment since 0400), with the
        fields that say whether it settled its moment. Raises on failure."""
        query = (self.client.table("confident_voice_practice")
                 .select("id,snippet_id,status,final_user_answer,after_practice")
                 .eq("take_session_id", str(take_session_id)))
        if owner_user_id:
            query = query.eq("owner_user_id", str(owner_user_id))
        return list(query.execute().data or [])

    def list_landed_practices_for_take(
        self, take_session_id: str, owner_user_id: str,
    ) -> list[dict]:
        """The practices on this Take that landed (Yes or In-between on an
        attempt, 29a), oldest first, for Bold voices (0409). Raises on
        failure."""
        res = (self.client.table("confident_voice_practice")
               .select("id,snippet_id,selected_attempt_id,exact_passage,kind,closed_at")
               .eq("take_session_id", str(take_session_id))
               .eq("owner_user_id", str(owner_user_id))
               .eq("status", "completed")
               .in_("final_user_answer", ["yes", "in_between"])
               .order("closed_at").execute())
        return list(res.data or [])

    def list_coach_readings(self, coach_id: str) -> list[dict]:
        """One coach's own readings (0409), newest first. Raises on failure."""
        res = (self.client.table("coach_readings").select("*")
               .eq("coach_id", str(coach_id))
               .order("created_at", desc=True).limit(100).execute())
        return list(res.data or [])

    def list_published_coach_readings(self) -> list[dict]:
        """Every published reading (0409), newest first, WITHOUT the coach:
        the speaker hears a voice, never a name. Raises on failure."""
        res = (self.client.table("coach_readings")
               .select("id,passage,media_url,media_kind,published_at")
               .not_.is_("published_at", "null")
               .order("published_at", desc=True).limit(50).execute())
        return list(res.data or [])

    def insert_coach_reading(self, row: dict) -> Optional[dict]:
        """A coach's new reading (0409). Raises on failure."""
        res = self.client.table("coach_readings").insert(dict(row)).execute()
        return (res.data or [None])[0]

    def set_coach_reading_published(
        self, *, reading_id: str, coach_id: str, published: bool,
    ) -> Optional[dict]:
        """Publish or withdraw one's own reading (0409); None when it is not
        this coach's. Raises on failure."""
        now = datetime.now(timezone.utc).isoformat()
        res = (self.client.table("coach_readings")
               .update({"published_at": now if published else None,
                        "updated_at": now})
               .eq("id", str(reading_id)).eq("coach_id", str(coach_id))
               .execute())
        return (res.data or [None])[0]

    def mark_after_practice_step(
        self, *, owner_user_id: str, take_session_id: str, step: str,
    ) -> bool:
        """The Take showed this step (0409), once per Take per step. True
        when THIS call recorded it. Raises on failure."""
        res = (self.client.table("after_practice_steps").upsert(
            {"owner_user_id": str(owner_user_id),
             "take_session_id": str(take_session_id), "step": str(step)},
            on_conflict="take_session_id,step",
            ignore_duplicates=True).execute())
        return bool(res.data)

    def list_after_practice_steps(self, take_session_id: str) -> list[dict]:
        """Which steps this Take has shown (0409). Raises on failure."""
        res = (self.client.table("after_practice_steps")
               .select("step,shown_at")
               .eq("take_session_id", str(take_session_id)).execute())
        return list(res.data or [])

    def record_bold_voices_play(
        self, *, owner_user_id: str, take_session_id: str, clip_kind: str,
        clip_id: str,
    ) -> Optional[dict]:
        """The speaker heard a clip (0409): a receipt. Raises on failure."""
        res = self.client.table("bold_voices_plays").insert({
            "owner_user_id": str(owner_user_id),
            "take_session_id": str(take_session_id),
            "clip_kind": str(clip_kind), "clip_id": str(clip_id),
        }).execute()
        return (res.data or [None])[0]

    def count_after_practice(self, since: str) -> dict:
        """{practices_landed, bold_voices_heard, steps: {step: n}} since
        `since` (0409), for the founder's ledger. Raises on failure."""
        def _count(table: str, **eq: Any) -> int:
            query = (self.client.table(table).select("id", count="exact"))
            for column, value in eq.items():
                query = query.eq(column, value)
            return int(query.gte(self._since_column(table), since)
                       .limit(1).execute().count or 0)
        landed = (self.client.table("confident_voice_practice")
                  .select("id", count="exact").eq("status", "completed")
                  .in_("final_user_answer", ["yes", "in_between"])
                  .gte("closed_at", since).limit(1).execute().count or 0)
        return {
            "practices_landed": int(landed),
            "bold_voices_heard": _count("bold_voices_plays"),
            "steps": {step: _count("after_practice_steps", step=step)
                      for step in ("bridge", "lend_your_ear", "bold_voices")},
        }

    @staticmethod
    def _since_column(table: str) -> str:
        return "shown_at" if table == "after_practice_steps" else "created_at"

    # ── Phase 4 and 5 of the after-practice paths (0410) ─────────────────

    def voice_album_has(self, arc_id: str, snippet_id: str) -> bool:
        """Whether this moment is in the speaker's Voice Album now."""
        res = (self.client.table("voice_album").select("snippet_id")
               .eq("arc_id", str(arc_id)).eq("snippet_id", str(snippet_id))
               .limit(1).execute())
        return bool(res.data)

    def set_voice_album_share(
        self, *, owner_user_id: str, arc_id: str, snippet_id: str,
        take_session_id: Optional[str], shared: bool,
    ) -> Optional[dict]:
        """Lend or withdraw one moment (0410): one row per moment; a share
        clears revoked_at, a withdrawal stamps it. Raises on failure."""
        now = datetime.now(timezone.utc).isoformat()
        res = (self.client.table("voice_album_shares").upsert({
            "owner_user_id": str(owner_user_id), "arc_id": str(arc_id),
            "snippet_id": str(snippet_id), "take_session_id": take_session_id,
            "shared_at": now, "revoked_at": None if shared else now,
        }, on_conflict="snippet_id").execute())
        return (res.data or [None])[0]

    def list_shared_clips_live(self) -> list[dict]:
        """Every moment lent and still in an Album (the view, 0410)."""
        res = (self.client.table("shared_clips_live").select("*")
               .order("shared_at", desc=True).limit(500).execute())
        return list(res.data or [])

    def list_corpus_clips(self, *, active_only: bool = True) -> list[dict]:
        query = self.client.table("corpus_clips").select("*")
        if active_only:
            query = query.eq("active", True)
        return list(query.order("created_at", desc=True).limit(500).execute().data or [])

    def list_corpus_clips_active(self) -> list[dict]:
        return self.list_corpus_clips(active_only=True)

    def insert_corpus_clip(self, row: dict) -> Optional[dict]:
        res = self.client.table("corpus_clips").insert(dict(row)).execute()
        return (res.data or [None])[0]

    def set_corpus_clip_coach_value(
        self, *, clip_id: str, coach_id: str, value: Optional[str],
    ) -> Optional[dict]:
        res = (self.client.table("corpus_clips")
               .update({"coach_value": value, "coach_id": str(coach_id) if value else None,
                        "labelled_at": datetime.now(timezone.utc).isoformat() if value else None})
               .eq("id", str(clip_id)).execute())
        return (res.data or [None])[0]

    def list_lend_your_ear_answered_clip_ids(self, listener_id: str) -> list[str]:
        res = (self.client.table("lend_your_ear_answers").select("clip_id")
               .eq("listener_user_id", str(listener_id)).limit(2000).execute())
        return [str(r.get("clip_id")) for r in (res.data or []) if r.get("clip_id")]

    def _with_answers(self, the_set: Optional[dict]) -> Optional[dict]:
        if not isinstance(the_set, dict):
            return None
        res = (self.client.table("lend_your_ear_answers").select("clip_id")
               .eq("set_id", str(the_set.get("id"))).execute())
        return {**the_set, "answered_clip_ids": [str(r.get("clip_id")) for r in (res.data or [])]}

    def get_lend_your_ear_set_for_take(self, take_session_id: str) -> Optional[dict]:
        res = (self.client.table("lend_your_ear_sets").select("*")
               .eq("take_session_id", str(take_session_id)).limit(1).execute())
        return self._with_answers((res.data or [None])[0])

    def get_lend_your_ear_set(self, set_id: str, listener_id: str) -> Optional[dict]:
        res = (self.client.table("lend_your_ear_sets").select("*")
               .eq("id", str(set_id)).eq("listener_user_id", str(listener_id))
               .limit(1).execute())
        return self._with_answers((res.data or [None])[0])

    def insert_lend_your_ear_set(self, row: dict) -> Optional[dict]:
        res = self.client.table("lend_your_ear_sets").insert(dict(row)).execute()
        return (res.data or [None])[0]

    def insert_lend_your_ear_answer(self, row: dict) -> Optional[dict]:
        """One per person per clip: a duplicate answers None."""
        try:
            res = self.client.table("lend_your_ear_answers").insert(dict(row)).execute()
        except Exception as e:  # noqa: BLE001 — the unique key is the rule
            if "23505" in str(e) or "duplicate" in str(e).lower():
                return None
            raise
        return (res.data or [None])[0]

    def list_recent_pair_ids_for_listener(self, listener_id: str, *, days: int) -> list[str]:
        """The pairs whose clip this listener was shown within `days`, so the
        partner waits (correction 5)."""
        since = (datetime.now(timezone.utc) - timedelta(days=max(1, int(days)))).isoformat()
        res = (self.client.table("lend_your_ear_sets").select("clips")
               .eq("listener_user_id", str(listener_id)).gte("created_at", since).execute())
        out: list[str] = []
        for row in res.data or []:
            for clip in (row.get("clips") or []) if isinstance(row, dict) else []:
                if isinstance(clip, dict) and clip.get("pair_id"):
                    out.append(str(clip["pair_id"]))
        return out

    def count_lend_your_ear(self, since: str) -> dict:
        def _count(table: str) -> int:
            return int(self.client.table(table).select("id", count="exact")
                       .gte("created_at", since).limit(1).execute().count or 0)
        return {"sets_opened": _count("lend_your_ear_sets"),
                "answers": _count("lend_your_ear_answers"),
                "shares_live": int(self.client.table("voice_album_shares")
                                   .select("id", count="exact").is_("revoked_at", "null")
                                   .limit(1).execute().count or 0)}

    def insert_delayed_measure_pair(self, row: dict) -> Optional[dict]:
        """One pair per practice (0410); the first write wins."""
        res = (self.client.table("delayed_measure_pairs").upsert(
            dict(row), on_conflict="practice_id", ignore_duplicates=True).execute())
        return (res.data or [None])[0]

    def get_delayed_measure_pair(self, pair_id: str) -> Optional[dict]:
        res = (self.client.table("delayed_measure_pairs").select("*")
               .eq("id", str(pair_id)).limit(1).execute())
        return (res.data or [None])[0]

    def list_delayed_measure_pairs_open(self) -> list[dict]:
        res = (self.client.table("delayed_measure_pairs").select("*")
               .eq("status", "open").order("created_at").limit(1000).execute())
        return list(res.data or [])

    def insert_delayed_measure_vote(self, row: dict) -> Optional[dict]:
        """One vote per rater per clip: a duplicate answers None."""
        try:
            res = self.client.table("delayed_measure_votes").insert(dict(row)).execute()
        except Exception as e:  # noqa: BLE001 — the unique key is the rule
            if "23505" in str(e) or "duplicate" in str(e).lower():
                return None
            raise
        return (res.data or [None])[0]

    def list_delayed_measure_votes(self, pair_id: str) -> list[dict]:
        res = (self.client.table("delayed_measure_votes").select("*")
               .eq("pair_id", str(pair_id)).execute())
        return list(res.data or [])

    def list_delayed_measure_votes_by_rater(self, rater_id: str) -> list[dict]:
        res = (self.client.table("delayed_measure_votes").select("pair_id,clip")
               .eq("rater_id", str(rater_id)).limit(5000).execute())
        return list(res.data or [])

    def coach_handled_moment(self, coach_id: str, take_session_id: str,
                             snippet_id: str) -> bool:
        """Whether this coach resolved the moment's request or rated the
        clip (correction 6): such a coach never votes on its pair."""
        request_row = self.get_exercise_coach_request(take_session_id, snippet_id)
        if isinstance(request_row, dict) and str(request_row.get("resolved_by") or "") == str(coach_id):
            return True
        labels = (self.get_confidence_labels_by_snippet_ids([str(snippet_id)]) or {}).get(str(snippet_id), [])
        return any(isinstance(r, dict) and str(r.get("rater_id") or "") == str(coach_id) for r in labels)

    # ── Communities (0432, N52.4) ─────────────────────────────────────────

    def get_general_community(self) -> Optional[dict]:
        """The one open community (seeded by 0432)."""
        res = (self.client.table("communities").select("*")
               .eq("kind", "general").limit(1).execute())
        return (res.data or [None])[0]

    def insert_community(self, row: dict) -> Optional[dict]:
        """A private community; a pass code already in use answers None (the
        unique digest is the rule). Raises on any other failure."""
        try:
            res = self.client.table("communities").insert(dict(row)).execute()
        except Exception as e:  # noqa: BLE001 — the unique key is the rule
            if "23505" in str(e) or "duplicate" in str(e).lower():
                return None
            raise
        return (res.data or [None])[0]

    def get_community_by_pass_code_digest(self, digest: str) -> Optional[dict]:
        res = (self.client.table("communities").select("*")
               .eq("pass_code_digest", str(digest)).is_("closed_at", "null")
               .limit(1).execute())
        return (res.data or [None])[0]

    def get_communities_by_ids(self, community_ids: list[str]) -> list[dict]:
        ids = [str(c) for c in community_ids or [] if c]
        if not ids:
            return []
        res = self.client.table("communities").select("*").in_("id", ids).execute()
        return list(res.data or [])

    def add_community_member(self, *, community_id: str, user_id: str,
                             role: str) -> bool:
        """One row per person per community; joining again keeps the row
        (and an owner stays owner). Raises on failure."""
        (self.client.table("community_members").upsert({
            "community_id": str(community_id), "user_id": str(user_id), "role": str(role),
        }, on_conflict="community_id,user_id", ignore_duplicates=True).execute())
        return True

    def list_community_memberships(self, user_id: str) -> list[dict]:
        """[{community_id, role, joined_at}] for one person."""
        res = (self.client.table("community_members")
               .select("community_id,role,joined_at")
               .eq("user_id", str(user_id)).limit(500).execute())
        return list(res.data or [])

    def list_take_shares(self, take_session_id: str) -> list[dict]:
        res = (self.client.table("take_shares").select("*")
               .eq("take_session_id", str(take_session_id)).execute())
        return list(res.data or [])

    def upsert_take_share(self, *, take_session_id: str, owner_user_id: str,
                          community_id: str, consent_version: str,
                          share_words_version: str) -> Optional[dict]:
        """Share one Take with one community: one row per pair; a share
        clears revoked_at and stamps the consent version (Privacy/Terms) and
        the version of the sharing screen's words the speaker saw (0443,
        CM2 B). Raises on failure."""
        res = (self.client.table("take_shares").upsert({
            "take_session_id": str(take_session_id), "owner_user_id": str(owner_user_id),
            "community_id": str(community_id), "consent_version": str(consent_version),
            "share_words_version": str(share_words_version),
            "shared_at": datetime.now(timezone.utc).isoformat(), "revoked_at": None,
        }, on_conflict="take_session_id,community_id").execute())
        return (res.data or [None])[0]

    def revoke_take_shares(self, take_session_id: str, *,
                           keep_community_ids: list[str]) -> int:
        """Withdraw the Take from every community not kept; the rows stay
        with revoked_at stamped. Raises on failure."""
        query = (self.client.table("take_shares")
                 .update({"revoked_at": datetime.now(timezone.utc).isoformat()})
                 .eq("take_session_id", str(take_session_id))
                 .is_("revoked_at", "null"))
        keep = [str(c) for c in keep_community_ids or [] if c]
        if keep:
            query = query.not_.in_("community_id", keep)
        return len(query.execute().data or [])

    def pick_line_bank_line(self, *, user_id: str, bank: str, size: int,
                            later_true: bool) -> int:
        """The index of the signed line to show next in one bank for one
        speaker, recorded in the same call (0438): -1 is the bank's later
        line. Raises on failure."""
        res = self.client.rpc("pick_line_bank_line_v1", {
            "p_user_id": str(user_id), "p_bank": str(bank),
            "p_size": int(size), "p_later_true": bool(later_true),
        }).execute()
        data = res.data
        if isinstance(data, list):
            data = data[0] if data else None
        if isinstance(data, dict):
            data = next(iter(data.values()), None)
        if isinstance(data, bool) or not isinstance(data, int):
            raise ValueError("pick_line_bank_line_v1 returned no index")
        return data

    def new_coach_feedback_by_project(self, user_id: str) -> dict[str, bool]:
        """{project id: True while a published coach word or answer for
        one of its Takes is newer than the walk's last show of it} for every
        project of this speaker (0439). A yes/no, never a count. Raises on
        failure."""
        res = self.client.rpc("new_coach_feedback_by_project_v1",
                              {"p_owner": str(user_id)}).execute()
        out: dict[str, bool] = {}
        for row in res.data or []:
            if isinstance(row, dict) and row.get("arc_id"):
                out[str(row["arc_id"])] = row.get("has_new") is True
        return out

    def mark_coach_feedback_seen(self, *, user_id: str, take_session_id: str,
                                 item: str) -> Any:
        """Record that the walk showed this speaker the Take's coach note
        (item 'take_word') or one moment (item = its snippet id) (0439).
        Raises on failure, including COACH_FEEDBACK_TAKE_NOT_OWNED."""
        res = self.client.rpc("mark_coach_feedback_seen_v1", {
            "p_owner": str(user_id), "p_take": str(take_session_id),
            "p_item": str(item),
        }).execute()
        return res.data

    def list_community_clips_live(self, community_ids: list[str]) -> list[dict]:
        """The live moments shared with these communities (the view, 0432),
        newest share first."""
        ids = [str(c) for c in community_ids or [] if c]
        if not ids:
            return []
        res = (self.client.table("community_clips_live").select("*")
               .in_("community_id", ids).order("shared_at", desc=True)
               .limit(500).execute())
        return list(res.data or [])

    def list_community_clips_for_snippet(self, snippet_id: str) -> list[dict]:
        res = (self.client.table("community_clips_live").select("*")
               .eq("snippet_id", str(snippet_id)).execute())
        return list(res.data or [])

    def list_community_answered_clip_ids(self, listener_id: str) -> list[str]:
        """Every clip this listener answered in a community queue: the
        snippet of a community clip, the corpus id of a training clip."""
        res = (self.client.table("community_answers")
               .select("snippet_id,corpus_clip_id")
               .eq("listener_user_id", str(listener_id)).limit(5000).execute())
        out: list[str] = []
        for row in res.data or []:
            for key in ("snippet_id", "corpus_clip_id"):
                if row.get(key):
                    out.append(str(row[key]))
        return out

    def insert_community_answer(self, row: dict) -> Optional[dict]:
        """One per person per clip: a duplicate answers None."""
        try:
            res = self.client.table("community_answers").insert(dict(row)).execute()
        except Exception as e:  # noqa: BLE001 — the unique key is the rule
            if "23505" in str(e) or "duplicate" in str(e).lower():
                return None
            raise
        return (res.data or [None])[0]

    def get_corpus_clip(self, clip_id: str) -> Optional[dict]:
        res = (self.client.table("corpus_clips").select("*")
               .eq("id", str(clip_id)).limit(1).execute())
        return (res.data or [None])[0]

    def upsert_coach_take_word(
        self, *, take_session_id: str, coach_id: str, text: Optional[str],
        video_ref: Optional[str], share: bool,
    ) -> Optional[dict]:
        """One word per (Take, coach) (0403), replaced on each save; sharing
        stamps shared_at once and a later save keeps it. Raises on failure."""
        now = datetime.now(timezone.utc).isoformat()
        existing = self.get_coach_take_word(take_session_id, coach_id) or {}
        payload: dict[str, Any] = {
            "take_session_id": str(take_session_id),
            "coach_id": str(coach_id),
            "text": text,
            "video_ref": video_ref,
            "updated_at": now,
        }
        if share and not existing.get("shared_at"):
            payload["shared_at"] = now
        res = (self.client.table("coach_take_words")
               .upsert(payload, on_conflict="take_session_id,coach_id")
               .execute())
        return (res.data or [None])[0]

    def get_coach_take_word(self, take_session_id: str, coach_id: str) -> Optional[dict]:
        if not take_session_id or not coach_id:
            return None
        try:
            res = (self.client.table("coach_take_words").select("*")
                   .eq("take_session_id", str(take_session_id))
                   .eq("coach_id", str(coach_id)).limit(1).execute())
            return (res.data or [None])[0]
        except Exception as e:
            logger.warning("get_coach_take_word failed take=%s: %s",
                           take_session_id, e, exc_info=True)
            return None

    def list_shared_coach_take_words(self, take_session_ids: list[str]) -> list[dict]:
        """Every shared word on these Takes (0403). Raises on failure."""
        ids = [str(i) for i in take_session_ids if i]
        if not ids:
            return []
        res = (self.client.table("coach_take_words")
               .select("take_session_id,coach_id,text,video_ref,shared_at,updated_at")
               .in_("take_session_id", ids)
               .not_.is_("shared_at", "null").execute())
        return list(res.data or [])

    # ── The ledger's weeks, the research role, the golden set (0404) ────

    def get_mlc2_foundation_health(self) -> dict:
        """F-9: the MLC-2 foundation's aggregate health
        (``get_mlc2_foundation_health_v1``, service-role only), read through
        the foundation's own adapter. Raises; the weekly job names it."""
        from services.mlc2_foundation import Mlc2FoundationStore
        return Mlc2FoundationStore(self.client).health()

    def upsert_ledger_snapshot(self, **row: Any) -> Optional[dict]:
        """One row per ISO week (ML-3), replaced on a second fire. Raises."""
        res = (self.client.table("ledger_snapshots")
               .upsert(row, on_conflict="week_start").execute())
        return (res.data or [None])[0]

    def list_ledger_snapshots(self, limit: int = 8) -> list[dict]:
        """The newest weeks first. Raises on failure."""
        res = (self.client.table("ledger_snapshots").select("*")
               .order("week_start", desc=True).limit(int(limit)).execute())
        return list(res.data or [])

    def is_research_user(self, email: str) -> bool:
        res = (self.client.table("research_users").select("email")
               .eq("email", str(email).strip().lower()).eq("is_active", True)
               .limit(1).execute())
        return bool(res.data)

    def list_dataset_releases(self) -> list[dict]:
        res = (self.client.table("dataset_releases")
               .select("id,release_identifier,learning_surface,source_cutoff_at,item_counts,manifest_checksum,created_at")
               .order("created_at", desc=True).limit(50).execute())
        return list(res.data or [])

    def list_dataset_exclusions(self) -> list[dict]:
        res = (self.client.table("dataset_exclusions").select("reason_code")
               .limit(5000).execute())
        return list(res.data or [])

    def list_annotation_export_runs(self, limit: int = 20) -> list[dict]:
        res = (self.client.table("admin_annotation_export_runs")
               .select("started_at,status,exported_count,export_uri")
               .order("started_at", desc=True).limit(int(limit)).execute())
        return list(res.data or [])

    def list_golden_judgements(self, *, surface: str,
                               judge: Optional[str] = None) -> list[dict]:
        q = (self.client.table("golden_judgements")
             .select("snippet_id,value,judge_email,created_at").eq("surface", str(surface)))
        if judge:
            q = q.eq("judge_email", str(judge))
        return list(q.order("created_at").limit(1000).execute().data or [])

    def insert_golden_judgement(self, **fields: Any) -> Optional[dict]:
        res = self.client.table("golden_judgements").insert(fields).execute()
        return (res.data or [None])[0]

    def get_golden_set(self, surface: str) -> Optional[dict]:
        res = (self.client.table("golden_sets").select("*")
               .eq("surface", str(surface)).limit(1).execute())
        return (res.data or [None])[0]

    def seal_golden_set(self, **fields: Any) -> Optional[dict]:
        # An upsert: a set whose moment erasure removed is re-sealed by the
        # founder with a new hash (0406); the service refuses while the
        # sealed rows still match.
        res = self.client.table("golden_sets").upsert(fields, on_conflict="surface").execute()
        return (res.data or [None])[0]

    # ── A pair remembers the yes (0405): consent refresh and releases ──────

    def refresh_feedback_pair_consent(self, required_surfaces: list[str]) -> dict:
        """The weekly refresh: every pair's consent state and releasability,
        and the voiding of releases whose owner withdrew. Raises."""
        res = self.client.rpc("refresh_feedback_pair_consent_v1", {
            "p_required_surfaces": [str(s) for s in required_surfaces],
        }).execute()
        data = res.data
        return data if isinstance(data, dict) else (self._rpc_row(data) or {})

    def list_releasable_pairs(self, surface: str, *, limit: int = 5000) -> list[dict]:
        """Releasable, unexported pairs of one surface, oldest first: the
        candidates the release decides again, item by item (PLF-P5), so the
        Take is selected for the project check. Only pairs that carry what
        the export contract needs beyond the speaker's yes are candidates:
        the passage they were drafted from and the model version that
        drafted them (C5, C9; W6 2026-10-05). Raises."""
        res = (self.client.table("feedback_pairs")
               .select("id,surface,draft_text,final_text,final_kind,draft_model_version,"
                       "pattern_key,owner_principal_id,consent_state,consent_grant_event_id,"
                       "consent_policy_version,take_session_id,created_at")
               .eq("surface", str(surface)).eq("releasable", True)
               .not_.is_("passage_text", "null")
               .not_.is_("draft_model_version", "null")
               .is_("exported_at", "null").order("created_at").limit(int(limit)).execute())
        return list(res.data or [])

    def list_active_training_grants(self, principal_ids: list[str]) -> list[dict]:
        """The training-only yes in force NOW for these principals, read from
        the view the weekly refresh reads (training_consent_active_grants,
        0405): [{id, acquisition_principal_id, consent_policy_version}]. The
        release-time decision (PLF-P5) and the promotion's freshness check
        read consent here, never from a pair's weekly stamp. Raises."""
        ids = sorted({str(p) for p in principal_ids if p})
        out: list[dict] = []
        for start in range(0, len(ids), 200):
            res = (self.client.table("training_consent_active_grants")
                   .select("id,acquisition_principal_id,consent_policy_version")
                   .in_("acquisition_principal_id", ids[start:start + 200]).execute())
            out.extend(r for r in (res.data or []) if isinstance(r, dict))
        return out

    def phase1_learning_stopped(self, principal_id: str) -> bool:
        """``phase1_learning_stopped_v1`` (0422): True while the person's
        service is ending (an account deletion not cancelled, or a
        termination, deletion or retention-expiry block). Raises on failure
        or on an answer that is not a boolean: unknown is never "no"."""
        res = self.client.rpc("phase1_learning_stopped_v1", {
            "p_acquisition_principal_id": str(principal_id),
        }).execute()
        data: Any = res.data
        if isinstance(data, list):
            data = data[0] if data else None
        if isinstance(data, dict):
            data = data.get("phase1_learning_stopped_v1")
        if not isinstance(data, bool):
            raise RuntimeError("phase1_learning_stopped_v1 gave no answer")
        return data

    def list_take_projects(self, take_ids: list[str]) -> dict[str, str]:
        """{take id: project id} for these Takes (v2_sessions); a Take that
        is gone is absent, a Take with no project maps to "". Raises."""
        ids = sorted({str(t) for t in take_ids if t})
        out: dict[str, str] = {}
        for start in range(0, len(ids), 200):
            res = (self.client.table("v2_sessions").select("id,project_id")
                   .in_("id", ids[start:start + 200]).execute())
            for row in res.data or []:
                if isinstance(row, dict) and row.get("id"):
                    out[str(row["id"])] = str(row.get("project_id") or "")
        return out

    def insert_pair_release(self, **fields: Any) -> Optional[dict]:
        res = self.client.table("pair_releases").insert(fields).execute()
        return (res.data or [None])[0]

    def insert_pair_release_owners(self, release_id: str, owner_principal_ids: list[str]) -> int:
        rows = [{"release_id": str(release_id), "owner_principal_id": str(p)}
                for p in sorted({str(p) for p in owner_principal_ids if p})]
        if not rows:
            return 0
        self.client.table("pair_release_owners").insert(rows).execute()
        return len(rows)

    def mark_feedback_pairs_released(self, release_id: str, pair_ids: list[str]) -> int:
        res = self.client.rpc("mark_feedback_pairs_released_v1", {
            "p_release_id": str(release_id), "p_pair_ids": [str(p) for p in pair_ids],
        }).execute()
        return int(res.data or 0)

    def list_pair_releases(self, limit: int = 20) -> list[dict]:
        """The newest releases first, with their manifests (the research
        screen sums the speaker-disjoint split counts from them, ML-7)."""
        res = (self.client.table("pair_releases")
               .select("id,release_version,surface,week_start,item_count,storage_bucket,storage_key,"
                       "manifest,manifest_sha256,file_sha256,signing_key_id,exported_at,voided_at,"
                       "voided_reason,purged_at")
               .order("exported_at", desc=True).limit(int(limit)).execute())
        return list(res.data or [])

    def _rpc_object(self, name: str, params: dict) -> dict:
        """A JSONB-returning RPC's object. Raises on failure or on an answer
        that is not an object: a monitor that cannot be read is named."""
        data: Any = self.client.rpc(name, params).execute().data
        if isinstance(data, list):
            data = data[0] if data else None
        if isinstance(data, dict) and len(data) == 1 and isinstance(data.get(name), dict):
            data = data[name]
        if not isinstance(data, dict):
            raise RuntimeError(f"{name} gave no object")
        return data

    def get_mlc2_confidence_canary_readiness(self) -> dict:
        """The confidence chain's own invariants, exactly as the five-minute
        readiness cron reads them (scripts/check_mlc2_confidence_canary_
        readiness.py): aggregate counts only. Raises."""
        return self._rpc_object("get_mlc2_confidence_canary_readiness_v1",
                                {"p_founder_principal_id": None})

    def get_ring_confidence_readiness(self) -> dict:
        """The ring rows' readiness, as the same cron reads it. Raises."""
        return self._rpc_object("get_ring_confidence_readiness_v1", {})

    def list_voided_unpurged_pair_releases(self) -> list[dict]:
        res = (self.client.table("pair_releases")
               .select("id,surface,storage_bucket,storage_key,voided_at")
               .not_.is_("voided_at", "null").is_("purged_at", "null").limit(500).execute())
        return list(res.data or [])

    def mark_pair_release_purged(self, release_id: str) -> None:
        (self.client.table("pair_releases").update({"purged_at": "now()"})
         .eq("id", str(release_id)).execute())

    # ── F-8: every download or release check appends a verification (0430) ──

    def list_live_pair_releases(self, limit: int = 500) -> list[dict]:
        """Releases that stand (not voided, not purged), for the weekly
        check. Raises."""
        res = (self.client.table("pair_releases")
               .select("id,surface,week_start,storage_bucket,storage_key")
               .is_("voided_at", "null").is_("purged_at", "null")
               .order("exported_at").limit(int(limit)).execute())
        return list(res.data or [])

    def record_pair_release_verification(
        self, *, release_id: str, object_role: str, observed_sha256: str,
        observed_byte_size: int, signature_valid: Optional[bool],
        verification_method: str, verifier_version: str,
    ) -> Optional[dict]:
        """One append-only check of a release object; the database judges
        it against the release row. Raises."""
        res = self.client.rpc("record_pair_release_verification_v1", {
            "p_release_id": str(release_id), "p_object_role": object_role,
            "p_observed_sha256": observed_sha256,
            "p_observed_byte_size": int(observed_byte_size),
            "p_signature_valid": signature_valid,
            "p_verification_method": verification_method,
            "p_verifier_version": verifier_version,
        }).execute()
        return self._rpc_row(res.data)

    def record_mlc2_object_verification(
        self, *, bucket: str, object_key: str, observed_sha256: str,
        observed_byte_size: int, verification_method: str,
        verifier_version: str,
    ) -> Optional[dict]:
        """One append-only check of a chain object (ml_object_verifications);
        None when the key is no chain object. Raises."""
        res = self.client.rpc("record_mlc2_object_verification_v1", {
            "p_bucket": bucket, "p_object_key": object_key,
            "p_observed_sha256": observed_sha256,
            "p_observed_byte_size": int(observed_byte_size),
            "p_verification_method": verification_method,
            "p_verifier_version": verifier_version,
        }).execute()
        return self._rpc_row(res.data)

    def list_mlc2_objects_due_verification(self, limit: int) -> list[dict]:
        """The weekly check's capped work list: coordinates only. Raises."""
        res = self.client.rpc("list_mlc2_objects_due_verification_v1",
                              {"p_limit": int(limit)}).execute()
        return [row for row in (res.data or []) if isinstance(row, dict)]

    # ── Doors 3 and 4 (0406): the golden text pool, runs, reports, promotions ──
    def list_golden_pair_pool(self, surface: str, *, limit: int = 500) -> list[dict]:
        """Pairs with a passage, newest first: the founder's text pool. The
        draft is not selected: the founder judges the coach's answer."""
        res = (self.client.table("feedback_pairs")
               .select("id,surface,final_text,passage_text,prompt_context,"
                       "owner_principal_id,take_session_id,created_at")
               .eq("surface", str(surface)).not_.is_("passage_text", "null")
               .order("created_at", desc=True).limit(int(limit)).execute())
        return list(res.data or [])

    def get_feedback_pair(self, pair_id: str) -> Optional[dict]:
        res = (self.client.table("feedback_pairs")
               .select("id,surface,final_text,passage_text,prompt_context,owner_principal_id")
               .eq("id", str(pair_id)).limit(1).execute())
        return (res.data or [None])[0]

    def list_trainable_pairs(self, surface: str, *, limit: int = 5000) -> list[dict]:
        """Released, releasable, never trained, with a passage; oldest first.
        Read at run start, so a withdrawal since the release keeps the pair
        out. Raises."""
        res = (self.client.table("feedback_pairs")
               .select("id,surface,final_text,passage_text,prompt_context,owner_principal_id,"
                       "releasable,release_id,trained_run_id,created_at")
               .eq("surface", str(surface)).eq("releasable", True)
               .not_.is_("release_id", "null").is_("trained_run_id", "null")
               .not_.is_("passage_text", "null")
               .order("created_at").limit(int(limit)).execute())
        return list(res.data or [])

    def list_trained_pairs(self, run_id: str) -> list[dict]:
        """The pairs one run learned from, as the withdrawal basis needs
        them (DOOR-4-WITHDRAWN): whose they are, their two texts, and
        whether they are still releasable. Raises."""
        res = (self.client.table("feedback_pairs")
               .select("owner_principal_id,passage_text,final_text,releasable")
               .eq("trained_run_id", str(run_id)).limit(5000).execute())
        return list(res.data or [])

    def get_fine_tune_run(self, run_id: str) -> Optional[dict]:
        """One run row, or None. Raises."""
        res = (self.client.table("fine_tune_runs").select("*")
               .eq("id", str(run_id)).limit(1).execute())
        return (res.data or [None])[0]

    def get_latest_evaluation_report(self, run_id: str) -> Optional[dict]:
        """The newest evaluation report of one run, or None. Raises."""
        res = (self.client.table("evaluation_reports").select("*")
               .eq("run_id", str(run_id)).order("created_at", desc=True)
               .limit(1).execute())
        return (res.data or [None])[0]

    def insert_fine_tune_run(self, **fields: Any) -> Optional[dict]:
        res = self.client.table("fine_tune_runs").insert(fields).execute()
        return (res.data or [None])[0]

    def insert_fine_tune_run_owners(self, run_id: str, owner_principal_ids: list[str]) -> int:
        rows = [{"run_id": str(run_id), "owner_principal_id": str(p)}
                for p in sorted({str(p) for p in owner_principal_ids if p})]
        if not rows:
            return 0
        self.client.table("fine_tune_run_owners").insert(rows).execute()
        return len(rows)

    def mark_feedback_pairs_trained(self, run_id: str, pair_ids: list[str]) -> int:
        res = self.client.rpc("mark_feedback_pairs_trained_v1", {
            "p_run_id": str(run_id), "p_pair_ids": [str(p) for p in pair_ids],
        }).execute()
        return int(res.data or 0)

    def update_fine_tune_run(self, run_id: str, **fields: Any) -> None:
        self.client.table("fine_tune_runs").update(fields).eq("id", str(run_id)).execute()

    def list_fine_tune_runs(self, *, status: Optional[str] = None, limit: int = 20) -> list[dict]:
        q = self.client.table("fine_tune_runs").select("*")
        if status:
            q = q.eq("status", status)
        res = q.order("started_at", desc=True).limit(int(limit)).execute()
        return list(res.data or [])

    def list_fine_tune_runs_with_withdrawn_owner(self) -> list[dict]:
        res = (self.client.table("fine_tune_runs_with_withdrawn_owner").select("*")
               .limit(500).execute())
        return list(res.data or [])

    def insert_evaluation_report(self, **fields: Any) -> Optional[dict]:
        res = self.client.table("evaluation_reports").insert(fields).execute()
        return (res.data or [None])[0]

    def get_evaluation_report(self, report_id: str) -> Optional[dict]:
        res = (self.client.table("evaluation_reports").select("*")
               .eq("id", str(report_id)).limit(1).execute())
        return (res.data or [None])[0]

    def list_evaluation_reports(self, *, limit: int = 20) -> list[dict]:
        res = (self.client.table("evaluation_reports").select("*")
               .order("created_at", desc=True).limit(int(limit)).execute())
        return list(res.data or [])

    def insert_model_promotion(self, **fields: Any) -> Optional[dict]:
        res = self.client.table("model_promotions").insert(fields).execute()
        return (res.data or [None])[0]

    def kill_model_promotions(self, *, surface: str, killed_by: str,
                              kill_reason: str, killed_at: str) -> None:
        (self.client.table("model_promotions")
         .update({"killed_at": killed_at, "killed_by": killed_by, "kill_reason": kill_reason})
         .eq("surface", str(surface)).is_("killed_at", "null").execute())

    def list_model_promotions(self, *, limit: int = 20) -> list[dict]:
        res = (self.client.table("model_promotions").select("*")
               .order("promoted_at", desc=True).limit(int(limit)).execute())
        return list(res.data or [])

    def insert_feedback_pair(self, **fields: Any) -> Optional[dict]:
        """One (draft, final) pair (0402). Raises on failure; the service
        logs it and the answer stands. A duplicate for the same request or
        version is the unique index's refusal, which is the same."""
        res = self.client.table("feedback_pairs").insert(fields).execute()
        return (res.data or [None])[0]

    def count_feedback_pairs(self) -> dict[str, dict[str, int]]:
        """{surface: {total, unexported, releasable}} for the ledger, for
        EVERY pair surface (services.feedback_pairs.SURFACES: the three
        answer surfaces and the two coach-word ones, ML-2).
        ``releasable`` counts every pair whose speaker's training yes is in
        force, exported or not. Raises on failure so the ledger names the
        source as unavailable rather than zero."""
        from services.feedback_pairs import SURFACES
        out: dict[str, dict[str, int]] = {}
        for surface in SURFACES:
            total = (self.client.table("feedback_pairs")
                     .select("id", count="exact").eq("surface", surface)
                     .limit(1).execute())
            waiting = (self.client.table("feedback_pairs")
                       .select("id", count="exact").eq("surface", surface)
                       .is_("exported_at", "null").limit(1).execute())
            releasable = (self.client.table("feedback_pairs")
                          .select("id", count="exact").eq("surface", surface)
                          .eq("releasable", True).limit(1).execute())
            out[surface] = {"total": int(total.count or 0),
                            "unexported": int(waiting.count or 0),
                            "releasable": int(releasable.count or 0)}
        return out

    def count_exportable_pairs(self) -> dict[str, dict[str, int]]:
        """{surface: {exportable, exportable_unexported}} for the ledger,
        for every pair surface (C9; W6 2026-10-05): the pairs the export
        contract can release, the speaker's training yes in force AND the
        passage the draft was written from AND the model version that wrote
        it, ever and still awaiting export. The pace jar and a run's bar of
        200 read these, beside ``count_feedback_pairs``'s three views.
        Raises on failure so the ledger names the source as unavailable."""
        from services.feedback_pairs import SURFACES
        out: dict[str, dict[str, int]] = {}
        for surface in SURFACES:
            def stamped(*, unexported: bool) -> int:
                q = (self.client.table("feedback_pairs")
                     .select("id", count="exact").eq("surface", surface)
                     .eq("releasable", True)
                     .not_.is_("passage_text", "null")
                     .not_.is_("draft_model_version", "null"))
                if unexported:
                    q = q.is_("exported_at", "null")
                return int(q.limit(1).execute().count or 0)
            out[surface] = {"exportable": stamped(unexported=False),
                            "exportable_unexported": stamped(unexported=True)}
        return out

    def count_draft_exposures(self) -> dict[str, int]:
        """{surface: drafts shown} for the ledger (ML-2): how often a model's
        draft was put in front of a coach on each pair surface, the half of
        the C5 rule a pair needs before its final can differ. A drafting
        route stores the draft on the row it shows it from, at the moment it
        shows it: the request row (``draft_surface``, 0402/0411) for the
        three answer surfaces and the moment line, the coach's Take-word row
        for the Take word (0411). A re-draft on the same row counts once.
        Raises on failure so the ledger names the source as unavailable."""
        out: dict[str, int] = {}
        for surface in ("exercise_script", "praise_line", "clearer_version",
                        "coach_moment_line"):
            shown = (self.client.table("exercise_coach_requests")
                     .select("id", count="exact").eq("draft_surface", surface)
                     .not_.is_("draft_text", "null").limit(1).execute())
            out[surface] = int(shown.count or 0)
        words = (self.client.table("coach_take_words")
                 .select("id", count="exact")
                 .not_.is_("draft_text", "null").limit(1).execute())
        out["coach_take_word"] = int(words.count or 0)
        return out

    def get_confident_voice_exercise_assignment(
        self, take_session_id: str, snippet_id: str,
    ) -> Optional[dict]:
        if not take_session_id or not snippet_id:
            return None
        try:
            res = (self.client.table("confident_voice_exercise_assignments")
                   .select("id,selected_exercise_id,selected_exercise_version,"
                           "selection_mode,exposure_policy_version,lane,"
                           "matching_policy_version")
                   .eq("take_session_id", str(take_session_id))
                   .eq("snippet_id", str(snippet_id))
                   .eq("exposure_policy_version", "exercise-80-20-v1")
                   .limit(1).execute())
            return (res.data or [None])[0]
        except Exception as e:
            logger.warning(
                "get_confident_voice_exercise_assignment failed sid=%s: %s",
                take_session_id, e)
            return None

    def get_confident_voice_practice_by_moment(
        self, take_session_id: str, snippet_id: str,
        owner_user_id: Optional[str] = None,
    ) -> Optional[dict]:
        """The practice on this exact moment (founder 2026-09-29: every
        bookmark may carry its own; migration 0396 keys it per moment)."""
        if not take_session_id or not snippet_id:
            return None
        try:
            query = (self.client.table("confident_voice_practice").select("*")
                     .eq("take_session_id", str(take_session_id))
                     .eq("snippet_id", str(snippet_id)))
            if owner_user_id:
                query = query.eq("owner_user_id", str(owner_user_id))
            res = query.limit(1).execute()
            return (res.data or [None])[0]
        except Exception as e:
            logger.warning("get_confident_voice_practice_by_moment failed "
                           "sid=%s snip=%s: %s", take_session_id, snippet_id, e,
                           exc_info=True)
            return None

    def get_confident_voice_practice_by_take(
        self, take_session_id: str, owner_user_id: Optional[str] = None,
    ) -> Optional[dict]:
        if not take_session_id:
            return None
        try:
            query = (self.client.table("confident_voice_practice").select("*")
                     .eq("take_session_id", str(take_session_id)))
            if owner_user_id:
                query = query.eq("owner_user_id", str(owner_user_id))
            res = query.limit(1).execute()
            return (res.data or [None])[0]
        except Exception as e:
            logger.warning("get_confident_voice_practice_by_take failed sid=%s: %s",
                           take_session_id, e)
            return None

    def speaker_exercise_history(
        self, owner_user_id: str, take_session_id: str, *, limit: int = 20,
    ) -> dict:
        """What this speaker's EARLIER Takes showed, for ranking (step 7).

        Returns {"pattern_takes": {problem: [take ids]},
                 "completed_exercises": [exercise ids], "earlier_takes": n}:
        the problems spotted on their exercise moments (from the frozen match
        traces and coach requests, never recomputed), and the exercises they
        completed. The current Take is excluded; at most `limit` earlier
        Takes of each kind are read. Shadow verdicts are never read here —
        they route nothing. Raises on failure; the caller ranks without
        history rather than guessing one.
        """
        owner = str(owner_user_id)
        current = str(take_session_id or "")
        takes_of: dict[str, set] = {}

        def seen(tag: Any, take: Any) -> None:
            if isinstance(tag, str) and tag and take:
                takes_of.setdefault(tag, set()).add(str(take))

        assignments = (self.client.table("confident_voice_exercise_assignments")
                       .select("id,take_session_id")
                       .eq("owner_user_id", owner).neq("take_session_id", current)
                       .order("created_at", desc=True).limit(limit)
                       .execute()).data or []
        take_of = {str(a.get("id")): a.get("take_session_id")
                   for a in assignments}
        if take_of:
            traces = (self.client.table("confident_voice_exercise_match_traces")
                      .select("assignment_id,observed_tags:trace->observed_tags")
                      .in_("assignment_id", list(take_of)).execute()).data or []
            for row in traces:
                for tag in row.get("observed_tags") or []:
                    seen(tag, take_of.get(str(row.get("assignment_id"))))
        requests = (self.client.table("exercise_coach_requests")
                    .select("take_session_id,observed_tags")
                    .eq("owner_user_id", owner).neq("take_session_id", current)
                    .order("created_at", desc=True).limit(limit)
                    .execute()).data or []
        for row in requests:
            for tag in row.get("observed_tags") or []:
                seen(tag, row.get("take_session_id"))
        completed = (self.client.table("confident_voice_practice")
                     .select("exercise_id")
                     .eq("owner_user_id", owner).eq("status", "completed")
                     .neq("take_session_id", current)
                     .execute()).data or []
        earlier = ({str(a.get("take_session_id")) for a in assignments}
                   | {str(r.get("take_session_id")) for r in requests})
        return {
            "pattern_takes": {tag: sorted(t) for tag, t in takes_of.items()},
            "completed_exercises": sorted({str(r.get("exercise_id"))
                                           for r in completed
                                           if r.get("exercise_id")}),
            "earlier_takes": len(earlier),
        }

    def completed_exercise_before(
        self, owner_user_id: str, exercise_id: str, take_session_id: str,
    ) -> bool:
        """Whether the owner completed a practice of this exercise on an
        earlier Take (contract 35d). False on any failure: the label is a
        courtesy and never blocks the offer."""
        if not owner_user_id or not exercise_id:
            return False
        try:
            query = (self.client.table("confident_voice_practice").select("id")
                     .eq("owner_user_id", str(owner_user_id))
                     .eq("exercise_id", str(exercise_id))
                     .eq("status", "completed"))
            if take_session_id:
                query = query.neq("take_session_id", str(take_session_id))
            res = query.limit(1).execute()
            return bool(res.data)
        except Exception as e:
            logger.warning("completed_exercise_before failed ex=%s: %s",
                           exercise_id, e)
            return False

    def get_confident_voice_practice(
        self, practice_id: str, owner_user_id: Optional[str] = None,
    ) -> Optional[dict]:
        if not practice_id:
            return None
        try:
            query = (self.client.table("confident_voice_practice").select("*")
                     .eq("id", str(practice_id)))
            if owner_user_id:
                query = query.eq("owner_user_id", str(owner_user_id))
            res = query.limit(1).execute()
            return (res.data or [None])[0]
        except Exception as e:
            logger.warning("get_confident_voice_practice failed id=%s: %s",
                           practice_id, e)
            return None

    def create_confident_voice_practice(self, row: dict) -> Optional[dict]:
        if not isinstance(row, dict):
            return None
        try:
            res = (self.client.table("confident_voice_practice")
                   .insert(row).execute())
            return (res.data or [None])[0]
        except Exception as e:
            # The DB unique(take_session_id, snippet_id) is the final
            # one-per-moment guard. A concurrent create re-reads the winner.
            logger.warning("create_confident_voice_practice failed take=%s: %s",
                           row.get("take_session_id"), e)
            return self.get_confident_voice_practice_by_moment(
                str(row.get("take_session_id") or ""),
                str(row.get("snippet_id") or ""),
                str(row.get("owner_user_id") or "") or None)

    def list_confident_voice_practice_attempts(
        self, practice_id: str,
    ) -> list[dict]:
        if not practice_id:
            return []
        try:
            res = (self.client.table("confident_voice_practice_attempt")
                   .select("*").eq("practice_id", str(practice_id))
                   .order("attempt_index").execute())
            return res.data or []
        except Exception as e:
            logger.warning("list_confident_voice_practice_attempts failed id=%s: %s",
                           practice_id, e)
            return []

    def get_confident_voice_practice_attempt(
        self, attempt_id: str, practice_id: Optional[str] = None,
    ) -> Optional[dict]:
        if not attempt_id:
            return None
        try:
            query = (self.client.table("confident_voice_practice_attempt")
                     .select("*").eq("id", str(attempt_id)))
            if practice_id:
                query = query.eq("practice_id", str(practice_id))
            res = query.limit(1).execute()
            return (res.data or [None])[0]
        except Exception as e:
            logger.warning(
                "get_confident_voice_practice_attempt failed id=%s: %s",
                attempt_id, e)
            return None

    def get_processing_purpose(self, purpose_id: str) -> Optional[dict]:
        """One row from the purpose registry, or None.

        None means "could not establish", NOT "not operational" — the two are
        different and the caller must fail closed on both. Raising would turn
        a registry blip into a 500 on a route that has a perfectly good
        "not available yet" answer already."""
        if not purpose_id:
            return None
        try:
            res = (self.client.table("processing_purpose_registry")
                   .select("id,phase,operational,authorizes_processing")
                   .eq("id", str(purpose_id)).limit(1).execute())
            return (res.data or [None])[0]
        except Exception as e:
            logger.warning("get_processing_purpose failed id=%s: %s",
                           purpose_id, e)
            return None

    def list_closed_practices_before(
        self, cutoff_iso: str, limit: int = 50,
    ) -> list[dict]:
        """Practices that closed before `cutoff_iso` — the retention sweep's
        candidates. Open practices are never returned: the speaker is still
        using them.

        Keyed on `closed_at`, NOT `updated_at`: the promise is measured from
        when the practice ended, and `updated_at` moves whenever anything
        touches the row — a coach attaching an explanation video to a finished
        practice would otherwise restart the speaker's 30-day clock. A NULL
        `closed_at` simply does not match, which is the safe direction: a row
        whose clock we cannot read is kept, not guessed at."""
        try:
            res = (self.client.table("confident_voice_practice")
                   .select("id,status,selected_attempt_id,closed_at")
                   .neq("status", "open").lt("closed_at", str(cutoff_iso))
                   .order("closed_at").limit(int(limit)).execute())
            return res.data or []
        except Exception as e:
            logger.warning("list_closed_practices_before failed: %s", e)
            return []

    def list_album_practice_attempt_ids(
        self, attempt_ids: List[str],
    ) -> list[str]:
        """Which of THESE attempts the Voice Album admitted.

        Album membership is Machine Yes + User Yes + Coach Yes about THE EXACT
        recording; deleting the clip would leave the Album listing something
        that no longer exists.

        Asked about a bounded set of ids rather than read whole. voice_album_
        practice has no practice_id column, so the obvious query is an
        unfiltered select of the entire table — which a default row cap can
        silently truncate, and a truncated protected set UNDER-protects, which
        is the one direction this must never fail in. Restricting to the
        attempts the sweep is actually holding makes truncation impossible.

        RAISES on failure. The caller must not treat a failed read as "protect
        nothing": that would widen what gets deleted at the worst moment."""
        wanted = [str(item) for item in (attempt_ids or []) if item]
        if not wanted:
            return []
        try:
            res = (self.client.table("voice_album_practice")
                   .select("practice_attempt_id")
                   .in_("practice_attempt_id", wanted).execute())
            return [str(row.get("practice_attempt_id"))
                    for row in (res.data or [])
                    if row.get("practice_attempt_id")]
        except Exception as e:
            logger.warning("list_album_practice_attempt_ids failed n=%s: %s",
                           len(wanted), e)
            raise

    def delete_practice_audio_object(self, attempt_id: str) -> bool:
        """Delete one practice recording from storage and stamp its registry
        row. Returns False when the object is still out there, so the caller
        keeps the attempt row rather than orphaning the file."""
        if not attempt_id:
            return False
        try:
            found = (self.client.table("processing_practice_objects")
                     .select("id,bucket,object_key,storage_provider,"
                             "exact_bytes_sha256,deleted_at")
                     .eq("practice_attempt_id", str(attempt_id))
                     .limit(1).execute())
            row = (found.data or [None])[0]
            if not row:
                return False
            if row.get("deleted_at") is None:
                from services.lab_audio_storage import (
                    delete_verified_lab_audio_object,
                )
                # Byte-hash verified against the exact coordinates before
                # deletion: the sweep must never remove an object that is not
                # the one the registry recorded.
                if not delete_verified_lab_audio_object(
                        str(row.get("object_key") or ""),
                        bucket=str(row.get("bucket") or ""),
                        storage_provider=str(row.get("storage_provider") or "r2"),
                        expected_sha256=str(row.get("exact_bytes_sha256") or "")):
                    return False
                # An explicit timestamp, not the string "now()": that goes over
                # the wire as a literal for PostgREST to cast, and this is a
                # deletion path where a cast error would strand the registry
                # row un-stamped while the object is already gone. Mirrors the
                # other deleted_at write in this file.
                from datetime import datetime, timezone
                (self.client.table("processing_practice_objects")
                 .update({"deleted_at": datetime.now(timezone.utc).isoformat()})
                 .eq("id", row["id"]).execute())
            return True
        except Exception as e:
            logger.warning("delete_practice_audio_object failed a=%s: %s",
                           attempt_id, e)
            return False

    def delete_confident_voice_practice_attempt(self, attempt_id: str) -> bool:
        """Undo one attempt. Used only when its audio could not be registered
        (services/practice_audio_objects.py) — an attempt whose recording the
        purge cannot reach must not survive."""
        if not attempt_id:
            return False
        try:
            (self.client.table("confident_voice_practice_attempt")
             .delete().eq("id", str(attempt_id)).execute())
            return True
        except Exception as e:
            logger.warning(
                "delete_confident_voice_practice_attempt failed id=%s: %s",
                attempt_id, e)
            return False

    def delete_confident_voice_practice(self, practice_id: str) -> bool:
        """Delete one practice row, once its attempts are gone (0361, E2).

        Its children go by foreign key: coach_moment_error_event CASCADE,
        diagnostic_exercise_teaching.practice_id SET NULL. The caller removes
        every attempt (recording first) before this, so no file is orphaned.
        """
        if not practice_id:
            return False
        try:
            (self.client.table("confident_voice_practice")
             .delete().eq("id", str(practice_id)).execute())
            return True
        except Exception as e:
            logger.warning("delete_confident_voice_practice failed id=%s: %s",
                           practice_id, e)
            return False

    def practice_ids_for_principal(self, principal_id: str) -> list[str]:
        """Every practice belonging to one person, as the governed purge sees
        it (resolve_phase1_purge_subject_graph_v2), so a guest who later
        signed up is one person here exactly as there. Raises on failure: a
        caller erasing data must not read "none" into a failed read."""
        result = self.client.rpc("resolve_phase1_purge_subject_graph_v2", {
            "p_acquisition_principal_id": str(principal_id),
        }).execute()
        data = result.data
        if isinstance(data, list):
            data = data[0] if data else None
        if not isinstance(data, dict) or not isinstance(
                data.get("practice_ids"), list):
            raise RuntimeError("subject graph unavailable")
        return [str(item) for item in data["practice_ids"] if item]

    def list_recent_practice_withdrawals(self, since: str, limit: int) -> list[str]:
        """People whose practice is off by a change made since `since`."""
        result = self.client.rpc("list_recent_practice_withdrawals_v1", {
            "p_since": since, "p_limit": int(limit),
        }).execute()
        return [str(row.get("acquisition_principal_id"))
                for row in (result.data or [])
                if isinstance(row, dict) and row.get("acquisition_principal_id")]

    def insert_practice_audio_object(self, row: dict) -> Optional[dict]:
        """Register one stored practice recording so the purge can reach it.

        Without a row here the file is invisible to data_purge: storage
        deletion only ever acts on processing_audio_objects,
        processing_orphan_objects and this table, so an unregistered upload
        survives its owner asking to be deleted.
        """
        if not isinstance(row, dict):
            return None
        try:
            res = (self.client.table("processing_practice_objects")
                   .insert(row).execute())
            return (res.data or [None])[0]
        except Exception as e:
            logger.warning(
                "insert_practice_audio_object failed attempt=%s: %s",
                row.get("practice_attempt_id"), e)
            return None

    def insert_confident_voice_practice_attempt(
        self, row: dict,
    ) -> Optional[dict]:
        if not isinstance(row, dict):
            return None
        try:
            res = (self.client.table("confident_voice_practice_attempt")
                   .insert(row).execute())
            return (res.data or [None])[0]
        except Exception as e:
            logger.warning("insert_confident_voice_practice_attempt failed practice=%s: %s",
                           row.get("practice_id"), e)
            return None

    def set_confident_voice_practice_strongest(
        self, practice_id: str, attempt_id: str,
    ) -> bool:
        if not practice_id or not attempt_id:
            return False
        try:
            (self.client.table("confident_voice_practice_attempt")
             .update({"is_strongest": False})
             .eq("practice_id", str(practice_id)).execute())
            res = (self.client.table("confident_voice_practice_attempt")
                   .update({"is_strongest": True})
                   .eq("practice_id", str(practice_id))
                   .eq("id", str(attempt_id)).execute())
            return bool(res.data)
        except Exception as e:
            logger.warning("set_confident_voice_practice_strongest failed id=%s: %s",
                           practice_id, e)
            return False

    def update_confident_voice_practice(
        self, practice_id: str, owner_user_id: Optional[str], patch: dict,
    ) -> Optional[dict]:
        if not practice_id or not isinstance(patch, dict):
            return None
        clean = dict(patch)
        clean["updated_at"] = datetime.now(timezone.utc).isoformat()
        try:
            query = (self.client.table("confident_voice_practice")
                     .update(clean).eq("id", str(practice_id)))
            if owner_user_id:
                query = query.eq("owner_user_id", str(owner_user_id))
            res = query.execute()
            return (res.data or [None])[0]
        except Exception as e:
            logger.warning("update_confident_voice_practice failed id=%s: %s",
                           practice_id, e)
            return None

    def keep_confident_voice_practice_attempt(
        self, practice_id: str, attempt_id: str, user_answer: str,
    ) -> Optional[dict]:
        # The same five answers as the first judgement (Q17 A, founder
        # 2026-09-25). Only a Yes keeps the attempt for Voice Album review.
        if user_answer not in ("yes", "in_between", "no", "not_sure",
                               "audio_unclear"):
            return None
        try:
            # Only an attempt belonging to this practice can be selected.
            res = (self.client.table("confident_voice_practice_attempt")
                   .update({
                       "kept": user_answer == "yes",
                       "user_answer": user_answer,
                   })
                   .eq("id", str(attempt_id))
                   .eq("practice_id", str(practice_id)).execute())
            return (res.data or [None])[0]
        except Exception as e:
            logger.warning("keep_confident_voice_practice_attempt failed id=%s: %s",
                           attempt_id, e)
            return None

    def adopt_practice_passage(
        self, *, arc_id: str, owner_user_id: str, expected_text: str,
        new_text: str, new_document: Optional[dict], slide_index: Any,
        practice_id: str, attempt_id: str, before: str, after: str,
    ) -> Optional[dict]:
        """Atomic: the adopted words + Slide map + history row, or nothing
        when the document moved since it was read (see the migration)."""
        result = self.client.rpc("adopt_practice_passage_v1", {
            "p_arc_id": str(arc_id),
            "p_owner_user_id": str(owner_user_id),
            "p_expected_text": expected_text,
            "p_new_text": new_text,
            "p_new_document": new_document,
            "p_slide_index": (slide_index if isinstance(slide_index, int)
                              and not isinstance(slide_index, bool) else None),
            "p_practice_id": str(practice_id),
            "p_attempt_id": str(attempt_id),
            "p_before": before,
            "p_after": after,
        }).execute()
        data = result.data
        if isinstance(data, list):
            return data[0] if data and isinstance(data[0], dict) else None
        return data if isinstance(data, dict) else None

    def list_practice_adoptions(self, arc_id: str, user_id: str,
                                slide_index: int) -> list:
        """One Slide's adopted practice passages, oldest first."""
        try:
            return (self.client.table("ideal_text_practice_adoptions")
                    .select("before_text,after_text,created_at")
                    .eq("arc_id", str(arc_id))
                    .eq("user_id", str(user_id))
                    .eq("slide_index", slide_index)
                    .order("id")
                    .execute().data) or []
        except Exception as e:
            logger.warning("list_practice_adoptions failed arc=%s: %s",
                           arc_id, e)
            return []

    def set_confident_voice_practice_attempt_coach_decision(
        self, practice_id: str, attempt_id: str, decision: str,
        coach_user_id: str,
    ) -> Optional[dict]:
        # The coach answers the speaker's five ways (0390, founder
        # 2026-09-29 Q3a). WRITTEN ONCE (LOCKIN §5c; contract 34; W6
        # 2026-10-05): "the original coach judgment is never editable". An
        # attempt that already carries a coach decision keeps it; the row
        # comes back as it stands, marked ``already_decided``.
        from services.practice_adoption import ANSWERS
        if decision not in ANSWERS:
            return None
        try:
            res = (self.client.table("confident_voice_practice_attempt")
                   .update({
                       "coach_confidence_decision": decision,
                       "coach_confidence_decided_by": str(coach_user_id),
                       "coach_confidence_decided_at": datetime.now(
                           timezone.utc).isoformat(),
                   })
                   .eq("id", str(attempt_id))
                   .eq("practice_id", str(practice_id))
                   .is_("coach_confidence_decision", "null").execute())
            written = (res.data or [None])[0]
            if written:
                return written
            standing = (self.client.table("confident_voice_practice_attempt")
                        .select("*").eq("id", str(attempt_id))
                        .eq("practice_id", str(practice_id)).limit(1).execute())
            row = (standing.data or [None])[0]
            if isinstance(row, dict) and row.get("coach_confidence_decision"):
                return {**row, "already_decided": True}
            return None
        except Exception as e:
            logger.warning(
                "set practice attempt coach decision failed id=%s: %s",
                attempt_id, e)
            return None

    # ── the coach panel's learning additions (migration 0411) ────────────
    # 1b (F8), 7 (C5-a), 6a to 6d (F6), 8 (C5-b) and the coach's exposure
    # record (task 4). Each lane is append-only under its own provenance;
    # none is mixed with another (L3). Readers raise so the ledger names the
    # source as unavailable rather than reading zero; writers raise so the
    # service can say what refused.

    def insert_coach_exercise_preference(self, row: dict) -> Optional[dict]:
        """One kept/swapped/new (F8, 0411). Raises on failure."""
        res = self.client.table("coach_exercise_preference").insert(row).execute()
        return (res.data or [None])[0]

    def list_coach_exercise_preferences(self, limit: int = 5000) -> list[dict]:
        res = (self.client.table("coach_exercise_preference").select("*")
               .order("created_at", desc=True).limit(int(limit)).execute())
        return list(res.data or [])

    def record_coach_clip_exposure(
        self, *, coach_id: str, clip_id: str, clip_kind: str, via: str,
    ) -> bool:
        """The first time this coach saw this clip's non-blind side (task 4,
        0411): True when new, False when it was already recorded (the first
        exposure stands). Raises on any other failure."""
        try:
            self.client.table("coach_clip_exposures").insert({
                "coach_id": str(coach_id), "clip_id": str(clip_id),
                "clip_kind": str(clip_kind), "via": str(via),
            }).execute()
        except Exception as e:
            text = str(e).lower()
            if "23505" in text or "duplicate" in text or "unique" in text:
                return False
            raise
        return True

    def list_coach_clip_exposures(self, coach_id: str, clip_ids: list[str]) -> list[dict]:
        ids = [str(c) for c in clip_ids if c]
        if not ids:
            return []
        res = (self.client.table("coach_clip_exposures").select("clip_id,clip_kind,via")
               .eq("coach_id", str(coach_id)).in_("clip_id", ids).execute())
        return list(res.data or [])

    def count_coach_blind_answers(self, coach_id: str, week: str) -> int:
        """Blind answers this coach gave this week across the audit (6a) and
        the block pick (8): the shared weekly cap."""
        audits = (self.client.table("error_presence_audit").select("id", count="exact")
                  .eq("coach_id", str(coach_id)).eq("week", str(week))
                  .not_.is_("answer", "null").limit(1).execute())
        picks = (self.client.table("coach_block_pick").select("id", count="exact")
                 .eq("coach_id", str(coach_id)).eq("week", str(week))
                 .not_.is_("answered_at", "null").limit(1).execute())
        return int(audits.count or 0) + int(picks.count or 0)

    def list_error_presence_audit_pending(self, coach_id: str) -> list[dict]:
        res = (self.client.table("error_presence_audit").select("*")
               .eq("coach_id", str(coach_id)).is_("answer", "null")
               .order("created_at").execute())
        return list(res.data or [])

    def list_error_presence_audit_by_coach(self, coach_id: str) -> list[dict]:
        res = (self.client.table("error_presence_audit")
               .select("id,clip_id,error_id,answer,week")
               .eq("coach_id", str(coach_id)).execute())
        return list(res.data or [])

    def list_error_presence_audit_answered(self, error_id: str) -> list[dict]:
        res = (self.client.table("error_presence_audit").select("*")
               .eq("error_id", str(error_id)).not_.is_("answer", "null").execute())
        return list(res.data or [])

    def list_error_presence_audit_answered_all(self, limit: int = 20000) -> list[dict]:
        res = (self.client.table("error_presence_audit").select("*")
               .not_.is_("answer", "null").order("answered_at", desc=True)
               .limit(int(limit)).execute())
        return list(res.data or [])

    def list_audit_candidates(self, errors: list[str], limit: int = 2000) -> list[dict]:
        """Clips the audit may sample (6a): the live detector's verdict per
        (clip, error) from the shadow log, with the speaker and how many
        coaches answered on it already. The verdict itself travels only
        into fired_at_sampling; no reader shows it."""
        from services.confident_voice_practice import SIGNAL_RULES_VERSION
        from services.detector_rollout import LIVE_DETECTOR
        from services.verbal_cues import VERBAL_CUES_VERSION
        wanted = [str(e) for e in errors if e]
        if not wanted:
            return []
        res = (self.client.table("verbal_cue_shadow_observations")
               .select("snippet_id,take_session_id,error_id,detector_version,"
                       "fired,measurements,clip_kind,created_at")
               .in_("error_id", wanted).order("created_at", desc=True)
               .limit(int(limit)).execute())
        rows = [r for r in (res.data or []) if isinstance(r, dict)]
        rows = [r for r in rows
                if str(r.get("detector_version")) ==
                str(LIVE_DETECTOR.get(str(r.get("error_id")), VERBAL_CUES_VERSION))]
        takes = sorted({str(r.get("take_session_id")) for r in rows if r.get("take_session_id")})
        speaker: dict[str, str] = {}
        for i in range(0, len(takes), 200):
            got = (self.client.table("v2_sessions").select("id,user_id")
                   .in_("id", takes[i:i + 200]).execute())
            speaker.update({str(s.get("id")): str(s.get("user_id") or "")
                            for s in (got.data or []) if isinstance(s, dict)})
        clips = sorted({str(r.get("snippet_id")) for r in rows})
        answered: dict[tuple[str, str], int] = {}
        for i in range(0, len(clips), 200):
            got = (self.client.table("error_presence_audit").select("clip_id,error_id")
                   .in_("clip_id", clips[i:i + 200]).not_.is_("answer", "null").execute())
            for a in got.data or []:
                key = (str(a.get("clip_id")), str(a.get("error_id")))
                answered[key] = answered.get(key, 0) + 1
        return [{
            "clip_id": str(r.get("snippet_id")),
            "clip_kind": str(r.get("clip_kind") or "snippet"),
            "take_session_id": r.get("take_session_id"),
            "speaker_user_id": speaker.get(str(r.get("take_session_id")) or ""),
            "error_id": str(r.get("error_id")),
            "fired": bool(r.get("fired")),
            "detector_version": r.get("detector_version"),
            "signal_rules_version": SIGNAL_RULES_VERSION,
            "measurements": r.get("measurements") or {},
            "answered_count": answered.get((str(r.get("snippet_id")), str(r.get("error_id"))), 0),
        } for r in rows]

    def insert_error_presence_audit(self, row: dict) -> Optional[dict]:
        res = self.client.table("error_presence_audit").insert(row).execute()
        return (res.data or [None])[0]

    def audit_clip_audio(self, clip_id: str, clip_kind: str) -> Optional[str]:
        """The clip's audio ref, by kind; None when unreadable."""
        if clip_kind == "practice_attempt":
            attempt = self.get_confident_voice_practice_attempt(str(clip_id)) or {}
            return attempt.get("audio_ref") or None
        snippet = self.get_snippet_by_id(str(clip_id)) or {}
        return snippet.get("audio_segment_path") or None

    def answer_error_presence_audit(
        self, *, audit_id: str, coach_id: str, answer: str,
    ) -> Optional[dict]:
        """One answer, once: None when the row is not this coach's or is
        already answered."""
        res = (self.client.table("error_presence_audit")
               .update({"answer": str(answer),
                        "answered_at": datetime.now(timezone.utc).isoformat()})
               .eq("id", str(audit_id)).eq("coach_id", str(coach_id))
               .is_("answer", "null").execute())
        return (res.data or [None])[0]

    def list_coach_block_picks_pending(self, coach_id: str) -> list[dict]:
        res = (self.client.table("coach_block_pick").select("*")
               .eq("coach_id", str(coach_id)).is_("answered_at", "null")
               .order("created_at").execute())
        return list(res.data or [])

    def list_coach_block_picks_by_coach(self, coach_id: str) -> list[dict]:
        res = (self.client.table("coach_block_pick").select("id,block_id,answered_at,week")
               .eq("coach_id", str(coach_id)).execute())
        return list(res.data or [])

    def list_coach_block_picks_all(self, limit: int = 20000) -> list[dict]:
        res = (self.client.table("coach_block_pick").select("*")
               .not_.is_("answered_at", "null").order("answered_at", desc=True)
               .limit(int(limit)).execute())
        return list(res.data or [])

    def list_takes_coach_is_walking(self, coach_id: str) -> list[str]:
        """Takes this coach has rated a moment of: the block pick never asks
        about a Take the coach walks (8)."""
        res = (self.client.table("confidence_labels").select("session_id")
               .eq("rater_id", str(coach_id)).not_.is_("session_id", "null")
               .limit(5000).execute())
        return sorted({str(r.get("session_id")) for r in (res.data or [])
                       if isinstance(r, dict) and r.get("session_id")})

    def list_recent_v3_frames(self, limit: int = 200) -> list[dict]:
        res = (self.client.table("take_feedback_policy_v3_shadow_frames")
               .select("take_session_id,policy_version,frame,created_at")
               .order("created_at", desc=True).limit(int(limit)).execute())
        return list(res.data or [])

    def insert_coach_block_pick(self, row: dict) -> Optional[dict]:
        res = self.client.table("coach_block_pick").insert(row).execute()
        return (res.data or [None])[0]

    def get_coach_block_pick(self, pick_id: str, coach_id: str) -> Optional[dict]:
        res = (self.client.table("coach_block_pick").select("*")
               .eq("id", str(pick_id)).eq("coach_id", str(coach_id)).limit(1).execute())
        return (res.data or [None])[0]

    def answer_coach_block_pick(
        self, *, pick_id: str, coach_id: str, pick_snippet_id: Optional[str],
        cant_tell: bool,
    ) -> Optional[dict]:
        res = (self.client.table("coach_block_pick")
               .update({"pick_snippet_id": pick_snippet_id, "cant_tell": bool(cant_tell),
                        "answered_at": datetime.now(timezone.utc).isoformat()})
               .eq("id", str(pick_id)).eq("coach_id", str(coach_id))
               .is_("answered_at", "null").execute())
        return (res.data or [None])[0]

    def list_shadow_observations_by_version(
        self, detector_version: str, limit: int = 50000,
    ) -> list[dict]:
        res = (self.client.table("verbal_cue_shadow_observations")
               .select("snippet_id,error_id,fired,clip_kind")
               .eq("detector_version", str(detector_version)).limit(int(limit)).execute())
        return list(res.data or [])

    def shadow_since(self, detector_version: str) -> Optional[str]:
        """When this version's first shadow verdict was logged."""
        res = (self.client.table("verbal_cue_shadow_observations").select("created_at")
               .eq("detector_version", str(detector_version))
               .order("created_at").limit(1).execute())
        row = (res.data or [None])[0]
        return str(row.get("created_at")) if isinstance(row, dict) and row.get("created_at") else None

    def list_clips_for_rescore(self, *, since: str, limit: int = 2000) -> list[dict]:
        """Clips and attempts since `since` with their stored snapshots, for
        a silent re-score under a candidate version (6d)."""
        from services.confident_voice_practice import acoustic_snapshot
        out: list[dict] = []
        snippets = (self.client.table("snippets").select("id,session_id,metrics,created_at")
                    .gte("created_at", str(since)).order("created_at")
                    .limit(int(limit)).execute())
        for s in snippets.data or []:
            if isinstance(s, dict) and s.get("id"):
                out.append({"clip_id": str(s["id"]), "clip_kind": "snippet",
                            "take_session_id": str(s.get("session_id") or ""),
                            "snapshot": acoustic_snapshot(s)})
        attempts = (self.client.table("confident_voice_practice_attempt")
                    .select("id,practice_id,acoustic_metrics,created_at")
                    .gte("created_at", str(since)).order("created_at")
                    .limit(int(limit)).execute())
        rows = [a for a in (attempts.data or []) if isinstance(a, dict) and a.get("id")]
        practice_ids = sorted({str(a.get("practice_id")) for a in rows if a.get("practice_id")})
        take_of: dict[str, str] = {}
        for i in range(0, len(practice_ids), 200):
            got = (self.client.table("confident_voice_practice").select("id,take_session_id")
                   .in_("id", practice_ids[i:i + 200]).execute())
            take_of.update({str(p.get("id")): str(p.get("take_session_id") or "")
                            for p in (got.data or []) if isinstance(p, dict)})
        for a in rows:
            out.append({"clip_id": str(a["id"]), "clip_kind": "practice_attempt",
                        "take_session_id": take_of.get(str(a.get("practice_id")), ""),
                        "snapshot": a.get("acoustic_metrics")})
        return out

    def list_bookmarked_snippet_ids(self, take_session_id: str) -> list[str]:
        """The Take's frozen Confident Voice bookmarks, in the Take's order;
        [] while not frozen. The Take word's blind gate (7)."""
        from services.take_feedback_set import (
            CONFIDENT_VOICE_FAMILY, sanitize_selected_keys,
        )
        session = self.v2_get_session_by_id(str(take_session_id)) or {}
        arc_id = session.get("arc_id")
        if not arc_id:
            return []
        row = self.get_ideal_text_feedback_set(str(arc_id), str(take_session_id))
        if not row:
            return []
        marked = {str(key["snippet_id"]) for key in sanitize_selected_keys(row.get("selected_keys"))
                  if key.get("feedback_family") == CONFIDENT_VOICE_FAMILY and key.get("snippet_id")}
        return [str(s.get("id")) for s in self.get_snippets_by_session(str(take_session_id)) or []
                if isinstance(s, dict) and str(s.get("id")) in marked]

    def set_coach_take_word_draft(
        self, *, take_session_id: str, coach_id: str, text: str,
        model_version: Optional[str],
    ) -> Optional[dict]:
        """The model's draft of the Take word (7, 0411), on the coach's row,
        created draft-only when the word is not written yet. Raises on
        failure."""
        now = datetime.now(timezone.utc).isoformat()
        res = (self.client.table("coach_take_words")
               .upsert({"take_session_id": str(take_session_id), "coach_id": str(coach_id),
                        "draft_text": str(text), "draft_model_version": model_version or None,
                        "drafted_at": now, "updated_at": now},
                       on_conflict="take_session_id,coach_id").execute())
        return (res.data or [None])[0]

    def set_coach_take_word_transcript(
        self, *, take_session_id: str, coach_id: str, transcript: str,
    ) -> Optional[dict]:
        res = (self.client.table("coach_take_words")
               .update({"transcript": str(transcript),
                        "transcribed_at": datetime.now(timezone.utc).isoformat()})
               .eq("take_session_id", str(take_session_id))
               .eq("coach_id", str(coach_id)).execute())
        return (res.data or [None])[0]

    def list_coach_word_drafts(self, limit: int = 5000) -> list[dict]:
        """Every draft shown on the two coach-word surfaces and whether it
        went unchanged: [{surface, unchanged}] for the ledger (7)."""
        out: list[dict] = []
        words = (self.client.table("coach_take_words").select("text,draft_text")
                 .not_.is_("draft_text", "null").limit(int(limit)).execute())
        for w in words.data or []:
            if isinstance(w, dict) and w.get("text"):
                out.append({"surface": "coach_take_word",
                            "unchanged": str(w.get("text") or "").strip()
                            == str(w.get("draft_text") or "").strip()})
        lines = (self.client.table("exercise_coach_requests").select("answer_text,draft_text")
                 .eq("draft_surface", "coach_moment_line").not_.is_("resolution", "null")
                 .limit(int(limit)).execute())
        for r in lines.data or []:
            if isinstance(r, dict) and r.get("answer_text"):
                out.append({"surface": "coach_moment_line",
                            "unchanged": str(r.get("answer_text") or "").strip()
                            == str(r.get("draft_text") or "").strip()})
        return out



# Singleton instance
db = DatabaseService()


def new_client() -> Client:
    """A FRESH service-role client, for the few calls that must not share the
    singleton's session (the auth routes' password grant and admin user
    calls mutate the client's auth state). This is the only other place a
    client comes from; nothing outside this module calls create_client
    (audit Q-A2, tests/test_db_client_fence.py)."""
    return db._build_supabase_client()

# The first-client exercise surface has a dedicated persistence boundary.  It
# shares the already-configured Supabase client but does not enlarge the
# application-wide DatabaseService API.
from services.first_client_repository import FirstClientRepository  # noqa: E402

first_client_repository = FirstClientRepository(lambda: db.client)
