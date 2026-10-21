# Learning and the label quorum

> **Label: In force** · one of the rules, read in N95's order. Every doc and its label: [`README.md`](../README.md) (N106).

One page for two questions: **what the app learns from**, and **how an
answer becomes a label it can trust**. Started 2026-10-21 (founder, the
Claude Code chat: "unify the .md files about the learning sources and quorum
in general"; decisions log N102) from the docs listed in §5, which stay as
history or as the detail of one part.

**How this page works**

- **It gathers; it does not outrank.** The order of truth stays N95's: the
  decisions log, then [`docs/CANONICAL_PRODUCT_CONTRACT.md`](CANONICAL_PRODUCT_CONTRACT.md), then
  [`docs/LOCKS.md`](LOCKS.md) and the `FOUNDER-LOCK-*.md` files; the frontend's flow pages
  count for their screens. Every rule here names where it comes from. If this
  page and one of those disagree, they win and this page is fixed.
- **§1 is the present.** A rule that changes is rewritten in place, and its
  old wording goes to §6 as one line. Never a new file.
- A new decision about learning or labels is an entry in the decisions log
  **and** a line here, in the same PR. A screen's part also goes on its flow
  page: the walk's §I (frontend [`docs/flows/feedback-walk-and-chat.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/feedback-walk-and-chat.md)) and
  the coach panel's H (frontend [`docs/flows/coach-panel.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/coach-panel.md)).
- A disagreement found between two docs, or between a doc and the code, is a
  line in §3 until the founder settles it. Where the code disagrees with the
  docs, the docs win and the code is a bug (N95).

---

## 0. In plain words

You record a talk. The app picks out a few short moments, and people answer
one question about each: **"Does this sound confident?"** (👍 Yes, 😐
In-between, 👎 No). One answer could be a mistake, so a moment is only
**settled** when **two people give the same answer**, like two referees seeing
the same thing. If they disagree, a third person listens.

Not everyone gets a vote. **Coaches** and **other speakers** do. **The
computer** only guesses: its guess may move a moment forward in the line for
the next listener, but it never decides the answer. **The speaker** never
votes on their own moment, because judging your own voice is like marking
your own homework. Their answer is kept, but it never counts and never
teaches a model.

Moments that still need a listener wait in a line. A moment where one answer
and the computer's guess clash goes to the front, because someone heard it
wrong and one more listener finds out who. Since 21 October the same is
decided for a speaker who disagrees with their coach, but it is not switched
on yet, because the app does not ask speakers about their own moments any
more (N97).

Only settled moments may be used to test or train a model, and only from
people who said yes to training. The founder's own answers are kept apart as
the sealed "golden set" every model is checked against.

---

## 1. The rules as they stand

### A · The question and its answers

- **A1** The question is `conf-q-v2`, "Does this sound confident?" (K1).
  👍 Yes, 😐 In-between and 👎 No are answers about the voice. "Audio
  unclear" says the sound failed, not the voice (K1, K5). "Not sure" is the
  rater's uncertainty (K1). It left the coach's Judge and the walk on
  2026-10-12 (panel D1, walk C10); old answers keep it.
- **A2** An answer about the voice is given **blind**: the sound first, with
  no transcript, machine read, score or reason before it (K2; contract 34;
  walk I2). A rating given after the rater saw the clip's non-blind side is
  stamped `blind = false` and counts for nothing (contract 35g-11).
- **A3** A rater must have the clip's language in their profile. An unknown
  or different language fails closed (K3).
- **A4** Old answers keep their question version. Historical v1 `neutral`
  rows keep their IDK meaning and are never recast (K; `label_quorum.py`).

### B · Who has a vote

| Who | Vote? | Lane | Source |
|---|---|---|---|
| A coach, blind and language-matched | Yes | `coach` | K6, K8 |
| Another speaker (a peer), on a moment shared with their community | Yes | `game_peer` | K6; N52.4; `lend_your_ear._peer_label` |
| A coach judging a training-corpus import | Yes, like any coach's | `coach` | N58 (CO3); K8 |
| The machine | **Never.** It only orders the line | none | rule 1; J1; K6 |
| The speaker, on their own moment | **Never.** A self-report | `self_report = true` | rule 2; J2; K6 |
| Seeded or historical rows that can't be verified, or any unknown lane | Never | `bootstrap`, others | K8; `QUORUM_LANES` |

A coach still can't judge their own voice anywhere (N58). The machine holds
`machine_votes: 0` on every resolution, so the rule can be checked in a log
line (rule 1).

### C · When answers become a label

Only counted answers (section B) are counted. "Audio unclear" is counted
apart (K4, K5; `label_quorum.resolve`):

| Counted answers | Status | Meaning |
|---|---|---|
| none | `unrated` | Nobody has listened |
| exactly 1 | `singleton` | Weak signal only, never gold or evaluation (J3) |
| 2 matching Yes, In-between or No | `quorum` | **Settled.** The only status that may enter a golden check, an evaluation or a training set (J3; K4) |
| 2 that don't settle (a clash, or a Not sure) | `needs_third` | A third rater |
| 3 or more with no matching pair | `unresolved` | Out for good: neither training nor evaluation (K4) |
| 1 "Audio unclear" | `audio_retry` | One fresh rater, never the same one (K5, K7) |
| 2 "Audio unclear" | `audio_quarantined` | Out for good (K5) |

"Not sure" never settles anything (K4). A rater may change an ordinary answer
before the clip closes, but one person never gives two votes (K7).

### D · The line for the next listener

Higher goes first (`label_quorum.routing_priority`):

| Priority | When |
|---|---|
| 100 | One answer, and the machine's Yes or No clashes with it (rule 3; J3). Decided, not built: or the speaker's own answer clashes with the lone coach's (N97) |
| 80 | `needs_third` |
| 60 | `audio_retry` |
| 40 | One answer, and nobody clashes with it |
| 20 | `unrated` |
| 0 | Settled, `unresolved` or quarantined: never served again. A speaker's disagreement never reopens a clip (N97) |

The priority is removed before a queue is sent, so a rater never learns why
a clip is where it is (BLIND COACH). As read in the code on 2026-10-21, it
orders one queue: a Take's confidence queue
(`/v2/coach/sessions/<id>/confidence-queue`). Other queues have their own
founder-set order (§3, item A9). The N97 rule waits until speakers answer
about their own moments again ([`docs/DESIGN-WIL-70-disagreement-signal-2026-10-18.md`](DESIGN-WIL-70-disagreement-signal-2026-10-18.md)
§6).

### E · Every learning source

| Source | Who gives it | Counts toward a label? | What it feeds | Needs | State |
|---|---|---|---|---|---|
| **Coach's blind answer** on a speaker's moment | Coach, on the Judge (panel D) | Yes | The label ledger. A single coach answer is also product authority: key moments, the Album's coach leg (`professional_confidence.py`), and the calibration of the reached bar (N51 V8, V9) | Coach review is contract (M) | Live |
| **Coach's blind answer** on a training-corpus import | Coach, in mixed rounds (N101) | Yes (N58) | The label ledger; 80/20 split by speaker (`corpus_split.py`) | The founder's processing basis (N58; N68 D4, N69) | Judging live. Nothing trains on these labels until the founder says so (N56) |
| **Other speakers' answers** | Speakers, one moment per practice try (walk C8; N97) | Yes, while the ledger still needs a rater | The label ledger (lane `game_peer`) and `community_answers`. Never a coach label or owner routing (N52.4). No authority over feedback, key moments, styling or the Album (contract 35) | The owner's per-Take community share (N52.4) | Live since 2026-10-08 |
| **Answers on licensed corpus clips** | Speakers, in the places peers leave (walk C8; N97) | **No.** A corpus clip is not a snippet and takes no label | `community_answers` (`clip_source = 'corpus'`) only | A licensed clip, never a speaker's training-corpus clip (CM1 A) | Served when rows exist. Nothing on main writes new ones since the tool was deleted on 2026-10-11 |
| **The machine's proposal** (`machine_value`) | The voice-confidence read, stamped server-side | **Never** | Ordering only: the line (section D), the corpus rounds' bands (N101), the mixed queue (K9), the S term of `willfidence-v1` (N51 carve-out) | none | Live |
| **The speaker's own answer** (`take_feedback_self_report`) | The speaker | **Never** (rule 2) | The Album's user leg (contract 32), rater calibration (rule 2), routing (N97, waiting) | none | Kept. Almost no new answers: judging your own moments left the walk on 2026-10-12 (walk C10), and judging your own practice try is off until about 50 clips have both answers (walk §3) |
| **Soft-label counts** (`clip_answer_counts`) | Built from blind coach and peer answers | Not a label | Yes 1, In-between ½, No 0; Not sure counted apart. Nothing reads it to decide anything yet | none | Live writes |
| **The founder's golden set** | The founder alone, 50 per surface, sealed by hash (lock L6; N51 QG4 B) | Never a label and never training (`golden_set.py`) | Every model check: the confidence read and the pair surfaces (`golden_set.py`) | none | Built. Whether each surface is sealed is not visible in the code |
| **Feedback pairs** (a model's draft and the coach's final words) | Coaches editing drafts (contract 35g-2a) | Never a label | Training of the open surfaces, behind the four doors (section F) | Door 1: the speaker's training yes | Recording live, per surface |
| **The coach's words, for a "text brain"** | Coaches (N79) | No | A future model trained on what coaches say, the situation and the error type. Capture first | The training yes for transcribed coach videos (N79) | Capture is in open PRs (BE #1133 to #1138). No trainer |
| **Training-corpus copies** (`training_corpus_items`) | The shown moment's text plus the coach's Yes or No | No | A text-only copy for later training (N68 D1) | The training yes | Live since 2026-10-12 |
| **The blind error audit** ("Do you hear it?") | Coaches (contract 35g-3a) | No | The shadow-cue promotion bar (at least 30 coach Yes, 80% firing) and the learned-v1 detector fit, shadow only (`detector_candidates.training_rows`) | The blind-check policy and legitimate interest; a written objection is recorded (N66) | See §3, items A3 and A4 |
| **Exercise outcomes** | The machine's practice check and the coach's legs | Only `exercise-adequacy-label-v2` is an exercise label (contract 35c; MLC3 §3.5) | The learned exercise order (live since 2026-10-08, training-yes speakers only) and the exercise picker (walk I4) | The training yes | Mixed: see [`docs/MLC3-EXERCISE-ADEQUACY-DESIGN.md`](MLC3-EXERCISE-ADEQUACY-DESIGN.md). The delayed measure is retired |
| **Will's speaker memory** | Every answer and every Take's outcome (`speaker_memory.py`) | No | Will's private note, five lines at most, which the founder can correct. No model is retrained | Processing authorization | Live ([`docs/SPEAKER-MEMORY.md`](SPEAKER-MEMORY.md)) |

### F · Training and checking a model

- **F1** Only a settled clip (`quorum`) may be gold or evaluation data (J3;
  K4). Splits are speaker-disjoint: one speaker's clips are in exactly one of
  train, validation or test (K10).
- **F2** A model is `off`, `shadow` or `limited`, and nothing else. It needs a
  sealed, pre-registered evaluation (K11). It never promotes itself (K12).
  The confidence read stays rules until the SPEC's evaluation passes (lock
  L9).
