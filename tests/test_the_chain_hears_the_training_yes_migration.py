"""The confidence chain hears the training yes: text pins on the migration.

Founder 2026-10-05, decisions log N48.5 Q27 A. The released rehearsal lane
proves the behaviour (tests/test_the_chain_hears_the_training_yes_postgres.py
and the chain's end-to-end suite); this file pins the TEXT: every re-issued
function differs from its latest source (manifest order) by exactly the lines
listed here and nothing else, the new functions are service-role only, and
the file is one additive transaction that opens no learning door.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "migrations"
FILE = "the_chain_hears_the_training_yes.sql"
SQL = (MIGRATIONS / FILE).read_text()


def _function(sql: str, name: str) -> str:
    match = re.search(
        rf"CREATE OR REPLACE FUNCTION public\.{name}\(.*?\n\$\$;", sql, flags=re.S)
    assert match, name
    return match.group(0)


def test_the_blind_rating_reader_is_blind_coach_only():
    body = _function(SQL, "get_mlc2_blind_coach_ratings_v1")
    assert "judgment.actor_provenance = 'blind_coach'" in body
    assert "packet.reviewer_role = 'coach'" in body
    for other in ("user_self_report", "blind_peer", "professional_evaluation",
                  "confidence_labels", "ml_machine_predictions"):
        assert other not in body


# ── F-8: verifications ───────────────────────────────────────────────────
