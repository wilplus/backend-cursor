# BE prompt — Pompeiana behind the WillpowerLab login, synced across devices

Companion: `docs/PROMPT-FE-pompeiana-cross-device-login.md`.

**Goal (founder, 2026-07-27):** Pompeiana (the 54-day Pompeian rosary novena
PWA) sits behind the WillpowerLab login, on its own domain for now. Any
WillpowerLab user can use it. Novena progress is saved server-side and follows
the user across devices.

> **STATUS 2026-07-27 — BE-1 and BE-2 are IMPLEMENTED and verified** in
> `migrations/add_pompeiana_sync.sql`. Founder answers folded in: **hard login
> gate**, **scripture syncs too** (so BE-2 is in, not blocked), **Option A
> first** (so BE-4 is not needed yet). One thing this plan got wrong is
> recorded in §5 — read it, because it is the failure mode that ships silently.
>
> **Caveat that still stands:** nobody has read the Pompeiana repo — access was
> declined — so every statement about *that* codebase comes from the founder's
> description and must be checked against the files. The migration below does
> not depend on any of it.

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
  user_id    uuid primary key references auth.users(id) on delete cascade
             default auth.uid(),
  state      jsonb       not null default '{}'::jsonb,
  updated_at timestamptz not null default now()
);

alter table pompeiana_state enable row level security;

-- REQUIRED, and separate from the policies below — see §5. Without this,
-- every request fails "permission denied for table".
grant select, insert, update on pompeiana_state to authenticated;
revoke all on pompeiana_state from anon;   -- the hard login gate
```

**The shipped version is `migrations/add_pompeiana_sync.sql`** — read that, not
this excerpt, before changing anything.

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

**Default `user_id` — decided:** the column carries `default auth.uid()`, so
the client **omits** it on insert and the database fills it from the JWT. The
FE prompt says the same. (Sending it explicitly also works; sending someone
else's is rejected by the insert policy, as verified in §6 test 5.)

Cross-check against `docs/RLS-AUDIT.md` and apply whatever standard the
existing willab tables use; this table must not be the weakest one in the
project.

## BE-2 — the scripture table — **DONE** (founder: yes, it syncs)

Pompeiana ships scripture *references* only; the user pastes their own
translation, stored locally per mystery per language. The founder confirmed
(2026-07-27) that this syncs across devices too.

It gets its **own table**, not a key in the `state` blob: 20 mysteries × 10
languages of pasted prose inside a jsonb row that is rewritten on every bead
tap means write amplification on the hot path and one row growing without
bound. Written rarely, read once at boot — the opposite access pattern from
progress, which is the whole reason it is separate.

```sql
create table if not exists pompeiana_scripture (
  user_id     uuid not null references auth.users(id) on delete cascade
              default auth.uid(),
  mystery_id  text not null,
  language    text not null,
  text        text not null,
  updated_at  timestamptz not null default now(),
  primary key (user_id, mystery_id, language)
);

alter table pompeiana_scripture enable row level security;
grant select, insert, update on pompeiana_scripture to authenticated;
revoke all on pompeiana_scripture from anon;
-- plus the same three own-row policies as BE-1
```

Conflict rule differs from progress, deliberately: this is free text a user
typed, not monotonic progress, so **last-write-wins per (mystery, language)**
is correct. The FE-3 furthest-progress rule must not be applied to it.

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

---

## 5. What this plan got wrong (found by testing, not by reading)

**GRANTs are separate from RLS, and the plan had only RLS.** The original
draft created both tables with policies and no grants. That is not a subtle
degradation — **every single PostgREST request fails with `permission denied
for table`**, because a policy filters which *rows* a role may touch and grants
nothing about the *table*. Verified against a real Postgres 16: with policies
alone, all ten behaviour tests failed identically.

The migration now carries:

```sql
GRANT SELECT, INSERT, UPDATE ON <table> TO authenticated;
REVOKE ALL ON <table> FROM anon;
```

Supabase's default privileges often paper over this, which is worse than it
sounds — it means the bug appears only when the defaults have been changed or
the migration is run by a different role, i.e. in exactly the environment
nobody tested. Stating the privileges explicitly removes the dependency.

`anon` getting **nothing** is the founder's hard login gate enforced at the
database, not just in the UI. No `DELETE` grant to anyone, matching the
no-delete-policy decision.

---

## 6. Verification — actually run, not asserted

A throwaway Postgres 16 with a minimal Supabase shim (`auth` schema,
`auth.users`, `auth.uid()` reading the JWT sub, and the `anon`/`authenticated`
roles). **The role must really switch** — `SET LOCAL` outside a transaction is
a silent no-op, and the first run of these tests passed everything while
actually executing as the table owner, which bypasses RLS entirely. Every test
below runs inside `BEGIN … COMMIT` with `current_user` asserted first.

| # | Check | Result |
|---|---|---|
| 0 | role really switches to `authenticated`, `auth.uid()` resolves | ✅ |
| 1 | A inserts with `user_id` **omitted** → `DEFAULT auth.uid()` fills it | ✅ |
| 3 | **A selects → exactly one row, A's own** | ✅ |
| 4 | A updates B's row → `UPDATE 0` | ✅ |
| 5 | A inserts a row owned by B → RLS violation | ✅ rejected |
| 6 | anonymous, no JWT → `permission denied` | ✅ (hard gate) |
| 7 | upsert `on conflict (user_id)` → state advances 3 → 4 | ✅ |
| 8 | scripture: A sees its 2 rows, never B's | ✅ |
| 9 | A cannot DELETE its own progress | ✅ denied |
| 10 | deleting the `auth.users` row cascades both tables to 0 | ✅ |

Re-running the migration is clean (`IF NOT EXISTS` + the DO-block policy
guards) and **existing rows survive** — confirmed by counting before and after.

**Still to do in the real project:** run it there and repeat tests 3 and 6 with
two genuine accounts. A policy that is present but wrong looks identical to a
correct one until a second real user tries it.

## Open questions

**Q3.** What is the Pompeiana domain? Needed for CORS. (Not needed for the
migration — it is already applied and domain-independent.)

**Q4 — gates an FE task.** Do existing Pompeiana users already have
`pompeiana.v1` state in localStorage that must survive first login? If yes,
first-login merge is real work and belongs in the FE prompt.

**Answered 2026-07-27:** ~~Q1~~ scripture syncs → BE-2 shipped. ~~Q2~~ hard
login gate → `anon` revoked at the database. ~~Q5~~ Option A first → no
handoff allowlist needed yet (BE-4 stays unbuilt).
