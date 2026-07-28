# FE prompt — Pompeiana behind the WillpowerLab login, synced across devices

Companion: `docs/PROMPT-BE-pompeiana-cross-device-login.md` (the Supabase
schema + RLS — read §BE-1 for the row shape you are writing to).

**Goal (founder, 2026-07-27):** log in to Pompeiana through WillpowerLab, on a
separate domain, and have novena progress follow the user across devices.

> **STATUS 2026-07-27.** The **backend is done and verified** —
> `migrations/add_pompeiana_sync.sql` in the willab repo creates
> `pompeiana_state` and `pompeiana_scripture` with row-level security, tested
> against a real Postgres with two users. **Nothing on the Pompeiana side is
> built** — repo access was declined, so this remains a spec.
>
> Founder answers folded in: **hard login gate** (FE-2), **scripture syncs
> too** (new FE-6), **Option A first** (so FE-5 is deferred, not deleted).
>
> **Caveat that still stands:** nobody has read the Pompeiana repo, so every
> claim about `app.js`, `store.js`, `sw.js` and the `pompeiana.v1` blob comes
> from the founder's description. **Verify each against the files.**

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
**The gate is HARD (founder 2026-07-27): no login, no app.** It is enforced at
the database too — `anon` has zero privileges on both tables, so an
unauthenticated client cannot read a row even if the UI let it try.

**But "hard gate" applies to the FIRST login only.** Once a user has
authenticated on a device, a cached session is sufficient **forever while
offline**. Re-prompt only when a network call actually returns `401` *and* the
device is online.

This is not a softening of the founder's decision — it is what makes it
survivable. `sw.js` is cache-first, so the app itself loads with no network. A
gate that re-checked auth on every launch would show a login wall to someone
in a church basement with no signal, on an app whose entire purpose is offline
use, and an expired refresh token would lock them out of a novena mid-run.
**Being logged out must cost sync, never access to prayers already on the
device.**

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

- Resolve on **pull**, then push the winner back so both devices converge.
- **No blob migration needed** (founder 2026-07-27: fresh app, zero existing
  users). Mint `runId` + `startedAt` when a novena starts and never read a
  legacy shape — there is none.

**The urgency has a shelf life, though.** "No existing users" is true *today*.
The moment the app is reachable by anyone, the first person to start a novena
becomes a user with a blob in their browser. So `runId`/`startedAt` must ship
**in the same release as, or before, public availability** — not necessarily
before sync, but before users exist. Miss that window and the retrofit problem
comes back.

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

## FE-6 — sync the pasted scripture (founder: yes, it syncs)

`pompeiana_scripture` is live: `(user_id, mystery_id, language)` primary key,
plus `text` and `updated_at`. Same three ops as FE-1, same anon key, same RLS
scoping — no `where user_id` clause.

- **Read once at boot**, not per mystery. One `GET
  /rest/v1/pompeiana_scripture?select=mystery_id,language,text` returns
  everything the user has, and RLS guarantees it is only theirs.
- **Write on blur/save of a paste**, not on keystroke. Upsert with
  `Prefer: resolution=merge-duplicates`; the composite PK is the conflict
  target.
- `mystery_id` and `language` are the keys from the app's own data package
  (`mysteries.json` / `languages.json`) — the column is `TEXT` precisely so a
  new language there never needs a database migration.
- **Conflict rule is different from progress, deliberately.** Scripture is
  free text a user typed, not monotonic progress: last-write-wins per
  `(mystery, language)` is correct here. Do **not** apply the FE-3
  furthest-progress rule to it.
- Keep it **out of the `state` blob**. It is written rarely and read at boot;
  progress is rewritten on every bead tap. Folding them together would
  re-send every pasted passage on each tap.

## FE-5 — the WillpowerLab handoff page — **DEFERRED (founder chose Option A)**

**Founder chose Option A — build that, not this.** Pompeiana shows its own
login form against the same Supabase project: same credentials, same accounts,
full cross-device sync, **no WillpowerLab change at all**. Cost is one extra
login per domain.

Option B below is the loading redirect originally described. It is written up
so it is ready when the second login starts to annoy — **do not build it now.**
It is an auth flow with a security-critical allowlist, where Option A is a
form.

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

## The wire contract you are coding against

Verified against a real Postgres, not assumed:

- `user_id` has `DEFAULT auth.uid()` — **omit it on insert**, the database
  fills it from the JWT. Sending it works too, but sending someone *else's* is
  rejected by the policy, as it should be.
- Upsert conflict targets: `pompeiana_state` → `(user_id)`;
  `pompeiana_scripture` → `(user_id, mystery_id, language)`.
- **There is no DELETE**, on either table, by design. "Start over" is an UPDATE
  to a fresh `run_id`. A delete attempt returns `permission denied` — that is
  not a bug to route around.
- An unauthenticated request gets `permission denied for table`, not an empty
  list. Treat it as "log in", never as "the user has no data" — writing an
  empty state on top of that would wipe real progress.

## Open questions

**Q3 — the only one left.** The Pompeiana domain, for the CORS entry in the
Supabase project. Everything else is decided.

**Answered 2026-07-27:** ~~Q1~~ scripture syncs → FE-6. ~~Q2~~ hard login gate,
with the offline caveat in FE-2. ~~Q4~~ fresh app, no existing users → no
first-login merge, no blob migration (but read the shelf-life note in FE-3).
~~Q5~~ Option A first.

**What the hard gate + fresh app buys you:** every user is authenticated from
their very first bead, so purely-local un-synced state only ever arises from
going offline — which FE-3 already covers. There is no anonymous-then-claim
path to design, and no orphaned local novena to rescue.
