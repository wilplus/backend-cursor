# The training switch wording — SIGNED by the founder 2026-10-01

    artifact_kind:       training_consent_wording
    version:             training-only-v1 (the consent_policy_version it registers)
    approving_authority: Artur Willoński (founder and controller)
    approved_at:         2026-10-01 (in chat: "You have my sign off.")
    wording by:          counsel, 2026-10-01 (door-1 answer, `docs/LEARNING-DOORS.md`)
    object_key:          phase1-2026.1/legal/training-consent-wording-v1.pdf
    sha256:              [[computed from the signed PDF at registration time]]

**What was signed.** Two parts, word for word. A yes is fingerprinted against
the switch sentence; the four lines sit above the switch on the same screen,
before it can be turned on.

## The switch sentence (`p_toggle_copy`)

```
Use my practice text and my coach's notes on it to train the models that write WillpowerLab's feedback.
```

sha256 of exactly those bytes (UTF-8, no trailing newline):

```
7ed9c87115a1f85d33b6e865c0d5d2859b8d2ebaa140dda30e9295a4b21983f7
```

The hash above is recomputed by the database at registration
(`configure_mlc2_training_consent_policy_v1` raises
`TRAINING_POLICY_COPY_HASH_DOES_NOT_VERIFY` on any difference), so the
sentence must reach the RPC byte for byte: straight quotes, one space between
words, no newline. See the registration SQL in `docs/LEARNING-DOORS.md`.

## The four lines above the switch

1. Text only. Never your voice.
2. Off unless you turn it on. Saying no costs you nothing.
3. OpenAI trains the models for us, in the United States, under the European
   Commission's standard contractual clauses.
4. Turning it off deletes your training copies and keeps you out of any new
   training. A model already trained stays.

The existing card line under the switch stays as signed on 2026-09-26:
"Anything already used to train stays in that training, but it won't be used
again." The lines live in the frontend
repo's data-consent copy module (`trainingBeforeLines`) and render only while
the backend offers the switch.

## What this does and does not do

- It fixes the words. It switches nothing on: the route still answers 410
  while `MLC2_TRAINING_SWITCH_ENABLED` is False, and no policy row exists
  until the SQL in `docs/LEARNING-DOORS.md` runs.
- Registration needs two things this file does not give: Privacy 3.2 and
  Terms 3.2 registered as a processing policy version (`10-…`, `12-…`; a yes
  is refused for anyone who has not accepted the version that introduced
  training, SPEC C1), and this file rendered and signed as a PDF so its hash
  can be the registration's `p_evidence_sha256`
  (`scripts/render_doc_pdf.py`, then `SIGNED-ARTIFACTS.md`).
- Changing a word later means a new consent policy version and a fresh yes
  from everyone; the database allows one active training policy at a time.
