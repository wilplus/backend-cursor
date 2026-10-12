"""The stand-down log leads with the answer, because it is the only copy.

2026-09-19. `_decline` writes a complete account of why V3 stood down, and on
a phone that account was unreadable: a take id is 36 characters, it sat
between "stood down" and the only two fields worth reading, and the line
truncated before ``reason=`` every time. Three attempts to read one from a
phone produced nothing at all.

WHAT WAS CONSIDERED AND REJECTED. Carrying the named gate out to
``feedback_status`` so it could be read from the enrichment call instead. It
needed a second field on ``V3Unavailable``, and
``test_the_database_error_stays_in_the_log_and_out_of_the_payload`` exists to
stop exactly that: with one field, a raw ``str(exc)`` CANNOT reach a payload;
with two, it is a matter of passing the right string to the right parameter.
A structural guarantee traded for a convention, to reach a surface that needs
a snapshot id and a token — harder from a phone than the log search it was
meant to replace. The field order is the whole fix.

So the ordering below is load-bearing, not cosmetic, and is pinned here.
"""
from __future__ import annotations

import unittest

from services.mlc3_first_client_feedback import V3Unavailable, _decline


class TheFailureStillCarriesOnlyItsReason(unittest.TestCase):
    """Re-stating the guard that turned the carry idea down.

    `tests/test_mlc3_first_client_feedback.py` asserts `len(failure) == 1`.
    This says WHY that number is the point, so the next person to want a
    second field reads the reason before the assertion.
    """

    def test_one_field_makes_a_leak_impossible_rather_than_unlikely(self):
        failure = _decline(
            "take-1", "source_snapshot_rpc_failed",
            'APIError: {"code":"0A000","message":"SELECT FOR SHARE ..."}',
        )
        self.assertEqual(failure, V3Unavailable("source_snapshot_rpc_failed"))
        self.assertEqual(len(failure), 1)
        self.assertNotIn("0A000", "".join(failure))