- **F3** **Willfidence.** `willfidence-v1` is live, read by the machine only.
  `willfidence-v2` is planned: training tunes its weights against the soft
  label once there are at least 200 labels, speaker-disjoint and checked on
  the sealed golden set, and then the founder promotes it (walk I3).
  Willfidence is an internal measure, not a label (J1 and J3 as amended by
  N51).
- **F4** **The four doors**, for feedback pairs ([`docs/LEARNING-DOORS.md`](LEARNING-DOORS.md)):
  - Door 1 is the speaker's training yes.
  - Doors 2 to 4 (release, training, promotion) are open for `praise_line`,
    `clearer_version` and `exercise_script`.
  - They are closed again for the coach-word surfaces `coach_moment_line` and
    `coach_take_word` (N79).
  - A training run waits for its surface's sealed golden set and 200
    trainable pairs. A promotion needs a passing report.
  - The door constants were removed on 2026-10-12. Each door is now its
    per-surface set in `config.py`.

### G · What never becomes a label or training data

- The speaker's own answers about their own voice (rule 2; contract 30; walk
  I2).
- The machine's proposal (rule 1).
- The AI version of the speaker's voice ([`FOUNDER-LOCK-ai-voice-practice-2026-10-12.md`](FOUNDER-LOCK-ai-voice-practice-2026-10-12.md);
  walk I2).
