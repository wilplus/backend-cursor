# ASR migration — the eval, and a finding that reshapes the plan

**Status**: harness shipped, corpus empty, no model swapped.
**Date**: 2026-08-03

---

## Decision filter

```
VERDICT:  ADVANCE-F1
CATEGORY: F1-SUPPORT → gates an F1-CORE change
WHY:      Per-slide transcription is load-bearing piece (a) of F1, and
          "improve transcription fidelity on hard/accented audio" is
          redirect target #2 in CLAUDE.md. The harness is not a platform
          play — it names a specific in-flight F1 task (the whisper-1
          migration, founder-directed 2026-08-03), which is what keeps it
          out of R11 ("foundation / unblocks F1 later"). No fence touched:
          the harness is offline, imports nothing from the live loop,
          surfaces no score to any user (AC-9), and is not reachable from a
          route. L1/L2/L3 untouched — it measures transcription, it does
          not rank, rewrite, or narrow the clone.
REDIRECT: n/a — clean ADVANCE-F1.
```

The LLM half of the request (gpt-4o/gpt-4o-mini → frontier) is **split off
and deferred**, not refused — see the last section. It does not classify as
one thing, and bundling it would have smuggled ~25 SCAFFOLDING call sites in
behind two F1 ones.

---

## The finding: the OpenAI ASR migration, as scoped, cannot work

Verified against the current API reference and corroborated across
independent sources (links at the bottom). Three facts, all load-bearing:

1. **`timestamp_granularities` is whisper-1 only.** `gpt-4o-transcribe`,
   `gpt-4o-mini-transcribe` and `gpt-transcribe` do not return word
   timestamps.
2. **`verbose_json` is whisper-1 only.** The newer endpoints accept `json`
   or `text`. Since `timestamp_granularities` requires `verbose_json`, there
   is no way to ask for word timings at all.
3. **The 25 MB cap is not a whisper-1 constraint.** It applies to the whole
   transcription endpoint, newer models included — and `gpt-4o-transcribe`
   adds a *tighter* audio-length limit (~1500s) that whisper-1 does not have.

### Why fact 1 is fatal rather than inconvenient

F1's entire word→slide mechanism is `word.start` → `slide_index_for_offset`.
`services/slide_word_split.py` buckets **every word** by its timestamp;
`services/slide_boundary_metrics.py` exists solely to measure how well that
boundary behaves. A model with no word timestamps cannot be bucketed at all
— per-slide transcription would fall back to whole-snippet assignment, which
is precisely the pre-#6 behaviour the founder's #6 work replaced.

So the swap that was framed as the highest-leverage upgrade would, as
scoped, **delete load-bearing piece (a)** — and it would do it while
improving the headline WER number, which is the failure mode the harness is
built to catch.

### And the 25 MB goal is not achievable this way either

The cap survives the migration. If the constraint is worth removing, the
lever is **local inference** (no request-size limit at all), not a different
OpenAI endpoint. The `-b:a 48k` mono 16 kHz encode in
`services/ffmpeg_audio_extract.py` exists to fit that cap and could be
retired on a local path.

**None of this says "don't migrate."** It says the migration target is not
where it looked. Which is exactly what an eval-first sequence is for, and
why the harness landed before any string was swapped.

---

## What this changes

The bake-off you proposed as a nice-to-have is now **the main path**:

| Candidate | Word timestamps | 25 MB cap | Accent headroom |
|---|---|---|---|
| `whisper-1` (incumbent) | yes | yes | baseline |
| `gpt-4o-transcribe` family | **no** | yes (+1500s) | n/a — fails coverage |
| `faster-whisper` (large-v3) | yes, native | **none** | large-v3 ≫ whisper-1 |
| `whisperx` (large-v3 + wav2vec2) | yes, **forced-aligned** | **none** | large-v3 + phoneme alignment |

`whisperx` is the one most likely to move F1, and for a reason specific to
this product: Whisper's native word times are decoder attention estimates,
while whisperx re-aligns each word against the acoustics with a phoneme
model. That is a different quality class *exactly* where willab is sensitive
— the first word after a slide tap. If it wins the timing metrics, the
two-clocks compensation in `slide_word_split` (pause-snap, clock offset) is
fighting a smaller residual than it is today.

The gpt-4o-* providers stay registered in the harness anyway, so the claim
is re-testable in one command the day OpenAI adds timestamps, rather than
decaying into a stale note in this file.

---

## The harness

