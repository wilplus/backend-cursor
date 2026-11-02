"""
STORY    As a speaker, after a Take I want one thing to do at a time: the
         Take's card and its summary, then each ask on its own, then a
         goodbye with nothing pushing me to record again, and the settings
         asks only the next time I open the app, so that nothing competes
         with the walk and I practise because I want to (founder 2026-10-20,
         N89; 2026-10-31, N294, N295; N319 item 7).
OUTCOME
  O1  One ask after each Take, the first that waits (founder 2026-10-26,
      N189). After Take 1 that is Will's question when he has one, else
      "Did this help?" when the Take looks off; never an ask from the CEO
      panel on Take 1; WhatsApp and the home screen never after a Take
      (N294 item 8).
  O2  From Take 2 the order is the CEO panel's ask, Will's question, "Did
      this help?"; the first that waits comes and the others wait for a
      later Take; Will's next question may follow his first, only when his
      is the ask (N294 item 4); nothing comes when nothing applies.
  O3  The asks come one at a time, each under whatever closed the one
      before: a typed turn, under Will's reply; "Yes", tapped or typed,
      under "We're glad it helped you."; a reply that opens a form keeps the
      ask open. An ask that no longer applies is skipped, and so is a
      settings ask a message held from before still names. After the last
      comes "Good job. See you next time.", no push to the next Take.
  O4  A message still waiting when a newer Take is written shows where it
      stands.
  O5  After a distressed message the chat's safety reply comes and the asks
      wait: nothing lands under it until I write again (founder 2026-10-21,
      N94).
  O6  The plan's lines after a practice day's Take ("That's your 15
      minutes for today.") wait for the ask: the ask stays the newest
      bubble, so its answers stay; after my answer come the lines, then
      "Good job. See you {day}." with the plan's next practice day (N347
      item 2), then the plan's progress, last (N319 item 7).
  O7  The settings asks wait for the next visit (N294 item 8, N295): never
      before my second Take is done, never while an ask after a Take waits,
      at most one per Take; WhatsApp first, opened with "It seems you enjoy
      using WillpowerLab." (at most twice), the home screen last, once,
      where the phone can add it.
PROVES   O1 -> test_after_take_one_will_else_the_question_never_a_settings_ask
         O2 -> test_from_take_two_one_ask_ceo_ask_will_the_question
         O3 -> test_each_ask_comes_under_what_closed_the_one_before_then_the_goodbye
         O4 -> test_an_older_waiting_message_shows_where_it_stands
         O5 -> test_after_a_distressed_message_the_asks_wait_until_i_write_again
         O6 -> test_the_plans_lines_wait_for_the_ask_then_the_goodbye_and_the_progress
         O7 -> test_settings_asks_wait_for_the_next_visit
WHY      Founder 2026-10-20: "one action at a time"; 2026-10-31 (N294): "No
         call to action means that there is no push", "the next time you
         come and open the app ask the settings questions".
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


def _index(take):
    """The Take's number from its name ("take-2" is Take 2)."""
    return int(take.rsplit("-", 1)[-1])


def _waiting(db, take="take-1", asks=("feedback_check",), lead_ins=None):
    """The summary's batch as take_summary writes it: the summary, the closing
    message held behind the chain, then the first ask."""
    closing = after_take.closing_row(user_id="u", arc_id="arc", take_index=_index(take), take=take,
                                     at="2026-10-20T10:00:00.001000+00:00", asks=list(asks),
                                     lead_ins=lead_ins or {})
    db.insert_lounge_messages("u", [{
        "client_id": f"summary-{take}", "role": "bot", "kind": "cadence", "body": SUMMARY,
        "metadata": {"summary": True, "take_session_id": take}, "client_created_at": AT},
        closing] + after_take.rows_for(db, "u", closing["metadata"], asks[0],
                                       "2026-10-20T10:00:00.002000+00:00"))
    return closing


