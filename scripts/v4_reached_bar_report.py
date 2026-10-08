#!/usr/bin/env python3
"""V4 B1.4b: print the reached-bar calibration report (founder O4).

Read-only. Run with the service key in the environment, as the app does:
    python scripts/v4_reached_bar_report.py
The JSON goes into the decisions log; a calibrated bar becomes a new
BAR_VERSION in services/v4_reached_bar.py in its own reviewed change.
Internal only (AC-9)."""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def main() -> int:
    from services.db import db
    from services.v4_reached_bar import gather
    print(json.dumps(gather(db), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
