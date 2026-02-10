# Debug: "Backend server is not responding"

When the frontend shows:

**"Backend server is not responding. Please check: 1. Is your Flask backend running? 2. Is NEXT_PUBLIC_API_URL set correctly? (Current: https://flask-backend-production-ab37.up.railway.app/) 3. Can you reach the backend URL directly?"**

the app cannot reach the backend API. Until this is fixed, the frontend cannot start sessions, submit recordings, or get task blocks. Below: what the error means, likely causes, and how to check them.

---

## If it was fixed and the bug came back

1. **Redeploy the backend** — Ensure the latest backend (with `GET /`, `GET /health`, `GET /health/`, `GET /api/health`) is deployed. Railway may be serving an old build.
2. **CORS** — In production, `CORS_ORIGINS` must include your frontend origin (e.g. `https://your-app.vercel.app`). If the browser blocks the health request due to CORS, the frontend reports "not responding."
3. **Verify from browser or curl:**
   - `curl -i https://flask-backend-production-ab37.up.railway.app/`
   - `curl -i https://flask-backend-production-ab37.up.railway.app/health`
   All should return **200** and `{"status":"ok"}`.

---

## What the error means

The frontend (e.g. Next.js) is calling the backend URL (from `NEXT_PUBLIC_API_URL`) and getting no valid response. Typical triggers:

- **Network error** — request never reaches the server or times out (e.g. connection refused, timeout, CORS, or no response).
- **Backend down** — Flask isn’t running, crashed, or isn’t listening on the expected host/port.
- **Wrong URL** — frontend is pointing at a different environment, old deployment, or typo (e.g. wrong subdomain or path).

The message is raised when the frontend’s health/connectivity check to the backend fails (e.g. a GET to a health or status endpoint returns an error or doesn’t complete).

---

## Suspicions and what could have gone wrong

### 1. Backend service not running or crashed

**Suspicion:** The Flask app at `https://flask-backend-production-ab37.up.railway.app/` is not running, failed to start, or crashed.

**Possible causes:**

- Process exited (e.g. unhandled exception on startup, OOM, or crash in a request).
- Railway (or your host) restarted the service and it failed to start (e.g. missing env, wrong Python version, import error).
- Deployment didn’t finish or was rolled back; the URL still points at an old or inactive deployment.
- App binds to `127.0.0.1` instead of `0.0.0.0`, so it’s not reachable from the internet.

**What to check:**

- Railway (or host) dashboard: service status, recent deploys, logs. Look for startup errors or repeated restarts.
- If you can run the app locally: start Flask and confirm it listens on `0.0.0.0` and the port your host expects (e.g. from `PORT` env).
- Backend logs: stack traces, “Address already in use”, missing env vars, or failed imports.

---

### 2. NEXT_PUBLIC_API_URL wrong or outdated

**Suspicion:** The frontend is calling the wrong backend URL.

**Possible causes:**

- Frontend env: `NEXT_PUBLIC_API_URL` not set in the environment where the app is built/run, so it falls back to an old or default value.
- Build-time vs runtime: `NEXT_PUBLIC_*` is baked in at **build** time. If you change the URL after building, you must rebuild (and redeploy) the frontend.
- Typo or wrong environment: e.g. `http` instead of `https`, wrong subdomain (`flask-backend-production-ab37` vs another), or trailing slash differences.
- Frontend points at a different backend (e.g. staging URL while backend is only running in production, or vice versa).

**What to check:**

- In the environment where the frontend is built: `echo $NEXT_PUBLIC_API_URL` (or equivalent). It should be exactly the backend base URL you intend (e.g. `https://flask-backend-production-ab37.up.railway.app`).
- After changing it, rebuild and redeploy the frontend; confirm the built bundle or runtime config shows the new URL (e.g. in the error message or network tab).
- In the browser: open DevTools → Network, trigger the request that fails, and check the **Request URL**. It should match the backend you’re actually running.

---