def _typed(db, monkeypatch, question, answer="Slow the first slide down.", offer=None):
    """One typed turn through the chat's chain, persisted as the route does;
    ``offer``: Will's reply opens that ask's form."""
    monkeypatch.setattr("services.db.db", db, raising=False)
    reply = {"answer": answer, **({"offer": offer} if offer else {})}
    monkeypatch.setattr(chat_query, "_librarian", lambda *a, **k: (reply, "faq"))
    monkeypatch.setattr(chat_query, "thread_history", lambda *a, **k: [])
    return chat_query.answer_chat(
        db, user_id="u", question=question, history=[], context=None, app_config=object(),
        finalize=lambda resp, intent: chat_query.finish_chat_turn(
            db, resp, user_id="u", question=question, persist_thread=True,
            user_client_id=None, user_created_at=None, intent=intent))


def test_after_take_one_will_else_the_question_never_a_settings_ask(monkeypatch):
    _world(monkeypatch, phone=None, admin={"id": "a1", "kind": "promo"})
    db = _Db()
    # No number, a CEO panel's ask open: Take 1 still brings Will's question.
    assert after_take.chain(db, "u", take_index=1, off=True, will=True) == ["will_question"]
    assert after_take.chain(db, "u", take_index=1, off=True) == ["feedback_check"]
    assert after_take.chain(db, "u", take_index=1, off=False) == []


def test_from_take_two_one_ask_ceo_ask_will_the_question(monkeypatch):
    db = _Db()
    _world(monkeypatch, phone=None, admin={"id": "a1", "kind": "promo"})
    # Three would wait: the first comes, the others wait (N189).
    assert after_take.chain(db, "u", take_index=2, off=True, will=True, will_next=True) == ["admin"]
    _world(monkeypatch, phone=None, admin=None)
    # No number: still no WhatsApp after a Take (N294 item 8).
    assert after_take.chain(db, "u", take_index=2, off=True, will=True) == ["will_question"]
    # Will's next question rides behind his first, never behind another ask.
    assert after_take.chain(db, "u", take_index=2, off=True, will=True, will_next=True) == [
        "will_question", "will_next"]
    assert after_take.chain(db, "u", take_index=2, off=True, will_next=True) == ["feedback_check"]
    assert after_take.chain(_Db(), "u", take_index=2, off=False) == []


def test_each_ask_comes_under_what_closed_the_one_before_then_the_goodbye(monkeypatch):
    _world(monkeypatch, phone=None, admin={"id": "a1", "kind": "promo"})
    db = _Db()
    # Take 2: the CEO panel's ask (the Lounge draws it), then "Did this
    # help?", then the goodbye. The summary is drawn at once, without the CTA.
    _waiting(db, "take-2", ["admin", "feedback_check"])
    assert db.drawn() == [SUMMARY]
    assert after_take.held(db, "u")["metadata"]["chain"] == ["feedback_check"]

    # The ask's form closes (the Lounge's POST): the question comes, the
    # closing message still waits.
    rows = after_take.release(db, "u")
    assert [r["body"] for r in rows] == [feedback_check.COPY["ask"]]
    assert db.drawn() == [SUMMARY, feedback_check.COPY["ask"]]
    assert after_take.held(db, "u")["metadata"]["held_for"] == "feedback_check"

    # "Yes": the founder's sentence, then nothing is left and the goodbye
    # comes under it, no push to the next Take (N294 item 6).
    rows = feedback_check.answer(db, user_id="u", arc_id="arc", take_session_id="take-2", choice="yes")
    assert [r["body"] for r in rows] == ["Yes", after_take.GLAD, "Good job. See you next time."]
    assert db.drawn()[-3:] == ["Yes", after_take.GLAD, after_take.SEE_YOU]
    assert after_take.held(db, "u") is None

    # A typed turn that passes the ask advances the chain under Will's reply.
    typed = _Db()
    _waiting(typed, "take-1", ["feedback_check"])
    _typed(typed, monkeypatch, "How do I sound calmer?")
    assert typed.drawn()[-2:] == ["Slow the first slide down.", after_take.SEE_YOU]
    assert after_take.held(typed, "u") is None

    # A typed "yes" is answered with the founder's sentence, the chain under it.
    glad = _Db()
    _waiting(glad, "take-1", ["feedback_check"])
    resp = _typed(glad, monkeypatch, "yes")
    assert resp["answer"] == after_take.GLAD and resp.get("after_take") is True
    assert glad.drawn()[-3:] == ["yes", after_take.GLAD, after_take.SEE_YOU]

    # A reply that opens a form keeps the ask open.
    form = _Db()
    _waiting(form, "take-2", ["feedback_check"])
    resp = _typed(form, monkeypatch, "Can I get a WhatsApp when my coach replies?",
                  answer="Sure, add your number.", offer="whatsapp")
    assert resp.get("offer") == "whatsapp" and after_take.held(form, "u") is not None

    # An ask that no longer applies when its turn comes is skipped, and so is
    # a settings ask a message held from before N294 still names.
    skipped = _Db()
    _waiting(skipped, "take-2", ["admin", "install", "whatsapp"])
    _world(monkeypatch, phone=None, admin=None)
    rows = after_take.release(skipped, "u")
    assert [r["body"] for r in rows] == [after_take.SEE_YOU]


