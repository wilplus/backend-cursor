# The ASR golden set — what it is and what it needs

This directory holds the manifest for the ASR bake-off. **Audio and reference
transcripts are never committed** (`.gitignore`d): they are user voice, which
`services/audio_storage.py` already treats as sensitive and access-controlled.
Keep them on the machine running the sweep, or pull them from R2 at run time.

```bash
# free, no API calls — what can this corpus measure right now?
python scripts/asr_eval_run.py --manifest evals/asr/manifest.json --check

# the sweep
python scripts/asr_eval_run.py --manifest evals/asr/manifest.json \
    --providers openai:whisper-1,faster-whisper,whisperx --out /tmp/asr.json
```

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

### 4. The strata — the actual question

An average across accents hides the subgroup we are trying to fix, so the
corpus is sliced by `accent` and the runner reports each slice separately.
**8–12 takes per stratum** (the harness flags anything under 5 as noise).

| Stratum | Why | Takes |
|---|---|---|
| `en-native` | control — isolates accent from everything else | 8 |
| *your heaviest L2-English accent* | the case the migration is for | 12 |
| *second L2-English accent* | shows whether a win generalizes | 8 |
| *non-English native* | different code path (English prompt is dropped) | 8 |
| `adverse-condition` | noise / bad mic / room, crossed with accent | 8 |

**Ask #1 — which accents actually matter for your users?** I have not
guessed; the manifest example uses Polish as a placeholder because the repo
already carries a Polish filler list and a first-non-English-import fix. Tell
me the real distribution and I will restructure the strata around it.

**Ask #2 — same speakers across strata where possible.** Two takes from the
same speaker under different conditions separate "this model dislikes this
accent" from "this model dislikes this microphone". `speaker_id` in the
manifest is what makes that separable.

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
| `language` | correct prompt rule + filler list | English prompt on non-English audio |
| `accent` / `condition` / `speaker_id` | per-stratum breakdown | the accent question goes unanswered |

`--check` prints exactly which of these the corpus currently supports and
refuses to start a paid sweep whose headline metric would come back blank.
