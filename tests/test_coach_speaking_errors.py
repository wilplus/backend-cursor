"""The coach's door into the speaking error library — /v2/coach/speaking-errors.

Founder 2026-09-16, after "coach library UI first". The same table already had
a write path (routes/journal.py), but it is gated on the shared
JOURNAL_ADMIN_PASSWORD, which a coach does not have — they sign in with a
coach account. A write surface the intended author cannot reach is not a write
surface, so this pair is the coach's side of the same seam.

WHAT THIS PINS DOWN:
  * both refusals survive the second door. Naming is not detecting: nothing
    written here may claim `detected`, and an entry that IS already detected
    cannot be saved from here at all (the upsert would demote it to `observed`
    and silently stop it routing exercises — no exception, no log);
  * L3 — `observed_by` is taken from the AUTHENTICATED caller and the body's
    own value is ignored. A self-declared author is not provenance, and the
    body is the one part of the request the caller fully controls;
  * L3 — a row is a NAME and a DEFINITION, never evidence that the pattern
    occurred in a recording, so neither route accepts a snippet, session or
    take;
  * the list is the WHOLE library including retired entries, so an author can
    see what exists before naming the same thing twice.

Run: python3 -m unittest tests.test_coach_speaking_errors
"""
from __future__ import annotations

import inspect
import unittest

try:
    from flask import Flask, request
    from routes.v2 import coach as v2_coach
    from services.db import db
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    Flask = None
    request = None
    _IMPORT_ERROR = e


COACH = "coach-1"

GOOD = {
    "error_id": "trailing_mumble",
    "label": "Trailing mumble",
    "definition": "The last words of a sentence lose volume and articulation "
                  "while the pace stays even.",
    "asks": "Did the speaker carry the end of the sentence?",
}

DETECTED_ROW = {
    "error_id": "rushing",
    "label": "Rushing",
    "definition": "…",
    "asks": "Did this passage give the listener room to follow it?",
    "status": "detected",
    "detector_ref": "insufficient_pauses,irregular_rushed_pacing",
}


class _FakeLibrary:
    """Only the three methods the service and the routes actually call."""

    def __init__(self, existing: dict | None = None,
                 rows: list | None = None, boom: bool = False):
        self.existing = existing
        self.rows = rows if rows is not None else []
        self.boom = boom
        self.saved: list[dict] = []
        self.listed_active_only: list[bool] = []

    def list_speaking_errors(self, active_only: bool = True):
        if self.boom:
            raise RuntimeError("library unavailable")
        self.listed_active_only.append(active_only)
        return list(self.rows)

    def get_speaking_error(self, error_id: str):
        if self.existing and self.existing.get("error_id") == error_id:
            return self.existing
        return None

    def upsert_speaking_error(self, row: dict):
        self.saved.append(row)
        return dict(row)


@unittest.skipIf(_IMPORT_ERROR is not None,
                 f"coach library tests need app deps: {_IMPORT_ERROR}")
class CoachSpeakingErrorRouteTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.originals: dict = {}

    def tearDown(self):
        for attr, orig in self.originals.items():
            if orig is None:
                delattr(db, attr)
            else:
                setattr(db, attr, orig)

    def _install(self, fake: _FakeLibrary):
        for attr in ("list_speaking_errors", "get_speaking_error",
                     "upsert_speaking_error"):
            self.originals[attr] = getattr(db, attr, None)
            setattr(db, attr, getattr(fake, attr))

    def _get(self):
        with self.app.test_request_context():
            request.user_id = COACH
            resp, status = v2_coach.v2_coach_list_speaking_errors.__wrapped__()
            return status, resp.get_json()

    def _post(self, body):
        with self.app.test_request_context(json=body):
            request.user_id = COACH
            resp, status = v2_coach.v2_coach_save_speaking_error.__wrapped__()
            return status, resp.get_json()

    # ── reading ──────────────────────────────────────────────────────────

    def test_the_list_includes_retired_entries(self):
        # An author who cannot see a retired entry names it a second time and
        # the upsert silently overwrites the first one.
        fake = _FakeLibrary(rows=[DETECTED_ROW, {"error_id": "x",
                                                 "active": False}])
        self._install(fake)
        status, body = self._get()
        self.assertEqual(status, 200)
        self.assertEqual(len(body["errors"]), 2)
        self.assertEqual(fake.listed_active_only, [False])

    def test_a_failed_read_is_a_500_not_an_empty_library(self):
        # Empty means "no library" to every caller of detected_problem_vocabulary,
        # so an error must not be able to masquerade as one here either.
        self._install(_FakeLibrary(boom=True))
        status, body = self._get()
        self.assertEqual(status, 500)
        self.assertEqual(body["code"], "V2_ERROR")

    # ── naming ───────────────────────────────────────────────────────────

    def test_a_coach_can_name_and_define_a_new_pattern(self):
        fake = _FakeLibrary()
        self._install(fake)
        status, body = self._post(dict(GOOD))
        self.assertEqual(status, 200)
        self.assertEqual(body["error"]["error_id"], "trailing_mumble")
        self.assertEqual(fake.saved[0]["status"], "observed")

    def test_observed_by_is_the_authenticated_coach_not_the_body(self):
        # THE provenance point (L3). The body is the one part of this request
        # the caller fully controls, so an author it names is a claim, not a
        # record of who actually wrote the row.
        fake = _FakeLibrary()
        self._install(fake)
        status, _ = self._post({**GOOD, "observed_by": "somebody-else"})
        self.assertEqual(status, 200)
        self.assertEqual(fake.saved[0]["observed_by"], COACH)

    def test_naming_can_never_claim_detection(self):
        self._install(_FakeLibrary())
        status, body = self._post({**GOOD, "status": "detected"})
        self.assertEqual(status, 400)
        self.assertIn("detector in code", body["error"])

    def test_an_already_detected_entry_cannot_be_demoted_from_here(self):
        # The silent failure the whole library exists to prevent: the write is
        # an upsert, so re-saving `rushing` would carry status=observed over it
        # and matching would quietly stop routing that error.
        fake = _FakeLibrary(existing=DETECTED_ROW)
        self._install(fake)
        status, body = self._post({**GOOD, "error_id": "rushing"})
        self.assertEqual(status, 409)
        self.assertEqual(body["code"], "ALREADY_DETECTED")
        self.assertEqual(fake.saved, [])

    def test_an_id_that_would_match_nothing_is_refused(self):
        # Matching is string overlap, so a space or a capital would match no
        # exercise, raise nothing, and route nothing.
        self._install(_FakeLibrary())
        for bad in ("Word Compression", "word compression", "", "9lives"):
            status, _ = self._post({**GOOD, "error_id": bad})
            self.assertEqual(status, 400, bad)

    def test_a_name_without_a_definition_is_refused(self):
        # The construct fence, made structural: a measured state with no
        # written operational definition is the defect that retired charisma.
        self._install(_FakeLibrary())
        for missing in ("label", "definition", "asks"):
            status, _ = self._post({**GOOD, missing: "  "})
            self.assertEqual(status, 400, missing)

    def test_a_non_object_body_is_a_400_not_a_crash(self):
        self._install(_FakeLibrary())
        with self.app.test_request_context(json=["not", "an", "object"]):
            request.user_id = COACH
            resp, status = v2_coach.v2_coach_save_speaking_error.__wrapped__()
        self.assertEqual(status, 400)
        self.assertEqual(resp.get_json()["code"], "INVALID_INPUT")

    # ── provenance fence (source level) ──────────────────────────────────

    def test_neither_route_accepts_a_recording(self):
        # A row is a NAME, never evidence the pattern occurred in a take. If
        # either route ever grows a snippet/session/take parameter, this pair
        # has started recording judgements about specific clips (L3).
        for fn in (v2_coach.v2_coach_list_speaking_errors,
                   v2_coach.v2_coach_save_speaking_error):
            source = inspect.getsource(fn.__wrapped__)
            for forbidden in ("snippet", "session_id", "take_session",
                              "arc_id"):
                self.assertNotIn(forbidden, source,
                                 f"{fn.__name__} mentions {forbidden}")
            self.assertEqual(
                inspect.signature(fn.__wrapped__).parameters, {},
                f"{fn.__name__} takes a path parameter")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
