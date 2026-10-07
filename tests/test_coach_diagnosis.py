"""The coach's diagnosis comes first (coach panel lock flow 6; Q-B7 A;
Q-B12 A; D-CP-4; migration 0445): the list's order, the body, the writes,
the gate and the walls. The database half is
tests/test_the_coach_s_diagnosis_comes_first_postgres.py."""
from __future__ import annotations

import inspect
import pathlib
import unittest

from services import coach_diagnosis as cd

ROOT = pathlib.Path(__file__).resolve().parents[1]

LIBRARY = [
    {"error_id": "rushing", "label": "Rushing", "active": True, "status": "detected"},
    {"error_id": "trailing", "label": "Trailing off", "active": True, "status": "observed"},
    {"error_id": "mumbling", "label": "Mumbling", "active": True, "status": "shadow"},
    {"error_id": "retired", "label": "Retired", "active": False, "status": "observed"},
]
NAMED = [
    {"id": "n-1", "name": "swallowed endings", "speaking_error_id": None},
    {"id": "n-2", "name": "already linked", "speaking_error_id": "rushing"},
]


class OrderTests(unittest.TestCase):
    def test_machine_heard_first_and_flagged_then_the_library_then_coach_named(self):
        request = {"observed_tags": ["mumbling", "rushing", "mumbling", "not_in_library"]}
        heard = cd.machine_heard_error_ids(request)
        self.assertEqual(heard, ["mumbling", "rushing", "not_in_library"])
        out = cd.error_choices(LIBRARY, NAMED, heard)
        self.assertEqual([(c["label"], c["machine_heard"]) for c in out], [
            ("Mumbling", True), ("Rushing", True),
            ("Trailing off", False),
            ("swallowed endings", False),
        ])
        self.assertEqual(out[-1], {"kind": "named_error", "named_error_id": "n-1",
                                   "label": "swallowed endings", "machine_heard": False,
                                   "named_by_a_coach": True})
        # A retired entry is not offered; a linked name is its library error.
        self.assertNotIn("Retired", [c["label"] for c in out])
        self.assertNotIn("already linked", [c["label"] for c in out])
        # Words only: no count, no number, no status rides.
        for choice in out:
            self.assertEqual(set(choice) - {"kind", "error_id", "named_error_id", "label",
                                            "machine_heard", "named_by_a_coach"}, set())
            self.assertNotIn("status", choice)

    def test_no_request_means_nothing_heard(self):
        self.assertEqual(cd.machine_heard_error_ids(None), [])
        out = cd.error_choices(LIBRARY, [], [])
        self.assertTrue(all(c["machine_heard"] is False for c in out))
        self.assertEqual(cd.error_choices([], [], ["rushing"]), [])


class BodyTests(unittest.TestCase):
    def test_exactly_one_of_three(self):
        self.assertEqual(cd.parse_body({"error_id": " rushing "}),
                         ({"kind": "error", "error_id": "rushing", "new_name": None}, None))
        self.assertEqual(cd.parse_body({"new_name": "  trailing   off "}),
                         ({"kind": "named_error", "error_id": None, "new_name": "trailing off"}, None))
        self.assertEqual(cd.parse_body({"no_error": True}),
                         ({"kind": "no_error", "error_id": None, "new_name": None}, None))
        for bad in ({}, {"error_id": "a", "no_error": True}, {"no_error": False},
                    {"error_id": ""}, {"new_name": 3}, {"new_name": "x" * 121}, None, "x"):
            parsed, error = cd.parse_body(bad)
            self.assertIsNone(parsed, bad)
            self.assertEqual(error[0], 400, bad)
            self.assertEqual(error[1]["code"], "INVALID_INPUT")


class _Db:
    def __init__(self, *, request=None, current=None, refusal=None):
        self.request = request
        self.current = current
        self.refusal = refusal
        self.writes: list = []

    def get_exercise_coach_request(self, _take, _snip):
        return self.request

    def list_speaking_errors(self):
        return LIBRARY

    def list_coach_named_errors(self, *, unlinked_only=True):
        return [n for n in NAMED if not (unlinked_only and n["speaking_error_id"])]

    def get_coach_moment_diagnosis(self, *, snippet_id, coach_id):
        return self.current

    def set_coach_moment_diagnosis(self, **kw):
        if self.refusal:
            raise RuntimeError(self.refusal)
        self.writes.append(kw)
        return {"kind": kw["kind"], "error_id": kw["error_id"], "named_error_id": "n-9",
                "version": 2, "created_at": "2026-10-07T21:00:00Z"}