- Will's conversation (N73). Whether a message helped is a report for the
  founder, not a label (walk I4).
- Answers on licensed corpus clips (section E).
- A rating that wasn't blind (contract 35g-11), and every `unresolved` or
  quarantined clip (K4, K5).

---

## 2. In flight

One line per piece of work: `item · what it is · where it stands · PR`.

- **N97** · speaker/coach disagreement goes first in the line · decided 2026-10-21, waits until speakers answer about their own moments again · BE #1219
- **willfidence-v2** · weights tuned against the soft label · waits for 200 labels (§3, item A6) · none yet
- **N79** · the coach's words captured for a "text brain" · capture in open PRs; no trainer · BE #1133, #1134, #1136, #1137, #1138
- **Will learns more** · transcripts, coach words and chat history in Will's memory (step 2) · open PR · BE #1186

---

## 3. Still open

Found while gathering this page on 2026-10-21, mostly by reading the docs and
code side by side. Each is for the founder unless it is marked as a code
bug.

**A · Docs that disagree with each other (the founder decides)**

1. **What admits a clip to the Voice Album.** Log C1 and C4 say the Album
   and a two-human quorum are the same thing. Contract 32 (2026-09-29) says
   a Machine Yes, a User Yes and a Coach Yes on the same recording, and
   contract 35 gives the peer quorum no say over the Album. The contract
   looks current, and C1 and C4 look stale.
