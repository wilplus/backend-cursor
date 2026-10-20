# Founder lock — the AI version of your voice in practice (2026-10-12)

`LOCKED 2026-10-12 · flow yes · UI yes · words yes · backend rules yes`

Locked by the founder on 2026-10-12 (chat: "D1: Approved", "all ok, L2:
Here's how you could say it."), from two clickable prototypes:

- the walk with the AI voice: <https://claude.ai/artifact/G8Am3fR3f3SzAdTkwyUGKZ>
  (version 8), copy in `docs/design/ai-voice-practice-2026-10-12.html`;
- the Data & consent card: <https://claude.ai/artifact/1AUfoqBtZThxVbQKz1BTih>
  (version 2), copy in `docs/design/ai-voice-settings-2026-10-12.html`.

Plain-words plan with the founder's answers:
<https://claude.ai/artifact/RYMPxAqSyHinRStymsGwFr>. Decisions log N71.

It adds one step to `FOUNDER-LOCK-moment-feedback-chat-2026-10-12.md`
(section 2, steps 4 and 5) and one card to the Data & consent page
(`FOUNDER-LOCK-consent-screens-2026-10-07.md`). Everything else in those
locks stays as it is. Where this file and those disagree on the AI step or
the card, this file wins.

## 1. What it is

When the speaker practises the voice Exercise sentence and the try is not
yet better, the app plays **that same sentence, in an AI version of the
speaker's own voice, said a little better**, then the speaker tries again.

- **Same words.** The clip says exactly the words the speaker said in that
  sentence. Only the delivery changes: a little slower (pace), one pause
  before the target phrase (pause), or the target phrase standing out
  (stress).
- **Only the voice Exercise.** Never with praise (green moments, "Good
  job") and never with the Clearer version. Those lanes never call the
  voice provider.
- **What it trains.** The before/after of each practice feeds the future
  exercise picker. The AI clip itself is never a label and never enters a
  training set (L3).

## 2. The flow

1. **Exercise screen.**
   - The library video fits **exactly** (its main target was detected on
     this sentence) **and** targets the same problem the severity picker
     chose → the locked Exercise: the video and its instruction.
   - Otherwise → the AI clip takes the video's place: L2, the clip, L3.
2. **The try** (the locked recorder). The machine checks it (willfidence
   Δ ≥ +0.05, as locked).
3. **Better** → the locked "Good job". No AI clip.
4. **Not yet** → in place of the signed encouragement, one app bubble:
   - the first AI clip after a try: L4, the clip, L3;
   - every later one: L5, the clip.
   Then the locked "Practise again" and "Skip".
5. **At most 3 AI clips per exercise**, the Exercise screen's one included.
   The locked 3-try limit and the move-on line stay.

## 3. How it looks

- One grey app bubble with the grey profile picture, as every app message.
- **Audio only.** The label L1 and the one player; never the words.
- **Never plays by itself.** The speaker taps play.
- The lens and the chat show the same bubble (one thread, stored once).
- No question, no consent screen and no recording task inside the walk.
- When the clip fails its check, the provider is down, the limits are
  reached, or the AI voice is off: no bubble; the screen is the locked one.

## 4. The AI voice

- **Made from Take 1**, in the background, from its cleanest speech (about
  two minutes). Made **once** per speaker and reused; never one per
  session. If Take 1 is too short or too noisy, none is made, and the next
  Take tries again.
- **Agreed by using the app.** It is part of the Terms (L12) and the
  Privacy Policy (L13), on from the start. The founder chose this over a
  separate tick (D3a, D3b). Counsel reviews it before launch. It is built
  for every speaker and always on (founder 2026-10-12: "build it as for
  everyone", "it is always enabled"): it works whenever the ElevenLabs key
  is set; `AI_VOICE_ENABLED=0` is only an emergency off.
- **Data & consent card** (on for everyone): L6, L7, Delete (L8, confirm
  L9). Delete removes the voice at ElevenLabs and here, with every clip made
  from it, and stops new clips. Off: L10 and Turn on (L11), which makes it
  again from the next Take.

## 5. Backend rules

```
voice Exercise only     willfidence: the lowest sentence, voice weaker (S ≤ W), as locked
problem                 severity per problem (pace, pause, stress), each 0–1, against the
                        speaker's own baseline; the highest wins if ≥ 0.4, else no exercise
video or AI clip        exercise fit = exact AND main target = the chosen problem → video
when it is made         only in this lane: when Practise is tapped (video fits), or when
                        the Exercise screen opens (no video fits); one clip per exercise,
                        reused for every appearance; ONE generation per exercise
                        (founder 2026-10-12): a clip that fails its check is not
                        remade, it is simply not shown
what is sent            the speaker's own transcript of the sentence, with the delivery
                        controls Eleven v4 supports; no unrestricted prompt
checked before shown    decodes, not clipped, sane length and silence, the words kept
                        (re-transcribed with the existing Whisper), and the change really
                        there; failed → never shown
measured after          the next try on the chosen problem only: improved, similar,
                        worsened or inconclusive; stored, never shown
limits                  per speaker per day, per app per day, and the month's credits
                        (warning at 28,000, hard stop at 38,000 of 40,000)
```

Every provider call goes through the processing-authorization path, as
CLAUDE.md requires. Deleting the account also deletes the AI voice.

## 6. Words signed on 2026-10-12

| # | Where | Words |
|---|---|---|
| L1 | label on every AI clip | AI version of your voice |
| L2 | Exercise screen, no video fits | Here's how you could say it. |
| L3 | after L2, and after L4 | Now try saying it like that. |
| L4 | the first "not yet" | That was good. But what if you said it more like this? |
| L5 | every later "not yet" | Not yet. Listen to how you sound and how you might sound. Keep calm and try again. |
| L6 | card title | AI version of your voice |
| L7 | card, on | Made from your first Take to create your practice examples. Only you hear it. |
| L8 | card button, on | Delete |
| L9 | card confirm | Delete your AI voice? We delete it at ElevenLabs and here, with every example made from it, and we stop making examples. Your own recordings stay. |
| L10 | card, off | Off. Turn it on and we'll make it from your next Take. |
| L11 | card button, off | Turn on |
| L12 | Terms, "What the service does" (for counsel) | WillpowerLab makes an AI version of your voice from your recordings, to create practice examples that only you hear. ElevenLabs, a voice AI company, builds it for us. You can turn it off and delete it at any time in Data & consent. |
| L13 | Privacy §5, replacing "OpenAI is the only AI provider…" (for counsel) | OpenAI and ElevenLabs are the AI providers that receive your audio or your transcript: OpenAI to transcribe it and write your feedback, ElevenLabs to make the AI version of your voice. |

## Decided after the lock (2026-10-15)

- **When it is made (founder 2026-10-15, option B: "start it the moment
  you know it will be needed").** The clip no longer waits for the
  Exercise screen. The first moment the backend knows which moment carries
  the voice exercise is the end of the bake (the Manager's stored feedback
  block). Right there the practice for that moment is opened server-side,
  exactly as the walk would open it (its exercise when one is offered,
  else the moment's own words), and the clip's job starts in the bake's
  lane. The walk's own ask when the Exercise screen opens or Practise is
  tapped stays as the fallback and finds the clip already made or on its
  way. Everything else in section 5 stands: one clip per exercise, one
  generation, checked before shown, the same limits and the same permits.
- A voice still being made from Take 1 when the clip is asked for is
  waited for (a short, bounded retry) instead of waiting for the next ask.

## Decided after the lock (2026-10-16, WIL-82)

**Not only how to say it but why.** The founder (Linear WIL-82, and the
six answers in the Claude Code session of 2026-10-16): under the player,
in the same grey bubble, one sentence says what the speaker's own numbers
showed, what this version does differently and why that sounds less flat
and more engaging to the listener. It is there every time the clip
appears, on the Exercise screen and on every "not yet", in the walk and in
the Lounge chat alike; no second bubble, nothing new stored in the thread.

- **Four signed sentences**, filled in by the server from the stored
  selection: the problem the picker measured against the speaker's own
  usual delivery (pace, pause, stress), or the default when nothing reached
  the line. No model writes them; no number is in them (AC-9).
- **Every claim comes from the data.** "You said this faster than you
  usually do" is only said when the picker measured it; the default clip
  (stress on the main point, nothing measured) says "Nothing was off here"
  instead. The sentence is only sent with a clip that passed its check, so
  the change it names was really heard.
- **The speaker's target words may be quoted** (L15, L16, L17): the two to
  four words cut from their own transcript that the clip pauses before or
  makes stand out, never the whole sentence. This amends section 3, "never
  the words", by exactly that much.
- The pace sentence names no words. A clip still on its way or one that
  failed its check says nothing, as before.

| # | Where | Words |
|---|---|---|
| L14 | under the player, pace | You said this faster than you usually do. This version is a little slower. Slower gives the listener time to take each thought in, so it is easier to follow. |
| L15 | under the player, pause | You ran straight into “‹the phrase›”. This version stops for a moment before it. The pause makes the listener wait for what comes next, so it lands. |
| L16 | under the player, stress | You said this flatter than you usually do. This version makes “‹the phrase›” stand out, said a little stronger. One point that stands out gives the sentence a shape, so it is less flat and keeps the listener with you. |
| L17 | under the player, the default clip (nothing reached the line) | Nothing was off here. This version just makes “‹the phrase›” stand out a little more, so the point lands and the sentence has a shape. |

## Decided after the lock (2026-10-18, fillers)

**A fourth problem: fillers.** The founder (Linear "Evaluate retaining
filler words in transcripts", and the answers in the Claude Code session of
2026-10-18): the transcript stays clean, as locked on 2026-07-20 (the
hesitations are removed silently, the Ideal Text screen does not change).
The speaker learns about their fillers in one place, the AI clip.

- **The picker** measures fillers against the speaker's own usual delivery
  on this Take, the same way it measures pace, pause and stress: hesitations
  per 100 words above their own median (`AI_VOICE_FILLER_GAP_PER_100` more
  is the line). The hesitations are exactly the closed list the transcript
  fence removes ("um", "uh", "erm", "hmm", ...), never "like", "so" or
  "right".
- **The clip** says the speaker's own sentence with those tokens left out
  and nothing else changed. This amends section 1, "same words", by exactly
  that much: the words the clip says are the words the Ideal Text shows. The
  check hears the clip and refuses it if one hesitation is heard.
- **One signed sentence**, L18, under the player, every time the fillers
  clip appears. No number, no words quoted.
- **Measured after**: the next try on fillers only, from its own transcript
  (hesitations per 100 words, against the same line as the pick): improved,
  similar, worsened or inconclusive. Stored, never shown. The admin Take
  view shows the problem practised, the outcome and, for fillers, the rate
  before and after; that is the awareness test, read after ten speakers.
- **Uploaded Takes** have no AI voice, so they get no clip and no sentence;
  nothing else changes for them.
- Section 5's problem list reads `pace, pause, stress, fillers`; migration
  0475 widens the stored exercise accordingly.

| # | Where | Words |
|---|---|---|
| L18 | under the player, fillers | You said this with a few ums and uhs. This version says it without them. Without them each thought comes out whole, so it sounds sure and is easier to follow. |

Founder-Approved: Artur, Claude Code session 2026-10-18 ("you have my OK to
the previous one", on the task text that carried L18).

## Decided after the lock (2026-10-18, words first)

**The clearer version's voice.** The founder (Claude Code session,
2026-10-18, "ok, push to prod" on
<https://claude.ai/artifact/Ut2SqvHCoJ1hvH8dp17yQe>) amends section 1's
"Only the voice Exercise. Never ... with the Clearer version": after a
clearer-version try that is not yet better, the AI clip says the words the
speaker accepted (or their own after "Keep my words"), the same bubble, the
same lines L1 to L5 and L14 to L18, at most three per exercise. A try that
sounds better gets the Good job and no clip. The clip is asked when the
practise of the clearer words starts, never prewarmed at the bake: until the
speaker accepts, the words are not chosen. Praise still never gets a clip.

## 7. Order of work

Build end to end, test with the founder's own voice, then counsel (L12,
L13, the data processing agreement with ElevenLabs, the AI Act Article 50
assessment), then launch.

Counsel approved L12 and L13 (founder, 2026-10-20, on the flow page's
first review).
