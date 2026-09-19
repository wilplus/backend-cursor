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


class TheAnswerLeadsAndTheIdentifierTrails(unittest.TestCase):
    def _line(self, reason: str = "service_inventory_unavailable",
              detail: str = "") -> str:
        with self.assertLogs(
            "services.mlc3_first_client_feedback", level="INFO",
        ) as caught:
            _decline("440b7c97-a031-4388-8f3c-cdb800b7d10c", reason, detail)
        return caught.output[0]

    def test_the_reason_comes_before_the_take_id(self):
        line = self._line()
        self.assertLess(line.index("reason="), line.index("take="))

    def test_the_named_gate_comes_before_both_the_reason_and_the_take_id(self):
        # The gate is the answer. It cannot sit behind 36 characters of
        # identifier — nor behind 36 characters of a reason that six gates
        # share — and still be the thing you read first.
        line = self._line(detail="no_candidate_id; at_candidate:1; "
                                 "confidence_block_rejected:1")
        self.assertLess(line.index("detail="), line.index("reason="))
        self.assertLess(line.index("reason="), line.index("take="))

    def test_the_gate_starts_inside_a_phone_width_preview(self):
        # The concrete failure this file exists for. A log list shows roughly
        # the first sixty characters of a message; the gate has to START well
        # inside that, not merely appear somewhere in the line. Reordering
        # once was not enough — leading with `reason=` still clipped it
        # mid-token — and this assertion is what caught that.
        line = self._line(detail="confidence_block_rejected:1")
        message = line.split(":", 2)[-1].strip()
        self.assertLess(message.index("detail="), 40)

    def test_the_take_id_is_still_there(self):
        # Trailing is not dropping. Correlating a line to a take is exactly
        # what it is for, once you have expanded it.
        self.assertIn("take=440b7c97-a031-4388-8f3c-cdb800b7d10c",
                      self._line())

    def test_a_raw_database_error_is_still_written_here(self):
        # Log-only is not the same as dropped: `source_snapshot_rpc_failed`
        # is diagnosable from this string and nothing else.
        line = self._line("source_snapshot_rpc_failed",
                          "0A000 SELECT FOR SHARE is not allowed")
        self.assertIn("detail=0A000 SELECT FOR SHARE is not allowed", line)

    def test_a_decline_with_no_detail_stays_one_clean_line(self):
        line = self._line("candidate_set_write_failed")
        self.assertNotIn("detail=", line)


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

    def test_the_named_gate_is_not_carried_either(self):
        # Not because it would be harmful — it is a controlled condition
        # name — but because the field that would carry it is the same field
        # a raw error would use.
        failure = _decline("take-1", "service_inventory_unavailable",
                           "confidence_block_rejected:1")
        self.assertEqual(len(failure), 1)
        self.assertNotIn("confidence_block_rejected", "".join(failure))
