# 29 · Terms 3.7 and Privacy 3.8: tokens bought once, the coach's answer free, and what was already live — SIGNED by the founder 2026-10-27

**SIGNED by the founder, 27 October 2026** (the sign-off page
<https://claude.ai/artifact/R65WrnFbUUFr3SEGeZaikA>, which showed every change
word for word, then in chat: "I sign as drafted, question 1 A, question 2 A";
decisions log N208). **Counsel has not seen it**; the founder signed knowing
that.

    documents:   copy/terms-3.7.txt, copy/privacy-3.8.txt (the exact bytes to publish)
    replaces:    copy/terms-3.6.txt, copy/privacy-3.7.txt
    unchanged:   copy/ai-notice-3.2.txt, copy/agreement-3.1.txt
    publish as:  phase1-2026-10-27-3.8 (PUBLISH-3.8-2026-10-27.sql, the founder's step)
    asked by:    the founder, 2026-10-27, "update", to the review line of Terms 3.6 §11
                 and Privacy 3.7 §5 that N205 made false
    question 1:  A, the Willfidence reading stays and is described; document 02 gets
                 the note 02-power-score-classification-v1.3-NOTE-SIGNED-2026-10-27.md
    question 2:  A, the plan is named, with its own yes, in the version that opens it
                 below ring 5
    drafted by:  engineering, from the code; not a lawyer

The `copy/*.txt` files carry no draft mark: their exact bytes are what is
hashed and what a speaker later proves they agreed to. Their effective date
line says 27 October 2026; on another day, change it in both files and
regenerate the publish script before it runs.

## 1. Why 3.8

N205 made the coach's answer free, so Terms 3.6 §11 and Privacy 3.7 §5 ("a
written review … is paid for in tokens") became false. Fixing them means a new
version, which every speaker accepts with one tap, so this version also fixes
everything else the texts in force got wrong:

- **Terms 3.6 §2 sold monthly plans that renew.** Since 5 October (N44,
  contract §8 items 48 to 51) a purchase is a one-time package
  (`services/token_packages.py:124`, Stripe in `payment` mode), the free grant
  lands once, and nothing resets (`services/token_account.py:64`).
- **Decided and built, not yet named:** the coach's answer costs nothing
  (`services/lab_send.py:246`, `services/token_prices.py:215`); a lesson paid
  with tokens (`services/booking.py:671`, behind pricing v4); the WhatsApp
  reminder 10 minutes before a booked lesson (`services/booking.py:962`,
  to the account's number only once `BOOKING_WHATSAPP_TO_ACCOUNT` is on,
  `config.py:442`).
- **Live, and the texts in force deny it or leave it out.** A check of
  everything merged since 3.7 (27 October 2026) found these; each was verified
  against the code before drafting.

## 2. Changelog

**Terms of Service 3.6 → 3.7**

| § | Change | Code or decision it describes |
|---|---|---|
| version note | rewritten: tokens as sold, the free answer, lessons with tokens, the reminders, the reading a coach sees | — |
| §1 | WhatsApp also 10 minutes before a booked lesson and, if asked for, on practice days | `services/booking.py:962`; N153 (not built: "if you ask for it") |
| §2 | rewritten: free tokens once, packages bought once, nothing renews, tokens stay until spent; no prices or counts (the app shows them); anything priced in tokens, a lesson where the booking page offers it; the coach's answer free; access kept when tokens run out (contract §8 item 51); withdrawal from a purchase of tokens; a lesson by card or tokens, tokens back for a cancellation 12 hours before | `services/token_packages.py:124`; `services/token_account.py:64`; `services/booking.py:671`; N198 item 4; N205 |
| §10 | "does not score you, rate you" becomes "does not grade you"; the one reading, never shown to you | `services/coach_moment_read.py:23`; N104 |
| §11 | the coach may answer a take in words or on video, free, whatever the tokens held; "not asking for one" goes (nobody asks, N205); a coach sees the reading only after answering | N205; N104 |

**Privacy Policy 3.7 → 3.8**

| § | Change | Code or decision it describes |
|---|---|---|
| version note | rewritten: the two reminders, tokens, the free answer, and five things already live | — |
| §2 | Will's note about you, at most five lines | `services/speaker_memory.py:1` (WIL-74) |
| §3 | "no score … shown to you, to a coach, or to anyone else" becomes the one reading: a percentage per moment, never shown to the speaker, to a coach only after their own answer, to the founder per take | `services/coach_moment_read.py:23` (N104); `services/admin_takes.py:57` (N105) |
| §4 Talking to Will | Will is also given the speaker's own history: earlier takes in any project, what the coach sent including video words, their own earlier messages | `services/speaker_lookup.py:25` |
| §4 Will's note | new: what it holds, OpenAI rewrites it, Will reads it, the founder reads and corrects it | `services/speaker_memory.py:1` |
| §4 private | "Nobody at WillpowerLab reads it" now names what reaches a person: the coach sees the talk's audience, its call to action and the goal, with changes; the founder sees "Did this help?" answers (up to three a week quoted, no name) and the note | `services/coach_moments_queue.py:432` (N87); `services/goal_history.py:1`; `services/feedback_digest.py:36` |
| §4 WhatsApp | the lesson reminder with its join link, and practice-day reminders if asked for; no message carries feedback or recordings | `services/booking.py:962`; N153 |
| §4 payments | tokens rather than a plan; the record of what was bought and what the tokens were spent on | `services/token_packages.py:124` |
| §4a basis | the yes can also be given on a card in the Lounge that asks only this, in the same words; not asked again within 30 days of a no | `services/person_asks.py:17`; the copy hash check, `services/training_consent.py:147` |
| §4a text only | while the switch is on, OpenAI writes out the coach's video words; kept with the take, read by Will, not used for training | `services/coach_word_pairs.py:270` (N79) |
| §4c | "never shown to WillpowerLab users" becomes: short clips play to users as another speaker's voice, sound only, no name or words; users' answers held too | `services/lend_your_ear.py:21` (N119) |
| §5 OpenAI | rewrites Will's note; writes out the coach's video words (training yes only) | `services/speaker_memory.py:1`; `services/coach_word_pairs.py:270` |
| §5 Meta, Stripe | the three kinds of WhatsApp message; Stripe for tokens or a lesson by card | `services/booking.py:962` |
| §5 coaches | the answer costs nothing; a coach sees the reading only after answering | N205; N104 |
| §7 | Will's note and the events it is written from: kept while the account is open | `services/speaker_memory.py:1` |

## 3. Not in this version

- **The plan** (N203, N204), on ring 5 since migration 0495: its stress and
  readiness answers from 1 to 10 may be health data and need their own yes.
  Question 2, A: named in the version that opens it below ring 5; until then
  ring 5 holds only people who know it is a test.
- **The transcript CSV** (N156) stays inside the training yes, as N156 chose.
- **The founder-only ring 6 features** (the voice notebook, the Sunday note,
  life goals) are named before they open to speakers.
- **Training on coaches' words** stays closed (N79) until the coach agreement
  exists; nothing here opens it.

## 4. Publishing

The founder runs `PUBLISH-3.8-2026-10-27.sql` in the Supabase SQL editor:
STEP 0 alone first (a dry run), then the whole file. It registers and
activates `phase1-2026-10-27-3.8` in one transaction, leaves the training
wording (training-only-v4) alone, and ends with a one-row check. A training yes
keeps working: it passes the training policy's own approval versions
(`services/training_consent.py:147`), and migration 0412 counts any version
activated later.

Afterwards, on Railway: `BOOKING_WHATSAPP_TO_ACCOUNT=true` (N207); and, once
token holders are told, `PRICING_V4_ENABLED=1` (N198).
