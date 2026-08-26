"""THE VOICE ALBUM — capture (founder re-lock 2026-08-13/14).

The entry rule, verbatim: "Acoustic data indicates a great moment ->
User agrees -> Coach agrees = This moment lands in the Voice Album."
These pins hold the JOIN: all three signals or no entry, blind until
publish, routing withdrawal, idempotence, and never a ranking term.

Run: python3 -m unittest test_voice_album
"""
from __future__ import annotations

import unittest

from services.voice_album import refresh_voice_album

ARC = "arc-1"


def _coach(value):
    return [{"rater_id": "coach1", "lane": "coach", "value": value,
             "state_id": "confidence", "self_report": False}]


class _Db:
    def __init__(self, *, routes=None, suggestions=None, sessions=None,
                 snips=None, conf=None, album=None):
        self.routes = routes or []
        self.suggestions = suggestions or {}
        self.sessions = sessions or []
        self.snips = snips or {}
        self.conf = conf or {}
        self.album = album or []
        self.inserted = []
        self.deleted = []

    def list_owner_voice_album_routes(self, arc_id):
        return self.routes

    def get_moment_suggestions_by_arc(self, arc_id):
        return self.suggestions

    def get_arc_sessions(self, arc_id):
        return self.sessions

    def get_snippets_by_session(self, sid):
        return self.snips.get(sid, [])

    def get_confidence_labels_by_snippet_ids(self, ids):
        return {i: self.conf.get(i, []) for i in ids}

    def list_voice_album(self, arc_id):
        return self.album

    def insert_voice_album_entry(self, **kw):
        self.inserted.append(kw)
        return True

    def delete_voice_album_entry(self, **kw):
        self.deleted.append(kw)
        return True


