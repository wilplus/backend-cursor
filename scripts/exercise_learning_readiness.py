#!/usr/bin/env python3
"""Print how close exercise learning is to its evidence bar (step 8 prep).

    python scripts/exercise_learning_readiness.py

Read-only. Counts first-exposure attempts with a valid endpoint against the
bar in exercise-adequacy-label-v1 (§3.5 item 8: 300 in all, 30 per
exercise). It never computes whether an exercise helped.
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main() -> int:
    from services.db import db
    from services.exercise_learning_readiness import readiness
    print(json.dumps(readiness(db), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
