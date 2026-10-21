# Where the Take loop works and where it doesn't (version 1.0)

**Date:** 2026-10-19. **Scope:** the core loop only (founder's pick): a Take
is recorded → transcribed → split by slide → the Ideal Text → the feedback
→ the next Take. Coach review, Confident Voice, practice, booking and chat
are out of scope.

**How this was tested**

- The offline half of the loop was run for real, as production code on
  made-up Whisper-shaped input, across 16 scenarios. That half is the word
  clean-up, the slide split, the Ideal Text builder, the Take 2 merge,
  helper words, the speech gate and the Whisper request builder. The probe
  is `scripts/probe_take_loop_limits.py`; its full output is in the
  appendix. It never touches a database or a provider.
- Every other claim was read from the code at `3f2347a` and is marked
  *code-read*.
- Claims taken from the audit ledger and backlog are marked *ledger* with
  their date.

**What this does not cover, honestly**

- No real recording was transcribed. No LLM or feedback Manager call was
  made, because there is no provider key in this environment.
- So nothing here measures how accurate Whisper is, how good the feedback
  wording is, or how often the LLM layers fall back.
- The instruments for that exist but have never produced a result:
  - The transcript/slide golden set (`scripts/measure_transcripts.py`,
    D-ML-1) has never had a baseline run. `docs/audit/measure/` is empty.
  - The founder's sealed golden set has no sealed surface yet.
  - The prompt evals are 22 engineering seed cases with no recorded run.
- **The biggest limitation of version 1.0 is that its accuracy is unmeasured.**

---

## 1. The test plan and what happened

Result key:
- **Works:** the output is right.
- **Degrades:** the output is usable but wrong in a visible way.
- **Breaks:** words are lost, or the loop stops.

| # | Use case | Result | What happened |
|---|---|---|---|
| S01 | Short deck talk, taps between sentences | **Works** | One paragraph per slide, the words verbatim. |
| S02 | The tap lands 0.7 s after the speaker starts the next slide | **Degrades** without the measured clock offset; **works** with it | Without the offset, "The fix." is left on slide 1 and slide 2 starts "Is a guided…". A paragraph break also adds a full stop and a capital letter mid-sentence. The front end now sends the offset. If measuring it fails, the code skips it with only a warning (`services/lab_recording.py:307-316`). |
| S03 | Deck uploaded, speaker never taps | **Degrades** | Every word goes onto slide 1 of the Ideal Text. The per-slide transcript shown under each slide is saved **empty for every slide** (`build_slide_transcripts` returns `''` when there are no taps). |
| S04 | Goes back to a slide (1 → 2 → 1 → 3) | **Works** | The return-visit words join slide 1, in slide order (founder rule of 2026-10-04). |
| S05 | No deck, 3-minute monologue | **Works** | 12 readable paragraphs of about 200 characters, no slide claims. |
| S06 | Run-on speech: Whisper gives no punctuation, pauses shorter than 0.6 s | **Degrades** | Paragraphs are cut at the 300-character hard cap in mid-sentence. The full stops are added by the paragraph closer, not by the speaker. |
| S07 | English fillers ("um", "umm", "uh") on a live Take | **Degrades** | See L2. Pieces of a live Take carry no language, so "Um" and "umm" **stay in the Ideal Text**. Only the fillers that are safe in every language are removed ("uh", "erm"). Removing a filler leaves a stray comma: "we should, launch in May". |
| S08 | Repeated words | **Degrades** | "We we" → "We" is right. But "I had had enough" → "I had enough", "that that plan" → "that plan" and "Bye bye" → "Bye" **change what the speaker said**. |
| S09 | Sentence capitals in other languages | **Degrades** for Polish, Ukrainian and Russian | "świetnie" and "łącznie" stay lower-case after a full stop, and so does Cyrillic text. The capitalisation regex only covers `a–z` and `à–ÿ` (`transcript_smoothing.py:76`). English and German work. |
| S10 | Long talk (about 55 min of speech) | **Breaks** past about 25 minutes | See L1. |
| S11 | Take 2 re-records one slide; the speaker had hand-edited another | **Works** | Only slide 2 is replaced. Slide 1 keeps its words and slide 3 keeps the speaker's edit. |
| S12 | Take 1 used a deck, Take 2 didn't | **Works as designed, surprising to a user** | The slides can't be proven, so the whole Ideal Text becomes Take 2's words (`follow_the_take`). Slide 2's Take 1 words leave the current text; they remain in History. |
| S13 | Helper words | **Works** | The 8-word cap and the in-order check hold. A pick no longer matches once the next Take rewords the slide ("twelve" → "12"); by design, locked picks are carried over. |
| S14 | Speech gate | **Degrades** at the edges | Silence is refused and 1 s of speech is accepted. A quiet speaker at −48 dBFS (far mic) is **refused as "no speech"**. **60 s of fan noise at −40 dBFS is accepted** and sent to Whisper. The floor is a fixed −45 dB (`audio_metrics.py:23`), not relative to the recording. |
| S15 | The Whisper call a live Take makes | **Degrades** | See L3. No language is sent, and the English filler prompt goes out on every Take, whatever language is spoken. |
| S16 | One piece in a decked Take whose slide is unknown | **Degrades quietly** | The piece silently joins the slide before it. The text is kept, but its slide is a guess. |

---

## 2. The limitations, most serious first

**L1. Talks longer than about 25 minutes lose their end on Take 1. (*Probe + code-read.*)**
- The Take 1 Ideal Text is cut to 20,000 characters, `text[:_MAX_BLOCK_CHARS]` at `services/ideal_text_block.py:253`. That is about 25 minutes at 150 words a minute.
- The pieces and paragraphs past the cut are not trimmed: 192 of them in S10. They point past the end of the text.
- The document builder itself allows 40,000 characters (`transcript_document.py:43`). Text over 20,000 characters gets no paragraph identities (`mint_machine_parts`, `ideal_text_parts.py:771`), and a speaker's edit over 20,000 characters is refused (`ideal_text_parts.py:273`). So for a long talk, locks and helper words are unavailable on Take 2 as well.
- Further caps apply above that:
  - Whisper accepts at most 25 MB. After compression to 48 kbps mp3 that is about 70 minutes; beyond it, transcription fails and the queue retries until it gives up.
  - On the Vercel upload lane: requests to a Vercel function are capped at 4.5 MB, which at the recorder's 48 kbps (`useDualCaptureMic.ts:349`) is about 12 minutes of audio. The function itself stops at 300 s. Both apply only if `NEXT_PUBLIC_UPLOAD_PROXY_URL` (the Cloudflare upload Worker) is **not** set in production; **check it**.

**L2. English hesitations stay in the Ideal Text. (*Probe + code-read; confirm with one query.*)**
- The filler list is chosen by the piece's `language` (`transcript_document.py:265`).
- The live Take writer never sets one (`recording_persistence.py:58-68`), so every live Take uses the "unknown language" list. That list leaves out "um" and "umm", because they are real words in German and Portuguese.
- Whisper is also prompted to *write the fillers out* ("Umm, let me think like, hmm…", `openai_service.py:65`). So they are transcribed and then not removed.
- To confirm: count recent lab snippets in `charisma_snippets` (or `$SNIPPETS_TABLE`) with `language IS NULL`.

**L3. Every Take is transcribed as if it might be English. (*Code-read.*)**
- `transcribe_recording` reads `session_context["language"]` (`recording_transcription.py:81`). The intake drops any key not in `_FIELDS` (`intake_context.py:85-89`), and `language` is not in it.
- So the fix of 2026-07-29 (send the language and drop the English prompt for non-English speech) only works for imports, never for a live Take.
- For a Polish or German speaker, Whisper auto-detects the language with an English prompt in front of it. Whisper is known to drift toward English or mixed output in that case, but this has **not been measured** here.
- The detected language is saved afterwards, so later Takes could use it.

**L4. Slide accuracy has never been measured. (*Ledger 2026-07-26 to 10-06 + probe S02, S03, S16.*)**
- Words are assigned to the slide on screen when each word starts. The clock offset fixes a constant lag; it does not fix a speaker who taps early or late.
- With no taps everything goes to slide 1, and the per-slide transcripts are empty.
- A piece of unknown slide quietly joins the slide before it.
- The D-ML-1 baseline, which reports the wrong-slide share, has never been run.

**L5. The Ideal Text tidies more than "what the speaker said". (*Probe S06, S08, S09.*)**
- Grammatical double words are removed ("had had", "that that").
- A paragraph break inside a sentence adds a full stop and a capital letter.
- Polish and Cyrillic sentences don't get a capital letter.
- Each case is small, but they work against Never-rule 5 and against speakers' trust in "my words".

**L6. The feedback layer is fragile and runs on budget fallbacks. (*Ledger 2026-09-23 to 10-06; not re-measured.*)**
- Only 16 pieces get the LLM layers (`WILLAB_PIECE_LLM_BUDGET`). In a sample Take, 11 of 12 verdicts came from word overlap rather than entailment (`PIPELINE_WORK_LEDGER.md:456-465`).
- An item whose span can't be proven is dropped, so its block shows nothing (A161).
- After an accepted rewrite, the bookmark is not re-anchored (A164).
- A lane with no defensible candidate is logged but not frozen with the Take (A166).
- Nobody has confirmed that V3 feedback actually serves real speakers rather than returning `feedback_status 'failed'` (A052b, in `FOUNDER-QUEUE.md`).
- The Ideal Text read path has about 15 swallow-all `except` blocks (`_tracked_changes_block`). The Manager runs live at 2–40 s when the bake is missing.

**L7. The loop doesn't yet know whether the next Take got better. (*Ledger B1.5, 2026-10-06.*)**
- A paragraph whose words change gets a fresh id (`ideal_text_parts.py:373-420`), so there is no per-paragraph "did it improve" outcome.
- The product promise (feedback → better next Take) is not measured anywhere.

**L8. Browser and recording edges. (*Code-read + probe S14.*)**
- The recorder supports only `audio/webm` (`useDualCaptureMic.ts:136`). A browser without it gets "Voice capture isn't supported in this browser." That includes older Safari: as far as I know, Safari only gained webm recording in 18.4. I didn't re-check that here; worth a test on an older iPhone.
- Fan or room noise above −45 dB passes the speech gate and reaches Whisper. Whisper is known to invent text on non-speech audio.
- A quiet speaker below −45 dB is refused with "no speech".

---

## 3. What the tool is good for today (best fit)

- **Talks of 1–20 minutes** in English or another supported language, with or without a deck. 20 minutes keeps a margin under L1.
- **A deck with roughly one tap per slide, tapped near the start of each slide.** Going back to a slide is handled.
- **Re-recording one slide or a few slides** on Take 2 and later. The merge is per slide and keeps edits on slides that weren't re-recorded.
- **A laptop or phone mic at normal speaking distance in a quiet room.**
- **A recent Chrome, Edge or Firefox; Safari 18.4 or later.**

**Not a good fit yet, so tell the speaker:**
- Talks longer than about 25 minutes.
- A deck without taps, if the speaker expects per-slide text.
- Switching between deck and no-deck from one Take to the next.
- Non-English talks, where it is unknown how much L3 degrades accuracy.
- Noisy rooms and far mics.
- Any claim that the feedback is "measured", until L6 and L7 are closed.

---

## 4. Recommended adjustments, in order

Each item is small unless marked otherwise, and each is a separate PR.

1. **Carry the detected language onto every piece (fixes L2; prepares L3).**
   - Set `language` from `state` (the Whisper-detected language) in `recording_persistence._snippet_rows`.
   - Effect: "um" and "umm" leave English Ideal Texts, and Polish and German keep their own lists.
   - Backend only. No new words on screen.
2. **Send a language hint for live Takes (fixes L3).**
   - Add `language` to `intake_context._FIELDS`, filled from the project's language or the language detected on the speaker's last Take.
   - The existing `_whisper_request` branch then drops the English prompt by itself.
   - Measure it before and after, using item 6.
3. **Make the 20,000-character ceiling one rule (fixes L1).**
   - Either raise `_MAX_BLOCK_CHARS` and `MAX_DOCUMENT_CHARS` to the builder's 40,000, or make the builder cut at 20,000 too, trimming pieces and paragraphs with it, as `_finish_document` already does.
   - Never slice `text` alone.
   - Confirm `NEXT_PUBLIC_UPLOAD_PROXY_URL` in Vercel production. If it is unset, Takes over about 12 minutes depend on the Vercel lane.
4. **Stop treating grammatical double words as stutters (fixes part of L5).**
   - Exempt a short list from `_REPEAT_RE` ("had had", "that that", "is is" across a clause, "bye bye"), or only collapse repeats where Whisper's word gap is short.
   - Widen `_BOUNDARY_RE` to any lower-case letter (`[^\W\d_]` + `.islower()`) so Polish and Cyrillic sentences get capitals.
5. **Make the speech gate relative (fixes L8).**
   - Judge voiced frames against the recording's own noise floor (the noise meter, `NOISE_METER_VERSION`, already exists), not a fixed −45 dB.
   - Show the quiet-mic case as a mic-level hint rather than "no speech". That wording needs the founder's OK.
6. **Run the D-ML-1 baseline once (closes the "unmeasured" gap).**
   - Use 10 founder Takes: 5 in English, 3 in Polish, 2 with deck switching or no taps.
   - Run `scripts/measure_transcripts.py` and commit the report to `docs/audit/measure/`.
   - That gives the first real WER and wrong-slide share, and the before and after for items 1, 2 and 4.
7. **Answer A052b with one production query:** does V3 feedback serve or fail for real speakers? Then decide on the 16-piece LLM budget with numbers, not the ledger sample. This is a founder decision.
8. *(Larger)* **Give paragraphs a lineage across Takes (L7)** so that "did this paragraph improve in the next Take" becomes measurable. This is a design task; ask first.

---

## 5. Words for speakers: a draft that needs the founder's OK

Never-rule 4: none of this goes on screen without the founder's yes. Suggested
for the recording intro or a help page:

> **Works best for** talks up to 20 minutes, recorded in a quiet room with
> your mic close. If you use slides, move to the next slide as you start
> talking about it.
>
> **Good to know**
> - Very long talks (over 25 minutes) may not show their ending in your
>   Ideal Text yet.
> - If you record once with slides and once without, your Ideal Text
>   follows your latest Take. Your earlier words stay in History.
> - Very quiet recordings may be turned away. Move closer to your mic.

The second item is lasting behaviour. The first and third go away once
adjustments 3 and 5 ship.

---

## Appendix: probe output (2026-10-19, `3f2347a`)

```
=== S01 3-slide deck, clean taps between sentences (the happy path)
    [slide 0] Good morning everyone, today I want to talk about our onboarding.
    [slide 1] Last quarter we lost forty percent of new users in the first week.
    [slide 2] So we rebuilt the first five minutes around one single action.

=== S02 tap 700 ms late vs speech, with and without a measured clock offset
  no offset sent:
    [slide 0] Our churn problem starts on day one. The fix.
    [slide 1] Is a guided first project.
  offset 700 ms sent:
    [slide 0] Our churn problem starts on day one.
    [slide 1] The fix is a guided first project.

=== S03 deck uploaded, speaker never taps
    [slide 0] First I will explain the problem. Then I will show the numbers. And finally what we ask from you.
  per-slide transcripts saved: ['', '', '']

=== S04 revisits a slide: 1 → 2 → 1 → 3
    [slide 0] This is the market. Back to the market for one more number.
    [slide 1] This is our product.
    [slide 2] And this is the team.

=== S05 no deck, 3-minute monologue with natural pauses
  12 paragraphs, lengths 195–195 chars, all slide={None}

=== S06 run-on speech: no punctuation from Whisper, short pauses (<600 ms)
  sentence ends in Ideal Text: 3; first paragraph (300 chars):
    And then we looked at the data and saw that people drop off and then we looked at the data and saw that people drop off and then we looked at the data and saw t…

=== S07 fillers: what a live Take sees (no language on pieces) vs language known
  language=None  → Um so I think, umm, we should, launch in May.
  language=en    → So I think, we should, launch in May.
  pl language=None  → No więc myślę że, powinniśmy zacząć w maju.
  pl language=pl    → No więc myślę że, powinniśmy zacząć w maju.
  de language=None  → Also wir sollten, im Mai starten.

=== S08 immediate repeats: disfluency vs grammatical double words
  'We we need to to move faster.'          → 'We need to move faster.'
  'I had had enough of that.'              → 'I had enough of that.'
  'He said that that plan would fail.'     → 'He said that plan would fail.'
  'It is what it is, is it not?'           → 'It is what it is, is it not?'
  'Bye bye, see you next week.'            → 'Bye, see you next week.'

=== S09 sentence casing across languages and abbreviations
  en: We grew. Revenue doubled. E.g. in the U.S. it tripled.
  pl: Zaczęliśmy w maju. świetnie nam poszło. łącznie sto osób.
  uk: Ми почали в травні. це спрацювало.
  de: Wir haben es geschafft. Über tausend Leute kamen.

=== S10 very long talk (~55 min of speech) vs the document caps
  spoken ≈42840 chars, minutes ≈55; Ideal Text keeps 40000 chars (93%), last piece ends at 39934
  ideal_text_block then cuts at 20000 (≈26 min at 150 wpm): pieces past it = 192

=== S11 Take 2 re-records only slide 2; the speaker had edited slide 3
  merged:
    [slide 0] Slide one first take words.
    [slide 1] Slide two said much better now.
    [slide 2] Slide three, as I edited it by hand.

=== S12 Take 1 with a deck, Take 2 without one
  merge_by_slide: None (slides unprovable)
  follow_the_take → whole text is now: 'Only the first part again, better.'
  (slide 2's words from Take 1 are no longer in the Ideal Text)

=== S13 helper words: cap and survival across Takes
  'twelve steps · three · churn halved'                    within_cap=True  in Take 1='twelve steps · three · churn halved'
  'cut onboarding from twelve steps to three and churn'    within_cap=False in Take 1='cut onboarding from twelve steps to three and churn'
  'Twelve steps'                                           within_cap=True  in Take 1=None
  same pick vs Take 2 wording (digits, synonyms): None

=== S14 speech gate on synthetic audio (16 kHz)
  60 s silence                                  ok=False reason=no_speech voiced=0.0s
  60 s speech at -30 dBFS                       ok=True  reason=None voiced=60.0s
  60 s quiet speech at -48 dBFS (far mic)       ok=False reason=no_speech voiced=0.0s
  1 s speech                                    ok=True  reason=None voiced=1.0s
  60 s fan/room noise at -40 dBFS, no speech    ok=True  reason=None voiced=60.0s

=== S15 the Whisper call a live Take makes
  language passed: None; prompt 771 chars (≈192 tokens; Whisper reads only the last ~224)
  prompt starts: 'Umm, let me think like, hmm... Okay, so, uh, yeah. I mean, you know, i'
  with language='pl' (never sent by a live Take): language='pl', prompt=None

=== S16 one piece with an unprovable slide in a decked Take
  paragraph slides in order: [0, 1]  text='Words on slide one.\n\nWords on slide two words with no slide.'
```

In S16 slide 1 is index 0, and the unknown piece joined index 1, the slide spoken
just before it.
