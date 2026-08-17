"""Project display names are unique; UUIDs own continuation identity."""
from __future__ import annotations

import unittest

try:
    from routes.v2.lab_recording import (
        _duplicate_project_arc, _normalized_project_name,
    )
    _ERR = None
except Exception as exc:  # pragma: no cover
    _ERR = exc


class _Db:
    def __init__(self, sessions):
        self.sessions = sessions

    def v2_list_user_lab_sessions(self, user_id):
        return self.sessions


@unittest.skipIf(_ERR is not None, f"needs app deps: {_ERR}")
class ProjectNameTests(unittest.TestCase):
    def test_normalization_is_case_and_whitespace_insensitive(self):
        self.assertEqual(_normalized_project_name("  My   Talk "), "my talk")

    def test_new_project_with_existing_name_is_a_collision(self):
        db = _Db([{
            "arc_id": "arc-one",
            "intake_context": {"topic": "My Talk"},
        }])
        self.assertEqual(
            _duplicate_project_arc(db, "owner", " my  talk "), "arc-one")

    def test_continuing_that_exact_uuid_may_reuse_its_name(self):
        db = _Db([{
            "arc_id": "arc-one",
            "intake_context": {"topic": "My Talk"},
        }])
        self.assertIsNone(
            _duplicate_project_arc(db, "owner", "My Talk", "arc-one"))

    def test_same_name_on_another_uuid_still_collides(self):
        db = _Db([
            {"arc_id": "arc-one", "intake_context": {"topic": "My Talk"}},
            {"arc_id": "arc-two", "intake_context": {"topic": "My Talk"}},
        ])
        self.assertEqual(
            _duplicate_project_arc(db, "owner", "My Talk", "arc-one"),
            "arc-two")

    def test_guests_have_no_cross_account_name_scope(self):
        db = _Db([{
            "arc_id": "arc-one",
            "intake_context": {"topic": "My Talk"},
        }])
        self.assertIsNone(_duplicate_project_arc(db, None, "My Talk"))


if __name__ == "__main__":
    unittest.main()
