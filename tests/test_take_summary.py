"""The closing summary after a Take's review (founder lock 2026-10-12,
section 3): one bubble per Take, no number or verdict, and the signed
journey copy when the written one breaks the rules or cannot be written."""
from services import take_summary
from services.journey_messages import _COPY


class _Db:
    def __init__(self, phone="+48600000000"):
        self.rows = {}
        self.phone = phone

    def get_v4_dark_frame(self, take):
        return {"blocks": [{"block_id": "b1", "snippet_ids": ["s1"]},
                           {"block_id": "b2", "snippet_ids": ["s2"]}]}

    def get_snippets_by_session(self, take):
        return [{"id": "s1", "transcript": "Our churn fell because we listened."},
                {"id": "s2", "transcript": "So here is what we do next."}]

    def get_lounge_message_by_client_id(self, user_id, client_id):
        return self.rows.get(client_id)

    def list_v4_willfidence_reads(self, take):
        return {"t1": [{"s": 0.5, "w": 0.6}],
                "t2": [{"block_id": "b1", "s": 0.7, "w": 0.6, "willfident": 0.42},
                       {"block_id": "b2", "s": 0.4, "w": 0.5, "willfident": 0.2}]}.get(take, [])

    def rewrite_lounge_message(self, user_id, client_id, body, metadata):
        self.rows[client_id] = {**self.rows[client_id], "body": body, "metadata": metadata}
        return self.rows[client_id]

    def insert_lounge_messages(self, user_id, messages):
        for m in messages:
            self.rows.setdefault(m["client_id"], m)
        return [self.rows[m["client_id"]] for m in messages]


TAKES = [{"id": "t1", "intake_context": {"topic": "Churn in Q3",
                                          "slides": [{"title": "Why churn fell"}]}},
         {"id": "t2"}]


def _run(db, monkeypatch, reply, body=None):
    seen = {}

    def fake(write):
        return write()

    def write(anchor, facts, **kw):
        seen["facts"], seen["signed"] = facts, kw.get("signed")
        return take_summary._clean(reply)

    monkeypatch.setattr("services.whatsapp_notify.whatsapp_state",
                        lambda _db, _user: {"phone": db.phone})
    monkeypatch.setattr(take_summary, "_under_authority", lambda _db, _take, w: fake(w))
    monkeypatch.setattr(take_summary, "write_summary", write)
    msg = take_summary.summary_message(db, user_id="u", arc_id="a", takes=TAKES,
                                       take_session_id="t2", body=body or {"practice": "better"})
    return msg, seen


def test_a_take_gets_one_summary_from_its_real_progress(monkeypatch):
    db = _Db()
    reply = "Your voice sounded surer than last time. Keep the endings you found."
    msg, seen = _run(db, monkeypatch, reply)
    assert msg["body"] == reply and msg["metadata"]["summary"] is True
    assert any("rose" in f for f in seen["facts"])
    again, _ = _run(db, monkeypatch, "Something else entirely. Twice over.")
    assert again["body"] == reply  # stored once per Take


def test_a_reply_with_a_number_falls_back_to_the_signed_copy(monkeypatch):
    msg, _ = _run(_Db(), monkeypatch, "You improved 20 percent. Great work.")
    assert msg["body"] == _COPY[2]
    assert msg["metadata"]["written"] is False


def test_a_coach_update_rewrites_the_summary_in_place_and_keeps_the_first(monkeypatch):
    """N80 (founder 2026-10-19): "see the earlier version" is the summary
    from before any coach note, however many notes follow."""
    db = _Db()
    first = "Your voice sounded surer than last time. Keep the endings you found."
    _run(db, monkeypatch, first)
    _run(db, monkeypatch, "Your coach wants the opening slower. Take your time.",
         {"coach_note": "Slow the opening."})
    later = "Your coach wants a breath before the price. Your voice is already surer."
    msg, _ = _run(db, monkeypatch, later, {"coach_note": "Breathe before the price."})
    assert msg["body"] == later
    assert msg["metadata"]["earlier"] == first and msg["metadata"]["coach_update"] is True
    assert len(db.rows) == 1


