# The training switch wording, version 4 — DRAFT, approved on screen by the founder 2026-10-15

**Approved by the founder on the clickable prototype, 15 October 2026** ("this looks perfect", consent prototype <https://claude.ai/artifact/YCM8rQKkkwA2HKb4UYajeo>). To be signed (PAdES) as a PDF before registration. **Counsel has not seen it.**

    artifact_kind:       training_consent_wording
    version:             training-only-v4 (the consent_policy_version it registers)
    supersedes:          26-training-consent-wording-v3-SIGNED-2026-10-15.md (training-only-v3), never registered
    approving_authority: Artur Willoński (founder and controller)
    wording by:          the founder, on the prototype, 15 October 2026
    object_key:          phase1-2026.1/legal/training-consent-wording-v4.pdf
    sha256:              [[computed from the signed PDF at registration time]]
    requires:            Privacy 3.6 and Terms 3.6 published, with the §9 changes of 25-…

**Why v4.** The founder shortened every screen that asks for the training
yes (decisions log N73). v3 was signed the same morning and never
registered, so no speaker holds a v3 yes and nobody has to be asked again
because of this change.

## What the speaker sees

The same three parts on every screen that asks: "Three things to confirm",
the question before a Take (only while training is off), and the Help
improve WillpowerLab card in Data & consent.

```
Can we make the product so much better for you?
We'd train our feedback on your practice. Read more
[ ] Yes, make it so much better.
```

- **Read more** opens Privacy 3.6 section 4a in its own scrolling window,
  with **Continue** to close it.
- **"Your practice"** is defined in Terms 3.6 §8: the words of the passages
  practised, the numbers measured from them, what the coach writes and
  answers about them, and the chats with Will; never the sound of the
  recordings.
- On the screen before a Take the tick is the **Yes** button (Skip below
  it); on the card it is **Turn on** / **Turn off**.
- No lines above the switch. v3's nine lines are gone; their content is in
  Privacy §4a, one tap away.

## The switch sentence (`p_toggle_copy`)

```
We'd train our feedback on your practice.
```

sha256 of exactly those bytes (UTF-8, straight apostrophe, no trailing
newline), computed by engineering on 2026-10-15:

```
ece8d1da2709971302542a490e41cf44d071028918daadc1880d65e339aac286
```

## Risks the founder accepted (engineering's notes for counsel)

1. **No withdrawal notice where the yes is given.** GDPR Art 7(3) requires
   the person to be told, before consenting, that they can withdraw. On
   these screens it is only behind Read more (Privacy §4a, "When you turn it
   off"). Engineering offered "You can turn it off any time." in the tick
   and a one-line footnote; the founder declined both.
2. **"Your practice" carries the scope.** The sentence names no category;
   the definition is in the Terms, and the full list in Privacy §4a. A
   regulator may read the on-screen yes as covering less than the
   definition, chats with Will most of all.

## Registration

As for v3 (26-…), in the same transaction as the 3.6 publish, by
`supersede_mlc2_training_consent_policy_v1`: approval reference
`training-consent-wording-v4`, the hash above, the sentence above
(apostrophe doubled inside the SQL literal), `training-only-v4`, terms
`3.6`, privacy `3.6`.
