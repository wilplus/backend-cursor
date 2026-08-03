#!/usr/bin/env python3
"""End-to-end smoke test for the RLHF capture pipeline.

Drives one snippet through:
  1. POST /v2/admin/snippets/<id>/comment   (with acceptance_mode)
  2. POST /v2/admin/sessions/<id>/publish    (with final array)

Then verifies the writes landed in:
  - charisma_snippets.admin_comment_acceptance_mode
  - admin_annotation_events (field_name='admin_comment' or similar)
  - admin_annotations_log   (1 session-level + N per-position rows)

Reports PASS/FAIL per gate so a regression in any of the three
write paths is caught before A1 backfill cron is built (which
depends on the publish-time capture firing).

DESTRUCTIVE — this is a real Publish:
  * results_published_at gets stamped on the session
  * status flips to 'completed'
  * the standard "results ready" email FIRES if SEND_EMAILS=true
  * RLHF rows land in admin_annotations_log
The script defaults to picking your most recent UNPUBLISHED
session so you don't double-publish a live one. Pass --snippet-id
to override. Use --dry-run to print the plan without writing.

Usage:
    export BACKEND_URL=https://flask-backend-production-ab37.up.railway.app
    export ADMIN_JWT=eyJhbGc...   # admin user's Supabase JWT
    export TEST_USER_EMAIL=artur@willonski.com

    python3 scripts/smoke_rlhf_capture.py
    python3 scripts/smoke_rlhf_capture.py --dry-run
    python3 scripts/smoke_rlhf_capture.py --snippet-id <uuid>
    python3 scripts/smoke_rlhf_capture.py --backend-url http://localhost:5000

Auth: --admin-jwt arg or ADMIN_JWT env var (the admin user's
Supabase access_token; grab it from browser dev tools after
logging into the admin UI).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Optional

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── ANSI for terminal output ────────────────────────────────────────


class Color:
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    CYAN = "\033[96m"
    DIM = "\033[2m"
    BOLD = "\033[1m"
    END = "\033[0m"


def _ok(label: str, detail: str = "") -> None:
    suffix = f" — {detail}" if detail else ""
    print(f"  {Color.GREEN}✓ PASS{Color.END}  {label}{Color.DIM}{suffix}{Color.END}")


def _fail(label: str, detail: str = "") -> None:
    suffix = f" — {detail}" if detail else ""
    print(f"  {Color.RED}✗ FAIL{Color.END}  {label}{Color.DIM}{suffix}{Color.END}")


def _info(msg: str) -> None:
    print(f"  {Color.CYAN}ℹ{Color.END}     {msg}")


def _warn(msg: str) -> None:
    print(f"  {Color.YELLOW}!{Color.END}     {msg}")


def _step(n: int, title: str) -> None:
    print(f"\n{Color.BOLD}── Step {n} — {title}{Color.END}")


def _summarize_and_exit(
    fail_count: int,
    pick: dict,
    *,
    additional_note: str = "",
) -> None:
    """Print the final summary block. Used both by the normal end-of-
    run path and by mid-run early-exits when an earlier gate's
    failure makes later gates meaningless."""
    print()
    if fail_count == 0:
        print(
            f"{Color.GREEN}{Color.BOLD}ALL GATES PASSED{Color.END}  "
            f"({Color.GREEN}0 failures{Color.END})"
        )
        return
    print(
        f"{Color.RED}{Color.BOLD}{fail_count} GATE(S) FAILED{Color.END}"
    )
    if additional_note:
        print(f"  {additional_note}")
    print("\n  Inspect manually:")
    print(
        f"  SELECT * FROM charisma_snippets WHERE id = '{pick['snippet_id']}';"
    )
    print(
        f"  SELECT * FROM admin_annotation_events WHERE session_id = "
        f"'{pick['session_id']}' ORDER BY created_at DESC LIMIT 10;"
    )
    print(
        f"  SELECT * FROM admin_annotations_log WHERE session_id = "
        f"'{pick['session_id']}' ORDER BY created_at DESC LIMIT 10;"
    )


# ── Step helpers ────────────────────────────────────────────────────


def _resolve_user_id(db, email: str) -> Optional[str]:
    """Find auth.users.id for the given email via Supabase admin API."""
    try:
        from config import Config
        url = (
            f"{Config.SUPABASE_URL.rstrip('/')}/auth/v1/admin/users"
        )
        headers = {
            "Authorization": f"Bearer {Config.SUPABASE_SERVICE_ROLE_KEY}",
            "apikey": Config.SUPABASE_SERVICE_ROLE_KEY,
        }
        resp = httpx.get(url, headers=headers, params={"email": email}, timeout=10)
        if resp.status_code != 200:
            return None
        data = resp.json()
        users = data.get("users") if isinstance(data, dict) else data
        if not users:
            return None
        return users[0].get("id")
    except Exception as e:
        _warn(f"auth lookup failed: {e}")
        return None


def _pick_test_snippet(db, user_id: str, prefer_unpublished: bool) -> Optional[dict]:
    """Pick a snippet on a session owned by user_id. Preference order:
    unpublished session first (so we don't double-publish a live one),
    then most-recent overall.
    """
    try:
        sessions = (
            db.client.table("v2_sessions")
            .select("id, results_published_at, created_at")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .limit(20)
            .execute()
            .data
        ) or []
    except Exception as e:
        _warn(f"session lookup failed: {e}")
        return None
    if not sessions:
        return None
    # Prefer unpublished
    candidates = sessions if not prefer_unpublished else [
        s for s in sessions if not s.get("results_published_at")
    ] or sessions

    for s in candidates:
        sid = s["id"]
        try:
            snippets = (
                db.client.table("charisma_snippets")
                .select("id, session_id, admin_comment, ai_draft_admin_comment, snippet_type")
                .eq("session_id", sid)
                .limit(1)
                .execute()
                .data
            ) or []
        except Exception:
            continue
        if snippets:
            return {
                "snippet_id": snippets[0]["id"],
                "session_id": sid,
                "session_published_at": s.get("results_published_at"),
                "current_admin_comment": snippets[0].get("admin_comment"),
                "current_ai_draft": snippets[0].get("ai_draft_admin_comment"),
                "snippet_type": snippets[0].get("snippet_type"),
            }
    return None


def _snapshot_counts(db, session_id: str) -> dict:
    """Read row counts in the tables we're about to write to."""
    snapshot: dict = {}
    try:
        snapshot["admin_annotation_events_for_session"] = (
            db.client.table("admin_annotation_events")
            .select("id", count="exact")
            .eq("session_id", session_id)
            .limit(1)
            .execute()
            .count
        )
    except Exception:
        snapshot["admin_annotation_events_for_session"] = None
    try:
        snapshot["admin_annotations_log_for_session"] = (
            db.client.table("admin_annotations_log")
            .select("id", count="exact")
            .eq("session_id", session_id)
            .limit(1)
            .execute()
            .count
        )
    except Exception:
        snapshot["admin_annotations_log_for_session"] = None
    return snapshot


def _post(
    url: str, jwt: str, body: dict, *, label: str,
) -> tuple[Optional[dict], Optional[int]]:
    """One auth'd POST. Returns (json_body, status_code)."""
    headers = {
        "Authorization": f"Bearer {jwt}",
        "Content-Type": "application/json",
    }
    try:
        resp = httpx.post(url, headers=headers, json=body, timeout=30)
    except Exception as e:
        _fail(label, f"transport error: {e}")
        return None, None
    try:
        data = resp.json()
    except Exception:
        data = {"raw": resp.text[:500]}
    return data, resp.status_code


# ── Main test flow ──────────────────────────────────────────────────


def _validate_jwt_shape(jwt: str) -> Optional[str]:
    """Catch the most common JWT footguns before the script hits the
    network. Returns an error string when the token is obviously
    wrong; None when it looks plausible (real validity is checked by
    the server, this is just a "is it even a JWT shape" pass).
    """
    if not jwt:
        return "ADMIN_JWT is empty"
    # Placeholder text from prior docs that people sometimes paste
    # verbatim. If any of these substrings appears, the token isn't
    # real.
    placeholder_markers = (
        "YOUR-USER-UUID-HERE", "paste your REAL", "paste your real",
        "<paste", "placeholder", "—",  # em dash never appears in JWTs
    )
    for marker in placeholder_markers:
        if marker in jwt:
            return (
                f"ADMIN_JWT contains the substring {marker!r} — looks "
                "like the placeholder text from the docs example, not a "
                "real Supabase access_token. Grab one from your browser's "
                "Local Storage (sb-<project>-auth-token → access_token)."
            )
    # JWTs are 3 base64url segments separated by dots.
    parts = jwt.split(".")
    if len(parts) != 3:
        return (
            f"ADMIN_JWT has {len(parts)} dot-separated segments; a JWT "
            "always has exactly 3 (header.payload.signature)."
        )
    # A real Supabase access_token is ~700+ chars; anything under 100
    # chars is almost certainly truncated or wrong.
    if len(jwt) < 100:
        return (
            f"ADMIN_JWT is only {len(jwt)} chars; a Supabase "
            "access_token is typically 700+. Token probably truncated "
            "on copy."
        )
    # Headers must be ASCII. If the token has non-ASCII bytes it
    # can't even be sent.
    try:
        jwt.encode("ascii")
    except UnicodeEncodeError as e:
        return (
            f"ADMIN_JWT contains non-ASCII characters ({e}) — typical "
            "cause is copying the placeholder text from the docs which "
            "includes an em dash. Real JWTs are ASCII-only."
        )
    return None


def run_smoke_test(
    *,
    backend_url: str,
    admin_jwt: str,
    user_email: str,
    snippet_id_override: Optional[str],
    dry_run: bool,
    service_role: bool,
) -> int:
    """Returns exit code: 0 = all gates passed, non-zero = at least one failed."""
    mode_label = (
        "DRY RUN (no writes)" if dry_run
        else "LIVE — service-role (bypasses Flask auth + body parsing)"
        if service_role
        else "LIVE — HTTP (full route path)"
    )
    print(f"{Color.BOLD}RLHF capture smoke test{Color.END}")
    print(f"  backend: {backend_url}")
    print(f"  user:    {user_email}")
    print(f"  mode:    {mode_label}")

    # ── Preflight: catch obviously-bad JWTs before any network call.
    #    Skipped in service-role mode (no JWT needed there).
    if not dry_run and not service_role:
        jwt_error = _validate_jwt_shape(admin_jwt)
        if jwt_error:
            print(f"\n{Color.RED}{Color.BOLD}JWT REJECTED — {jwt_error}{Color.END}")
            print(
                "\n  Get a real one: open the admin UI in your browser → "
                "log in → DevTools → Application → Local Storage → "
                "key 'sb-<project>-auth-token' → copy the access_token "
                "value (it's nested JSON, the long string under that key)."
            )
            print(
                f"\n  OR re-run with {Color.CYAN}--service-role{Color.END} "
                "to skip the route layer and write via db helpers directly."
            )
            return 2

    fail_count = 0

    # ── Setup
    from services.db import db
    _step(0, "Resolve user + snippet")
    user_id = _resolve_user_id(db, user_email)
    if not user_id:
        _fail("user lookup", f"no auth user for {user_email}")
        return 1
    _ok("user lookup", f"user_id={user_id[:8]}…")

    if snippet_id_override:
        try:
            row = (
                db.client.table("charisma_snippets")
                .select(
                    "id, session_id, admin_comment, ai_draft_admin_comment, "
                    "snippet_type"
                )
                .eq("id", snippet_id_override)
                .limit(1)
                .execute()
                .data
            ) or []
        except Exception as e:
            _fail("snippet lookup", str(e))
            return 1
        if not row:
            _fail("snippet lookup", f"no snippet with id={snippet_id_override}")
            return 1
        # Fetch session published_at
        try:
            sess = (
                db.client.table("v2_sessions")
                .select("results_published_at")
                .eq("id", row[0]["session_id"])
                .limit(1)
                .execute()
                .data
            ) or [{}]
        except Exception:
            sess = [{}]
        pick = {
            "snippet_id": row[0]["id"],
            "session_id": row[0]["session_id"],
            "session_published_at": sess[0].get("results_published_at"),
            "current_admin_comment": row[0].get("admin_comment"),
            "current_ai_draft": row[0].get("ai_draft_admin_comment"),
            "snippet_type": row[0].get("snippet_type"),
        }
    else:
        pick = _pick_test_snippet(db, user_id, prefer_unpublished=True)
        if not pick:
            _fail(
                "snippet pick",
                f"no snippets found on any session for user {user_email}",
            )
            return 1
    _ok(
        "snippet pick",
        f"snippet={pick['snippet_id'][:8]}… session={pick['session_id'][:8]}…",
    )
    _info(f"existing admin_comment: {pick['current_admin_comment'] or '(none)'}")
    _info(f"existing ai_draft:      {pick['current_ai_draft'] or '(none)'}")
    _info(f"session published_at:   {pick['session_published_at'] or '(unpublished)'}")
    if pick["session_published_at"]:
        _warn(
            "session is ALREADY PUBLISHED — re-publish is idempotent on "
            "results_published_at but will still write a fresh RLHF row "
            "and may re-fire the results email."
        )

    # Snapshot before any writes
    before = _snapshot_counts(db, pick["session_id"])
    _info(f"before — admin_annotation_events rows for session: "
          f"{before['admin_annotation_events_for_session']}")
    _info(f"before — admin_annotations_log    rows for session: "
          f"{before['admin_annotations_log_for_session']}")

    if dry_run:
        print(f"\n{Color.YELLOW}DRY RUN — exiting before any writes.{Color.END}")
        return 0

    # ── Step 1 — Admin saves an edited comment with acceptance_mode
    test_comment_text = (
        "[SMOKE TEST "
        + datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        + "] Capture-pipeline E2E check."
    )
    coach_label = (
        "charisma" if pick["snippet_type"] != "stress" else "stress"
    )

    if service_role:
        _step(1, "db.update_snippet_comment(...) [service-role, no HTTP]")
        try:
            updated_row = db.update_snippet_comment(
                snippet_id=pick["snippet_id"],
                admin_comment=test_comment_text,
                snippet_type=coach_label,
                admin_user_id=user_id,
                acceptance_mode="admin_corrected",
            )
        except Exception as e:
            _fail("db.update_snippet_comment", f"raised: {e}")
            updated_row = None

        step1_ok = updated_row is not None
        if not step1_ok:
            _fail(
                "db.update_snippet_comment",
                "returned None — see service log above",
            )
            fail_count += 1
        else:
            _ok("db.update_snippet_comment", "row written")
            returned_mode = updated_row.get("admin_comment_acceptance_mode")
            if returned_mode == "admin_corrected":
                _ok(
                    "row acceptance_mode",
                    "admin_corrected on returned row",
                )
            else:
                _fail(
                    "row acceptance_mode",
                    f"expected 'admin_corrected' got {returned_mode!r}",
                )
                fail_count += 1
    else:
        _step(1, "POST /v2/admin/snippets/<id>/comment")
        url1 = f"{backend_url.rstrip('/')}/v2/admin/snippets/{pick['snippet_id']}/comment"
        body1 = {
            "admin_comment": test_comment_text,
            "snippet_type": coach_label,
            "acceptance_mode": "admin_corrected",
        }
        resp1, status1 = _post(url1, admin_jwt, body1, label="comment endpoint")
        step1_ok = status1 == 200
        if not step1_ok:
            _fail(
                "comment endpoint",
                f"status={status1} body={json.dumps(resp1)[:300]}",
            )
            fail_count += 1
        else:
            _ok("comment endpoint", "status=200")
            returned_mode = (resp1 or {}).get("acceptance_mode")
            if returned_mode == "admin_corrected":
                _ok("response acceptance_mode", "admin_corrected echoed back")
            else:
                _fail(
                    "response acceptance_mode",
                    f"expected 'admin_corrected' got {returned_mode!r}",
                )
                fail_count += 1

    # ── Step 2 — Verify snippet column updated
    _step(2, "Verify charisma_snippets.admin_comment_acceptance_mode")
    if not step1_ok:
        _warn("skipping — Step 1 failed, the snippet wasn't written to")
        _summarize_and_exit(
            fail_count, pick, additional_note=(
                "Step 1's POST didn't succeed, so subsequent gates "
                "have nothing to verify against. Fix the comment-endpoint "
                "failure (above) before re-running."
            ),
        )
        return 1
    try:
        row = (
            db.client.table("charisma_snippets")
            .select(
                "admin_comment, admin_comment_acceptance_mode, "
                "admin_comment_acceptance_set_at"
            )
            .eq("id", pick["snippet_id"])
            .limit(1)
            .execute()
            .data
        ) or []
    except Exception as e:
        _fail("snippet column read", str(e))
        fail_count += 1
        row = []

    if row:
        actual_mode = row[0].get("admin_comment_acceptance_mode")
        actual_at = row[0].get("admin_comment_acceptance_set_at")
        actual_comment = row[0].get("admin_comment")
        if actual_mode == "admin_corrected":
            _ok("admin_comment_acceptance_mode", "set to 'admin_corrected'")
        else:
            _fail(
                "admin_comment_acceptance_mode",
                f"expected 'admin_corrected' got {actual_mode!r}",
            )
            fail_count += 1
        if actual_at:
            _ok("admin_comment_acceptance_set_at", f"timestamp set: {actual_at}")
        else:
            _fail("admin_comment_acceptance_set_at", "still NULL")
            fail_count += 1
        if actual_comment == test_comment_text:
            _ok("admin_comment value", "matches what we POSTed")
        else:
            preview = (
                (actual_comment[:80] if isinstance(actual_comment, str) else None)
                or repr(actual_comment)
            )
            _fail("admin_comment value", f"got {preview!r}")
            fail_count += 1

    # ── Step 3 — Publish the session with the 5-question array
    test_session_comment = (
        f"[SMOKE TEST {datetime.now(timezone.utc).isoformat()}] "
        "Session-level test comment from smoke_rlhf_capture.py"
    )
    test_questions = [
        {
            "position": 1,
            "text": "Smoke test Q1 — ground emotion?",
            "intent_tag": "ground-emotion",
        },
        {
            "position": 2,
            "text": "Smoke test Q2 — test application?",
            "intent_tag": "test-application",
        },
    ]

    if service_role:
        _step(3, "Replicate publish handler via db helpers [service-role]")
        # Mirror the route's POST /admin/sessions/<id>/publish steps:
        # stamp results_published_at → flip status → persist final_
        # human_next_questions → write 1 session-level row +
        # N per-position rows to admin_annotations_log. Skips the
        # results-ready email and the route's body-shape validation.
        rlhf_rows_written = 0

        try:
            published_row = db.v2_publish_session_results(pick["session_id"])
            if published_row:
                _ok("v2_publish_session_results", "results_published_at stamped")
            else:
                _fail("v2_publish_session_results", "returned None")
                fail_count += 1
        except Exception as e:
            _fail("v2_publish_session_results", f"raised: {e}")
            fail_count += 1

        try:
            db.v2_update_session_status_unscoped(pick["session_id"], "completed")
            _ok("status flip", "set to 'completed'")
        except Exception as e:
            _fail("status flip", f"raised: {e}")
            fail_count += 1

        try:
            db.set_session_final_next_questions(
                pick["session_id"], test_questions,
            )
            _ok("set_session_final_next_questions", "array persisted")
        except Exception as e:
            _fail("set_session_final_next_questions", f"raised: {e}")
            fail_count += 1

        # Session-level row
        try:
            sess_row = db.insert_admin_annotation_log(
                user_id=user_id,
                session_id=pick["session_id"],
                ai_predicted_comment=None,
                ai_predicted_question=None,
                final_human_comment=test_session_comment,
                final_human_question=None,
                was_corrected=True,
            )
            if sess_row is not None:
                rlhf_rows_written += 1
        except Exception as e:
            _fail("admin_annotations_log session-row", f"raised: {e}")
            fail_count += 1

        # Per-position rows
        for q in test_questions:
            try:
                row = db.insert_admin_annotation_log(
                    user_id=user_id,
                    session_id=pick["session_id"],
                    ai_predicted_comment=None,
                    ai_predicted_question=None,
                    final_human_comment=None,
                    final_human_question=q["text"],
                    was_corrected=True,
                    question_position=q["position"],
                    intent_tag=q["intent_tag"],
                )
                if row is not None:
                    rlhf_rows_written += 1
            except Exception as e:
                _fail(
                    f"admin_annotations_log pos={q['position']}",
                    f"raised: {e}",
                )
                fail_count += 1

        if rlhf_rows_written >= 3:
            _ok(
                "admin_annotations_log rows written",
                f"{rlhf_rows_written} (1 session + 2 positions)",
            )
        else:
            _fail(
                "admin_annotations_log rows written",
                f"only {rlhf_rows_written} of 3 expected landed",
            )
            fail_count += 1

        _info(
            "service-role mode: skipped the route's "
            "record_snippet_publish_annotations() call. Step 5 "
            "(admin_annotation_events check) will show 0 fresh rows — "
            "that's expected in this mode, not a failure."
        )
    else:
        _step(3, "POST /v2/admin/sessions/<id>/publish")
        url3 = (
            f"{backend_url.rstrip('/')}/v2/admin/sessions/"
            f"{pick['session_id']}/publish"
        )
        body3 = {
            "final_human_comment": test_session_comment,
            "final_human_next_questions": test_questions,
        }
        resp3, status3 = _post(url3, admin_jwt, body3, label="publish endpoint")
        if status3 != 200:
            _fail(
                "publish endpoint",
                f"status={status3} body={json.dumps(resp3)[:300]}",
            )
            fail_count += 1
        else:
            _ok("publish endpoint", "status=200")
            rlhf_logged = (resp3 or {}).get("rlhf_logged")
            rlhf_rows = (resp3 or {}).get("rlhf_rows_written")
            was_corrected = (resp3 or {}).get("was_corrected")
            if rlhf_logged is True:
                _ok("response.rlhf_logged", "True")
            else:
                _fail("response.rlhf_logged", f"got {rlhf_logged!r}")
                fail_count += 1
            if isinstance(rlhf_rows, int) and rlhf_rows >= 3:
                _ok(
                    "response.rlhf_rows_written",
                    f"{rlhf_rows} (≥ 3 expected: 1 session + 2 positions)",
                )
            else:
                _fail(
                    "response.rlhf_rows_written",
                    f"expected ≥3 got {rlhf_rows!r}",
                )
                fail_count += 1
            if was_corrected is True:
                _ok("response.was_corrected", "True (admin diffed)")
            else:
                _warn(
                    f"response.was_corrected = {was_corrected!r} "
                    "(may be False if no AI prediction existed to diff against)"
                )

    # Give Supabase a moment to settle (rare race on subsequent reads)
    time.sleep(0.5)

    # ── Step 4 — Verify rows in admin_annotations_log
    _step(4, "Verify admin_annotations_log rows for this session")
    try:
        log_rows = (
            db.client.table("admin_annotations_log")
            .select(
                "id, question_position, intent_tag, was_corrected, "
                "ai_predicted_question, final_human_question, "
                "ai_predicted_comment, final_human_comment, created_at"
            )
            .eq("session_id", pick["session_id"])
            .order("created_at", desc=True)
            .limit(20)
            .execute()
            .data
        ) or []
    except Exception as e:
        _fail("admin_annotations_log read", str(e))
        fail_count += 1
        log_rows = []

    # Filter to rows from this run (most recent N)
    fresh_log = [
        r for r in log_rows
        if (r.get("final_human_comment") == test_session_comment
            or (r.get("final_human_question") or "").startswith("Smoke test Q"))
    ]
    if len(fresh_log) >= 3:
        _ok(
            "admin_annotations_log fresh rows",
            f"{len(fresh_log)} rows (expected ≥3: 1 session + 2 positions)",
        )
    else:
        _fail(
            "admin_annotations_log fresh rows",
            f"expected ≥3 got {len(fresh_log)}",
        )
        fail_count += 1

    positions = sorted(
        [r.get("question_position") for r in fresh_log
         if r.get("question_position") is not None]
    )
    if positions == [1, 2]:
        _ok("per-position rows", "positions [1, 2] present")
    else:
        _fail("per-position rows", f"expected [1, 2] got {positions}")
        fail_count += 1

    session_level = [r for r in fresh_log if r.get("question_position") is None]
    if len(session_level) >= 1:
        _ok("session-level row", f"{len(session_level)} row(s) with NULL position")
    else:
        _fail("session-level row", "no NULL-position row found")
        fail_count += 1

    # Verify intent_tag carried through
    tags_seen = sorted({r.get("intent_tag") for r in fresh_log if r.get("intent_tag")})
    if "ground-emotion" in tags_seen and "test-application" in tags_seen:
        _ok("intent_tags carried", f"{tags_seen}")
    else:
        _fail("intent_tags carried", f"got {tags_seen}")
        fail_count += 1

    # ── Step 5 — Verify rows in admin_annotation_events
    _step(5, "Verify admin_annotation_events for this session "
              "(field_name capture)")
    try:
        ev_rows = (
            db.client.table("admin_annotation_events")
            .select("field_name, reason_chip, ai_original_text, "
                    "coach_final_text, created_at")
            .eq("session_id", pick["session_id"])
            .order("created_at", desc=True)
            .limit(20)
            .execute()
            .data
        ) or []
    except Exception as e:
        _fail("admin_annotation_events read", str(e))
        fail_count += 1
        ev_rows = []

    fresh_ev = [
        r for r in ev_rows
        if (r.get("coach_final_text") or "") == test_comment_text
        or (r.get("coach_final_text") or "") == test_session_comment
    ]

    if fresh_ev:
        _ok(
            "admin_annotation_events fresh rows",
            f"{len(fresh_ev)} row(s) carry our test text",
        )
        for r in fresh_ev:
            _info(
                f"  field_name={r.get('field_name')!r}  "
                f"chip={r.get('reason_chip')!r}"
            )
    elif service_role:
        _warn(
            "admin_annotation_events fresh rows = 0 — EXPECTED in "
            "service-role mode (we bypassed the route handler that "
            "calls record_snippet_publish_annotations). To exercise "
            "this gate, re-run without --service-role and with a real "
            "admin JWT."
        )
    else:
        _fail(
            "admin_annotation_events fresh rows",
            "NO rows from this run contain our test text. "
            "This means publish-time capture (record_snippet_publish_annotations) "
            "did NOT write to admin_annotation_events. "
            "A1 backfill cron would have nothing to recover from this path."
        )
        fail_count += 1

    # ── Summary
    if fail_count == 0:
        _summarize_and_exit(0, pick)
        print(
            "  RLHF capture pipeline is firing end-to-end. Safe to "
            "build A1 backfill cron — it has working capture to "
            "complement."
        )
        return 0

    _summarize_and_exit(
        fail_count, pick, additional_note=(
            "At least one write path did not land. Investigate before "
            "building A1 — a broken capture means the cron will produce "
            "zero useful rows."
        ),
    )
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="End-to-end smoke test for the RLHF capture pipeline."
    )
    parser.add_argument(
        "--backend-url",
        default=os.getenv("BACKEND_URL", "https://flask-backend-production-ab37.up.railway.app"),
        help="Backend base URL (default: prod Railway)",
    )
    parser.add_argument(
        "--admin-jwt",
        default=os.getenv("ADMIN_JWT", ""),
        help="Admin Supabase access_token (or set ADMIN_JWT env)",
    )
    parser.add_argument(
        "--user-email",
        default=os.getenv("TEST_USER_EMAIL", "artur@willonski.com"),
        help="Email of the user whose snippet/session we'll test against",
    )
    parser.add_argument(
        "--snippet-id",
        default=None,
        help="Specific snippet UUID to test (default: auto-pick most recent)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve snippet + print plan, but do not POST anything",
    )
    parser.add_argument(
        "--service-role",
        action="store_true",
        help=(
            "Skip the Flask route layer (no JWT needed). Calls db "
            "helpers directly via SUPABASE_SERVICE_ROLE_KEY. Tests "
            "the data path end-to-end; does NOT exercise route auth "
            "or body validation, and Step 5 (admin_annotation_events) "
            "will show 0 fresh rows since publish-time capture is "
            "the route's job."
        ),
    )
    args = parser.parse_args()

    if not args.admin_jwt and not args.service_role and not args.dry_run:
        print(
            f"{Color.RED}ERROR{Color.END} — pass --admin-jwt / "
            "ADMIN_JWT env, OR --service-role to bypass the route "
            "layer entirely. --dry-run also works without either "
            "(no writes).",
            file=sys.stderr,
        )
        return 2

    try:
        return run_smoke_test(
            backend_url=args.backend_url,
            admin_jwt=args.admin_jwt,
            user_email=args.user_email,
            snippet_id_override=args.snippet_id,
            dry_run=args.dry_run,
            service_role=args.service_role,
        )
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
