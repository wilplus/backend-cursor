# The golden set for `scripts/measure_transcripts.py` (D-ML-1)

Internal only (AC-9). The founder's recordings are **not** in the repo: the
script takes a path to a folder you keep elsewhere. Reports land in
`docs/audit/measure/<date>.json`; the first real one becomes the dated
baseline in `docs/SPEC-DECISIONS-LOG.md`.

## Folder layout

One sub-folder per recording. Anything else under the root is ignored.

```
~/golden/
  take-01/
    item.json               the labels (below)
    take.m4a                the audio, exactly as the app uploaded it
    slide-01.txt            the hand transcript of what was said on slide 1
    slide-02.txt            ... one file per slide, in deck order, even if empty
    slide-03.txt
  take-02/
    ...
```

`item.json`:

```json
{
  "audio": "take.m4a",
  "take_id": "4b0c...-the v2 session id of the Take this was recorded in",
  "recording_id": "optional, the recording attempt id",
  "language": "en",
  "slides": ["Opening", "The market", "Ask"],
  "true_slide_changes_s": [12.40, 31.05],
  "tags": ["accent:pl", "noise:quiet"],
  "pipeline_slide_advances": [{"index": 0, "t_ms": 0}, {"index": 1, "t_ms": 12650}, {"index": 2, "t_ms": 31300}],
  "pipeline_slide_clock_offset_ms": 180
}
```

- `audio` — optional when the folder holds exactly one audio file.
- `take_id` — **required when Phase-1 authorization is enforced** (every
  provider call is permitted under the recording owner's own acceptance,
  for that Take). When present, the script also reads the Take's stored
  slide timeline from the database, so the two `pipeline_*` fields can be
  left out.
- `language` and `slides` — what the app sent, so Whisper is primed the
  same way the live Take was. Both optional; `slides` count must match the
  slide files.
- `true_slide_changes_s` — the moment, in seconds **on the audio**, each
  slide change really happened: one number per transition, ascending, so a
  deck of N slides has N−1 entries. Find them by listening (where the
  speaker's words for the next slide begin, or the click is audible).
- `tags` — free `key:value` strings; the report groups WER by each tag.
  Suggested: `accent:<none|pl|...>`, `noise:<quiet|office|street>`,
  `mic:<phone|laptop|headset>`.
- `pipeline_slide_advances` / `pipeline_slide_clock_offset_ms` — the
  timeline and measured offset the app recorded for this Take (the intake
  context). Give them here when the Take is not in the database you run
  against. Without either source the split runs on the true times and the
  report says `"timeline_source": "truth"` with no offset error.

## Running it

```
./venv/bin/python scripts/measure_transcripts.py ~/golden
```

Needs the same `.env` the backend runs with (database and
`OPENAI_API_KEY`). The provider is reached only through the live
pipeline's authorized adapter; if it cannot be built, or the provider is
not configured, the script refuses (exit 3) rather than call anything
itself. It never charges tokens and never writes a Take.

`--out PATH` picks the report file; `--date YYYY-MM-DD` only renames the
default one.

To see the format, write the synthetic example and run it offline:

```
./venv/bin/python scripts/measure_transcripts.py --write-example /tmp/golden-example
./venv/bin/python scripts/measure_transcripts.py /tmp/golden-example --stub
```

`--stub` reads `stub_transcription.json` per item instead of the provider.
It is for the fixture and the tests; a stubbed report says
`"transcriber": "stub"` and is never a baseline.

## What the report holds

Per item and overall (micro-averaged), plus the same per tag:

- `wer` — word error rate against the concatenated hand transcript
  (substitutions + insertions + deletions over reference words; case and
  punctuation ignored).
- `slide_assignment.wrong_slide_share` — of the pipeline's words that align
  to a hand-transcript word, the share bucketed to a different slide than
  the hand transcript puts them on. `per_slide_wer` is the same comparison
  slide by slide, so a bucketing error shows as a deletion on one slide
  and an insertion on the next.
- `wrong_slide_by_true_times` — the same count judged by the word's time
  against the true change times instead of by text. When this is low and
  `wrong_slide_share` is high, the provider's word times are off.
- `offset.errors_ms` — per boundary, the pipeline's boundary (the app's tap
  after `slide_clock_offset_ms`) minus the true change, signed: positive
  means the pipeline is late and the new slide's first words fall on the
  previous slide. `raw_tap_errors_ms` is the same before the correction,
  so the measured offset's worth is visible.
