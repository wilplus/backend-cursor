# 00 — Read this first

**WillpowerLab — instruction pack for counsel** · 17 September 2026
Artur Willoński, sole trader (*działalność nieewidencjonowana*), Poland
contact@willpowerlab.com

---

## What this is

A consumer speech-coaching web application. A user records themselves
presenting; the system transcribes the audio, segments it per slide, and returns
written coaching. It is live, it is small, and I operate it alone.

I need **one determination** and **one urgent triage**. Everything else in this
pack is supporting material you may not need to open.

---

## The determination — Document 02

**Is one component of my product an "emotion recognition system" under AI Act
Art 3(39)?**

The component reads seven acoustic features — pitch range, loudness range, mean
pitch, speech rate, pausing, terminal contour, energy contour — and produces a
single value placing a moment on a spectrum from *doubtful* to *confident*. The
value is never shown to the user.

My concern, in one sentence: **AI Act Art 3(34) defines "biometric data" without
the unique-identification limb that GDPR Art 4(14) requires**, so the reasoning
in my published privacy policy (we do not identify anyone, therefore we are
outside the biometric regime) may be correct for GDPR and wrong for the AI Act.

**Document 02 §7 sets out both sides as I understand them. §9 is left blank for
your determination.** Please complete it. The rest of the pack is downstream:

- If **yes and Art 5(1)(f) is engaged** — prohibited in workplace and education
  contexts. I have live inbound B2B interest and cannot answer it until I know.
- If **yes but not prohibited** — Annex III(1)(c) high-risk. At my scale that
  regime is not survivable, so my realistic options are redesign or removal, not
  conformity. **Please advise on that basis rather than defaulting to full
  compliance.**
- If **no** — most of this pack becomes ordinary GDPR housekeeping.

---

## The triage — Document 03

My published v1.2 terms rely on a **bundled consent**: personalised coaching and
pooled model training accepted together, both required to use the service. I
believe that is invalid under Art 7(4) and Art 4(11) read with Recital 43.

The consequence I want checked is not the training purpose but the collateral
one: **if the bundle is invalid, consent fails for *both* purposes, including the
recording itself** — and my privacy policy §3 expressly declines to rely on
Art 6(1)(b) for recording. That would leave the core operation of the service
without a lawful basis.

⚠️ **Scale of affected users: see Document 03 §2.** I am verifying the figure
from the database and will confirm it to you separately. Please do not size the
urgency from my covering email until I do.

---

## The pack

| # | Document | Read if |
|---|---|---|
| **00** | This note | — |
| **01** | Product and processing description | You want the technical facts before 02 |
| **02** | ⭐ **AI Act Art 3(39) determination** | **Always. This is the instruction** |
| **03** | ⭐ **Bundled consent — Art 7(4) analysis** | **Always. This is the triage** |
| 04 | Draft DPIA (Art 35) | You are asked to review it, or want the risk picture |
| 05 | Draft record of processing (Art 30) | You want the full data inventory |
| 06 | Published Terms and Privacy Policy v1.2 | You want what users were actually told |
| 07 | Consent artifacts — in force, and proposed replacement | Reviewing 03 |
| 08 | Sub-processors and international transfers | Reviewing transfers |
| 09 | Data subject rights readiness | Reviewing DSR exposure |
| 10 | Retention position | Reviewing Art 5(1)(e) — includes a decision I took against advice |
| 11 | ⭐ **Consolidated question schedule** | **Your worklist. Every question, one page** |

If you read only three: **00, 02, 11.**

---

## Provenance and what I am not asking you to assume

These documents were drafted by my engineering side with AI assistance, working
from the source code. **Nothing in them has been reviewed by a lawyer and nothing
in them is legal advice** — that is what I am instructing you for.

Specifically:

- **The technical statements in Document 01 are verified against source** and
  carry file and line references. You can rely on them as facts about the system,
  or check them — I can give you repository access.
- **The legal characterisations throughout are my working assumptions.** They are
  stated confidently because vague instructions waste your time, not because they
  are settled. Where I have reasoned my way to a conclusion I have shown the
  reasoning so you can reject it.
- Where I think my own position is weak, I have said so rather than argued past
  it. See 02 §7.2 and 10 §3.

---

## Three things I would rather you tell me now than later

1. **If the answer to 02 is that we are in the high-risk regime, say so plainly
   and tell me the feature has to go.** I would rather remove it than build a
   conformity apparatus I cannot sustain.
2. **If my Art 7(4) analysis in 03 is wrong**, say so — I have a remediation
   half-built on the assumption that it is right, and I would rather stop than
   ship an unnecessary change to live consent flows.
3. **If this pack is the wrong shape for how you work**, tell me and I will
   redo it. It is structured for your convenience, not mine.

---

Artur Willoński
WillpowerLab
