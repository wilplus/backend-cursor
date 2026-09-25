"""Practice made for people who never ticked the box (founder decision 1).

FOUNDER 2026-09-25: delete the practice recordings made for people who never
ticked "Personalised practice" — after a preview of the exact list is
approved. Cleanup of data is a separately authorised, previewed operation,
never a migration side effect (CLAUDE.md), so this is two steps run by hand:

  preview   lists every person in the `unticked` group (0363) with the
            practice ids that would go, and a SHA-256 of that list. It also
            reports the `ticked` and `no_receipt` groups, which it never
            touches.
  execute   rebuilds the list, refuses unless its hash is the approved one,
            then erases each person's practice through the same byte-verified
            step turning practice off uses (practice_retention, E2 = C).

A list that changed between the preview and the execute is refused whole:
someone who ticked the box in between must not be erased on a stale
approval.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from services.practice_retention import erase_practice_for_principal


def _groups(database: Any) -> dict[str, list[dict]]:
    rows = database.client.rpc("list_practice_without_the_tick_v1", {}).execute().data
    if not isinstance(rows, list):
        raise RuntimeError("PRACTICE_TICK_LIST_UNAVAILABLE")
    groups: dict[str, list[dict]] = {"unticked": [], "ticked": [], "no_receipt": []}
    for row in rows:
        category = str((row or {}).get("category") or "")
        if category not in groups:
            raise RuntimeError(f"PRACTICE_TICK_CATEGORY_UNKNOWN:{category}")
        groups[category].append(row)
    return groups


def preview(database: Any) -> dict:
    """What an execute would erase, and the hash an operator approves."""
    groups = _groups(database)
    people = []
    for row in sorted(groups["unticked"], key=lambda r: str(r["principal_id"])):
        principal = str(row["principal_id"])
        practice_ids = sorted(database.practice_ids_for_principal(principal))
        people.append({"principal_id": principal, "practice_ids": practice_ids})
    erasable = [person for person in people if person["practice_ids"]]
    digest = hashlib.sha256(json.dumps(
        erasable, sort_keys=True, separators=(",", ":"),
    ).encode()).hexdigest()
    return {
        "mode": "preview",
        "erase": erasable,
        "erase_people": len(erasable),
        "erase_practices": sum(len(p["practice_ids"]) for p in erasable),
        "sha256": digest,
        "untouched": {
            "ticked_people": len(groups["ticked"]),
            "no_receipt_people": len(groups["no_receipt"]),
            "no_receipt_practices": sum(
                int(r.get("practice_count") or 0) for r in groups["no_receipt"]),
        },
    }


def execute(database: Any, *, approved_sha256: str) -> dict:
    """Erase exactly the approved list, or nothing."""
    current = preview(database)
    if not approved_sha256 or current["sha256"] != approved_sha256.strip().lower():
        raise SystemExit("PRACTICE_TICK_LIST_CHANGED_SINCE_APPROVAL")
    results = []
    for person in current["erase"]:
        outcome = erase_practice_for_principal(
            database=database, principal_id=person["principal_id"])
        results.append({"principal_id": person["principal_id"], **outcome})
    return {
        "mode": "execute",
        "sha256": current["sha256"],
        "people": results,
        "complete": all(item.get("complete") for item in results),
    }
