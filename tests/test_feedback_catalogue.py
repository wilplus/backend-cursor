"""The catalogue of signed lines (founder 2026-09-30, E3 and C4; P1-4).

What this pins down:

  * a praise row gets the line for its device first, then its first cue
    with a line, then the confident read; a rewrite row gets the move for
    its why_key; a row with nothing matching is served untouched, so the
    honest fallback stays honest (24f);
  * the newest ACTIVE version of a line wins, whatever order rows arrive;
  * an author's line is words: no percentage may reach a speaker (AC-9),
    and `signed_by` comes from the caller, never the body (L3);
  * the coach routes: the list includes every version, a refusal carries
    the service's own sentence, a failed read is a 500 and never an empty
    catalogue.

Run: python3 -m unittest tests.test_feedback_catalogue
"""
from __future__ import annotations

import unittest

from services import feedback_catalogue as fc

try:
    from flask import Flask, request
    from routes.v2 import coach as v2_coach
    from services.db import db
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    Flask = None
    request = None
    _IMPORT_ERROR = e


def _line(lane, kind, key, text, version=1, active=True):
    return {"lane": lane, "pattern_kind": kind, "pattern_key": key,
            "text": text, "version": version, "active": active}


CATALOGUE = [
    _line("praise", "read", "confident_read", "You held this one."),
    _line("praise", "cue", "steady_pace", "You kept a steady pace here."),
    _line("praise", "device", "contrast", "That contrast landed."),
    _line("rewrite", "move", "clarity", "Split the clause."),
    _line("rewrite", "move", "clarity", "Split the clause, then breathe.",
          version=2),
    _line("rewrite", "move", "clarity", "Retired wording.", version=3,
          active=False),
]


class NewestLinesTests(unittest.TestCase):
    def test_the_newest_active_version_wins_in_any_order(self):
        lines = fc.newest_lines(list(reversed(CATALOGUE)))
        self.assertEqual(lines[("rewrite", "move", "clarity")],
                         "Split the clause, then breathe.")

    def test_rows_that_are_not_lines_are_skipped(self):
        lines = fc.newest_lines([None, {"lane": "praise"}, {"text": " "},
                                 _line("praise", "read", "x", "ok")])
        self.assertEqual(lines, {("praise", "read", "x"): "ok"})


class PickingTests(unittest.TestCase):
    def setUp(self):
        self.lines = fc.newest_lines(CATALOGUE)

    def test_device_first_then_cue_then_read(self):
        self.assertEqual(
            fc.praise_line_for({"device": "contrast",
                                "cue_keys": ["steady_pace"]}, self.lines),
            "That contrast landed.")
        self.assertEqual(
            fc.praise_line_for({"device": "tentative_formulation",
                                "cue_keys": ["nope", "steady_pace"]},
                               self.lines),
            "You kept a steady pace here.")
        self.assertEqual(fc.praise_line_for({"cue_keys": []}, self.lines),
                         "You held this one.")

    def test_a_rewrite_move_by_why_key(self):
        self.assertEqual(fc.rewrite_move_for({"why_key": "clarity"}, self.lines),
                         "Split the clause, then breathe.")
        self.assertIsNone(fc.rewrite_move_for({"why_key": "profanity"},
                                              self.lines))
        self.assertIsNone(fc.rewrite_move_for({}, self.lines))

    def test_decorate_touches_only_praise_and_rewrite_rows(self):
        rows = [
            {"feedback_family": "great_formulation", "device": "contrast"},
            {"feedback_family": "rewrite_clarity", "why_key": "clarity"},
            {"feedback_family": "rewrite_clarity", "why_key": "other"},
            {"feedback_family": "confident_voice"},
            "not a row",
        ]
        out = fc.decorate(rows, CATALOGUE)
        self.assertEqual(out[0]["praise_line"], "That contrast landed.")
        self.assertEqual(out[1]["rewrite_move"],
                         "Split the clause, then breathe.")
        self.assertNotIn("rewrite_move", out[2])
        self.assertNotIn("praise_line", out[3])
        self.assertEqual(out[4], "not a row")
        # The input rows are not mutated.
        self.assertNotIn("praise_line", rows[0])

    def test_no_catalogue_serves_the_rows_untouched(self):
        rows = [{"feedback_family": "great_formulation", "device": "contrast"}]
        self.assertEqual(fc.decorate(rows, []), rows)


