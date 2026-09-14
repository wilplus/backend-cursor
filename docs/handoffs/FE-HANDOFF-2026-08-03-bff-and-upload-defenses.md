# FE handoff — one BFF idiom + lab upload defenses (2026-08-03)

Two items from the P0/P1 sweep live in the **frontend** repo, not here.
This is the backend-side contract plus the specific defects found while
reading `docs/homework-bff-routes/` — enough to do the FE work without
re-deriving any of it.

Also documents three backend response changes the FE will see immediately.

---

## A. What changed on the backend (act on these)

### A1. Error bodies are now generic — and carry a `ref`

Every error response keeps the shape you already parse and adds one field:

```jsonc
{ "code": "V2_ERROR", "error": "Something went wrong on our end.", "ref": "a1b2c3d4" }
```

`error` is now **generic copy** in production. It used to be `str(e)` —
raw exception text, absolute server paths, occasionally credentials — so
anywhere the FE renders `error` straight into the UI, it was rendering a
stack trace fragment at users.

- **Render `error` as-is.** It is now safe and human-readable.
- **Show `ref` in the error boundary**, small and copyable
  ("Reference: a1b2c3d4"). It is the join key to the real exception in our
  logs — the only way support can diagnose a generic message.
- **Branch on `code`, never on `error` text.** Codes are stable; copy is not.

Unknown routes and uncaught server errors are now JSON too, not HTML —
`response.json()` no longer throws on those.

### A2. New status: `504 PROCESSING_TIMEOUT` on lab upload

```jsonc
{ "code": "PROCESSING_TIMEOUT",
  "error": "That recording is taking longer than expected — it's still processing, check back shortly.",
  "session_id": "…" }
```

The synchronous upload path now has a wall-clock budget
(`SYNC_UPLOAD_DEADLINE_SECONDS`, default 600s). When it is spent, the
request returns 504 instead of hanging until gunicorn reaps the worker.

**This is not a failure.** The audio is stored and the session row
exists. Treat it exactly like the async-queue 202: poll the readout with
the returned `session_id`. Do **not** show "recording failed" and do
**not** prompt a re-record — that would lose a take that is still
processing.

### A3. `413` semantics unchanged, but now enforced on real bytes

The upload cap was checked against `Content-Length`, which a client can
misdeclare. It is now enforced on the bytes actually read, so a request
that previously slipped through and failed confusingly downstream now
returns a clean `413 FILE_TOO_LARGE`.

---

## B. Lab upload route — `maxDuration` + abort (FE work)

The backend guard is in. The FE half is a Vercel route-segment config and
an `AbortSignal`; there is no backend equivalent for either.

In the BFF route that proxies the lab upload:

```ts
// app/api/lab/recordings/route.ts

// Vercel kills the function at the plan default (10s Hobby / 15s Pro)
// without this. A lab take is minutes of audio: the upload alone can
// exceed the default, and the analysis runs behind it.
export const maxDuration = 800;      // must EXCEED the backend's 600s budget
export const runtime = "nodejs";     // edge can't stream a multipart body this size
export const dynamic = "force-dynamic";

export async function POST(req: Request) {
  // Abort the upstream call slightly BEFORE Vercel kills us, so we can
  // return a real error instead of a platform 504 with an HTML body.
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 780_000);

  // Propagate the CLIENT's disconnect too: if the user closes the tab,
  // there is no reason to keep the backend working on a dead request.
  req.signal.addEventListener("abort", () => controller.abort());

  try {
    const upstream = await fetch(`${getBackendUrl()}/v2/lab/recordings`, {
      method: "POST",
      headers: { Authorization: `Bearer ${token}` },
      body: req.body,
      duplex: "half",              // required when streaming a request body
      signal: controller.signal,
    });
    return proxyResponse(upstream);
  } catch (e) {
    if ((e as Error).name === "AbortError") {
      return NextResponse.json(
        { code: "PROCESSING_TIMEOUT",
          error: "That recording is taking longer than expected — it's still processing, check back shortly." },
        { status: 504 },
      );
    }
    throw e;
  } finally {
    clearTimeout(timer);
  }
}
```

The ordering matters: **client abort < BFF abort (780s) < BFF maxDuration
(800s)**, and the backend's own budget (600s) sits below all of them. Each
layer gets to produce its own error before the layer above it gives up.
Invert any pair and you get a platform timeout page instead of JSON.

Apply the same shape to `POST /v2/coach/annotation-uploads` and the deck
upload route.

