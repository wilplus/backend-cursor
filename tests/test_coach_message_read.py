"""
STORY    As a speaker, I want my coach's word for a Take to count as new
         until I have watched it, from whichever door I came in, and to be
         new again when the coach changes it, so that I never miss it and
         am never asked twice.
OUTCOME
  O1  The word is new before I ever watched it.
  O2  Once I watched it (the WhatsApp or email link, the dot card, the
      bubble), it is no longer new.
  O3  A new or removed video with the same words makes it new again.
  O4  The journey adds one yes/no to the message, nothing else.
PROVES   O1, O2, O3, O4 -> test_the_coach_s_word_is_new_until_watched_and_again_after_a_new_video
WHY      Founder 2026-10-19, N80 (D4, D7), approved two-phone prototype
         https://claude.ai/artifact/APk56PLZt6o6Cx9qUMKkuk.
"""
from services.coach_message_read import journey_payload

TAKE = "33333333-3333-4333-8333-333333333333"


class _Db:
    def __init__(self):
        self.word = {"take_session_id": TAKE, "coach_id": "c1",
                     "text": "Breathe before the price.",
                     "video_ref": f"s3://coach-videos/coach-feedback/{TAKE}/k1.webm",
                     "shared_at": "2026-10-19T10:00:00+00:00",
                     "updated_at": "2026-10-19T10:00:00+00:00"}
        self.seen = {}

    def get_lounge_message_by_client_id(self, user_id, client_id):
        return None

    def list_shared_coach_take_words(self, takes):
        return [dict(self.word)] if TAKE in takes else []

    def list_coach_take_word_seen(self, user_id, takes):
        assert user_id == "me" and takes == [TAKE]
        return dict(self.seen)


def _message(db):
    return journey_payload(db, "me", "arc1", 2, [{"id": TAKE, "take_index": 2}],
                           TAKE)["coach_message"]


def test_the_coach_s_word_is_new_until_watched_and_again_after_a_new_video(monkeypatch):
    monkeypatch.setattr("services.coach_video_storage.refreshed_media_url",
                        lambda ref: f"signed-{ref}")
    db = _Db()
    first = _message(db)
    assert first["unseen"] is True
    assert set(first) == {"text", "video_url", "take_index", "published_at",
                          "take_session_id", "unseen"}

    db.seen = {TAKE: "2026-10-19T11:00:00+00:00"}
    assert _message(db)["unseen"] is False

    db.word.update(video_ref=None, updated_at="2026-10-19T12:00:00+00:00")
    again = _message(db)
    assert again["unseen"] is True and again["video_url"] is None
    assert again["text"] == "Breathe before the price."
