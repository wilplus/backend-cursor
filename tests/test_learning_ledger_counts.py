"""The ledger's counts, proven on rows (build plan ML-2: "one function
returns the whole ledger as data; a test with a fixture DB proves every
count; nothing in it identifies a speaker").

Pins:
  * the pair count covers EVERY pair surface, the two coach-word surfaces
    included (it used to hardcode three, so coach-word pairs never showed);
  * exposures (model drafts shown to a coach) are counted per surface from
    the rows the drafting routes write, and reach the ledger beside the
    pairs;
  * a count that cannot be read is named in `unavailable` and reads as
    unknown (None / absent), never as zero;
  * the ledger says what last happened (the newest release, run and
    promotion) without an owner, a coach or a file key.
"""
from __future__ import annotations

import json
import unittest
from unittest import mock

from services import feedback_pairs as fp
from services import learning_ledger as ll
from services.db import DatabaseService


class _Result:
    def __init__(self, rows, count):
        self.data = rows
        self.count = count


class _Query:
    """Just enough of PostgREST to filter rows: eq, is_ null, not_.is_ null,
    order, limit, a counted select."""

    def __init__(self, rows):
        self._rows = list(rows)
        self._filters = []
        self._negate = False
        self._limit = None

    def select(self, *_columns, **_kw):
        return self

    @property
    def not_(self):
        self._negate = True
        return self

    def _add(self, test):
        negate, self._negate = self._negate, False
        self._filters.append((lambda r: not test(r)) if negate else test)
        return self

    def eq(self, column, value):
        return self._add(lambda r: r.get(column) == value)

    def is_(self, column, value):
        assert value == "null"
        return self._add(lambda r: r.get(column) is None)

    def order(self, *_a, **_k):
        return self

    def limit(self, n):
        self._limit = int(n)
        return self

    def execute(self):
        rows = [r for r in self._rows if all(f(r) for f in self._filters)]
        count = len(rows)
        return _Result(rows[: self._limit] if self._limit else rows, count)


class _Client:
    def __init__(self, tables):
        self.tables = tables

    def table(self, name):
        return _Query(self.tables.get(name, []))


def _db(tables) -> DatabaseService:
    db = DatabaseService.__new__(DatabaseService)
    db.client = _Client(tables)
    return db


def _pair(surface, *, exported=False, releasable=False):
    return {"id": f"{surface}-{exported}-{releasable}", "surface": surface,
            "exported_at": "2026-10-05T06:00:00Z" if exported else None,
            "releasable": releasable}


PAIRS = [
    _pair("praise_line"), _pair("praise_line", releasable=True),
    _pair("praise_line", exported=True, releasable=True),
    _pair("clearer_version", releasable=True),
    _pair("exercise_script"),
    _pair("coach_moment_line", releasable=True), _pair("coach_moment_line"),
    _pair("coach_take_word"),
]

REQUESTS = [
    {"id": "r1", "draft_surface": "exercise_script", "draft_text": "breathe, then say it"},
    {"id": "r2", "draft_surface": "exercise_script", "draft_text": "slow the first line"},
    {"id": "r3", "draft_surface": "praise_line", "draft_text": "you held the pause"},
    {"id": "r4", "draft_surface": "praise_line", "draft_text": None},     # never drafted
    {"id": "r5", "draft_surface": None, "draft_text": None},              # an ambiguity
    {"id": "r6", "draft_surface": "coach_moment_line", "draft_text": "one line for you"},
]
WORDS = [
    {"id": "w1", "draft_text": "a word for this take"},
    {"id": "w2", "draft_text": None},
]


class DatabaseCountTests(unittest.TestCase):
    def test_the_pair_count_covers_every_surface(self):
        out = _db({"feedback_pairs": PAIRS}).count_feedback_pairs()
        self.assertEqual(set(out), set(fp.SURFACES))
        self.assertEqual(out["praise_line"], {"total": 3, "unexported": 2, "releasable": 2})
        self.assertEqual(out["clearer_version"], {"total": 1, "unexported": 1, "releasable": 1})
        self.assertEqual(out["exercise_script"], {"total": 1, "unexported": 1, "releasable": 0})
        # The two coach-word surfaces were invisible while the list said three.
        self.assertEqual(out["coach_moment_line"], {"total": 2, "unexported": 2, "releasable": 1})
        self.assertEqual(out["coach_take_word"], {"total": 1, "unexported": 1, "releasable": 0})

    def test_exposures_are_the_drafts_shown_per_surface(self):
        out = _db({"exercise_coach_requests": REQUESTS,
                   "coach_take_words": WORDS}).count_draft_exposures()
        self.assertEqual(out, {"exercise_script": 2, "praise_line": 1,
                               "clearer_version": 0, "coach_moment_line": 1,
                               "coach_take_word": 1})


class CountServiceTests(unittest.TestCase):
    def test_a_count_that_cannot_be_read_raises_instead_of_reading_zero(self):
        class _Down:
            def count_feedback_pairs(self):
                raise RuntimeError("down")

            def count_draft_exposures(self):
                raise RuntimeError("down")
        with self.assertRaises(RuntimeError):
            fp.counts(_Down())
        with self.assertRaises(RuntimeError):
            fp.exposures(_Down())

    def test_every_surface_is_named_at_zero(self):
        self.assertEqual(fp.exposures(_db({})), {s: 0 for s in fp.SURFACES})


