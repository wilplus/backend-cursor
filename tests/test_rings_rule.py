"""The rule, every clause (rings, 0394).

    A feature is on for a person when the row is not killed, the person's
    ring is >= the feature's ring, the row's attribute rule matches them
    (AND of "key is in list"), and, for a feature with a consent purpose,
    that consent is current for that person.

The database function ``feature_is_on_v1`` is what every gate calls; the
Python mirror in services/rings.py is what the People tab previews with, and
tests/test_rings_postgres.py asserts the two agree on this same matrix on the
released lane. Here: the mirror, clause by clause, then the read side's
fail-closed behaviour and the one-way kill against a fake client.
"""
from __future__ import annotations

from services import rings

P1 = "11111111-1111-4111-8111-111111111111"


def _feature(**overrides) -> dict:
    row = {"feature": "thing", "min_ring": 3, "attribute_rule": None,
           "consent_purpose": None, "killed": False, "one_way": False}
    row.update(overrides)
    return row


def _person(ring: int, **attributes) -> dict:
    return {"principal_id": P1, "ring": ring, "attributes": attributes}


# ── the rule ───────────────────────────────────────────────────────────────


def test_a_ring_never_substitutes_for_consent():
    """L3: the highest ring in the world does not turn a consent feature on."""
    row = _feature(min_ring=0, consent_purpose="pooled_model_improvement")
    assert rings.rule_is_on(row, _person(10_000), 2, False) is False


# ── the read side ──────────────────────────────────────────────────────────


# ── the writes ─────────────────────────────────────────────────────────────


# ── attributes ─────────────────────────────────────────────────────────────
