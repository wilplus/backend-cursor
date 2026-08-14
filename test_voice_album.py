"""THE VOICE ALBUM — capture (founder re-lock 2026-08-13/14).

The entry rule, verbatim: "Acoustic data indicates a great moment ->
User agrees -> Coach agrees = This moment lands in the Voice Album."
These pins hold the JOIN: all three signals or no entry, blind until
publish, append-only, idempotent, and never a ranking term.

Run: python3 -m unittest test_voice_album
"""
from __future__ import annotations

import unittest

from services.voice_album import refresh_voice_album

ARC = "arc-1"


class _Db:
    def __init__(self, *, ledger=None, suggestions=None, sessions=None,
                 drafts=None, album=None):
        self.ledger = ledger or []
        self.suggestions = suggestions or {}
        self.sessions = sessions or []
        self.drafts = drafts or {}
        self.album = album or []
        self.inserted = []
        self.deleted = []

    def list_ideal_decisions(self, arc_id):
        return self.ledger

    def get_moment_suggestions_by_arc(self, arc_id):
        return self.suggestions

    def get_arc_sessions(self, arc_id):
        return self.sessions

    def get_coach_snippet_drafts(self, sid):
        return self.drafts.get(sid, [])

    def list_voice_album(self, arc_id):
        return self.album

    def insert_voice_album_entry(self, **kw):
        self.inserted.append(kw)
        return True

    def delete_voice_album_entry(self, **kw):
        self.deleted.append(kw)
        return True


def _all_three(published=True):
    """A db where snippet sn1 carries all three signals."""
    return _Db(
        ledger=[{"kind": "emphasize", "decision": "approved",
                 "snippet_id": "sn1", "slide_index": 2}],
        suggestions={"sn1": {"kind": "emphasize"}},
        sessions=[{"id": "t1",
                   "results_published_at":
                       "2026-08-14T10:00:00Z" if published else None}],
        drafts={"t1": [{"snippet_id": "sn1", "tag": "strong"}]},
    )


class EntryRuleTests(unittest.TestCase):
    def test_all_three_signals_land_the_moment(self):
        db = _all_three()
        self.assertEqual(refresh_voice_album(ARC, database=db), 1)
        self.assertEqual(len(db.inserted), 1)
        e = db.inserted[0]
        self.assertEqual(e["snippet_id"], "sn1")
        self.assertEqual(e["take_session_id"], "t1")
        self.assertEqual(e["slide_index"], 2)

    def test_no_user_approval_no_entry(self):
        db = _all_three()
        db.ledger = [{"kind": "emphasize", "decision": "dismissed",
                      "snippet_id": "sn1"}]
        self.assertEqual(refresh_voice_album(ARC, database=db), 0)
        self.assertEqual(db.inserted, [])

    def test_no_acoustic_star_no_entry(self):
        # A replace star is not the acoustic great-moment signal.
        db = _all_three()
        db.suggestions = {"sn1": {"kind": "replace"}}
        self.assertEqual(refresh_voice_album(ARC, database=db), 0)

    def test_coach_tag_without_publish_is_invisible(self):
        # BLIND COACH: the coach signal does not exist before publish.
        db = _all_three(published=False)
        self.assertEqual(refresh_voice_album(ARC, database=db), 0)
        self.assertEqual(db.inserted, [])

    def test_work_on_tag_is_not_agreement(self):
        db = _all_three()
        db.drafts = {"t1": [{"snippet_id": "sn1", "tag": "to_work_on"}]}
        self.assertEqual(refresh_voice_album(ARC, database=db), 0)

    def test_idempotent_second_refresh_inserts_nothing(self):
        db = _all_three()
        db.album = [{"snippet_id": "sn1"}]
        self.assertEqual(refresh_voice_album(ARC, database=db), 0)
        self.assertEqual(db.inserted, [])
        # Still aligned — the mirror leaves it exactly in place.
        self.assertEqual(db.deleted, [])

    def test_a_reverted_approval_removes_the_entry(self):
        # THE MIRROR RULING (founder 2026-08-14): the album is a pure
        # reflection of current state — un-apply the emphasize and the
        # moment leaves the album, never a graveyard of changed minds.
        db = _all_three()
        db.ledger = []                       # the user signal withdrew
        db.album = [{"snippet_id": "sn1"}]
        self.assertEqual(refresh_voice_album(ARC, database=db), 0)
        self.assertEqual(db.inserted, [])
        self.assertEqual([d["snippet_id"] for d in db.deleted], ["sn1"])

    def test_one_lands_while_another_leaves_in_one_pass(self):
        db = _all_three()
        db.album = [{"snippet_id": "sn_old"}]   # no longer aligned
        self.assertEqual(refresh_voice_album(ARC, database=db), 1)
        self.assertEqual([i["snippet_id"] for i in db.inserted], ["sn1"])
        self.assertEqual([d["snippet_id"] for d in db.deleted], ["sn_old"])

    def test_a_phrase_only_approval_cannot_enter(self):
        # The entry is a MOMENT: a ledger row with no snippet id has
        # nowhere to land.
        db = _all_three()
        db.ledger = [{"kind": "emphasize", "decision": "approved",
                      "snippet_id": None}]
        self.assertEqual(refresh_voice_album(ARC, database=db), 0)

    def test_broken_db_never_raises(self):
        class _Boom(_Db):
            def get_arc_sessions(self, arc_id):
                raise RuntimeError("db down")
        self.assertEqual(refresh_voice_album(ARC, database=_Boom(
            ledger=[{"kind": "emphasize", "decision": "approved",
                     "snippet_id": "sn1"}],
            suggestions={"sn1": {"kind": "emphasize"}})), 0)


class NeverARankingTermTests(unittest.TestCase):
    def test_power_score_has_no_album_term(self):
        # The founder deleted the quorum bonus with _W_B: the album is a
        # destination, not a weight. power_score must not accept one.
        from services.power_phrase_ranking import power_score
        with self.assertRaises(TypeError):
            power_score(album_quorum=True)   # retired kwarg stays dead
        import inspect
        from services import power_phrase_ranking as ppr
        src = inspect.getsource(ppr)
        self.assertNotIn("voice_album", src)


if __name__ == "__main__":
    unittest.main()
