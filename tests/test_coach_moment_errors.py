"""The coach names the error on a moment, and attaching teaches the library.

FOUNDER 2026-09-25, on the coach's Confident Voice practice review:
  * "Naming a new error tags the clip, stored as coach provenance."
  * "Attach = both": giving the speaker an exercise for this moment also teaches
    the library that the exercise fixes this moment's error, with undo.

WHAT THIS PINS DOWN:
  * the coach's naming wins over the machine's reading when there is one, and
    a name no detector produces is never taught (it could match nobody);
  * teaching happens on ATTACH (share), after the save, never for a coach's
    own exercise (that one is filed with the moment's errors instead);
  * the coach's own exercise now names the moment's error, so it is no longer
    refused every time (the form never sent one);
  * naming is an append-only event, idempotent, and only for a library entry;
  * undo is scoped to this moment and is idempotent;
  * it is ONE route: naming and undoing are a PATCH on the practice review,
    dispatched after its own blind gate and under its one purpose guard, and
    nothing here reaches the speaker's payload (L3, BLIND COACH);
  * both new tables are deleted with the speaker's practice.

The SQL functions' own behaviour (the stranded-tag rule, never emptying an
exercise, deletion) was exercised against PostgreSQL 16 before this landed;
see the PR.

Run: python3 -m unittest tests.test_coach_moment_errors
"""
from __future__ import annotations

import inspect
import pathlib
import unittest

from services import coach_moment_errors as cme

try:
    from flask import Flask, request
    from routes.v2 import coach as v2_coach
    from services.db import db
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    Flask = None
    request = None
    _IMPORT_ERROR = e

ROOT = pathlib.Path(__file__).resolve().parents[1]
COACH = "00000000-0000-0000-0000-00000000000c"
PRACTICE_ID = "11111111-1111-1111-1111-111111111111"
SESSION = "22222222-2222-2222-2222-222222222222"
SNIPPET = "33333333-3333-3333-3333-333333333333"
TEACHING = "44444444-4444-4444-4444-444444444444"

DETECTED = ("rushing", "word_compression", "ending_compression")


class _Library:
    def __init__(self, detected=DETECTED, observed=("mumbled_opening",)):
        self.detected = detected
        self.observed = observed

    def list_speaking_errors(self, active_only: bool = True):
        rows = [{"error_id": e, "status": "detected", "label": e.title()}
                for e in self.detected]
        rows += [{"error_id": e, "status": "observed", "label": e.title()}
                 for e in self.observed]
        return rows


def _practice(**signals):
    return {
        "id": PRACTICE_ID,
        "snippet_id": SNIPPET,
        "exercise_id": "land-it",
        "machine_assessment": {"pattern": "near_confident"},
        "acoustic_evidence": {"signals": signals},
    }


# ── the pure rules ─────────────────────────────────────────────────────────

class CurrentNamedErrorsTests(unittest.TestCase):
    def test_the_latest_event_decides_and_first_naming_keeps_its_place(self):
        events = [
            {"error_id": "rushing", "action": "named"},
            {"error_id": "ending_compression", "action": "named"},
            {"error_id": "rushing", "action": "withdrawn"},
            {"error_id": "mumbled_opening", "action": "named"},
            {"error_id": "rushing", "action": "named"},
        ]
        self.assertEqual(cme.current_named_errors(events),
                         ["rushing", "ending_compression", "mumbled_opening"])

    def test_a_withdrawn_name_is_gone(self):
        events = [{"error_id": "rushing", "action": "named"},
                  {"error_id": "rushing", "action": "withdrawn"}]
        self.assertEqual(cme.current_named_errors(events), [])

    def test_junk_is_ignored(self):
        self.assertEqual(cme.current_named_errors(
            [None, {"error_id": "", "action": "named"},
             {"error_id": "x", "action": "promoted"}]), [])
        self.assertEqual(cme.current_named_errors(None), [])