class ValidateTests(unittest.TestCase):
    def test_a_good_line(self):
        row = fc.validate_line({"lane": "praise", "pattern_kind": "cue",
                                "pattern_key": "steady_pace",
                                "text": "  You kept a steady pace.  ",
                                "signed_by": "ignored"})
        self.assertEqual(row, {"lane": "praise", "pattern_kind": "cue",
                               "pattern_key": "steady_pace",
                               "text": "You kept a steady pace."})

    def test_refusals(self):
        bad = [
            "not an object",
            {"lane": "score", "pattern_kind": "cue", "pattern_key": "k", "text": "t"},
            {"lane": "praise", "pattern_kind": "move", "pattern_key": "k", "text": "t"},
            {"lane": "rewrite", "pattern_kind": "cue", "pattern_key": "k", "text": "t"},
            {"lane": "praise", "pattern_kind": "cue", "pattern_key": "two words", "text": "t"},
            {"lane": "praise", "pattern_kind": "cue", "pattern_key": "k", "text": ""},
            {"lane": "praise", "pattern_kind": "cue", "pattern_key": "k", "text": "x" * 401},
            {"lane": "praise", "pattern_kind": "cue", "pattern_key": "k", "text": "You were 80% there"},
        ]
        for body in bad:
            with self.assertRaises(fc.CatalogueRefusal, msg=repr(body)):
                fc.validate_line(body)


class _FakeCatalogue:
    def __init__(self, rows=None, boom=False, save_fails=False):
        self.rows = rows if rows is not None else []
        self.boom = boom
        self.save_fails = save_fails
        self.saved = []
        self.listed_active_only = []

    def list_feedback_catalogue(self, active_only=True):
        if self.boom:
            raise RuntimeError("catalogue unavailable")
        self.listed_active_only.append(active_only)
        return list(self.rows)

    def insert_feedback_catalogue_line(self, **row):
        if self.save_fails:
            return None
        self.saved.append(row)
        return {**row, "version": 1}


@unittest.skipIf(_IMPORT_ERROR is not None,
                 f"catalogue route tests need app deps: {_IMPORT_ERROR}")
class CatalogueRouteTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.originals = {}

    def tearDown(self):
        for attr, orig in self.originals.items():
            if orig is None:
                delattr(db, attr)
            else:
                setattr(db, attr, orig)

    def _install(self, fake):
        for attr in ("list_feedback_catalogue", "insert_feedback_catalogue_line"):
            self.originals[attr] = getattr(db, attr, None)
            setattr(db, attr, getattr(fake, attr))

    def _get(self):
        with self.app.test_request_context():
            request.user_id = "coach-1"
            resp, status = v2_coach.v2_coach_list_catalogue.__wrapped__()
            return status, resp.get_json()

    def _post(self, body):
        with self.app.test_request_context(json=body):
            request.user_id = "coach-1"
            resp, status = v2_coach.v2_coach_add_catalogue_line.__wrapped__()
            return status, resp.get_json()

    def test_the_list_includes_every_version(self):
        fake = _FakeCatalogue(rows=CATALOGUE)
        self._install(fake)
        status, body = self._get()
        self.assertEqual(status, 200)
        self.assertEqual(len(body["lines"]), len(CATALOGUE))
        self.assertEqual(fake.listed_active_only, [False])

    def test_a_failed_read_is_a_500(self):
        self._install(_FakeCatalogue(boom=True))
        status, body = self._get()
        self.assertEqual((status, body["code"]), (500, "V2_ERROR"))

    def test_the_author_is_the_caller(self):
        fake = _FakeCatalogue()
        self._install(fake)
        status, body = self._post({"lane": "praise", "pattern_kind": "read",
                                   "pattern_key": "confident_read",
                                   "text": "You held this one.",
                                   "signed_by": "someone-else"})
        self.assertEqual(status, 200)
        self.assertEqual(fake.saved[0]["signed_by"], "coach-1")
        self.assertEqual(body["line"]["text"], "You held this one.")

    def test_a_refusal_carries_the_sentence(self):
        self._install(_FakeCatalogue())
        status, body = self._post({"lane": "praise", "pattern_kind": "read",
                                   "pattern_key": "confident_read",
                                   "text": "You were 80% there"})
        self.assertEqual(status, 400)
        self.assertIn("percentage", body["error"])

    def test_a_failed_save_is_a_500(self):
        self._install(_FakeCatalogue(save_fails=True))
        status, _ = self._post({"lane": "rewrite", "pattern_kind": "move",
                                "pattern_key": "clarity", "text": "Split it."})
        self.assertEqual(status, 500)


if __name__ == "__main__":
    unittest.main()
