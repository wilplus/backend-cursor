# 09 — Data subject rights readiness

**Status: I could not currently serve most of these requests within the statutory
period.** That is the finding.

---

## 1. Current position

| Right | Route today | Status |
|---|---|---|
| **Access (Art 15)** | Manual assembly across ~69 tables plus object storage | ⛔ No export exists |
| Rectification (Art 16) | Manual; transcript editing is self-service | 🟡 Partial |
| **Erasure (Art 17)** | Manual | ⛔ **No deletion route exists** |
| Restriction (Art 18) | Manual | ⛔ |
| **Portability (Art 20)** | Manual | ⛔ No structured export |
| Object (Art 21) | By email | 🟡 Partial |
| Withdraw consent (Art 7(3)) | Account surface | 🟡 No model-improvement flag exists |

**A trap worth naming:** the system has an endpoint called
`/v2/processing-authorization/data-export`. It exports **authorisation
evidence** — records of which processing permissions were granted — **not the
subject's personal data.** It does not discharge Art 15 or Art 20, and I flag it
so that nobody reading the codebase mistakes it for compliance.

---

## 2. Why this matters more than its severity rating suggests

My published policy promises a response within one month, per Art 12(3). With no
export and no deletion route, every request is a manual operation across the full
schema plus stored audio objects.

For a sole operator, **a single erasure request that I fail to complete within
the month is the most realistic route to a UODO complaint** — more likely than any
of the structural issues in Documents 02 and 03. It requires no regulator
initiative and no sophistication from the complainant.

There is a compounding problem with Document 10: **I have elected life-of-account
retention for audio. That makes the deletion route the retention policy.**
Without it there is no storage limit at all, only an intention.

---

## 3. What I am building

- `GET /v2/account/export` — structured machine-readable archive: account,
  recordings, transcripts, Ideal Text versions, derived measurements, ratings
  given, consent history.
- `DELETE /v2/account` — hard deletion across all tables **and stored audio
  objects**, preserving only what law requires (billing records under Polish
  accounting and tax law), with the deletion itself logged for Art 5(2).

**One design question I would value a view on.** Where a user has given a blind
peer rating of *another* user's extract, that judgement is personal data about
the rater, but it is attached to a third party's recording and has contributed to
calibration. My intention is to **sever the link to the rater and retain the
judgement in anonymised form** rather than delete it.

---

## 4. Questions

> **Q9.1** Is severing the link and retaining an anonymised peer rating adequate
> under Art 17, or must the judgement itself be deleted?
>
> **Q9.2** My published policy says that where a contribution has already been
> incorporated into a trained model, the model is not retrained solely on that
> basis. Is that position defensible under Art 17, given that it is disclosed in
> advance?
>
> **Q9.3** Until the routes ship, is a documented manual procedure sufficient to
> meet Art 12(3), or does the absence of technical means create exposure in itself?
>
> **Q9.4** Anything specific under the Polish Act of 10 May 2018 that differs
> from the GDPR baseline here?
