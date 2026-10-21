"""
STORY    As a speaker, I want my coach's words and video to reach my page
         when the coach shares them, not when I next answer something, so
         that a video sent with the feedback is there (founder 2026-10-21:
         "the video was sent too with the coach feedback and didn't pass
         through").
OUTCOME
  O1  A stored bake serves the coach's answer as it stands now: words
      shared after the bake arrive, a video added after it is there with a
      fresh link, and an answer the coach withdrew since the bake is gone.
  O2  A coach's answer asks for the document to be baked again, off the
      coach's request; a broken queue never fails the answer.
PROVES   O1 -> test_a_stored_bake_serves_the_coachs_answer_and_video_as_they_stand
         O2 -> test_a_coachs_answer_asks_for_a_rebake_and_a_broken_queue_never_fails_it
WHY      Founder 2026-10-21. The bake is retired only by the speaker's own
         writes (`ideal_text_feedback_surface_touched_at_v1`), never by the
         coach's, and a signed video link in it went dark after six hours.
"""
from __future__ import annotations

from services import exercise_coach_requests as requests
from services import ideal_text_feedback_bake as bake

ARC, ACTOR, SNAPSHOT, TAKE = "arc-1", "actor-1", "snap-1", "take-1"
SHARED = "2026-10-21T04:00:00+00:00"


class _Db:
    def __init__(self, stored, live):
        self.stored = stored
        self.live = live

    def read_ideal_text_feedback_bake(self, arc_id, actor_id, snapshot_id):
        return self.stored

    def list_exercise_coach_requests_for_take(self, take_session_id):
        return self.live if take_session_id == TAKE else {}


def _row(snippet_id, **fields):
    return {"id": f"cand-{snippet_id}", "source": "confident_voice",
            "take_session_id": TAKE, "snippet_id": snippet_id, **fields}


def test_a_stored_bake_serves_the_coachs_answer_and_video_as_they_stand(monkeypatch):
    monkeypatch.setattr(bake, "_bake_enabled", lambda: True)
    monkeypatch.setattr("services.coach_video_storage.refreshed_media_url",
                        lambda ref: f"https://signed/{ref.rsplit('/', 1)[-1]}")
    stored = {"changes": [
        # Baked with the words only; the coach added the video after.
        _row("s1", coach_answer={"kind": "note", "text": "Old words."},
             coach_request={"status": "answered", "kind": "error"}),
        # Baked while the coach had not answered; they have since.
        _row("s2", coach_request={"status": "open", "kind": "praise"}),
        # Baked with an answer the coach has since taken back.
        _row("s3", coach_answer={"kind": "line", "text": "Gone."},
             coach_request={"status": "answered", "kind": "praise"}),
    ], "style_changes": []}
    live = {
        "s1": {"resolution": "note_written", "shared_at": SHARED, "kind": "error",
               "answer_text": "If you are not interested, the crowd won't be either.",
               "answer_video_ref": "s3://coach-media/coach-answers/u/r/clip.mp4"},
        "s2": {"resolution": "line_written", "shared_at": SHARED, "kind": "praise",
               "answer_text": "That ending landed."},
        "s3": {"resolution": "line_written", "shared_at": None, "kind": "praise",
               "answer_text": "Gone."},
    }
    block = bake.changes_block_for(_Db(stored, live), ARC, ACTOR, SNAPSHOT, {})
    by = {row["snippet_id"]: row for row in block["changes"]}
    assert by["s1"]["coach_answer"] == {
        "kind": "note", "text": "If you are not interested, the crowd won't be either.",
        "video_url": "https://signed/clip.mp4"}
    assert by["s2"]["coach_answer"] == {"kind": "line", "text": "That ending landed."}
    assert by["s2"]["coach_request"]["status"] == "answered"
    assert "coach_answer" not in by["s3"]
    assert by["s3"]["coach_request"]["status"] == "open"
    # The stored block itself is left as it was.
    assert stored["changes"][0]["coach_answer"] == {"kind": "note", "text": "Old words."}


class _AnswerDb:
    def __init__(self):
        self.request = {"id": "req-1", "take_session_id": TAKE, "snippet_id": "s1",
                        "owner_user_id": "u1", "kind": "error"}

    def resolve_exercise_coach_request(self, **kwargs):
        return {**self.request, "resolution": kwargs["resolution"],
                "answer_text": kwargs.get("answer_text"),
                "shared_at": SHARED if kwargs["share"] else None}

    def v2_get_session_by_id(self, session_id):
        return {"id": session_id, "arc_id": ARC, "user_id": "u1"}


def test_a_coachs_answer_asks_for_a_rebake_and_a_broken_queue_never_fails_it(monkeypatch):
    asked: list = []
    monkeypatch.setattr(requests, "_file_answer", lambda *a, **k: None)
    monkeypatch.setattr(requests, "_tell_the_speaker", lambda *a, **k: None)
    monkeypatch.setattr(requests, "coach_request_payload", lambda resolved, _db: resolved)
    monkeypatch.setattr(bake, "request_rebake_for_take", lambda session: asked.append(session) or True)
    db = _AnswerDb()
    body = {"resolution": "note_written", "answer_text": "Land it.", "share_with_user": True}
    status, payload = requests.resolve_request(db, db.request, body, "coach-1")
    assert status == 200 and payload["request"]["shared_at"] == SHARED
    assert [s["arc_id"] for s in asked] == [ARC]

    def broken(_session):
        raise RuntimeError("no queue")
    monkeypatch.setattr(bake, "request_rebake_for_take", broken)
    status, _payload = requests.resolve_request(db, db.request, body, "coach-1")
    assert status == 200
