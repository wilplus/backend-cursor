# The training switch wording, version 3 — SIGNED by the founder 2026-10-15

**SUPERSEDED the same day by `27-training-consent-wording-v4-SIGNED-2026-10-15.md` (never registered).** SIGNED by the founder, 15 October 2026, in chat ("I sign the 3.6 pack of 15 October 2026 as drafted"; decisions log N72). **Counsel has not seen it**; the founder signed knowing that.

    artifact_kind:       training_consent_wording
    version:             training-only-v3 (the consent_policy_version it registers)
    succeeds:            23-training-consent-wording-v2-SIGNED-2026-10-08.md (training-only-v2)
    approving_authority: Artur Willoński (founder and controller)
    approved_at:         2026-10-15 (in chat: "I sign the 3.6 pack of 15 October 2026 as drafted"; decisions log N72; counsel has not seen it)
    wording by:          engineering, in the style of counsel's v1 wording of 2026-10-01
    object_key:          phase1-2026.1/legal/training-consent-wording-v3.pdf
    sha256:              [[computed from the signed PDF at registration time]]
    requires:            Privacy 3.6 and Terms 3.6 published (25-privacy-terms-3.6-new-features-SIGNED-2026-10-15.md)

**What changes from v2, and why.** Asked by the founder on 2026-10-14: users
who accept should be free to use the app and he should be able to train on
their data, with training kept opt-in (the founder's answer in chat: "Keep
opt-in, widen it"). v2 named practice text, the coach's words and answers,
and measurements. It did not name **what a speaker writes to Will** in the
Lounge, which `13bddb7` (#1055) now keeps and the founder wants to learn
from. v3 adds those words. One change only; everything else in v2 stands.

The training yes stays its own act: off at sign-up, never pre-ticked, never a
condition of using WillpowerLab (GDPR Art 7(4); counsel 2026-10-01). Putting
training inside the Terms acceptance was considered and not drafted: a
consent bundled with the contract is not freely given, and the bundled MLC2
consent was retired for that reason (`routes/v2/mlc2_consent.py`,
`BUNDLED_CONSENT_RETIRED`).

## The switch sentence (`p_toggle_copy`)

```
Use my practice text, my coach's words and answers about it, what I write to Will, and measurements of my practice to train the models that give every WillpowerLab speaker feedback.
```

sha256 of exactly those bytes (UTF-8, no trailing newline), computed by
engineering on 2026-10-15:

```
6a8ab6eeefb59c0ef481bbdd8e05f90fb3b1f07330a949586221d45fe4828bd9
```

## The lines above the switch

v2's eight lines, with one line added as line 4 (the rest renumbered, words
unchanged):

1. Text and numbers only. No recording of your voice, and no clip of one, is ever copied or sent for training.
2. Off unless you turn it on. Saying no costs you nothing.
3. Your coach's words include their line on a moment and their word for a take.
4. **What you write to Will includes Will's answers to you. (new)**
5. The numbers are measurements such as your pace and pauses, and whether an exercise helped you. They stay with us.
6. A coach may hear a moment of yours, without your name, to answer a question that teaches our software.
7. The trained models write feedback for every speaker. We test that they do not repeat your text.
8. OpenAI trains the text models for us, in the United States, under the European Commission's standard contractual clauses.
9. Turning it off deletes your training copies and keeps you out of any new training. A model already trained stays.

The lines live in the frontend (`frontend-cursor/src/lib/legal/dataConsentCopy.ts`,
`trainingBeforeLines`) on the design-locked consent screens: the Data &
consent card and "Turn on the learning?". Adding line 4 is a change to a
locked screen, so it waits for the founder's yes under the consent-screen
lock (frontend `docs/LOCKS.md`) and lands with a `Founder-Approved:` line.

## The registration call (template)

Run in the same transaction as the 3.6 publish, as `PUBLISH-3.5-2026-10-08.sql`
did for v2, using `supersede_mlc2_training_consent_policy_v1` (migration 0458):
v2 is retired at the instant v3 starts, so every v2 yes reads as off (25-…,
D1). The publish script for 3.6 is written after signature, from the 3.5 one,
with these values: approval reference `training-consent-wording-v3`, the
hash above, the sentence above (apostrophes doubled inside the SQL literal),
`training-only-v3`, terms `3.6`, privacy `3.6`.

## What this does and does not do

- It fixes the words and, once registered, makes a v3 yes possible.
- No code trains on Lounge messages today. The lane that does must read the
  v3 yes per speaker, like every other lane (`services/pair_consent.py`), and
  is its own reviewed PR (25-…, E8).
