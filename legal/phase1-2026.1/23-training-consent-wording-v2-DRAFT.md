# The training switch wording, version 2

**DRAFT — for the founder's signature; counsel not yet consulted on these changes.**

    artifact_kind:       training_consent_wording
    version:             training-only-v2 (the consent_policy_version it registers)
    succeeds:            13-training-consent-wording-SIGNED-2026-10-01.md (training-only-v1), which stays signed for v1
    approving_authority: Artur Willoński (founder and controller)
    approved_at:         [[at signature]]
    wording by:          engineering, in the style of counsel's v1 wording of 2026-10-01; counsel has not seen v2
    object_key:          phase1-2026.1/legal/training-consent-wording-v2.pdf
    sha256:              [[computed from the signed PDF at registration time]]
    requires:            Privacy 3.5 and Terms 3.5 published (22-privacy-terms-3.5-all-learning-DRAFT.md)

**What changes from v1, and why.** v1 named "my practice text and my coach's
notes on it" and "the models that write WillpowerLab's feedback". Three
things it did not name now need the speaker's yes:

1. **The coach's own words** on a moment and for a Take
   (`coach_moment_line`, `coach_take_word`). Counsel said on 2026-10-01 that a
   coach's sentences about a speaker's passage are the speaker's personal
   data; whether "my coach's notes" reaches them is counsel question 6, and
   `17-door-2-coach-word-surfaces-shut-2026-10-02.md` says the safe answer is
   new wording and a fresh yes. v2 is that wording: "my coach's words".
2. **Answers and measurements**: the coach's blind answers about a clip (the
   check, the V4 sheets, the block pick), the clip's timing measurements, and
   whether an exercise helped. v2: "answers about it, and measurements of my
   practice".
3. **The deployed models write for everyone.** v1 said what the models do
   ("write WillpowerLab's feedback"); v2 says for whom: "give every
   WillpowerLab speaker feedback". A speaker should know their text shapes
   what other people read.

v1's structure is kept: one first-person sentence, fingerprinted, and short
lines above it that must be on screen before the switch can be turned on.

## The switch sentence (`p_toggle_copy`)

```
Use my practice text, my coach's words and answers about it, and measurements of my practice to train the models that give every WillpowerLab speaker feedback.
```

sha256 of exactly those bytes (UTF-8, no trailing newline), computed by
engineering on 2026-10-08:

```
69d3e70205d991b725a55d5a537071358a9fd31b236d5c5049a5273fb521083c
```

The database recomputes it at registration and refuses any other text
(`TRAINING_POLICY_COPY_HASH_DOES_NOT_VERIFY`): straight apostrophes, one
space between words, no newline. If a word changes before signature, the
hash is recomputed and this line updated in the same commit.

## The lines above the switch

1. Text and numbers only. No recording of your voice, and no clip of one, is ever copied or sent for training.
2. Off unless you turn it on. Saying no costs you nothing.
3. Your coach's words include their line on a moment and their word for a take.
4. The numbers are measurements such as your pace and pauses, and whether an exercise helped you. They stay with us.
5. A coach may hear a moment of yours, without your name, to answer a question that teaches our software.
6. The trained models write feedback for every speaker. We test that they do not repeat your text.
7. OpenAI trains the text models for us, in the United States, under the European Commission's standard contractual clauses.
8. Turning it off deletes your training copies and keeps you out of any new training. A model already trained stays.

Lines 2 and 8 are v1's lines 2 and 4, unchanged. Line 7 is v1's line 3 with
"the models" made "the text models", because the pattern spotters and the
exercise order are tuned here, not at OpenAI. Line 1 replaces "Text only.
Never your voice.": numbers measured from a clip are now in scope, and the
promise that matters, no audio, is kept and made exact. Lines 3 to 6 are
new.

The card line under the switch stays as signed on 2026-09-26: "Anything
already used to train stays in that training, but it won't be used again."

## Where they live

