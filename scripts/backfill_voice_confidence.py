#!/usr/bin/env python3
"""Re-stamp historical pieces under the CURRENT voice-confidence weighting.

WHY THIS EXISTS. services/voice_confidence.py stamps its composite at record
time and nothing ever re-stamps it. So when the weighting changed (v1 sex-blind
-> v2 sex-routed, where cue 1 REVERSES direction for men), every piece already
in the database kept a score computed under the retired weighting while new
pieces got the new one. Both land in [-1, 1] and both look plausible, and the
delivery term swings 2.0 in power_score — twice the content term's range — so a
mixed arc ranks last week's take against today's on an inconsistent basis and
the winner looks entirely reasonable. That is the failure this repairs.

Until a piece is backfilled it simply does not rank: rank_term gates on
_RANKABLE_VERSIONS, and power_score reads a missing term as 0.0 (an unstamped
piece is never penalised against a stamped one). So the ordering is: ship the
gate, run this, and coverage comes back. Running it is what ENDS the degraded
window, not what starts one.

WHAT IT COVERS — and what it deliberately does not.

  * Normal takes (``source='audit_upload'``). These are what
    v2_list_user_lab_sessions returns, and they are the pieces that rank.

  * NOT training imports. An imported take is someone else's voice under the
    importing coach's user_id, and which voice it was lives in the in-memory
    ``session_context`` handed to process_lab_recording — it is never
    persisted. So for a historical import there is no way to recover whether
    the speaker was the account holder, and guessing would re-create the exact
    bug #290 fixed: a woman's talk scored with a male coach's weights, cue 1
    inverted, result still plausible. They keep their old stamps, which means
    they do not rank — harmless, since imports are corpus, not user-facing
    ranking. The script REPORTS the count so the gap is visible rather than
    silent.

BASELINE CHOICE. Resolution is identical to the record path — same
resolve_confidence_baseline, same resolve_take_sex. That is deliberate even
though a backfill could in principle do something cleverer: a piece re-stamped
under different rules than a freshly recorded one would re-introduce the very
comparability problem this script exists to remove. One consequence to know:
the baseline is TODAY'S (the speaker has more takes now than when the piece was
recorded), so a backfilled score is "what v2 says about this piece given
everything we now know about this speaker", not a reconstruction of what v2
would have said at the time. Across a corpus that is the more consistent basis.

IDEMPOTENT. A piece already stamped at the current version is skipped, so
re-running costs reads and changes nothing. Safe to re-run after a partial run.

DRY RUN BY DEFAULT. Nothing is written without --apply.

Usage:
  ./venv/bin/python scripts/backfill_voice_confidence.py --all
  ./venv/bin/python scripts/backfill_voice_confidence.py --all --apply
  ./venv/bin/python scripts/backfill_voice_confidence.py --user-id <uuid> --apply

After a full --apply run, warm best-presentation caches recompute on their own:
_BP_PAYLOAD_VERSION was bumped and the composite version is folded into
_bp_signature, so no cache can outlive the weighting change.
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _piece_rows(database, user_id: str, max_sessions: int) -> tuple:
    """(rows, session_count) — every snippet across the user's normal takes.

    Each row is (snippet_id, metrics_dict). Snippets with no metrics blob are
    dropped here; there is nothing to re-stamp on them."""
    rows: list = []
    sessions = database.v2_list_user_lab_sessions(
        user_id, limit=max_sessions) or []
    for s in sessions:
        sid = str(s.get("id") or "")
        if not sid:
            continue
        for snip in (database.get_snippets_by_session(sid) or []):
            metrics = snip.get("metrics")
            snippet_id = str(snip.get("id") or "")
            if snippet_id and isinstance(metrics, dict) and metrics:
                rows.append((snippet_id, metrics))
    return rows, len(sessions)


def backfill_user(database, user_id: str, *, apply: bool,
                  max_sessions: int) -> Counter:
    """Re-stamp one speaker. Returns a Counter of outcomes.

    The speaker is the unit of work because the composite is speaker-relative:
    baseline and sex are resolved ONCE and applied to every piece, which is
    both correct and what makes a whole corpus internally consistent."""
    from services.voice_confidence import (
        _VERSION, read_for_piece, resolve_confidence_baseline,
        resolve_take_sex,
    )
    out: Counter = Counter()

    rows, session_count = _piece_rows(database, user_id, max_sessions)
    out["sessions"] = session_count
    out["pieces"] = len(rows)
    if not rows:
        return out

    baseline, baseline_kind = resolve_confidence_baseline(
        user_id, [m for _sid, m in rows], database=database)
    if not baseline:
        # No usable reference — the honest outcome is silence, not a
        # fabricated neutral. Same rule the record path follows.
        out["skipped_no_baseline"] = len(rows)
        return out

    # session_context is None: these are normal takes by definition (the
    # listing filters to source='audit_upload'), so the account IS the speaker.
    sex, sex_source = resolve_take_sex(
        user_id, None, baseline, database=database)
    out[f"sex:{sex or 'unknown'}/{sex_source}"] = 1

    for snippet_id, metrics in rows:
        existing = metrics.get("voice_confidence")
        if isinstance(existing, dict):
            if existing.get("version") == _VERSION:
                out["already_current"] += 1
                continue
            out["from_v1"] += 1
        else:
            out["never_stamped"] += 1

        read = read_for_piece(metrics, baseline, baseline_kind, sex, sex_source)
        if read is None:
            out["unmeasurable"] += 1
            continue
        if not apply:
            out["would_write"] += 1
            continue
        updated = dict(metrics)
        updated["voice_confidence"] = read
        if database.update_snippet_metrics_blob(snippet_id, updated):
            out["written"] += 1
        else:
            out["write_failed"] += 1
    return out


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--user-id", help="re-stamp one speaker")
    group.add_argument("--all", action="store_true",
                       help="re-stamp every user with lab takes")
    ap.add_argument("--apply", action="store_true",
                    help="actually write. Without it this is a dry run.")
    ap.add_argument("--max-sessions", type=int, default=200)
    ap.add_argument("--user-cap", type=int, default=2000,
                    help="--all only: ceiling on users enumerated")
    args = ap.parse_args()

    from services.db import db
    from services.voice_confidence import _VERSION

    if args.all:
        user_ids = db.v2_list_all_auth_user_ids(args.user_cap) or []
    else:
        user_ids = [args.user_id]

    if not args.apply:
        print("DRY RUN — nothing will be written. Re-run with --apply.\n")
    print(f"target version: {_VERSION}   users: {len(user_ids)}\n")

    total: Counter = Counter()
    routes: Counter = Counter()
    touched_users = 0
    for i, uid in enumerate(user_ids, 1):
        try:
            counts = backfill_user(db, uid, apply=args.apply,
                                   max_sessions=args.max_sessions)
        except Exception as e:                       # keep going; report at end
            print(f"  [{i}/{len(user_ids)}] {uid}: FAILED — {e}",
                  file=sys.stderr)
            total["user_failed"] += 1
            continue
        if counts.get("pieces"):
            touched_users += 1
        for k, v in counts.items():
            (routes if k.startswith("sex:") else total)[k] += v

    print(f"users with pieces: {touched_users}")
    for k in ("sessions", "pieces", "already_current", "from_v1",
              "never_stamped", "unmeasurable", "skipped_no_baseline",
              "would_write", "written", "write_failed", "user_failed"):
        if total.get(k):
            print(f"  {k:<20} {total[k]}")

    if routes:
        print("\nsex routes applied (speakers, not pieces):")
        for k, v in sorted(routes.items()):
            print(f"  {k[4:]:<22} {v}")

    if total.get("write_failed"):
        print("\nWARNING: some writes failed — those pieces keep their old "
              "stamp and stay out of the ranking. Re-run; this is idempotent.",
              file=sys.stderr)

    print("\nTraining imports are NOT covered — an import's speaker identity "
          "lives in a transient session_context and cannot be recovered, so "
          "re-stamping one would risk applying the coach's weights to a "
          "stranger's voice (#290). They keep their old stamps and do not "
          "rank, which is harmless: imports are corpus, not user-facing "
          "ranking.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
