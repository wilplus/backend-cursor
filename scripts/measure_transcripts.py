#!/usr/bin/env python3
"""Measure transcription accuracy and word→slide bucketing on a founder
golden set (D-ML-1, build plan 2026-10-07). F1-CORE piece (a).

Runs the LIVE code paths — the same authorized provider adapter, the same
word normalisation, the same clock-offset correction and the same
word→slide bucketing production uses — on a folder of the founder's own
consented recordings, each with a hand transcript per slide and the true
slide-change times, and writes one JSON report:

  * word error rate, overall and per tag (accent / noise tags per item);
  * the share of words the pipeline put on the wrong slide;
  * the clock-offset error in ms: the pipeline's slide boundary (the app's
    tap time after the measured clock-offset correction) minus the true
    change time, per boundary.

Format of the golden folder: scripts/measure_transcripts.md (next to this
file). `--write-example DIR` writes a complete synthetic item that shows it.

Usage:
  ./venv/bin/python scripts/measure_transcripts.py ~/golden
  ./venv/bin/python scripts/measure_transcripts.py ~/golden --out docs/audit/measure/2026-10-09.json
  ./venv/bin/python scripts/measure_transcripts.py --write-example /tmp/golden-example
  ./venv/bin/python scripts/measure_transcripts.py /tmp/golden-example --stub   # no provider

Provider calls go ONLY through services.recording_transcription.
recording_provider_adapter — the adapter the live transcription stage
builds, under the Phase-1 processing authorization path. With the gate
enforced every item needs the ``take_id`` of the Take it was recorded in, so
the permit is issued under the recording owner's own acceptance. The script
refuses to run when that adapter cannot be built or the provider is not
configured; it never instantiates a provider client itself. ``--stub`` reads
a provider-shaped ``stub_transcription.json`` per item instead and is for
the synthetic fixture and the tests; a stubbed report says so in its
``transcriber`` field and is never a baseline.

AC-9: internal only. The report is read by the founder and the decisions
log; nothing here is user-facing. Runs locally, never in CI.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import logging
import math
import os
import struct
import sys
import wave
from typing import Any, Callable, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.transcript_measure import (  # noqa: E402
    boundary_offset_error,
    hyp_tokens_with_index,
    normalize_tokens,
    slide_assignment,
    summarize,
    summarize_by_tag,
    true_slide_at,
    word_error_rate,
)

logger = logging.getLogger("measure_transcripts")

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPORT_DIR = os.path.join(REPO_ROOT, "docs", "audit", "measure")
ITEM_FILE = "item.json"
STUB_FILE = "stub_transcription.json"
AUDIO_EXTENSIONS = (".wav", ".mp3", ".m4a", ".webm", ".ogg", ".flac", ".mp4", ".aac")

Transcriber = Callable[["GoldenItem"], dict]


class MeasureRefusal(RuntimeError):
    """The run cannot proceed honestly: a provider path outside the authorized
    adapter, an unreadable item, a missing hand label."""


class GoldenItem:
    """One recording of the golden set, read from its folder."""

    def __init__(self, folder: str) -> None:
        self.folder = folder
        self.name = os.path.basename(os.path.normpath(folder))
        meta_path = os.path.join(folder, ITEM_FILE)
        try:
            with open(meta_path, encoding="utf-8") as fh:
                meta = json.load(fh)
        except (OSError, ValueError) as error:
            raise MeasureRefusal(f"{self.name}: cannot read {ITEM_FILE}: {error}")
        if not isinstance(meta, dict):
            raise MeasureRefusal(f"{self.name}: {ITEM_FILE} must hold an object")
        self.meta = meta
        self.audio_path = self._find_audio(meta.get("audio"))
        self.slide_texts = self._read_slide_texts()
        self.true_changes_s = self._true_changes(meta.get("true_slide_changes_s"))
        if len(self.true_changes_s) != len(self.slide_texts) - 1:
            raise MeasureRefusal(
                f"{self.name}: {len(self.slide_texts)} slide transcripts need "
                f"{len(self.slide_texts) - 1} true_slide_changes_s, got "
                f"{len(self.true_changes_s)}")
        self.tags = [str(t) for t in (meta.get("tags") or []) if str(t).strip()]
        self.take_id = str(meta.get("take_id") or "").strip() or None
        self.recording_id = str(meta.get("recording_id") or "").strip() or None
        self.language = str(meta.get("language") or "").strip() or None
        titles = meta.get("slides")
        if isinstance(titles, list) and titles:
            if len(titles) != len(self.slide_texts):
                raise MeasureRefusal(
                    f"{self.name}: {len(titles)} slide titles for "
                    f"{len(self.slide_texts)} slide transcripts")
            self.slides = [{"title": str(t)} for t in titles]
        else:
            self.slides = [{"title": f"Slide {k + 1}"}
                           for k in range(len(self.slide_texts))]

    def _find_audio(self, named: Any) -> str:
        if named:
            path = os.path.join(self.folder, str(named))
            if not os.path.isfile(path):
                raise MeasureRefusal(f"{self.name}: audio file {named} not found")
            return path
        found = sorted(
            f for f in os.listdir(self.folder)
            if f.lower().endswith(AUDIO_EXTENSIONS))
        if len(found) != 1:
            raise MeasureRefusal(
                f"{self.name}: expected exactly one audio file or an "
                f"\"audio\" entry in {ITEM_FILE}, found {found}")
        return os.path.join(self.folder, found[0])

    def _read_slide_texts(self) -> list[str]:
        names = sorted(
            f for f in os.listdir(self.folder)
            if f.lower().startswith("slide-") and f.lower().endswith(".txt"))
        if not names:
            raise MeasureRefusal(
                f"{self.name}: no slide-NN.txt hand transcripts")
        texts: list[str] = []
        for n in names:
            with open(os.path.join(self.folder, n), encoding="utf-8") as fh:
                texts.append(fh.read())
        return texts

    def _true_changes(self, raw: Any) -> list[float]:
        if raw is None:
            return []
        if not isinstance(raw, list):
            raise MeasureRefusal(f"{self.name}: true_slide_changes_s must be a list")
        out: list[float] = []
        for v in raw:
            if isinstance(v, bool) or not isinstance(v, (int, float)) \
                    or not math.isfinite(float(v)) or float(v) < 0:
                raise MeasureRefusal(
                    f"{self.name}: true_slide_changes_s holds a non-time {v!r}")
            out.append(float(v))
        if out != sorted(out):
            raise MeasureRefusal(f"{self.name}: true_slide_changes_s must be ascending")
        return out

    def audio_bytes(self) -> bytes:
        with open(self.audio_path, "rb") as fh:
            return fh.read()

    def session_context(self) -> dict:
        """The intake-shaped context the live pipeline would see for this
        recording: slides for Whisper priming, the language hint."""
        ctx: dict[str, Any] = {"slides": self.slides}
        if self.language:
            ctx["language"] = self.language
        return ctx

    def pipeline_timeline(self) -> Optional[dict]:
        """``{slide_advances, slide_clock_offset_ms}`` as the app recorded
        them, from item.json when given, else None (the runner may fetch
        them from the Take)."""
        adv = self.meta.get("pipeline_slide_advances")
        if not isinstance(adv, list) or not adv:
            return None
        return {
            "slide_advances": _int_advances(adv, self.name),
            "slide_clock_offset_ms": self.meta.get("pipeline_slide_clock_offset_ms"),
        }


def _int_advances(raw: list, name: str) -> list[dict]:
    """``[{index, t_ms}]`` with integer fields, as the app's intake validates
    them (services.intake_context); a hand-typed 12650.0 must not silently
    drop a boundary (slide_index_for_offset reads only ints)."""
    out: list[dict] = []
    for a in raw:
        if not isinstance(a, dict):
            raise MeasureRefusal(f"{name}: pipeline_slide_advances entries must be objects")
        idx, t = a.get("index"), a.get("t_ms")
        if isinstance(idx, bool) or isinstance(t, bool) \
                or not isinstance(idx, (int, float)) or not isinstance(t, (int, float)):
            raise MeasureRefusal(f"{name}: pipeline_slide_advances needs numeric index and t_ms")
        out.append({**a, "index": int(idx), "t_ms": int(round(float(t)))})
    return out


def load_golden(root: str) -> list[GoldenItem]:
    if not os.path.isdir(root):
        raise MeasureRefusal(f"golden folder not found: {root}")
    items: list[GoldenItem] = []
    for name in sorted(os.listdir(root)):
        folder = os.path.join(root, name)
        if os.path.isdir(folder) and os.path.isfile(os.path.join(folder, ITEM_FILE)):
            items.append(GoldenItem(folder))
    if not items:
        raise MeasureRefusal(f"no item folders (with {ITEM_FILE}) under {root}")
    return items


# ── Transcribers ──────────────────────────────────────────────────────────

def stub_transcriber(item: GoldenItem) -> dict:
    """The provider-shaped result from the item's stub_transcription.json.
    For the synthetic fixture and the tests only."""
    path = os.path.join(item.folder, STUB_FILE)
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as error:
        raise MeasureRefusal(f"{item.name}: --stub needs {STUB_FILE}: {error}")
    if not isinstance(data, dict) or not isinstance(data.get("words"), list):
        raise MeasureRefusal(f"{item.name}: {STUB_FILE} must hold {{words: [...]}}")
    return data


def provider_transcriber(items: list[GoldenItem]) -> Transcriber:
    """The live adapter, or a refusal. Pre-flight runs over EVERY item before
    the first provider call so a half-labelled set does not half-spend."""
    from services.db import db
    from services.processing_authorization import ProcessingAuthorizationService
    from services.recording_transcription import (
        _language_hint,
        merge_slide_vocabulary,
        recording_provider_adapter,
    )

    authorization = ProcessingAuthorizationService(db)
    if authorization.enforced:
        missing = [it.name for it in items if not it.take_id]
        if missing:
            raise MeasureRefusal(
                "Phase-1 authorization is enforced: every item needs the "
                f"take_id of its own Take in {ITEM_FILE}; missing on {missing}")
    try:
        from services.openai_service import OpenAIService
        configured = bool(OpenAIService().client)
    except Exception as error:  # noqa: BLE001 - a missing SDK or key is the refusal itself, reported below
        configured = False
        logger.warning("provider check failed: %s", error)
    if not configured:
        raise MeasureRefusal(
            "the transcription provider is not configured (OPENAI_API_KEY); "
            "this script never builds a provider client of its own")

    def run(item: GoldenItem) -> dict:
        adapter = recording_provider_adapter(
            db, authorization,
            session_id=item.take_id or f"measure:{item.name}",
            recording_id=item.recording_id,
            user_id=None,
        )
        result = adapter.transcribe_audio(
            item.audio_bytes(), os.path.basename(item.audio_path),
            vocabulary=merge_slide_vocabulary(item.session_context()),
            language=_language_hint(item.session_context()),
            usage_surface="whisper_measure",
            usage_user_id=None,
            usage_session_id=item.take_id or f"measure:{item.name}",
        )
        if result is None:
            raise MeasureRefusal(
                f"{item.name}: the authorized adapter returned no transcription")
        return result

    return run


def no_timeline(_item: GoldenItem) -> Optional[dict]:
    """A stubbed run reads nothing from a database."""
    return None


def fetch_pipeline_timeline(item: GoldenItem) -> Optional[dict]:
    """The slide timeline the app stored on the Take, when the item names
    one and the database is reachable; None otherwise."""
    if not item.take_id:
        return None
    try:
        from services.db import db
        ctx = db.takes.get_session_intake_context(item.take_id) or {}
    except Exception as error:  # noqa: BLE001 - no database locally is a documented, reported fallback
        logger.warning("%s: could not read the Take's timeline: %s", item.name, error)
        return None
    adv = ctx.get("slide_advances") if isinstance(ctx, dict) else None
    if not isinstance(adv, list) or not adv:
        return None
    return {
        "slide_advances": adv,
        "slide_clock_offset_ms": ctx.get("slide_clock_offset_ms"),
    }


# ── One item through the live split ───────────────────────────────────────

def _truth_timeline(item: GoldenItem) -> list[dict]:
    return [{"index": 0, "t_ms": 0}] + [
        {"index": k + 1, "t_ms": int(round(t * 1000))}
        for k, t in enumerate(item.true_changes_s)
    ]


def measure_item(
    item: GoldenItem, transcription: dict, timeline: Optional[dict],
) -> dict:
    """The live normalisation, clock-offset correction and bucketing on one
    recording, scored against its hand labels."""
    from services.recording_transcription import _normalize_words
    from services.slide_word_split import (
        _bucket_words_by_slide,
        build_slide_transcripts,
        context_with_clock_offset,
    )

    words = _normalize_words(
        list(transcription.get("words") or []),
        list(transcription.get("segments") or []),
        session_id=item.name, log=logger,
    )
    if timeline:
        corrected = context_with_clock_offset(dict(timeline))
        advances = corrected["slide_advances"]
        timeline_source = "pipeline"
        offset = boundary_offset_error(item.true_changes_s, advances)
        offset["raw_tap_errors_ms"] = boundary_offset_error(
            item.true_changes_s, timeline["slide_advances"])["errors_ms"]
        offset["slide_clock_offset_ms"] = timeline.get("slide_clock_offset_ms")
    else:
        advances = _truth_timeline(item)
        timeline_source = "truth"
        offset = None

    # THE live bucketing (build_slide_transcripts calls the same function),
    # read per word so each word's slide can be judged.
    buckets = _bucket_words_by_slide(words, advances, item.slides)
    slide_of: dict[int, int] = {}
    for si, ws in buckets.items():
        for w in ws:
            slide_of[id(w)] = si
    hyp_tokens, src = hyp_tokens_with_index(words)
    hyp_slide = [slide_of.get(id(words[i]), 0) for i in src]
    ref_slides = [normalize_tokens(t) for t in item.slide_texts]
    ref_all = [t for toks in ref_slides for t in toks]

    assignment = slide_assignment(ref_slides, hyp_tokens, hyp_slide)
    by_time = sum(
        1 for i, si in zip(src, hyp_slide)
        if true_slide_at(float(words[i].get("start") or 0.0),
                         item.true_changes_s) != si)
    per_slide = build_slide_transcripts(words, advances, item.slides)
    per_slide_wer = [
        {"slide_index": k,
         **word_error_rate(ref_slides[k],
                           normalize_tokens(per_slide[k].get("transcript")))}
        for k in range(len(ref_slides))
    ]
    return {
        "item": item.name,
        "audio": os.path.basename(item.audio_path),
        "tags": item.tags,
        "take_id": item.take_id,
        "duration_s": transcription.get("duration"),
        "language": transcription.get("language"),
        "timeline_source": timeline_source,
        "wer": word_error_rate(ref_all, hyp_tokens),
        "per_slide_wer": per_slide_wer,
        "slide_assignment": assignment,
        "wrong_slide_by_true_times": {
            "words": len(hyp_tokens), "wrong": by_time,
            "share": (by_time / len(hyp_tokens)) if hyp_tokens else None,
        },
        "offset": offset,
    }


def run(
    items: list[GoldenItem], transcriber: Transcriber, *,
    transcriber_name: str, timeline_of: Callable[[GoldenItem], Optional[dict]],
) -> dict:
    results: list[dict] = []
    failures: list[dict] = []
    for item in items:
        try:
            timeline = item.pipeline_timeline() or timeline_of(item)
            results.append(measure_item(item, transcriber(item), timeline))
            logger.info("measured %s", item.name)
        except MeasureRefusal:
            raise
        except Exception as error:  # noqa: BLE001 - one bad item is reported in the JSON, the rest still measure
            logger.exception("%s failed", item.name)
            failures.append({"item": item.name, "error": f"{type(error).__name__}: {error}"})
    return {
        "generated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "script": "scripts/measure_transcripts.py",
        "transcriber": transcriber_name,
        "internal_only": "AC-9: never user-facing",
        "items": results,
        "failures": failures,
        "overall": summarize(results),
        "per_tag": summarize_by_tag(results),
    }


# ── The synthetic example ─────────────────────────────────────────────────

EXAMPLE_SLIDES = ("Hello and welcome to the lab.", "Today we measure every word.")
EXAMPLE_WORDS = [
    ("Hello", 0.10), ("and", 0.30), ("welcome", 0.45), ("to", 0.60),
    ("the", 0.70), ("lap", 0.78),           # "lap" for "lab": one substitution
    ("Today", 0.84),                        # spoken on slide 2, timed before the boundary
    ("we", 1.00), ("measure", 1.15), ("every", 1.30), ("word", 1.45),
]


def write_example(root: str) -> str:
    """A complete synthetic item: 1.6 s of generated audio, two hand
    transcripts, a true change at 0.80 s, the app's tap at 900 ms with a
    measured 50 ms offset, and a stub transcription with one substitution
    and one word timed onto the wrong slide."""
    folder = os.path.join(root, "example-01")
    os.makedirs(folder, exist_ok=True)
    rate, seconds = 16000, 1.6
    with wave.open(os.path.join(folder, "audio.wav"), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        frames = bytearray()
        for n in range(int(rate * seconds)):
            frames += struct.pack("<h", int(3000 * math.sin(2 * math.pi * 220 * n / rate)))
        wf.writeframes(bytes(frames))
    for k, text in enumerate(EXAMPLE_SLIDES):
        with open(os.path.join(folder, f"slide-{k + 1:02d}.txt"), "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
    meta = {
        "audio": "audio.wav",
        "language": "en",
        "slides": ["Welcome", "Measuring"],
        "true_slide_changes_s": [0.80],
        "tags": ["accent:none", "noise:synthetic"],
        "pipeline_slide_advances": [{"index": 0, "t_ms": 0}, {"index": 1, "t_ms": 900}],
        "pipeline_slide_clock_offset_ms": 50,
    }
    with open(os.path.join(folder, ITEM_FILE), "w", encoding="utf-8") as fh:
        json.dump(meta, fh, indent=2)
        fh.write("\n")
    words = [{"word": w, "start": s, "end": round(s + 0.12, 2)} for w, s in EXAMPLE_WORDS]
    stub = {
        "text": "Hello and welcome to the lap. Today we measure every word.",
        "duration": seconds,
        "language": "en",
        "segments": [
            {"start": 0.10, "end": 0.90, "text": "Hello and welcome to the lap."},
            {"start": 0.84, "end": 1.57, "text": "Today we measure every word."},
        ],
        "words": words,
    }
    with open(os.path.join(folder, STUB_FILE), "w", encoding="utf-8") as fh:
        json.dump(stub, fh, indent=2)
        fh.write("\n")
    return folder


# ── CLI ───────────────────────────────────────────────────────────────────

def _print_summary(report: dict) -> None:
    o = report["overall"]

    def pct(v: Any) -> str:
        return "n/a" if v is None else f"{100 * v:.1f}%"

    def ms(v: Any) -> str:
        return "n/a" if v is None else f"{v:+.0f} ms"

    print(f"transcriber: {report['transcriber']}   items: {o['items']}   "
          f"failures: {len(report['failures'])}")
    print(f"WER overall:         {pct(o['wer'])}  ({o['errors']}/{o['ref_words']} words)")
    print(f"wrong-slide share:   {pct(o['wrong_slide_share'])}  "
          f"({o['wrong_slide_words']}/{o['judged_words']} judged words)")
    print(f"offset error:        mean {ms(o['offset_mean_ms'])}, "
          f"mean abs {ms(o['offset_mean_abs_ms'])}, max abs {ms(o['offset_max_abs_ms'])} "
          f"over {o['boundaries_compared']} boundaries")
    for tag, s in report["per_tag"].items():
        print(f"  {tag:<24} WER {pct(s['wer'])}  wrong-slide {pct(s['wrong_slide_share'])}"
              f"  offset mean abs {ms(s['offset_mean_abs_ms'])}  ({s['items']} items)")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("golden_dir", nargs="?", help="folder of golden items")
    parser.add_argument("--out", help="report path (default docs/audit/measure/<date>.json)")
    parser.add_argument("--date", help="date for the default report name (YYYY-MM-DD)")
    parser.add_argument("--stub", action="store_true",
                        help=f"read {STUB_FILE} per item instead of calling the provider")
    parser.add_argument("--write-example", metavar="DIR",
                        help="write the synthetic example item under DIR and exit")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    if args.write_example:
        folder = write_example(args.write_example)
        print(f"wrote {folder}")
        return 0
    if not args.golden_dir:
        parser.error("golden_dir is required (or --write-example DIR)")

    try:
        items = load_golden(args.golden_dir)
        if args.stub:
            transcriber: Transcriber = stub_transcriber
            name = "stub"
            timeline_of: Callable[[GoldenItem], Optional[dict]] = no_timeline
        else:
            transcriber = provider_transcriber(items)
            name = "provider"
            timeline_of = fetch_pipeline_timeline
        report = run(items, transcriber, transcriber_name=name, timeline_of=timeline_of)
    except MeasureRefusal as refusal:
        print(f"refused: {refusal}", file=sys.stderr)
        return 3

    date = args.date or _dt.date.today().isoformat()
    out = args.out or os.path.join(REPORT_DIR, f"{date}.json")
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)
        fh.write("\n")
    _print_summary(report)
    print(f"report: {out}")
    return 1 if report["failures"] else 0


if __name__ == "__main__":
    sys.exit(main())
