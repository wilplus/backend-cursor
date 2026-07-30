# FE handoff — the speaker-sex field

BE is on `feat/sex-conditioned-voice-confidence`. Nothing here is blocked on FE:
the field is optional end-to-end and the composite already runs without it.

## What it is, so the copy is honest

It is **not** a demographics field and it does not personalise anything the user
sees. It selects a set of **weights** inside the voice-confidence composite —
the acoustic half of how we rank one take of a slide against another.

The reason it has to exist: of the seven acoustic cues, one **reverses
direction** by speaker sex (Jiang & Pell 2017).

| | wide pitch range means… |
|---|---|
| women | **more** confident — it is the strongest single cue |
| men | **less** confident |

Normalising each speaker against their own baseline does not fix this. That
removes a scale offset; this is a direction flip, so it survives normalisation.
Without the field, one sex is scored with the sign upside down on that cue.

## Endpoints

Two ways in — use whichever fits the flow. Both are optional.

**1. At signup** — `POST /auth/signup` (and its alias `POST /v2/auth/signup`)
takes an optional `sex` alongside the existing fields:

```json
{ "email": "…", "password": "…", "terms_accepted": true, "sex": "female" }
```

A bad value is a `400 INVALID_INPUT` **before the account is created**, so the
user can correct it and retry. If the value is fine but the write fails, signup
still returns `201` — we do not fail a registration over this.

**2. Any time after** — `GET` / `POST /v2/user/profile` now carry `sex`:

```json
{ "domain": "sales", "goal": "…", "sex": "female",
  "domain_vocabulary_default": [], "is_coach": false }
```

Four states, and they are **not** interchangeable:

| value | meaning | FE behaviour |
|---|---|---|
| `null` | never asked | show the question |
| `"female"` / `"male"` | answered | don't re-ask |
| `"prefer_not_to_say"` | asked, declined | **don't re-ask** |

`POST` only touches what you send. `{"sex": "male"}` alone will not clear the
user's domain/goal, and `{"domain": …, "goal": …}` alone will not clear their
sex. Sending `"sex": null` explicitly clears it back to never-asked.
Invalid values → `422 INVALID_INPUT`.

## Two things for the founder, not for FE to decide

**1. The story says the field is mandatory. BE does not enforce that, on
purpose, and I'd push back on it.**

- It cannot be mandatory retroactively — every existing user has no answer, and
  their takes are being scored right now.
- Blocking account creation on a demographic-looking question, on the signup
  screen, is a conversion cost paid for a weight vector.
- A user who won't answer but is forced to will answer *randomly*, which is
  strictly worse than no answer: a wrong value inverts the cue for them, while
  no value just falls back to the sex-blind weights we ship today.

If it does go mandatory, that's a founder call and FE-side enforcement — the
API stays permissive either way.

**2. All user-facing copy here needs founder sign-off** (CLAUDE.md standing
constraint). Including the question itself, the option labels, and any
explanation of why we ask. Suggested framing to sign off or reject — *"This
tunes how we read your voice. Confident delivery sounds measurably different in
male and female voices, so we calibrate to the right one."* — and note the
answer must never be presented as feeding a score the user sees, because it
doesn't (AC-9).

## What FE must not do

- Don't surface it as an insight, badge, or anything in the readout.
- Don't infer it and post it on the user's behalf. The BE has its own acoustic
  fallback for users who haven't answered; it is a routing guess held in memory
  for one take and is **never** written to their profile. A guess the FE posts
  would become a stored claim about them and would overwrite a real answer.
