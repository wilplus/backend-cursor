# The learning doors — how each one opens (founder 2026-09-30, L1 to L9)

Four doors, each a code constant in `config.py`, each opened only by a
reviewed change carrying the founder's sentence in the commit. Never a
toggle, never an environment variable. The machinery behind every door is
built and tested with the door closed; the weekly job says in words why
nothing left.

| Door | Constant | Opens when | The sentence |
|------|----------|------------|--------------|
| 1 · the training yes | `MLC2_TRAINING_SWITCH_ENABLED` | counsel has answered which pairs need a speaker's yes and approved the wording; the policy row is configured with that wording (`configure_mlc2_training_consent_policy_v1`) | "open door 1" |
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

**The question for counsel** (send as is):

> WillpowerLab records a coach's written answers about a speaker's own
> passage: a praise line, a clearer version of the speaker's sentence, and
> an exercise instruction, each stored beside the model's first draft. We
> want to use these pairs to improve the drafting model for everyone. Each
> pair quotes the speaker's own words (the passage) and never their voice.
> (1) Which of the three kinds needs the speaker's explicit training
> consent before it may be used, given that the passage is the speaker's
> content and the answer is the coach's? (2) Please approve the wording of
> the one-sentence consent the speaker turns on in Settings, revocable at
> any time, with the consequence that copies already exported are deleted
> on revocation: proposed "Use my recordings and my practice text to help
> improve WillpowerLab for everyone." (3) Does a withdrawal have to reach
> a model already trained on the pair, or only the stored copies?

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
