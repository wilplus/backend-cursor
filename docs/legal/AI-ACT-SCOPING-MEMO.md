# Memorandum to Counsel

**To:** [Counsel] · **From:** Artur Willoński, WillpowerLab (Poland)
**Date:** 17 September 2026
**Subject:** EU AI Act — whether a voice-based delivery-confidence feature is an
"emotion recognition system", and the consequences under Art 5(1)(f) and
Annex III(1)(c)

**Instruction sought:** a written scoping opinion on the four questions in §6.
Estimated scope: one product feature, one jurisdiction, no litigation.

---

## 1. Summary of the instruction

WillpowerLab is a consumer speech-coaching application. A user records a
presentation; the system transcribes it, segments it per slide, and returns
coaching feedback.

One internal component, `voice_confidence`, reads seven acoustic features from
the recording and produces a single number placing the moment on a spectrum from
*doubtful* to *confident*. The number is **never shown to the user** — an
internal product rule forbids surfacing scores — but it is computed, stored, and
(behind a currently-disabled flag) used to rank which moments are selected for
feedback.

**I need to know whether that component is an "emotion recognition system"
within AI Act Art 3(39), and what follows if it is.** The question has become
urgent because we have received **inbound B2B interest**, and Art 5(1)(f)
prohibits emotion recognition in the workplace.

---

## 2. The technical facts (stated precisely, because the answer turns on them)

### 2.1 What is measured

Seven features, each z-scored **against that individual speaker's own historical
baseline**, signed, weighted, summed, and squashed through `tanh` with a neutral
dead zone. Output is a float in [-1.0, +1.0].

| # | Feature | Direction |
|---|---|---|
| 1 | Pitch range (f0 standard deviation) | wider → more confident |
| 2 | Loudness range (dynamic dB) | wider → more confident |
| 3 | Mean pitch | higher → less confident |
| 4 | Speech rate (words per minute) | faster → more confident |
| 5 | Pause ratio | more pausing → less confident |
| 6 | Terminal pitch contour | falling → more confident |
| 7 | Energy contour | decaying → more confident |

Weights are fixed and derived from published literature (Jiang & Pell 2017,
*Speech Communication* 88:106-126). **The composite is not machine-learned.**

### 2.2 What is done with it
- Computed and persisted for every take (default on).
- Feeds a ranking function that selects which moments become coaching feedback —
  **currently disabled by flag**, pending validation.
- Never rendered to the user as a number, band, score, or badge.
- Never shown to the human coach, deliberately, so as not to anchor their
  independent judgement.

### 2.3 A second, separate component
We also operate a **blind shadow model** that learns from human coaches' answers
to the question *"does this delivery sound assured?"* It is machine-learned, it
is not surfaced to anyone, and it exists to measure agreement. I flag it
separately because I assume it is harder to defend than the fixed composite.

### 2.4 Deployment
Business-to-consumer. Individuals practise their own presentations. Our Terms
§7 expressly prohibit use by employers and educational institutions to assess,
monitor, rank or decide about employees, candidates or students, and provide for
account termination. **There is currently no technical control enforcing this —
only the contract term.**

### 2.5 Where each of these statements is in the source

This memo says at the foot that §2 is verified against source. This table is that
verification, so that the claim can be checked rather than taken. Paths are in
`wilplus/backend-cursor` unless marked otherwise; line numbers are as at
2026-09-18 and `tests/test_legal_citations.py` fails the build if any of them
stops resolving.

