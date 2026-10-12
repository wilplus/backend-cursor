"""THE VOICE ALBUM — capture (founder re-lock 2026-08-13/14).

The entry rule, verbatim: "Acoustic data indicates a great moment ->
User agrees -> Coach agrees = This moment lands in the Voice Album."
These pins hold the JOIN: all three signals or no entry, blind until
publish, routing withdrawal, idempotence, and never a ranking term.

Run: python3 -m unittest tests.test_voice_album
"""
from __future__ import annotations

import unittest
from unittest import mock


# THE MACHINE LEG IS THE CLIP'S OWN READ (founder 2026-10-05, Q5; N45).
# These fakes still describe a confident clip the way the old lane did (an
# EMPHASIZE "confident" row); the read below translates that into the read
# the album now asks for, so each test keeps its meaning. A reader that
# raises is a clip that cannot be read (None).
def _read_from_star(database, take_session_id, snippet_id):
    try:
        try:
            rows = database.get_moment_suggestions_by_arc("arc-1", strict=True)
        except TypeError:
            rows = database.get_moment_suggestions_by_arc("arc-1")
    except Exception:
        return None
    row = (rows or {}).get(str(snippet_id))
    if (isinstance(row, dict) and row.get("kind") == "emphasize"
            and row.get("trigger") == "confident"):
        return "confident"
    return "weak"


_READ_PATCH = mock.patch("services.judgement_follow_up.clip_machine_read",
                         _read_from_star)


def setUpModule():
    _READ_PATCH.start()


def tearDownModule():
    _READ_PATCH.stop()


if __name__ == "__main__":
    unittest.main()


try:
    from flask import Flask, request

    from routes.v2 import arcs as v2_arcs
    from services.db import db
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    Flask = None
    request = None
    _IMPORT_ERROR = e

from unittest.mock import patch


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class VoiceAlbumReadTests(unittest.TestCase):
    """The read endpoint — data only, AC-9-clean, ownership-gated. The
    surface copy/UI is the founder's; this is the substrate it lands on."""

    def _get(self, *, sessions, entries, snips, uid="u1"):
        app = Flask(__name__)
        with app.test_request_context():
            request.user_id = uid
            with patch.object(db.takes, "get_arc_sessions",
                              return_value=sessions), \
                 patch.object(db, "list_voice_album",
                              return_value=entries, create=True), \
                 patch.object(db, "get_snippets_by_session",
                              return_value=snips):
                out = v2_arcs.v2_explore_arc_voice_album.__wrapped__("arc-1")
            resp, status = out if isinstance(out, tuple) else (out, 200)
            return resp.get_json(), status

    _SESS = [{"id": "t1", "user_id": "u1", "take_index": 2}]
    _ENTRY = [{"snippet_id": "sn1", "take_session_id": "t1",
               "slide_index": 3, "entered_at": "2026-08-14T10:00:00Z"}]
    _SNIPS = [{"id": "sn1", "transcript": "The words that landed.",
               "storage_path": None, "audio_url": None,
               "start_offset_ms": 1200, "duration_ms": 4000,
               "metrics": {"voice_confidence": {"score": 0.93}}}]


    def test_ac9_no_confidence_no_tags_no_scores_on_the_wire(self):
        body, _ = self._get(sessions=self._SESS, entries=self._ENTRY,
                            snips=self._SNIPS)
        flat = str(body)
        self.assertNotIn("confidence", flat)
        self.assertNotIn("0.93", flat)
        self.assertNotIn("tag", flat)
        self.assertNotIn("metrics", flat)
