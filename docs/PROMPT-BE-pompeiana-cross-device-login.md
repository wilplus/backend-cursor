# BE prompt — Pompeiana behind the WillpowerLab login, synced across devices

Companion: `docs/PROMPT-FE-pompeiana-cross-device-login.md`.

**Goal (founder, 2026-07-27):** Pompeiana (the 54-day Pompeian rosary novena
PWA) sits behind the WillpowerLab login, on its own domain for now. Any
WillpowerLab user can use it. Novena progress is saved server-side and follows
the user across devices.

> **Two caveats on this document.** (1) Nobody has read the Pompeiana repo
> while writing it — repo access was declined, so every statement about that
> codebase comes from the founder's own description and must be checked against
> the files before you trust it. (2) **Nothing here is built yet.** This is the
> plan, not a changelog.

**This document lives in the willab backend repo for one reason:** the Supabase
project is willab infrastructure. The schema and RLS below run against the
*same* project that backs the ideal-text lane, so the migration and its
policies belong in willab's review path even though the app consuming them is
a different product.

---

## 0. Decision filter (CLAUDE.md §🛂)

```
VERDICT:  DEFER — proceed as scoped, but it never enters the F1 critical path
CATEGORY: DRIFT relative to F1/F2
WHY:      A prayer-app login on a separate domain serves no F1 or F2 piece:
          it does not touch per-slide transcription, best-per-slide ranking,
          or the F2 shadow loop. It passes as a scoped, self-contained
          product only because — as designed below — it costs the willab
          backend ZERO code changes. There is no contention to resolve
          because there is nothing to contend with.
REDIRECT: The moment this wants an endpoint, a service, or a route in THIS
          backend, that is real drift and the answer is no — it belongs in
          Pompeiana's own repo against shared Supabase. See BE-3, which is
          written as a fence, not a task.
```

**Fence check passes**: no scores or verdicts surface to a user (AC-9 is not
even in play — there is nothing scored here), the charisma construct is
untouched, coach labels are untouched, and the live record→transcribe→coach→
read loop is not modified. Nothing in this plan reads or writes a willab table.

---

## The architecture in one paragraph

WillpowerLab does not own identity — **Supabase does**. `POST /auth/login`
(`routes/auth.py:181`) is a passthrough to `supabase.auth.sign_in_with_password`
returning Supabase's own access + refresh tokens, and `verify_supabase_token`
(`auth.py:93`) validates against `{SUPABASE_URL}/auth/v1/.well-known/jwks.json`
with issuer `{SUPABASE_URL}/auth/v1` and audience `authenticated`. So "log in
through WillpowerLab" means "log in against the same Supabase project."
Pompeiana points at that project, gets the same accounts for free, and stores
its state in the same Postgres keyed on the JWT's `sub`. No user table, no
account linking, no sync service.

---

## BE-1 — the state table (the whole backend, essentially)

One migration against the shared Supabase project. **Idempotent** (`IF NOT
EXISTS`), never drops anything — standing constraint.

```sql
create table if not exists pompeiana_state (
  user_id    uuid primary key references auth.users(id) on delete cascade,
  state      jsonb       not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);

alter table pompeiana_state enable row level security;
```

`user_id` as the **primary key** is deliberate: one row per user makes the
client's upsert (`Prefer: resolution=merge-duplicates`) a one-liner and makes
"two devices racing" a single-row conflict rather than a duplicate-row mess.

### Policies — not optional, and the reason is specific

Pompeiana shares a database with willab. A table here without RLS is readable
by **every logged-in willab user**, using nothing but the public anon key.

```sql
create policy "pompeiana own row select" on pompeiana_state
  for select using (auth.uid() = user_id);

create policy "pompeiana own row insert" on pompeiana_state
  for insert with check (auth.uid() = user_id);

create policy "pompeiana own row update" on pompeiana_state
  for update using (auth.uid() = user_id) with check (auth.uid() = user_id);
```

No delete policy on purpose — a novena's progress should not be deletable by
the client. If "start over" needs to wipe it, that is an UPDATE to a fresh
`runId`, not a DELETE.

