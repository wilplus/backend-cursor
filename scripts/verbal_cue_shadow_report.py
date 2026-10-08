#!/usr/bin/env python3
"""Print how the shadow-stage spoken-word cues agree with coaches (D3a; the
bar as amended 2026-10-05, decisions log N48.5 Q24 A).

    python scripts/verbal_cue_shadow_report.py

Read-only. Says which cues clear the founder's bar (30 coaches' Yes answers
in the blind error audit, 80% of them caught by the detector); promotion
itself is a migration a person writes after reading this. --min-yes /
--min-caught override the bar for a what-if.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--min-yes", type=int, default=None)
    parser.add_argument("--min-caught", type=float, default=None)
    args = parser.parse_args()

    from services.db import db
    from services.verbal_cue_validation import (
        PROMOTION_MIN_CAUGHT_RATE,
        PROMOTION_MIN_YES,
        meets_bar,
        report,
    )
    from services.verbal_cues import CUES, VERBAL_CUES_VERSION

    min_yes = PROMOTION_MIN_YES if args.min_yes is None else args.min_yes
    min_caught = (PROMOTION_MIN_CAUGHT_RATE if args.min_caught is None
                  else args.min_caught)
    out = report(db, detector_version=VERBAL_CUES_VERSION, cues=CUES)
    for summary in out.values():
        ok, why = meets_bar(summary, min_yes=min_yes,
                            min_caught_rate=min_caught)
        summary["clears_bar"] = ok
        summary["why_not"] = why
    print(json.dumps({"detector_version": VERBAL_CUES_VERSION,
                      "bar": {"min_yes": min_yes,
                              "min_caught_rate": min_caught},
                      "cues": out},
                     indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
