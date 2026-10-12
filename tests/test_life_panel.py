"""willab — The Life Panel (founder-directed 2026-07-26).

Every non-negotiable in PROMPT-BE-life-panel.md §0 is a test here, not a note:

  N1  RLS on every life_* table IN ITS CREATING MIGRATION
  N2  no product-side module imports the life module; the SHARED master body
      is never written to
  N3  a non-participating user's chat is byte-identical — the router hands the
      turn back untouched
  N4  the per-user master-doc injection is capped and trimmed, and is absent
      entirely for everyone who has not opted in
  N5  the system never authors reflective prose (L-1)
  N6  nothing reaches the strategy doc without an approved proposal, and the
      immutable core is never proposed against (L-2 / L-2a)
  N7  at most one strategy proposal surfaced per day (L-2b)
  N8  zero scheduled outbound anything (L-4)
  N9  hard delete actually deletes; export returns everything

Plus the locked rules the routes rest on: the hashtag grammar (§5), the fixed
six-entry taxonomy (§3.1), the phrase wall's relevance floor and no-repeat
window, L-3's both-sides-never-a-winner, and the importer's preservation
guarantees (BE-3).

The pure-layer tests import ONLY services.life_panel, which has no DB and no
network — so they run in CI unconditionally. The route/store tests need the
app's dependency graph and skip cleanly when it is unavailable, following the
house pattern in test_journal.py.

Run: python3 -m unittest tests.test_life_panel

N3's full form is a SUITE-level gate, not a single test — "the full existing
chat suite re-run under a non-participating user". Run it with the flag ON and
no consent row, which is exactly that state:

    LIFE_PANEL_ENABLED=1 python3 -m pytest -q

Green means the hook falls through untouched for everyone who has not opted
in. If that run ever goes red on a NON-life test, the hook has started
changing responses it must not change.
"""
from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

# Placeholder credentials BEFORE the app graph is imported: config.py and
# services/db.py read the environment at import time, and the Supabase client
# validates the key's SHAPE at construction. These never leave the process —
# every store call in this file is mocked.
os.environ.setdefault("SUPABASE_URL", "https://life-panel-test.invalid")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "aaaa.bbbb.cccc")


from services import life_panel as lp  # noqa: E402  (pure, always importable)

try:
    from flask import Flask

    import auth
    from routes import life_reminders_webhook as lremhook
    from routes import life_routes as lroutes
    from services import life_chat as lchat
    from services import life_engine as lengine
    from services import life_reminders as lreminders
    from services import life_store as lstore
    from services import master_doc_rag as mdr
    _IMPORT_ERROR = None
except Exception as e:                          # pragma: no cover
    Flask = None
    auth = lroutes = lremhook = lchat = lengine = lreminders = lstore = None
    mdr = None
    _IMPORT_ERROR = e

USER = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"


MIGRATION = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "migrations", "add_life_panel.sql")


# ═════════════════════════════════════════════════════════════════════════
# N1 — RLS in the creating migration
# ═════════════════════════════════════════════════════════════════════════


# ═════════════════════════════════════════════════════════════════════════
# §5 — the hashtag grammar
# ═════════════════════════════════════════════════════════════════════════


# ═════════════════════════════════════════════════════════════════════════
# The reality layer — #thoughts / #reflections / #observations
# ═════════════════════════════════════════════════════════════════════════
# Founder-agreed 2026-08-02: these tags are CONTEXT for the strategy, never a
# trigger. Capture costs nothing (no model call, no proposal); retrieval feeds
# compare_to_strategy as background; a reflection is never the warrant.


# ═════════════════════════════════════════════════════════════════════════
# §3.1 — the fixed six-entry taxonomy
# ═════════════════════════════════════════════════════════════════════════


# ═════════════════════════════════════════════════════════════════════════
# N5 / L-1 — the system never authors reflective prose
# ═════════════════════════════════════════════════════════════════════════


# ═════════════════════════════════════════════════════════════════════════
# N6 / L-2a — the immutable core
# ═════════════════════════════════════════════════════════════════════════


# ═════════════════════════════════════════════════════════════════════════
# N7 / L-2b — the change budget
# ═════════════════════════════════════════════════════════════════════════


