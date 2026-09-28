#!/usr/bin/env python3
"""Print how the shadow-stage spoken-word cues agree with coaches (D3a).

    python scripts/verbal_cue_shadow_report.py
    python scripts/verbal_cue_shadow_report.py --min-named 30 --min-caught 0.8

Read-only. With a bar, also says which cues clear it; promotion itself is a
migration a person writes after reading this.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--min-named", type=int, default=None)
    parser.add_argument("--min-caught", type=float, default=None)
    args = parser.parse_args()

    from services.db import db
    from services.verbal_cue_validation import meets_bar, report
    from services.verbal_cues import CUES, VERBAL_CUES_VERSION

    out = report(db, detector_version=VERBAL_CUES_VERSION, cues=CUES)
    if args.min_named is not None and args.min_caught is not None:
        for summary in out.values():
            ok, why = meets_bar(summary, min_named=args.min_named,
                                min_caught_rate=args.min_caught)
            summary["clears_bar"] = ok
            summary["why_not"] = why
    print(json.dumps({"detector_version": VERBAL_CUES_VERSION, "cues": out},
                     indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
