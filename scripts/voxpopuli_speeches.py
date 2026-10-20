#!/usr/bin/env python3
"""Turn VoxPopuli (CC0, European Parliament plenary speech) into whole
speeches for the training corpus (founder 2026-10-19), then optionally upload
them through the same route the panel's "Import audio" uses.

VoxPopuli ships each plenary session as one long recording plus a table of
the transcribed segments in it (session, speaker, start/end). A speech is an
unbroken run of one speaker's segments in one session; it is cut from the
session recording from its first segment's start to its last one's end, so
the speaker's real pauses stay in. Only speech in the chosen language is
used: VoxPopuli's transcribed segments are the speaker's own words, never an
interpreter's.

Run it on a machine that can reach dl.fbaipublicfiles.com, with ffmpeg on
the PATH. The session recordings come as one archive per year (large: tens
of GB), so pick one year.

  # 1. download and cut (writes speeches + manifest.csv into --out)
  python scripts/voxpopuli_speeches.py prepare --root ~/voxpopuli \\
      --year 2019 --lang pl --lang en --out ~/voxpopuli/speeches

  # 2. upload each speech as a training import (the route registers it
  #    under the founder's processing basis, exactly like the panel)
  WILLAB_API_URL=https://<backend host> WILLAB_TOKEN=<your access token> \\
  python scripts/voxpopuli_speeches.py upload --out ~/voxpopuli/speeches

Speaker labels are VoxPopuli's own speaker ids ("vp-<id>"), never names:
they keep one person's speeches in the same 80/20 split and show raters
nothing. Credit rides every import's note.
"""
from __future__ import annotations

import argparse
import ast
import csv
import gzip
import json
import os
import subprocess
import sys
import tarfile
import time
import urllib.request
from collections import defaultdict
from pathlib import Path

BASE_URL = "https://dl.fbaipublicfiles.com/voxpopuli"
CREDIT = ("© European Union, source: European Parliament. "
          "Via VoxPopuli (CC0), https://github.com/facebookresearch/voxpopuli")
MANIFEST = "manifest.csv"


def _download(url: str, dest: Path) -> Path:
    if dest.exists():
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    print(f"downloading {url}")
    with urllib.request.urlopen(url) as resp, open(part, "wb") as fh:
        while chunk := resp.read(1 << 20):
            fh.write(chunk)
    part.rename(dest)
    return dest


def _sessions_audio(root: Path, year: int) -> Path:
    """The year's session recordings, downloaded and unpacked once."""
    out = root / "raw_audios" / "original" / str(year)
    if out.is_dir() and any(out.glob("*_original.ogg")):
        return out
    tar_path = _download(f"{BASE_URL}/audios/original_{year}.tar",
                         root / f"original_{year}.tar")
    print(f"unpacking {tar_path.name}")
    with tarfile.open(tar_path) as tar:
        tar.extractall(root / "raw_audios", filter="data")
    tar_path.unlink()
    return out


def _segments(root: Path, lang: str, year: int) -> list[dict]:
    tsv = _download(f"{BASE_URL}/annotations/asr/asr_{lang}.tsv.gz",
                    root / "annotations" / f"asr_{lang}.tsv.gz")
    rows = []
    with gzip.open(tsv, "rt") as fh:
        for r in csv.DictReader(fh, delimiter="|"):
            if not r["session_id"].startswith(str(year)):
                continue
            vad = ast.literal_eval(r["vad"])
            if not vad:
                continue
            rows.append({"session": r["session_id"], "speaker": r["speaker_id"],
                         "gender": r.get("gender") or "",
                         "start": float(vad[0][0]), "end": float(vad[-1][1])})
    return rows


def speeches(rows: list[dict], *, min_sec: float, max_sec: float,
             max_gap: float) -> list[dict]:
    """Unbroken runs of one speaker within one session, within the length
    limits. A run breaks on another speaker or a gap longer than max_gap."""
    by_session = defaultdict(list)
    for r in rows:
        by_session[r["session"]].append(r)
    out = []
    for session, segs in by_session.items():
        segs.sort(key=lambda r: r["start"])
        run: list[dict] = []
        for seg in segs + [None]:
            if run and (seg is None or seg["speaker"] != run[-1]["speaker"]
                        or seg["start"] - run[-1]["end"] > max_gap):
                length = run[-1]["end"] - run[0]["start"]
                if min_sec <= length <= max_sec:
                    out.append({"session": session, "speaker": run[0]["speaker"],
                                "gender": run[0]["gender"],
                                "start": run[0]["start"], "end": run[-1]["end"]})
                run = []
            if seg is not None:
                run.append(seg)
    return out