class TeachableErrorsTests(unittest.TestCase):
    def test_with_no_naming_the_machine_s_reading_is_taught(self):
        errors, source = cme.teachable_errors(
            _practice(compressed_ending=True, insufficient_pauses=True),
            [], _Library())
        self.assertEqual(errors, ["ending_compression", "rushing"])
        self.assertEqual(source, cme.SOURCE_MACHINE_OBSERVED)

    def test_the_coach_s_naming_wins_over_the_machine(self):
        errors, source = cme.teachable_errors(
            _practice(compressed_ending=True), ["rushing"], _Library())
        self.assertEqual(errors, ["rushing"])
        self.assertEqual(source, cme.SOURCE_COACH_NAMED)

    def test_a_name_no_detector_produces_is_never_taught(self):
        errors, source = cme.teachable_errors(
            _practice(compressed_ending=True),
            ["mumbled_opening", "rushing"], _Library())
        self.assertEqual(errors, ["rushing"])
        self.assertEqual(source, cme.SOURCE_COACH_NAMED)

    def test_the_machine_is_not_substituted_when_the_coach_named_otherwise(self):
        # The coach said it was something the machine cannot hear. Teaching
        # the machine's reading instead would teach what the coach rejected.
        errors, source = cme.teachable_errors(
            _practice(compressed_ending=True), ["mumbled_opening"], _Library())
        self.assertEqual(errors, [])
        self.assertEqual(source, cme.SOURCE_COACH_NAMED)


class LiveLibraryTeachingsTests(unittest.TestCase):
    def test_only_standing_teachings_that_changed_the_library(self):
        rows = [
            {"id": "t1", "exercise_id": "e", "error_id": "rushing",
             "action": "taught", "changed_tags": True},
            {"id": "t2", "exercise_id": "e", "error_id": "word_compression",
             "action": "taught", "changed_tags": False},
            {"id": "t3", "exercise_id": "e", "error_id": "ending_compression",
             "action": "taught", "changed_tags": True},
            {"id": "u1", "exercise_id": "e", "error_id": "ending_compression",
             "action": "undone", "changed_tags": True, "undoes_id": "t3"},
        ]
        self.assertEqual(cme.live_library_teachings(rows), [
            {"teaching_id": "t1", "exercise_id": "e", "error_id": "rushing"}])


# ── the route ──────────────────────────────────────────────────────────────
# One route, on purpose: the exercise surface on the coach side is pinned to a
# single purpose-guarded route (test_phase1_compliance_contract), so naming
# and undoing are a PATCH on it, behind its own inline blind gate.

OWNER_TAKE = "55555555-5555-5555-5555-555555555555"


class _Db:
    """Only what the practice route and its services call."""

    def __init__(self, *, events=None, entry=None, undo=None, practice=None):
        self.events = list(events or [])
        self.entry = entry
        self.undo_result = undo
        self.practice = practice
        self.inserted: list[tuple] = []
        self.taught: list[tuple] = []
        self.undone: list[tuple] = []
        self.updated: list[dict] = []
        self.filed_fields: list[dict] = []
        self.calls: list[str] = []
        self.library = _Library()

    # the route's own guard
    def v2_get_session_by_id(self, session_id):
        return {"id": session_id}

    def get_confident_voice_practice_by_take(self, owner_sid):
        return self.practice

    # naming
    def list_coach_moment_error_events(self, practice_id):
        return list(self.events)

    def insert_coach_moment_error_event(self, practice_id, error_id,
                                        coach_id, action):
        self.inserted.append((practice_id, error_id, coach_id, action))
        self.events.append({"error_id": error_id, "action": action})
        return {"ok": True}

    def get_speaking_error(self, error_id):
        return self.entry

    def list_speaking_errors(self, active_only: bool = True):
        return self.library.list_speaking_errors(active_only)

    # teaching
    def teach_diagnostic_exercise(self, exercise_id, practice_id, coach_id,
                                  error_ids, source):
        self.calls.append("teach")
        self.taught.append((exercise_id, practice_id, coach_id,
                            list(error_ids), source))
        return []

    def undo_diagnostic_exercise_teaching(self, teaching_id, practice_id,
                                          coach_id):
        self.undone.append((teaching_id, practice_id, coach_id))
        return self.undo_result

    # the PUT
    def get_active_diagnostic_exercise(self, exercise_id):
        return {"exercise_id": exercise_id, "version": 1, "title": "T",
                "instruction": "I",
                "explanation_video_url": "https://cdn.example/v.mp4"}

    def update_confident_voice_practice(self, practice_id, _owner, patch):
        self.calls.append("update")
        self.updated.append(patch)
        return {**_practice(), **patch}

    def upsert_diagnostic_exercise(self, row):
        self.filed_fields.append(row)
        return row


