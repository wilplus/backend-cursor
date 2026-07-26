#!/usr/bin/env python3
"""Import the Life Panel corpus from the three export files (BE-3).

Dry run first — it is the default, and it reports exactly what the real run
would write plus everything a human has to look at:

    python3 scripts/import_life_corpus.py \
        --user-id <uuid> \
        --principles ~/exports/principles.json \
        --timeline   ~/exports/timeline.json \
        --strategy   ~/exports/strategy.json

Then, once the counts and the review queue look right:

    ... --write

Idempotent: every row carries an external_id, and the unique partial indexes
on (user_id, external_id) turn a re-run into an update rather than a duplicate.
Run it, check it, fix the export, run it again.

Before ANY of this: take the exports (BE-0). principles-app has no export
button — its data lives in localStorage mirrored to an unauthenticated
Firestore doc, and one cleared browser profile loses a four-year corpus. That
change is ~10 lines in the OTHER repo and it is the only thing standing
between the founder and an unrecoverable localStorage clear.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import life_import as importer   # noqa: E402


def _load(path: str | None) -> dict | None:
    if not path:
        return None
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--principles", help="principles-app export JSON")
    parser.add_argument("--timeline", help="timeline export JSON")
    parser.add_argument("--strategy", help="transcribed strategy docs JSON")
    parser.add_argument("--write", action="store_true",
                        help="actually write (default is a dry run)")
    args = parser.parse_args()

    if not any((args.principles, args.timeline, args.strategy)):
        parser.error("give at least one export file")

    plan = importer.build_plan(
        args.user_id,
        principles_export=_load(args.principles),
        timeline_export=_load(args.timeline),
        strategy_export=_load(args.strategy),
    )

    print("PLANNED")
    for key, value in (plan.get("counts") or {}).items():
        print(f"  {key:14} {value}")

    review = plan.get("review") or []
    if review:
        # Loud on purpose. An unmapped category is the one thing here that
        # needs a human before it means anything, and a quiet line in a long
        # log is a line nobody reads.
        print(f"\nNEEDS REVIEW — {len(review)} case(s) carry a category "
              f"outside the fixed six.")
        print("They import with the raw label parked in import_category_raw; "
              "nothing was coerced.")
        for entry in review:
            print(f"  · {entry['unmapped']}  ← {entry['case_at_hand']!r}")

    result = importer.apply_plan(args.user_id, plan, dry_run=not args.write)
    if result["dry_run"]:
        print("\nDRY RUN — nothing written. Re-run with --write.")
    else:
        print("\nWRITTEN")
        for key, value in result["written"].items():
            print(f"  {key:14} {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