```
asr_eval/
  normalize.py   token normalization; verbatim vs disfluency-insensitive
  metrics.py     WER · timestamp error · slide-bucket agreement · coverage
  corpus.py      manifest schema, loader, readiness check
  providers.py   whisper-1 · gpt-4o-* · faster-whisper · whisperx · aligner
  report.py      aggregation + the PASS/FAIL/INSUFFICIENT-DATA gate
scripts/asr_eval_run.py    CLI
evals/asr/README.md        the golden-set spec — what we need from you
test_asr_eval.py           60 tests, no network, CI unit tier
```

Nothing imports from the live loop, and `services/` imports nothing from
here. The one dependency runs the other way: `metrics._bucket` calls the
**production** `slide_index_for_offset` rather than reimplementing it, so
the eval cannot drift from the rule it is gating.

### Language flips (added 2026-08-03, after the demographics landed)

The user base is L2-English speakers — Polish, German, Italian, Ukrainian,
and a Mandarin/Japanese/Indian mix — who ALSO speak fluent native Polish. So
`en` and `pl` are both live in the same product, and the live path
**auto-detects** language whenever `session_context.language` is unset
(`lab_recording.py:408`).

That makes language detection a first-class F1 concern rather than a
hypothetical. The signature failure is Whisper hearing accented English as
the speaker's mother tongue: the transcript comes back in the wrong language
(or translated), and willab's own prompt rule then drops the English
disfluency primer on top, because that rule keys off language. Scored against
an English reference the take reports ~100% WER and looks like an accent
problem, when the real failure was one routing decision upstream of
transcription.

`metrics.language_detection` reports it, `accent_l1` in the corpus separates
a flip-to-L1 from generic confusion, and the gate holds flips to **zero** —
the one threshold here not expected to move after the baseline run. A flip
does not degrade a take, it destroys it.

Corpus is split into two tracks that are never averaged (`l2_english`,
`native_non_english`) because they run under different decoding
configurations. Strata, counts, and a 26-take phase-1 subset are in
`evals/asr/README.md`.

### Metric ranking, and why it is not WER

Ranked by decision-relevance. Getting this order wrong is how a migration
ships a regression while the headline improves:

0. **language flip** — is the transcript even in the right language?
   Evaluated before coverage, because a flip is a plausible cause of an
   unusable result and losing that diagnosis to an early return is how an
   upstream routing bug gets recorded as an accent problem.
1. **coverage** — did the provider return word timestamps at all? Reported
   first because a provider that returns none otherwise sails through every
   timing metric as "no disagreements found". This is a hard fail, and it is
   the gate the gpt-4o-* family trips.
2. **slide-bucket agreement** — same tap timeline, two word streams: what
   share of words land on a *different* slide? **This is the metric.**
   Reported overall and restricted to boundary-adjacent words, where
   essentially all real disagreement lives.
3. **timestamp error** — |Δstart|, median/p90/p95.
4. **verbatim WER** — fillers *kept*.
5. **content WER** — fillers stripped. Last on purpose: least
   decision-relevant, and it is the number that flatters a model which
   quietly cleans up disfluencies.

The harness demonstrates this on itself: `test_asr_eval.py` includes a
candidate with a **0.00% WER** that the gate still fails, because a 600 ms
timing shift moved a quarter of its words across a slide boundary.

### Three tiers of ground truth, never blurred

`slide_boundary_metrics.py` already says the hard part out loud — nothing
records which slide was *actually* on screen when a word was spoken. The same
gap applies to timing: a human reference transcript is text, with no
timestamps. So:

- **tier 1** reference text → WER. Real ground truth for words, none for time.
- **tier 2** reference word times (forced-aligned) → timestamp **accuracy**.
- **tier 3** the incumbent's output → **agreement**, not accuracy. Says "this
  differs from what we ship"; never "this is better". Cheap, needs no labels,
  right as a tripwire — and labeling it accuracy would assume the answer.

Every timing number carries its tier, and the gate prints a warning whenever
it is reading tier 3. `--align` upgrades a corpus from tier 3 to tier 2 with
no human labeling.

### The gate

`PASS` / `FAIL` / `INSUFFICIENT-DATA`, the last a first-class outcome rather
than a soft pass — an absent number is a reason to refuse, never to approve.
Thresholds (`report.py`) are **starting points to be re-set from the observed
whisper-1 baseline** once the corpus exists; a threshold invented before any
measurement is a guess wearing a number's clothes.

