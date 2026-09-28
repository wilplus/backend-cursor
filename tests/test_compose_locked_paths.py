"""Every alignment path of ``compose_locked``, pinned exactly before its
split into named stages (audit W1, 2026-09-28).

``tests/test_ideal_text_parts.py`` holds the product cases. These pin the
whole output of each path — ids, order, text, the lock, the helper words
riding on it, and ``changed`` — with minted ids made deterministic, so a
refactor that mints in a different order, or drops a field, fails here.
"""
from __future__ import annotations

import itertools
import unittest
from unittest import mock

from services import ideal_text_parts as itp

LOCKED_AT = "2026-09-28T00:00:00Z"


def _rows(*specs, **extra):
    rows = []
    for i, (pid, text, locked) in enumerate(specs):
        row = {"id": pid, "ord": i, "text": text,
               "locked_at": LOCKED_AT if locked else None}
        row.update(extra.get(pid, {}))
        rows.append(row)
    return rows


def _compose(base, rows):
    minted = itertools.count(1)
    with mock.patch.object(itp.uuid, "uuid4",
                           side_effect=lambda: f"new-{next(minted)}"):
        return itp.compose_locked(base, rows)


def _kept(pid, ord_, text, locked=False, **extra):
    return {"id": pid, "ord": ord_, "text": text, "locked": locked,
            "iteration": 0, **extra}


def _minted(n, ord_, text):
    return {"id": f"new-{n}", "text": text, "locked": False, "ord": ord_}


class ComposeLockedPathPins(unittest.TestCase):
    def test_every_lock_anchored_refreshes_each_open_region(self):
        rows = _rows(
            ("a", "Old one.", False), ("L1", "LOCK A.", True),
            ("b", "Keep me.", False), ("L2", "LOCK B.", True),
            ("c", "Old tail.", False),
            L1={"root_phrase": "LOCK", "root_start": 0, "root_end": 4,
                "iteration": 2},
        )
        out = _compose(
            "New one.\n\nLOCK A.\n\nKeep me.\n\nAdded.\n\nLOCK B.", rows)
        self.assertEqual(out, {
            "text": "New one.\n\nLOCK A.\n\nKeep me.\n\nAdded.\n\nLOCK B.",
            "parts": [
                _minted(1, 0, "New one."),
                # The lock keeps its helper words and its maturity.
                {"id": "L1", "ord": 1, "text": "LOCK A.", "locked": True,
                 "iteration": 2, "root_phrase": "LOCK", "root_start": 0,
                 "root_end": 4},
                _kept("b", 2, "Keep me."),
                _minted(2, 3, "Added."),
                _kept("L2", 4, "LOCK B.", locked=True),
            ],
            "changed": True,
        })

    def test_no_lock_anchored_and_equal_counts_is_positional(self):
        rows = _rows(("a", "Same.", False), ("L", "MINE.", True),
                     ("c", "Old.", False))
        out = _compose("Same.\n\nMachine two.\n\nNew three.", rows)
        self.assertEqual(out, {
            "text": "Same.\n\nMINE.\n\nNew three.",
            "parts": [_kept("a", 0, "Same."),
                      _kept("L", 1, "MINE.", locked=True),
                      _minted(1, 2, "New three.")],
            "changed": True,
        })

    def test_diverged_counts_pin_a_replace_region_holding_a_lock(self):
        rows = _rows(("a", "A.", False), ("b", "B.", False),
                     ("L", "MINE.", True), ("d", "D.", False))
        out = _compose("A.\n\nX.\n\nY.\n\nD.\n\nE.", rows)
        self.assertEqual(out, {
            "text": "A.\n\nB.\n\nMINE.\n\nD.\n\nE.",
            "parts": [_kept("a", 0, "A."), _kept("b", 1, "B."),
                      _kept("L", 2, "MINE.", locked=True),
                      _kept("d", 3, "D."), _minted(1, 4, "E.")],
            "changed": True,
        })

    def test_diverged_counts_refresh_an_open_replace_and_keep_a_deleted_lock(
            self):
        rows = _rows(("a", "A.", False), ("b", "B.", False),
                     ("c", "C.", False), ("L", "MINE.", True),
                     ("e", "E.", False))
        out = _compose("A.\n\nX.\n\nC.\n\nE.", rows)
        self.assertEqual(out, {
            "text": "A.\n\nX.\n\nC.\n\nMINE.\n\nE.",
            "parts": [_kept("a", 0, "A."), _minted(1, 1, "X."),
                      _kept("c", 2, "C."),
                      _kept("L", 3, "MINE.", locked=True),
                      _kept("e", 4, "E.")],
            "changed": True,
        })

    def test_diverged_counts_drop_deleted_open_parts(self):
        rows = _rows(("a", "A.", False), ("b", "B.", False),
                     ("c", "C.", False), ("L", "MINE.", True),
                     ("x", "X.", False), ("y", "Y.", False))
        out = _compose("A.\n\nC.", rows)
        self.assertEqual(out, {
            "text": "A.\n\nC.\n\nMINE.",
            "parts": [_kept("a", 0, "A."), _kept("c", 1, "C."),
                      _kept("L", 2, "MINE.", locked=True)],
            "changed": True,
        })

    def test_some_locks_anchored_some_gone_serves_the_stored_state(self):
        rows = _rows(("L1", "LOCK A.", True), ("L2", "LOCK B.", True))
        out = _compose("LOCK A.\n\nOther.", rows)
        self.assertEqual(out, {
            "text": "LOCK A.\n\nLOCK B.",
            "parts": [_kept("L1", 0, "LOCK A.", locked=True),
                      _kept("L2", 1, "LOCK B.", locked=True)],
            "changed": False,
        })

    def test_an_unchanged_document_is_not_changed(self):
        rows = _rows(("a", "One.", False), ("L", "MINE.", True))
        out = _compose("One.\n\nMINE.", rows)
        self.assertEqual(out, {
            "text": "One.\n\nMINE.",
            "parts": [_kept("a", 0, "One."),
                      _kept("L", 1, "MINE.", locked=True)],
            "changed": False,
        })

    def test_no_usable_machine_text_serves_the_stored_state(self):
        rows = _rows(("a", "One.", False), ("L", "MINE.", True))
        pinned = {
            "text": "One.\n\nMINE.",
            "parts": [_kept("a", 0, "One."),
                      _kept("L", 1, "MINE.", locked=True)],
            "changed": False,
        }
        for base in (None, "", "   \n\n  ", 7, "One **bold.\n\nMINE."):
            self.assertEqual(_compose(base, rows), pinned, base)

    def test_nothing_to_compose_is_none(self):
        self.assertIsNone(_compose("x", _rows(("a", "One.", False))))
        self.assertIsNone(_compose("x", []))
        self.assertIsNone(_compose("x", None))


if __name__ == "__main__":
    unittest.main()