class RouteWorkTests(unittest.TestCase):
    def test_get_lists_in_order_with_this_coach_s_current_diagnosis(self):
        db = _Db(request={"observed_tags": ["rushing"]},
                 current={"kind": "error", "error_id": "rushing", "version": 1,
                          "created_at": "t"})
        status, payload = cd.review(db, take_session_id="t", snippet_id="s", coach_id="c",
                                    method="GET")
        self.assertEqual(status, 200)
        self.assertEqual(payload["errors"][0], {"kind": "error", "error_id": "rushing",
                                                "label": "Rushing", "machine_heard": True})
        self.assertEqual(payload["diagnosis"], {"kind": "error", "error_id": "rushing",
                                                "created_at": "t"})
        self.assertNotIn("version", payload["diagnosis"])
        db = _Db(request=None, current=None)
        status, payload = cd.review(db, take_session_id="t", snippet_id="s", coach_id="c",
                                    method="GET")
        self.assertIsNone(payload["diagnosis"])

    def test_put_saves_one_diagnosis_and_names_the_database_s_refusals(self):
        db = _Db()
        status, payload = cd.review(db, take_session_id="t", snippet_id="s", coach_id="c",
                                    method="PUT", body={"new_name": "swallowed words"})
        self.assertEqual(status, 200)
        self.assertEqual(db.writes, [{"take_session_id": "t", "snippet_id": "s", "coach_id": "c",
                                      "kind": "named_error", "error_id": None,
                                      "new_name": "swallowed words"}])
        self.assertEqual(payload["diagnosis"]["kind"], "named_error")
        self.assertEqual(payload["diagnosis"]["named_error_id"], "n-9")
        status, payload = cd.review(_Db(refusal="COACH_DIAGNOSIS_ERROR_NOT_IN_LIBRARY"),
                                    take_session_id="t", snippet_id="s", coach_id="c",
                                    method="PUT", body={"error_id": "nope"})
        self.assertEqual((status, payload["code"]), (404, "ERROR_NOT_IN_LIBRARY"))
        status, payload = cd.review(_Db(refusal="COACH_DIAGNOSIS_INPUT_INVALID"),
                                    take_session_id="t", snippet_id="s", coach_id="c",
                                    method="PUT", body={"no_error": True})
        self.assertEqual((status, payload["code"]), (400, "INVALID_INPUT"))
        status, payload = cd.review(_Db(refusal="connection reset"),
                                    take_session_id="t", snippet_id="s", coach_id="c",
                                    method="PUT", body={"no_error": True})
        self.assertEqual((status, payload["code"]), (500, "V2_ERROR"))
        status, _ = cd.review(_Db(), take_session_id="t", snippet_id="s", coach_id="c",
                              method="PUT", body={})
        self.assertEqual(status, 400)


class WallsTests(unittest.TestCase):
    def test_the_route_sits_behind_the_blind_gate_and_inside_the_fence(self):
        from routes.v2 import coach
        source = inspect.getsource(coach.v2_coach_moment_diagnosis)
        self.assertLess(source.index("_moment_gate(session_id, snippet_id)"),
                        source.index("review("))
        self.assertIn('methods=["GET", "PUT"]', source)
        self.assertNotIn("db.", source.split("from services.coach_diagnosis import review")[0]
                         .replace("_moment_gate", ""))

    def test_a_diagnosis_is_coach_provenance_and_never_readiness(self):
        """Q-B7 A: naming is a signal for the founder only; readiness still
        comes from blind 'Do you hear it?' answers; nothing trains on it."""
        for path in ("services/error_presence_audit.py", "services/label_quorum.py",
                     "services/confidence_labels.py", "scripts/exercise_learning_readiness.py",
                     "services/feedback_data_contract.py", "routes/v2/user_sessions.py",
                     "services/confident_voice_practice.py"):
            text = (ROOT / path).read_text(encoding="utf-8")
            self.assertNotIn("coach_moment_diagnoses", text, path)
            self.assertNotIn("coach_named_errors", text, path)
            self.assertNotIn("coach_diagnosis", text, path)

    def test_both_tables_are_classified_for_the_purge(self):
        from services.data_purge_registry import DEPENDENCIES, NON_SUBJECT_RELATIONS
        keyed = {(d.selector_column, d.locator_kind, d.disposition)
                 for d in DEPENDENCIES if d.relation == "coach_moment_diagnoses"}
        self.assertEqual(keyed, {("take_session_id", "take", "delete"),
                                 ("coach_id", "user", "delete")})
        self.assertIn("coach_named_errors", NON_SUBJECT_RELATIONS)

    def test_the_migration_holds_the_standing_rules(self):
        sql = (ROOT / "migrations" / "the_coach_s_diagnosis_comes_first.sql").read_text()
        self.assertEqual(sql.count("ENABLE ROW LEVEL SECURITY"), 2)
        for table in ("coach_named_errors", "coach_moment_diagnoses"):
            self.assertIn(f"REVOKE ALL ON TABLE public.{table} FROM PUBLIC", sql)
        fn = "set_coach_moment_diagnosis_v1(text, text, text, text, text, text)"
        self.assertIn(f"REVOKE ALL ON FUNCTION public.{fn} FROM PUBLIC", sql)
        self.assertIn(f"GRANT EXECUTE ON FUNCTION public.{fn} TO service_role", sql)
        self.assertIn("SECURITY DEFINER SET search_path = public", sql)
        self.assertIn("Rollback (a new forward migration)", sql)
        self.assertNotIn("confidence_labels", sql.split("BEGIN;", 1)[1])
