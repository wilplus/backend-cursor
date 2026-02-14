#!/usr/bin/env python3
"""
Run a single migration file. Uses DATABASE_URL (Postgres connection string) if set;
otherwise prints the SQL to run in Supabase Dashboard > SQL Editor.
"""
import os
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

def main():
    migration_name = "add_recording_1_processing_status"
    migration_path = Path(__file__).parent / "migrations" / f"{migration_name}.sql"
    if not migration_path.exists():
        print(f"Migration not found: {migration_path}", file=sys.stderr)
        sys.exit(1)

    sql = migration_path.read_text()
    database_url = os.getenv("DATABASE_URL")

    if database_url:
        try:
            import psycopg2
        except ImportError:
            print("Install psycopg2 to run migrations from the CLI: pip install psycopg2-binary", file=sys.stderr)
            sys.exit(1)
        try:
            conn = psycopg2.connect(database_url)
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute(sql)
            conn.close()
            print(f"Migration applied: {migration_name}")
        except Exception as e:
            print(f"Migration failed: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        print("DATABASE_URL is not set. Run this migration in Supabase Dashboard:\n")
        print("1. Open https://supabase.com/dashboard → your project → SQL Editor")
        print("2. New query, paste the SQL below, then Run.\n")
        print("--- SQL ---")
        print(sql)
        print("--- end ---")


if __name__ == "__main__":
    main()
