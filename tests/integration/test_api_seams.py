"""
STORY    As a speaker using the app, I want the server's front door (sign-in,
         job progress, uploads, error answers) to behave the same every
         time, so that the app never breaks on it or shows me someone
         else's job.
OUTCOME
  O1  The paths the website and Railway call exist, and the health check
      answers "ok".
  O2  Without a valid sign-in, a protected page answers a clear "not signed
      in" the app can read.
  O3  A guest or the owner can follow their own processing job; someone
      else's job looks exactly like no job at all.
  O4  Errors come back in a form the app can read, never as a web page.
  O5  The browser's pre-upload check accepts every header the app sends,
      so big deck uploads go through.
PROVES   O1 -> test_critical_routes_are_wired, test_health_endpoints_answer_200
         O2 -> test_protected_route_without_header_is_401_json,
               test_protected_route_non_bearer_is_401_json,
               test_protected_route_garbage_token_is_401_json
         O3 -> test_guest_job_polls_anonymously,
               test_owned_job_polls_with_bearer,
               test_foreign_job_and_unknown_job_are_indistinguishable,
               test_non_uuid_job_id_is_404_without_db
         O4 -> test_405_answers_json_not_html,
               test_413_handler_is_registered_and_answers_json
         O5 -> test_preflight_allows_every_header_the_fe_sends
WHY      Incident 2026-07-15: big deck uploads failed at the browser's
         pre-upload (CORS) check.
"""
import uuid


JOB_ID = str(uuid.UUID(int=1))


def _job_row(**over):
    row = {
        "id": JOB_ID,
        "user_id": None,          # guest job unless a test says otherwise
        "status": "completed",
        "stage": "readout",
        "percent": 100,
        "message": None,
        "session_id": str(uuid.UUID(int=2)),
        "created_at": "2026-08-01T00:00:00Z",
        "finished_at": "2026-08-01T00:01:00Z",
        "result": {"ok": True},
        "error": None,
    }
    row.update(over)
    return row


# ---------------------------------------------------------------- wiring --

# Load-bearing paths the FE (or Railway) calls by exact string. A rename or
# a dropped blueprint registration must fail HERE, not in production.
CRITICAL_ROUTES = (
    "/health",
    "/api/health",
    "/auth/signup",
    "/user/profile",
    "/v2/jobs/<job_id>/status",
    "/v2/internal/jobs/sweep",
)


def test_critical_routes_are_wired(app_client):
    import app as app_module

    rules = {r.rule for r in app_module.app.url_map.iter_rules()}
    missing = [p for p in CRITICAL_ROUTES if p not in rules]
    assert not missing, f"critical routes missing from url_map: {missing}"


def test_health_endpoints_answer_200(app_client):
    for path in ("/health", "/health/", "/api/health"):
        resp = app_client.get(path)
        assert resp.status_code == 200, path
        assert resp.get_json() == {"status": "ok"}


# ------------------------------------------------------------ auth seam --

def test_protected_route_without_header_is_401_json(app_client):
    resp = app_client.get("/user/profile")
    assert resp.status_code == 401
    assert resp.get_json()["code"] == "UNAUTHORIZED"


def test_protected_route_non_bearer_is_401_json(app_client):
    resp = app_client.get("/user/profile", headers={"Authorization": "Basic abc"})
    assert resp.status_code == 401
    assert resp.get_json()["code"] == "UNAUTHORIZED"


def test_protected_route_garbage_token_is_401_json(app_client):
    # "garbage" is not even JWT-shaped: verification dies at parse, before
    # any JWKS network fetch — deterministic offline and in CI.
    resp = app_client.get("/user/profile", headers={"Authorization": "Bearer garbage"})
    assert resp.status_code == 401
    assert resp.get_json()["code"] == "UNAUTHORIZED"


# ------------------------------------------- job poll (F1 pipeline seam) --

