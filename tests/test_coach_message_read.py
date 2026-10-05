"""The coach's overall message reaches the speaker (founder 2026-09-29, Q1).

Pins: only a PUBLISHED Take counts, and only the Take on screen (N48.3
Q11 A: a coach's word belongs to its Take); the words come from the
published revision, never the session's draft field; a video-only message
is kept; nothing when the coach sent neither; a failed read is None; and the
Ideal Text enrichment serves it in the owner's journey section for the
document's latest Take.
"""
from __future__ import annotations

from pathlib import Path

from services import coach_message_read as cmr

ROOT = Path(__file__).resolve().parents[1]


class _Db:
    def __init__(self, sessions, revisions, fail=False):
        self.sessions, self.revisions, self.fail = sessions, revisions, fail

    def v2_get_session_by_id(self, sid):
        if self.fail:
            raise RuntimeError("down")
        return self.sessions.get(sid)

    def get_coach_review_revision(self, rid):
        return self.revisions.get(rid)


def _arc():
    return [
        {"id": "t1", "take_index": 1, "results_published_at": "2026-09-20T10:00:00Z"},
        {"id": "t2", "take_index": 2, "results_published_at": "2026-09-28T10:00:00Z"},
        {"id": "t3", "take_index": 3, "results_published_at": None},
    ]


def test_the_take_on_screen_and_its_published_words(monkeypatch):
    monkeypatch.setattr("services.coach_video_storage.refreshed_media_url",
                        lambda ref: f"https://media/{ref}")
    db = _Db(
        {"t2": {"id": "t2", "coach_review_revision_id": "r2",
                # a later draft on the session must NOT be served
                "coach_overall_message": "DRAFT, not sent",
                "coach_video_ref": "v2.mp4"}},
        {"r2": {"overall_message": " Let the pause breathe. ",
                "published_at": "2026-09-28T10:00:05Z"}})
    assert cmr.coach_message_for(db, _arc(), "t2") == {
        "text": "Let the pause breathe.",
        "video_url": "https://media/v2.mp4",
        "take_index": 2,
        "published_at": "2026-09-28T10:00:05Z",
        "take_session_id": "t2",
    }


def test_another_takes_message_never_stands_in(monkeypatch):
    """Q11 A: the page showing Take 3 (nothing published on it) gets no
    message, though Take 2 has one; the page showing Take 1 gets Take 1's
    own, not the later Take 2's."""
    monkeypatch.setattr("services.coach_video_storage.refreshed_media_url",
                        lambda ref: f"https://media/{ref}")
    db = _Db(
        {"t1": {"id": "t1", "coach_review_revision_id": "r1"},
         "t2": {"id": "t2", "coach_review_revision_id": "r2"}},
        {"r1": {"overall_message": "Take one words", "published_at": "p1"},
         "r2": {"overall_message": "Take two words", "published_at": "p2"}})
    assert cmr.coach_message_for(db, _arc(), "t3") is None
    assert cmr.coach_message_for(db, _arc(), "t1")["text"] == "Take one words"
    assert cmr.coach_message_for(db, _arc(), "t1")["take_session_id"] == "t1"


def test_no_take_on_screen_means_nothing():
    db = _Db({"t2": {"coach_review_revision_id": "r2"}},
             {"r2": {"overall_message": "words"}})
    assert cmr.coach_message_for(db, _arc(), None) is None
    assert cmr.coach_message_for(db, _arc(), "") is None
    assert cmr.coach_message_for(db, _arc(), "not-a-take-of-this-arc") is None


def test_nothing_published_means_nothing():
    arc = [{"id": "t1", "take_index": 1, "results_published_at": None}]
    assert cmr.coach_message_for(_Db({}, {}), arc, "t1") is None


def test_neither_words_nor_video_means_nothing():
    db = _Db({"t2": {"coach_review_revision_id": "r2"}},
             {"r2": {"overall_message": "   "}})
    assert cmr.coach_message_for(db, _arc(), "t2") is None


def test_video_only_is_kept(monkeypatch):
    monkeypatch.setattr("services.coach_video_storage.refreshed_media_url",
                        lambda ref: "https://media/x")
    db = _Db({"t2": {"coach_review_revision_id": None, "coach_video_ref": "x"}}, {})
    out = cmr.coach_message_for(db, _arc(), "t2")
    assert out["text"] is None and out["video_url"] == "https://media/x"


def test_a_failed_read_is_none():
    assert cmr.coach_message_for(_Db({}, {}, fail=True), _arc(), "t2") is None


def test_served_in_the_owners_journey_section():
    route = (ROOT / "routes" / "v2" / "explore_ideal_text.py").read_text()
    start = route.index("def journey_section():")
    section = route[start:route.index("take_count = int(", start)]
    # The Take on screen is the document's latest Take (N48.3 Q11 A).
    assert ('journey_payload(db, actor_id, arc_id, take_count, sessions, '
            'core.get("latest_take_session_id"))') in section
    assert ('"coach_message": coach_message_for(database, sessions, '
            'take_session_id)') in (
        ROOT / "services" / "coach_message_read.py").read_text()
    # The enrichment refuses a caller who does not own the project.
    head = route[route.index("def v2_explore_get_ideal_text_enrichment"):start]
    assert "if not owned:" in head