def pick(found: list[dict], *, per_speaker: int, limit: int) -> list[dict]:
    """At most per_speaker speeches each, then alternate genders so the set
    is balanced, up to limit."""
    count: dict[str, int] = defaultdict(int)
    by_gender = defaultdict(list)
    for s in sorted(found, key=lambda s: (s["session"], s["start"])):
        if count[s["speaker"]] < per_speaker:
            count[s["speaker"]] += 1
            by_gender[s["gender"]].append(s)
    queues = list(by_gender.values())
    chosen: list[dict] = []
    while len(chosen) < limit and any(queues):
        for q in queues:
            if q and len(chosen) < limit:
                chosen.append(q.pop(0))
    return chosen


def prepare(args: argparse.Namespace) -> int:
    root, out = Path(args.root).expanduser(), Path(args.out).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    audio_dir = _sessions_audio(root, args.year)
    manifest = []
    for lang in args.lang:
        found = speeches(_segments(root, lang, args.year), min_sec=args.min_sec,
                         max_sec=args.max_sec, max_gap=args.max_gap)
        chosen = pick(found, per_speaker=args.per_speaker, limit=args.limit)
        print(f"{lang}: {len(found)} speeches found, {len(chosen)} chosen")
        for i, s in enumerate(chosen):
            src = audio_dir / f"{s['session']}_original.ogg"
            name = f"vp_{lang}_{s['session']}_{i:03d}.mp3"
            if not (out / name).exists():
                subprocess.run(
                    ["ffmpeg", "-loglevel", "error", "-y", "-ss", f"{s['start']:.2f}",
                     "-to", f"{s['end']:.2f}", "-i", str(src), "-ac", "1",
                     "-b:a", "96k", str(out / name)], check=True)
            manifest.append({
                "filename": name, "speaker": f"vp-{s['speaker']}",
                "topic": f"EP plenary {s['session'][:8]} ({lang})",
                "language": lang,
                "seconds": round(s["end"] - s["start"]),
            })
    with open(out / MANIFEST, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(manifest[0]) if manifest else
                                ["filename", "speaker", "topic", "language", "seconds"])
        writer.writeheader()
        writer.writerows(manifest)
    print(f"wrote {len(manifest)} speeches and {out / MANIFEST}")
    return 0


def _post(api: str, token: str, path: Path, row: dict) -> dict:
    """One multipart POST /v2/coach/training-imports, the panel's own route."""
    boundary = f"----vp{int(time.time() * 1000)}"
    fields = {"topic": row["topic"], "speaker_label": row["speaker"],
              "language": row["language"], "note": CREDIT,
              "idempotency_key": f"voxpopuli:{row['filename']}"}
    body = b"".join(
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n"
        .encode() for k, v in fields.items())
    body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"audio_file\"; "
             f"filename=\"{path.name}\"\r\nContent-Type: audio/mpeg\r\n\r\n").encode()
    body += path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        f"{api.rstrip('/')}/v2/coach/training-imports", data=body, method="POST",
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            return json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as e:
        return {"ok": False, "status": e.code, "error": e.read().decode()[:300]}


def upload(args: argparse.Namespace) -> int:
    api, token = os.environ.get("WILLAB_API_URL"), os.environ.get("WILLAB_TOKEN")
    if not api or not token:
        print("set WILLAB_API_URL and WILLAB_TOKEN in the environment")
        return 1
    out = Path(args.out).expanduser()
    with open(out / MANIFEST, newline="") as fh:
        rows = list(csv.DictReader(fh))
    failed = 0
    for row in rows:
        result = _post(api, token, out / row["filename"], row)
        ok = result.get("session_id") and result.get("ok", True) is not False
        failed += 0 if ok else 1
        print(f"  {'OK  ' if ok else 'FAIL'} {row['filename']} "
              f"{result.get('session_id') or result.get('error') or result}")
        time.sleep(args.pause)
    print(f"\nuploaded={len(rows) - failed} failed={failed}")
    return 0 if failed == 0 else 2


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--root", required=True, help="where downloads are kept")
    p.add_argument("--out", required=True, help="where speeches are written")
    p.add_argument("--year", type=int, default=2019, help="2009-2020")
    p.add_argument("--lang", action="append", required=True, help="pl, en, ...")
    p.add_argument("--min-sec", type=float, default=60)
    p.add_argument("--max-sec", type=float, default=300)
    p.add_argument("--max-gap", type=float, default=8,
                   help="seconds of silence that still count as one speech")
    p.add_argument("--per-speaker", type=int, default=2)
    p.add_argument("--limit", type=int, default=30, help="speeches per language")
    u = sub.add_parser("upload")
    u.add_argument("--out", required=True)
    u.add_argument("--pause", type=float, default=20,
                   help="seconds between uploads (the route is rate limited)")
    args = ap.parse_args()
    return prepare(args) if args.cmd == "prepare" else upload(args)


if __name__ == "__main__":
    sys.exit(main())
