# The learning doors — how each one opens (founder 2026-09-30, L1 to L9)

Four doors, each a code constant in `config.py`, each opened only by a
reviewed change carrying the founder's sentence in the commit. Never a
toggle, never an environment variable. The machinery behind every door is
built and tested with the door closed; the weekly job says in words why
nothing left.

| Door | Constant | Opens when | The sentence |
|------|----------|------------|--------------|
| 1 · the training yes | `MLC2_TRAINING_SWITCH_ENABLED` | **OPEN since 2026-10-01** (N15): the founder's sentence flipped the constant, Privacy 3.2 + Terms 3.2 are the active policy (`phase1-2026-10-01`, 09:00 UTC) and the training policy row exists (`training-only-v1`, 09:08 UTC). The card shows to every speaker who has accepted 3.2 | "open door 1" (said) |
| 2 · pair releases | `MLC2_PAIR_RELEASES_ENABLED` and, per surface, `PAIR_RELEASE_SURFACES` | **OPEN for all three existing surfaces since 2026-10-01**: exercise_script (N16), then praise_line and clearer_version by their own sentences (C4, N18). The release bucket and signing key sit on the web service (`MLC2_DATASET_RELEASES_ENABLED` is the retired DPO lane's constant and stays False). The Phase 7 coach-word surfaces are on hold until a qualified lawyer answers question 2 | "open door 2 for surface S" (said for praise_line, clearer_version, exercise_script) |
| 3 · training | `MLC2_TRAINING_ENABLED` and, per surface, `TRAINING_SURFACES` | the OpenAI DPA with SCCs obliges file deletion; the key may fine-tune; the golden set for the surface is sealed (ML-10); 200 trainable pairs exist | "open door 3 for surface S" |
| 4 · promotion | `MLC2_PROMOTION_ENABLED` and, per surface, `PROMOTION_SURFACES` | an evaluation report passed (candidate ahead, regurgitation clean) under the current prompt lock | "open door 4 for surface S" |

## Door 1 · what is built (ML-8, migration 0405)

- Every pair (`feedback_pairs`) carries its owner's principal, the consent
  state it was recorded under, the grant it rests on, and `releasable`.
- Which surfaces need the yes is `services/pair_consent.py`
  `CONSENT_REQUIRED_SURFACES`. **All three until counsel says otherwise**: a
  coach's words about a speaker's passage carry the passage.
- The weekly job's first act is the refresh (`refresh_feedback_pair_consent_v1`):
  a yes given later makes older pairs releasable; a withdrawal makes them
  not, and **voids any release that carried them**; the job's sweep then
  deletes the object. Revocation purges the copies, whatever door 2 says.
- The speaker's settings card (`TrainingConsentCard`) already exists and
  hides itself while the route answers 410. It shows counsel's sentence as
  the backend serves it, fingerprinted.

**Counsel's answer (2026-10-01, developer version)**

1. All three surfaces need the speaker's yes: a coach's note about a
   speaker's passage is the speaker's personal data even without the
   passage attached (CJEU Nowak). Basis: consent, Art 6(1)(a), with
   Art 9(2)(a) explicit consent on top; never legitimate interest (Privacy
   3.1 promises no training). `CONSENT_REQUIRED_SURFACES` stays all three.
2. The proposed sentence was not approved ("my recordings" is false for a
   text-only programme; the coach's notes were missing; "improve
   WillpowerLab" too vague). Counsel's replacement, for the founder to sign:
   *"Use my practice text and my coach's notes on it to train the models
   that write WillpowerLab's feedback."* On the same screen, before the
   switch can be turned on: text only, never your voice; off by default, no
   cost to saying no; OpenAI, United States, standard contractual clauses;
   turning it off deletes your training copies and keeps you out of new
   training; a model already trained stays. The existing card line
   "Anything already used to train stays in that training, but it won't be
   used again" stays.
3. A withdrawal reaches: every stored copy here with the release voided
   (the weekly refresh does this); every copy at OpenAI (fine-tuning files
   deleted; the DPA must oblige it); every training run that starts after
   the withdrawal, queued ones included. It does not reach an
   already-trained model, provided the model cannot reproduce the speaker's
   text: a regurgitation check joins the golden evaluation before door 4
   opens, and a model that fails it is retrained without the withdrawn pairs.

**Before any policy version is registered** (counsel's list; legal drafts
under `legal/phase1-2026.1/`): the coach's video never enters a pair
(true: `exercise_script` pairs carry the transcript text only; the coach's
own basis and IP sit in the coach agreement); the Terms need a licence to
reproduce and adapt the speaker's presentation text for training; Privacy
3.2's audio-moments draft and this text-only programme become one
description; the consent record gets a fixed retention period instead of
"as long as it is useful"; "models hold no personal information" softens to
"we test that our models do not reproduce your text".

**Signed 2026-10-01.** The founder signed the sentence and the four lines in
chat ("You have my sign off."); the record is
`legal/phase1-2026.1/13-training-consent-wording-SIGNED-2026-10-01.md`, and
the four lines live in the frontend (`dataConsentCopy.ts`,
`trainingBeforeLines`), rendered above the switch only while the backend
offers it. The five legal fixes landed the same day: `10-…` (Privacy 3.2,
text only, six-year consent record, the regurgitation sentence), `11-…`
(retention rows), `12-terms-training-licence-DRAFT.md` (the Terms licence).
One number stays counsel's: the consent-record period, drafted as six years
after withdrawal or erasure.

**Door 1's sequence, then:**

1. ~~the founder signs the sentence and the four lines~~ done 2026-10-01;
2. ~~the legal drafts carry counsel's five fixes~~ done 2026-10-01; counsel
   reads `10`, `11`, `12` once more and confirms the six-year period;
3. ~~the founder approves the final Privacy 3.2 and Terms 3.2 text; they are
   registered as a processing policy version and every user re-accepts~~
   DONE 2026-10-01 09:00 UTC: `phase1-2026-10-01` is the active policy
   (N15 item 5); re-acceptance runs from here
   (SPEC C1: a training yes is refused for anyone who has not accepted the
   version that introduced training). This is the long pole: it is the
   existing policy-registration path (`legal/phase1-2026.1/04-…`,
   `docs/PHASE1-PROCESSING-RUNBOOK.md`), not new code;
4. ~~the founder renders and signs `13-…` as a PDF~~ signed 2026-10-01
   09:02 UTC, hash in `SIGNED-ARTIFACTS.md` row 13; the upload to
   `phase1-2026.1/legal/training-consent-wording-v1.pdf` is the founder's;
5. ~~the policy row is registered with the signed copy and its fingerprint,
   by the founder in the Supabase SQL editor (service role)~~ DONE
   2026-10-01 09:08 UTC (`training-only-v1`, active). The call, for the
   record:

```sql
SELECT public.configure_mlc2_training_consent_policy_v1(
    'training-consent-wording-v1',                       -- approval reference
    '7ed9c87115a1f85d33b6e865c0d5d2859b8d2ebaa140dda30e9295a4b21983f7',
    'Use my practice text and my coach''s notes on it to train the models that write WillpowerLab''s feedback.',
    'training-only-v1',                                  -- consent policy version
    '3.2',                                               -- terms version
    '3.2',                                               -- privacy version
    'Artur Willoński, founder; wording by counsel',
    '2026-10-01T00:00:00Z',
    ARRAY['PL'],
    'phase1-2026.1/legal/training-consent-wording-v1.pdf',
    'b1ec620ea7a8c85d8b351a7e1eadc31c81b52bfffc4cd0c7d4897053b0ce1632',  -- the signed PDF, SIGNED-ARTIFACTS row 13
    'phase1-2026-10-01',                                 -- the version the publish script creates
    now());
```

   The database recomputes the sentence's hash and refuses any other text;
   the last two placeholders exist only after steps 3 and 4;
6. ~~the founder says "open door 1"~~ said 2026-10-01; the constant is True.
   The Settings card appears the moment step 5's row exists, with the four
   lines above it; until then the route answers `available: false` and the
   card hides itself.

**The publish of Privacy 3.2 and Terms 3.2 (step 3), prepared 2026-10-01:**
the approved copy is `legal/phase1-2026.1/copy/privacy-3.2.txt` and
`terms-3.2.txt` (effective 1 October 2026, the day the founder ran it; another day means changing the date first);
the script is `scripts/phase1_policy_publish_training_3_2.sql`, run by hand
in the Supabase SQL editor like the 3.1 publish, step by step (the 3.1
publish's rollout re-point is no longer needed: ML-15 retired that loop). The
processing policy
version it creates is `phase1-2026-10-01`: that string is the registration
SQL's twelfth argument.

**The OpenAI side, before door 3 — in place 2026-10-01:** the founder holds
OpenAI's data processing agreement (one DPA per account; it carries the EU
standard contractual clauses and deletion on instruction, which covers
fine-tuning files; the date is the founder's to record); the backend's key
("willab", permissions All) may fine-tune; the organisation passed
OpenAI's individual verification on 2026-10-01. What door 3 still waits for
is time: the sealed golden set and 200 released exercise_script pairs.

**Carried into doors 3 and 4 (ML-11, ML-10):** a fine-tuning file uploaded
to OpenAI is deleted on any owner's withdrawal; a run reads releasability
at start, so a queued run never trains on a withdrawn pair; the golden
evaluation gains a regurgitation check and a failing model is retrained
without the withdrawn pairs.

## Door 2 · what is built (ML-9, migration 0405)

- `services/pair_release.py`: one JSONL file per surface per week to the
  private bucket, manifest beside it, HMAC-SHA256 signature over the
  manifest's sha256, split speaker-disjoint 80/10/10, no user id, coach id
  or take in the file; the pairs are marked released atomically and leave
  once. `pair_releases` and `pair_release_owners` are the ledger; the
  research screen lists them.
- **The split is the owner's speaker assignment (F-3, 2026-10-05, 0430).**
  Until then it hashed the owner principal, an account or a guest rather
  than a person. Now a pair leaves only when its owner's speaker
  (`ml_speaker_principals`) has its one assignment
  (`ml_speaker_split_assignments`, `speaker-sha256-80-10-10-v1`), and leaves
  under it; the manifest says `split_source: speaker_assignment`. The
  training yes binds the speaker (in the same transaction since 0430; a yes
  given earlier is bound the next time the switch is read, which every
  entry to the recording screen does). A pair whose owner is not bound yet
  waits, and the job's row says "waiting for the owner's speaker binding".
  Door 3 reads the same assignment (`services/speaker_split.py`), so a pair
  released as test is never trained on.
- **Every release is checked (F-8, 0430).** The file and its manifest are
  read back right after they are written, and every week while the release
  stands; each read appends one `pair_release_verifications` row, which the
  database judges against the release row (the file's sha256; the
  manifest's sha256 and its signature). A check that cannot run is named in
  the job's row and never holds a release back.
- **One file per surface per week, and a failed export leaves no copy
  (0447).** The export reads the week's row first and writes nothing when
  there is one, standing or voided: the cron may fire twice in a week, and
  the second fire used to put the week's key again over the standing
  release's objects. It then writes the release row and its owners before
  any object, so a racing fire is refused at its own row. If anything after
  the row fails (a put, a write, or the mark refusing a pair that stopped
  being releasable after it was read), `void_failed_pair_release_v1` voids
  the release (`export_failed`) and sends any marked pair back to waiting;
  the sweep deletes what was put. Before this, a refused mark left a live
  release whose file no refresh and no project erasure could find.
- Variables on the **web** service (the weekly cron calls the web app):

```
R2_PAIR_RELEASE_BUCKET=willab-pair-releases
PAIR_RELEASE_SIGNING_KEY=<a long random string>
PAIR_RELEASE_SIGNING_KEY_ID=pair-release-key-1
```

  The bucket is a new private R2 bucket (no public domain), on the same R2
  account and token as the others; the token must be scoped to it too, or
  the put fails with a silent 403 (see OPS-SECRETS-AND-STAGING.md §3).
  Config-first: set them before the surface is named. The bucket was set on
  2026-10-01 before the sentence; the signing key is the founder's next hand
  (the job says "no signing key" and exports nothing until it is).

## Door 3 · what is built (ML-10, ML-11, migration 0406)

- **The golden set for a pair surface (ML-10).** On the research screen the
  founder judges fifty pairs per surface: the passage and the coach's
  final, never the machine's draft, one question (is this the right
  answer for this passage? yes / no / not sure). A judgement keeps both
  texts and names the owner, so the sealed set stays what was sealed and
  erasure still reaches it; a set a purge changed is refused by the
  evaluation until the founder judges a replacement and re-seals.
  `services/golden_set.py` `sealed_rows` is the one read the evaluation
  uses; it raises on an unsealed or changed set.
- **The run (`services/model_training.py`).** A surface trains only when
  `MLC2_TRAINING_ENABLED` is True AND it is in `TRAINING_SURFACES` AND the
  key is set AND its golden set is sealed AND 200 trainable pairs wait:
  pairs that left through door 2, are still releasable when the run
  starts (exclusion at run start), carry their passage (0406 backfilled
  it; `record_pair` stores it since), and were never trained on (a pair
  trains once, `mark_feedback_pairs_trained_v1`). The file is the serving
  prompt example for example, split by the same speaker assignment door 2
  released each pair under (train, validation; the test bucket held out;
  F-3, 2026-10-05; a pair released before then keeps the owner-principal
  split it left under). One OpenAI job per run; the row remembers the
  file, the job and the owners.
- **The poll.** Each week a running job is read; a finished one loses its
  files at the provider at once; a succeeded one gets its candidate id and
  the golden evaluation (`services/golden_evaluation.py`): token F1
  against the founder's confirmed finals, candidate vs stock, at least 20
  references, and counsel's regurgitation check (an 8-word window of any
  withdrawn speaker's text in any answer fails the model). The report is
  a row; the research screen lists it. Nothing promotes.
- **The withdrawal sweep** (counsel 2026-10-01): a run with an owner whose
  yes is gone loses its files at the provider now and its job if still
  running, whatever the door says. A model already trained stays, marked
  withdrawn-from; only a passing regurgitation check lets it be promoted,
  and a failing one is retrained without those pairs.
- Variables: `OPENAI_API_KEY` (the worker's key must be allowed to
  fine-tune), `OPENAI_FINE_TUNE_BASE_MODEL` (default
  `gpt-4.1-mini-2025-04-14`). Config-first: set before the sentence.

## Door 4 · what is built (ML-12, migration 0406)

- The three answer surfaces are contracts (`ml_surface_contracts`), with
  runtime keys on the allowlist (`runtime_model_gate`, the SQL guard's
  widened RPC) and canonical aliases (praise → praise_generation, clearer
  version → correction_generation, exercise script →
  coach_comment_generation). `compose_draft` already serves through
  `chat_complete`, so a promoted id is served the moment the door opens and
  the stock model until then (`_model_the_promotion_gate_allows`).
- `services/model_promotion.py` `promote` refuses unless
  `MLC2_PROMOTION_ENABLED` is True AND the surface is in
  `PROMOTION_SURFACES` AND the report passed under the current prompt lock;
  it writes one runtime key through the only writer and a `model_promotions`
  history row. `kill` returns the surface to the stock model within one
  request, door or no door. `scripts/promote_pair_surface.py` is the hand.

## The two model-free lanes (ML-13, ML-14)

- **Learned exercise order** (`services/exercise_learned_order.py`): with
  `EXERCISE_LEARNED_ORDER_ENABLED` True, the jar past its bar and the fair
  test above its bar, equal-fit ties in the matcher follow the learned
  helped rate; otherwise today's order exactly. The eligible pool never
  changes. Closed in code until the founder's yes.
- **Two acoustic shadow cues** (`services/acoustic_cues.py`): `low_volume`
  (the voice under 12 dB above the room, by the clip's own noise meter) and
  `flat_pitch` (pitch variation under 6% of its mean on 30+ frames), logged
  per Take into the shadow log, routing nothing; the ledger reports them
  against the same bar, and the weekly job drafts their promotion
  migration like the verbal cues'.

## What never changes by a door

L1: a pair without the yes is never releasable while its surface needs one.
L2: the catalogue and every answer stay Manager-ranked; a release changes
nothing a speaker sees. L3: pairs are provenance, never labels; owner
answers never enter a file. AC-9: the counts live on the founder's pages
and the research screen only.