def test_a_shared_coach_word_rewrites_a_reviewed_take_once_per_word(monkeypatch):
    db = _Db()
    db.takes = type("T", (), {"get_arc_sessions": staticmethod(lambda arc: TAKES)})()
    db.v2_get_session_by_id = lambda take: {"user_id": "u", "arc_id": "a"}
    monkeypatch.setattr("services.parallel.start_scoped_thread", lambda run, name=None: run())
    _run(db, monkeypatch, "Your voice sounded surer than last time. Keep the endings you found.",
         {"coach_note": "Slow the opening.", "practice": "better"})
    later = "Your coach wants you to pause before the ask. The rest already sounds sure."
    monkeypatch.setattr(take_summary, "write_summary", lambda *a, **kw: later)
    take_summary.coach_update(db, "t2", "Pause before the ask.")
    row = next(iter(db.rows.values()))
    assert row["body"] == later and row["metadata"]["practice"] == "better"
    monkeypatch.setattr(take_summary, "write_summary", lambda *a, **kw: "Never written. Not again.")
    take_summary.coach_update(db, "t2", "Pause before the ask.")
    assert next(iter(db.rows.values()))["body"] == later


def test_a_coach_word_shared_after_the_review_is_its_own_bubble(monkeypatch):
    db = _Db()
    db.v2_get_session_by_id = lambda take: {"user_id": "u", "arc_id": "a"}
    db.takes = type("T", (), {"get_arc_sessions": staticmethod(lambda arc: TAKES)})()
    word = {"take_session_id": "t2", "text": "Breathe before the price.", "video_ref": None}
    assert take_summary.coach_update_message(db, **word) is None  # review not ended: the walk shows it
    _run(db, monkeypatch, "Your voice sounded surer than last time. Keep the endings you found.")
    msg = take_summary.coach_update_message(db, **word)
    assert msg["body"] == "Your coach\nBreathe before the price."
    assert msg["metadata"]["heading"] == "Later · from your coach" and msg["metadata"]["coach_update"] is True
    take_summary.coach_update_message(db, **word)
    assert len(db.rows) == 2  # the summary and one update, stored once


def test_the_summary_knows_the_talk_and_asks_for_whatsapp_once(monkeypatch):
    """Founder 2026-10-14: the bubble is about their talk (its title, its
    slides, what they said, their most confident moment), praises only
    through the signed lines, and a speaker without a WhatsApp number gets
    the Lounge's WhatsApp offer right after it."""
    db = _Db(phone=None)
    msg, seen = _run(db, monkeypatch, "Churn in Q3, nailed it! Another Take?")
    facts = " ".join(seen["facts"])
    assert 'called "Churn in Q3"' in facts and "Why churn fell" in facts
    assert 'most confident moment this Take: "Our churn fell because we listened."' in facts
    assert seen["signed"] and all(line in take_summary.line_bank_lines() for line in seen["signed"][:4])
    offers = [r for r in db.rows.values() if (r.get("metadata") or {}).get("offer") == "whatsapp"]
    assert msg["metadata"]["summary"] is True and len(offers) == 1


def test_a_reply_that_drifts_from_the_signed_lines_is_the_signed_copy():
    signed = ["You sounded like you really believed it this time!"]
    near = "Churn in Q3 was the talk! You sounded like you believed it this time! Another go?"
    assert take_summary._clean(near, signed, ("Churn in Q3",)) == near
    assert take_summary._clean("Churn in Q3 was the talk. You're a natural genius. Another go?",
                               signed, ("Churn in Q3",)) is None
    assert take_summary._clean("Fewer stops here than on Take 1. Lovely! Again?",
                               ["Fewer stops here than on Take 1."]) is not None

