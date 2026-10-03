# exercise-human-delayed-v1 — the delayed blind human measure (signed by the founder 2026-10-02)

**Status: written before any data; signed by the founder on 2026-10-02 (in
chat: "I sign it all"; SPEC-DECISIONS-LOG N24).** No row of
`delayed_measure_pairs` or `delayed_measure_votes` is written while
`Config.DELAYED_MEASURE_ENABLED` is False. The switch stayed False until (a)
this definition was signed by the founder and (b) C1 to C3 were answered (the
measure plays speakers' clips to other people, like Lend your ear). Both are
now true: (a) on 2026-10-02, and (b) by the founder's own determinations of
2026-10-02 (`legal/phase1-2026.1/14-founder-determinations-2026-10-02/`, Q3
to Q5; not reviewed by outside counsel). What still holds the switch is the
published policy: Privacy 3.3 and Terms 3.3 active and re-accepted
(`scripts/phase1_policy_publish_3_3.sql`), the lending rows seeded
(`scripts/phase1_retention_rules_v1_2.sql`), and `PEER_LANE_ENABLED` first.
The switch went on 2026-10-02 (N25) and off again on 2026-10-03 (N29): no
screen renders the share switch or Lend your ear, so no pair could ever be
voted on. It comes back on with the peer lane.
Phase 5 of the after-practice paths (founder 2026-10-01).

## What it measures

Whether a library exercise, practised once on one moment, made that moment
sound more confident to people who do not know which recording is which.
It is the human companion of the machine's exercise-adequacy label
(exercise-adequacy-label-v2) and of the machine leg of
practice_more_confident (exercise-more-confident-v2). It never teaches the
exercise ranker on its own; it grades.

## The pair

One practice makes at most one pair:

| field | fixed as |
|---|---|
| the before | the original moment's clip (the snippet the practice was offered on) |
| the after | the practice's **first valid attempt among its first three** (F7, `exercise_learning_readiness.endpoint_attempt`); later attempts never replace it, so when the speaker stopped cannot change the pair |
| eligible | `kind = exercise` only; the match trace carries **no fallback rung** (general or warm-up, F2); the practice has a valid endpoint; the speaker's consent covers it (C1) |
| excluded | rewrite practices (the words changed), plain-moment practices, fallbacks, practices with no valid attempt |
| heard | only while the original moment's **share switch** is on (founder 2026-10-02, Q3-A): the pair's two clips ride that one switch, and switching it off pulls both from Lend your ear at once; the shared entry and the pair's before carry one pair id so a set never holds the same voice twice |

A pair is enrolled once (insert-once on `practice_id`), with the rule
version, when the practice closes.

## The horizon

A pair's clips may be judged only from **seven days** after the practice
closed (`HORIZON_DAYS = 7`), and never both in one Lend your ear set; the
partner clip reaches the same listener no sooner than the next day
(founder correction 5, `lend_your_ear.PAIR_GAP_DAYS`). The two clips enter
as separate, unlabelled clips: the rater is never told that a clip has a
partner, which clip is which, or that an exercise was involved.

## Who judges

Peers through Lend your ear (lane `peer`) and coaches through the blind
queue (lane `coach`), each with the same five answers. Excluded from a
pair's votes:

- the speaker (never their own clip);
- **the coach who handled the moment** on request (resolved its coach
  request, or rated the original on the walk) — founder correction 6;
- any rater **already exposed** to either clip outside a blind rating
  (task 4: first exposure per coach per clip is recorded; a later rating is
  `blind = false` and does not count).

A vote is one per rater per clip. Audio only.

## What counts as "better"

Each clip is settled by the quorum rules of `label_quorum` (two human
answers that agree; a disagreement routes a third; `not_sure` never
settles; `audio_unclear` is a technical abstention). The ladder is
`no < in_between < yes`. A pair's outcome, read only once **both** clips
are settled:

| outcome | when |
|---|---|
| `better` | the after settles higher on the ladder than the before |
| `same` | the two settle equal |
| `worse` | the after settles lower |
| `pending` | either clip is not settled yet |

No single rater's answer, and no machine read, is an outcome.

## What is reported

Per exercise (and per targeted error): pairs enrolled, pairs settled, and
the share `better` with a **speaker-resampled interval** (the fair test's
bootstrap, `exercise_fair_test`), on held-out speakers where the fair test
has a split. Founder-only, in the learning ledger; never a number on any
speaker's screen (AC-9). The measure is compared against the machine's
label on the same pairs; disagreement is a finding about the label, not a
re-label.

## F6 audits on attempts

The error-audit queue (Phase 6a) samples practice attempts as well as
original moments, under the same blindness and exposure rules, so the
alarms that decide "helped" are checked on attempts, not only on
originals. Attempts enter that queue by `clip_kind = practice_attempt`.

## What never happens

- No training on any of this (voice training waits for C1 and the
  founder's sentence).
- No pair's clips to the same listener on one day, or in one set.
- No reveal: no rater learns a clip's speaker, words, partner, exercise, or
  the machine's read.
