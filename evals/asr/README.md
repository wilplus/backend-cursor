# The ASR golden set — what it is and what it needs

This directory holds the manifest for the ASR bake-off. **Audio and reference
transcripts are never committed** (`.gitignore`d): they are user voice, which
`services/audio_storage.py` already treats as sensitive and access-controlled.
Keep them on the machine running the sweep, or pull them from R2 at run time.

```bash
cp evals/asr/manifest.example.json evals/asr/manifest.json

# create the audio/ + refs/ layout the manifest implies
python scripts/asr_eval_run.py --manifest evals/asr/manifest.json --scaffold

# free, no API calls — what can this corpus measure right now?
python scripts/asr_eval_run.py --manifest evals/asr/manifest.json --check

# the sweep (mirrors the live path: no language hint, so auto-detect is tested)
python scripts/asr_eval_run.py --manifest evals/asr/manifest.json \
    --providers openai:whisper-1,faster-whisper,whisperx \
    --no-language-hint --out /tmp/asr.json
```

---

## Start here: a first answer with ZERO transcription

The 12–18 hours of transcription below buys *accuracy*. But the question
"how much would this migration actually move F1?" needs no transcripts at
all — slide-bucket agreement, timestamp drift and language flips are all
provider-vs-provider. **Audio + slide timelines is enough.**

```bash
python scripts/asr_eval_run.py --manifest evals/asr/manifest.json \
    --providers openai:whisper-1,whisperx --baseline openai:whisper-1 \
    --agreement-only --no-language-hint
```

You get a `RISK: LOW / MODERATE / HIGH` read per candidate, and it sizes
whether the full corpus is urgent or merely prudent:

- **LOW** — the candidate buckets words almost exactly where whisper-1 does.
  A swap is unlikely to move per-slide text. Build the corpus for
  confidence, not urgency.
- **HIGH** — a swap would visibly move per-slide text, so the corpus becomes
  *required*: at that magnitude, shipping on agreement numbers alone is
  guessing which direction the change goes.
- **Any language flip → HIGH automatically.** That is not a tuning question.

What it cannot do, and is written not to imply: say a candidate is
**better**. Every number is agreement with the incumbent. A candidate that
disagrees on 8% of words might be 8% better or 8% worse — which is exactly
why HIGH argues *for* building the corpus, not against it.

Do this before anyone spends an afternoon transcribing.

---

## What we need from you

### 0. First, the free data you already have

Before recording anything, two tables already hold **human-corrected
transcripts of real takes**:

| Source | What it is |
|---|---|
| `coach_snippet_drafts.transcript_corrected` | a coach fixed the transcript of a piece |
| `user_transcript_edits.text` | a user fixed their own readout text |

Every row is a human saying "the ASR got this wrong here", on real willab
audio, in real conditions, for free. If the matching audio is still in R2,
these convert straight into golden-set entries — and they are **better than
anything we could record on purpose**, because they are drawn from the exact
distribution of takes the product actually sees.

**Ask #0 — can we pull these?** How many rows exist, and is the source audio
still retained for them? That answer decides whether the rest of this list is
"record 40 takes" or "label the 10 gaps".

### 1. Audio

- **Format**: whatever the recorder produces (`.webm`/`.mp4`) or the extracted
  MP3. The harness reads files directly, so the 25 MB cap does not apply here.
- **Length**: 2–4 minutes per take. Long enough for several slide boundaries,
  short enough that a human will transcribe it.
- **Decked takes, please.** A take with no slide taps cannot produce the
  headline metric — the harness returns `None` rather than a misleading zero.
  Target **3–6 slides per take**.

### 2. The slide tap timeline (non-negotiable)

For each take: the raw `slide_advances` the FE recorded, plus
`slide_clock_offset_ms` where the client reported one.

```json
"slide_advances": [{"index": 0, "t_ms": 0}, {"index": 1, "t_ms": 48200}],
"slide_clock_offset_ms": 140
```

Without this the run measures word accuracy and **not** whether words land on
the right slide — which is the only question that decides the migration.

### 3. Reference transcripts

One UTF-8 text file per take. The spec is short but matters:

- **Verbatim.** Every "um", "uh", "yyy", every false start, every repeated
  word. This is the point — willab primes Whisper with a disfluency prompt on
  purpose, and a model that tidies speech up is a regression here even though
  it scores better on conventional WER. A cleaned reference makes that
  regression invisible.
- **Numbers as spoken** ("twenty twenty six", not "2026").
- **Punctuation and casing don't matter** — normalization strips them.

**Cheaper path**: start from the whisper-1 output and *correct* it rather than
typing from scratch — roughly 4x faster. The honest caveat: a corrector
skimming Whisper's text tends to accept its errors, which biases the reference
toward the incumbent and makes whisper-1 look better than it is. Mitigate by
listening to the whole take, not just reading along. On the accent strata,
where the errors are, prefer transcribing from scratch.

### 4. The strata

Two tracks, reported separately and **never averaged** — they run under
different decoding configurations, so a combined number describes a setup no
take actually ran under. `openai_service.transcribe_audio` applies the
English disfluency primer on track 1 and **drops it** on track 2.

**Track 1 — L2 English** (`language: "en"`, `accent_l1` = mother tongue)

