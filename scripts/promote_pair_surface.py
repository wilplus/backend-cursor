#!/usr/bin/env python3
"""Door 4 by hand: promote a coach-answer surface's candidate, or kill it.

  python3 scripts/promote_pair_surface.py promote --surface praise_line \
      --model ft:gpt-4.1-mini-2025-04-14:willab:praise-line:abc --report <evaluation_report id>
  python3 scripts/promote_pair_surface.py kill --surface praise_line --reason "wrong tone"

Refuses while MLC2_PROMOTION_ENABLED is False or the surface is not in
PROMOTION_SURFACES (the founder's "open door 4 for surface S" is a reviewed
change). The kill never refuses on the door.
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import Config  # noqa: E402
from services.db import db  # noqa: E402
from services.model_promotion import PromotionRefusal, kill, promote  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="verb", required=True)
    p = sub.add_parser("promote")
    p.add_argument("--surface", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--report", required=True, help="evaluation_reports.id")
    p.add_argument("--by", default="ops:promote_pair_surface.py")
    k = sub.add_parser("kill")
    k.add_argument("--surface", required=True)
    k.add_argument("--reason", required=True)
    k.add_argument("--by", default="ops:promote_pair_surface.py")
    args = parser.parse_args()
    try:
        if args.verb == "promote":
            out = promote(db, surface=args.surface, candidate_model=args.model,
                          evaluation_report_id=args.report, by=args.by, config=Config)
        else:
            out = kill(db, surface=args.surface, by=args.by, reason=args.reason)
    except PromotionRefusal as refusal:
        print(f"refused ({refusal.code}): {refusal.message}")
        return 2
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
