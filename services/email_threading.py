"""Per-user mailbox-threading headers (founder fix-pack BE-3 b+c).

Goal: ONE conversation per student in the mail client instead of one
new mail per event. Email can't literally edit a sent message, so the
mechanism is RFC 5322 threading: every mail about the same user carries
the same synthetic root reference in ``References`` + ``In-Reply-To``,
plus a stable subject. Gmail (and most clients) then stack them into a
single thread. We never control the first mail's real Message-ID with
Resend, so a References-only synthetic root is the reliable variant —
it still groups because the reference chain + subject match.

Two thread families, deliberately distinct so the coach's inbox and the
student's inbox each get their own clean conversation:

  - ``student_thread_headers`` — COACH-bound mail about one student
    (homework-complete pings). Root: willab-student-{user_id}@…
  - ``user_thread_headers`` — USER-bound mail from the coach/platform
    (publish-results, audit-ready, strong-sides audit).
    Root: willab-user-{user_id}@…

Both return ``{}`` for a falsy user_id (guest sessions) — callers pass
``headers or None`` and the send simply goes out unthreaded. Additive
and never raising: LIVE-LOOP-safe by construction.
"""
from __future__ import annotations

# Domain of the synthetic root Message-IDs. Purely an identifier —
# nothing is ever delivered to these addresses.
_THREAD_DOMAIN = "willpowerlab.com"


def _thread_headers(prefix: str, user_id) -> dict[str, str]:
    if not user_id:
        return {}
    ref = f"<willab-{prefix}-{user_id}@{_THREAD_DOMAIN}>"
    return {"References": ref, "In-Reply-To": ref}


def student_thread_headers(user_id) -> dict[str, str]:
    """Threading headers for COACH-mailbox mail about one student."""
    return _thread_headers("student", user_id)


def user_thread_headers(user_id) -> dict[str, str]:
    """Threading headers for mail sent TO one user."""
    return _thread_headers("user", user_id)