### 3. Network / reachability

**Suspicion:** The backend is running, but the client (browser or BFF) cannot reach it.

**Possible causes:**

- **CORS:** Backend rejects the browser request due to CORS. The frontend may treat this as “not responding” if the response is missing or not handled as success. Check backend CORS config (e.g. allowed origins, methods, headers).
- **Firewall / security group:** Host or cloud firewall allows only certain IPs or ports; your client or the frontend host is blocked.
- **Timeout:** Backend is slow or stuck; the frontend (or proxy) times out and shows a generic “not responding” message.
- **DNS:** The hostname doesn’t resolve or resolves to the wrong place (less common for a known Railway URL but possible in some networks).
- **Proxy / VPN:** Corporate proxy or VPN blocks or alters requests to that host.

**What to check:**

- From your machine (or the machine that runs the frontend):  
  `curl -v https://flask-backend-production-ab37.up.railway.app/`  
  (or the exact health/status path the frontend uses). See if you get a response, a timeout, or a connection error.
- In the browser: DevTools → Network. For the failing request, check status (e.g. (failed), 0, 5xx), and whether it’s CORS or timeout.
- Backend logs: see if the request reaches the server at all. No log entry often means the request never reached the app (e.g. connection refused, TLS, or proxy).

---

### 4. Backend path or health check

**Suspicion:** Backend is up, but the URL or path the frontend uses is wrong, or the health check fails.

**Possible causes:**

- Frontend calls a path that doesn’t exist (404) or returns 5xx, and the frontend treats that as “backend not responding.”
- Backend has no root or health route; the frontend hits `/` or `/health` and gets 404 or an error.
- Backend is behind a reverse proxy; the public URL is correct but the proxy is misconfigured or down.

**What to check:**

- Open the **exact** backend URL (and path) in the browser or with `curl`. You should get a successful response (e.g. 200 with JSON or HTML), not 404/5xx or connection error.
- Confirm the backend exposes a route the frontend uses for the “backend responding” check (e.g. `/` or `/health`). If the backend only has `/v2/homework/...`, calling `/` might 404 and be treated as “not responding” depending on frontend logic.

---

### 5. Railway (or host) specifics

**Suspicion:** Issue is with the hosting platform, not the code.

**Possible causes:**

- Service slept or was scaled to 0; first request after idle times out or fails until the service is woken.
- Build failed on deploy; the running instance is an old version or no new version is running.
- Env vars (e.g. database URL, API keys) missing or wrong on the host, so the app crashes on startup or on first request.
- Port: host expects the app to listen on `PORT`; if the app ignores it and listens on a fixed port, the host’s proxy won’t forward traffic.

**What to check:**

- Railway (or host) dashboard: build logs, deploy status, runtime logs, and env vars.
- Backend code: app uses `os.environ.get("PORT", 5000)` (or similar) and listens on `0.0.0.0`.

---

## Quick checklist

| Check | Action |
|-------|--------|
| Backend running? | Host dashboard + backend logs; confirm process is up and listening. |
| URL correct? | Confirm `NEXT_PUBLIC_API_URL` at build time and in the failing request (DevTools → Network). Rebuild frontend after changing it. |
| Reachable? | `curl -v <NEXT_PUBLIC_API_URL>` (and the path used for the check) from your machine and from the frontend host if different. |
| CORS / 4xx/5xx? | Inspect failing request in Network tab; check response status and CORS headers. |
| Health route? | Backend exposes the path the frontend calls for “backend responding” (e.g. `/` or `/health`) and returns 2xx. |

---

## Summary

The error means the frontend’s request to the backend did not succeed. Most likely: **(1)** the backend isn’t running or crashed, **(2)** the frontend is using the wrong or outdated `NEXT_PUBLIC_API_URL`, or **(3)** the request is blocked or times out (network, CORS, firewall). Check backend status and logs, then the exact URL the frontend calls and whether that URL is reachable (e.g. with `curl` and DevTools).
