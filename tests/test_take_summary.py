"""The closing summary after a Take's review (founder lock 2026-10-12,
section 3): one bubble per Take, no number or verdict, and the signed
journey copy when the written one breaks the rules or cannot be written."""
from services import take_summary
from services.journey_messages import _COPY


class _Db:
    def __init__(self):
        self.rows = {}

    def get_lounge_message_by_client_id(self, user_id, client_id):
        return self.rows.get(client_id)

    def list_v4_willfidence_reads(self, take):
        return {"t1": [{"s": 0.5, "w": 0.6}], "t2": [{"s": 0.7, "w": 0.6}]}.get(take, [])

    def rewrite_lounge_message(self, user_id, client_id, body, metadata):
        self.rows[client_id] = {**self.rows[client_id], "body": body, "metadata": metadata}
        return self.rows[client_id]

    def insert_lounge_messages(self, user_id, messages):
        for m in messages:
            self.rows.setdefault(m["client_id"], m)
        return [self.rows[m["client_id"]] for m in messages]


TAKES = [{"id": "t1"}, {"id": "t2"}]


def _run(db, monkeypatch, reply, body=None):
    seen = {}

    def fake(write):
        return write()

    def write(anchor, facts, **kw):
        seen["facts"] = facts
        return take_summary._clean(reply)

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


def test_a_coach_update_rewrites_the_summary_in_place_and_keeps_the_earlier(monkeypatch):
    db = _Db()
    first = "Your voice sounded surer than last time. Keep the endings you found."
    _run(db, monkeypatch, first)
    later = "Your coach wants the opening slower. Your voice is already surer, so take your time."
    msg, _ = _run(db, monkeypatch, later, {"coach_note": "Slow the opening."})
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
