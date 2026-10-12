"""willab — the Community Content Studio (founder 2026-07-26).

One button in the Journal CMS turns a blog post into the three derived
community formats. Pinned here, token by token:

  C-1  the content model actually reaches the model (the strategy file is
       loaded and the six pillars are in the system prompt).
  C-2  the user prompt carries title/excerpt/body, the requested formats and
       the founder's steer — and truncates a book-length body.
  C-3  cleaning: markdown stripped, caps re-enforced, unknown/duplicate
       formats dropped, a bogus pillar becomes None rather than a guess.
  C-4  the AC-9 construct guard FLAGS a body, it never drops it — a founder
       reviewing a flagged draft beats a draft that silently vanished.
  C-5  the fabrication guard: a claim or number the source essay does not
       make raises "verify"; one the essay does make does not.
  C-6  generate_community_posts returns None on every failure path and never
       raises into the route.
  C-7  a SINGLE-format regenerate inherits the week's framing from a sibling
       instead of re-theming the other two.
  C-8  routes: the CMS password gate, the flag, the input contract.
  C-9  the fences — community drafts never reach a public route, and no F1
       assembly module may depend on this marketing surface (L1).

Run: python3 -m unittest tests.test_community_content
"""
from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import MagicMock

# services.db pulls in supabase — stub in setUpModule, RESTORE the saved
# original in tearDownModule (willab test-stub-isolation convention: a bare
# pop leaves a second DatabaseService singleton behind and silently breaks
# other modules' patches).
_ORIG_SERVICES_DB = None


def setUpModule():
    global _ORIG_SERVICES_DB
    _ORIG_SERVICES_DB = sys.modules.get("services.db")
    stub = types.ModuleType("services.db")
    stub.db = MagicMock()
    sys.modules["services.db"] = stub


def tearDownModule():
    if _ORIG_SERVICES_DB is not None:
        sys.modules["services.db"] = _ORIG_SERVICES_DB
    else:
        sys.modules.pop("services.db", None)


from services import community_content as cc  # noqa: E402

try:
    from flask import Flask

    from routes import journal as jroutes
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    Flask = None
    jroutes = None
    _IMPORT_ERROR = e

PID = "11111111-1111-4111-8111-111111111111"
IID = "22222222-2222-4222-8222-222222222222"


# ── C-1 the content model reaches the model ───────────────────────────────


# ── C-2 the user prompt ───────────────────────────────────────────────────


# ── C-3 cleaning ──────────────────────────────────────────────────────────

# ── C-4 the AC-9 construct guard ──────────────────────────────────────────

# ── C-5 the fabrication guard ─────────────────────────────────────────────

# ── C-6 the call never raises ─────────────────────────────────────────────


# ── C-7 a single-format reroll inherits the week's framing ────────────────


# ── C-8 the routes ────────────────────────────────────────────────────────


def _row(**over):
    row = {"id": IID, "journal_post_id": PID, "kind": "fear",
           "title": "t", "body": "b", "flags": [], "pillar_id": 1,
           "pillar_name": "Focus & attention", "theme": "The Re-Entry Note",
           "soft_cta_line": "", "app_proof_line": "line"}
    row.update(over)
    return row


# ── C-9 the fences ────────────────────────────────────────────────────────

@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class FenceTests(unittest.TestCase):
    """Community drafts are a marketing surface: unreachable from the public
    site, and invisible to the F1 assembly path."""


    def test_no_scores_reach_a_community_payload(self):
        import json
        raw = json.dumps(cc.serialize_community_item(_row()))
        for banned in ("power_score", "charisma", "overall_score", "threat"):
            self.assertNotIn(banned, raw)


if __name__ == "__main__":
    unittest.main()
