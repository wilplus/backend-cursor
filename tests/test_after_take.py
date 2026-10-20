"""
STORY    As a speaker, after a Take I want one thing to do at a time: the
         Take's card, at most one ask, then the message with "Record Take N",
         so that a question never competes with recording again.
OUTCOME
  O1  After Take 1 the only ask is "Did this help?", and only when the Take
      looks off: never WhatsApp, never an ask from the CEO panel, even
      without a number.
  O2  From Take 2 the one ask is the CEO panel's when there is one, else
      WhatsApp (at most twice), else the home screen (once, where the phone
      can add it), else the question; nothing asked, nothing waits.
  O3  The message waits for the ask and comes under whatever closed it: a
      typed turn, under Will's reply; "Yes", tapped or typed, glad, as the
      reply; a reply that opens a form keeps it waiting.
  O4  A message still waiting when a newer Take is written shows where it
      stands.
PROVES   O1 -> test_after_take_one_only_the_question_and_only_when_it_looks_off
         O2 -> test_from_take_two_the_ceo_ask_then_whatsapp_then_home_screen_then_the_question
         O3 -> test_the_message_comes_under_what_closed_the_ask
         O4 -> test_an_older_waiting_message_shows_where_it_stands
WHY      Founder 2026-10-20: "one action at a time"; details chosen on the
         decisions page the same day.
"""
from services import after_take, chat_query, feedback_check

SUMMARY = "Your first take is in 🎉\n\nNow record take 2 with your helper words ⬇️"


class _Db:
    def __init__(self):
        self.thread = {}
        self.checks = {}

    def insert_lounge_messages(self, user_id, rows):
        for r in rows:
            self.thread.setdefault(r["client_id"], dict(r))
        return [self.thread[r["client_id"]] for r in rows]

    def get_lounge_messages_page(self, user_id, limit=50, before=None):
        return list(reversed(self.thread.values()))[:limit]  # newest first

    def get_lounge_message_by_client_id(self, user_id, client_id):
        return self.thread.get(client_id)

    def rewrite_lounge_message(self, user_id, client_id, body, metadata, at=None):
        row = self.thread.pop(client_id) if at else self.thread[client_id]
        row.update(body=body, metadata=metadata, **({"client_created_at": at} if at else {}))
        self.thread[client_id] = row
        return row

    def save_take_feedback_check(self, row):
        key = (row["user_id"], row["take_session_id"])
        self.checks[key] = {**self.checks.get(key, {}), **row}
        return True

    def get_take_feedback_check(self, user_id, take):
        return self.checks.get((user_id, take))

    def bodies(self):
        return [r["body"] for r in self.thread.values()]


def _world(monkeypatch, *, phone=None, admin=None):
    monkeypatch.setattr("services.whatsapp_notify.whatsapp_state", lambda _db, _u: {"phone": phone})
    monkeypatch.setattr("services.person_asks.next_for", lambda _u: admin)


def _waiting(db, take="take-1", ask="feedback_check"):
    """The summary's batch as take_summary writes it: the held message, then its ask."""
    db.insert_lounge_messages("u", [{
        "client_id": f"summary-{take}", "role": "bot", "kind": "cadence", "body": SUMMARY,
        "metadata": {"summary": True, "held_for": ask, "take_session_id": take},
        "client_created_at": "2026-10-20T10:00:00+00:00"}]
        + after_take.ask_rows(db, ask, user_id="u", arc_id="arc", take=take,
                              at="2026-10-20T10:00:00.001000+00:00"))


def _typed(db, monkeypatch, question, answer="Slow the first slide down."):
    """One typed turn through the chat's chain, persisted as the route does."""
    monkeypatch.setattr("services.db.db", db, raising=False)
    monkeypatch.setattr(chat_query, "_librarian", lambda *a, **k: ({"answer": answer}, "faq"))
    monkeypatch.setattr(chat_query, "thread_history", lambda *a, **k: [])
    return chat_query.answer_chat(
        db, user_id="u", question=question, history=[], context=None, app_config=object(),
        finalize=lambda resp, intent: chat_query.finish_chat_turn(
            db, resp, user_id="u", question=question, persist_thread=True,
            user_client_id=None, user_created_at=None, intent=intent))


def test_after_take_one_only_the_question_and_only_when_it_looks_off(monkeypatch):
    _world(monkeypatch, phone=None, admin={"id": "a1", "kind": "promo"})
    db = _Db()
    assert after_take.choose(db, "u", take_index=1, off=True, can_install=True) == "feedback_check"
    assert after_take.choose(db, "u", take_index=1, off=False, can_install=True) is None


def test_from_take_two_the_ceo_ask_then_whatsapp_then_home_screen_then_the_question(monkeypatch):
    db = _Db()
    _world(monkeypatch, phone=None, admin={"id": "a1", "kind": "promo"})
    assert after_take.choose(db, "u", take_index=2, off=True) == "admin"

    _world(monkeypatch, phone=None, admin=None)
    assert after_take.choose(db, "u", take_index=2, off=True) == "whatsapp"
    _waiting(db, "take-2", "whatsapp")
    _waiting(db, "take-3", "whatsapp")
    assert after_take.choose(db, "u", take_index=4, off=True, can_install=True) == "install"
    _waiting(db, "take-4", "install")
    assert after_take.choose(db, "u", take_index=5, off=True, can_install=True) == "feedback_check"

    _world(monkeypatch, phone="+447700900461", admin=None)
    assert after_take.choose(_Db(), "u", take_index=2, off=False) is None


def test_the_message_comes_under_what_closed_the_ask(monkeypatch):
    db = _Db()
    _waiting(db)
    _typed(db, monkeypatch, "How do I sound calmer?")
    assert db.bodies()[-2:] == ["Slow the first slide down.", SUMMARY]
    assert after_take.held(db, "u") is None

    glad = _Db()
    _waiting(glad)
    resp = _typed(glad, monkeypatch, "yes")
    said = "Your first take is in 🎉\n\nWe're glad it helped you. Now record take 2 with your helper words ⬇️"
    assert resp["answer"] == said and glad.bodies()[-2:] == ["yes", said]  # no other reply

    tap = _Db()
    _waiting(tap)
    rows = feedback_check.answer(tap, user_id="u", arc_id="arc", take_session_id="take-1",
                                 choice="yes")
    assert [r["body"] for r in rows] == ["Yes", said] and tap.bodies()[-1] == said

    form = _Db()
    _world(monkeypatch, phone=None)
    _waiting(form, "take-2", "whatsapp")
    resp = _typed(form, monkeypatch, "07700 900461")  # no country code: the form opens
    assert resp.get("offer") == "whatsapp" and after_take.held(form, "u") is not None


def test_an_older_waiting_message_shows_where_it_stands():
    db = _Db()
    _waiting(db)
    after_take.release_older(db, "u")
    assert db.bodies()[0] == SUMMARY and after_take.held(db, "u") is None
    assert feedback_check.COPY["ask"] in db.bodies()
