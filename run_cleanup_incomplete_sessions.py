#!/usr/bin/env python3
"""
Run cleanup of incomplete sessions (and their recordings, pre/post answers) older than N days.
Use for cron (e.g. daily with days=10) or to test without waiting 10 days.

Examples:
  # Dry-run: what would be deleted after 10 days (no actual delete)
  python3 run_cleanup_incomplete_sessions.py --days 10 --dry-run

  # Test without waiting 10 days: dry-run for sessions older than ~1 hour
  python3 run_cleanup_incomplete_sessions.py --days 0.04 --dry-run

  # Actually delete incomplete sessions older than ~1 hour (for testing)
  python3 run_cleanup_incomplete_sessions.py --days 0.04

  # Production: delete incomplete sessions older than 10 days
  python3 run_cleanup_incomplete_sessions.py --days 10
"""
import argparse
import os
import sys

# Load env so config works
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from services.db import db


def main():
    parser = argparse.ArgumentParser(description="Clean up incomplete recording sessions older than N days")
    parser.add_argument("--days", type=float, default=10, help="Delete sessions older than this many days (default 10)")
    parser.add_argument("--dry-run", action="store_true", help="Only list what would be deleted; do not delete")
    args = parser.parse_args()

    if args.days < 0:
        print("Error: --days must be >= 0", file=sys.stderr)
        sys.exit(1)

    count, ids = db.cleanup_incomplete_sessions(days=args.days, dry_run=args.dry_run)
    if args.dry_run:
        print(f"Dry-run: would delete {count} incomplete session(s) older than {args.days} days")
        if ids:
            for sid in ids:
                print(f"  - {sid}")
    else:
        print(f"Deleted {count} incomplete session(s) older than {args.days} days")
        if ids:
            for sid in ids:
                print(f"  - {sid}")
    sys.exit(0 if count >= 0 else 1)


if __name__ == "__main__":
    main()
