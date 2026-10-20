"""
STORY    As a speaker, I want the "your voice album is ready" chat message to
         speak in words, never counts or rankings, so that it encourages
         rather than grades.
OUTCOME
  O1  The message has no digits and none of: score, best, top, rank, %,
      points.
PROVES   O1 -> VoiceAlbumBubbleTests::test_ac9_it_never_counts_or_grades
WHY      Never-rule 1; founder 2026-08-15 (post the album bubble once it is
         available).
"""
from __future__ import annotations

import unittest

if __name__ == "__main__":
    unittest.main()


class VoiceAlbumBubbleTests(unittest.TestCase):
    """THE ALBUM ANNOUNCES ITSELF (founder 2026-08-15: "when is the bubble
    with voice album posted in the chat? if not post it once it is
    available").

    It was posted nowhere. The album filled quietly from its first day —
    capture-only on purpose, because the read surface needed signed copy — so
    the only way to find a moment in it was to already know it was there."""

    class _Db:
        def __init__(self):
            self.rows = []
            self.voice_album_introduced = False

        def list_voice_album(self, arc_id):
            return [{"snippet_id": "clip-1"}]

        def get_arc_sessions(self, arc_id):
            return [
                {"id": f"take-{index}", "analysis_state": "ready"}
                for index in range(1, 4)
            ]

        @property
        def takes(self):
            # audit Q-A2: production now calls db.takes.<method>();
            # this fake implements those methods directly on itself.
            return self

        def insert_lounge_messages(self, user_id, messages):
            for m in messages:
                if any(r["client_id"] == m["client_id"] for r in self.rows):
                    continue          # mirror the real upsert idempotency
                self.rows.append({**m, "_user": user_id})
            return list(messages)

        def has_voice_album_introduction(self, user_id):
            return self.voice_album_introduced

        def mark_voice_album_introduced(self, user_id):
            self.voice_album_introduced = True
            return True


    def test_ac9_it_never_counts_or_grades(self):
        from services.arc_notifications import fire_voice_album_ready
        db = self._Db()
        fire_voice_album_ready(db, "u1", "arc-1")
        body = db.rows[0]["body"].lower()
        for banned in ("score", "best", "top", "rank", "%", "points"):
            self.assertNotIn(banned, body)
        # No count either — "a moment", never "3 moments".
        self.assertFalse(any(ch.isdigit() for ch in body))
