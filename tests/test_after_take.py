"""
STORY    As a speaker, after a Take I want one thing to do at a time: the
         Take's card and its summary, then each ask on its own with Will's
         words leading into it, and only then "practice makes perfect" with
         "Record Take N", so that nothing competes with the walk or with
         recording again (founder 2026-10-20, N89).
OUTCOME
  O1  One ask after each Take, the first that waits (founder 2026-10-26,
      N189; was two, N94). After Take 1 that is WhatsApp when I left no
      number (N171), else Will's question when he has one, else "Did this
      help?" when the Take looks off; never an ask from the CEO panel or
      the home screen on Take 1.
  O2  From Take 2 the order is the CEO panel's ask, WhatsApp (at most twice
      in all), the home screen (once, where the phone can add it), Will's
      question, "Did this help?"; the first that waits comes and the others
      wait for a later Take; nothing comes when nothing applies.
  O3  The asks come one at a time, each under whatever closed the one
      before: a typed turn, under Will's reply; "Yes", tapped or typed,
      under "We're glad it helped you."; a reply that opens a form keeps the
      ask open. An ask that no longer applies is skipped. After the last,
      the closing message comes, with its words.
  O4  A message still waiting when a newer Take is written shows where it
      stands.
  O5  After a distressed message the chat's safety reply comes and the asks
      wait: nothing lands under it until I write again (founder 2026-10-21,
      N94).
  O6  The plan's lines after a practice day's Take ("That's your 15
      minutes for today.") wait for the ask: the ask stays the newest
      bubble, so its answers stay; after my answer come the lines, then
      the closing message with "Record Take N", last (founder 2026-10-30).
PROVES   O1 -> test_after_take_one_the_whatsapp_ask_else_will_else_the_question
         O2 -> test_from_take_two_one_ask_ceo_ask_whatsapp_home_screen_will_the_question
         O3 -> test_each_ask_comes_under_what_closed_the_one_before_then_the_closing_message
         O4 -> test_an_older_waiting_message_shows_where_it_stands
         O5 -> test_after_a_distressed_message_the_asks_wait_until_i_write_again
         O6 -> test_the_plans_lines_wait_for_the_ask
WHY      Founder 2026-10-20: "one action at a time", then, after checking the
         app: the summary without the CTA, Will's liaison before each ask,
         "Look, practice makes perfect…" and the CTA last.
"""
from services import after_take, chat_query, feedback_check

SUMMARY = "Your first take is in 🎉"
AT = "2026-10-20T10:00:00+00:00"


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

    def drawn(self):
        """The thread as the Lounge draws it: the held closing message left out."""
        return [r["body"] for r in self.thread.values()
                if not (r.get("metadata") or {}).get("held_for")]


def _world(monkeypatch, *, phone=None, admin=None):
    monkeypatch.setattr("services.whatsapp_notify.whatsapp_state", lambda _db, _u: {"phone": phone})
    monkeypatch.setattr("services.person_asks.next_for", lambda _u: admin)


def _waiting(db, take="take-1", asks=("feedback_check",), lead_ins=None):
    """The summary's batch as take_summary writes it: the summary, the closing
    message held behind the chain, then the first ask."""
    closing = after_take.closing_row(user_id="u", arc_id="arc", take_index=1, take=take,
                                     at="2026-10-20T10:00:00.001000+00:00", asks=list(asks),
                                     lead_ins=lead_ins or {})
    db.insert_lounge_messages("u", [{
        "client_id": f"summary-{take}", "role": "bot", "kind": "cadence", "body": SUMMARY,
        "metadata": {"summary": True, "take_session_id": take}, "client_created_at": AT},
        closing] + after_take.rows_for(db, "u", closing["metadata"], asks[0],
                                       "2026-10-20T10:00:00.002000+00:00"))
    return closing


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


def test_after_take_one_the_whatsapp_ask_else_will_else_the_question(monkeypatch):
    _world(monkeypatch, phone=None, admin={"id": "a1", "kind": "promo"})
    db = _Db()
    # No number: WhatsApp is Take 1's one ask; the CEO panel's ask and the
    # home screen never come on Take 1.
    assert after_take.chain(db, "u", take_index=1, off=True, can_install=True, will=True) == ["whatsapp"]
    _world(monkeypatch, phone="+447700900461", admin={"id": "a1", "kind": "promo"})
    assert after_take.chain(db, "u", take_index=1, off=True, can_install=True, will=True) == ["will_question"]
    assert after_take.chain(db, "u", take_index=1, off=True, can_install=True) == ["feedback_check"]
    assert after_take.chain(db, "u", take_index=1, off=False, can_install=True) == []


def test_from_take_two_one_ask_ceo_ask_whatsapp_home_screen_will_the_question(monkeypatch):
    db = _Db()
    _world(monkeypatch, phone=None, admin={"id": "a1", "kind": "promo"})
    # Five would wait: the first comes, the others wait (N189).
    assert after_take.chain(db, "u", take_index=2, off=True, can_install=True, will=True) == ["admin"]
    _world(monkeypatch, phone=None, admin=None)
    assert after_take.chain(db, "u", take_index=2, off=True, can_install=True, will=True) == ["whatsapp"]

    _waiting(db, "take-1", ["whatsapp"])
    _waiting(db, "take-2", ["whatsapp"])
    # Asked twice: WhatsApp no longer comes; then the home screen, once.
    assert after_take.chain(db, "u", take_index=3, off=True, can_install=True, will=True) == ["install"]
    _waiting(db, "take-3", ["install"])
    assert after_take.chain(db, "u", take_index=4, off=True, can_install=True, will=True) == ["will_question"]
    assert after_take.chain(db, "u", take_index=4, off=True, can_install=True) == ["feedback_check"]

    _world(monkeypatch, phone="+447700900461", admin=None)
    assert after_take.chain(_Db(), "u", take_index=2, off=False) == []