| Stratum | `accent_l1` | Takes |
|---|---|---|
| `en-native` (control) | `en` | 6 |
| `polish-l2-en` | `pl` | 10 |
| `german-l2-en` | `de` | 8 |
| `italian-l2-en` | `it` | 8 |
| `ukrainian-l2-en` | `uk` | 8 |
| `asian-l2-en` | `zh` / `ja` / `hi`, ≥3 each | 12 |

**Track 2 — native fluent Polish** (`language: "pl"`)

| Stratum | `accent_l1` | Takes |
|---|---|---|
| `pl-native` | `pl` | 10 |

**62 takes total.** Be aware what that costs: at 2–4 min each that is ~3
hours of audio, and verbatim transcription runs 4–6× realtime, so **12–18
hours of human work**. That is the real price of the gate, and it is worth
knowing before anyone starts rather than halfway through.

**Phase it.** The minimum corpus that answers your two named questions:

> `en-native` (6) + `polish-l2-en` (10) + `pl-native` (10) = **26 takes**

That covers the control, the largest accent group, and the native-Polish
track — roughly 5–7 hours of transcription, and enough to characterize the
whisper-1 baseline and set real gate thresholds. German / Italian /
Ukrainian / Asian can land in phase 2 without redoing anything; the harness
reports whatever strata exist and flags thin ones rather than quoting them.

Two notes on the design:

- **`asian-l2-en` is one stratum, not three.** You asked for a representative
  mix, so the mix lives inside the stratum and `accent_l1` stays exact
  (`zh` / `ja` / `hi`). If one sub-group behaves differently the split is a
  one-line regroup; three strata of 4 would have been three unreliable
  numbers instead of one usable one.
- **Reuse `speaker_id` across tracks.** The same person recording both an
  L2-English take and a native-Polish take is what separates "the model
  dislikes this language" from "the model dislikes this voice." Cheap to
  arrange at record time, impossible to recover afterward.

### 4b. Language flips — the failure WER cannot see

New metric, added because of your demographics specifically. The live path
**auto-detects language** whenever `session_context.language` is unset
(`lab_recording.py:408`). For heavily accented English the signature failure
is Whisper deciding the audio is the speaker's mother tongue and returning a
wrong-language transcript — which then also silently drops the English
disfluency primer, because willab's own prompt rule keys off language.

Scored against an English reference, that take reports ~100% WER and reads
as "the model is bad at accents," when the real failure was one wrong routing
decision upstream of transcription. `accent_l1` is what lets the harness say
which of the two actually happened.

The gate holds language flips to **zero** — the only threshold here not
expected to move after the baseline run. A flip does not degrade a take, it
destroys it. Run with `--no-language-hint` to exercise the live behaviour;
without that flag the model is simply told the answer and the metric is
meaningless.

### 5. Optional but high value: reference word times

Without them, every timing number is **tier 3** — agreement with whisper-1.
That can show a candidate *differs*; it can never show it is *better*, because
it assumes the incumbent is right.

The fix needs no labeling. Given audio + a reference transcript, a forced
aligner produces reference word times directly:

```bash
pip install whisperx
python scripts/asr_eval_run.py --manifest evals/asr/manifest.json --align
```

Do this once and the whole harness upgrades from "differs" to "better/worse".

---

## What each field unlocks

| Field | Unlocks | Without it |
|---|---|---|
| `audio` | everything | take is skipped |
| `slide_advances` + `slides` | **slide-bucket agreement** | headline metric unmeasurable |
| `reference_text` | WER (verbatim + content) | no accuracy number at all |
| `reference_words` | timestamp **accuracy** (tier 2) | timing is agreement only (tier 3) |
| `language` | correct prompt rule + filler list + flip detection | English prompt on non-English audio |
| `accent_l1` | isolates L1 flips from generic confusion | a flip is visible but not diagnosable |
| `accent` / `condition` / `speaker_id` | per-stratum breakdown | the accent question goes unanswered |

`--check` prints exactly which of these the corpus currently supports and
refuses to start a paid sweep whose headline metric would come back blank.
Take-level problems are collected, not fatal — a 60-take manifest with three
bad reference paths reports all three in one run.

---

## Known gap: filler lists don't cover your demographics

`utils/filler_words.py` has `en`, `pl`, `de`, `es`. Missing: **`it`, `uk`,
`zh`, `ja`, `hi`** — all fall back to the English list.

For this eval that is mostly harmless: L2-English takes are `language: "en"`,
so the English list is the right one, and native Polish is covered. It
matters in two places, both worth a decision rather than a silent fix:

1. **L2 speakers use their native fillers while speaking English** — a Polish
   speaker saying "yyy" mid-English-sentence. The English list misses it, so
   the disfluency-insensitive WER companion is slightly off, and more
   importantly **production filler density under-counts for exactly your user
   base**. That is an F1 question about `stress_snippet_service`, not an eval
   question.
2. **If you ever add native Italian/Ukrainian takes**, they would be scored
   against English fillers.

I have not touched `utils/filler_words.py`. Adding a language key changes
live filler counting for any take detected as that language (today they fall
back to English), so it is a live-loop behaviour change that needs its own
decision-filter run — not something to slip in behind an eval harness.