| Statement in §2 | Where it is |
|---|---|
| The seven features, their directions and their weights | `services/voice_confidence.py:209` — the `_CUES` table. Per-cue direction and the Jiang & Pell reference are in the module docstring, `:38-45`. |
| The weights are fixed literals, not learned | Same table — the weights are source constants. There is no training path to reach them: every Phase-2 learning route is fail-closed at `routes/phase2_guard.py:15` (`phase2_learning_disabled`, HTTP 410). |
| Each feature is z-scored against that speaker's own historical baseline | The per-speaker reference is built in `services/acoustic_baseline.py` (`BASELINE_VERSION`, `:47`); the composite consumes it at `services/voice_confidence.py:356`. **This is the fact Q1 and Q4(a) turn on.** |
| Signed, weighted, summed, squashed through `tanh` with a neutral dead zone; output in [-1.0, +1.0] | `services/voice_confidence.py:230` (`_DEAD_ZONE = 0.25`) and `:385-388` — the dead zone is subtracted from the magnitude before `math.tanh`, so a middling clip returns exactly `0.0`. |
| Computed and persisted for every take, on by default | `services/voice_confidence.py:252`, `enabled()`. `VOICE_CONFIDENCE_ENABLED` defaults to `"1"` at `:256`. It is an environment kill-switch, **not** a per-user consent flag, and no per-user flag exists. |
| It feeds feedback ranking only behind a flag that is currently off | `services/voice_confidence.py:243`, `ranking_enabled()`. `VOICE_CONFIDENCE_RANKING_ENABLED` defaults to `"0"` at `:248`. |
| Never rendered to the user as a number, band, score or badge | The AC-9 product fence. Asserted as a test, not only as a policy: `tests/test_cross_take_selection.py` pins the score-free payload. |
| Never shown to the human coach | The BLIND COACH fence, recorded at the point of use in `services/moment_confidence.py:21`. |
| The five band labels were renamed on 2026-09-17 | `services/voice_confidence.py:131` — the renamed `BANDS`, with `_RETIRED_BAND_LABELS` at `:135` mapping the old names forward so no stored value is silently reinterpreted; the block comment above them, from `:103`, records the rename and why it is not cosmetic. The second function is `services/confidence_labels.py:108`, `band_of()`. |
| Terms §7 prohibits employer and educational use | Live text: `src/app/terms/page.tsx:306` in `wilplus/frontend-cursor` at commit `f460788` — pinned, because that page is edited under this pack. Draft replacement: `legal/phase1-2026.1/copy/terms-2.0.txt:113-117`. |
| No technical control enforces the §7 prohibition | Stated as an absence, so there is nothing to cite. There is no seat purchasing, team plan or employer surface in the product, but equally no check that would refuse one. |

### 2.6 A correction to §2.3, made while sourcing this memo

§2.3 says we "operate" a blind shadow model that learns from coach answers. That
is **stronger than what is running.** What exists in code is the blind *packet
contract* — `services/mlc2_confidence_blind.py`, which validates that a rating
packet reaches a coach with no machine answer attached. The corpus, dataset,
training, evaluation and promotion paths that would make it a learning model are
all fail-closed behind `routes/phase2_guard.py` and return HTTP 410.

So the accurate statement is: **the blind-rating apparatus is built and the
learning half is disabled.** We have left §2.3 in the memo rather than deleting
it, because the design intent is real and you should price it — but please
answer Q1 on the fixed composite as it actually runs, and treat the shadow model
as a planned capability we are asking about in advance.

---

## 3. The issue: "biometric data" is defined differently in the two regimes

Our privacy policy takes the position — correctly, I believe — that voice
processed to analyse delivery rather than to identify a speaker is **not**
biometric data under **GDPR Art 4(14)**, which requires processing "for the
purpose of uniquely identifying a natural person." We create no voiceprints and
perform no identification. Recital 51 supports this.

**My concern is that this conclusion does not carry across to the AI Act.**
Art 3(34) AI Act defines biometric data as *"personal data resulting from
specific technical processing relating to the physical, physiological or
behavioural characteristics of a natural person"* — **omitting the
unique-identification limb entirely.**

If that reading is right, pitch, loudness dynamics, speech rate and pause
structure are biometric data for AI Act purposes, and `voice_confidence` is a
system inferring something from biometric data. Whether that something is an
*emotion* is then the whole question.

---

## 4. Art 3(39) — arguments both ways

**Art 3(39):** *"an AI system for the purpose of identifying or inferring
emotions or intentions of natural persons on the basis of their biometric data."*

### 4.1 For inclusion
- The internal documentation described the output as locating a moment on a
  spectrum from **"doubtful"** to **"confident"**. Those read as affective states.
  **Disclosure:** on 2026-09-17, after this question was raised, those five
  labels were renamed to neutral delivery-signal terms (`delivery_signal_high`
  through `_low`) and the docstring was rewritten. The change is internal, alters
  no computed value, and is recorded rather than presented as pre-existing —
  please weigh it as a change made in response to the question, not as evidence
  that predates it. **A second function carried the same vocabulary** —
  `confidence_labels.band_of()`, returning `confident` / `neutral` / `doubtful`
  for queue selection — and was renamed the same day, for completeness rather
  than because it was asked about. It is in-memory only, never persisted or
  surfaced. Both renames are disclosed together so the first does not read as
  having been the only one worth making.
- The z-scoring is **against the individual's own baseline**, so the output is
  expressly a statement about *this speaker relative to their own norm* — not a
  property of an audio file in the abstract. This is, I think, our weakest point,
  because our public explanation says "the measurements describe a recording, not
  a person," and the design does not fully support that.
- The shadow model at §2.3 learns to reproduce human judgements about how
  assured a speaker sounds.
- The Commission's February 2025 guidelines on prohibited practices appear to
  read Art 5(1)(f) broadly.

### 4.2 Against inclusion
- Recital 18's indicative list — happiness, sadness, anger, surprise, disgust,
  embarrassment, excitement, shame, contempt, satisfaction, amusement — does not
  include confidence, assurance or doubt.
