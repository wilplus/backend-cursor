#!/usr/bin/env python3
"""What we actually pay OpenAI, per surface — the Phase 0 readout.

Reads the ``llm_usage`` table and prints the rollup that
docs/PRICING-TOKENS-PLAN.md needs in order to replace its ESTIMATED ×7
multipliers with measured ones.

There is deliberately no psql dependency: this host has none, and the founder
works from the Supabase SQL Editor. It talks to PostgREST with
SUPABASE_SERVICE_ROLE_KEY from .env, exactly like any other service here.

    ./venv/bin/python scripts/llm_usage_report.py            # last 30 days
    ./venv/bin/python scripts/llm_usage_report.py --days 7
    ./venv/bin/python scripts/llm_usage_report.py --per-take # cost per session

READ-ONLY. It never writes, and it prints no user content — the table holds
none (see test_llm_usage.test_no_prompt_or_completion_text_can_reach_the_table).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timedelta, timezone

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PAGE = 1000


def _load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    path = os.path.join(_REPO, ".env")
    if not os.path.exists(path):
        return env
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def _fetch(url: str, key: str, since_iso: str) -> list[dict]:
    rows: list[dict] = []
    offset = 0
    select = "surface,model,tokens_in,tokens_out,audio_seconds,cost_usd,session_id,created_at"
    while True:
        q = (f"{url}/rest/v1/llm_usage?select={urllib.parse.quote(select)}"
             f"&created_at=gte.{urllib.parse.quote(since_iso)}")
        req = urllib.request.Request(q, headers={
            "apikey": key, "Authorization": f"Bearer {key}",
            "Range-Unit": "items", "Range": f"{offset}-{offset + _PAGE - 1}",
        })
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                batch = json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            body = e.read().decode()[:300]
            if "llm_usage" in body and ("does not exist" in body or e.code == 404):
                sys.exit("llm_usage table not found — run "
                         "migrations/add_llm_usage.sql in the Supabase SQL Editor.")
            sys.exit(f"HTTP {e.code}: {body}")
        rows.extend(batch)
        if len(batch) < _PAGE:
            return rows
        offset += _PAGE


def _num(v, default=0.0) -> float:
    try:
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--per-take", action="store_true",
                    help="cost per session_id — the number §2 of the plan prices on")
    args = ap.parse_args()

    env = _load_env()
    url = (env.get("SUPABASE_URL") or os.getenv("SUPABASE_URL") or "").rstrip("/")
    key = env.get("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY") or ""
    if not url or not key:
        sys.exit("missing SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY")

    since = datetime.now(timezone.utc) - timedelta(days=args.days)
    rows = _fetch(url, key, since.isoformat())
    if not rows:
        print(f"No llm_usage rows in the last {args.days} days.\n"
              "Either the migration has not run, LLM_USAGE_ENABLED=0, or "
              "nothing has been recorded yet.")
        return

    agg: dict[str, dict] = defaultdict(
        lambda: {"calls": 0, "in": 0, "out": 0, "sec": 0.0, "usd": 0.0})
    total_usd = 0.0
    for r in rows:
        a = agg[r.get("surface") or "?"]
        a["calls"] += 1
        a["in"] += int(_num(r.get("tokens_in")))
        a["out"] += int(_num(r.get("tokens_out")))
        a["sec"] += _num(r.get("audio_seconds"))
        a["usd"] += _num(r.get("cost_usd"))
        total_usd += _num(r.get("cost_usd"))

    print(f"\n{'=' * 88}")
    print(f"llm_usage — last {args.days} days · {len(rows):,} calls · ${total_usd:.4f} total")
    print("=" * 88)
    print(f"{'surface':<26}{'calls':>7}{'tok_in':>11}{'tok_out':>10}"
          f"{'audio_s':>10}{'usd':>11}{'%':>7}")
    print("-" * 88)
    for surface, a in sorted(agg.items(), key=lambda kv: -kv[1]["usd"]):
        pct = (100 * a["usd"] / total_usd) if total_usd else 0.0
        print(f"{surface[:25]:<26}{a['calls']:>7}{a['in']:>11,}{a['out']:>10,}"
              f"{a['sec']:>10.0f}{a['usd']:>11.4f}{pct:>6.1f}%")
    print("-" * 88)
    print(f"{'TOTAL':<26}{len(rows):>7}{'':<21}{'':>10}{total_usd:>11.4f}")

    # Per-surface cost-per-take. Deliberately derived by DIVISION rather than
    # by grouping on session_id: only the Whisper surfaces carry session
    # attribution today (chat_complete accepts session_id but no caller passes
    # it yet — Phase 0.1). Grouping would therefore report a "take" as costing
    # only its transcription, understating it by ~2×. Dividing each surface's
    # total by the take count is unbiased and needs no attribution at all.
    takes = sum(a["calls"] for s, a in agg.items() if s.startswith("whisper_")
                and s != "whisper_snippet")
    if takes:
        print(f"\n{'=' * 88}\nPER TAKE — {takes:,} takes (surface total ÷ take count)\n{'=' * 88}")
        per_take = total_usd / takes
        for surface, a in sorted(agg.items(), key=lambda kv: -kv[1]["usd"])[:8]:
            print(f"  {surface[:34]:<36}${a['usd'] / takes:.5f}")
        print(f"  {'─' * 34}  {'─' * 8}")
        print(f"  {'TOTAL PER TAKE':<36}${per_take:.5f}")
        tok = round(per_take * 7 * 10000, -2)
        print(f"\n  At the plan's 10,000 tokens = $1.00 peg, a ×7 price on this is")
        print(f"  {tok:,.0f} willab tokens. docs/PRICING-TOKENS-PLAN.md §2 currently")
        print(f"  prices a <2 min take at 1,000 and a 2-6 min take at 3,000.")
        if not any(r.get("session_id") for r in rows
                   if not (r.get("surface") or "").startswith("whisper_")):
            print("\n  NOTE: only Whisper rows carry session_id, so this is a MEAN, not a")
            print("  distribution. For per-take spread, thread session_id through the")
            print("  chat_complete callers (Phase 0.1) — the column is already there.")

    if args.per_take:
        per: dict[str, float] = defaultdict(float)
        for r in rows:
            sid = r.get("session_id")
            if sid:
                per[sid] += _num(r.get("cost_usd"))
        if not per:
            print("\nNo session_id attribution yet — nothing to roll up per session.")
            return
        vals = sorted(per.values())
        print(f"\n{'=' * 88}\nBY session_id — {len(vals):,} sessions\n{'=' * 88}")
        print("  WARNING: attributed surfaces only (today: Whisper). This is a FLOOR on")
        print("  what a take costs, not the whole of it — see the note above.")
        print(f"  mean   ${sum(vals) / len(vals):.4f}")
        print(f"  median ${vals[len(vals) // 2]:.4f}")
        print(f"  p90    ${vals[int(len(vals) * 0.9)]:.4f}")
        print(f"  max    ${vals[-1]:.4f}")


if __name__ == "__main__":
    main()
