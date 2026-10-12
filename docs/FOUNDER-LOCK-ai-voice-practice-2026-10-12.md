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

## 7. Order of work

Build end to end, test with the founder's own voice, then counsel (L12,
L13, the data processing agreement with ElevenLabs, the AI Act Article 50
assessment), then launch.
