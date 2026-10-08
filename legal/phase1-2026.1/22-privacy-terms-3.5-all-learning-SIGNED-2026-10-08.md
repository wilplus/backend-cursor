# Privacy Policy 3.5 and Terms of Service 3.5: every learning pipe, under the training yes — SIGNED by the founder 2026-10-08

**SIGNED by the founder, 8 October 2026** (in chat: "I sign the 3.5 pack of 8 October 2026 as drafted"; decisions log N68). **Counsel has not seen these changes**; the founder signed knowing that.

    documents:           copy/privacy-3.5.txt, copy/terms-3.5.txt (the exact bytes to publish)
    replaces:            copy/privacy-3.4.txt, copy/terms-3.4.txt (published 2026-10-08, phase1-2026-10-08)
    asked by:            Artur Willoński, founder and controller, 2026-10-08 ("open every learning pipe")
    drafted by:          engineering, from the code and the signed records named below; not a lawyer
    basis kept:          consent, Art 6(1)(a) with Art 9(2)(a), opt-in, withdrawable (counsel, 2026-10-01, docs/LEARNING-DOORS.md)
    the switch wording:  23-training-consent-wording-v2-SIGNED-2026-10-08.md (a new consent policy version, training-only-v2)
    signing sheet:       SIGN-3.5-2026-10-08.md

The two `copy/*.txt` files carry no draft mark on purpose: their exact bytes
are what is hashed and what a user later proves they agreed to (README,
"Hashes"). This file is the signature mark, the changelog and the notes.

## 1. What 3.5 is for

Every learning lane the code has built, dark, behind its own constant, gets a
published description and a lawful basis, so that each can then be opened by
its own reviewed switch PR. The rule the drafts follow is one sentence:
**anything that learns across people happens only for speakers who hold the
training yes.** One yes, one switch, one withdrawal, one record, one basis
(consent), as counsel advised for text training on 2026-10-01. The only
processing outside the yes is the corpus import (section 4c), whose voices
are not users and cannot be asked.