def test_guest_job_polls_anonymously(app_client, swap_db_client):
    swap_db_client.seed("processing_jobs", [_job_row()])
    resp = app_client.get(f"/v2/jobs/{JOB_ID}/status")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "completed"
    assert body["state"] == "ready"      # readout-GET vocabulary
    assert body["result"] == {"ok": True}
    # Poll freshness: a proxy must never cache 'processing'.
    assert resp.headers["Cache-Control"] == "no-store"


def test_owned_job_polls_with_bearer(app_client, swap_db_client, stub_verified_user):
    stub_verified_user("owner-1")
    swap_db_client.seed("processing_jobs", [_job_row(user_id="owner-1")])
    resp = app_client.get(
        f"/v2/jobs/{JOB_ID}/status", headers={"Authorization": "Bearer t"}
    )
    assert resp.status_code == 200
    assert resp.get_json()["job_id"] == JOB_ID


def test_foreign_job_and_unknown_job_are_indistinguishable(app_client, swap_db_client):
    # Foreign: the job exists but belongs to someone else; caller anonymous.
    swap_db_client.seed("processing_jobs", [_job_row(user_id="someone-else")])
    foreign = app_client.get(f"/v2/jobs/{JOB_ID}/status")

    # Unknown: no such job at all.
    swap_db_client.seed("processing_jobs", [])
    unknown = app_client.get(f"/v2/jobs/{JOB_ID}/status")

    assert foreign.status_code == unknown.status_code == 404
    # No existence leak: the two answers must be byte-identical.
    assert foreign.get_json() == unknown.get_json()


def test_non_uuid_job_id_is_404_without_db(app_client):
    resp = app_client.get("/v2/jobs/not-a-uuid/status")
    assert resp.status_code == 404
    assert resp.get_json()["code"] == "NOT_FOUND"


# ------------------------------------------------------- error handlers --

def test_405_answers_json_not_html(app_client):
    resp = app_client.patch("/health")
    assert resp.status_code == 405
    assert resp.get_json()["code"] == "METHOD_NOT_ALLOWED"


def test_413_handler_is_registered_and_answers_json(app_client):
    """Pins the app-level 413 contract: registered, and JSON on both branches
    (reference-video uploads get their own message).

    Deliberately NOT driven end-to-end with an oversized body: Werkzeug only
    raises RequestEntityTooLarge when a handler reads the body, and most
    routes read it inside a broad try/except that converts the 413 into that
    route's 500 — a seam finding in its own right, tracked separately. This
    test pins the piece app.py owns.
    """
    from werkzeug.exceptions import RequestEntityTooLarge
    import app as app_module

    flask_app = app_module.app
    app_level = flask_app.error_handler_spec[None]
    assert app_level.get(413), "no app-level 413 handler registered"

    with flask_app.test_request_context("/v2/recordings/upload", method="POST"):
        resp, status = app_module.handle_413(RequestEntityTooLarge())
        assert status == 413
        assert resp.get_json()["code"] == "PAYLOAD_TOO_LARGE"

    with flask_app.test_request_context(
        "/v2/admin/copilot/reference-videos/upload", method="POST"
    ):
        resp, status = app_module.handle_413(RequestEntityTooLarge())
        assert status == 413
        assert resp.get_json()["code"] == "PAYLOAD_TOO_LARGE"
        assert "Reference video" in resp.get_json()["error"]


# -------------------------------------------------------- CORS preflight --

def test_preflight_allows_every_header_the_fe_sends(app_client):
    """Regression fence for the 2026-07-15 incident: big deck uploads bypass
    the Vercel BFF and hit the backend directly; the browser preflight fails
    on ANY request header missing from the server allowlist."""
    resp = app_client.options(
        "/health",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers":
                "authorization, content-type, x-internal-secret, "
                "accept, x-requested-with, x-dev-key, x-willab-guest-owner",
        },
    )
    assert resp.status_code in (200, 204)
    allowed = (resp.headers.get("Access-Control-Allow-Headers") or "").lower()
    for header in ("authorization", "content-type", "x-internal-secret",
                   "accept", "x-requested-with", "x-dev-key",
                   "x-willab-guest-owner"):
        assert header in allowed, f"preflight would reject '{header}'"