The sentence is served by the backend from the policy row. The lines live in
the frontend's data-consent copy module
(frontend-cursor/src/lib/legal/dataConsentCopy.ts, `trainingBeforeLines`),
which renders them on the Data & consent card and in "Turn on the
learning?". Those screens are design-locked (frontend CLAUDE.md, "Design lock
— the consent screens"); the signing sheet lists the exact strings and the
one layout question (eight lines where the locked prototype shows four).

## The registration call (template; placeholders filled after signature)

Run by the founder in the Supabase SQL editor (service role), in one
transaction, only after: Privacy 3.5 and Terms 3.5 are published as a
processing policy version; this file is rendered and signed as a PDF; the PDF
is uploaded to the `object_key` above and its hash is in
`SIGNED-ARTIFACTS.md`. v1 must be retired at the same instant v2 starts:
the database allows one active training policy, and a retired_at later than
v2's active_from is refused (`ANOTHER_TRAINING_POLICY_IS_ACTIVE`).

```sql
BEGIN;

-- 1. Retire v1 at the instant v2 starts. Every v1 yes then reads as off
--    (Privacy 3.5 §4a, "If you said yes before version 3.5").
UPDATE public.ml_consent_policies
   SET retired_at = TIMESTAMPTZ '[[T: the switch instant, e.g. 2026-10-08T18:00:00Z]]'
 WHERE version = 'training-only-v1' AND retired_at IS NULL;

-- 2. Register v2.
SELECT public.configure_mlc2_training_consent_policy_v1(
    'training-consent-wording-v2',                       -- approval reference
    '69d3e70205d991b725a55d5a537071358a9fd31b236d5c5049a5273fb521083c',
    'Use my practice text, my coach''s words and answers about it, and measurements of my practice to train the models that give every WillpowerLab speaker feedback.',
    'training-only-v2',                                  -- consent policy version
    '3.5',                                               -- terms version
    '3.5',                                               -- privacy version
    'Artur Willoński, founder; wording drafted by engineering in counsel''s style, counsel not consulted',
    '[[APPROVED_AT: the signature date, e.g. 2026-10-08T00:00:00Z]]',
    ARRAY['PL'],
    'phase1-2026.1/legal/training-consent-wording-v2.pdf',
    '[[SIGNED_PDF_SHA256: SIGNED-ARTIFACTS row 23]]',
    '[[PROCESSING_POLICY_VERSION: the version id the 3.5 publish creates]]',
    TIMESTAMPTZ '[[T: the same instant as step 1]]');

-- 3. Check: exactly one training policy is in force, and it is v2.
SELECT version, active_from, retired_at
  FROM public.ml_consent_policies
 WHERE grant_scope = 'training_only'
 ORDER BY active_from;

COMMIT;  -- or ROLLBACK if step 3 shows anything but v1 retired at T and v2 active from T
```

Notes on the call:

- **If step 1 is refused** (the SQL editor's role cannot update the table),
  stop: engineering adds a reviewed retire function; nothing is half-done
  inside the transaction.
- **The Article 9 field.** The function records `article_9_treatment =
  'not_applicable'` whatever is passed (`migrations/a_training_yes_is_its_own_act.sql`),
  while Privacy 3.5 §4a, like 3.2 to 3.4, says Art 9(2)(a). That is counsel
  question 9, still open; registering v2 does not settle it.
- **What a retirement does, to be confirmed by engineering before the call**
  (22-…, E6): the weekly refresh treats the pairs of every v1 yes as not
  releasable and voids their releases; the door-3 sweep deletes provider
  files of any run with such an owner. The corpus copy is off, so no corpus
  copy exists under v1.
- The switch sentence's apostrophes are doubled only inside the SQL string
  literal; the hashed bytes have single apostrophes.

## What this does and does not do

- It fixes the words and, once registered, makes a v2 yes possible. It opens
  no door: each lane still waits for its own switch PR (22-…, section 4).
- Changing a word later means a training-only-v3 and a fresh yes from
  everyone, exactly as v1 → v2.
