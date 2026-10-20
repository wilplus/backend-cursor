"""
STORY    As a speaker, I want one short summary of my Take in words, about my
         own talk, so that I know what went well without a number or verdict.
OUTCOME
  O1  Each Take gets one stored summary, written from its real progress and
      about my talk (its title, slides, my most confident moment).
  O2  A summary with a number, praise that drifts from the approved lines,
      or a closing question (one action at a time: the next step is the last
      thing said, founder 2026-10-20) is replaced by the approved fallback
      copy.
  O3  A coach note rewrites the summary in place, keeping the first one
      however many notes follow, once per note; a note shared after the
      review is its own bubble, stored once.
  O4  From Take 2, a speaker without a WhatsApp number is asked for it
      after the Take's card, and the summary waits under the ask
      (services/after_take.py).
  O5  The summary and the ask after it sort under the walk's last step,
      even when my browser's clock runs ahead of the server's.
  O6  The summary can point back to what I said in an older Take (the same
      project first), never this Take, never a Take whose processing
      authorization is not in force; a failing or slow lookup leaves the
      summary as it was, and a number it brings in still falls back to the
      approved copy (founder 2026-10-20, step 3).
PROVES   O1 -> test_a_take_gets_one_summary_from_its_real_progress,
               test_the_summary_knows_the_talk_and_asks_for_whatsapp_once
         O2 -> test_a_reply_with_a_number_falls_back_to_the_signed_copy,
               test_a_reply_that_drifts_from_the_signed_lines_is_the_signed_copy,
               test_a_reply_that_ends_on_a_question_is_the_signed_copy
         O3 -> test_a_coach_update_rewrites_the_summary_in_place_and_keeps_the_first,
               test_a_shared_coach_word_rewrites_a_reviewed_take_once_per_word,
               test_a_coach_word_shared_after_the_review_is_its_own_bubble
         O4 -> test_the_summary_knows_the_talk_and_asks_for_whatsapp_once
         O5 -> test_the_summary_and_its_ask_sort_under_the_walk
         O6 -> test_the_summary_points_back_to_an_older_take_never_this_one,
               test_a_take_not_in_force_never_reaches_the_summary,
               test_a_failing_or_slow_lookup_leaves_the_summary_as_today,
               test_an_earlier_take_with_a_number_still_falls_back_to_the_signed_copy
WHY      Never-rule 1; founder lock 2026-10-12 (section 3) and 2026-10-14;
         founder 2026-10-20 (the chat keeps the order it shows; one action
         at a time).
"""
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

    def rewrite_lounge_message(self, user_id, client_id, body, metadata, at=None):
        self.rows[client_id] = {**self.rows[client_id], "body": body, "metadata": metadata,
                                **({"client_created_at": at} if at else {})}
        return self.rows[client_id]

    def insert_lounge_messages(self, user_id, messages):
        for m in messages:
            self.rows.setdefault(m["client_id"], m)
        return [self.rows[m["client_id"]] for m in messages]


TAKES = [{"id": "t1", "intake_context": {"topic": "Churn in Q3",
                                          "slides": [{"title": "Why churn fell"}]}},
         {"id": "t2"}]


