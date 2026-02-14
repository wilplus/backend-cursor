#!/usr/bin/env python3
"""
Clean up incomplete v2_sessions (homework flow) older than N hours.
Run via cron (e.g. every 15–60 min) so stale sessions are removed and users can start fresh.

Default: 1 hour. Incomplete = status != 'completed'.

Examples:
  # Dry-run: list what would be deleted (sessions older than 1 hour)
  python3 run_cleanup_v2_sessions.py --dry-run

  # Delete incomplete v2_sessions older than 1 hour (default)
  python3 run_cleanup_v2_sessions.py

  # Custom threshold: 30 minutes
  python3 run_cleanup_v2_sessions.py --hours 0.5

  # 2 hours
  python3 run_cleanup_v2_sessions.py --hours 2
"""
import argparse
import sys

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from services.db import db


def main():
    parser = argparse.ArgumentParser(
        description="Clean up incomplete v2 (homework) sessions older than N hours"
    )
    parser.add_argument(
        "--hours",
        type=float,
        default=1.0,
        help="Delete sessions older than this many hours (default 1)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only list what would be deleted; do not delete",
    )
    args = parser.parse_args()

    if args.hours <= 0:
        print("Error: --hours must be > 0", file=sys.stderr)
        sys.exit(1)

    count, ids = db.v2_cleanup_incomplete_sessions(hours=args.hours, dry_run=args.dry_run)
    if args.dry_run:
        print(f"Dry-run: would delete {count} incomplete v2 session(s) older than {args.hours} hour(s)")
        for sid in ids:
            print(f"  - {sid}")
    else:
        print(f"Deleted {count} incomplete v2 session(s) older than {args.hours} hour(s)")
        for sid in ids:
            print(f"  - {sid}")
    sys.exit(0 if count >= 0 else 1)


if __name__ == "__main__":
    main()
