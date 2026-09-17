# 01 — Product and processing description

**Purpose:** the technical facts underlying Documents 02 and 03. Every statement
here is verified against source and carries a file reference. **These are facts
about the system, not legal characterisations.**

---

## 1. What the product does

A user creates a project, uploads or writes slides, and records themselves
presenting. For each recording ("take"):

1. Audio is captured in the browser and uploaded to object storage.
2. It is transcribed and the transcript is segmented **1:1 per slide**.
3. Acoustic measurements are computed from the audio.
4. After the first take the system generates an **"Ideal Text"** — a canonical
   written version of the presentation, which the user owns and edits. Later
   takes propose improvements but never silently rewrite it.
5. After every take the system returns a small fixed number of **coaching
   feedback items**, each tied to evidence in the recording.
6. Optionally and separately: a human coach may review the recording
   asynchronously; the user may share short extracts with other users for blind
   rating.

The loop from recording to feedback is fully automated and never waits for a
human.

---

## 2. The component at issue — `services/voice_confidence.py`

### 2.1 What it computes

Seven acoustic features are read from measurements the pipeline already holds.
Each is **z-scored against that individual speaker's own historical baseline**,
signed toward "confident", multiplied by a fixed weight, summed, and squashed
through `tanh` with a neutral dead zone. Output is a single float in
**[-1.0, +1.0]**, documented in source as a spectrum from *doubtful* (-1.0)
through a neutral band (0.0) to *confident* (+1.0).

| # | Feature | Source field | Direction |
|---|---|---|---|
| 1 | Pitch range | `f0_sd` | wider → more confident |
| 2 | Loudness range | `dynamic_db` | wider → more confident |
| 3 | Mean pitch | `f0_mean` | higher → less confident |
| 4 | Speech rate | `wpm` | faster → more confident |
| 5 | Pausing | `pause_ratio` | more → less confident |
| 6 | Terminal pitch contour | `f0_mid_end_delta` | falling → more confident |
| 7 | Energy contour | intensity envelope | decaying → more confident |

**Weights are fixed and derived from published literature** (Jiang & Pell 2017,
*Speech Communication* 88:106-126). **The composite is not machine-learned and
does not adapt.**

### 2.2 Baseline normalisation — material to Document 02

The z-scoring is **within-speaker**, against that user's own prior recordings —
not against an absolute scale or a population norm. Source documents this as
deliberate: the underlying paper normalises within-speaker.

**I flag this because I think it is the fact most adverse to my own position.**
A within-speaker baseline means the output is a statement about *this speaker
relative to their own norm*, which is harder to characterise as a property of an
audio file than a population-normalised or absolute reading would be. See
Document 02 §7.2.

### 2.3 What is done with the output

| | |
|---|---|
| **Computed and stored** | For every take. **Default on** (`services/voice_confidence.py:177` — `VOICE_CONFIDENCE_ENABLED` defaults to `"1"`) |
| **Used for ranking** | Feeds selection of which moments become coaching feedback — **currently disabled** (`:169` — `VOICE_CONFIDENCE_RANKING_ENABLED` defaults to `"0"`), pending validation against human ratings |
| **Shown to the user** | **Never.** An internal product rule forbids surfacing any score, band, ratio or classifier output. Enforced by test |
| **Shown to the coach** | **Never.** Deliberately withheld so the coach's independent judgement is not anchored to the machine's |

So at present the system **computes and persists a delivery-state value it does
not act on.** I record this because it bears on necessity and data minimisation
(Document 04 §3) as well as on scope.

### 2.4 A second, separate component

A **blind shadow model** learns from human coaches' answers to the question
*"does this delivery sound assured?"* It is machine-learned, it is not surfaced
to anyone, and it exists to measure human-machine agreement off-surface.

**I flag it separately because I assume it is harder to defend than the fixed
composite** — it is a learned classifier of human judgements about a speaker's
state, rather than a fixed arithmetic read of acoustic features.

### 2.5 What the system does *not* do

- No voiceprints, no speaker identification, no speaker verification.
- No inference of health, personality, ethnicity, age, or any comparable
  characteristic.
- **No collection or inference of speaker sex.** An earlier version routed some
  calculations by speaker sex; this was **retired as executable behaviour on
  2026-08-29** and the current cue contract is one universal, sex-blind
  calculation. Historical rows are retained audit-only and receive no new writes.
- No emotion vocabulary is applied to the acoustic output. The only named
  emotions in the system are **the user's own self-report** (§3 below).

---

## 3. Self-reported state — not an inference

Before recording, the user may answer a check-in naming how they feel, choosing
from a closed vocabulary: *calm, curious, excited, determined, confident,
nervous, tense, overwhelmed, doubtful, tired, unsure*.

This is **stored verbatim as the user's own statement.** Source records that it
is "not converted to a psychological state, score, direction, or training label."
The reviewing coach sees it, on the reasoning that it is the student's own words
rather than a machine guess.

**I include this because a reader scanning the codebase will find an emotion
vocabulary and should know what it is: self-report, not output.** I do not
believe it engages Art 3(39), which addresses *inferring* emotions.

---

## 4. Deployment context

**Business-to-consumer.** Individuals practise their own presentations, on their
own initiative, about their own material.

**Terms §7 expressly prohibits** use by employers or educational institutions to
assess, monitor, rank or make decisions about employees, candidates or students,
and provides for account termination.

⚠️ **There is currently no technical control enforcing this — only the contract
term.** No team plans or seat purchasing exist today, but nothing in the code
prevents them being added, and I have live inbound B2B interest. See Document 02
§8.2.

⚠️ One flow to flag rather than conceal: a coach can **assign practice to a
learner**. Today the coaches are engaged by me for feedback quality, not by any
institution. I raise it because I do not know whether it could engage the
*education* limb of Art 5(1)(f), and I would rather you tell me than discover it.

---

## 5. Data flows and recipients

| Stage | Where | Notes |
|---|---|---|
| Capture | Browser | User-initiated |
| Storage | Cloudflare R2 | Audio objects |
| Transcription and text analysis | **OpenAI developer API (United States)** | Asserted zero-retention; **see Document 08 — unverified** |
| Acoustic measurement | In-process | No external transfer |
| `voice_confidence` | In-process | Pure arithmetic over held metrics; no external call |
| Database | Supabase, EU region | ~69 tables |
| Human coach review | Coach account | Optional, consented |
| Peer rating | Other users | Optional, per-recording, consented |

Full inventory: Document 05. Transfers: Document 08.

---

## 6. Scale

⚠️ **Being verified.** My working understanding is that the service has **no
active user base beyond myself and a small number of test accounts.** I am
confirming this from the database and will tell you the figure separately.

**Please do not size the urgency of Document 03 from my covering email until I
confirm it.** If the figure is near zero, the bundled-consent defect is a
pre-launch correction. If it is not, it is a live exposure. I would rather give
you the number than have you assume either.

---

## 7. Repository access

Available on request. The relevant files are:

| Path | What |
|---|---|
| `services/voice_confidence.py` | The component at issue; header documents construct, cues, weights and constraints |
| `services/acoustic_baseline.py` | Within-speaker baseline (§2.2) |
| `services/named_emotion.py` | Self-report vocabulary (§3) |
| `legal/mlc2-bundled-consent-v1.json` | The consent in force (Document 07) |
| `frontend-cursor/src/app/privacy/page.tsx` | Published policy (Document 06) |
| `frontend-cursor/src/app/terms/page.tsx` | Published terms (Document 06) |
