#!/usr/bin/env python3
"""Generate today's Life Panel daily card, then stop (BE-8).

    python3 scripts/generate_life_daily_cards.py --user-id <uuid> [--date YYYY-MM-DD]

Wire it to a 05:00 local cron if you want the card to exist before the day
starts. It is an OPTIMISATION, not a dependency: GET /v2/life/day generates the
same row on first read, so if the cron never fires the card is simply built
when the panel is opened. Nothing about the user's experience changes either
way, because nothing is delivered either way.

L-4 — GENERATION IS SCHEDULED; DELIVERY IS NOT. This script writes a row and
exits. No email, no push, no notification, no "you haven't opened it" check.
Not typing means living, not failing.

Why --user-id is required and there is no "all users" mode: iterating every
user would mean a cross-user read inside the life module, and every read in
services/life_store is scoped to one owner on purpose (a test enforces it).
The feature has one user today; when it has more, the right shape is one
invocation per user id, not a query that can see all of them at once.
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import life_engine as engine    # noqa: E402
from services import life_chat as chat        # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user-id", required=True, action="append",
                        dest="user_ids",
                        help="repeat for more than one user")
    parser.add_argument("--date", help="YYYY-MM-DD (default: today)")
    args = parser.parse_args()

    if not chat.is_enabled():
        print("LIFE_PANEL_ENABLED is off — nothing to do.")
        return 0

    target = date.fromisoformat(args.date) if args.date else None
    for user_id in args.user_ids:
        if not chat.has_consented(user_id):
            # No consent, no row. L-6 holds on the cron path too — a
            # scheduled job is not an exemption from "consent before any life
            # row is written".
            print(f"{user_id}: not consented — skipped")
            continue
        row = engine.ensure_daily_card(user_id, target)
        print(f"{user_id}: {'card ready' if row else 'generation failed'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
