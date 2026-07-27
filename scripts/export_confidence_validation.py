#!/usr/bin/env python3
"""Draw a validation sample for the voice-confidence composite.

THE GATE THIS SERVES (founder spec 2026-07-27, Jiang & Pell 2017): the composite
in services/voice_confidence.py sets DIRECTIONS from the literature but its
weights are ours and uncalibrated. It must be anchored against BLINDED human
confidence ratings before it is allowed to move a pick — i.e. before
VOICE_CONFIDENCE_RANKING_ENABLED is flipped on. The paper's listeners reached
>83% agreement, with mean ratings 4.52 / 3.24 / 2.05 on a 1-5 scale across its
confident / close-to-confident / unconfident items; that is the bar to compare
against.

WHAT IT WRITES (two files, deliberately separate):
  <out>/blind_sheet.csv  — snippet_id, audio_ref, span, transcript, and an EMPTY
                           rating column. Give this to the rater. It carries NO
                           machine score, band, or acoustic number, so the rating
                           cannot be anchored by ours.
  <out>/key.csv          — snippet_id, score, band, cues, baseline. Keep this
                           closed until the sheet comes back, then join on
                           snippet_id.

SAMPLING. Random over the user's pieces, NOT ordered by score or salience. This
matters: services/snippet_salience.py documents a hard methodological fence that
a validation sample must be drawn independently of the salience features, so it
cannot inherit the product selection's bias. Under PIECES_CANONICAL every piece
of a take becomes a row (salience only picks which get the LLM layers), so a
random draw over pieces is legitimately independent — but if you run this with
PIECES_CANONICAL_ENABLED=0, the rows ARE the salience-selected windows and the
draw is biased. The script refuses to pretend otherwise: it prints which regime
each sampled row came from.

Read-only. Touches no ranking, writes nothing back to the database.

Usage:
  ./venv/bin/python scripts/export_confidence_validation.py \
      --user-id <uuid> --n 40 --out /tmp/vc_validation
  # optional: --seed 7 for a reproducible draw
"""
from __future__ import annotations

import argparse
import csv
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _rows_for_user(database, user_id: str, max_sessions: int) -> list:
    """Every stamped piece across the user's recent lab sessions."""
    rows: list = []
    sessions = database.v2_list_user_lab_sessions(
        user_id, limit=max_sessions) or []
    for s in sessions:
        sid = str(s.get("id") or "")
        if not sid:
            continue
        for snip in (database.get_snippets_by_session(sid) or []):
            metrics = snip.get("metrics")
            if not isinstance(metrics, dict):
                continue
            read = metrics.get("voice_confidence")
            if not isinstance(read, dict) or read.get("score") is None:
                continue
            rows.append({
                "session_id": sid,
                "snippet_id": str(snip.get("id") or ""),
                "audio_ref": snip.get("audio_ref") or snip.get("storage_path") or "",
                "start_offset_ms": snip.get("start_offset_ms"),
                "duration_ms": snip.get("duration_ms"),
                "transcript": (snip.get("transcript")
                               or snip.get("transcript_excerpt") or "").strip(),
                "score": read.get("score"),
                "band": read.get("band"),
                "cues": read.get("cues"),
                "baseline": read.get("baseline"),
                # Which regime produced this row — see the SAMPLING note above.
                "regime": "piece" if isinstance(metrics.get("piece"), dict)
                          else "salient_window",
            })
    return rows


def _stratify(rows: list, n: int, rng: random.Random) -> list:
    """Random within band, spread across bands, so a sample isn't all-neutral.

    Deliberately NOT score-ordered — within a band the draw is uniform. If a
    band is short, its shortfall is redistributed to the others rather than
    topped up with the most extreme rows (which would flatter the composite)."""
    by_band: dict = {}
    for r in rows:
        by_band.setdefault(r.get("band") or "unknown", []).append(r)
    for bucket in by_band.values():
        rng.shuffle(bucket)

    picked: list = []
    bands = sorted(by_band)
    while len(picked) < n and any(by_band[b] for b in bands):
        for b in bands:
            if len(picked) >= n:
                break
            if by_band[b]:
                picked.append(by_band[b].pop())
    rng.shuffle(picked)   # the sheet must not be ordered by band either
    return picked[:n]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--user-id", required=True,
                    help="whose pieces to sample (the composite is speaker-relative, "
                         "so a sample mixing speakers is not interpretable)")
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--out", default="./vc_validation")
    ap.add_argument("--max-sessions", type=int, default=25)
    ap.add_argument("--seed", type=int, default=None)
    args = ap.parse_args()

    from services.db import db

    rows = _rows_for_user(db, args.user_id, args.max_sessions)
    if not rows:
        print("No stamped pieces found. Either the user has no takes since "
              "voice_confidence shipped, or VOICE_CONFIDENCE_ENABLED was off "
              "when they recorded.", file=sys.stderr)
        return 1

    regimes = {r["regime"] for r in rows}
    if regimes == {"salient_window"}:
        print("WARNING: every row came from the legacy salient-window cutter, "
              "so this sample INHERITS the salience selection and is not an "
              "independent draw (see the SAMPLING note in this file). Re-run "
              "against takes recorded under PIECES_CANONICAL_ENABLED=1.",
              file=sys.stderr)

    rng = random.Random(args.seed)
    sample = _stratify(rows, args.n, rng)

    os.makedirs(args.out, exist_ok=True)
    blind_path = os.path.join(args.out, "blind_sheet.csv")
    key_path = os.path.join(args.out, "key.csv")

    with open(blind_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["snippet_id", "audio_ref", "start_offset_ms", "duration_ms",
                    "transcript", "confidence_1_to_5"])
        for r in sample:
            w.writerow([r["snippet_id"], r["audio_ref"], r["start_offset_ms"],
                        r["duration_ms"], r["transcript"], ""])

    with open(key_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["snippet_id", "score", "band", "cues", "baseline",
                    "session_id", "regime"])
        for r in sample:
            w.writerow([r["snippet_id"], r["score"], r["band"], r["cues"],
                        r["baseline"], r["session_id"], r["regime"]])

    counts: dict = {}
    for r in sample:
        counts[r["band"]] = counts.get(r["band"], 0) + 1

    print(f"pool={len(rows)} sampled={len(sample)}")
    print("bands: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    print(f"\nblind sheet (give to the rater): {blind_path}")
    print(f"key (keep closed until it returns): {key_path}")
    print("\nRate each clip 1-5 for how CONFIDENT the speaker sounds, audio "
          "only, without reading the machine column. Then join on snippet_id "
          "and check that the rating rises with `score`. Flip "
          "VOICE_CONFIDENCE_RANKING_ENABLED=1 only if it does.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
