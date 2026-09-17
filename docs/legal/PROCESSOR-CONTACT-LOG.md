# Processor contact log — OpenAI settings-change history

**Purpose.** A dated record of every attempt to obtain, from OpenAI, the date
its data-sharing / model-improvement settings were enabled and disabled on our
organisation.

**Why this file exists rather than a commit message.** If the date is never
obtained, this log *is* the answer to counsel question **Q-C** in
`legal/phase1-2026.1/09-counsel-cover-note.md`: what a reasonable investigation
looks like when a start date cannot be established. Under Art 5(2) the
controller must be able to *demonstrate* compliance, and a documented record of
having asked — repeatedly, through the correct channel, with the correct legal
basis cited — is what demonstrates it. An absence of evidence is worth nothing;
evidence of diligent asking is worth a great deal.

**And it is a finding about the processor.** An unanswered Art 28(3)(h) request
is a fact about OpenAI's performance of its own obligations, not about ours.
Counsel will want it on the record either way, and it belongs in the
sub-processor assessment (DPIA RISK-8) as well as in RISK-10.

> **Keep this current.** Add a row on every attempt and every reply, including
> replies that answer nothing. An autoresponder is a data point: it establishes
> that the channel was tried and what it returned.

---

## The request

The settings-change history of our own organisation is **information necessary
to demonstrate compliance with Art 28**, which Art 28(3)(h) obliges the
processor to make available. It is not a support question and not a favour, and
the log records which framing was used each time — because the two go to
different queues and have produced different outcomes.

## Attempts

| # | Date | Channel | Framed as | Asked for | Outcome |
|---|---|---|---|---|---|
| 1 | 2026-09-17 | `privacy@openai.com` | Support / general privacy enquiry | DPA execution route, EU contracting entity, retention period, sub-processor list | **Consumer autoresponder.** No human reply. Nothing answered |
| 2 | *pending* | `privacy@openai.com` + `dsar@openai.com` | **Controller request under Art 28(3)(h)** — subject line says so explicitly | Settings-change timestamps and actor; whether content was used for training; consequences for content already incorporated | *awaiting send by the account owner* |

**Attempt 1 is itself informative.** The published privacy address routed a
controller enquiry to a consumer autoresponder. That is relevant to whether the
processor has made an effective channel available under Art 28(3)(h), and it is
the reason attempt 2 changes both the framing and the address set.

## Independent evidence, pursued in parallel

Not every route runs through the processor. Recorded here so the investigation
is visibly more than one email:

| Source | What it would establish | Status |
|---|---|---|
| **Billing → Usage / Credits**, date the complimentary daily token grant first appears | A **proxy** for the sharing-enabled date: the credits were the consideration for enabling sharing, so the grant's first appearance brackets it | **Obtainable from our own account without any reply.** Not yet captured |
| OpenAI organisation audit log | Authoritative timestamps | **Unavailable for the period** — audit logging was not enabled at the time. Enabled 2026-09-17 |
| Local application logs | Any record of the setting | None. The setting is account-level, not application-level |

### ⚠️ The billing date is a proxy, and must be labelled as one

It is evidence of when the *credits* appeared, not of when the *toggle* moved.
It may predate the toggle (credits offered, accepted later) or postdate it
(setting enabled first, credits granted on the next cycle).

**It must not be written into the DPIA, the cover note, or any document sent to
counsel as the settings-change date.** Where it is recorded at all, it is
recorded as "billing-derived proxy, ±one billing cycle, source: screenshot
dated <date>". The distinction between a known date and a bracketed estimate is
exactly the kind of thing that, if blurred once in an internal document, gets
repeated as fact in an external one.

---

## Template — Art 28(3)(h) request

Sent by the **account owner**, from the account owner's address. Not from an
engineer: a processor obligation runs to the controller, and a request that
arrives from a non-owner address is easy to route back to support.

**To:** `privacy@openai.com`, `dsar@openai.com`
**Subject:** `Controller request under Article 28(3)(h) GDPR — not a support question`

```
We are a data controller using the OpenAI API as processor under your
DPA. We are conducting a personal data breach assessment under Article 33
and require, as information necessary to demonstrate compliance under
Article 28(3)(h):

1. The date and time each data-sharing / model-improvement setting on
   organisation [ORG ID] was enabled and disabled, and by which account.
2. Confirmation of whether content submitted by this organisation was in
   fact used for model training during that period.
3. If it was, what that means for content already incorporated, and what
   you can tell us about deletion or exclusion.

We are not asking for a policy explanation. We are asking for records
about our own organisation, which we need to assess a possible breach
affecting EU data subjects and to meet our own Article 33 duty.

Please confirm receipt within 72 hours.
```

**Before sending:** replace `[ORG ID]` with the organisation identifier from
the OpenAI dashboard. It is the only placeholder.

**After sending:** add the row to the table above with the date, and set a
reminder for 72 hours. If no receipt confirmation arrives, that silence is
itself the next row — record it rather than only recording replies.
