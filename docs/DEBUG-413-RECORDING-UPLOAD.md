# Debug: 413 on recording-1 upload

When the frontend shows **"Request failed 413"** on the recording-1 (warm-up) step, the server is rejecting the request because the **request body is too large** ("Payload Too Large"). This usually happens because the client is uploading the **audio blob** (or base64) to the API, and either the **BFF (Next.js)** or the **Flask backend / reverse proxy** rejects it due to a size limit.

---

## 1) Identify who is returning the 413 (BFF vs backend)

Open DevTools → **Network** → click the failing **recording-1** request and check:

- **Request URL**
  - If it’s `https://app.willonski.com/api/.../recording-1` → the **Next.js BFF** (or the platform in front of it, e.g. Vercel) is rejecting.
  - If it’s `<BACKEND_URL>/v2/homework/session/.../recording-1` → the **Flask backend or its proxy** (e.g. Railway) is rejecting.
- **Response headers** → look at **`server`** (Vercel, Cloudflare, Railway, nginx, etc.).
- **Response body** → If it’s **JSON** with `code: "PAYLOAD_TOO_LARGE"` → the request reached **Flask**. If it’s empty or HTML → something in front of Flask (BFF or proxy) returned 413.
- **Request headers** → **`Content-Length`** (payload size) and **`Content-Type`** (expect `multipart/form-data` for file upload).

That tells you where to fix it.

---

## 2) Common causes and fixes

### A) Next.js API route limit / hosting limit (very common)

If the request goes to **`/api/...`**, you may be hitting:

- **Next.js body parser limits** — Pages router defaults to ~1 MB.
- **Vercel / serverless request size limits** — Hard limits; often can’t be raised enough for long recordings.

**Fix (best): don’t proxy raw audio through Next.js.**

- Upload audio **directly to storage** (Supabase Storage / S3) from the browser using a **signed URL**.
- Then call the backend **recording-1** with `{ audio_url, duration_seconds, ... }` (and optionally transcript if you do client-side transcription). The backend would need to support this “by URL” flow (create recording from URL instead of `request.files`).

**If you keep proxying through Next.js and it’s not a hard platform limit:**

In the **Next.js API route** that proxies to recording-1, set a higher body size:

```ts
export const config = {
  api: { bodyParser: { sizeLimit: "50mb" } }
};
```

(This doesn’t help on platforms with a hard request body limit.)

### B) Flask / reverse proxy limit

If 413 comes from the **backend** side:

**Flask (this repo):** Already set in `app.py`:

- `app.config["MAX_CONTENT_LENGTH"] = config.MAX_AUDIO_SIZE_MB * 1024 * 1024` (e.g. 25 MB).
- When exceeded, we return **413** with JSON: `{ "code": "PAYLOAD_TOO_LARGE", "error": "..." }`.

To allow larger uploads, increase **`MAX_AUDIO_SIZE_MB`** in config (or set `MAX_CONTENT_LENGTH` to e.g. `50 * 1024 * 1024`).

**Nginx (if in front of Flask):**

```nginx
client_max_body_size 50m;
```

**Railway / Cloudflare / load balancer:** Check their docs for request body size limits and increase to at least 25–50 MB if possible.

---

## 3) Quick confirmation: how big is the upload?

In Network → the **recording-1** request → check **Payload** size or **Request header `Content-Length`**. If it’s several MB+, that explains the 413.

Also check whether the client sends audio as:

- **`multipart/form-data`** with a file (preferred if uploading to server); or
- **JSON with base64** (adds ~33% size and hits limits faster).

---

## 4) What to paste so we can tell you the exact fix

From the failing **recording-1** request in DevTools → Network:

1. **Request URL** (full URL).
2. **Response headers** (or at least the **`server`** header).
3. **Request `Content-Length`** (or approximate payload size).
4. **Request `Content-Type`**.

With that we can say whether you need to switch to **direct-to-storage upload** (likely if the request hits the BFF/Vercel) or a **limit bump** in Flask / proxy is enough.

---

## Backend summary (this repo)

| What | Where |
|------|--------|
| **Flask `MAX_CONTENT_LENGTH`** | `app.py` — set from `config.MAX_AUDIO_SIZE_MB` (default 25 MB). |
| **413 handler** | `app.py` — returns JSON `{ "code": "PAYLOAD_TOO_LARGE", "error": "..." }`. |
| **Response body = JSON** | Request reached Flask; body was over our limit. |
| **Response body = empty/HTML** | 413 from BFF or proxy in front of Flask. |