| Lane | Constant (`config.py`) | What it does | Where 3.5 says so |
|---|---|---|---|
| Door 3, fine-tuning | `MLC2_TRAINING_ENABLED`, `TRAINING_SURFACES` | OpenAI fine-tunes on (passage, coach final) text pairs, per surface | Privacy §4a "Your practice text and your coach's words", "Who trains, and where" |
| Door 4, deployment | `MLC2_PROMOTION_ENABLED`, `PROMOTION_SURFACES` | a fine-tuned model passes the golden evaluation and the regurgitation check and is served to every speaker | Privacy §4a "The trained models"; Terms §8 licence (second purpose) |
| The coach-word surfaces | `PAIR_RELEASE_SURFACES` (`coach_moment_line`, `coach_take_word`) | the coach's line on a moment and word for a Take join doors 2 to 4 | Privacy §4a first bullet, "Your coach's words are your coach's too"; the switch sentence names them (counsel question 6) |
| The corpus copy | `MLC2_TRAINING_CORPUS_COPY_ENABLED` | separate copies of each shown moment's words and the coach's blind yes or no, from Takes recorded while the yes is on | Privacy §4a "Separate copies"; §7 |
| The corpus import | `TRAINING_IMPORT_ENABLED` | audio the founder holds the rights to, imported, transcribed and judged under the N58 basis | Privacy §4c (new) |
| Learned detectors | `DETECTOR_TRAINING_AUTHORISED` | a per-error model fitted on the blind-check answers and the clip's timing measurements | Privacy §3 (new paragraph), §4 (blind check), §4a "Measurements"; document 02 v1.2 note |
| V4 coach sheets | `V4_COACH_SHEETS_ENABLED` | "Pick the moment for feedback" (clips with words and audio) and "Which sounds surer" (the speaker's words beside a reworded version), stored as answers and preference pairs | Privacy §4a "A coach's answers", §5, §7; Terms §11 |
| The coach's blind block pick | `COACH_BLOCK_PICK_ENABLED` | the coach's blind pick among a block's moments against the Manager's | same as V4 sheets |
| Learned exercise order | `EXERCISE_LEARNED_ORDER_ENABLED` | ties among equally fitting exercises ordered by the pooled helped rate | Privacy §2 (new line), §4a "Measurements" |

## 2. Changelog, 3.4 → 3.5

**Privacy Policy**

- Version line and version note: 3.5; the note says what widened, that an
  earlier yes does not carry over, and that §4c is new.
- §2: one line added, "Whether a fragment you re-recorded after an exercise
  came out better" (the input of the learned exercise order).
- §3: one paragraph added: with the §4a yes, timing measurements of a clip a
  coach answered about may tune the pattern-spotting software for everyone;
  without it, never.
- §4, the blind check: one sentence added: with the §4a yes, the answer may
  also tune that software. The check itself is unchanged (legitimate
  interest, objection by email).
- §4, after the Stripe paragraph: the sentence "Under this version we do not
  use anyone's recordings to train models … our systems refuse to register a
  processing policy that would permit it" is replaced by "We never use the
  sound of anyone's recordings to train models: no recording, and no clip of
  one, is copied or sent for training", with pointers to §4a and §4c. The old
  sentence was true only of processing policies and would mislead once doors
  3 and 4 open.
- §4a, rewritten: the new switch sentence; what is used and what for (four
  bullets: text and coach's words, coach's answers, measurements, separate
  copies); "text and numbers only"; what is used from before the yes; the
  basis (unchanged words); the coach's side; the trained models and the
  regurgitation test; retention (unchanged); withdrawal (now names the queued
  run and the learned settings); the earlier yes; the six-year record
  (unchanged); who trains and where (OpenAI for text, our own systems for
  the rest).
- §4c, new: recordings imported for training (Article 14 information for
  people who are not users): what, why, basis, retention, rights.
- §5: OpenAI also transcribes imported recordings; human coaches may hear a
  moment for §4a.
- §7: training copies now include a coach's yes or no; three rows added
  (§4a coach answers, trained models and learned settings, imported
  recordings).
- §9: the coach's §4a answers do not survive an account deletion.

**Terms of Service**

- Version line and version note: 3.5; the training choice is widened and
  asked again; "the sound of your recordings … is never used to train
  models".
- §8: "We do not use your recordings to train models, and we do not pool
  your material" becomes "We do not use the sound of your recordings …";
  pooling is named, with the yes only. The licence gains its second purpose,
  using the trained models to write feedback for every speaker, and says the
  coach's words are licensed by the coach agreement, not by the speaker.
- §11: one paragraph added: with the yes, a coach may hear a moment and
  sometimes read its words to answer a question that teaches the software.

Nothing else moves: practice stays contract (3.4), the blind check stays
legitimate interest with objection by email (3.4), lending stays per
recording (3.3), the six-year record stays (counsel question 7 still open),
the AI notice and the agreement screen are the 3.1 bytes.

## 3. Decisions the signature takes (each drafted one way; say so if not)

**D1. The corpus copy copies audio today. Drafted: it must not.**
`services/training_corpus.py` (`_copy_audio`) cuts each shown moment's audio
and stores it under `training-corpus/` when `MLC2_TRAINING_CORPUS_COPY_ENABLED`
is on. Every signed text says the opposite: Privacy 3.2 to 3.4 §4a ("Your
voice never leaves for training: no audio is copied"), the signed switch lines
("Text only. Never your voice.") and the signed retention schedule
(`11-retention-schedule-v1.1-training-DRAFT.md`: "The earlier audio design …
is retired and holds nothing"). 3.5 keeps "no recording of your voice, and no
clip of one, is ever copied or sent for training". So the switch PR for the
corpus copy first removes the audio branch (code, its own reviewed PR). The
other way, copying audio, would need its own consent, its own retention row
and a new consent-screen design, and is not drafted.

**D2. Passages from before the yes. Drafted: they can be used.** The weekly
refresh makes a pair releasable when its owner says yes later
(`services/pair_consent.py`, the module docstring: "a yes given later makes
older pairs releasable"). Privacy 3.4 §4a said "nothing recorded before you
turn it on is" copied, which is true of the corpus copy and not of the pairs.
3.5 says what the code does: earlier passages and the coach's words on them
can be used; separate copies only from Takes recorded while the switch is on.
The other way would be a code change to the refresh.

**D3. An earlier yes does not carry over. Drafted: it counts as off.** The
database holds one active training policy at a time
(`ANOTHER_TRAINING_POLICY_IS_ACTIVE`, `migrations/a_training_yes_is_its_own_act.sql`),
so registering training-only-v2 means retiring training-only-v1, and the
status read counts only a yes under a policy that is not retired. Every v1 yes
then reads as off: the weekly refresh makes those pairs unreleasable, voids
their releases and sweeps the files; a door-3 run with such an owner loses its
files at the provider. That is also the honest answer to counsel's question 6:
a v1 yes did not name the coach's line or the Take word. 3.5 §4a says so in
plain words, and the Lab asks again before each Take ("Turn on the
learning?").

**D4. The corpus import's basis. Drafted: legitimate interest.** N58
(`docs/SPEC-DECISIONS-LOG.md`, 7 October) records "legal basis recorded by the
founder, agreed with counsel" and names no article. The people speaking on
imported audio are not users and cannot be asked through the product; holding
the rights to a recording (copyright, a licence) is not a GDPR basis for the
voices on it. 3.5 §4c drafts Art 6(1)(f), with Article 14 information,
deletion when the right ends and objection by email. If the founder's
recorded basis is a different article, §4c changes before signature. The
Article 9 position for incidental sensitive content on imported audio is put
to counsel (DPIA addendum, item 7).

## 4. What the code must make true before each switch PR

3.5 makes promises that some lanes do not yet keep. Publishing 3.5 opens
nothing; each lane's switch PR must first show that its promise holds. These
are engineering items, listed so the signature is not read as saying they are
done.

| # | Before flipping | The code must | Today |
|---|---|---|---|
| E1 | `MLC2_TRAINING_CORPUS_COPY_ENABLED` | copy no audio (D1) | copies an audio clip per moment |
| E2 | coach-word surfaces in `PAIR_RELEASE_SURFACES`, `TRAINING_SURFACES`, `PROMOTION_SURFACES` | carry them in doors 2 to 4 (surface contracts, golden sets, runtime keys) | release, training and promotion read `ANSWER_SURFACES` in `services/feedback_pairs.py`, the three answer surfaces only |
| E3 | `DETECTOR_TRAINING_AUTHORISED` | fit only on clips whose speaker holds an active v2 yes, on our own systems | `LearnedDetector.fit` raises `NotImplementedError` (`services/detector_candidates.py`) |
| E4 | `V4_COACH_SHEETS_ENABLED`, `COACH_BLOCK_PICK_ENABLED` | put only blocks of speakers with an active yes on a sheet; delete answers and preference pairs with the recording and on withdrawal; leave out a speaker who objected to the blind check | `services/v4_coach_sheets.py` reads no consent |
| E5 | `EXERCISE_LEARNED_ORDER_ENABLED` | count helped rates only from speakers with an active yes | the jar counts study-group speakers, no consent filter (`services/exercise_learned_order.py`) |
| E6 | registering training-only-v2 | retire v1 at the same instant v2 starts; confirm the refresh and the door-3 sweep treat a v1 yes as withdrawn | no retire function exists; done by hand (signing sheet, step 6) |
| E7 | `TRAINING_IMPORT_ENABLED` | let a person delete one import on request (§4c objection) | to confirm |
| E8 | every switch PR | the switch PR names this file and the line of 3.5 it relies on | — |

## 5. Open with counsel, not settled by this signature

- Question 9 of `21-counsel-questions-2026-10.md`: Privacy says Art 9(2)(a)
  for the training yes; the registration function records
  `article_9_treatment = 'not_applicable'`
  (`migrations/a_training_yes_is_its_own_act.sql`, `configure_mlc2_training_consent_policy_v1`).
  3.5 keeps the published Art 9(2)(a) and the disagreement stays open.
- Question 7: the six-year record.
- Question 1: document 02's condition, now also covering the learned detector
  (`02-power-score-classification-v1.2-NOTE-SIGNED-2026-10-08.md`).
- New: whether a model fine-tuned on speakers' text and served to every
  speaker is anonymous (EDPB Opinion 28/2024 on AI models); whether the
  8-word regurgitation test, which today fails a model only on withdrawn
  speakers' text, is enough for deployment, or the memorisation rate it
  already records should gate door 4 too; the D4 basis.