2. **Does the coach see the machine's read after answering?** Contract 34,
   as amended 2026-10-06 (P28 B), says nothing is revealed, after
   submitting either. The coach panel (D2, E1) shows "The machine heard"
   once the coach's rating is saved.
3. **Detector training.** `config.py` has `DETECTOR_TRAINING_AUTHORISED =
   True` ("ON again from 2026-10-08"). Contract 35g-9 and N29.6 say off
   since 2026-10-03, and no log entry records it going back on. Did the
   founder's "turn it all ON" of 2026-10-08 cover it?
4. **The blind lines.** Panel B3 and contract 35g-10 say they're switched
   off. The docstrings of `error_presence_audit.py`, `coach_block_pick.py`
   and `v4_coach_sheets.py` say they're on. This wasn't checked in
   production.
5. **"Half praised and half low."** Walk I1 says the clips judged are half
   praised and half low sentences. The shown moments follow the score
   (N86), the corpus rounds take equal thirds by the machine's band (N101),
   and other speakers' clips come before licensed ones (N97). No code
   picks half and half.
6. **What "200 labels" means for willfidence-v2.** Walk I1 says a label
   counts once two answers match. Walk I3 trains on the soft label, which
   any single blind answer feeds. Is it 200 settled clips or 200 answers?
7. **A coach's own talk, imported.** N58 says a coach can't judge their own
   voice anywhere. `rating_is_self_report` treats every import as not a
   self-report, so a coach's label on an import of their own talk would
   count.
8. **The training-yes screen.** N28 asks "Turn on the learning?" before
   every Take. The consent-screens lock (amended 2026-10-18) removes that
   screen. The amendment isn't in the log, and the log comes first (N95).
9. **Where rule 3's line applies.** J3 sends a clashing singleton to a
   second listener immediately. The coach panel's queue, the corpus's mixed
   rounds (N101) and other speakers' clips each have their own founder-set
   order, so rule 3 orders only a Take's confidence queue. Should it also
   order any of the others?
10. **Copies for training: text or audio?** N6 Q1 and N10 say audio. N68 D1
    and `training_corpus.py` say text only.
11. **An Art 9 basis for training.** [`LEARNING-DOORS.md`](LEARNING-DOORS.md), `pair_consent.py`
    and the ROPA addendum name Art 9(2)(a). N69 says no Art 9 basis is
    needed.
12. **A practice self-report as training data.** MLC3 §8 says it is
    "potentially training-eligible". Contract 30 and walk I2 say never. The
    founder's "never trains any model" of 2026-10-19 is written only in the
    WIL-70 note, not in the log.
