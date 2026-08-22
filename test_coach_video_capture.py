"""Coach-video corpus capture (Subsystem V). Pure builder + orchestration.

Run: python3 -m unittest test_coach_video_capture
"""
from __future__ import annotations

import unittest

from services.coach_video_capture import (
    build_asset_row, capture_coach_video, DEFAULT_CONSENT_SCOPE,
)


class BuildAssetRowTests(unittest.TestCase):
    def _row(self, **kw):
        base = dict(
            session_id="s1", snippet_id=None, content_type="take_summary",
            recorded_by="coach1", video_ref="https://v/1.mp4", comment_text=None,
            device=None, source=None, duration=None, idempotency_key=None,
        )
        base.update(kw)
        return build_asset_row(**base)

    def test_defaults(self):
        r = self._row()
        self.assertTrue(r["is_current"])
        self.assertEqual(r["origin"], "recorded")
        self.assertEqual(r["transcription_status"], "pending")
        self.assertEqual(r["consent_scope"], DEFAULT_CONSENT_SCOPE)
        self.assertTrue(r["train_eligible"])  # no rating yet → eligible
        self.assertNotIn("quality_rate", r)

    def test_train_eligible_computed_once_not_reject(self):
        self.assertTrue(self._row(quality_rate="good")["train_eligible"])
        self.assertTrue(self._row(quality_rate="usable")["train_eligible"])
        # reject → not eligible; but it's a plain value (overridable later), not
        # a generated column.
        rej = self._row(quality_rate="reject")
        self.assertFalse(rej["train_eligible"])
        self.assertEqual(rej["quality_rate"], "reject")

    def test_optional_fields(self):
        r = self._row(comment_text="great open", device="iphone", source="app",
                      duration="12.5", idempotency_key="k1")
        self.assertEqual(r["comment_text_snapshot"], "great open")
        self.assertEqual(r["device"], "iphone")
        self.assertEqual(r["duration"], 12.5)
        self.assertEqual(r["upload_idempotency_key"], "k1")

    def test_bad_duration_dropped(self):
        self.assertNotIn("duration", self._row(duration="abc"))

    def test_empty_comment_is_null(self):
        self.assertIsNone(self._row(comment_text="")["comment_text_snapshot"])


class _FakeDB:
    def __init__(self, prior=None):
        self._prior = prior
        self.inserted = None
        self.superseded = None
        self._next_id = "new-asset-1"

    def get_current_coach_video_asset(self, session_id, content_type, snippet_id=None):
        return self._prior

    def insert_coach_video_asset(self, row):
        self.inserted = row
        return {"id": self._next_id, **row}

    def supersede_coach_video_asset(self, prev_id, new_id):
        self.superseded = (prev_id, new_id)
        return True


class CaptureOrchestrationTests(unittest.TestCase):
    def test_first_take_inserts_no_supersede(self):
        db = _FakeDB(prior=None)
        capture_coach_video(
            database=db, session_id="s1", content_type="take_summary",
            recorded_by="c1", video_ref="u1", video_bytes=None,
        )
        self.assertIsNotNone(db.inserted)
        self.assertTrue(db.inserted["is_current"])
        self.assertIsNone(db.superseded)

    def test_re_record_supersedes_prior(self):
        db = _FakeDB(prior={"id": "old-asset"})
        capture_coach_video(
            database=db, session_id="s1", content_type="take_summary",
            recorded_by="c1", video_ref="u2", video_bytes=None,
        )
        # the (kept new, superseded old) preference pair is labeled
        self.assertEqual(db.superseded, ("old-asset", "new-asset-1"))

    def test_bad_content_type_noop(self):
        db = _FakeDB()
        capture_coach_video(
            database=db, session_id="s1", content_type="nonsense",
            recorded_by="c1", video_ref="u1", video_bytes=None,
        )
        self.assertIsNone(db.inserted)

    def test_insert_failure_is_swallowed(self):
        class _BadDB(_FakeDB):
            def insert_coach_video_asset(self, row):
                return None
        db = _BadDB(prior={"id": "old"})
        # must not raise, must not supersede when insert failed
        capture_coach_video(
            database=db, session_id="s1", content_type="take_summary",
            recorded_by="c1", video_ref="u1", video_bytes=None,
        )
        self.assertIsNone(db.superseded)


if __name__ == "__main__":
    unittest.main()
