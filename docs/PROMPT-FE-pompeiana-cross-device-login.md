# FE prompt — Pompeiana behind the WillpowerLab login, synced across devices

Companion: `docs/PROMPT-BE-pompeiana-cross-device-login.md` (the Supabase
schema + RLS — read §BE-1 for the row shape you are writing to).

**Goal (founder, 2026-07-27):** log in to Pompeiana through WillpowerLab, on a
separate domain, and have novena progress follow the user across devices.

> **Two caveats.** (1) Nobody has read the Pompeiana repo while writing this —
> repo access was declined, so every claim about `app.js`, `store.js`, `sw.js`
> and the `pompeiana.v1` blob comes from the founder's description. **Verify
> each one against the files before acting on it.** (2) **Nothing here is built
> yet.**

Two frontends are in scope: **Pompeiana** (all tasks except FE-5) and the
**WillpowerLab web app** (FE-5 only, and only under Option B).

---

## 0. The constraint that shapes everything

Pompeiana has **no package manager, no bundler, no build step** — four ES
modules loaded straight from `<script type="module">`, and the entire JS is
~45KB. It is offline-first: a cache-first service worker, zero external calls,
`localStorage` as the only persistence.

Two consequences, both non-negotiable:

1. **Do not add `@supabase/supabase-js`.** From a CDN it breaks the
   zero-external-calls property the service worker relies on; vendored, it is a
   larger dependency than the entire application. Everything needed here is
   four plain HTTP calls (§FE-1).
2. **Offline behaviour is a feature, not a nicety.** This app is used in
   churches with no signal. No network call may ever sit between a user and the
   next bead.

---

## FE-1 — `js/sync.js`, a new module, no dependencies

Three operations against Supabase, all plain `fetch`, matching the hand-written
character of the existing modules:

| Operation | Call |
|---|---|
| refresh session | `POST {SUPABASE_URL}/auth/v1/token?grant_type=refresh_token` |
| pull state | `GET {SUPABASE_URL}/rest/v1/pompeiana_state?select=state,updated_at` |
| push state | `POST {SUPABASE_URL}/rest/v1/pompeiana_state` with header `Prefer: resolution=merge-duplicates` |

Every request carries `apikey: <ANON_KEY>` and `Authorization: Bearer
<access_token>`.

- **No `where user_id = …` anywhere.** RLS scopes the row server-side; a client
  filter is redundant and, if it ever disagrees with the policy, misleading.
- **The anon key is the only key this app may ever hold.** If you find yourself
  reaching for the service-role key, stop — it bypasses RLS entirely and would
  hand every user's data to anyone who opens devtools.
- Config (`SUPABASE_URL`, anon key) is public and can live in a small
  `js/config.js`. Both are already public values; the security boundary is RLS,
  not secrecy.

## FE-2 — the session, and the offline rule

- Session (access + refresh token) persists in `localStorage`, alongside but
  **not inside** `pompeiana.v1`.
- Refresh on boot and on `401`. Never on a timer.
- **The offline rule, which matters more than the auth flow:** once a user has
  logged in, a cached session is sufficient **forever** while offline. Only
  re-prompt when a network call actually returns `401` *and* the device is
  online.

  Why this is called out: `sw.js` is cache-first, so the app loads with no
  network — but a hard login gate would then show a login wall to someone in a
  basement with no signal, on an app whose entire point is offline use. Being
  logged out must cost **sync**, never **access**. (See Q2 in the BE prompt —
  the founder said "behind the login", and this is the caveat to confirm
  against.)

## FE-3 — conflict resolution — **the real design work, not the auth**

Phone reaches step 40. Laptop still holds step 12 from an earlier sync. Naive
last-write-wins **drags the user backwards mid-novena**, which for this app is
a correctness bug, not a UX wrinkle.

Rule: **furthest progress wins, scoped to a run.**