13. **What willfidence is.** SPEC §17 says S is (coach + peer + machine) ÷ 3
    over a block of about 75 words. Walk H1 says S is `voice_confidence`
    over a sentence.
14. **Doors 3 and 4 "held behind 3.5".** `config.py` says Privacy and Terms
    3.5 were published. N68 says publication was blocked. No log entry
    records a publication.
15. **Exercise measures built from chat answers.** `exercise_held.py` and
    `practice_effects.py` (WIL-29) rest on answers given in chat that aren't
    in the log. Under N95 they aren't in force until they are.

**B · Code that disagrees with the docs (N95: the docs win; each fix is its
own PR)**

1. The SQL view `snippet_label_quorum` (migration 0289) counts ratings with
   `blind = false`. `label_quorum.py` excludes them (contract 35g-11).
2. The golden set's candidate pool reads every `confidence_labels` row,
   with no lane, self-report or blind filter. Its docstring says "moments
   coaches have already labelled blind".
3. ~~`research_quorum.py` counts a lane `peer` and rows with no lane, and
   treats Not sure as a definite answer.~~ **Fixed (N111):** the research
   figures count by the ledger's rules; Not sure is a label but never agrees
   (`tests/test_research_quorum.py`).
2. ~~The golden set's candidate pool reads every `confidence_labels` row,
   with no lane, self-report or blind filter.~~ **Fixed (N111):** the pool
   takes only blind answers in the ledger's lanes (a coach, another speaker
   inside practice), never a self-report (`tests/test_golden_set_pool.py`).
3. `research_quorum.py` counts a lane `peer` and rows with no lane, and
   treats Not sure as a definite answer.
4. `state_ratings.aggregate` has no blind or self-report filter.
5. ~~`communities.order_community_clips` skips only settled clips, so
4. ~~`state_ratings.aggregate` has no blind or self-report filter.~~
   **Fixed (N111):** a panel read leaves out a self-report in any lane and a
   non-blind answer. Nothing outside its tests calls it today.
5. `communities.order_community_clips` skips only settled clips, so
   `unresolved` and quarantined clips still reach listeners, whose answers
   then become no label.~~ **Fixed (N111):** a community clip reaches a
   listener only while the ledger says it still needs a rater.
6. The `label_quorum.py` docstring points to `game_engine._source_class`,
   which is gone. It also says the SQL file holds the same truth table, but
   the current view is migration 0289, not `add_label_quorum_ledger.sql`.
7. The docstrings of `coach_word_pairs.py`, `pair_consent.py` and
   `feedback_pairs.py` don't mention N79's closing of the coach-word
   surfaces. `training_import.py` still names door constants that were
   removed.

Items B2 to B5 were read from the code but not run. The PR that fixes each
one confirms it first.

**C · History**

1. **v1 `neutral` + `neutral`.** Under J4 to J6 (2026-08-14), two `neutral`
   answers settled a clip as "perceptually ambiguous". K (2026-08-25)
   replaced that rule and says historical rows keep their meaning. Today the
   code reads every v1 `neutral` as an IDK that never settles, so a clip
   that was settled under v1 now reads as `needs_third` or `unresolved`.
   Should those clips stay settled?
2. **`neutral` means three things.** In SPEC §17 it is a perceptual middle.
   In J6 and the ledger it is an IDK. In `practice_more_confident.py` it is
   the In-between rung. Writing that down here is enough, unless the
   founder wants old rows relabelled.

---

## 4. Where it lives

**Code (backend):**
- `services/label_quorum.py`: the four rules, the truth table and the line
- `migrations/version_confidence_rating_instrument_v2.sql` (0289): the
  `snippet_label_quorum` view
- `services/lend_your_ear.py` and `services/communities.py`: other speakers'
  clips and licensed clips
- `services/professional_confidence.py`: a single coach answer as product
  authority
- `services/clip_answer_counts.py`: the soft label
- `services/golden_set.py` and `services/golden_evaluation.py`: the golden
  set and model checks
- `services/feedback_pairs.py`, `services/pair_consent.py` and
  `services/model_training.py`: pairs and the doors
- `services/training_corpus.py`, `services/training_import.py`,
  `services/corpus_split.py` and `services/corpus_mixed_queue.py`: the
  training corpus