**Default `user_id`.** Either give the column
`default auth.uid()` so the client never sends it, or have the client send it
explicitly from the JWT. Pick one and make the FE prompt match — a mismatch
here shows up as a confusing RLS rejection, not a clear error.

Cross-check against `docs/RLS-AUDIT.md` and apply whatever standard the
existing willab tables use; this table must not be the weakest one in the
project.

## BE-2 — the scripture table — **BLOCKED on Q1**

Pompeiana ships scripture *references* only; the user pastes their own
translation, stored locally per mystery per language. If that must follow the
user across devices too, it does **not** belong in the `state` blob: 20
mysteries × 10 languages of pasted prose in a single jsonb row that gets
rewritten on every bead tap is a bad shape — write amplification on the hot
path, and one oversized row.

If Q1 comes back "yes", it is its own table:

```sql
create table if not exists pompeiana_scripture (
  user_id     uuid not null references auth.users(id) on delete cascade,
  mystery_id  text not null,
  language    text not null,
  text        text not null,
  updated_at  timestamptz not null default now(),
  primary key (user_id, mystery_id, language)
);
-- same three own-row policies as BE-1
```

Written rarely, read once at boot — the opposite access pattern from `state`,
which is exactly why it is a separate table.

## BE-3 — what must NOT change in this backend (fence, not a task)

- **No new route, blueprint, service or model in `routes/` or `services/`.**
  Pompeiana talks to Supabase directly (PostgREST + `/auth/v1`). If someone
  proposes a `/v2/pompeiana/...` endpoint, that is the drift the filter above
  rejects.
- **No change to `auth.py` or `routes/auth.py`.** They already do the right
  thing; Pompeiana reuses the same issuer and JWKS without knowing they exist.
- **No willab table gains a Pompeiana column.**
- **The service-role key never leaves the server.** `SUPABASE_SERVICE_ROLE_KEY`
  bypasses RLS entirely. Pompeiana is a static PWA with no server — it gets the
  **anon** key only, and every guarantee above rests on that.

## BE-4 — the handoff allowlist — only with Option B (see the FE prompt)

If the founder takes the redirect flow rather than a second login screen, the
only backend-adjacent artifact is an **exact-match allowlist of redirect
origins**, and it belongs wherever the WillpowerLab *frontend* reads config —
not here. Requirements, wherever it lands:

- exact origin match (`https://pompeiana.example` — not a prefix, not a regex,
  not `endsWith`);
- tokens travel in the **URL fragment**, never the query string (fragments are
  not sent to servers and never reach access logs);
- no wildcard, no user-supplied origin echoed back.

An allowlist bug here is a session-stealing open redirect against every
WillpowerLab account, which is a materially worse failure than anything else in
this document.

---

## Verification

1. Migration applied, `select * from pg_policies where tablename =
   'pompeiana_state'` returns the three policies.
2. **The RLS proof, and do not skip it:** with two real accounts, user A's
   anon-key request for `pompeiana_state` returns exactly A's row and never
   B's. A policy that is present but wrong looks identical to a correct one
   until you test it with a second user.
3. A request with **no** `Authorization` header returns zero rows, not the
   table.
4. `curl` the willab health/config surface and confirm nothing changed — this
   work should be invisible to the F1 backend.

## Open questions

**Q1 — gates BE-2.** Should the user's pasted scripture text sync across
devices, or stay local to each device? Changes whether BE-2 exists at all.

**Q2 — gates the FE's session model.** Is login a **hard gate** (no login, no
app) or **optional** (app works anonymously as today; login adds cross-device
sync)? The founder said "behind the login", which reads as a hard gate — but
see the offline-lockout warning in the FE prompt before confirming, because a
hard gate has a real failure mode in a church basement.

**Q3.** What is the Pompeiana domain? Needed for the CORS/allowlist entries.

**Q4.** Do existing Pompeiana users already have `pompeiana.v1` state in
localStorage that must survive first login? If yes, first-login merge is a
real task and belongs in the FE prompt, not an afterthought.