Beyond the obvious checks, two that are specific to this product:

- **deletion-share shift** — a candidate holding WER steady by deleting more
  and substituting less is *not* equivalent. Dropped speech costs whole slide
  fragments, not just words.
- **worst per-slide word delta** — a model that moves one slide's whole
  opening clause to the previous slide is an F1 regression at 1% overall
  disagreement. The average hides it; this does not.

---

## Sequence

1. **You**: answer Ask #0 (are the existing coach/user transcript
   corrections joinable to retained audio?) and Ask #1 (which accents).
   → `evals/asr/README.md`
2. Assemble the corpus; `--check` until green.
3. `--align` to get tier-2 reference times.
4. Baseline sweep on whisper-1 → **re-set the gate thresholds from what we
   actually observe**, not from the placeholders in `report.py`.
5. Bake-off: `faster-whisper` and `whisperx` against the baseline, per
   stratum.
6. Only then decide. If a local model wins, the follow-on work is real —
   inference hosting, latency budget, and the queue path in
   `services/job_queue.py` — and that is a separate decision-filter run.

Step 4 is the one worth protecting. Running the bake-off before the baseline
is characterized means comparing candidates against invented thresholds.

---

## The LLM half — split, and deferred behind this

You asked to bump `gpt-4o-mini`/`gpt-4o` alongside the ASR work. Splitting it
as the filter requires (step 1, "split bundles and run each") gives two very
different answers. Every `LLMSpec` in `services/llm_config.py`, classified:

**F1 — these five feed best-per-slide ranking (piece b):**

| Spec | Site | Mechanism |
|---|---|---|
| `SPEC_BEST_PRESENTATION` | `best_presentation.py` | assembles the best-per-slide deliverable |
| `SPEC_SLIDE_CLAIMS` | `slide_alignment.py` | decomposes slides → claims |
| `SPEC_SLIDE_ENTAILMENT` | `slide_alignment.py` | on-slide-ness — drives overall/rank |
| `SPEC_SNIPPET_STICKINESS` | `snippet_stickiness.py` | stickiness feeds the ranking blend |
| `SPEC_DELIVERY_ALIGNMENT` | `delivery_alignment.py` | delivery — half of the L2 blend |

**SCAFFOLDING — the other ~17 specs**: the eight `SPEC_LIFE_*`, master-doc
RAG and chunking, journal images, community content, onboarding, coaching
intro, session cadence, icebreaker, audit pointer, goal update, directive
suggestions, conversation summary, moment suggestions. A model bump there is
neutral-to-nice and unblocks nothing in flight.

One to look at separately: `SPEC_SAY_IT_STRONGER` generates alternative
phrasings. Whether a model bump there is F1 or an **L1 risk** depends on
whether its output can reach selected slide text — that needs checking before
it is swapped, not assumed either way.

Bundling all of these would have moved ~17 scaffolding changes under an F1
banner, so they are separated. The F1 five are worth doing and should follow
the same sequence — baseline eval first — but they sit **behind** the ASR
work under contention (F1-CORE wins ties, and transcription is piece (a)).

Two things make the swap itself cheap when we get to it:
`services/llm_config.py` already centralizes the model strings, and
`services/llm_schemas.py` already pins strict schemas. The eval to build is a
**schema-adherence + coaching-quality** probe, and there is a working
precedent to copy: `tests/evals/master_doc_probe.py`.

One live constraint, worth flagging now rather than at swap time: the pinned
SDK is `openai==1.59.2` (Dec 2024). It predates the newer transcribe models
*and* the newer chat tiers, so **either** upgrade begins with an SDK bump —
which touches the live loop and wants its own gate-routed PR.

---

## Sources

- [Create transcription — OpenAI API reference](https://developers.openai.com/api/reference/resources/audio/subresources/transcriptions/methods/create)
- [Speech-to-text guide — OpenAI](https://developers.openai.com/api/docs/guides/speech-to-text)
- [GPT-4o Transcribe specifications (2026)](https://gate.ai/blog/gpt-4o-transcribe-openai-specs-pricing-api-use-cases)
- [OpenAI launches GPT-4o-transcribe: powerful yet limited](https://scribewave.com/blog/openai-launches-gpt-4o-transcribe-a-powerful-yet-limited-transcription-model)
- [gpt-4o-transcribe audio length limits — OpenAI community](https://community.openai.com/t/gpt-4o-transcribe-audio-length-limits/1148374)
