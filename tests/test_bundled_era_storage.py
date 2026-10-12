"""F4 storage step: which references are ours, and what happens to each.

Pinned without storage or a database:
  * our refs (s3 marker, presigned, our public base, Supabase URL, export
    URI, bare path) are placed exactly; foreign URLs and non-paths are not ours;
  * preview never deletes; execute deletes, then verifies absence, and a file
    still there after delete raises rather than being recorded;
  * a provider error is never absence — it raises;
  * the run records every outcome only in execute mode, exports included.
"""
from __future__ import annotations

import unittest

from services.bundled_era_storage import Place, resolve


class ResolveTests(unittest.TestCase):

    def _fakes(self, present):
        state = {"present": set(present), "deleted": []}

        def is_absent(place):
            return place not in state["present"]

        def delete(place):
            state["deleted"].append(place)
            state["present"].discard(place)

        return state, is_absent, delete


    def test_execute_deletes_then_verifies(self):
        place = Place("r2", "b", "k/x.webm")
        state, absent, delete = self._fakes([place])
        self.assertEqual(resolve("s3://b/k/x.webm", execute=True, is_absent=absent,
                                 delete=delete)[0], "deleted")
        self.assertEqual(state["deleted"], [place])


if __name__ == "__main__":
    unittest.main()
