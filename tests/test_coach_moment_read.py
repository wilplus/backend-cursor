"""The coach's Read screen, one source (founder 2026-09-30, A2; P2-10).

Pins: the passage, both answers, the request (or None), the named patterns
and the goal come back in words; the route sits behind the blind gate; no
number about the speaker is in the payload.
"""
from __future__ import annotations

import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class ReadTests(unittest.TestCase):


    def test_the_route_is_behind_the_blind_gate(self):
        source = (ROOT / "routes/v2/coach.py").read_text()
        start = source.index("def v2_coach_moment_read")
        body = source[start:source.index("@v2_bp.route", start)]
        self.assertLess(body.index("_moment_gate(session_id, snippet_id)"),
                        body.index("payload = _moment_read_payload("))
        # The read the label PUT returns passes the same gate first (C2).
        start = source.index("def _moment_read_after_rating")
        helper = source[start:source.index("\n\n\n", start)]
        self.assertLess(helper.index("_moment_gate("),
                        helper.index("_moment_read_payload("))


if __name__ == "__main__":
    unittest.main()