@unittest.skipIf(_IMPORT_ERROR is not None, f"flask app unavailable: {_IMPORT_ERROR}")
class RouteTests(unittest.TestCase):
    _PATCHED = (
        "v2_get_session_by_id", "get_confident_voice_practice_by_take",
        "list_coach_moment_error_events", "insert_coach_moment_error_event",
        "get_speaking_error", "list_speaking_errors",
        "teach_diagnostic_exercise", "undo_diagnostic_exercise_teaching",
        "get_active_diagnostic_exercise", "update_confident_voice_practice",
        "upsert_diagnostic_exercise",
    )
    _MODULE = ("_snippet_owner_map", "_coach_state_map",
               "_coach_practice_payload")

    def setUp(self):
        self.app = Flask(__name__)
        self._orig_db = {a: getattr(db, a) for a in self._PATCHED}
        self._orig_mod = {a: getattr(v2_coach, a) for a in self._MODULE}
        self.rating = "yes"
        v2_coach._snippet_owner_map = lambda sid: {SNIPPET: OWNER_TAKE}
        v2_coach._coach_state_map = (
            lambda owner, rater_id=None: {SNIPPET: {"rating_value": self.rating}})
        v2_coach._coach_practice_payload = lambda p: {"id": str(p.get("id"))}

    def tearDown(self):
        for attr, orig in self._orig_db.items():
            setattr(db, attr, orig)
        for attr, orig in self._orig_mod.items():
            setattr(v2_coach, attr, orig)

    def _install(self, fake: _Db):
        if fake.practice is None:
            fake.practice = _practice(compressed_ending=True)
        for attr in self._PATCHED:
            setattr(db, attr, getattr(fake, attr))

    def _call(self, fake, method, body):
        self._install(fake)
        raw = inspect.unwrap(v2_coach.v2_coach_confident_voice_practice)
        with self.app.test_request_context(method=method, json=body):
            request.user_id = COACH
            result = raw(SESSION, SNIPPET)
        return result if isinstance(result, tuple) else (result, 200)

    def _name(self, fake, error_id, named):
        return self._call(fake, "PATCH", {"name_error": {
            "error_id": error_id, "named": named}})

    def _undo(self, fake, teaching_id=TEACHING):
        return self._call(fake, "PATCH", {"undo_teaching": teaching_id})

    # naming ------------------------------------------------------------------

    def test_naming_an_error_appends_one_event_by_the_signed_in_coach(self):
        fake = _Db(entry={"error_id": "rushing", "active": True})
        _resp, status = self._name(fake, "rushing", True)
        self.assertEqual(status, 200)
        self.assertEqual(fake.inserted,
                         [(PRACTICE_ID, "rushing", COACH, "named")])

    def test_naming_twice_writes_once_and_withdrawing_appends(self):
        fake = _Db(entry={"error_id": "rushing", "active": True})
        self._name(fake, "rushing", True)
        self._name(fake, "rushing", True)
        self._name(fake, "rushing", False)
        self.assertEqual([row[3] for row in fake.inserted],
                         ["named", "withdrawn"])

    def test_only_a_library_entry_can_be_named(self):
        fake = _Db(entry=None)
        _resp, status = self._name(fake, "made_up", True)
        self.assertEqual(status, 404)
        self.assertEqual(fake.inserted, [])

    def test_a_retired_entry_cannot_be_newly_named_but_can_be_withdrawn(self):
        fake = _Db(entry={"error_id": "old", "active": False},
                   events=[{"error_id": "old", "action": "named"}])
        _resp, status = self._name(fake, "old", True)
        self.assertEqual(status, 404)
        _resp, status = self._name(fake, "old", False)
        self.assertEqual(status, 200)
        self.assertEqual(fake.inserted[-1][3], "withdrawn")

    def test_a_malformed_edit_is_a_400(self):
        for body in ({}, {"name_error": {"error_id": "rushing"}},
                     {"name_error": {"error_id": "rushing", "named": "yes"}},
                     {"name_error": {"error_id": " ", "named": True}},
                     {"name_error": "rushing"}, ["not", "an", "object"]):
            fake = _Db(entry={"error_id": "rushing", "active": True})
            _resp, status = self._call(fake, "PATCH", body)
            self.assertEqual(status, 400, body)
            self.assertEqual(fake.inserted, [], body)

    def test_the_blind_gate_holds_for_an_edit_too(self):
        # The same gate as the review: no definite rating, no edit.
        self.rating = None
        fake = _Db(entry={"error_id": "rushing", "active": True},
                   undo={"undone": True})
        _resp, status = self._name(fake, "rushing", True)
        self.assertEqual(status, 409)
        _resp, status = self._undo(fake)
        self.assertEqual(status, 409)
        self.assertEqual(fake.inserted, [])
        self.assertEqual(fake.undone, [])

    # undo --------------------------------------------------------------------

    def test_undo_is_scoped_to_this_moment_and_this_coach(self):
        fake = _Db(undo={"undone": True, "removed": True, "reason": None})
        _resp, status = self._undo(fake)
        self.assertEqual(status, 200)
        self.assertEqual(fake.undone, [(TEACHING, PRACTICE_ID, COACH)])

    def test_undo_outcomes(self):
        cases = [
            ({"undone": False, "removed": False, "reason": "not_found"}, 404),
            ({"undone": False, "removed": False,
              "reason": "already_undone"}, 200),
            (None, 503),
        ]
        for result, expected in cases:
            _resp, status = self._undo(_Db(undo=result))
            self.assertEqual(status, expected, result)

    def test_undo_refuses_a_malformed_id(self):
        fake = _Db(undo={"undone": True})
        _resp, status = self._undo(fake, "not-a-uuid")
        self.assertEqual(status, 400)
        self.assertEqual(fake.undone, [])

    # attaching ---------------------------------------------------------------

    def _put(self, fake, body):
        import services.arc_notifications as arc
        original = arc.fire_confidence_practice_shared
        arc.fire_confidence_practice_shared = lambda *a, **k: False
        try:
            return self._call(fake, "PUT", body)
        finally:
            arc.fire_confidence_practice_shared = original

    def test_attaching_teaches_the_library_after_the_save(self):
        fake = _Db()
        _resp, status = self._put(fake, {
            "professional_coach_decision": "yes", "exercise_id": "land-it",
            "share_with_user": True})
        self.assertEqual(status, 200)
        self.assertEqual(fake.taught, [(
            "land-it", PRACTICE_ID, COACH, ["ending_compression"],
            cme.SOURCE_MACHINE_OBSERVED)])
        self.assertEqual(fake.calls, ["update", "teach"])

    def test_attaching_teaches_the_coach_s_naming_when_there_is_one(self):
        fake = _Db(events=[{"error_id": "rushing", "action": "named"}])
        self._put(fake, {"professional_coach_decision": "yes",
                         "exercise_id": "land-it", "share_with_user": True})
        self.assertEqual(fake.taught[0][3:], (["rushing"],
                                              cme.SOURCE_COACH_NAMED))

    def test_saving_without_attaching_teaches_nothing(self):
        fake = _Db()
        self._put(fake, {"professional_coach_decision": "yes",
                         "exercise_id": "land-it", "share_with_user": False})
        self.assertEqual(fake.taught, [])

    def test_the_coach_s_own_exercise_names_the_moment_s_error(self):
        # Since decision 04 the form's exercise was refused every time for
        # naming no error. It now carries the moment's, and teaches nothing
        # on top: it is filed with them.
        fake = _Db()
        _resp, status = self._put(fake, {
            "professional_coach_decision": "yes", "share_with_user": True,
            "custom_exercise": {
                "title": "Land the last word",
                "instruction": "Say it at full volume.",
                "explanation_video_url": "https://cdn.example/c.mp4"}})
        self.assertEqual(status, 200)
        self.assertEqual(fake.filed_fields[0]["acoustic_problem_tags"],
                         ["ending_compression"])
        self.assertEqual(fake.taught, [])

    def test_errors_the_coach_gave_their_exercise_are_kept(self):
        fake = _Db()
        self._put(fake, {
            "professional_coach_decision": "yes", "share_with_user": False,
            "custom_exercise": {
                "title": "Pause", "instruction": "Breathe.",
                "explanation_video_url": "https://cdn.example/c.mp4",
                "acoustic_problem_tags": ["rushing"]}})
        self.assertEqual(fake.filed_fields[0]["acoustic_problem_tags"],
                         ["rushing"])

    def test_the_video_address_is_still_checked_as_before(self):
        # Moved out of the route unchanged (_requested_video_url).
        for url, expected in (("ftp://x/v.mp4", 400), (42, 400),
                              ("https://cdn.example/v.mp4", 200)):
            _resp, status = self._put(_Db(), {
                "professional_coach_decision": "yes",
                "exercise_id": "land-it", "explanation_video_url": url})
            self.assertEqual(status, expected, url)