def _all_three(published=True):
    """A db where snippet sn1 carries all three signals.

    The COACH leg is an explicit professional coach YES. Peer and owner labels
    remain separately typed evidence and cannot substitute for it."""
    return _Db(
        routes=[{"snippet_id": "sn1", "response": "yes",
                 "slide_index": 2}],
        suggestions={"sn1": {"kind": "emphasize", "trigger": "confident"}},
        sessions=[{"id": "t1",
                   "results_published_at":
                       "2026-08-14T10:00:00Z" if published else None}],
        snips={"t1": [{"id": "sn1"}]},
        conf={"sn1": _coach("yes")},
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
        db.routes = [{"snippet_id": "sn1", "response": "no"}]
        self.assertEqual(refresh_voice_album(ARC, database=db), 0)
        self.assertEqual(db.inserted, [])

    def test_no_acoustic_star_no_entry(self):
        # A replace star is not the acoustic great-moment signal.
        db = _all_three()
        db.suggestions = {"sn1": {"kind": "replace"}}
        self.assertEqual(refresh_voice_album(ARC, database=db), 0)

    def test_coach_yes_without_publish_is_invisible(self):
        # BLIND COACH: a coach answer can exist while the review is still in
        # progress; none of it exists for the student until publish.
        db = _all_three(published=False)
        self.assertEqual(refresh_voice_album(ARC, database=db), 0)
        self.assertEqual(db.inserted, [])

    def test_a_settled_NO_is_not_agreement(self):
        # A quorum that settled the other way is a real verdict, and the
        # opposite of an album entry.
        db = _all_three()
        db.conf = {"sn1": _coach("no")}
        self.assertEqual(refresh_voice_album(ARC, database=db), 0)

    def test_peer_agreement_cannot_replace_the_professional_coach(self):
        db = _all_three()
        db.conf = {"sn1": [
            {"rater_id": "peer1", "lane": "game_peer", "value": "yes"},
            {"rater_id": "peer2", "lane": "game_peer", "value": "yes"},
        ]}
        self.assertEqual(refresh_voice_album(ARC, database=db), 0)

    def test_owner_self_report_cannot_replace_the_professional_coach(self):
        db = _all_three()
        db.conf = {"sn1": [{"rater_id": "owner", "lane": "coach",
                            "value": "yes", "self_report": True,
                            "state_id": "confidence"}]}
        self.assertEqual(refresh_voice_album(ARC, database=db), 0)

    def test_legacy_explicit_coach_row_remains_eligible(self):
        db = _all_three()
        db.conf = {"sn1": [{"rater_id": "coach1", "source": "coach",
                            "value": "yes", "state_id": "confidence",
                            "self_report": False}]}
        self.assertEqual(refresh_voice_album(ARC, database=db), 1)

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
        db.routes = []                       # the user signal withdrew
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

    def test_a_route_without_snippet_cannot_enter(self):
        # The entry is a MOMENT: a routing row with no snippet id has nowhere
        # to land.
        db = _all_three()
        db.routes = [{"response": "yes", "snippet_id": None}]
        self.assertEqual(refresh_voice_album(ARC, database=db), 0)

    def test_broken_db_never_raises(self):
        class _Boom(_Db):
            def get_arc_sessions(self, arc_id):
                raise RuntimeError("db down")
        self.assertEqual(refresh_voice_album(ARC, database=_Boom(
            routes=[{"response": "yes", "snippet_id": "sn1"}],
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


try:
    from flask import Flask, request
    from routes import v2_routes as v2
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    Flask = None
    request = None
    v2 = None
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
            with patch.object(v2.db, "get_arc_sessions",
                              return_value=sessions), \
                 patch.object(v2.db, "list_voice_album",
                              return_value=entries, create=True), \
                 patch.object(v2.db, "get_snippets_by_session",
                              return_value=snips):
                out = v2.v2_explore_arc_voice_album.__wrapped__("arc-1")
            resp, status = out if isinstance(out, tuple) else (out, 200)
            return resp.get_json(), status

    _SESS = [{"id": "t1", "user_id": "u1", "take_index": 2}]
    _ENTRY = [{"snippet_id": "sn1", "take_session_id": "t1",
               "slide_index": 3, "entered_at": "2026-08-14T10:00:00Z"}]
    _SNIPS = [{"id": "sn1", "transcript": "The words that landed.",
               "storage_path": None, "audio_url": None,
               "start_offset_ms": 1200, "duration_ms": 4000,
               "metrics": {"voice_confidence": {"score": 0.93}}}]

    def test_entries_serve_words_position_and_span(self):
        body, status = self._get(sessions=self._SESS, entries=self._ENTRY,
                                 snips=self._SNIPS)
        self.assertEqual(status, 200)
        e = body["entries"][0]
        self.assertEqual(e["text"], "The words that landed.")
        self.assertEqual(e["slide_index"], 3)
        self.assertEqual(e["take_index"], 2)
        self.assertEqual(e["start_offset_ms"], 1200)

    def test_ac9_no_confidence_no_tags_no_scores_on_the_wire(self):
        body, _ = self._get(sessions=self._SESS, entries=self._ENTRY,
                            snips=self._SNIPS)
        flat = str(body)
        self.assertNotIn("confidence", flat)
        self.assertNotIn("0.93", flat)
        self.assertNotIn("tag", flat)
        self.assertNotIn("metrics", flat)

    def test_ownership_gate_404s_a_foreign_arc(self):
        body, status = self._get(sessions=self._SESS, entries=self._ENTRY,
                                 snips=self._SNIPS, uid="intruder")
        self.assertEqual(status, 404)

    def test_empty_album_serves_an_empty_list(self):
        body, status = self._get(sessions=self._SESS, entries=[], snips=[])
        self.assertEqual(status, 200)
        self.assertEqual(body["entries"], [])

    def test_entries_read_in_presentation_order_not_capture_order(self):
        # Founder 2026-08-14: the album reads in DECK position, whatever
        # order the moments were earned in. Capture order (the DB's
        # entered_at base) put slide 7 first when it was locked first;
        # an entry with no slide reads last.
        entries = [
            {"snippet_id": "s7", "take_session_id": "t1", "slide_index": 7,
             "entered_at": "2026-08-01T10:00:00Z"},
            {"snippet_id": "sN", "take_session_id": "t1",
             "slide_index": None,
             "entered_at": "2026-08-02T10:00:00Z"},
            {"snippet_id": "s2", "take_session_id": "t1", "slide_index": 2,
             "entered_at": "2026-08-03T10:00:00Z"},
        ]
        body, status = self._get(sessions=self._SESS, entries=entries,
                                 snips=self._SNIPS)
        self.assertEqual(status, 200)
        self.assertEqual([e["snippet_id"] for e in body["entries"]],
                         ["s2", "s7", "sN"])

    def test_same_slide_ties_break_on_entered_at(self):
        # Two moments on one slide keep earn order (oldest first).
        entries = [
            {"snippet_id": "late", "take_session_id": "t1",
             "slide_index": 4, "entered_at": "2026-08-05T10:00:00Z"},
            {"snippet_id": "early", "take_session_id": "t1",
             "slide_index": 4, "entered_at": "2026-08-01T10:00:00Z"},
        ]
        body, _ = self._get(sessions=self._SESS, entries=entries,
                            snips=self._SNIPS)
        self.assertEqual([e["snippet_id"] for e in body["entries"]],
                         ["early", "late"])