def test_the_plans_lines_wait_for_the_ask_then_the_goodbye_and_the_progress(monkeypatch):
    fifteen, done = "That's your 15 minutes for today.", "1 of 9 practices done."
    monkeypatch.setattr("services.plan_flow.after_take", lambda db, u: db.insert_lounge_messages(u, [
        {"client_id": "fifteen", "role": "bot", "kind": "text", "body": fifteen, "metadata": {}}]))
    monkeypatch.setattr("services.plan_flow.next_day_text", lambda db, u: "Wednesday")
    monkeypatch.setattr("services.plan_flow.progress", lambda db, u: db.insert_lounge_messages(u, [
        {"client_id": "progress", "role": "bot", "kind": "text", "body": done,
         "metadata": {"plan_progress": True, "done": 1, "total": 9}}]))
    db = _Db()
    _waiting(db, "take-1", ["feedback_check"])
    assert db.drawn() == [SUMMARY, feedback_check.COPY["ask"]]

    feedback_check.answer(db, user_id="u", arc_id="arc", take_session_id="take-1", choice="yes")
    assert db.drawn()[-3:] == [fifteen, "Good job. See you Wednesday.", done]


def test_an_older_waiting_message_shows_where_it_stands():
    db = _Db()
    _waiting(db)
    after_take.release_older(db, "u")
    assert db.drawn()[0] == SUMMARY and after_take.held(db, "u") is None
    assert after_take.SEE_YOU in db.bodies() and feedback_check.COPY["ask"] in db.bodies()


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
    assert db.drawn()[-2:] == ["Slow the first slide down.", after_take.SEE_YOU]


def _done(db, take):
    """A Take whose walk reached its end: its closing message, let go."""
    db.insert_lounge_messages("u", [after_take.closing_row(
        user_id="u", arc_id="arc", take_index=_index(take), take=take, at=AT, asks=[])])


def test_settings_asks_wait_for_the_next_visit(monkeypatch):
    _world(monkeypatch, phone=None, admin=None)
    db = _Db()
    whatsapp = ("It seems you enjoy using WillpowerLab. "
                "Want a WhatsApp when your coach replies? Add your number.")
    _done(db, "take-1")
    assert after_take.visit(db, "u", can_install=True) == []  # never before the second Take
    _done(db, "take-2")
    rows = after_take.visit(db, "u", can_install=True)
    assert [r["body"] for r in rows] == [whatsapp]
    assert rows[0]["metadata"]["offer"] == "whatsapp"  # the Lounge opens its form
    assert after_take.visit(db, "u", can_install=True) == []  # one a Take

    # While an ask after a Take is in front of me, nothing is asked over it.
    _waiting(db, "take-3", ["feedback_check"])
    assert after_take.visit(db, "u", can_install=True) == []
    feedback_check.answer(db, user_id="u", arc_id="arc", take_session_id="take-3", choice="yes")
    assert [r["body"] for r in after_take.visit(db, "u", can_install=True)] == [whatsapp]

    # Asked twice: then the home screen, once, where the phone can add it.
    _done(db, "take-4")
    assert after_take.visit(db, "u", can_install=False) == []
    _done(db, "take-5")
    assert [r["body"] for r in after_take.visit(db, "u", can_install=True)] == [
        "Well, I can see you're doing pretty good. "
        "Add WillpowerLab to your home screen? Your coach is one tap away."]
    _done(db, "take-6")
    assert after_take.visit(db, "u", can_install=True) == []
