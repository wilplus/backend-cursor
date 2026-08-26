#!/usr/bin/env python3
"""
Export admin_annotation_events → OpenAI Chat fine-tuning JSONL (plaintext messages).

This is the "refinery" output for SFT: each line is
  {"messages":[{"role":"system",...},{"role":"user",...},{"role":"assistant",...}]}

Security / privacy:
  - Contains coach and AI text; treat as sensitive. Do not commit outputs to git.
  - Run from a trusted machine with .env (SUPABASE_SERVICE_ROLE_KEY).

Usage:
  python3 scripts/export_openai_finetuning_jsonl.py \
    --surface say_it_stronger -o training.jsonl --enrich-sessions

OpenAI fine-tuning: upload JSONL via API or dashboard. At inference, use the same API key and
pass model=\"ft:...\" (not a different key).

Deployment: set e.g. OPENAI_HOMEWORK_MODEL=ft:gpt-4o-mini:org:... in backend env and wire
openai_service to read it (product-specific).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.db import db  # noqa: E402
from services.ml_finetuning_export import (  # noqa: E402
    event_to_openai_messages,
    example_to_jsonl_line,
    fetch_events_for_export,
    fetch_sessions_map,
)
from services.ml_surface_contracts import (  # noqa: E402
    contract_for_surface,
    fields_for_surface,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Export annotation events to OpenAI fine-tuning JSONL.")
    parser.add_argument("--surface", required=True, help="Canonical correction surface")
    parser.add_argument("-o", "--output", required=True, help="Output .jsonl path")
    parser.add_argument("--limit", type=int, default=10_000, help="Max rows from DB (ordered by created_at)")
    parser.add_argument("--since", type=str, default=None, help="Only events with created_at > this ISO timestamp")
    parser.add_argument(
        "--enrich-sessions",
        action="store_true",
        help="Join v2_sessions for context_short / score when session_id is set",
    )
    parser.add_argument(
        "--skip-identical",
        action="store_true",
        help="Skip rows where coach_final_text equals ai_original_text (after strip)",
    )
    args = parser.parse_args()

    contract = contract_for_surface(args.surface)
    field_filter = fields_for_surface(contract.id)

    rows = fetch_events_for_export(
        db.client,
        limit=args.limit,
        since_iso=args.since,
        field_names=field_filter,
    )

    sessions: dict = {}
    if args.enrich_sessions:
        sids = [str(r.get("session_id") or "") for r in rows]
        sessions = fetch_sessions_map(db.client, sids)

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    written = 0
    skipped = 0
    with out_path.open("w", encoding="utf-8") as fh:
        for row in rows:
            if args.skip_identical:
                a = (row.get("ai_original_text") or "").strip()
                c = (row.get("coach_final_text") or "").strip()
                if a and c and a == c:
                    skipped += 1
                    continue

            sid = str(row.get("session_id") or "").strip() or None
            sess = sessions.get(sid) if sid else None
            ex = event_to_openai_messages(row, session=sess)
            if not ex:
                skipped += 1
                continue
            fh.write(example_to_jsonl_line(ex) + "\n")
            written += 1

    print(
        f"Wrote {written} {contract.id} examples to {out_path} "
        f"(skipped {skipped}, scanned {len(rows)})"
    )


if __name__ == "__main__":
    main()