# ── fences ─────────────────────────────────────────────────────────────────

class FenceTests(unittest.TestCase):
    SOURCE = (ROOT / "routes/v2/coach.py").read_text()

    def _route(self):
        start = self.SOURCE.index("def v2_coach_confident_voice_practice")
        head = self.SOURCE.rindex("@v2_bp.route", 0, start)
        end = self.SOURCE.index("@v2_bp.route", start)
        return self.SOURCE[head:end]

    def test_an_edit_is_dispatched_only_after_the_blind_gate(self):
        route = self._route()
        self.assertIn('methods=["GET", "PUT", "PATCH"]', route)
        self.assertLess(route.index("BLIND_RATING_REQUIRED"),
                        route.index('if request.method == "PATCH":'))

    def test_nothing_the_coach_named_or_taught_reaches_the_speaker(self):
        source = (ROOT / "routes/v2/user_sessions.py").read_text()
        start = source.index("def _practice_user_payload")
        end = source.index("@v2_bp.route", start)
        speaker = source[start:end]
        for leaked in ("named_errors", "library_teachings",
                       "coach_moment", "teaching"):
            self.assertNotIn(leaked, speaker)

    def test_teaching_only_on_attach_and_never_for_the_coach_s_own(self):
        route = self._route()
        self.assertIn("if share and custom_exercise is None:", route)
        self.assertLess(route.index("update_confident_voice_practice("),
                        route.index("teach_on_attach("))

    def test_both_tables_go_with_the_speaker_s_practice(self):
        from services.data_purge_registry import DEPENDENCIES
        by_relation = {d.relation: d for d in DEPENDENCIES}
        practice = by_relation["confident_voice_practice"]
        for relation in ("coach_moment_error_event",
                         "diagnostic_exercise_teaching"):
            dependency = by_relation[relation]
            self.assertEqual((dependency.selector_column,
                              dependency.locator_kind,
                              dependency.disposition),
                             ("practice_id", "practice", "delete"), relation)
            self.assertLess(dependency.delete_order, practice.delete_order)

    def test_the_migration_holds_the_standing_rules(self):
        sql = (ROOT / "migrations/"
               "a_coach_names_the_error_and_teaches_the_library.sql"
               ).read_text()
        code = "\n".join(line for line in sql.splitlines()
                         if not line.lstrip().startswith("--"))
        for table in ("coach_moment_error_event",
                      "diagnostic_exercise_teaching"):
            self.assertIn(f"ALTER TABLE public.{table} ENABLE ROW LEVEL "
                          "SECURITY", code)
        for signature in ("teach_diagnostic_exercise_v1(\n    TEXT, UUID, "
                          "UUID, TEXT[], TEXT\n) FROM PUBLIC, anon, "
                          "authenticated",
                          "undo_diagnostic_exercise_teaching_v1(\n    UUID, "
                          "UUID, UUID\n) FROM PUBLIC, anon, authenticated"):
            self.assertIn(signature, code)
        self.assertEqual(code.count("SET search_path = public"), 2)
        self.assertNotRegex(code, r"(?i)\bDROP\b|\bTRUNCATE\b|\bDELETE\s+FROM")
        self.assertIn("ON DELETE CASCADE", code)
        self.assertIn("ON DELETE SET NULL", code)


if __name__ == "__main__":
    unittest.main()
