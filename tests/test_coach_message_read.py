"""
STORY    As a speaker, I want my coach's word for a Take to show on that Take
         only, to count as new until I have watched it, from whichever door
         I came in, and to be new again when the coach changes it, so that
         I never miss it, never meet it on the wrong Take, and am never
         asked twice.
OUTCOME
  O1  The word is new before I ever watched it.
  O2  Once I watched it (the WhatsApp or email link, the dot card, the
      bubble), it is no longer new.
  O3  A new or removed video with the same words makes it new again.
  O4  The journey adds one yes/no to the message, nothing else.
  O5  With Take 3 on screen and a word on Take 2 only, no coach message is
      served and Take 2's word is never read for it (story 1).
  O6  A word on Take 3 with Take 3 on screen is served, naming Take 3 and
      its index (story 2).
  O7  A word the coach leaves on Take 1 after Take 2 was recorded is not
      served on Take 2; it reaches me as its own "Later · from your coach"
      bubble for Take 1 (story 3; WhatsApp: test_whatsapp_number.py).
  O8  No word on the Take serves nothing; a failed read serves nothing and
      never raises (stories 6 and 7).
  O9  That late word on Take 1, sent to me as a link (the WhatsApp and the
      email), names Take 1, and opening it serves Take 1's word; a link
      naming a Take that is not mine serves the Take on screen's instead
      (story 3, founder 2026-10-21: the coach's link opens the coach's
      feedback).
PROVES   O1, O2, O3, O4 -> test_the_coach_s_word_is_new_until_watched_and_again_after_a_new_video
         O5 -> test_a_word_on_take_2_is_not_served_on_take_3
         O6 -> test_the_word_on_the_take_on_screen_is_served
         O7 -> test_a_late_word_on_take_1_goes_to_its_lounge_bubble_not_take_2
         O8 -> test_no_word_or_a_failed_read_serves_nothing
         O9 -> test_a_late_word_on_take_1_sent_as_a_link_opens_take_1_s_word
WHY      Founder 2026-10-19, N80 (D4, D7), approved two-phone prototype
         https://claude.ai/artifact/APk56PLZt6o6Cx9qUMKkuk. Founder
         2026-10-18, N77 (contract 35g-6, superseding N48.3 Q11 A's
         earlier-Take fallback), landed with N94 on 2026-10-21; its links
         name the word's Take (founder, 2026-10-21).
"""
from urllib.parse import parse_qs, urlsplit

from services import take_summary
from services.coach_feedback_email import feedback_url
from services.coach_message_read import coach_message_for, journey_payload
from services.ideal_text_enrichment import section_readers
from services.whatsapp_notify import feedback_path

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


T1, T2, T3 = (f"{n}{n}{n}{n}{n}{n}{n}{n}-0000-4000-8000-000000000000" for n in (1, 2, 3))
TAKES = [{"id": T1, "take_index": 1}, {"id": T2, "take_index": 2},
         {"id": T3, "take_index": 3}]


class _Words:
    """Shared Take words by Take; records which Takes the read asked for."""

    def __init__(self, words=(), fail=False):
        self.words = {w: {"take_session_id": w, "coach_id": "c1",
                          "text": f"Word on {w[:1]}.", "video_ref": None,
                          "shared_at": "2026-10-20T10:00:00+00:00",
                          "updated_at": "2026-10-20T10:00:00+00:00"} for w in words}
        self.fail, self.asked = fail, []

    def list_shared_coach_take_words(self, takes):
        self.asked.extend(takes)
        if self.fail:
            raise RuntimeError("database down")
        return [dict(self.words[t]) for t in takes if t in self.words]

    def v2_get_session_by_id(self, take):
        if self.fail:
            raise RuntimeError("database down")
        return {"id": take, "user_id": "me", "arc_id": "arc1"}


def test_a_word_on_take_2_is_not_served_on_take_3():
    db = _Words([T2])
    assert coach_message_for(db, TAKES, T3) is None
    assert T2 not in db.asked


def test_the_word_on_the_take_on_screen_is_served():
    message = coach_message_for(_Words([T3]), TAKES, T3)
    assert message["text"] == "Word on 3."
    assert message["take_session_id"] == T3 and message["take_index"] == 3


def test_a_late_word_on_take_1_goes_to_its_lounge_bubble_not_take_2():
    db = _Words([T1])
    assert coach_message_for(db, TAKES[:2], T2) is None
    # The coach's share writes the word as its own bubble (coach_take_word.
    # _tell_the_speaker -> take_summary.coach_update_message), on Take 1.
    db.rows = []
    db.takes = type("T", (), {"get_arc_sessions": staticmethod(lambda arc: TAKES[:2])})()
    db.get_lounge_messages_page = lambda user, limit: []
    db.insert_lounge_messages = lambda user, rows: db.rows.extend(rows) or rows
    bubble = take_summary.coach_update_message(
        db, take_session_id=T1, text="Word on 1.", video_ref=None)
    assert bubble["body"] == "Your coach\nWord on 1."
    assert bubble["metadata"]["heading"] == "Later · from your coach"
    assert bubble["metadata"]["take_session_id"] == T1
    assert bubble["metadata"]["take_index"] == 1


def test_no_word_or_a_failed_read_serves_nothing():
    assert coach_message_for(_Words(), TAKES, T3) is None
    published = [dict(t, results_published_at="2026-10-20T09:00:00+00:00") for t in TAKES]
    assert coach_message_for(_Words([T3], fail=True), published, T3) is None


def _opened(db, sessions, link):
    """What the Ideal Text's journey serves for a link's `take`, with Take 2
    on screen (the enrichment section the coach-only walk reads)."""
    take = parse_qs(urlsplit(link).query).get("take", [None])[0]
    snapshot = {"payload": {"latest_take_session_id": T2, "take_count": 2}}
    readers = section_readers(db, arc_id="arc1", actor_id="me", sessions=sessions,
                              selected=snapshot, snapshot_id="snap", deps=None,
                              coach_take=take)
    return readers["journey"]()["coach_message"]


def test_a_late_word_on_take_1_sent_as_a_link_opens_take_1_s_word():
    mine = [dict(t, user_id="me") for t in TAKES[:2]]
    for link in (feedback_path("arc1", T1), feedback_url("arc1", T1)):
        message = _opened(_Words([T1]), mine, link)
        assert message["text"] == "Word on 1."
        assert message["take_session_id"] == T1 and message["take_index"] == 1
    # Not my Take: the link opens the Take on screen, which has no word.
    theirs = [dict(TAKES[0], user_id="someone-else"), dict(TAKES[1], user_id="me")]
    db = _Words([T1])
    assert _opened(db, theirs, feedback_path("arc1", T1)) is None
    assert T1 not in db.asked
