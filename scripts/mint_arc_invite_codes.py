#!/usr/bin/env python3
"""Mint founding free-pass invite codes for Paid Audits (BE chunk A4).

Each code grants ONE 'founding_pass' arc_purchase when redeemed via
POST /v2/arc/<arc_id>/redeem. Existing/early users use these for a free audit.

Usage:
    python3 scripts/mint_arc_invite_codes.py            # 30 codes, 1 use each
    python3 scripts/mint_arc_invite_codes.py 50         # 50 codes
    python3 scripts/mint_arc_invite_codes.py 30 --max-uses 1 --prefix WILLAB

Prints each minted code (hand these out). Idempotent per code (a re-run of the
same code returns the existing row). Needs the same Supabase env as the app and
migrations/add_arc_invite_codes.sql applied.
"""
from __future__ import annotations

import argparse
import secrets
import sys

# Unambiguous alphabet — no 0/O/1/I/L to keep codes easy to read out loud.
_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"


def _gen_code(prefix: str, length: int = 6) -> str:
    body = "".join(secrets.choice(_ALPHABET) for _ in range(length))
    return f"{prefix}-{body}" if prefix else body


def main() -> int:
    ap = argparse.ArgumentParser(description="Mint arc invite codes (A4).")
    ap.add_argument("count", nargs="?", type=int, default=30,
                    help="how many codes to mint (default 30)")
    ap.add_argument("--max-uses", type=int, default=1,
                    help="uses per code (default 1)")
    ap.add_argument("--prefix", default="WILLAB",
                    help="code prefix (default WILLAB)")
    ap.add_argument("--note", default="founding-pass",
                    help="human label stored on each code")
    args = ap.parse_args()

    from services.db import db

    minted, seen = [], set()
    attempts = 0
    while len(minted) < args.count and attempts < args.count * 20:
        attempts += 1
        code = _gen_code(args.prefix.strip())
        if code in seen:
            continue
        seen.add(code)
        row = db.create_arc_invite_code(
            code, max_uses=args.max_uses, note=args.note,
        )
        if row:
            minted.append(row.get("code") or code)

    if not minted:
        print("ERROR: no codes minted — check Supabase env + run "
              "migrations/add_arc_invite_codes.sql", file=sys.stderr)
        return 1

    print(f"Minted {len(minted)} invite code(s), {args.max_uses} use(s) each:\n")
    for c in minted:
        print(f"  {c}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