class _LedgerDb(DatabaseService):
    """The real count methods over fixture rows, plus the three ledger
    tables of what last happened."""

    def __init__(self, tables, *, releases=(), runs=(), promotions=(), down=()):
        self.client = _Client(tables)
        self._releases, self._runs, self._promotions = releases, runs, promotions
        self._down = set(down)

    def count_draft_exposures(self):
        if "exposures" in self._down:
            raise RuntimeError("exposures down")
        return super().count_draft_exposures()

    def list_pair_releases(self, limit=20):
        return list(self._releases)[:limit]

    def list_fine_tune_runs(self, *, status=None, limit=20):
        if "runs" in self._down:
            raise RuntimeError("runs down")
        return list(self._runs)[:limit]

    def list_model_promotions(self, *, limit=20):
        return list(self._promotions)[:limit]


class _Config:
    MLC2_TRAINING_SWITCH_ENABLED = True
    MLC2_PAIR_RELEASES_ENABLED = True
    PAIR_RELEASE_SURFACES = frozenset({"exercise_script", "praise_line", "clearer_version"})
    MLC2_TRAINING_ENABLED = False
    MLC2_PROMOTION_ENABLED = False


class LedgerTests(unittest.TestCase):
    def setUp(self):
        for target, value in (
            ("services.exercise_learning_readiness.readiness", {"counted": 0, "bar": 300}),
            ("services.verbal_cue_validation.report", {}),
            ("services.coach_load.coach_load", {}),
            ("services.bold_voices.after_practice_counts", {}),
            ("services.learning_ledger._peer_lane_counts", {"enabled": False}),
            ("services.delayed_measure.report", {"enabled": False}),
            ("services.learning_ledger._coach_panel_rows", {}),
        ):
            patcher = mock.patch(target, return_value=value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _ledger(self, **kw):
        db = _LedgerDb({"feedback_pairs": PAIRS, "exercise_coach_requests": REQUESTS,
                        "coach_take_words": WORDS}, **kw)
        return ll.ledger(db, config=_Config())

    def test_every_count_reaches_the_ledger_with_its_exposures(self):
        out = self._ledger()
        self.assertEqual(out["unavailable"], [])
        self.assertEqual(set(out["pairs"]), set(fp.SURFACES))
        self.assertEqual(out["pairs"]["praise_line"]["total"], 3)
        self.assertEqual(out["pairs"]["praise_line"]["exposures"], 1)
        self.assertEqual(out["pairs"]["exercise_script"]["exposures"], 2)
        self.assertEqual(out["pairs"]["coach_take_word"]["exposures"], 1)
        self.assertEqual(out["pairs"]["coach_moment_line"]["releasable"], 1)
        self.assertEqual(out["last"], {"pair_release": None, "fine_tune": None, "promotion": None})

    def test_an_unreadable_exposure_count_is_named_and_unknown(self):
        out = self._ledger(down={"exposures"})
        self.assertEqual(out["unavailable"], ["exposures"])
        self.assertTrue(all(entry["exposures"] is None for entry in out["pairs"].values()))
        # The pair counts themselves still stand.
        self.assertEqual(out["pairs"]["praise_line"]["total"], 3)

    def test_an_unreadable_pair_count_is_named_not_zeroed(self):
        class _Down(_LedgerDb):
            def count_feedback_pairs(self):
                raise RuntimeError("pairs down")
        db = _Down({"exercise_coach_requests": REQUESTS, "coach_take_words": WORDS})
        out = ll.ledger(db, config=_Config())
        self.assertIn("pairs", out["unavailable"])
        self.assertEqual(out["pairs"], {})

    def test_what_last_happened_names_no_person_and_no_file(self):
        out = self._ledger(
            releases=[{"id": "rel-2", "surface": "praise_line", "week_start": "2026-10-05",
                       "item_count": 12, "exported_at": "2026-10-05T06:00:01Z",
                       "voided_at": None, "purged_at": None,
                       "storage_key": "pair-releases/praise_line/2026-10-05/pairs.jsonl",
                       "storage_bucket": "willab-pair-releases"}],
            runs=[{"id": "run-1", "surface": "praise_line", "status": "running",
                   "item_count": 200, "started_at": "2026-10-05T06:00:02Z",
                   "openai_file_id": "file-abc", "openai_job_id": "job-abc"}],
            promotions=[{"surface": "praise_line", "candidate_model": "ft:x",
                         "promoted_by": "artur@willonski.com", "promoted_at": "t", "killed_at": None}])
        last = out["last"]
        self.assertEqual(last["pair_release"]["item_count"], 12)
        self.assertEqual(last["fine_tune"]["status"], "running")
        self.assertEqual(last["promotion"]["candidate_model"], "ft:x")
        text = json.dumps(last)
        for leak in ("pair-releases/", "willab-pair-releases", "file-abc", "job-abc",
                     "willonski", "owner", "coach"):
            self.assertNotIn(leak, text)

    def test_a_last_event_that_cannot_be_read_is_named(self):
        out = self._ledger(down={"runs"})
        self.assertEqual(out["unavailable"], ["last_fine_tune"])
        self.assertIsNone(out["last"]["fine_tune"])


if __name__ == "__main__":
    unittest.main()