```
rank(s)  = [s.day, s.stepIndex, s.rep]           // lexicographic
same run → higher rank wins                       // never move backwards
new run  → later startedAt wins                   // novena #2 beats finished #1
```

This requires **two new fields in the stored state**: `runId` and `startedAt`.

**Add them now, in this task, even before sync ships.** Without `runId`,
starting a second novena at day 1 looks like regression and day 54 of the
finished run wins forever. Retrofitting them onto blobs already in users'
browsers is strictly harder than writing them today.

- Migrate an existing `pompeiana.v1` blob on read: absent `runId` → mint one,
  set `startedAt` from whatever start date is recoverable, else now.
- Resolve on **pull**, then push the winner back so both devices converge.

## FE-4 — bump the service worker cache — **or none of this ships**

`sw.js` is cache-first on `pompejanka-v1`. Every installed PWA will keep
serving today's files forever: a new `js/sync.js` is never fetched, and edits
to `app.js` never land.

- Bump the cache name (`pompejanka-v2`).
- Delete stale caches in the `activate` handler, or they accumulate on every
  release.
- Add every new file to the precache list.
- Verify against an **already-installed** instance, not a fresh one. A hard
  reload hides exactly this bug — the failure only appears for existing users,
  who are all of them.

## FE-5 — the WillpowerLab handoff page — **Option B only**

Two ways to satisfy "log in through WillpowerLab". They differ only in whether
the user types their password twice.

**Option A (recommended first):** Pompeiana shows its own login form against
the same Supabase project. Same credentials, same accounts, cross-device sync
works fully. Costs one extra login per domain. **No WillpowerLab change at
all.**

**Option B:** the loading redirect the founder described.

```
pompeiana → willpowerlab.com/handoff?next=<pompeiana-url>
          → (session already present) → redirect back with tokens in the FRAGMENT
          → pompeiana setSession → strip the fragment immediately
```

Rules, all load-bearing:

- **Exact-origin allowlist** on `next`. Not a prefix check, not `endsWith`, not
  a regex. A permissive check here is an open redirect that mails a live
  WillpowerLab session to any URL an attacker supplies — the worst failure
  available in this whole plan.
- Tokens in the **fragment** (`#at=…&rt=…`), never the query string. Fragments
  are not sent to servers and never land in access logs.
- `history.replaceState` to strip the fragment the instant the session is
  stored, so it does not survive in history or a shared link.
- The handoff page is **pure client-side** — the WillpowerLab frontend already
  holds the session. It needs no backend endpoint (see BE-3).

**Recommendation: ship A, add B when the second login actually annoys.** A is
a form; B is an auth flow with a security-critical allowlist.

---

## Acceptance

1. Log in on device 1, advance to day 3 step 40, open device 2 → resumes at day
   3 step 40, same bead.
2. Advance further on device 2, return to device 1 → device 1 moves **forward**
   to match. Never backwards.
3. Aeroplane mode: the app opens, all 91 steps of the day work, taps persist
   locally. Back online → state converges with no user action and nothing lost.
4. Finish a novena and start a new one → day 1 of the new run wins on every
   device; the old run's day 54 never resurrects it.
5. An already-installed PWA picks up the new build (FE-4 verified the hard way).
6. Language switch mid-prayer still preserves step and bead — the existing
   behaviour must not regress.

## Open questions

Answer these before starting; two of them change the shape of the work.

**Q1** — does the user's pasted **scripture text** sync across devices, or stay
local? If it syncs it needs its own table (BE-2), not the state blob — it is
written rarely and read at boot, the opposite pattern from progress.

**Q2** — **hard login gate**, or optional login that only adds sync? Read the
offline rule in FE-2 before answering.

**Q3** — the Pompeiana domain, for the allowlist and CORS.

**Q4** — do existing users have `pompeiana.v1` progress that must survive first
login? If yes, first-login merge (local blob vs empty server row) is its own
task and needs the FE-3 rule applied to it.

**Q5** — Option A or Option B first?