---

## C. One BFF idiom + token refresh (FE work)

### C1. The defect

`docs/homework-bff-routes/getAuth.ts` creates its Supabase server client
with only a `get` cookie handler:

```ts
cookies: {
  get(name: string) { return cookieStore.get(name)?.value; },
}
```

`supabase.auth.getSession()` will refresh an expired access token — and
then tries to **persist** the new one by calling `set`. With no `set`
handler, that write is silently dropped. The refreshed token exists for
exactly one request, and the next one starts from the same expired cookie.

Symptom: a user who leaves a tab open past the access-token TTL (1h by
default) starts getting 401s until a hard reload. That matches the
"random logouts" reports.

`getSession()` is also the wrong call server-side: it reads the cookie
without verifying it. Use `getUser()`, which validates against the auth
server, when the decision is "is this request authenticated".

### C2. The fix — one helper, used by every BFF route

```ts
// src/app/api/_lib/backend.ts   ← the ONLY place that talks to the backend
import { cookies } from "next/headers";
import { createServerClient } from "@supabase/ssr";
import { NextResponse } from "next/server";

async function getSupabase() {
  const cookieStore = await cookies();
  return createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll: () => cookieStore.getAll(),
        // THE FIX: without setAll, a refreshed token is never persisted.
        setAll: (list) => {
          try {
            list.forEach(({ name, value, options }) =>
              cookieStore.set(name, value, options));
          } catch {
            // Called from a Server Component, where cookies are readonly.
            // Safe to ignore when middleware also refreshes the session.
          }
        },
      },
    },
  );
}

export async function getAccessToken(): Promise<string | null> {
  const supabase = await getSupabase();
  // getUser() VALIDATES against the auth server and triggers a refresh
  // when the access token is expired; getSession() only reads the cookie.
  const { data: { user } } = await supabase.auth.getUser();
  if (!user) return null;
  const { data: { session } } = await supabase.auth.getSession();
  return session?.access_token ?? null;
}

/** Every BFF route goes through this. No exceptions, no direct fetch. */
export async function callBackend(
  path: string,
  init: RequestInit & { requireAuth?: boolean } = {},
): Promise<NextResponse> {
  const { requireAuth = true, ...rest } = init;
  const token = await getAccessToken();

  if (requireAuth && !token) {
    return NextResponse.json(
      { code: "UNAUTHENTICATED", error: "Authentication required." },
      { status: 401 },
    );
  }

  const base = (process.env.BACKEND_URL
    ?? process.env.NEXT_PUBLIC_BACKEND_URL
    ?? "http://localhost:5000").replace(/\/$/, "");

  const upstream = await fetch(`${base}${path}`, {
    ...rest,
    headers: {
      ...(rest.headers ?? {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    cache: "no-store",
  });

  return proxyResponse(upstream);   // existing helper, unchanged — keep it
}
```

Also add the middleware refresh, so the token is renewed on navigation
rather than only when an API call happens to notice:

```ts
// middleware.ts
export async function middleware(request: NextRequest) {
  const response = NextResponse.next({ request });
  const supabase = createServerClient(url, anonKey, {
    cookies: {
      getAll: () => request.cookies.getAll(),
      setAll: (list) => list.forEach(({ name, value, options }) =>
        response.cookies.set(name, value, options)),
    },
  });
  await supabase.auth.getUser();   // refreshes + writes cookies via setAll
  return response;
}

export const config = {
  matcher: ["/((?!_next/static|_next/image|favicon.ico).*)"],
};
```

### C3. Migration

1. Add `_lib/backend.ts` and `middleware.ts` above.
2. Convert routes to `callBackend` in batches — start with the ones users
   hit after a long idle (readout, session list, profile), since those are
   where the stale-token 401s actually surface.
3. Delete `getV2AccessToken` once nothing imports it. Keep
   `proxyResponse` — passing the upstream body through unchanged is
   correct and `callBackend` depends on it.
4. Guard against regression: a lint rule or a CI grep for `fetch(` with a
   backend URL outside `_lib/backend.ts`. Fragmentation is what produced
   the inconsistency; a single helper only stays single if something
   enforces it.

### C4. Definition of done

- No BFF route constructs an `Authorization` header itself.
- A session left idle past the access-token TTL keeps working without a
  reload.
- A 401 from the backend surfaces as a re-auth prompt, not a generic
  error toast.
- Error boundaries display `code` + `ref`, not raw `error` text matching.
