# 28 · Privacy 3.7: what Will is given (APPROVED 2026-10-15)

**Approved by the founder in chat, 15 October 2026: "approve all"**, and the
same day, told that 3.6 was already published: "yes, go ahead as 3.7"
(decisions log N74). Counsel has not seen it. Published 2026-10-15 12:49 UTC
by the founder (`PUBLISH-3.7-2026-10-15.sql`, `phase1-2026-10-15-3.7`).

## Why

The founder wants Will, the Lounge assistant, to read the speaker's whole
talk, slide by slide, to answer "what do I say on slide 4?" or "does my talk
match my title?". Privacy 3.6 §4 promises Will only "your slide titles … and
the beginning of your Ideal Text". Since backend #1069 (merged 2026-10-15
07:45 UTC), Will also reads the Lounge thread: the summary after a Take, the
walk's steps and the coach's word. Privacy 3.7 discloses both.

Privacy 3.6 cannot be changed in place: it is in force since 2026-10-15
08:42 UTC (`phase1-2026-10-15-3.6`, privacy `3e35aec5…`) and a receipt
already proves agreement to its exact bytes. So the change is a new version.

## What changes (`copy/privacy-3.7.txt`, sha256 `ac0942ac…`)

Privacy 3.7 is `copy/privacy-3.6.txt` with these changes and nothing else.

1. **§4 "Talking to Will"**, the founder's words, verbatim:

   > Talking to Will. Will is the AI assistant in the Lounge. To answer you,
   > Will is given what you write and your recent messages in the Lounge,
   > including the summary after each take and your coach's word. He is also
   > given your current project: its title, what each of your slides says,
   > your Ideal Text slide by slide, how many takes you have recorded, and
   > whether your coach's feedback is in. If your talk is long, he gets the
   > slides you ask about in full and the others by their titles. Will only
   > ever sees your own project. Your conversation is kept in your account so
   > you can come back to it, and you can clear it at any time.

   The next paragraph ("Your conversation with Will is private. …") and the
   legal basis line are unchanged.
2. **§7, what OpenAI receives**, the founder's words, verbatim: "what you
   write to Will, your recent Lounge messages and your project as described
   in section 4, in order to answer you;"
3. **The version lines**, needed for a new version (engineering, for the
   founder to see before publishing):
   - "Version 3.7. Effective 15 October 2026."
   - The opening paragraph starts: "Version 3.7 replaces every earlier
     version. It says more fully what Will is given to answer you in the
     Lounge (sections 4 and 7). Version 3.6 described what WillpowerLab now
     does that earlier versions did not: …" (the rest as in 3.6).
   - "a yes you gave under an earlier version does not carry over" becomes
     "a yes you gave before version 3.6 does not carry over": a training yes
     given under 3.6 stays on under 3.7 (training-only-v4 is unchanged).

**Checked:** nothing else in Privacy 3.6, Terms 3.6 or AI notice 3.2 says what
Will is given. Privacy §2 ("What you write to Will in the Lounge"), §4's
service paragraph, §7's AI providers paragraph and §14 (California) name the
conversation without listing what Will is given; Terms §1 ("an AI assistant
that knows the app and your project") and AI notice ("Will … is an AI
assistant") stay true.

## What does not change

Terms 3.6, AI notice 3.2, the agreement (3.1 bytes), the countries, the five
purposes and training-only-v4 (its approval keeps privacy-3.6 as the version
it was signed against; a new yes needs 3.6 or a later version accepted,
migration 0412). Dry-run 2026-10-15 on a disposable database copied from the
3.6 rehearsal: 3.7 active with the approved bytes and the United States, v4
still the one wording in force, a second run stops, and after accepting 3.7 a
training yes is recorded and counts as on.

## Risks the founder accepted

- OpenAI now receives each slide's points and the full Ideal Text, slide by
  slide, for chat answers, and the coach's word in the Lounge thread.
  Counsel has not seen this.
- Until 3.7 is published, #1069 already gives Will the summary, the walk's
  steps and the coach's word, which Privacy 3.6 names only as "your recent
  messages".
