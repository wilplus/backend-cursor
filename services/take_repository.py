"""Take repository — the F1 v2_sessions (Takes) table access carved out of services/db.py
(audit Q-A1 step 2 / Q-A2, Phase 4, 2026-09-14).

Every method here is the verbatim body it had on DatabaseService; db.py keeps
a one-line delegate under the same name, so the ~360 test sites that patch
``db.<method>`` and every caller keep working unchanged. The repository takes
the injected database service (the feedback_repository idiom) and reads the
Supabase client THROUGH it on every call (``self.client`` is a property), so
``DatabaseService.reset_connections()`` — the post-fork rebuild — is seen here
too. Nothing in this module constructs a client; only services/db.py does.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone  # noqa: F401 — used by the moved bodies
from typing import Any, Dict, List, Optional  # noqa: F401

import sentry_sdk  # noqa: F401

from services.table_repository import TableRepository

logger = logging.getLogger(__name__)


class TakeRepository(TableRepository):
    def v2_update_session(self, session_id: str, user_id: str, data: dict):
        """Update v2 session; verify user_id."""
        result = self.client.table("v2_sessions").update(data).eq("id", session_id).eq("user_id", user_id).execute()
        return result.data[0] if result.data else None

    def v2_delete_session(self, session_id: str, user_id: str) -> bool:
        """Delete v2 session (owner only). Recordings.session_v2_id set to NULL; v2_reports CASCADE deleted. Returns True when delete executes without error (Supabase delete may return empty body).

        NOTE: The schema has a mutual FK cycle between v2_sessions and v2_reports:
          v2_sessions.report_id → v2_reports(id) ON DELETE SET NULL
          v2_reports.session_v2_id → v2_sessions(id) ON DELETE CASCADE
        PostgreSQL can raise a constraint-cycle error when both fire in the same transaction.
        We break the cycle first by nulling out the FK columns on v2_sessions before deleting.
        Same precaution for recording_1_id (bidirectional with recordings table).
        """
        # Step 1: Break circular FK references to avoid PostgreSQL constraint-cycle errors.
        try:
            self.client.table("v2_sessions").update({
                "recording_1_id": None,
                "report_id": None,
            }).eq("id", session_id).eq("user_id", user_id).execute()
        except Exception:
            pass  # Best-effort; proceed to delete regardless.

        # Step 2: Delete the session row (v2_reports CASCADE, recordings.session_v2_id SET NULL).
        self.client.table("v2_sessions").delete().eq("id", session_id).eq("user_id", user_id).execute()
        # PostgREST/Supabase delete often returns empty result.data even on success; if we got here without exception, treat as success.
        return True

    def v2_get_incomplete_sessions_older_than(self, hours: float) -> List[dict]:
        """Return v2_sessions that are not completed and created_at is older than hours (for cleanup)."""
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        result = (
            self.client.table("v2_sessions")
            .select("id, user_id, created_at, status")
            .neq("status", "completed")
            .lt("created_at", cutoff)
            .execute()
        )
        return result.data or []

    def v2_get_session(self, session_id: str, user_id: Optional[str] = None):
        """Get v2 session by id, optionally scoped to user."""
        q = self.client.table("v2_sessions").select("*").eq("id", session_id)
        if user_id:
            q = q.eq("user_id", user_id)
        result = q.execute()
        return result.data[0] if result.data else None

    def v2_update_session_status_unscoped(self, session_id: str, status: str) -> Optional[dict]:
        """Update v2_sessions.status without user_id scoping (admin/internal usage).

        NOTE: v2_sessions has NO ``updated_at`` column (confirmed against the
        live schema — it has created_at/completed_at/coach_approved_at/... but
        no plain updated_at). Writing it made PostgREST reject the ENTIRE
        update (PGRST204 "could not find the 'updated_at' column"), so the
        status flip silently never landed — and callers
        (lab_send.send_lab_recording_to_coach, session_publish finalize) wrap
        this in try/except, masking the failure. Status-only payload here;
        every other v2_sessions update writes its own fields without
        updated_at too.
        """
        result = (
            self.client.table("v2_sessions")
            .update({"status": status})
            .eq("id", session_id)
            .execute()
        )
        return result.data[0] if result.data else None

    def v2_mark_session_pending_review(
        self, session_id: str,
    ) -> Optional[dict]:
        """Atomically enter the coach queue and stamp its canonical ordering time."""
        from datetime import datetime, timezone

        result = (
            self.client.table("v2_sessions")
            .update({
                "status": "pending_admin_review",
                "coach_review_status": "queued",
                "review_requested_at": datetime.now(timezone.utc).isoformat(),
            })
            .eq("id", session_id)
            .execute()
        )
        return result.data[0] if result.data else None

    def v2_publish_session_results(self, session_id: str) -> Optional[dict]:
        """Set results_published_at on a session (admin publish action).

        This flag tells the user-facing /results page that snippets are ready.
        """
        from datetime import datetime, timezone
        result = (
            self.client.table("v2_sessions")
            .update({"results_published_at": datetime.now(timezone.utc).isoformat()})
            .eq("id", session_id)
            .execute()
        )
        return result.data[0] if result.data else None

    def v2_get_latest_published_session_for_user(self, user_id: str) -> Optional[dict]:
        """Return the most recent session with results_published_at set (for /results landing)."""
        try:
            result = (
                self.client.table("v2_sessions")
                .select("*")
                .eq("user_id", user_id)
                .not_.is_("results_published_at", "null")
                .order("results_published_at", desc=True)
                .limit(1)
                .execute()
            )
            return result.data[0] if result.data else None
        except Exception as e:
            logger.warning("v2_get_latest_published_session_for_user failed: %s", e)
            return None

    def v2_get_latest_session_for_user(self, user_id: str) -> Optional[dict]:
        """Return the most recent session for a user (any status, including
        unfinished / unpublished). Used by /v2/user/sessions/current to expose
        the full state machine to the frontend so it can route correctly.
        """
        try:
            result = (
                self.client.table("v2_sessions")
                .select("*")
                .eq("user_id", user_id)
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
            return result.data[0] if result.data else None
        except Exception as e:
            logger.warning("v2_get_latest_session_for_user failed: %s", e)
            return None

    def v2_get_published_sessions_for_user(self, user_id: str) -> List[dict]:
        """All published sessions for a user, newest first.

        Powers the /v2/user/results/me Voice-Journey timeline. Returns an
        empty list when the user has nothing published — the endpoint must
        NEVER fall back to mock data.
        """
        try:
            result = (
                self.client.table("v2_sessions")
                .select("*")
                .eq("user_id", user_id)
                .not_.is_("results_published_at", "null")
                .order("results_published_at", desc=True)
                .execute()
            )
            return result.data or []
        except Exception as e:
            logger.warning("v2_get_published_sessions_for_user failed: %s", e)
            return []

    def v2_get_last_completed_session(self, user_id: str):
        """Return the most recent completed session for the user (for tutor_feedback_deadline when no active session). Includes tutor_feedback_sent_at so deadline is omitted once feedback is sent."""
        wide = "id, report_id, completed_at, created_at, tutor_feedback_sent_at, student_completion_email_sent_at, score_for_display"
        base = "id, report_id, completed_at, created_at, tutor_feedback_sent_at, student_completion_email_sent_at"
        try:
            result = (
                self.client.table("v2_sessions")
                .select(wide)
                .eq("user_id", user_id)
                .eq("status", "completed")
                .order("completed_at", desc=True)
                .limit(1)
                .execute()
            )
            return result.data[0] if result.data else None
        except Exception as e:
            msg = str(e).lower()
            if "score_for_display" in msg or "42703" in msg or "does not exist" in msg:
                result = (
                    self.client.table("v2_sessions")
                    .select(base)
                    .eq("user_id", user_id)
                    .eq("status", "completed")
                    .order("completed_at", desc=True)
                    .limit(1)
                    .execute()
                )
                return result.data[0] if result.data else None
            raise

    def v2_get_latest_session_id_for_user(self, user_id: str) -> Optional[str]:
        """Most recent v2_sessions.id by created_at (any status). For admin UI when no completed row exists."""
        try:
            result = (
                self.client.table("v2_sessions")
                .select("id")
                .eq("user_id", user_id)
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )
            if not result.data:
                return None
            sid = result.data[0].get("id")
            return str(sid) if sid else None
        except Exception as e:
            logger.warning("v2_get_latest_session_id_for_user failed user_id=%s: %s", user_id, e)
            return None

    def v2_mark_tutor_feedback_sent(self, session_id: str, user_id: str):
        """Set tutor_feedback_sent_at to now for this session (idempotent)."""
        from datetime import datetime, timezone
        self.client.table("v2_sessions").update({
            "tutor_feedback_sent_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", session_id).eq("user_id", user_id).execute()
        return True

    def _session_homework_recording_words_per_minute(self, session_id: str):
        """Words per minute from the recording linked to a v2 session (recording_1)."""
        if not session_id:
            return None
        try:
            sess = (
                self.client.table("v2_sessions")
                .select("recording_1_id")
                .eq("id", session_id)
                .limit(1)
                .execute()
            )
            if not sess.data:
                return None
            s0 = sess.data[0]
            rid = s0.get("recording_1_id")
            if not rid:
                return None
            rec_res = (
                self.client.table("recordings")
                .select("words_per_minute")
                .eq("id", str(rid))
                .limit(1)
                .execute()
            )
            if not rec_res.data:
                return None
            return rec_res.data[0].get("words_per_minute")
        except Exception as e:
            logger.debug("_session_homework_recording_words_per_minute: %s", e)
            return None

    def v2_find_session_by_upload_key(self, key: Optional[str]
                                      ) -> Optional[dict]:
        """The retry-collapse lookup (founder 2026-08-10, the double
        recording): same key = same take = the same session. None on
        anything missing — the POST then proceeds as a first attempt."""
        if not key:
            return None
        try:
            res = (
                self.client.table("v2_sessions")
                .select("*")
                .eq("upload_idempotency_key", str(key))
                .limit(1)
                .execute()
            )
            rows = res.data or []
            return rows[0] if rows else None
        except Exception as e:
            logger.warning("v2_find_session_by_upload_key failed: %s", e)
            return None

    def v2_set_session_upload_key(self, session_id: str,
                                  key: Optional[str]) -> bool:
        """Stamp the take's idempotency key on its session. Best-effort —
        a miss just means a retry cannot collapse (today's behavior)."""
        if not session_id or not key:
            return False
        try:
            (self.client.table("v2_sessions")
             .update({"upload_idempotency_key": str(key)})
             .eq("id", str(session_id))
             .execute())
            return True
        except Exception as e:
            logger.warning("v2_set_session_upload_key failed sid=%s: %s",
                           session_id, e)
            return False

    def v2_create_recording_session(
        self,
        session_id: str,
        *,
        owner_principal_id: Optional[str],
        user_id: Optional[str],
        recording_id: Optional[str] = None,
    ) -> Optional[dict]:
        """Create a canonical Take row with a verified owner from its first write."""
        if not owner_principal_id:
            raise ValueError("owner_principal_id is required")
        payload = {
            "id": session_id,
            "user_id": user_id,
            "owner_principal_id": owner_principal_id,
            "status": "processing",
        }
        if recording_id:
            payload["recording_1_id"] = recording_id
        result = self.client.table("v2_sessions").insert(payload).execute()
        return result.data[0] if result.data else None

    def v2_create_internal_session(self, session_id: str) -> Optional[dict]:
        """Create an intentionally ownerless internal training/annotation row."""
        result = self.client.table("v2_sessions").insert({
            "id": session_id,
            "user_id": None,
            "status": "processing",
        }).execute()
        return result.data[0] if result.data else None

    def next_project_take_index(self, project_id: str) -> int:
        try:
            result = (self.client.table("v2_sessions")
                      .select("take_index,analysis_state")
                      .eq("project_id", str(project_id)).execute())
            # A failed take retains its ordinal. Only a genuinely new upload
            # reserves the next index; retries reuse the existing take id.
            indexes = [int(row.get("take_index")) for row in (result.data or [])
                       if isinstance(row.get("take_index"), int)]
            return max(indexes, default=0) + 1
        except Exception as e:
            logger.warning("next_project_take_index failed project=%s: %s",
                           project_id, e)
            raise

    def get_project_take_by_upload_key(
        self, project_id: str, upload_key: str,
    ) -> Optional[dict]:
        """Project-scoped retry collapse; never leaks another owner's take."""
        if not project_id or not upload_key:
            return None
        try:
            result = (self.client.table("v2_sessions").select("*")
                      .eq("project_id", str(project_id))
                      .eq("upload_idempotency_key", str(upload_key))
                      .limit(1).execute())
            return result.data[0] if result.data else None
        except Exception as error:
            logger.warning(
                "get_project_take_by_upload_key failed project=%s: %s",
                project_id, error,
            )
            return None

    def get_project_take_for_owner(
        self, project_id: str, take_id: str, owner_principal_id: str,
    ) -> Optional[dict]:
        """Load one Take only when both canonical ownership coordinates match."""
        try:
            result = (self.client.table("v2_sessions").select("*")
                      .eq("id", str(take_id))
                      .eq("project_id", str(project_id))
                      .eq("owner_principal_id", str(owner_principal_id))
                      .limit(1).execute())
            return result.data[0] if result.data else None
        except Exception as error:
            logger.warning(
                "get_project_take_for_owner failed project=%s take=%s: %s",
                project_id, take_id, error,
            )
            return None

    def v2_set_session_recording(
        self, session_id: str, recording_id: str,
    ) -> Optional[dict]:
        """Link a recording to its already-owned Take row."""
        result = (
            self.client.table("v2_sessions")
            .update({"recording_1_id": recording_id})
            .eq("id", session_id)
            .execute()
        )
        return result.data[0] if result.data else None

    def list_coach_students(self, *, limit: int = 100, offset: int = 0) -> list[dict]:
        """willab coach roster (UX Wave v2 E3 / §B.4). Distinct users who have
        a willab Lab session, newest-active first. Returns raw rows
        [{user_id, last_active, session_count}]; the route pseudonymizes +
        attaches the profile domain (NEVER name/email here). session_count =
        the user's total Lab sessions — the read-only coach-load / heavy-user
        signal for the beta "drowning guard" (accurate up to the scan cap
        below). Solo-coach beta: every willab student is in scope (no per-coach
        assignment table yet). Scans up to 2000 recent Lab sessions, dedups in
        Python (PostgREST has no DISTINCT), then pages — fine at beta scale;
        revisit if the roster grows large.
        """
        try:
            res = (
                self.client.table("v2_sessions")
                .select("user_id, created_at, review_requested_at")
                .eq("source", "audit_upload")
                .order("created_at", desc=True)
                .limit(2000)
                .execute()
            )
            seen: dict[str, dict] = {}
            for r in (res.data or []):
                uid = r.get("user_id")
                if not uid:
                    continue  # unclaimed guest rows have no user — skip
                ts = r.get("review_requested_at") or r.get("created_at") or ""
                key = str(uid)
                entry = seen.get(key)
                if entry is None:
                    seen[key] = {"user_id": key, "last_active": ts, "session_count": 1}
                else:
                    entry["session_count"] += 1
                    if ts > entry["last_active"]:
                        entry["last_active"] = ts
            rows = sorted(seen.values(), key=lambda x: x["last_active"], reverse=True)
            return rows[offset:offset + limit]
        except Exception as e:
            err_low = str(e).lower()
            if "source" in err_low and "pgrst" in err_low:
                logger.warning(
                    "list_coach_students: source column missing (run "
                    "migrations/add_foundation_discriminators.sql)",
                )
                return []
            logger.warning("list_coach_students failed err=%s", e)
            return []

    def v2_list_user_lab_sessions(self, user_id: str, *, limit: int = 200) -> list[dict]:
        """All of a user's willab Lab sessions (source=audit_upload), newest
        first. Powers the coach drill-down (E-1b), the user_audit assembly
        (BE-3), and the cumulative recorded-seconds sum (BE-1). Best-effort:
        [] on missing column / DB hiccup."""
        if not user_id:
            return []
        try:
            res = (
                self.client.table("v2_sessions")
                .select("id, recording_1_id, intake_context, status, "
                        "created_at, review_requested_at, results_published_at, "
                        "coach_overall_message, project_id, arc_id, take_index, "
                        "slide_transcripts, coach_feedback_saved_at, "
                        "recording_kind, paired_session_id")
                .eq("user_id", user_id)
                .eq("source", "audit_upload")
                .order("created_at", desc=True)
                .limit(limit)
                .execute()
            )
            return res.data or []
        except Exception as e:
            err_low = str(e).lower()
            if "source" in err_low and "pgrst" in err_low:
                return []
            # arc_id/take_index/slide_transcripts/coach_feedback_saved_at/
            # recording_kind/paired_session_id are later migrations — fall
            # back to the base select if any isn't present yet.
            if any(c in err_low for c in
                   ("arc_id", "take_index", "slide_transcripts",
                    "coach_feedback_saved_at",
                    "recording_kind", "paired_session_id")):
                try:
                    res = (
                        self.client.table("v2_sessions")
                        .select("id, recording_1_id, intake_context, status, "
                                "created_at, review_requested_at, "
                                "results_published_at, coach_overall_message")
                        .eq("user_id", user_id)
                        .eq("source", "audit_upload")
                        .order("created_at", desc=True)
                        .limit(limit)
                        .execute()
                    )
                    return res.data or []
                except Exception:
                    return []
            logger.warning(
                "v2_list_user_lab_sessions failed user=%s err=%s", user_id, e,
            )
            return []

    def list_orphaned_processing_sessions(
        self, stale_minutes: int = 30, max_rows: int = 100,
    ) -> List[Dict[str, Any]]:
        """Sessions stuck on analysis_state='processing' with NO active job.

        The gap this closes: the job sweeper only walks processing_jobs, so a
        session flipped to 'processing' that never got a job row is invisible
        to it and shows "Working on your take" forever. Two ways to get one:
        the pre-queue daemon path (ASYNC_ANALYSIS_ENABLED) whose thread died
        with a redeploy, and a crash-looping worker window where the enqueue
        never landed.

        Deliberately generous default cutoff (30 min > the job sweeper's 15):
        a session is only a candidate once it is far past any plausible live
        run, AND has no active job protecting it. Reaping one that IS somehow
        still being worked is self-healing anyway — whoever finishes writes
        'ready' over the 'failed'.

        v2_sessions has no updated_at column (PGRST204 lesson), so created_at
        is the clock. In this flow analysis starts moments after the row is
        created, which makes it a fair proxy.
        """
        from datetime import timedelta
        cutoff = (
            datetime.now(timezone.utc) - timedelta(minutes=max(5, stale_minutes))
        ).isoformat()
        try:
            res = (
                self.client.table("v2_sessions")
                .select("id, analysis_state, created_at")
                .eq("analysis_state", "processing")
                .lt("created_at", cutoff)
                .limit(max_rows)
                .execute()
            )
            candidates = res.data or []
        except Exception as e:
            logger.warning("list_orphaned_processing_sessions: %s", e)
            return []
        if not candidates:
            return []
        # Subtract anything a live job still owns — that one is not orphaned.
        protected: set = set()
        try:
            ids = [str(r.get("id")) for r in candidates if r.get("id")]
            res = (
                self.client.table("processing_jobs")
                .select("session_id, status")
                .in_("session_id", ids)
                .in_("status", ["pending", "processing"])
                .execute()
            )
            protected = {
                str(r.get("session_id")) for r in (res.data or [])
                if r.get("session_id")
            }
        except Exception as e:
            # Fail CLOSED: if the guard query fails we cannot tell orphaned
            # from live, and failing a running take is worse than a banner
            # that clears one sweep later.
            logger.warning(
                "list_orphaned_processing_sessions: active-job guard failed "
                "(%s) — skipping this pass", e)
            return []
        return [r for r in candidates if str(r.get("id")) not in protected]

    def v2_get_last_completed_session_full(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Latest completed homework session row (wide select) for copilot / admin seeding."""
        try:
            res = (
                self.client.table("v2_sessions")
                .select("*")
                .eq("user_id", user_id)
                .eq("status", "completed")
                .order("completed_at", desc=True)
                .limit(1)
                .execute()
            )
            return res.data[0] if res.data else None
        except Exception as e:
            logger.warning("v2_get_last_completed_session_full failed for %s: %s", user_id, e)
            return None

    def stamp_review_opened(self, session_id: Optional[str]) -> bool:
        """First-touch stamp of when the coach OPENED a session for review
        (readiness rig #3 — coach-time baseline = results_published_at -
        review_opened_at). Idempotent: set ONLY when NULL, so the first open
        wins. Best-effort → False on missing column / error; NEVER raises into
        the coach review path."""
        if not session_id:
            return False
        now = datetime.now(timezone.utc).isoformat()
        try:
            res = (
                self.client.table("v2_sessions")
                .update({"review_opened_at": now})
                .eq("id", session_id)
                .is_("review_opened_at", "null")
                .execute()
            )
            return bool(res.data)
        except Exception as e:
            err_low = str(e).lower()
            if "review_opened_at" in err_low and (
                "does not exist" in err_low or "pgrst" in err_low
            ):
                return False
            logger.warning("stamp_review_opened failed sid=%s: %s", session_id, e)
            return False

    def set_session_conversation_summary(
        self,
        session_id: str,
        summary: Optional[str],
    ) -> Optional[dict]:
        """Phase A2.1 — persist the rolling interview digest.

        Called by services/conversation_summary.py after each turn.
        Stamps conversation_summary_updated_at so the prompt builder
        can detect staleness.

        Passing ``summary=None`` clears the column — useful for
        admin resets or when graduation invalidates the digest.

        Failure logs + returns None; the caller (the async
        updater) treats a failed persist as "leave previous
        summary in place" rather than blocking the next turn.
        """
        try:
            now = datetime.now(timezone.utc).isoformat()
            result = (
                self.client.table("v2_sessions")
                .update({
                    "conversation_summary": summary,
                    "conversation_summary_updated_at": (
                        now if summary is not None else None
                    ),
                })
                .eq("id", session_id)
                .execute()
            )
            if result.data and len(result.data) > 0:
                return result.data[0]
            return None
        except Exception as e:
            err_low = str(e).lower()
            if (
                "conversation_summary" in err_low
                or "pgrst204" in err_low
            ):
                logger.warning(
                    "set_session_conversation_summary: column missing "
                    "(migration pending?) sid=%s", session_id,
                )
                return None
            logger.warning(
                "set_session_conversation_summary failed sid=%s err=%s",
                session_id, e,
            )
            return None

    def get_session_conversation_summary(
        self,
        session_id: str,
    ) -> Optional[dict]:
        """Read the current digest + its updated_at without pulling
        the full session row. Returns ``{summary, updated_at}`` or
        None when the session doesn't exist OR the digest hasn't
        been generated yet (cold-start)."""
        try:
            result = (
                self.client.table("v2_sessions")
                .select("conversation_summary, conversation_summary_updated_at")
                .eq("id", session_id)
                .limit(1)
                .execute()
            )
            data = result.data or []
            if not data:
                return None
            row = data[0]
            summary = (row.get("conversation_summary") or "").strip() or None
            if summary is None:
                return None
            return {
                "summary": summary,
                "updated_at": row.get("conversation_summary_updated_at"),
            }
        except Exception as e:
            logger.warning(
                "get_session_conversation_summary failed sid=%s err=%s",
                session_id, e,
            )
            return None

    def set_session_predictions(
        self,
        session_id: str,
        *,
        ai_predicted_session_comment: Optional[str],
        ai_predicted_next_question: Optional[str] = None,
        ai_predicted_next_questions: Optional[list] = None,
    ) -> Optional[dict]:
        """Persist pre-generated AI predictions on the session row.

        Called by services.session_predictions during finalize so
        the admin opens the user-detail page to a pre-filled
        comment + next-question(s) they can accept or edit. Stamps
        ai_predictions_generated_at so the UI can surface "this is
        N hours old, regenerate?" when metrics drift.

        ``ai_predicted_next_questions`` is the NEW 5-position
        ordered script — list of {position, text, intent_tag}.
        ``ai_predicted_next_question`` is kept for back-compat
        with the old single-question admin UI; if the array is
        provided but the single field isn't, we derive the single
        field from position-1 so legacy callers keep working.

        Gracefully degrades if the new JSONB column doesn't exist
        yet (migration pending) — retries the update without it
        and logs a warning, so existing admin tooling still saves
        the comment + single question.
        """
        try:
            now = datetime.now(timezone.utc).isoformat()
            # Derive single-question back-compat value when only
            # the array was passed.
            single_q = ai_predicted_next_question
            if single_q is None and ai_predicted_next_questions:
                try:
                    first = ai_predicted_next_questions[0]
                    if isinstance(first, dict):
                        single_q = (first.get("text") or "").strip() or None
                except (IndexError, AttributeError, TypeError):
                    single_q = None

            patch: dict = {
                "ai_predicted_session_comment": ai_predicted_session_comment,
                "ai_predicted_next_question": single_q,
                "ai_predictions_generated_at": now,
            }
            if ai_predicted_next_questions is not None:
                patch["ai_predicted_next_questions"] = ai_predicted_next_questions

            result = (
                self.client.table("v2_sessions")
                .update(patch)
                .eq("id", session_id)
                .execute()
            )
            if result.data and len(result.data) > 0:
                return result.data[0]
            return None
        except Exception as e:
            err_low = str(e).lower()
            if (
                "ai_predicted_next_questions" in err_low
                or "pgrst204" in err_low
            ):
                # New JSONB column missing in this environment —
                # retry without it so the comment + single-question
                # back-compat path still saves.
                logger.warning(
                    "set_session_predictions: array column missing "
                    "(migration pending?), retrying without — sid=%s",
                    session_id,
                )
                try:
                    fallback = {
                        "ai_predicted_session_comment": ai_predicted_session_comment,
                        "ai_predicted_next_question": single_q,
                        "ai_predictions_generated_at": now,
                    }
                    result = (
                        self.client.table("v2_sessions")
                        .update(fallback)
                        .eq("id", session_id)
                        .execute()
                    )
                    if result.data and len(result.data) > 0:
                        return result.data[0]
                    return None
                except Exception as e2:
                    logger.warning(
                        "set_session_predictions fallback failed sid=%s err=%s",
                        session_id, e2,
                    )
                    return None
            logger.warning(
                "set_session_predictions failed sid=%s err=%s",
                session_id, e,
            )
            return None

    def set_session_final_next_questions(
        self,
        session_id: str,
        questions: Optional[list],
    ) -> Optional[dict]:
        """Save the admin-edited 5-question script on Publish.

        ``questions`` is a list of {position, text, intent_tag?}
        dicts (length ≤ 5) or None to clear. Idempotent — same
        list saved twice is a no-op. Failure logs + returns None
        so the publish itself isn't blocked.
        """
        try:
            now = datetime.now(timezone.utc).isoformat()
            result = (
                self.client.table("v2_sessions")
                .update({
                    "final_human_next_questions": questions,
                    "updated_at": now,
                })
                .eq("id", session_id)
                .execute()
            )
            if result.data and len(result.data) > 0:
                return result.data[0]
            return None
        except Exception as e:
            err_low = str(e).lower()
            if (
                "final_human_next_questions" in err_low
                or "pgrst204" in err_low
            ):
                logger.warning(
                    "set_session_final_next_questions: column missing "
                    "(migration pending?) sid=%s",
                    session_id,
                )
                return None
            logger.warning(
                "set_session_final_next_questions failed sid=%s err=%s",
                session_id, e,
            )
            return None

    def get_session_predictions(self, session_id: str) -> Optional[dict]:
        """Read the (predicted_comment, predicted_question,
        generated_at) trio without pulling the full session row.

        Returns ``None`` when the session doesn't exist or has
        never had predictions generated. The publish handler uses
        this to recover the AI prediction it needs to log
        alongside the human's final.
        """
        try:
            result = (
                self.client.table("v2_sessions")
                .select(
                    "id, ai_predicted_session_comment, "
                    "ai_predicted_next_question, "
                    "ai_predictions_generated_at"
                )
                .eq("id", session_id)
                .limit(1)
                .execute()
            )
            data = result.data or []
            return data[0] if data else None
        except Exception as e:
            logger.warning(
                "get_session_predictions failed sid=%s err=%s",
                session_id, e,
            )
            return None

    def update_session_global_metrics(
        self,
        session_id: str,
        global_wpm: float | None,
        global_fillers: int | None,
        global_pause_ms: float | None,
        global_dynamic_db: float | None,
        global_pitch_center: float | None,
        global_energy: float | None,
        kpi_score: float | None = None,
    ) -> Optional[dict]:
        """Update v2_sessions with aggregated global acoustic metrics + KPI."""
        try:
            payload = {
                "global_wpm": global_wpm,
                "global_fillers": global_fillers,
                "global_pause_ms": global_pause_ms,
                "global_dynamic_db": global_dynamic_db,
                "global_pitch_center": global_pitch_center,
                "global_energy": global_energy,
            }
            if kpi_score is not None:
                payload["kpi_score"] = kpi_score
            result = (
                self.client.table("v2_sessions")
                .update(payload)
                .eq("id", session_id)
                .execute()
            )
            if result.data and len(result.data) > 0:
                return result.data[0]
            return None
        except Exception as e:
            logger.error(f"update_session_global_metrics failed: {e}")
            return None

    def update_session_ai_alignment(
        self,
        session_id: str,
        score: float | None,
        comment: str | None,
    ) -> Optional[dict]:
        """Store the LLM's alignment score + comment for a session."""
        try:
            result = (
                self.client.table("v2_sessions")
                .update({
                    "ai_task_alignment_score": score,
                    "ai_task_alignment_comment": comment,
                })
                .eq("id", session_id)
                .execute()
            )
            if result.data and len(result.data) > 0:
                return result.data[0]
            return None
        except Exception as e:
            logger.error(f"update_session_ai_alignment failed: {e}")
            return None

    def get_next_session_icebreaker_row(
        self,
        session_id: str,
    ) -> Optional[dict]:
        """Read the six icebreaker columns + session metadata for
        the admin GET endpoint.

        Returns a dict with the raw columns; the route layer derives
        the public 5-state ``queue_status`` enum via
        ``services.next_session_icebreaker.derive_queue_status``.

        Returns None when the row doesn't exist OR when the columns
        are missing (migration pending). Empty-row vs missing-column
        is logged so we can tell them apart in audits.
        """
        if not session_id:
            return None
        try:
            result = (
                self.client.table("v2_sessions")
                .select(
                    "id, user_id, "
                    "next_session_icebreaker_ai_draft, "
                    "next_session_icebreaker_ai_draft_generated_at, "
                    "next_session_icebreaker, "
                    "next_session_icebreaker_edited_at, "
                    "next_session_icebreaker_status, "
                    "next_session_icebreaker_generation_error"
                )
                .eq("id", session_id)
                .limit(1)
                .execute()
            )
            if not result.data:
                return None
            return result.data[0]
        except Exception as e:
            err_low = str(e).lower()
            if (
                "next_session_icebreaker" in err_low
                or "pgrst204" in err_low
            ):
                logger.warning(
                    "get_next_session_icebreaker_row: columns missing "
                    "(run migrations/add_next_session_icebreaker_"
                    "columns.sql) sid=%s",
                    session_id,
                )
                return None
            logger.warning(
                "get_next_session_icebreaker_row failed sid=%s err=%s",
                session_id, e,
            )
            return None

    def set_next_session_icebreaker_ai_draft(
        self,
        session_id: str,
        *,
        ai_draft: str,
        generated_at: str,
        reset_editable: bool,
    ) -> bool:
        """Persist the immutable AI baseline of the icebreaker.

        Called from services.next_session_icebreaker.generate_next_
        session_icebreaker — the only writer of the ai_draft column.

        Writes:
          - next_session_icebreaker_ai_draft = ai_draft
          - next_session_icebreaker_ai_draft_generated_at = generated_at
          - next_session_icebreaker_generation_error = NULL (success
            clears any prior failure tag)

        When ``reset_editable=True`` (default for first generation
        AND regenerate), ALSO writes:
          - next_session_icebreaker = ai_draft (current starts
            equal to draft)
          - next_session_icebreaker_edited_at = NULL
          - next_session_icebreaker_status = 'pending'

        ``reset_editable=False`` would preserve admin edits across a
        re-generation — we don't expose that today (regenerate is
        destructive by FE-approved design) but the kwarg leaves the
        door open.

        Returns True on success. Logs + returns False on:
          - missing column (migration pending)
          - generic DB failure
        """
        if not session_id or not ai_draft:
            return False
        payload: dict[str, Any] = {
            "next_session_icebreaker_ai_draft": ai_draft,
            "next_session_icebreaker_ai_draft_generated_at": generated_at,
            "next_session_icebreaker_generation_error": None,
        }
        if reset_editable:
            payload.update({
                "next_session_icebreaker": ai_draft,
                "next_session_icebreaker_edited_at": None,
                "next_session_icebreaker_status": "pending",
            })
        try:
            (
                self.client.table("v2_sessions")
                .update(payload)
                .eq("id", session_id)
                .execute()
            )
            return True
        except Exception as e:
            err_low = str(e).lower()
            if (
                "next_session_icebreaker" in err_low
                or "pgrst204" in err_low
            ):
                logger.warning(
                    "set_next_session_icebreaker_ai_draft: column "
                    "missing (run migrations/add_next_session_"
                    "icebreaker_columns.sql) sid=%s",
                    session_id,
                )
                return False
            logger.error(
                "set_next_session_icebreaker_ai_draft failed sid=%s: %s",
                session_id, e,
            )
            return False

    def update_next_session_icebreaker_editable(
        self,
        session_id: str,
        *,
        current: Optional[str],
        edited_at: str,
        status: str,
    ) -> bool:
        """Admin-edit write path for the icebreaker.

        Updates ONLY the editable columns:
          - next_session_icebreaker = current
          - next_session_icebreaker_edited_at = edited_at
          - next_session_icebreaker_status = status

        The immutable ai_draft column is intentionally NOT touched —
        admin edits leave the LLM baseline pinned for diff tracking.

        ``current=None`` + ``status='skipped'`` is the "admin cleared"
        case: n+1 will fall through to the default first-question
        path.

        Caller is responsible for the status enum value matching the
        CHECK constraint ('pending', 'skipped', 'delivered'). Routes
        pass 'pending' or 'skipped' only; 'delivered' is owned by
        ``mark_next_session_icebreaker_delivered``.
        """
        if not session_id:
            return False
        try:
            (
                self.client.table("v2_sessions")
                .update({
                    "next_session_icebreaker": current,
                    "next_session_icebreaker_edited_at": edited_at,
                    "next_session_icebreaker_status": status,
                })
                .eq("id", session_id)
                .execute()
            )
            return True
        except Exception as e:
            logger.error(
                "update_next_session_icebreaker_editable failed "
                "sid=%s: %s", session_id, e,
            )
            return False

    def set_next_session_icebreaker_generation_error(
        self,
        session_id: str,
        error_tag: str,
    ) -> bool:
        """Tag a failed generation attempt.

        Writes next_session_icebreaker_generation_error = error_tag
        and leaves ai_draft NULL. FE consumes the tag to render the
        "Generation failed — Regenerate" red banner state.

        Common tags (no DB-level enum; informational):
          'transcript_too_short' | 'llm_unavailable' | 'llm_empty'
        """
        if not session_id:
            return False
        try:
            (
                self.client.table("v2_sessions")
                .update({
                    "next_session_icebreaker_generation_error": error_tag,
                })
                .eq("id", session_id)
                .execute()
            )
            return True
        except Exception as e:
            err_low = str(e).lower()
            if (
                "next_session_icebreaker" in err_low
                or "pgrst204" in err_low
            ):
                # Migration pending; nothing to log loudly.
                return False
            logger.warning(
                "set_next_session_icebreaker_generation_error "
                "failed sid=%s: %s", session_id, e,
            )
            return False

    def clear_next_session_icebreaker_generation_error(
        self,
        session_id: str,
    ) -> bool:
        """Clear the error tag before a fresh generation attempt.

        Called from generate_next_session_icebreaker(overwrite=True)
        so the FE sees the new attempt's outcome rather than a stale
        failure tag bleeding through.
        """
        if not session_id:
            return False
        try:
            (
                self.client.table("v2_sessions")
                .update({
                    "next_session_icebreaker_generation_error": None,
                })
                .eq("id", session_id)
                .execute()
            )
            return True
        except Exception:
            return False  # best-effort; not load-bearing

    def get_next_session_id_for(
        self,
        user_id: str,
        after_session_id: str,
    ) -> Optional[str]:
        """For the GET endpoint's queue_status derivation: does the
        user have a session that was created AFTER ``after_session_id``?
        If so, return its id; the FE renders the card as 'queued'.

        Returns None when:
          - no later session exists
          - the after_session row isn't found (can't compare created_at)
          - DB hiccup

        Light query — single index seek on (user_id, created_at).
        """
        if not user_id or not after_session_id:
            return None
        try:
            # First fetch after_session's created_at — we don't have
            # it in the GET row payload context and don't want to
            # require the caller to thread it through.
            anchor = (
                self.client.table("v2_sessions")
                .select("created_at")
                .eq("id", after_session_id)
                .limit(1)
                .execute()
            )
            if not anchor.data:
                return None
            anchor_ts = anchor.data[0].get("created_at")
            if not anchor_ts:
                return None
            later = (
                self.client.table("v2_sessions")
                .select("id")
                .eq("user_id", user_id)
                .gt("created_at", anchor_ts)
                .order("created_at", desc=False)
                .limit(1)
                .execute()
            )
            rows = later.data or []
            if not rows:
                return None
            return rows[0].get("id")
        except Exception as e:
            logger.warning(
                "get_next_session_id_for failed user=%s sid=%s err=%s",
                user_id, after_session_id, e,
            )
            return None

    def set_session_user_id(self, session_id: str, user_id: str) -> bool:
        """Attribute a session to a user (Prompt D — authed lab takes are owned
        at record time so the explore arc + best-presentation work without
        waiting for the guest→signed claim flow). Best-effort; non-fatal."""
        if not session_id or not user_id:
            return False
        try:
            self.client.table("v2_sessions").update(
                {"user_id": user_id}
            ).eq("id", session_id).execute()
            return True
        except Exception as e:
            logger.warning("set_session_user_id failed sid=%s: %s", session_id, e)
            return False

    def set_session_arc(
        self, session_id: str, arc_id: Optional[str], take_index: Optional[int],
    ) -> bool:
        """Link a session into an explore-session arc (Prompt A §3). Best-effort;
        missing column (migration pending) → False, non-fatal."""
        if not session_id or not arc_id:
            return False
        try:
            self.client.table("v2_sessions").update({
                "arc_id": arc_id, "take_index": take_index,
            }).eq("id", session_id).execute()
            return True
        except Exception as e:
            if "arc_id" in str(e).lower() or "take_index" in str(e).lower():
                logger.warning(
                    "set_session_arc: column missing (run "
                    "migrations/add_explore_arc.sql)",
                )
                return False
            logger.warning("set_session_arc failed sid=%s: %s", session_id, e)
            return False

    def set_session_recording_kind(
        self, session_id: str, kind: str,
        paired_session_id: Optional[str] = None,
    ) -> bool:
        """Tag a session as the SPOKEN take or its READ variant (founder
        2026-07-14). ``paired_session_id`` links a read back to the spoken
        take it corrects. Best-effort: missing column (migration pending) →
        False, non-fatal (the recording still processes; it just reads as
        'spoken' by default downstream)."""
        if not session_id or kind not in ("spoken", "read"):
            return False
        payload: dict = {"recording_kind": kind}
        if paired_session_id:
            payload["paired_session_id"] = str(paired_session_id)
        try:
            self.client.table("v2_sessions").update(payload).eq(
                "id", session_id).execute()
            return True
        except Exception as e:
            _e = str(e).lower()
            if "recording_kind" in _e or "paired_session_id" in _e:
                logger.warning(
                    "set_session_recording_kind: column missing (run "
                    "migrations/add_recording_kind.sql) sid=%s", session_id,
                )
                return False
            logger.warning("set_session_recording_kind failed sid=%s: %s",
                           session_id, e)
            return False

    def set_session_analysis_state(
        self, session_id: str, state: str, error: Optional[str] = None,
    ) -> bool:
        """Flip the async-analysis job state on the session row
        (processing | ready | failed | failed_ideal_text_unconfirmed).
        Best-effort; missing column (migration pending) → False (the sync path
        never reads it)."""
        if not session_id or state not in (
            "processing",
            "ready",
            "failed",
            "failed_ideal_text_unconfirmed",
        ):
            return False
        payload: dict = {"analysis_state": state}
        if state in ("failed", "failed_ideal_text_unconfirmed"):
            payload["analysis_error"] = (str(error) if error else "unknown")[:500]
        try:
            self.client.table("v2_sessions").update(payload).eq(
                "id", session_id).execute()
        except Exception as e:
            if "analysis_state" in str(e).lower():
                logger.warning(
                    "set_session_analysis_state: column missing (run "
                    "migrations/add_analysis_state.sql) sid=%s", session_id,
                )
                return False
            logger.warning("set_session_analysis_state failed sid=%s: %s",
                           session_id, e)
            return False
        # Push half (docs/BE-HANDOFF-analysis-state-push.md): announce the
        # flip AFTER the write lands, never before — the FE's poll fallback
        # must always agree with what push said. Guarded here too so a broken
        # notifier can never turn a landed write into a reported failure.
        try:
            from services.realtime_notify import broadcast_analysis_state
            broadcast_analysis_state(str(session_id), state)
        except Exception:
            logger.debug(
                "analysis-state broadcast wrapper failed sid=%s", session_id)
        return True

    def set_session_feedback_saved(self, session_id: str) -> bool:
        """Stamp the per-take coach 'Save' checkpoint (nothing delivered —
        the publish requires all 3 takes saved). Best-effort."""
        if not session_id:
            return False
        try:
            self.client.table("v2_sessions").update({
                "coach_feedback_saved_at":
                    datetime.now(timezone.utc).isoformat(),
            }).eq("id", session_id).execute()
            return True
        except Exception as e:
            if "coach_feedback_saved_at" in str(e).lower():
                logger.warning(
                    "set_session_feedback_saved: column missing (run "
                    "migrations/add_coach_feedback_saved.sql) sid=%s",
                    session_id,
                )
                return False
            logger.warning("set_session_feedback_saved failed sid=%s: %s",
                           session_id, e)
            return False

    def count_arc_sessions(
        self, arc_id: Optional[str], exclude_session_id: Optional[str] = None,
    ) -> Optional[int]:
        """STRICT arc-session count for take numbering: returns None on ANY
        error (so the caller can fail CLOSED and keep the FE-sent index instead
        of mislabeling a real take-2/3 as take-1), and can EXCLUDE the current
        session (an upload retry already arc-linked must not double-count
        itself).

        Counts SPOKEN takes only (founder 2026-07-14): a read is a paired
        variant of its take (paired_session_id set), not a take of its own —
        so `paired_session_id IS NULL` isolates the real takes. Falls back to
        the unfiltered count when the column is not migrated."""
        if not arc_id:
            return None

        def _q(with_paired_filter):
            q = (
                self.client.table("v2_sessions")
                .select("id", count="exact")
                .eq("arc_id", arc_id)
            )
            if with_paired_filter:
                q = q.is_("paired_session_id", "null")
            if exclude_session_id:
                q = q.neq("id", str(exclude_session_id))
            return q.limit(1).execute()

        try:
            res = _q(True)
            cnt = getattr(res, "count", None)
            return int(cnt) if cnt is not None else 0
        except Exception as e:
            if "paired_session_id" in str(e).lower():
                try:  # pre-migration → count all arc sessions
                    res = _q(False)
                    cnt = getattr(res, "count", None)
                    return int(cnt) if cnt is not None else 0
                except Exception:
                    return None
            logger.warning("count_arc_sessions failed arc=%s: %s", arc_id, e)
            return None

    def get_arc_take_count(self, arc_id: Optional[str]) -> int:
        """How many takes are in an arc (Prompt A §3 take_count). 0 on missing
        column / no arc."""
        if not arc_id:
            return 0
        try:
            res = (
                self.client.table("v2_sessions")
                .select("id", count="exact")
                .eq("arc_id", arc_id)
                .limit(1)
                .execute()
            )
            return int(getattr(res, "count", None) or 0)
        except Exception as e:
            if "arc_id" in str(e).lower():
                return 0
            logger.warning("get_arc_take_count failed arc=%s: %s", arc_id, e)
            return 0

    def get_read_sessions_for(self, spoken_session_id) -> list[dict]:
        """The paired mid-take RE-READ sessions of a spoken take
        (recording_kind='read', paired_session_id=<take>), oldest first —
        the fold order the coach packet appends them in (founder 2026-07-16:
        "re-reads are part of the take, never separate items"). Uses
        idx_v2_sessions_paired. Best-effort: [] pre-migration / on hiccup
        (the packet degrades to the parent take alone)."""
        if not spoken_session_id:
            return []
        try:
            res = (
                self.client.table("v2_sessions")
                .select("id, user_id, arc_id, take_index, status, "
                        "created_at, results_published_at, "
                        "recording_kind, paired_session_id, intake_context")
                .eq("paired_session_id", str(spoken_session_id))
                .order("created_at", desc=False)
                .execute()
            )
            return res.data or []
        except Exception as e:
            err_low = str(e).lower()
            if "paired_session_id" in err_low:
                return []  # pre-migration — no read rows can exist either
            logger.warning(
                "get_read_sessions_for failed sid=%s err=%s",
                spoken_session_id, e,
            )
            return []

    def get_arc_sessions(self, arc_id: Optional[str]) -> list[dict]:
        """The takes of an explore arc, ORDERED by take_index (Prompt A §3/§5).
        Powers cross-take selection + the delivery layer (spoken/read split,
        per-take Save state). Best-effort: [] on missing column / no arc /
        DB hiccup; the delivery-layer columns degrade to absent pre-migration
        (older rows read as spoken/unsaved)."""
        if not arc_id:
            return []
        _full_cols = ("id, user_id, owner_principal_id, project_id, arc_id, "
                      "take_index, status, "
                      "created_at, intake_context, results_published_at, "
                      "recording_kind, paired_session_id, "
                      "coach_feedback_saved_at, analysis_state")
        try:
            try:
                res = (
                    self.client.table("v2_sessions")
                    .select(_full_cols)
                    .eq("arc_id", arc_id)
                    .order("take_index", desc=False)
                    .execute()
                )
                return res.data or []
            except Exception as _e_full:
                _low = str(_e_full).lower()
                # Delivery-layer columns not migrated yet → the legacy list.
                # analysis_state joined the select 2026-07-22 (the re-read
                # completion gate); it degrades the same way.
                if not any(c in _low for c in (
                        "recording_kind", "paired_session_id",
                        "coach_feedback_saved_at", "analysis_state")):
                    raise
            res = (
                self.client.table("v2_sessions")
                .select("id, user_id, owner_principal_id, project_id, arc_id, "
                        "take_index, status, "
                        "created_at, intake_context, results_published_at")
                .eq("arc_id", arc_id)
                .order("take_index", desc=False)
                .execute()
            )
            return res.data or []
        except Exception as e:
            _e = str(e).lower()
            # results_published_at is a base column, but be defensive: if the
            # explicit select trips any missing column, retry without the
            # optional one (keeps coach_reviewed/cache-signature best-effort).
            if "results_published_at" in _e:
                try:
                    res = (
                        self.client.table("v2_sessions")
                        .select("id, user_id, owner_principal_id, project_id, "
                                "arc_id, take_index, status, "
                                "created_at, intake_context")
                        .eq("arc_id", arc_id)
                        .order("take_index", desc=False)
                        .execute()
                    )
                    return res.data or []
                except Exception:
                    return []
            if "arc_id" in _e or "take_index" in _e:
                logger.warning(
                    "get_arc_sessions: column missing (run "
                    "migrations/add_explore_arc.sql) arc=%s", arc_id,
                )
                return []
            logger.warning("get_arc_sessions failed arc=%s: %s", arc_id, e)
            return []

    def list_user_arc_sessions(self, user_id: Optional[str]) -> list[dict]:
        """Every arc-linked session the user owns — the /user/trainings source
        (the route groups per arc). Arc-keyed on purpose, so DECKLESS trainings
        appear too (the deck-hash grouping in /user/strengths drops them into
        the flat general bucket). Best-effort: [] on missing column / hiccup."""
        if not user_id:
            return []
        _legacy_cols = ("id, arc_id, take_index, status, created_at, "
                        "intake_context, results_published_at")
        _full_cols = _legacy_cols + ", recording_kind, paired_session_id"
        try:
            try:
                res = (
                    self.client.table("v2_sessions")
                    .select(_full_cols)
                    .eq("user_id", str(user_id))
                    .not_.is_("arc_id", "null")
                    .order("created_at", desc=False)
                    .execute()
                )
                return res.data or []
            except Exception as _ef:
                _lowf = str(_ef).lower()
                if not ("recording_kind" in _lowf
                        or "paired_session_id" in _lowf):
                    raise
            res = (
                self.client.table("v2_sessions")
                .select(_legacy_cols)
                .eq("user_id", str(user_id))
                .not_.is_("arc_id", "null")
                .order("created_at", desc=False)
                .execute()
            )
            return res.data or []
        except Exception as e:
            _e = str(e).lower()
            if "arc_id" in _e or "take_index" in _e:
                logger.warning(
                    "list_user_arc_sessions: column missing (run "
                    "migrations/add_explore_arc.sql) user=%s", user_id,
                )
                return []
            logger.warning("list_user_arc_sessions failed user=%s: %s",
                           user_id, e)
            return []

    def set_session_presentation_duration(
        self, session_id: Optional[str], seconds: Optional[int],
    ) -> bool:
        """Persist the gate's measured duration onto the session (A5 — the
        length→audits read). Best-effort: no-op (False) on missing column /
        bad value / error; the recording row keeps the authoritative copy."""
        if not session_id or seconds is None:
            return False
        try:
            secs = int(round(float(seconds)))
        except (TypeError, ValueError):
            return False
        try:
            self.client.table("v2_sessions").update(
                {"presentation_duration_seconds": secs}
            ).eq("id", session_id).execute()
            return True
        except Exception as e:
            err_low = str(e).lower()
            if "presentation_duration_seconds" in err_low and (
                "does not exist" in err_low or "pgrst" in err_low
            ):
                logger.warning(
                    "set_session_presentation_duration: column missing (run "
                    "migrations/add_session_duration.sql) sid=%s", session_id,
                )
                return False
            logger.warning(
                "set_session_presentation_duration failed sid=%s: %s",
                session_id, e,
            )
            return False

    def find_training_import_by_key(self, key: str) -> Optional[dict]:
        """The SUCCESSFUL import already created under this idempotency key,
        or None.

        The retry-safety half of the timeout problem (FE 2026-07-28): the
        proxy can time out on a request whose BE work then SUCCEEDS, so a
        re-send must return the ORIGINAL import rather than mint a second —
        a talk imported twice is labelled twice and trained on twice, and
        nothing on screen would say so.

        A FAILED import releases its key (FE §7, 2026-07-29). Deduping a
        retry-after-failure would make the key a permanent lock: a
        NO_CANDIDATES import is a tuning problem on MY side, the coach
        changes nothing about the file, and once I retune they could never
        get a fresh run — the key would keep handing back the failure. The
        duplicate worth preventing is the retry after a SUCCESS the coach
        could not see; a retry after a visible failure is exactly the retry
        that should be allowed through.

        Best-effort; None on any error (the caller then proceeds, which risks
        the duplicate but never blocks a legitimate first import)."""
        if not key:
            return None
        try:
            rows = (
                self.client.table("v2_sessions")
                .select("id, arc_id, intake_context, analysis_state")
                .eq("source", "training_import")
                .eq("intake_context->>import_key", str(key))
                .order("created_at", desc=True)
                .limit(5)
                .execute()
                .data
            ) or []
            for r in rows:
                if (r.get("analysis_state") or "ready") != "failed":
                    return r
            return None
        except Exception as e:
            logger.warning("find_training_import_by_key failed: %s", e)
            return None

    def list_training_import_sessions(self, *, user_id: Optional[str] = None,
                                      limit: int = 200) -> list[dict]:
        """The imported training takes, newest first (founder 2026-07-28).

        Deliberately NOT v2_list_user_lab_sessions with a different filter:
        that method is the per-speaker BASELINE reader, and imports must stay
        out of it (a corpus of many voices would corrupt one speaker's norm —
        see services/training_import.py). This is the coach's separate
        window onto the corpus. Best-effort: [] on anything missing.

        analysis_state comes from an older migration, so the select degrades
        rather than betting the whole list on it: a DB without that column
        would otherwise return an EMPTY corpus index, which reads exactly
        like "nothing imported" — the failure this list exists to rule out."""
        _cols_full = ("id, arc_id, take_index, intake_context, created_at, "
                      "status, user_id, recording_1_id, analysis_state")
        _cols_base = ("id, arc_id, take_index, intake_context, created_at, "
                      "status, user_id, recording_1_id")
        for _cols in (_cols_full, _cols_base):
            try:
                q = (
                    self.client.table("v2_sessions")
                    .select(_cols)
                    .eq("source", "training_import")
                )
                if user_id:
                    q = q.eq("user_id", str(user_id))
                return (q.order("created_at", desc=True)
                         .limit(int(limit)).execute().data) or []
            except Exception as e:
                if _cols is _cols_base:
                    logger.warning(
                        "list_training_import_sessions failed: %s", e)
                    return []
                logger.warning(
                    "list_training_import_sessions: analysis_state missing "
                    "(run migrations/add_analysis_state.sql) — retrying "
                    "without it: %s", e)
        return []

    def set_session_source(self, session_id: str, source: str) -> bool:
        """Stamp v2_sessions.source (foundation discriminator). The Lab
        handler marks its sessions 'audit_upload' so the history list +
        future audit features can find willab Lab sessions. Best-effort;
        missing column (migration pending) → False, non-fatal."""
        if not session_id:
            return False
        try:
            (
                self.client.table("v2_sessions")
                .update({"source": source})
                .eq("id", session_id)
                .execute()
            )
            return True
        except Exception as e:
            err_low = str(e).lower()
            # An enum CHECK rejection is a DEPLOYMENT error, not a data one,
            # and it cost a day of silent orphaned imports: 'training_import'
            # was not in v2_sessions_source_check, every UPDATE 23514'd, and
            # this method's quiet False was mistaken for "nothing to do".
            # Name the fix in the log rather than making the next person
            # reverse-engineer a missing row.
            if "23514" in err_low or "check constraint" in err_low:
                logger.error(
                    "set_session_source: '%s' is not an allowed source value "
                    "— the v2_sessions_source_check CHECK rejected it (run "
                    "migrations/add_training_import_source.sql if this is a "
                    "training import) sid=%s", source, session_id,
                )
                return False
            if "source" in err_low and "pgrst" in err_low:
                return False
            logger.warning(
                "set_session_source failed sid=%s err=%s", session_id, e,
            )
            return False

    def list_user_lab_sessions(
        self,
        user_id: str,
        *,
        limit: int = 50,
    ) -> list[dict]:
        """List a user's willab Lab sessions, newest first, for the
        history / scroll-back view. Filters source='audit_upload' so
        old-funnel/homework sessions don't appear. Returns lightweight
        rows; the FE fetches the full readout per session on tap.
        """
        if not user_id:
            return []
        try:
            res = (
                self.client.table("v2_sessions")
                .select(
                    "id, created_at, status, results_published_at, "
                    "intake_context"
                )
                .eq("user_id", user_id)
                .eq("source", "audit_upload")
                .order("created_at", desc=True)
                .limit(limit)
                .execute()
            )
            return res.data or []
        except Exception as e:
            err_low = str(e).lower()
            if "source" in err_low and "pgrst" in err_low:
                logger.warning(
                    "list_user_lab_sessions: source column missing (run "
                    "migrations/add_foundation_discriminators.sql) user=%s",
                    user_id,
                )
                return []
            logger.warning(
                "list_user_lab_sessions failed user=%s err=%s", user_id, e,
            )
            return []

    def set_session_coach_overall_message(
        self,
        session_id: str,
        message: Optional[str],
    ) -> bool:
        """Persist the optional take-level coach summary.

        Exact-evidence paragraph feedback lives in ``coach_snippet_drafts``
        through ``FeedbackRepository``.  This scalar is intentionally
        separate so it cannot become a second feedback-item schema.
        """
        if not session_id:
            return False
        try:
            (
                self.client.table("v2_sessions")
                .update({"coach_overall_message": message})
                .eq("id", session_id)
                .execute()
            )
            return True
        except Exception as e:
            err_low = str(e).lower()
            if "coach_overall_message" in err_low or "pgrst204" in err_low:
                logger.warning(
                    "set_session_coach_overall_message: column missing (run "
                    "migrations/add_canonical_project_ownership.sql) "
                    "sid=%s", session_id,
                )
                return False
            logger.error(
                "set_session_coach_overall_message failed sid=%s err=%s",
                session_id, e,
            )
            return False

    def set_session_coach_video_ref(
        self,
        session_id: str,
        video_ref: Optional[str],
    ) -> bool:
        """Persist the coach feedback video URL on the session (B.3).

        The canonical readout exposes it in the separate take-level
        ``coach_review`` object. Missing column → False.
        """
        if not session_id:
            return False
        try:
            (
                self.client.table("v2_sessions")
                .update({"coach_video_ref": video_ref})
                .eq("id", session_id)
                .execute()
            )
            return True
        except Exception as e:
            err_low = str(e).lower()
            if "coach_video_ref" in err_low or "pgrst204" in err_low:
                logger.warning(
                    "set_session_coach_video_ref: column missing (run "
                    "migrations/add_coach_video_ref_to_v2_sessions.sql) sid=%s",
                    session_id,
                )
                return False
            logger.error(
                "set_session_coach_video_ref failed sid=%s err=%s",
                session_id, e,
            )
            return False

    def set_session_boundary_metrics(
        self,
        session_id: str,
        metrics: Optional[dict],
    ) -> bool:
        """Persist the F1 word→slide boundary measurement for a take
        (services.slide_boundary_metrics). INTERNAL/coach-side — exposure and
        impact of the pause-snap compensation, never surfaced to a user (AC-9).

        Best-effort: missing column (migration pending) → False, and the
        recording is unaffected. A measurement never blocks the live loop."""
        if not session_id:
            return False
        try:
            (
                self.client.table("v2_sessions")
                .update({"boundary_metrics": metrics})
                .eq("id", session_id)
                .execute()
            )
            return True
        except Exception as e:
            err_low = str(e).lower()
            if "boundary_metrics" in err_low or "pgrst204" in err_low:
                logger.warning(
                    "set_session_boundary_metrics: column missing "
                    "(run migrations/add_boundary_metrics.sql)")
            else:
                logger.warning(
                    "set_session_boundary_metrics failed sid=%s: %s",
                    session_id, e)
            return False

    def set_session_slide_transcripts(
        self,
        session_id: str,
        slide_transcripts: Optional[list],
    ) -> bool:
        """Persist the COMPLETE per-slide 1:1 transcript on the session (#A —
        bucketed from the whole-recording word list by the slide-click timeline).
        The take viewer reads this directly (complete + fast). Best-effort:
        missing column (migration pending) → False, recording unaffected."""
        if not session_id:
            return False
        try:
            (
                self.client.table("v2_sessions")
                .update({"slide_transcripts": slide_transcripts})
                .eq("id", session_id)
                .execute()
            )
            return True
        except Exception as e:
            err_low = str(e).lower()
            if "slide_transcripts" in err_low or "pgrst204" in err_low:
                logger.warning(
                    "set_session_slide_transcripts: column missing (run "
                    "migrations/add_slide_transcripts.sql) sid=%s", session_id,
                )
                return False
            logger.error(
                "set_session_slide_transcripts failed sid=%s err=%s",
                session_id, e,
            )
            return False

    def get_session_slide_transcripts(self, session_id: str) -> Optional[list]:
        """Read the persisted COMPLETE per-slide 1:1 transcript for a session
        (#A). Returns the list [{index, transcript, start_offset_ms,
        duration_ms}] or None when absent / missing column / error — the readout
        then falls back to its per-snippet rendering."""
        if not session_id:
            return None
        try:
            res = (
                self.client.table("v2_sessions")
                .select("slide_transcripts")
                .eq("id", session_id)
                .limit(1)
                .execute()
            )
            row = (res.data or [None])[0]
            st = row.get("slide_transcripts") if isinstance(row, dict) else None
            return st if isinstance(st, list) else None
        except Exception as e:
            err_low = str(e).lower()
            if "slide_transcripts" in err_low or "pgrst" in err_low:
                return None
            logger.warning("get_session_slide_transcripts failed sid=%s: %s",
                           session_id, e)
            return None

    def set_session_drift_flag(
        self,
        *,
        session_id: str,
        needs_review: bool,
        diagnostic: Optional[dict],
    ) -> Optional[dict]:
        """Phase 17.1 — persist the Phase 17 drift-guard verdict.

        Writes both columns atomically so admin surfaces never see a
        flag without the explanation, or vice versa. ``diagnostic``
        is the dict returned by detect_classifier_drift.

        Idempotent — when drift resolves on a re-run (admin re-
        extracted a snippet with better metrics, say) pass
        ``needs_review=False`` and the new diagnostic; the row flips
        back. Failure logs + returns None so the metrics compute
        path can keep going.
        """
        try:
            result = (
                self.client.table("v2_sessions")
                .update({
                    "needs_admin_review": bool(needs_review),
                    "drift_diagnostic": diagnostic,
                })
                .eq("id", session_id)
                .execute()
            )
            return result.data[0] if result.data else None
        except Exception as e:
            logger.warning(
                "set_session_drift_flag failed session=%s err=%s",
                session_id, e,
            )
            return None

    def update_session_stickiness(
        self,
        *,
        session_id: str,
        top_topic: Optional[str],
        score: Optional[float],
        distribution: Optional[dict],
    ) -> Optional[dict]:
        """Persist the Phase 11 stickiness-topic metric onto v2_sessions.

        Pass all three values as None to clear (e.g. after a re-extract
        produced no topics). The ``computed_at`` timestamp is always
        written so admins can see "ran but found nothing" vs "never ran".
        """
        try:
            result = (
                self.client.table("v2_sessions")
                .update({
                    "stickiness_top_topic": top_topic,
                    "stickiness_score": score,
                    "stickiness_topic_distribution": distribution,
                    "stickiness_computed_at": (
                        datetime.now(timezone.utc).isoformat()
                    ),
                })
                .eq("id", session_id)
                .execute()
            )
            if result.data and len(result.data) > 0:
                return result.data[0]
            return None
        except Exception as e:
            logger.warning(
                "update_session_stickiness failed session=%s err=%s",
                session_id, e,
            )
            return None

    def get_session_intake_context(
        self,
        session_id: str,
    ) -> Optional[dict]:
        """Read v2_sessions.intake_context JSONB for a session.

        Task 9 — per-session speech-context intake block:
            { topic, audience, target_length_seconds }

        Returns the parsed dict (may contain nulls inside), or None
        when the column is unset / row not found / DB hiccup.
        ``None`` means "use defaults" downstream — same pre-task-9
        behavior. Owner-scope is enforced by the caller (route
        handler), not here.
        """
        if not session_id:
            return None
        try:
            result = (
                self.client.table("v2_sessions")
                .select("intake_context")
                .eq("id", session_id)
                .limit(1)
                .execute()
            )
            if not result.data:
                return None
            ctx = result.data[0].get("intake_context")
            return ctx if isinstance(ctx, dict) else None
        except Exception as e:
            err_low = str(e).lower()
            if "intake_context" in err_low or "pgrst204" in err_low:
                logger.warning(
                    "get_session_intake_context: column missing "
                    "(run migrations/add_intake_context_to_v2_"
                    "sessions.sql) sid=%s", session_id,
                )
                return None
            logger.warning(
                "get_session_intake_context failed sid=%s err=%s",
                session_id, e,
            )
            return None

    def set_session_intake_context(
        self,
        session_id: str,
        intake_context: Optional[dict],
    ) -> bool:
        """Full-replace write of v2_sessions.intake_context.

        Task 9 — FE owns the draft and PUTs the whole 3-field form
        on submit; partial updates are out of scope. Pass None to
        clear the column back to NULL (rare, but supported so an
        admin tool can wipe stale intake data without a SQL hop).

        Returns True on success, False on any failure path
        (caller maps to 500). Best-effort logging matches the
        rest of the v2_sessions helpers.
        """
        if not session_id:
            return False
        try:
            (
                self.client.table("v2_sessions")
                .update({"intake_context": intake_context})
                .eq("id", session_id)
                .execute()
            )
            return True
        except Exception as e:
            err_low = str(e).lower()
            if "intake_context" in err_low or "pgrst204" in err_low:
                logger.warning(
                    "set_session_intake_context: column missing "
                    "(run migrations/add_intake_context_to_v2_"
                    "sessions.sql) sid=%s", session_id,
                )
                return False
            logger.error(
                "set_session_intake_context failed sid=%s err=%s",
                session_id, e,
            )
            return False

    def list_sessions_for_user_admin(self, user_id: str) -> List[dict]:
        """All v2_sessions rows for ``user_id``, newest first.

        Phase 12 — backs the multi-session admin user view. No limit
        — the admin needs the full longitudinal history. Returns []
        on any error so the endpoint still renders.
        """
        try:
            return (
                self.client.table("v2_sessions")
                .select("*")
                .eq("user_id", user_id)
                .order("created_at", desc=True)
                .execute()
                .data
            ) or []
        except Exception as e:
            logger.warning(
                "list_sessions_for_user_admin failed user=%s err=%s",
                user_id, e,
            )
            return []

    def get_session_with_global_metrics(self, session_id: str) -> Optional[dict]:
        """Get a session row including global metrics and AI alignment."""
        try:
            result = (
                self.client.table("v2_sessions")
                .select("*")
                .eq("id", session_id)
                .limit(1)
                .execute()
            )
            if result.data and len(result.data) > 0:
                return result.data[0]
            return None
        except Exception as e:
            logger.error(f"get_session_with_global_metrics failed: {e}")
            return None