# ═════════════════════════════════════════════════════════════════════════
# The phrase wall — floor + no-repeat
# ═════════════════════════════════════════════════════════════════════════


# ═════════════════════════════════════════════════════════════════════════
# L-3 — surface paradoxes, never resolve them
# ═════════════════════════════════════════════════════════════════════════


# ═════════════════════════════════════════════════════════════════════════
# The board, due labels, and item validation
# ═════════════════════════════════════════════════════════════════════════


# ═════════════════════════════════════════════════════════════════════════
# L-5 — the application log
# ═════════════════════════════════════════════════════════════════════════


# ═════════════════════════════════════════════════════════════════════════
# BE-3 — the importer's preservation guarantees
# ═════════════════════════════════════════════════════════════════════════


# ═════════════════════════════════════════════════════════════════════════
# Serialization
# ═════════════════════════════════════════════════════════════════════════

class SerializationTests(unittest.TestCase):

    def test_no_payload_carries_a_score_or_a_verdict(self):
        blob = json.dumps({
            "case": lp.serialize_case({"case_at_hand": "x",
                                       "category": ["hubris"]}),
            "item": lp.serialize_item({"kind": "principle", "title": "t"}),
            "day": lp.serialize_day({"one_thing": "x"}),
            "week": lp.serialize_week({}),
            "proposal": lp.serialize_proposal({"target": "weekly.goals"}),
        })
        for banned in ("power_score", "charisma", "overall_score", "threat",
                       "verdict", "confidence", "relevance"):
            self.assertNotIn(banned, blob)


# ═════════════════════════════════════════════════════════════════════════
# N3 — the chat router hands a non-participant's turn back untouched
# ═════════════════════════════════════════════════════════════════════════

@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class ChatIsolationTests(unittest.TestCase):


    def test_the_cache_never_leaks_between_users(self):
        lchat._consent_cache.clear()
        with patch.object(lchat.store, "get_consent", return_value={"id": "c"}):
            self.assertTrue(lchat.has_consented(USER))
        with patch.object(lchat.store, "get_consent",
                          return_value=None) as read:
            self.assertFalse(lchat.has_consented(OTHER))
        read.assert_called_once()
        lchat._consent_cache.clear()


# ═════════════════════════════════════════════════════════════════════════
# BE-8 — the daily card, and the rank rule that survives Bet 3 joining it
# ═════════════════════════════════════════════════════════════════════════


# ═════════════════════════════════════════════════════════════════════════
# N4 — the per-user master-doc injection
# ═════════════════════════════════════════════════════════════════════════


# ═════════════════════════════════════════════════════════════════════════
# N8 — zero scheduled outbound anything (L-4)
# ═════════════════════════════════════════════════════════════════════════


# ═════════════════════════════════════════════════════════════════════════
# N2 — the fence: this feature stays off the live loop
# ═════════════════════════════════════════════════════════════════════════


# ═════════════════════════════════════════════════════════════════════════
# N9 + the gate — routes
# ═════════════════════════════════════════════════════════════════════════


# ═════════════════════════════════════════════════════════════════════════
# BE-10 — the corpus never reaches a log or a prompt in bulk
# ═════════════════════════════════════════════════════════════════════════


# ═════════════════════════════════════════════════════════════════════════
# Item 9 (founder 2026-07-30) — setup strategy-document upload + drafting
# ═════════════════════════════════════════════════════════════════════════


# ═════════════════════════════════════════════════════════════════════════
# Item 12 (founder 2026-07-30) — the opt-in reminder machinery itself
# ═════════════════════════════════════════════════════════════════════════


# ═════════════════════════════════════════════════════════════════════════
# Editable check-in copy (founder decision 2026-07-30: "my copy as default,
# editable")
# ═════════════════════════════════════════════════════════════════════════


# ═════════════════════════════════════════════════════════════════════════
# Piece 5 (founder-agreed program, 2026-08-02) — the monthly + quarterly
# reviews read the reflections layer
# ═════════════════════════════════════════════════════════════════════════


if __name__ == "__main__":
    unittest.main()
