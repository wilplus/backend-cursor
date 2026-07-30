#!/usr/bin/env python3
"""Bulk-import a folder of audio files as coach-reviewable training takes.

The no-UI path for seeding the corpus (founder 2026-07-28): point it at a
folder, get one reviewable arc per file. Each file runs the SAME analysis a
live take runs, but is marked ``source='training_import'`` — invisible to the
speaker's project list and excluded from their acoustic baseline. See
services/training_import.py for why both markers matter.

Sequential by design: the analysis is CPU-heavy (ffmpeg + Whisper + per-piece
metrics) and hammering it in parallel from a laptop mostly produces timeouts.
A 20-file batch is a coffee break, not a spinner.

Usage:
  ./venv/bin/python scripts/import_training_audio.py \\
      --dir ~/talks --user-id <uuid> --topic "Conference talks"

  # per-file speaker labels via a manifest (filename,speaker,topic):
  ./venv/bin/python scripts/import_training_audio.py \\
      --dir ~/talks --user-id <uuid> --manifest ~/talks/manifest.csv

  --dry-run   list what WOULD be imported (no upload, no analysis, no rows)
"""
from __future__ import annotations

import argparse
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _load_manifest(path: str) -> dict:
    """{filename: {speaker, topic}} from a CSV with a filename column.

    Tolerant on purpose — a corpus manifest is usually hand-made: the header
    may be filename/file/name, speaker/speaker_label, topic/title, and any
    unknown columns are ignored."""
    out: dict = {}
    if not path:
        return out
    with open(path, newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            lower = {(k or "").strip().lower(): (v or "").strip()
                     for k, v in row.items()}
            name = (lower.get("filename") or lower.get("file")
                    or lower.get("name") or "")
            if not name:
                continue
            out[os.path.basename(name)] = {
                "speaker": (lower.get("speaker") or lower.get("speaker_label")
                            or ""),
                "topic": lower.get("topic") or lower.get("title") or "",
            }
    return out


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", help="folder of audio files (non-recursive)")
    ap.add_argument("--file", action="append", default=[],
                    help="a single file; repeatable")
    ap.add_argument("--user-id", required=True,
                    help="who the corpus rows belong to")
    ap.add_argument("--topic", default="",
                    help="default topic for every file (manifest overrides)")
    ap.add_argument("--speaker", default="",
                    help="default speaker label (manifest overrides)")
    ap.add_argument("--manifest", default="",
                    help="CSV: filename,speaker,topic")
    ap.add_argument("--note", default="", help="provenance note on every row")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    from services.training_import import (
        import_training_audio, is_audio_filename,
    )

    paths: list = list(args.file)
    if args.dir:
        for name in sorted(os.listdir(args.dir)):
            full = os.path.join(args.dir, name)
            if os.path.isfile(full) and is_audio_filename(name):
                paths.append(full)
    if not paths:
        print("No audio files found.", file=sys.stderr)
        return 1

    manifest = _load_manifest(args.manifest) if args.manifest else {}
    if not args.topic and not manifest:
        print("Give --topic (or a --manifest with a topic column): the topic "
              "labels each take on the coach's review screen.", file=sys.stderr)
        return 1

    print(f"{len(paths)} file(s) to import"
          f"{' — DRY RUN' if args.dry_run else ''}\n")
    ok = failed = 0
    for path in paths:
        name = os.path.basename(path)
        meta = manifest.get(name, {})
        topic = meta.get("topic") or args.topic
        speaker = meta.get("speaker") or args.speaker or None
        if not topic:
            print(f"  SKIP {name}: no topic (not in manifest, no --topic)")
            failed += 1
            continue
        if args.dry_run:
            print(f"  would import {name}  topic={topic!r} "
                  f"speaker={speaker or '-'}")
            continue
        try:
            with open(path, "rb") as fh:
                audio = fh.read()
        except OSError as e:
            print(f"  FAIL {name}: {e}")
            failed += 1
            continue
        result = import_training_audio(
            audio_bytes=audio, filename=name, user_id=args.user_id,
            topic=topic, speaker_label=speaker,
            source_note=args.note or None,
        )
        if result.get("ok"):
            ok += 1
            print(f"  OK   {name}  {result['snippet_count']} pieces  "
                  f"arc={result['arc_id']}")
        else:
            failed += 1
            print(f"  FAIL {name}: {result.get('reason')} "
                  f"— {result.get('detail') or ''}")

    if args.dry_run:
        return 0
    print(f"\nimported={ok} failed={failed}")
    if ok:
        print("Review each arc at GET /v2/coach/arc/<arc_id>/stars "
              "(or the coach UI's imports list).")
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
