# Privacy Policy 3.1 → 3.2 — the training changes (DRAFT for counsel)

**STATUS: DRAFT.** Written by engineering at the founder's request
(SPEC-DECISIONS-LOG §N11, answer 5: "I draft it; the lawyer reviews; you
approve"). Counsel reviews; the founder approves the final text; only then is
it registered as a new processing policy version that every user re-accepts
(SPEC C1). Nothing here is published or switched on.

It changes only what training needs. Every other line of
`copy/privacy-3.1.txt` stays as it is. Each change below gives the section, the
current text where one exists, and the proposed text.

**Two blanks must be filled before this can be published**, and training stays
off until they are (§N11, answers 3 and 4):

- `[[TRAINING PROCESSOR]]`: who trains the models, and where.
- `[[TRANSFER MECHANISM]]`: EU only, or outside the EU under standard
  contractual clauses.

Decisions this text rests on: §N10 (the founder's signed wordings, counsel's
nine answers) and §N11 (the founder's eight answers).

---

## Change 1 — the opening

**Current (3.1):**

> Version 3.1 replaces every earlier version. Earlier versions required you to
> agree that your practice data could be used to train models shared with other
> users. This version does not ask for that. Under this version your recordings
> are used to deliver your own coaching: they are not pooled with other users'
> data and they are not used to train models. If that ever changes, it changes in
> a new version of this policy, which you will be asked to accept before it
> applies to you — see section 12.

**Proposed (3.2):**

> Version 3.2 replaces every earlier version. It adds one thing, and only if you
> choose it: you can let us keep separate copies of short moments from your
> recordings to train WillpowerLab's models. That choice is off unless you turn
> it on, it is on its own screen, and everything else in WillpowerLab works the
> same without it. Earlier versions bundled training into the agreement you had
> to accept; any yes you gave that way does not count, and nothing recorded
> under it is used for training. Section 4a explains the new choice.

## Change 2 — section 4, the contract basis

**Current:** "…it does not cover training models, analytics about you, or
advertising, none of which we do."

**Proposed:** "…it does not cover training models, analytics about you, or
advertising. We do not do analytics or advertising. Training happens only with
the separate choice in section 4a."

## Change 3 — section 4, the enforcement sentence

**Current:** "Under this version we do not use anyone's recordings to train
models, and that is enforced rather than merely stated: while this version is in
force our systems refuse to register a processing policy that would permit it.
Changing it would take a new policy version and your acceptance of it."

**Proposed:** "We use a person's recordings for training only when that person
has turned on the choice in section 4a, and that is enforced rather than merely
stated: our systems refuse to keep a training copy for anyone who has not."

## Change 4 — a new section 4a

> **4a. HELPING TO IMPROVE WILLPOWERLAB — OPTIONAL**
>
> If you turn on **Help improve WillpowerLab**, we keep separate copies of short
> moments from your recordings — the audio of that moment, its words, and your
> coach's rating of it — and use them to train WillpowerLab's models.
>
> *Legal basis:* your consent (Article 6(1)(a) GDPR). You give it on its own
> screen, by turning the switch on. It is never on when you sign up, never
> pre-ticked, and never a condition of using WillpowerLab. You can turn it off
> at any time.
>
> *What we copy:* only moments from takes you record while the switch is on.
> Nothing recorded before you turn it on is copied.
>
> *How long we keep the copies:* until you turn the switch off or delete your
> account. If you delete a project while the switch is on, the training copies
> made from that project stay until you turn the switch off.
>
> *When you turn it off:* your training copies are deleted. Anything already
> used to train stays in that training, but it won't be used again. The models
> we have trained are kept; they are built from anonymised data and hold no
> personal information.
>
> *The record of your choice:* we keep the record of when you turned the switch
> on and off, including after you delete your account, for as long as it is
> useful for training our models.
>
> *Who trains, and where:* `[[TRAINING PROCESSOR]]`, `[[TRANSFER MECHANISM]]`.

## Change 5 — section 5, who else receives your data

**Add, under "AI providers":** "If you turn on the choice in section 4a, your
training copies are processed by `[[TRAINING PROCESSOR]]` to train
WillpowerLab's models, and by no one else."

## Change 6 — section 6, transfers

**Add:** "Training copies (section 4a) are transferred `[[TRANSFER MECHANISM]]`."

## Change 7 — section 7, how long we keep it

**Add after the recordings paragraph:** "Training copies, if you chose to make
them (section 4a): kept until you turn the choice off or delete your account."

**Add after the agreement-record paragraph:** "Record of your training choice:
kept, including after you delete your account, for as long as it is useful for
training our models."

## Change 8 — section 9, what survives deletion

**Current:** the list "Two things survive deletion".

**Proposed:** "Three things survive deletion", adding:

> - The record of your training choice (section 4a): when you turned it on and
>   off. It holds identifiers and timestamps, not your recordings or anything
>   you said, and we keep it for as long as it is useful for training our
>   models.

**Add after the list:** "Your training copies do not survive an account
deletion: they are deleted with everything else."

---

## For counsel

The positions above are the ones counsel gave (§N10). Three of them are worth a
second look in the final text, because the product decisions they carry were
made against the recommended option (§N11):

1. **The consent-record period** is "as long as it is useful for training our
   models", with no fixed end (§N11 answer 1). Is that specific enough under
   Art. 5(1)(e) and Art. 13(2)(a)?
2. **"Built from anonymised data and hold no personal information"** is stated
   on counsel's advice; no technical check verifies it for a given model (§N11
   answer 2). Is the statement acceptable as written?
3. **The two blanks**: the processor and the transfer mechanism.
