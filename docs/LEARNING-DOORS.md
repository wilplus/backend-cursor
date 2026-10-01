# The learning doors — how each one opens (founder 2026-09-30, L1 to L9)

Four doors, each a code constant in `config.py`, each opened only by a
reviewed change carrying the founder's sentence in the commit. Never a
toggle, never an environment variable. The machinery behind every door is
built and tested with the door closed; the weekly job says in words why
nothing left.

| Door | Constant | Opens when | The sentence |
|------|----------|------------|--------------|
| 1 · the training yes | `MLC2_TRAINING_SWITCH_ENABLED` | counsel answered (2026-10-01: all three surfaces); the founder signs counsel's wording; the legal drafts carry counsel's five fixes; the policy row is configured with the signed wording (`configure_mlc2_training_consent_policy_v1`) | "open door 1" |
| 2 · dataset releases | `MLC2_DATASET_RELEASES_ENABLED` and, per surface, `PAIR_RELEASE_SURFACES` | door 1 is open, the release bucket and signing key are set on the web service, and the founder names the surface | "open door 2 for surface S" (S ∈ praise_line, clearer_version, exercise_script) |
| 3 · training | `MLC2_TRAINING_ENABLED` | the golden set for the surface is sealed (ML-10) and 200 releasable pairs exist | "open door 3 for surface S" |
| 4 · promotion | `MLC2_PROMOTION_ENABLED` | the golden evaluation shows the candidate ahead of the baseline | "open door 4 for surface S" |

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

**Door 1's sequence, then:** the founder signs the sentence and the four
pre-switch lines → the legal drafts carry counsel's five fixes → the policy
row is registered with the signed copy and its fingerprint
(`configure_mlc2_training_consent_policy_v1`) → the founder says "open door
1" → the switch flips by one reviewed change and the Settings card appears.

**Carried into doors 3 and 4 (ML-11, ML-10):** a fine-tuning file uploaded
to OpenAI is deleted on any owner's withdrawal; a run reads releasability
at start, so a queued run never trains on a withdrawn pair; the golden
evaluation gains a regurgitation check and a failing model is retrained
without the withdrawn pairs.

## Door 2 · what is built (ML-9, migration 0405)

- `services/pair_release.py`: one JSONL file per surface per week to the
  private bucket, manifest beside it, HMAC-SHA256 signature over the
  manifest's sha256, split speaker-disjoint 80/10/10 by owner principal,
  no user id, coach id or take in the file; the pairs are marked released
  atomically and leave once. `pair_releases` and `pair_release_owners` are
  the ledger; the research screen lists them.
- Variables on the **web** service (the weekly cron calls the web app):

```
R2_PAIR_RELEASE_BUCKET=willab-pair-releases
PAIR_RELEASE_SIGNING_KEY=<a long random string>
PAIR_RELEASE_SIGNING_KEY_ID=pair-release-key-1
```

  The bucket is a new private R2 bucket (no public domain), on the same R2
  account and token as the others; the token must be scoped to it too, or
  the put fails with a silent 403 (see OPS-SECRETS-AND-STAGING.md §3).
  Config-first: set them before the surface is named.

## What never changes by a door

L1: a pair without the yes is never releasable while its surface needs one.
L2: the catalogue and every answer stay Manager-ranked; a release changes
nothing a speaker sees. L3: pairs are provenance, never labels; owner
answers never enter a file. AC-9: the counts live on the founder's pages
and the research screen only.