def _run(db, monkeypatch, reply, body=None, takes=TAKES):
    seen = {}

    def fake(write):
        return write()

    def write(anchor, facts, **kw):
        seen["facts"], seen["signed"] = facts, kw.get("signed")
        return take_summary._clean(reply)

    monkeypatch.setattr("services.whatsapp_notify.whatsapp_state",
                        lambda _db, _user: {"phone": db.phone})
    monkeypatch.setattr("services.person_asks.next_for", lambda _user: None)
    monkeypatch.setattr(take_summary, "_under_authority", lambda _db, _take, w: fake(w))
    monkeypatch.setattr(take_summary, "write_summary", write)
    msg = take_summary.summary_message(db, user_id="u", arc_id="a", takes=takes,
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
    msg, seen = _run(db, monkeypatch, "Churn in Q3, nailed it! Now record take three.")
    facts = " ".join(seen["facts"])
    assert 'called "Churn in Q3"' in facts and "Why churn fell" in facts
    assert 'most confident moment this Take: "Our churn fell because we listened."' in facts
    assert seen["signed"] and all(line in take_summary.line_bank_lines() for line in seen["signed"][:4])
    offers = [r for r in db.rows.values() if (r.get("metadata") or {}).get("offer") == "whatsapp"]
    assert msg["metadata"]["summary"] is True and len(offers) == 1
    assert msg["metadata"]["held_for"] == "whatsapp"  # it waits under the ask


def test_the_summary_and_its_ask_sort_under_the_walk(monkeypatch):
    """The walk's steps carry the browser's time; an hour ahead here."""
    from datetime import datetime, timedelta, timezone
    ahead = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    db = _Db(phone=None)
    db.get_lounge_messages_page = lambda user_id, limit, before=None: [
        {"client_id": "step", "kind": "walk_step", "client_created_at": ahead}]
    msg, _ = _run(db, monkeypatch, "Churn in Q3, nailed it! Now record take three.")
    ask = next(r for r in db.rows.values() if (r.get("metadata") or {}).get("offer"))
    at = datetime.fromisoformat
    assert at(ahead) < at(msg["client_created_at"]) < at(ask["client_created_at"])


def test_a_reply_that_drifts_from_the_signed_lines_is_the_signed_copy():
    signed = ["You sounded like you really believed it this time!"]
    near = "Churn in Q3 was the talk! You sounded like you believed it this time! Go again."
    assert take_summary._clean(near, signed, ("Churn in Q3",)) == near
    assert take_summary._clean("Churn in Q3 was the talk. You're a natural genius. Go again.",
                               signed, ("Churn in Q3",)) is None
    assert take_summary._clean("Fewer stops here than on Take 1. Lovely! Record the next one ⬇️",
                               ["Fewer stops here than on Take 1."]) is not None


def test_a_reply_that_ends_on_a_question_is_the_signed_copy(monkeypatch):
    """Founder 2026-10-20: the Record button is under it, so a question
    would be a second thing to do."""
    msg, _ = _run(_Db(), monkeypatch, "Your voice sounded surer. Another Take? 🎉")
    assert msg["body"] == _COPY[2] and msg["metadata"]["written"] is False



class _History:
    """The speaker's Takes with their transcripts, newest first."""
    def __init__(self, rows):
        self.rows = rows

    def list_speaker_take_transcripts(self, user_id, *, limit):
        if self.rows is None:
            raise RuntimeError("database down")
        return self.rows[:limit]


def _said(take_id, index, words, at, arc="a", owner="p-live"):
    return {"id": take_id, "user_id": "u", "arc_id": arc, "take_index": index,
            "created_at": at, "analysis_state": "ready", "owner_principal_id": owner,
            "slide_transcripts": [{"index": 0, "transcript": words}]}


ARC = [{**TAKES[0], "created_at": "2026-10-18T10:00:00+00:00"},
       {"id": "t2", "created_at": "2026-10-19T10:00:00+00:00"}]


def _earlier(seen):
    return next((f for f in seen["facts"] if f.startswith("What they said in earlier Takes")), None)


def test_the_summary_points_back_to_an_older_take_never_this_one(monkeypatch):
    """Step 3 (founder 2026-10-20): the summary hears what the speaker said
    in an older Take, matched on what they said now, the same project
    first; never this Take (already in the prompt) nor a later one."""
    db = _Db()
    db.client = None
    db.takes = _History([
        _said("t3", 3, "Later: churn fell because we listened again", "2026-10-20T10:00:00+00:00"),
        _said("t2", 2, "Our churn fell because we listened.", "2026-10-19T10:00:00+00:00"),
        _said("x1", 1, "Churn fell and we listened to the panel", "2026-10-18T12:00:00+00:00",
              arc="b"),
        _said("t1", 1, "Churn fell, I rushed it, we listened", "2026-10-18T10:00:00+00:00")])
    _, seen = _run(db, monkeypatch, "Churn in Q3, nailed it! Now record take three.", takes=ARC)
    fact = _earlier(seen)
    assert fact.endswith('Take 1: "Churn fell, I rushed it, we listened"; '
                         'Take 1: "Churn fell and we listened to the panel"')
    assert "Later" not in fact and "Our churn fell because we listened." not in fact


def test_a_take_not_in_force_never_reaches_the_summary(monkeypatch):
    from services.processing_authorization import ProcessingAuthorizationService as Service
    monkeypatch.setenv("PLF1_PROCESSING_AUTHORIZATION_MODE", "enforce")
    monkeypatch.setattr(Service, "resolve_acquisition_principal", lambda self, owner, **kw: owner)
    monkeypatch.setattr(Service, "status", lambda self, principal: (
        {"authorized": True, "pooled_learning_eligible": False} if principal == "p-live"
        else {"authorized": False, "code": "PROCESSING_AUTHORIZATION_WITHDRAWN"}))
    db = _Db()
    db.client = None
    db.takes = _History([_said("t1", 1, "Churn fell, I rushed it, we listened",
                               "2026-10-18T10:00:00+00:00", owner="p-gone")])
    _, seen = _run(db, monkeypatch, "Churn in Q3, nailed it! Now record take three.", takes=ARC)
    assert _earlier(seen) is None


def test_a_failing_or_slow_lookup_leaves_the_summary_as_today(monkeypatch):
    import time
    from services import speaker_lookup
    reply = "Your churn talk, nailed it! Now record the next take."
    _, today = _run(_Db(), monkeypatch, reply, takes=ARC)
    broken = _Db()
    broken.takes = _History(None)
    msg, seen = _run(broken, monkeypatch, reply, takes=ARC)
    assert seen["facts"] == today["facts"] and msg["body"] == reply
    monkeypatch.setattr(take_summary, "_EARLIER_BUDGET", 0.05)
    monkeypatch.setattr(speaker_lookup, "earlier_takes",
                        lambda *a, **kw: time.sleep(0.5) or [speaker_lookup.Snippet(
                            "Take 1 transcript", "too late", "take", "")])
    started = time.monotonic()
    _, slow = _run(_Db(), monkeypatch, reply, takes=ARC)
    assert slow["facts"] == today["facts"] and time.monotonic() - started < 0.4


def test_an_earlier_take_with_a_number_still_falls_back_to_the_signed_copy(monkeypatch):
    db = _Db()
    db.client = None
    db.takes = _History([_said("t1", 1, "Churn fell twenty percent, from 30 to 10",
                               "2026-10-18T10:00:00+00:00")])
    msg, seen = _run(db, monkeypatch, "In Take 1 churn fell from 30 to 10. Record the next one.",
                     takes=ARC)
    assert "from 30 to 10" in _earlier(seen)
    assert msg["body"] == _COPY[2] and msg["metadata"]["written"] is False