def test_each_ask_comes_under_what_closed_the_one_before_then_the_closing_message(monkeypatch):
    _world(monkeypatch, phone=None, admin=None)
    db = _Db()
    # Take 2: WhatsApp with Will's lead-in, then "Did this help?", then the
    # closing message. The summary is drawn at once, without the CTA.
    lead = "You kept every ending this time. Want a WhatsApp when your coach replies? Add your number."
    _waiting(db, "take-2", ["whatsapp", "feedback_check"], lead_ins={"whatsapp": lead})
    assert db.drawn() == [SUMMARY, lead]
    assert after_take.held(db, "u")["metadata"]["chain"] == ["feedback_check"]

    # The WhatsApp form closes (the Lounge's POST): the question comes, the
    # closing message still waits.
    rows = after_take.release(db, "u")
    assert [r["body"] for r in rows] == [feedback_check.COPY["ask"]]
    assert db.drawn() == [SUMMARY, lead, feedback_check.COPY["ask"]]
    assert after_take.held(db, "u")["metadata"]["held_for"] == "feedback_check"

    # "Yes": the founder's sentence, then nothing is left and the closing
    # message comes, with its words, under it.
    rows = feedback_check.answer(db, user_id="u", arc_id="arc", take_session_id="take-2", choice="yes")
    assert [r["body"] for r in rows] == ["Yes", after_take.GLAD, after_take.NEXT_TAKE]
    assert db.drawn()[-3:] == ["Yes", after_take.GLAD, after_take.NEXT_TAKE]
    assert after_take.held(db, "u") is None

    # A typed turn that passes the ask advances the chain under Will's reply.
    typed = _Db()
    _waiting(typed, "take-1", ["feedback_check"])
    _typed(typed, monkeypatch, "How do I sound calmer?")
    assert typed.drawn()[-2:] == ["Slow the first slide down.", after_take.NEXT_TAKE]
    assert after_take.held(typed, "u") is None

    # A typed "yes" is answered with the founder's sentence, the chain under it.
    glad = _Db()
    _waiting(glad, "take-1", ["feedback_check"])
    resp = _typed(glad, monkeypatch, "yes")
    assert resp["answer"] == after_take.GLAD and resp.get("after_take") is True
    assert glad.drawn()[-3:] == ["yes", after_take.GLAD, after_take.NEXT_TAKE]

    # A reply that opens a form keeps the ask open.
    form = _Db()
    _waiting(form, "take-2", ["whatsapp"])
    resp = _typed(form, monkeypatch, "07700 900461")  # no country code: the form opens
    assert resp.get("offer") == "whatsapp" and after_take.held(form, "u") is not None

    # An ask that no longer applies when its turn comes is skipped.
    skipped = _Db()
    _waiting(skipped, "take-2", ["install", "whatsapp"])
    _world(monkeypatch, phone="+447700900461", admin=None)
    rows = after_take.release(skipped, "u")
    assert [r["body"] for r in rows] == [after_take.NEXT_TAKE]


def test_the_plans_lines_wait_for_the_ask(monkeypatch):
    fifteen = "That's your 15 minutes for today."
    monkeypatch.setattr("services.plan_flow.after_take", lambda db, u: db.insert_lounge_messages(u, [
        {"client_id": "fifteen", "role": "bot", "kind": "text", "body": fifteen, "metadata": {}}]))
    db = _Db()
    _waiting(db, "take-1", ["feedback_check"])
    assert db.drawn() == [SUMMARY, feedback_check.COPY["ask"]]

    feedback_check.answer(db, user_id="u", arc_id="arc", take_session_id="take-1", choice="yes")
    assert db.drawn()[-2:] == [fifteen, after_take.NEXT_TAKE]


def test_an_older_waiting_message_shows_where_it_stands():
    db = _Db()
    _waiting(db)
    after_take.release_older(db, "u")
    assert db.drawn()[0] == SUMMARY and after_take.held(db, "u") is None
    assert after_take.NEXT_TAKE in db.bodies() and feedback_check.COPY["ask"] in db.bodies()


def test_after_a_distressed_message_the_asks_wait_until_i_write_again(monkeypatch):
    _world(monkeypatch, phone=None, admin=None)
    db = _Db()
    _waiting(db, "take-1", ["feedback_check"])
    _typed(db, monkeypatch, "no")
    assert db.drawn()[-1] == feedback_check.COPY["missing"]
    resp = _typed(db, monkeypatch, "Honestly I can't go on like this")
    assert "sorry" in resp["answer"].lower() and not resp.get("after_take")
    assert db.drawn()[-1] == resp["answer"] and after_take.held(db, "u") is not None
    # Writing again: Will's reply, and the chain goes on under it.
    _typed(db, monkeypatch, "Ok, I'm calmer now. How do I sound calmer on stage?")
    assert db.drawn()[-2:] == ["Slow the first slide down.", after_take.NEXT_TAKE]
