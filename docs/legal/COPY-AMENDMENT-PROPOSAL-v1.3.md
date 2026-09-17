# Proposed copy amendments — Privacy v1.3 / Terms v1.3

**Status:** ⛔ **HELD FOR FOUNDER SIGN-OFF.** User-facing copy is fenced under
LIVE LOOP. Nothing here is applied to the live pages.
**Prepared:** 2026-09-17 · **Files:** `frontend-cursor/src/app/privacy/page.tsx`, `frontend-cursor/src/app/terms/page.tsx`
**Driver:** DPIA RISK-1 and RISK-2

---

## Amendment 1 — the false sentence (DPIA RISK-2) 🔴

Appears **twice**, identically, in Privacy §6 and Terms §7:

> ❌ "This inference is opt-in and off by default."

**Why it must go.** `services/voice_confidence.py:177` defaults
`VOICE_CONFIDENCE_ENABLED` to `"1"` — on. It is an environment variable, not a
per-user consent flag; no per-user opt-in for this inference exists. What
defaults off is `VOICE_CONFIDENCE_RANKING_ENABLED` (`:169`), which controls
whether the composite enters ranking — a different question.

It also contradicts §3 and §5 of the same policy, which say the consent covering
the inference is **required** to use the service. It cannot be both mandatory and
opt-in.

Art 5(1)(a) fairness and transparency, and Art 13 accuracy.

### Option A — amend the copy to describe reality *(recommended)*

> ✅ **Privacy §6, replacing the sentence:**
>
> "This analysis runs on every take. It is part of how the coaching works, and it
> is described in §3 as part of the service you sign up for. If you would rather
> it did not run, you can stop recording at any time or close your account; we
> cannot provide coaching without it."

> ✅ **Terms §7, replacing the sentence:**
>
> "The Service analyses how you delivered each take — pace, pauses, pitch range
> and loudness — in order to choose what feedback to give you. This runs on every
> recording. See the Privacy Policy for what is measured and on what legal basis."

**Cost:** none in engineering. Honest, and consistent with re-basing recording on
Art 6(1)(b) under the split consent.

### Option B — build the flag and keep the promise
Add a per-user flag, default off, and gate computation on it. Truthful, but it
means the coaching quality differs between users who enable it and users who do
not — and since the inference selects feedback evidence, a user who declines gets
a materially worse product while still paying. That is arguably a worse outcome
for the user than Option A.

**Recommendation: Option A.** Take the honest sentence; keep one product.

---

## Amendment 2 — split the consent in the policy (DPIA RISK-1) 🔴

Privacy §3 currently reads, in substance: explicit consent under Art 6(1)(a) for
recording, personalised coaching **and** pooled model improvement, "accepted
together and required to use recording and coaching."

> ✅ **Privacy §3, replacing the Article 6(1)(a) paragraph:**
>
> "**Performance of a contract (Article 6(1)(b)).** Recording your voice,
> transcribing it, analysing how you delivered it, and generating your coaching
> and Ideal Text is the service itself. We rely on our contract with you for
> this, not on consent — because it is not genuinely optional, and presenting it
> as a choice would be misleading.
>
> **Consent (Article 6(1)(a)).** We rely on your separate, optional consent for:
> using your practice data to improve WillpowerLab's shared models (§5); sharing
> your extracts with other users (§7); and human coach review (§8). **Each is a
> separate choice. Refusing any of them does not reduce your access to recording,
> coaching, Ideal Text or feedback.** You may withdraw any of them at any time in
> Account → Data & consent (§11).
>
> **Special categories (Article 9).** Where special-category data within the
> meaning of Article 9(1) is processed — most likely because of something you
> happen to say in a practice presentation — we rely on your explicit consent
> under Article 9(2)(a)."

> ✅ **Privacy §5, replacing the withdrawal paragraph:**
>
> "This is optional and separate from the coaching service. You may say no when
> you sign up, or withdraw later in Account → Data & consent, **and you keep full
> access to recording and coaching either way.** When you withdraw we stop
> including your data in new training from that moment."

> ✅ **Delete from §5:** "Because the bundled consent is required for both
> connected purposes, withdrawal ends access to recording and coaching."
>
> ✅ **Delete from §11:** "Withdrawing the bundled consent ends recording and
> coaching access."
>
> These two sentences *are* the Art 7(4) conditionality problem, stated in the
> controller's own words. They are the most quotable lines in the document from a
> regulator's point of view.

---

## Amendment 3 — restore the model-improvement opt-out (closes L-1) 🟠

Backlog L-1 records that the opt-out claim was **removed** from both documents
rather than published false, and is ⛔ BLOCKING the next revision.

Once the `model_improvement_consent` flag ships, restore it — as a statement of
fact this time:

> ✅ **Privacy §5 and §11, and Terms §4:**
>
> "You can stop your content being used to improve our models at any time, in
> Account → Data & consent, without giving up the Service."

**Do not publish this sentence until the flag and its filtering exist.** Publishing
ahead of the code is precisely what created Epic L.

---

## Amendment 4 — smaller corrections 🟡

| § | Current | Change | Why |
|---|---|---|---|
| Privacy §10 | Voice Data retained "while the required consent remains active" | State the actual criterion: **retained for the life of the account and deleted on account closure** | Founder decision 2026-09-17. Art 13(2)(a) requires the real criterion |
| Privacy §9 | Asserts DPA + safeguard for all eight sub-processors | Hold until L-6 verifies each | An unsigned DPA makes the published policy false |
| Privacy §5 | Asserts OpenAI zero data retention | Hold until written confirmation | ZDR is not a default; it needs an approved per-org application |
| Terms §7 | "must not be used by employers or educational institutions" | **Keep, strengthen, and back with technical controls** | This is the AI Act Art 5(1)(f) fence. Contract alone does not discharge it |
| Privacy §1 | "Given the small scale of processing, we are not required to... appoint a DPO" | Add: "We review this as the Service grows." | The conclusion is scale-dependent and will flip |

---

## Amendment 5 — Art 50(3) AI transparency 🟡

If counsel confirms the system is an emotion recognition system but not
prohibited, AI Act Art 50(3) requires that people exposed to it be **informed of
its operation**. Privacy §6 substantially does this already, and the AI notice
receipt path in `routes/v2/processing_authorization.py` records delivery.

Hold pending counsel's answer — the wording depends on the scoping outcome, and
drafting it now risks writing an admission we may not need to make.

---

## Version and notice obligations

- Both documents move to **v1.3**; Privacy §14 and Terms §16 require notice of
  material change, and this is material.
- `user_consents` is the ledger that answers who is owed notice (backlog L-8).
- Every prior accepted version must remain recoverable — the ledger proves which
  users accepted which text.

---

## Sign-off

| Amendment | Risk | Recommendation | Founder |
|---|---|---|---|
| 1 — false "opt-in" sentence | 🔴 RISK-2 | Option A | ☐ |
| 2 — split the consent in copy | 🔴 RISK-1 | Adopt | ☐ |
| 3 — restore opt-out claim | 🟠 L-1 | Adopt **after** flag ships | ☐ |
| 4 — smaller corrections | 🟡 | Adopt; hold §9/§5 assertions | ☐ |
| 5 — Art 50(3) notice | 🟡 | Hold for counsel | ☐ |
