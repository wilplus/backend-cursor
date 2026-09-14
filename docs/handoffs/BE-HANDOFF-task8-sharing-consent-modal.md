# BE handoff — Task 8: data-sharing consent modal at session 2

Status: **Almost entirely FE work. Storage + endpoint already exist. One BE add maybe (probe field), and two product questions to settle before I touch anything.** The "collaboration chat + swiping game" features the consent gates don't exist on BE yet — when they do, gating them on `share_consent=true` is part of those features' own tasks, not this one.

---

## TL;DR — what the brief assumes vs reality

| Brief premise | Reality |
|---|---|
| "Persist to existing `user_consents` table" | Two storage surfaces exist. `user_consents` is the **immutable GDPR audit ledger** (append-only, timestamped, written at signup). `user_settings.share_consent` (bool \| null) is the **mutable preference** the user can flip from this modal. The shipped `/v2/user/sharing-consent` endpoint writes only to `user_settings.share_consent` — the audit ledger write is open question Q1 below. |
| "If yes → unlock collaboration chat + swiping game" | **Neither feature exists on BE today.** Zero hits across `routes/v2_routes.py` and `services/`. When they ship, those features' tasks own the share_consent gate. This task is just the consent-capture moment. |
| "Add a state flag" | `user_settings.share_consent` returns `null` when not answered, `true`/`false` after. FE has had this since commit `a3279a2` — the "have they answered yet?" check is already trivially `share_consent === null`. No new flag needed unless you want a session-count probe (open question Q2 below). |
| Session-1 ToS covers "personal use" | Pure legal/copy concern. Out of BE scope. Confirm with whoever owns the ToS that the session-1 acceptance language covers personal-use processing of the recording (so this modal is genuinely about the **sharing uplift** and isn't a back-door retroactive consent grab). |

---

## What's already wired (no BE work needed)

### Mutable preference storage + API

| Surface | Endpoint | Shape |
|---|---|---|
| Read | `GET /v2/user/sharing-consent` | `{ has_answered, mic_consent, share_consent, email_consent, terms_consent }` — all booleans-or-null |
| Write | `PUT /v2/user/sharing-consent` | Body: any subset of `{ mic_consent, share_consent, email_consent, terms_consent }`. Returns same shape as GET. |

`share_consent: null` = never answered → modal should fire.
`share_consent: true | false` = answered, modal stays closed.

Storage: `user_settings.share_consent` (boolean nullable) per `migrations/add_consent_flags_to_user_settings.sql`. Per-user, shipped, working.

### GDPR audit ledger

`user_consents` table (per `migrations/add_user_consents_table.sql`). Immutable append-only. `db.insert_user_consent()` exists. Currently written at signup for the initial ToS-acceptance record. **Not** currently written when the share_consent toggle is flipped via `/v2/user/sharing-consent` — that's Q1.

---

## What FE needs to do (the meat of the work)

### The modal flow

1. **Detect "is this session 2 + snippet-review?"** — pure FE state. The user has session 1's results, has just clicked through to review their first snippet. FE knows the route + the click; BE doesn't need to be involved in the trigger timing.

2. **Check whether to show the modal** —
   ```ts
   const consent = await GET /v2/user/sharing-consent;
   if (consent.share_consent === null) {
     // Never answered → show modal
   }
   ```
   Cache it locally for the rest of the session so the modal doesn't pop up twice on a page refresh mid-review.

3. **Modal renders** — "Share your data with the human coach to unlock collaboration features?" Yes/No buttons. Copy is FE's call (or surface another BE-flag if you want it A/B-able — see Q2).

4. **On Yes** —
   ```ts
   await PUT /v2/user/sharing-consent { share_consent: true };
   // Optionally also POST to a new audit-ledger endpoint — see Q1
   // Unlock collaboration chat / swiping game UI affordances
   ```

5. **On No** —
   ```ts
   await PUT /v2/user/sharing-consent { share_consent: false };
   // Skip collaboration UI, route straight to post-session questions
   ```

6. **On dismiss without answering** — pick a stance. Don't write, modal pops up again next visit. Or treat as `false`. Or block the user from advancing. Recommend "don't write, prompt again next visit" — keeps it user-driven, no implicit consent grab.

---

## Two product questions for you

### Q1 — Audit-ledger write on the modal answer?

The `user_consents` table is the immutable proof-of-consent record. Today it's written at signup; the `/v2/user/sharing-consent` PUT only updates the mutable preference. Three options:

| Option | What happens on PUT | GDPR posture |
|---|---|---|
| **A (recommended)** | PUT also appends to `user_consents` with `consent_type='share_snippets'` + the bool + timestamp | Strong audit trail. If a user ever disputes "I never agreed to share," there's a row with their user_id + the timestamp + the boolean. ~10 LOC BE change. |
| **B** | Don't touch `user_consents` on the PUT. Mutable preference only. | Weaker audit. The preference value is what's enforceable, but no point-in-time record of what they clicked when. |
| **C** | Only write to `user_consents` on YES (positive consent), not on NO. | Asymmetric. Defensible legally (the audit is for consent, not refusal) but inconsistent. |

If you pick A, I add the audit write to the PUT handler in ~10 LOC. The PUT response shape doesn't change — the ledger row is a side effect.

### Q2 — "Should I show the modal?" probe field?

Today FE infers it from `share_consent === null` after a `GET /v2/user/sharing-consent`. That's enough for the basic case. Two more sophisticated options exist:

| Option | What | Cost |
|---|---|---|
| **A (recommended)** | Skip — `share_consent === null` is fine, FE computes "is this session 2?" client-side from its own session count. No new BE field. | 0 LOC |
| **B** | Add `needs_share_consent_prompt: bool` to the GET response. BE computes "has user completed session 1 AND share_consent === null". | ~5 LOC. Useful if FE doesn't know the session count locally (e.g. fresh device, lost local state). |
| **C** | Add a full `share_consent_state` block: `{ should_prompt, reason, last_prompted_at }`. Future-proofs against "re-prompt after N months" or "re-prompt if data-sharing policy changed". | ~20 LOC + a new `last_prompted_at` column on `user_settings`. Probably overkill for v1. |

If you pick B, I ship it alongside. If A, no BE work for this part.

---

## Feature-gating note (NOT this task)

The brief says "If yes → unlock collaboration chat + swiping game." Neither feature has an endpoint or service today. **Don't gate them in this task** — those features don't exist to gate. When they ship, each feature's task wires its own `share_consent=true` check at the endpoint level (probably via a `@require_share_consent` decorator I'd add next to `@require_admin`). This task is consent capture only.

---

## Acceptance criteria (when both sides ship)

1. Fresh user finishes session 2 review entry → FE sees `share_consent === null` → modal renders.
2. User clicks "Yes" → PUT 200 with `share_consent: true` → (if Q1=A) row appears in `user_consents` with the timestamp.
3. User refreshes the page → `share_consent === true` → modal does NOT render.
4. User on a different device after consenting → `share_consent === true` returned → modal does NOT render (persistence works cross-device).
5. User clicks "No" → PUT 200 with `share_consent: false` → modal does NOT render again (same suppression).
6. User dismisses without clicking → no PUT fires → next visit modal pops again (per the recommended dismiss stance).

---

## Reply with

Two answers:

1. **Audit-ledger write on PUT** — A (ledger row every time) / B (skip ledger) / C (yes-only)
2. **"Should I prompt?" probe field** — A (skip, FE computes locally) / B (add `needs_share_consent_prompt` boolean) / C (full state block)

If A/A, I ship zero BE LOC. If A/B, ~15 LOC commit. Either way the consent-capture half is done end-to-end and FE wires the modal + flow.
