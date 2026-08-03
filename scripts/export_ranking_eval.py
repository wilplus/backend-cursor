#!/usr/bin/env python3
"""Draw the best-per-slide RANKING eval sample (blind sheet + closed key).

THE GATE THIS SERVES: power_score picks one line per slide (F1's second
load-bearing piece) with hand-set weights nobody has compared to a human
judgment. This draws the comparison set. The label question per case:

    "Here are the lines this speaker said while slide N was on screen,
     blind, shuffled. Which ONE best represents this slide?"

Cases are (session, slide) — single takes qualify (the ranker chooses
between a slide's pieces today; it never sees take_index), so no multi-take
arcs are required. Deckless sessions are a DIFFERENT label task (choose K
of N moments) and are out of v1 scope — skipped and counted, never silent.

WHAT IT WRITES (two files, deliberately separate — the same discipline as
export_confidence_validation):
  <out>/blind_sheet.csv — case_id, slide title/body, shuffled lettered
                          candidates with transcript + audio span, an EMPTY
                          is_best column (+ optional why). NO machine read
                          of any kind: no score, no band, no take, no
                          direction. Give this to the rater.
  <out>/key.csv         — the machine's answers (shipped local + assembly
                          picks) and every power_score input, so the report
                          can score the shipped blend AND the named
                          variants offline. KEEP CLOSED until the sheet
                          comes back.

SAMPLING. Stratified across decision bands — gate_decided (the complete-
sentence sort key overrode the score), close (top-two score gap under
--close-gap), clear — because near-ties are where the ranker is actually
deciding anything. Bands select and stay key-side (blind coach). Candidate
lists are never truncated within a case; cases too big to judge are
excluded whole and counted.

Read-only. Touches no ranking, writes nothing back to the database. AC-9:
internal/coach-side artifacts only.

Usage:
  ./venv/bin/python scripts/export_ranking_eval.py --out /tmp/ranking_eval
  # narrower: --user-id <uuid> (repeatable); reproducible: --seed 7
Then label blind_sheet.csv (exactly one is_best=1 per case_id, audio
first, transcript second) and run scripts/score_ranking_eval.py.
"""
from __future__ import annotations

import argparse
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.ranking_eval import (  # noqa: E402
    BLIND_COLUMNS, KEY_COLUMNS, DEFAULT_CLOSE_GAP, DEFAULT_MAX_CANDIDATES,
    DEFAULT_PER_BAND, attach_bands, attach_machine_picks, blind_rows,
    build_cases, build_session_candidates, draw_sample, key_rows,
)

_SESSION_COLS = ("id, user_id, arc_id, take_index, status, created_at, "
                 "intake_context, recording_kind, paired_session_id")


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
    """Coach-corrected transcripts, keyed by snippet id — the assembler's
    verbatim source when present (best_presentation.py:587-598)."""
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
    """Coach direction labels {snippet_id: value} (blind side input)."""
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


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--user-id", action="append", default=None,
                    help="restrict to this user's sessions (repeatable); "
                         "omit for the most recent sessions across users "
                         "(ranking is within-slide, so mixing speakers is "
                         "fine — unlike the confidence validation)")
    ap.add_argument("--limit-sessions", type=int, default=100)
    ap.add_argument("--per-band", type=int, default=DEFAULT_PER_BAND)
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

    # SPOKEN takes only — reads never enter the candidate pool
    # (best_presentation.py:574-578; founder 2026-07-15).
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
    sample = draw_sample(cases, per_band=args.per_band, seed=args.seed)

    os.makedirs(args.out, exist_ok=True)
    blind_path = os.path.join(args.out, "blind_sheet.csv")
    key_path = os.path.join(args.out, "key.csv")
    with open(blind_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(BLIND_COLUMNS))
        w.writeheader()
        w.writerows(blind_rows(sample, slides_by_session))
    with open(key_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(KEY_COLUMNS))
        w.writeheader()
        w.writerows(key_rows(sample))

    # Honesty block: which blend terms were actually LIVE in this draw. A
    # high agreement means little if every non-content term was zero.
    n = sum(len(c["candidates"]) for c in sample)
    live_dir = sum(1 for c in sample for x in c["candidates"]
                   if x.get("direction"))
    live_vc = sum(1 for c in sample for x in c["candidates"]
                  if x.get("voice_confidence") is not None)
    bands = {b: sum(1 for c in sample if c.get("band") == b)
             for b in ("gate_decided", "close", "clear")}

    print(f"sessions={len(sessions)} rankable_cases={len(cases)} "
          f"sampled={len(sample)} candidates={n}")
    print(f"case exclusions (counted, not silent): {stats}")
    print(f"sampled bands: {bands}")
    print(f"live terms in sample: direction {live_dir}/{n}, "
          f"voice_confidence {live_vc}/{n} "
          "(0s mean the blend ran content-only for this draw — that is "
          "itself a finding; say so next to any agreement number)")
    print(f"\nblind sheet (give to the rater): {blind_path}")
    print(f"key (KEEP CLOSED until the sheet returns): {key_path}")
    print("\nLabel: per case_id, listen to every candidate's span, then put "
          "1 in is_best on exactly ONE row (forced choice; `why` optional "
          "but feeds the coach corpus). Do not open key.csv first. Then:\n"
          f"  python scripts/score_ranking_eval.py "
          f"--sheet {blind_path} --key {key_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
