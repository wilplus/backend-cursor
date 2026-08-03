#!/usr/bin/env python3
"""Draw the best-per-slide RANKING eval run: labeling page + closed key.

Protocol ratified 2026-08-03 — full decision record in docs/RANKING-EVAL.md.
The one-line version: 30+ blind (session, slide) cases, stratified across
gate_decided/close/clear, labeled on a local HTML page ("Which of these
would I put in their best speech?" — forced choice + a none-fit checkbox),
~10 disguised repeats for the rater-noise ceiling, scored offline against
the shipped selector and four named variants (including confidence_on — the
VOICE_CONFIDENCE_RANKING_ENABLED simulation from the stamped reads).

WHAT IT WRITES:
  <out>/labeling_page.html — the rater's surface. Open in a browser, label,
                             press "Download answers" → ranking_answers.csv.
                             Blind: no score/band/take/machine pick/repeat
                             marker anywhere in the file.
  <out>/key.csv            — the machine side. KEEP CLOSED until labeling
                             is done.
  <out>/blind_sheet.csv    — archive copy of exactly what the rater saw.

Audio: per-snippet signed URLs (db.create_signed_url on AUDIO_BUCKET_NAME —
the same pattern the snippet-labeling surface uses), default 7-day expiry to
survive spread-over-days labeling. Refs that are already https pass through.

Read-only. Touches no ranking, writes nothing back to the database. AC-9:
internal/coach-side artifacts only.

Usage:
  ./venv/bin/python scripts/export_ranking_eval.py --out /tmp/ranking_eval
  # narrower: --user-id <uuid> (repeatable); reproducible: --seed 7
Then label, and:
  python scripts/score_ranking_eval.py \
      --answers ranking_answers.csv --key <out>/key.csv
"""
from __future__ import annotations

import argparse
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.ranking_eval import (  # noqa: E402
    BLIND_COLUMNS, KEY_COLUMNS, DEFAULT_CLOSE_GAP, DEFAULT_MAX_CANDIDATES,
    DEFAULT_PER_BAND, DEFAULT_REPEATS, attach_bands, attach_machine_picks,
    blind_rows, build_cases, build_session_candidates, draw_sample, key_rows,
    page_payload, render_labeling_page, run_id_for,
)

_SESSION_COLS = ("id, user_id, arc_id, take_index, status, created_at, "
                 "intake_context, recording_kind, paired_session_id")
_SIGN_TTL_SEC = 7 * 24 * 3600  # spread-over-days labeling (ratified)