- `services/detector_candidates.py`: the detector fit
- `services/willfidence.py` and `services/moment_pick.py`: willfidence
- `services/speaker_memory.py`: Will's memory
- `config.py`: the doors' per-surface sets and `DETECTOR_TRAINING_AUTHORISED`

**Docs:**

| File | What it keeps now |
|---|---|
| [`docs/SPEC-DECISIONS-LOG.md`](SPEC-DECISIONS-LOG.md) | The decisions: J (amended), K, L, M, and N51, N52.4, N56, N58, N68, N69, N73, N79, N95, N97, N99 to N102 |
| [`docs/CANONICAL_PRODUCT_CONTRACT.md`](CANONICAL_PRODUCT_CONTRACT.md) | §5 (clauses 29 to 35k) and §6 |
| [`docs/LEARNING-DOORS.md`](LEARNING-DOORS.md) | The detail of the four doors |
| [`docs/SPEAKER-MEMORY.md`](SPEAKER-MEMORY.md) | The detail of Will's memory |
| [`docs/MLC3-EXERCISE-ADEQUACY-DESIGN.md`](MLC3-EXERCISE-ADEQUACY-DESIGN.md) | The detail of the exercise label (§3.5) |
| [`docs/DESIGN-WIL-70-disagreement-signal-2026-10-18.md`](DESIGN-WIL-70-disagreement-signal-2026-10-18.md) | The detail of N97 (§6) |
| [`FOUNDER-LOCK-coach-panel-2026-10.md`](FOUNDER-LOCK-coach-panel-2026-10.md) | L1 to L9 |
| [`FOUNDER-LOCK-ai-voice-practice-2026-10-12.md`](FOUNDER-LOCK-ai-voice-practice-2026-10-12.md) | The AI clip |
| Frontend [`docs/flows/feedback-walk-and-chat.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/feedback-walk-and-chat.md) | C8 and §1 I |
| Frontend [`docs/flows/coach-panel.md`](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/coach-panel.md) | D (the Judge) and H (the training corpus) |

## 5. The older pages

These now open with a note pointing here and are no longer the place to
look for the whole picture:

- [`docs/LEARNING-TRACE.md`](https://github.com/wilplus/backend-cursor/blob/8b5205fa519f3c8447eb8c49d1bcf6f28b8df3e6/docs/LEARNING-TRACE.md) (history since 2026-09-29)
- [`docs/SESSION-2026-08-14-confidence-unification.md`](SESSION-2026-08-14-confidence-unification.md) (history; its "two
  IDKs settle" is replaced by K)
- [`docs/PRODUCTION-DATA-FOUNDATION.md`](https://github.com/wilplus/backend-cursor/blob/8b5205fa519f3c8447eb8c49d1bcf6f28b8df3e6/docs/PRODUCTION-DATA-FOUNDATION.md) (history; its "no training
  implemented" is out of date)
- [`docs/SPEC.md`](SPEC.md) §3, §9 and §17 (the log wins, N95)
- [`docs/MEASURE-exercise-human-delayed-v1.md`](MEASURE-exercise-human-delayed-v1.md) (retired measure)
- [`docs/CONCEPT-per-user-exercise-effectiveness-2026-10-18.md`](CONCEPT-per-user-exercise-effectiveness-2026-10-18.md)

The audit snapshot ([`docs/audit/LEDGER.md`](audit/LEDGER.md), [`docs/audit/FOUNDER-QUEUE.md`](audit/FOUNDER-QUEUE.md)),
the MLC-2 and MLC-3 audits and the legal register (`docs/legal/`) keep their
own dates and are left as they are. The legal files are counsel's to change.

## 6. Changes

One line each, newest first: `date · N · what changed · PR`.

- 2026-10-21 · N111 · B5 fixed: an unresolved or quarantined clip no longer reaches community listeners · BE
- 2026-10-21 · N111 · B4 fixed: a panel read in `state_ratings` leaves out self-reports and non-blind answers · BE
- 2026-10-21 · N111 · B3 fixed: the research screen's label figures count what the ledger counts · BE
- 2026-10-21 · N111 · B2 fixed: the golden set's pool takes only blind, independent labels · BE
- 2026-10-21 · N102 · this page gathers the learning sources and the label quorum into one place, with what's open (§3) · BE #1234, FE #922
