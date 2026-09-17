# WillpowerLab — instruction pack for Polish/EU counsel
**17 September 2026**

Eleven documents. **Start with `01-determinations/02-power-score-classification`
§7 and §9** — that is the question everything else waits on.

---

## What WillpowerLab is, in four lines

A free consumer speech-coaching web app. A user records themselves rehearsing a
presentation; a speech model transcribes it; a language model writes a
presentation document and feedback; the user records again. Operated by **Artur
Willoński as a natural person** in Poland (unregistered business activity — no
company), serving **Poland only**, with **no payment of any kind**.

## What we are asking for

1. **The determination at `02-power-score-classification` §9.** Is our
   voice-confidence component an emotion recognition system under AI Act
   Art 3(39)? §7 sets out both sides; §9 is deliberately left blank.
2. **Review and signature of `01-product-legal-approval` and
   `03-article-50-assessment`.**
3. **Adoption advice on the DPIA and the Article 30 record.**
4. **Answers to the triage question below.**

Each signed document becomes an immutable, fingerprinted database record. Once
registered it can only be superseded by a new version, never edited — please
draft with that in mind.

## 🔴 Read this before anything else

On 17 September 2026 we discovered that **all three data-sharing settings on
our OpenAI organisation were enabled**, including *"Share inputs and outputs
with OpenAI… including for improving and training our models"*. They had been
accepted in exchange for complimentary daily API tokens.

At the same time, our published Privacy Policy told users we **do not**
provide their content to third parties to train general-purpose or
foundation models.

### The scope, as far as we can currently establish it

| | |
|---|---|
| Audio recordings held | 1,708 |
| Distinct users with audio | 25 |
| Oldest recording | 8 May 2026 |
| Most recent | 17 September 2026 |
| Recordings carrying a delivery-signal value | 590, across 4 users |

**This is not a pre-launch defect.** Real users' voice recordings have
existed continuously for over four months, and the service was still
recording on the day of discovery.

### What we cannot yet establish

**We do not know when the sharing settings were enabled**, and therefore
cannot bound how much of that four-month window is affected. Audit logging
was not enabled at the time. We have asked OpenAI whether their own records
can supply the date. Until they answer, the window is "up to four months"
and we are not able to narrow it ourselves.

**We also cannot yet state our user count with confidence.** Our settings
table holds 7 rows while 25 distinct user identifiers have audio. We are
resolving that discrepancy and will send the figure; please do not rely on
either number in the meantime.

### What we have done

All three settings are off. The organisation is locked down further than it
started — no hosted tools, no API call logging — and **audit logging is now
enabled**, which it was not before. The privacy copy is being corrected.

Two limits we state rather than have you find:

1. **Disabling is forward-only.** Anything already shared cannot be recalled.
2. **The start date may not be recoverable**, for the reason above.

### What we need from you, in this order

- **Q-A.** Is this a personal data breach under Art 4(12), and is it
  notifiable to UODO under Art 33 and/or to data subjects under Art 34?
- **Q-B.** What is our position on processing that had no lawful basis for
  that purpose, and on a privacy notice that was inaccurate for the period
  concerned (Art 5(1)(a), Art 13)?
- **Q-C.** If we cannot establish the start date, what does a reasonable
  investigation look like, what should we record, and what may we say to
  users about a window we cannot bound?
- **Q-D.** Our published page now states, accurately, that we do not share
  for training. Should it say anything about the period in which that
  statement was untrue? Silently making a false statement true is not the
  same act as disclosing that it was false, and we would rather be told
  which is required than choose.

We are treating this as the most urgent item in this pack.

## ⚠️ And the earlier triage item — read against the same figures

Our published v1.2 terms rely on a **bundled consent**: users had to agree that
their practice data could be used to train models shared with other users, as a
condition of using the service at all. We assess that as invalid under Art 4(11)
and Art 7(4) with Recital 43, and — because the bundle was invalid — consent
arguably failed for **both** purposes, including the recording itself, for which
v1.2 expressly declined to rely on Art 6(1)(b). That collateral effect is the
part we would most like checked: it is easy to read this as a training-data
problem when the more serious consequence is that it removes the basis for the
recording.

`01-product-legal-approval` §3 proposes re-basing the core operations on
Art 6(1)(b) contract.

**⚠️ We do not yet know how many users accepted under v1.2. The figure is being
verified and is not in this pack.** We are telling you rather than estimating,
because it changes what you are being asked:

**We do not yet know how many users accepted under v1.2.** A query is
outstanding. What we do know is that the product is not pre-launch: 25 users
have audio going back to May. Please assume the acceptance count is non-zero
unless we tell you otherwise, and tell us what remediation that requires.

## Two things we corrected before writing to you

Stated so you are not the one to find them.

1. **Our published pages said the voice inference was "opt-in and off by
   default". It was not** — it runs by default for every recording. Corrected on
   the live site today.
2. **Our published pages asserted OpenAI "zero data retention"** in three
   places, including as a security measure. ZDR is a per-organisation approved
   application, not a default, and we have not applied. Corrected today; the
   accurate retention period is still being confirmed with OpenAI.

## One disclosure that bears on the determination

The five internal labels for the confidence output were `confident`,
`close_to_confident`, `neutral`, `unconfident`, `doubtful`. **On 17 September
2026, after this question was raised, they were renamed** to neutral
delivery-signal terms and the module documentation was rewritten.

The change is internal, alters no computed value, and is disclosed rather than
presented as pre-existing. It removes a contradiction between our framing and our
vocabulary. **It does not answer the question** — the composite is still z-scored
against each speaker's own baseline, which is the strongest argument *against*
our position and is untouched by any rename.

## What we are NOT asking

- **US law.** We serve Poland only. A separate US brief exists and is parked
  until we incorporate.
- **"How do we achieve full compliance."** We are a sole operator with no
  company and no revenue. If the high-risk regime is engaged, *remove or
  redesign the feature* is a realistic answer and we would rather hear it than a
  compliance programme we cannot staff.

## Please note about authorship

These documents were drafted by our engineering side with AI assistance, working
directly from the source code. The technical sections are verifiable line by line
against the repository and we can give you access. **Nothing here is legal advice
and nothing has been reviewed by a lawyer** — that is what we are asking you for.

## Contents

| | |
|---|---|
| `01-determinations/01-product-legal-approval` | Lawful basis for each operation on a recording. Needs your signature. |
| `01-determinations/02-power-score-classification` | **The AI Act question.** §7 both sides, §9 blank for you. |
| `01-determinations/03-article-50-assessment` | Transparency assessment. Names five gaps, two unmet. Needs your signature. |
| `01-determinations/06-retention-schedule` | Retention and destruction periods. |
| `02-assessments/AI-ACT-SCOPING-MEMO` | The same AI Act question as a letter, with four numbered questions at §6. |
| `02-assessments/DPIA-2026-09-17` | Art 35 assessment. Nine risks, six open questions. |
| `02-assessments/ROPA-ART30` | Art 30 record. Thirteen activities. |
| `03-user-facing-copy/*.txt` | Terms, Privacy, AI notice and the consent screen, as drafted to replace v1.2. Plain text because the exact bytes are hashed. |

Contact: Artur Willoński · contact@willpowerlab.com
