# 10 — Retention position

**This document records a decision I took against my own engineering side's
advice.** I am not asking you to ratify it. I am asking you to tell me whether it
is defensible, and I would rather hear that it is not.

---

## 1. The position

**Raw audio is retained for the life of the account and purged on account
closure.** No fixed maximum.

Everything else — transcripts, Ideal Text, derived measurements, ratings, labels
— is likewise retained for the life of the account.

---

## 2. What the published policy currently says

Privacy §10 states the Voice Data criterion as:

> *"retained for as long as needed to transcribe and analyse the take, to let you
> play it back, and — while the required consent remains active — for the model
> improvement described in §5."*

**That resolves to "indefinitely", expressed as criteria.** Art 13(2)(a) permits
criteria in place of a period, so I believe the form is permissible — but the
substance is that nothing is ever deleted while the account lives.

An earlier version (v1.0) promised audio was *"automatically deleted no later
than 30 days"*. **That promise was never implemented** — no purge job existed
then and none exists now. It was replaced with criteria in v1.1 rather than
published false.

---

## 3. The advice I received, and why I went the other way

My engineering side recommended a **fixed 90-day maximum** for raw audio, with
transcripts and coaching history surviving so the user's record stayed intact.
The reasoning was Art 5(1)(e) storage limitation, and that an ever-growing store
of every user's voice increases breach severity monotonically with no offsetting
benefit.

**I chose life-of-account instead**, because:

- Playback of earlier takes is a real part of the product — comparing how you
  sounded then against now is much of the value.
- Two planned features (a longitudinal "album" of the user's better moments, and
  comparison across projects) assume nothing ages out.
- At my current scale the absolute volume is small.

**I record the disagreement rather than presenting this as settled**, because
Art 5(2) accountability requires the reasoning to be visible, and because I would
rather you saw the argument I rejected.

---

## 4. What I know is weak about it

- "The user can close their account" is not really a storage limitation answer.
  It puts the limit entirely in the subject's hands.
- The product reasons are **product** reasons. I am aware that is exactly the
  shape of argument Art 5(1)(e) is meant to test.
- It makes deletion (Document 09) load-bearing in a way it would not otherwise
  be: **with no fixed maximum, the deletion route IS the retention policy**, and
  it does not yet exist.
- No purge job exists even for account closure, so at present the stated position
  is an intention rather than a control.

---

## 5. Other retention gaps

| Category | Position | Gap |
|---|---|---|
| Shared peer extracts | Removed from circulation on withdrawal | Per-recording revocation published but unbuilt |
| Usage and diagnostic data | Sub-processor defaults | Never pinned to a period |
| **Retired demographic rows** | "Audit only" | **No deletion date set** — see below |

On the last: the product previously routed some calculations by speaker sex. That
was retired as executable behaviour on 2026-08-29 and the rows were kept for
audit integrity. **They now have no current processing purpose and no end date.**
My understanding is that "audit only" is a legitimate purpose if documented with
a retention period, and is otherwise simply data that was not deleted.

---

## 6. Questions

> **Q10.1** Is life-of-account retention of raw voice recordings defensible under
> Art 5(1)(e)? If not, what maximum would you advise?
>
> **Q10.2** Does Privacy §10's criteria-based formulation satisfy Art 13(2)(a),
> given that the criteria resolve to "indefinitely"?
>
> **Q10.3** Users who accepted v1.0 were told audio would be deleted within 30
> days, and it was not. Is anything owed to them? *(Scale unverified — Document
> 03 §2.)*
>
> **Q10.4** The retired demographic rows: what must I do to retain them lawfully
> for audit, and for how long?