- Recital 18 excludes physical states, and excludes detection of readily apparent
  expressions unless used to infer emotions.
- "Confidence" here is arguably an attribute of a **performance** — how a piece of
  speech is delivered — rather than an internal emotional state of the performer.
  A voice coach's ear makes the same judgement; the system automates the
  observation, not a psychological diagnosis.
- The output is never surfaced, so no verdict about the person is communicated to
  anyone, including the person.

### 4.3 My own working assessment
**More likely in scope than not, but genuinely arguable.** I would not want to
build on the assumption that we are outside it.

---

## 5. Why the answer matters commercially

### 5.1 If Art 5(1)(f) is engaged
Prohibited in workplace and education, applicable since 2 February 2025, with an
Art 99(3) ceiling of €35m or 7% of worldwide turnover.

**We have live inbound B2B interest.** I need to know whether I can respond to it
at all, and specifically:
- whether the Terms §7 prohibition is sufficient to establish that the system is
  not "placed on the market... for this specific purpose";
- whether a technical control (no team plans, no seat purchasing, no employer
  dashboard) is necessary in addition, and whether it is sufficient;
- whether a coach assigning practice to a learner could engage the **education**
  limb.

### 5.2 If Annex III(1)(c) is engaged
An emotion recognition system that is not prohibited is high-risk. I understand
the Art 6(3) "no significant risk" derogation to be unavailable to us, because
its final subparagraph makes any Annex III system always high-risk where it
performs **profiling**, and we evaluate delivery across repeated takes.

That would mean Arts 9-17, a quality management system, conformity assessment
under Art 43 — and I understand that for Annex III point 1 the internal-control
route under Annex VI is available only where harmonised standards have been
applied in full, failing which a **notified body** is required — plus CE marking,
registration in the EU database, post-market monitoring and incident reporting.

**I am a sole operator conducting unregistered business activity
(*działalność nieewidencjonowana*). That regime is not survivable at my scale.**
If the answer to Q1 is yes, my realistic options are to redesign the feature out
of scope or to remove it.

### 5.3 The date
Annex III obligations were scheduled for 2 August 2026. I am aware of a
Commission "Digital Omnibus" proposal that would have altered the high-risk
timeline. **Please confirm the position as at the date of your opinion** — it
changes my sequencing by roughly a year in either direction.

---

## 6. Questions on which I seek your opinion

> **Q1.** Is `voice_confidence`, as described in §2, an "emotion recognition
> system" within Art 3(39)? Please address in particular whether "confidence"
> and "doubt" are *emotions* for these purposes, and whether the
> speaker-relative baseline is material to that conclusion.

> **Q2.** If yes: does our B2C positioning plus the Terms §7 prohibition keep us
> outside Art 5(1)(f)? What further technical or contractual measures would you
> advise before we respond to B2B interest — and is there any lawful route to
> serving a corporate customer at all?

> **Q3.** If Art 5(1)(f) is not engaged, do we fall within Annex III(1)(c)?
> Please confirm the **current application date** of the Annex III obligations
> following the Digital Omnibus process, and whether the Art 6(3) derogation is
> foreclosed by the profiling subparagraph as I assume.

> **Q4.** Would either of the following design changes materially reduce the risk
> of Q1 being answered yes, and would you regard them as a legitimate scoping
> change or as an attempt at formal evasion likely to be seen through?
> **(a)** removing the speaker-relative baseline so that the read is a property
> of the audio segment rather than of the person;
> **(b)** redefining the construct, in its written operational definition and in
> its use, so that it describes delivery properties only and makes no claim about
> the speaker's state.

**Supplementary, if within scope:** we retain an Art 35 DPIA in draft
(`DPIA-2026-09-17.md`). It records a controller decision to retain raw audio for
the life of the account rather than to a fixed maximum. I would value a view on
whether that is defensible under Art 5(1)(e).

---

## 7. Materials available on request

- Draft DPIA and draft Art 30 record
- Published Terms of Service v1.2 and Privacy Policy v1.2 (willpowerlab.com)
- The consent artifact currently in force, and a proposed replacement
- Source of the component at issue, with its documentation —
  `services/voice_confidence.py` and `services/acoustic_baseline.py`; §2.5
  gives the line anchors, and we can grant repository access
- The internal product fences (no surfaced scores; blind coach) that constrain it

---

*Prepared with AI counsel-support tooling. The technical statements in §2 are
verified against source; §2.5 gives the file and line for each one so you can
check rather than rely on that sentence, and §2.6 records the one statement that
did not survive the check. The legal characterisations in §§3-5 are the client's
working assumptions and are what I am asking you to test.*