def _recent_sessions(db, limit: int) -> list:
    """Most recent completed sessions across all users (kpi_sanity_check's
    direct-table pattern — there is no cross-user list method)."""
    res = (
        db.client.table("v2_sessions")
        .select(_SESSION_COLS)
        .eq("status", "completed")
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return res.data or []


def _corrections(db, session_id) -> dict:
    getter = getattr(db, "get_coach_snippet_drafts", None)
    out: dict = {}
    if not callable(getter):
        return out
    try:
        for d in (getter(session_id) or []):
            tc = d.get("transcript_corrected")
            if isinstance(tc, str) and tc.strip() and d.get("snippet_id") is not None:
                out[str(d["snippet_id"])] = tc.strip()
    except Exception:
        pass
    return out


def _labels(db, session_id) -> dict:
    getter = getattr(db, "get_training_labels", None)
    if not callable(getter):
        return {}
    try:
        return {
            str(r.get("snippet_id")): r.get("value")
            for r in (getter(session_id) or [])
            if isinstance(r, dict)
        }
    except Exception:
        return {}


def _audio_urls(db, cases: list) -> tuple[dict, int]:
    """{snippet_id: playable URL} for every sampled candidate. Already-https
    refs pass through; storage keys get a signed URL (snippet_labels.py's
    pattern). Failures are counted and printed — a case whose audio can't be
    played can't honor the listen-to-everything rubric."""
    from config import config as app_config

    bucket = getattr(app_config, "AUDIO_BUCKET_NAME", None) or "audio"
    urls: dict = {}
    failed = 0
    for case in cases:
        for c in case["candidates"]:
            sid = str(c.get("snippet_id"))
            if sid in urls:
                continue
            ref = c.get("audio_ref") or ""
            if ref.startswith("http://") or ref.startswith("https://"):
                urls[sid] = ref
                continue
            try:
                url = db.create_signed_url(bucket, ref,
                                           expires_in=_SIGN_TTL_SEC)
            except Exception:
                url = None
            if url:
                urls[sid] = url
            else:
                failed += 1
    return urls, failed


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--user-id", action="append", default=None,
                    help="restrict to this user's sessions (repeatable); "
                         "omit for the most recent sessions across users")
    ap.add_argument("--limit-sessions", type=int, default=200)
    ap.add_argument("--per-band", type=int, default=DEFAULT_PER_BAND)
    ap.add_argument("--repeats", type=int, default=DEFAULT_REPEATS,
                    help="disguised re-labels for the R0 ceiling")
    ap.add_argument("--max-candidates", type=int,
                    default=DEFAULT_MAX_CANDIDATES)
    ap.add_argument("--close-gap", type=float, default=DEFAULT_CLOSE_GAP)
    ap.add_argument("--seed", type=int, default=None)
    ap.add_argument("--out", default="./ranking_eval")
    args = ap.parse_args()

    from services.db import db
    from services.best_presentation import spoken_arc_sessions

    if args.user_id:
        sessions = []
        for uid in args.user_id:
            sessions.extend(
                db.v2_list_user_lab_sessions(
                    uid, limit=args.limit_sessions) or [])
    else:
        sessions = _recent_sessions(db, args.limit_sessions)

    # SPOKEN takes only (best_presentation.py:574-578; founder 2026-07-15).
    # Training imports are deckless (topic-only context) so they fall out
    # naturally at the deckless counter — routed to the confidence corpus,
    # not this eval (ratified).
    sessions = spoken_arc_sessions(sessions)
    if not sessions:
        print("No completed spoken sessions found.", file=sys.stderr)
        return 1

    all_candidates: list = []
    session_candidates: dict = {}
    slides_by_session: dict = {}
    for s in sessions:
        sid = str(s.get("id") or "")
        if not sid:
            continue
        snippets = db.get_snippets_by_session(sid) or []
        if not snippets:
            continue
        cands = build_session_candidates(
            s, snippets, _labels(db, sid), _corrections(db, sid))
        if not cands:
            continue
        session_candidates[sid] = cands
        all_candidates.extend(cands)
        ctx = s.get("intake_context") if isinstance(s.get("intake_context"), dict) else {}
        slides_by_session[sid] = ctx.get("slides") or []

    cases, stats = build_cases(
        all_candidates, max_candidates=args.max_candidates)
    if not cases:
        print("No rankable cases (need a decked session with 2+ pieces on "
              f"one slide). Exclusions: {stats}", file=sys.stderr)
        return 1

    attach_machine_picks(cases, session_candidates)
    attach_bands(cases, close_gap=args.close_gap)
    sample = draw_sample(cases, per_band=args.per_band, seed=args.seed,
                         repeats=args.repeats)

    urls, url_failures = _audio_urls(db, sample)

    os.makedirs(args.out, exist_ok=True)
    page_path = os.path.join(args.out, "labeling_page.html")
    key_path = os.path.join(args.out, "key.csv")
    sheet_path = os.path.join(args.out, "blind_sheet.csv")

    payload = page_payload(sample, slides_by_session, urls)
    with open(page_path, "w", encoding="utf-8") as fh:
        fh.write(render_labeling_page(payload, run_id_for(sample)))
    with open(key_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(KEY_COLUMNS))
        w.writeheader()
        w.writerows(key_rows(sample))
    with open(sheet_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(BLIND_COLUMNS))
        w.writeheader()
        w.writerows(blind_rows(sample, slides_by_session, urls))

    # Honesty block: which blend terms were actually LIVE in this draw. A
    # high agreement means little if every non-content term was zero.
    base = [c for c in sample if not c.get("repeat_of")]
    n = sum(len(c["candidates"]) for c in base)
    live_dir = sum(1 for c in base for x in c["candidates"]
                   if x.get("direction"))
    live_vc = sum(1 for c in base for x in c["candidates"]
                  if x.get("voice_confidence") is not None)
    stamped_vc = sum(1 for c in base for x in c["candidates"]
                     if x.get("voice_confidence_stamped") is not None)
    bands = {b: sum(1 for c in base if c.get("band") == b)
             for b in ("gate_decided", "close", "clear")}

    print(f"sessions={len(sessions)} rankable_cases={len(cases)} "
          f"sampled={len(base)}+{len(sample) - len(base)} repeats "
          f"candidates={n}")
    print(f"case exclusions (counted, not silent): {stats}")
    print(f"sampled bands: {bands}")
    print(f"live terms: direction {live_dir}/{n}, "
          f"voice_confidence served {live_vc}/{n}, stamped {stamped_vc}/{n}")
    if stamped_vc == 0:
        print("WARNING: no candidate carries a stamped confidence read — "
              "the confidence_on variant (R3) will be a no-op on this draw. "
              "Pieces recorded before the composite shipped (2026-07-27) "
              "are unstamped; record fresh takes or re-draw.")
    if url_failures:
        print(f"WARNING: {url_failures} candidate(s) have NO playable audio "
              "URL — those cases can't honor the listen-to-everything "
              "rubric. Fix storage access or exclude those sessions.")
    print(f"\nlabeling page (open in a browser): {page_path}")
    print(f"key (KEEP CLOSED until answers are in): {key_path}")
    print(f"archive sheet: {sheet_path}")
    print("\nWhen done, the page downloads ranking_answers.csv. Then:\n"
          f"  python scripts/score_ranking_eval.py "
          f"--answers ranking_answers.csv --key {key_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
