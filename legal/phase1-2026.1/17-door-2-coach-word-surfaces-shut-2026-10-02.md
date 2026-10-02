# Door 2 stays shut for the two coach-word surfaces — the record

    record:              door-2-coach-word-surfaces-2026-10-02
    author:              Artur Willoński, founder and controller; not reviewed by outside counsel
    rests on:            14-founder-determinations-2026-10-02/q8.md (A, changed from B the same day)
    what it keeps shut:  door 2 (pair releases) for `coach_moment_line` and `coach_take_word`

## The rule

A coach's sentences about a speaker's passage are the speaker's personal data,
even with the passage stripped out (counsel 2026-10-01, `docs/LEARNING-DOORS.md`,
citing CJEU Nowak). The two Phase 7 surfaces, the coach's personal line on a
moment and the coach's word for a Take, therefore need the speaker's yes before
anything trained on them leaves the service, exactly as the three answer
surfaces do.

## What the code says, and keeps saying

- `services/pair_consent.py`: `CONSENT_REQUIRED_SURFACES` is every pair surface,
  the two coach-word surfaces included; a pair without the speaker's yes is
  never releasable.
- `config.py`: `PAIR_RELEASE_SURFACES` names only `exercise_script`,
  `praise_line` and `clearer_version`. No founder sentence adds the coach-word
  surfaces to it before the condition below is met.
- `services/feedback_pairs.py`: `ANSWER_SURFACES` is the three surfaces doors 2,
  3 and 4 know; the coach-word pairs are recorded and counted and stand outside
  every door.

## What would open it

1. A consent wording whose yes covers the coach's own sentences about the
   speaker's passage. The signed wording of 2026-10-01
   (`13-training-consent-wording-SIGNED-2026-10-01.md`, "Use my practice text
   and my coach's notes on it…") names the coach's notes; whether "notes"
   reaches the personal line and the Take word as the speaker reads them is the
   question a lawyer answers, not this record.
2. If it does not, a new consent policy version with wording that does, and a
   fresh yes from every speaker (the database allows one active training
   policy at a time).
3. Then, and only then, the founder's sentence "open door 2 for surface
   coach_moment_line" and "… coach_take_word", each one reviewed PR.

## Why it is recorded

The founder's first answer (B) would have contradicted counsel's signed answer
of the day before. He withdrew it: "keep it how it used to be, I don't want
contradictions." This record exists so the next person asking the question
finds the answer and its reason in one place.
