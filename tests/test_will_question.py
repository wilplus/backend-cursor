"""
STORY    As a speaker, after a Take I want Will to ask me at most one short
         question, only when something is off or missing, that I answer
         with a tap or in my own words, so that the next feedback knows my
         talk without a form in front of my next Take.
OUTCOME
  O1  Will asks only when something is off or missing, the first that
      holds: a breather when the practice missed or the voice dipped two
      Takes in a row; "On purpose?" when the clearer line I practised last
      Take did not come back; who the talk is for; what I want them to do;
      from Take 3, with both known, one deeper question. Nothing missing, no
      question; each of these once per talk, a breather never twice in a row.
  O2  The tap answers come from what Will heard: a Take that names its
      audience twice is checked ("Right?"); named once, those words come
      first, then what I said for an earlier talk, then the signed answers
      for my field. From the AI's read only words my Take says, word for
      word, short and without a number, are kept.
  O3  A tap is kept for Will and fills the talk's setup, so the next Take
      carries who it is for; then "Got it, thanks 🙏" and the message after
      the Take. "Someone else" opens one follow-up and the message waits;
      my typed words under it are the answer, or Skip. Skip lets the
      message go; a repeat tap writes nothing.
  O4  Typed words under the question are the answer: what I want them to
      do lands as the talk's call to action, my own note on the talk kept.
      Distress is never taken as an answer: the chat's safety reply comes.
  O5  After a Take that needs it, the summary's batch holds the message
      under Will's question, and the summary hears the line I practised
      last Take when this Take said it.
  O6  The founder's words are what Will asks from the next Take: a changed
      question and renamed answers (each answer keeps its follow-up by its
      place), a filled empty slot asked after the signed deeper questions;
      a number, a missing "{the board}" or a different number of answers is
      refused.
  O7  Will says a question with a light touch only when it still means the
      signed one and keeps my own words in it once, one line, no number,
      still a question; otherwise he says the signed words. The tap answers
      never change.
PROVES   O1 -> test_will_asks_the_first_that_holds_and_nothing_when_nothing_is_missing
         O2 -> test_the_taps_come_from_what_will_heard,
               test_only_words_the_take_says_are_kept_from_the_read
         O3 -> test_a_tap_is_kept_fills_the_setup_and_lets_the_message_go,
               test_someone_else_opens_one_follow_up_answered_in_own_words,
               test_skip_lets_the_message_go_and_a_repeat_tap_writes_nothing
         O4 -> test_typed_words_are_the_answer_and_fill_the_call_to_action,
               test_distress_typed_under_the_question_gets_the_safety_reply
         O5 -> test_the_summary_holds_its_message_under_wills_question,
               test_the_summary_hears_the_practised_line_when_it_came_back
         O6 -> test_the_founders_words_are_what_will_asks
         O7 -> test_will_varies_his_words_lightly_or_says_them_as_written
WHY      Founder 2026-10-20 (N82): "ask me a lot of questions … a natural
         flow in the walk and in the lounge"; the bank signed the same day.
"""
import json

from services import after_take, chat_query, speaker_memory, take_summary, will_question
import pytest

from services.will_question import AUDIENCE_BY_FIELD, CHIPS, FOLLOW_AT, PRINCIPLES, QUESTIONS, THANKS

SUMMARY = "Q3 Board pitch, the endings landed! 😎\n\nRecord Take 2 when you're ready ⬇️"


class _Takes:
    def __init__(self):
        self.ctx = {}

    def get_session_intake_context(self, take):
        return self.ctx.get(take)

    def set_session_intake_context(self, take, ctx):
        self.ctx[take] = dict(ctx)
        return True


class _Db:
    def __init__(self):
        self.thread = {}
        self.events = []
        self.takes = _Takes()
        self.bank = {}

    def insert_lounge_messages(self, user_id, rows):
        for r in rows:
            self.thread.setdefault(r["client_id"], dict(r))
        return [self.thread[r["client_id"]] for r in rows]

    def get_lounge_messages_page(self, user_id, limit=50, before=None):
        rows = sorted(self.thread.values(), key=lambda r: r["client_created_at"])
        return list(reversed(rows))[:limit]  # newest first

    def get_lounge_message_by_client_id(self, user_id, client_id):
        return self.thread.get(client_id)

    def rewrite_lounge_message(self, user_id, client_id, body, metadata, at=None):
        row = self.thread[client_id]
        row.update(body=body, metadata=metadata, **({"client_created_at": at} if at else {}))
        return row

    def insert_speaker_memory_event(self, row):
        self.events.append(row)

    def list_speaker_memory_events(self, user_id, limit=None):
        return list(self.events)

    def list_will_question_bank(self):
        return list(self.bank.values())

    def save_will_question_bank(self, rows):
        self.bank.update({r["key"]: dict(r) for r in rows})
        return True

    def count_will_questions_asked(self, key):
        return sum(1 for r in self.thread.values()
                   if (r.get("metadata") or {}).get("will_question") == key
                   and (r.get("metadata") or {}).get("will_question_step") == "ask")

    def get_user_profile(self, user_id):
        return {"domain": "sales"}

    def bodies(self):
        return [r["body"] for r in self.get_lounge_messages_page("u", limit=99)][::-1]


def _quiet(monkeypatch):
    monkeypatch.setattr(speaker_memory, "refresh", lambda *a, **k: False)


def _key(**kw):
    base = dict(take_index=2, now=("better", "rose"), before=("better", "held"), carried=None,
                audience="", goal="", asked=set(), asked_last=None)
    return will_question.choose_key(**{**base, **kw})


def test_will_asks_the_first_that_holds_and_nothing_when_nothing_is_missing():
    off_twice = dict(now=("not_yet", "dipped"), before=("not_yet", "held"))
    assert _key(**off_twice) == "pause"
    assert _key(**off_twice, asked_last="pause") == "audience"  # never twice in a row
    assert _key(carried={"passage": "We can match their price.", "used": False}) == "not_used"
    assert _key(carried={"passage": "We can match their price.", "used": True}) == "audience"
    assert _key(audience="The board") == "goal"
    assert _key(asked={"audience"}) == "goal"  # once per talk
    assert _key(audience="The board", goal="Approve two hires") is None  # Take 2: nothing missing
    known = dict(take_index=3, audience="The board", goal="Approve two hires")
    assert _key(**known) == "vision"
    assert _key(**known, asked={"vision", "most_you"}) == "why_matters"
    assert _key(**known, asked=set(will_question.PRINCIPLES)) is None
    assert _key(take_index=1, before=None) == "audience"


def _plan(key, heard=None, earlier=(), field_name="sales"):
    return will_question.Plan(key=key, arc_id="arc", take="t1", heard=lambda: heard or {},
                              field_name=field_name, earlier=list(earlier))


def test_the_taps_come_from_what_will_heard():
    twice = _plan("audience", {"audience": "the board", "audience_times": 2})
    key, text, chips, rest = will_question.words_for(twice)
    assert key == "audience_check" and text == QUESTIONS["audience_check"].format(heard="the board")
    assert chips == list(CHIPS["audience_check"]) and rest == {"heard": "the board"}

    once = _plan("audience", {"audience": "the board", "audience_times": 1}, earlier=["my team"])
    assert will_question.words_for(once)[2] == ["The board", "My team", AUDIENCE_BY_FIELD["sales"][0]]
    nothing = _plan("audience", field_name=None)
    assert will_question.words_for(nothing)[2] == list(AUDIENCE_BY_FIELD["executive_presence"])
    goal = _plan("goal", {"ask": "approve the pilot"})
    assert will_question.words_for(goal)[2] == ["Approve the pilot", "Say yes", "Trust me"]
    for key in ("pause", "vision"):
        assert will_question.words_for(_plan(key))[2] == list(CHIPS[key])


def test_only_words_the_take_says_are_kept_from_the_read():
    said = "The board decides today. So I ask the board to approve two hires by March 2027."
    read = will_question.read_heard
    got = read(json.dumps({"audience": "the board", "ask": "approve two hires"}), "Q3 Board pitch", said)
    assert got == {"audience": "the board", "ask": "approve two hires", "audience_times": 2}
    assert read(json.dumps({"audience": "the investors"}), "", said)["audience"] is None  # not said
    assert read(json.dumps({"ask": "approve two hires by March 2027"}), "", said)["ask"] is None
    assert read(json.dumps({"audience": "everyone"}), "", "hello everyone")["audience"] is None
    assert read("not json", "", said) == {"audience": None, "ask": None, "audience_times": 0}


def _asked(db, key="audience", chips=("The board", "My team", "A buyer"), take="t1", **rest):
    """The summary's batch as take_summary writes it: the held message, then
    Will's question."""
    found = _plan(key)
    from services import after_take
    db.insert_lounge_messages("u", [{
        "client_id": f"summary-{take}", "role": "bot", "kind": "cadence", "body": SUMMARY,
        "metadata": {"summary": True, "take_session_id": take},
        "client_created_at": "2026-10-20T10:00:00+00:00"},
        after_take.closing_row(user_id="u", arc_id="arc", take_index=1, take=take,
                               at="2026-10-20T10:00:00.000500+00:00", asks=["will_question"])])
    row = will_question.ask_rows(found, user_id="u", at="2026-10-20T10:00:00.001000+00:00")[0]
    row["metadata"].update(chips=list(chips), **rest)
    row["metadata"]["will_question"] = key
    db.insert_lounge_messages("u", [row])
    return row


def _tap(db, choice, take="t1"):
    return will_question.answer(db, user_id="u", arc_id="arc", take_session_id=take, choice=choice)


def test_a_tap_is_kept_fills_the_setup_and_lets_the_message_go(monkeypatch):
    _quiet(monkeypatch)
    db = _Db()
    db.takes.ctx["t1"] = {"topic": "Q3 Board pitch", "flow_tags": ["kept"]}
    _asked(db, "audience_check", chips=CHIPS["audience_check"], heard="the board")
    rows = _tap(db, "Yes")
    assert [r["body"] for r in rows] == ["Yes", THANKS, after_take.NEXT_TAKE]
    assert db.takes.ctx["t1"] == {"topic": "Q3 Board pitch", "flow_tags": ["kept"], "audience": "the board"}
    assert db.events[-1]["payload"]["audience"] == "the board"
    assert after_take.held(db, "u") is None


def _typed(db, monkeypatch, question):
    """One typed turn through the chat's chain, persisted as the route does."""
    db.insert_lounge_messages("u", [{"client_id": f"typed-{question}", "role": "user", "kind": "text",
                                     "body": question, "metadata": {},
                                     "client_created_at": "2026-10-20T10:00:09+00:00"}])
    monkeypatch.setattr("services.db.db", db, raising=False)
    monkeypatch.setattr(chat_query, "_librarian", lambda *a, **k: ({"answer": "Will's own reply."}, "faq"))
    monkeypatch.setattr(chat_query, "thread_history", lambda *a, **k: [])
    return chat_query.answer_chat(
        db, user_id="u", question=question, history=[], context=None, app_config=object(),
        finalize=lambda resp, intent: chat_query.finish_chat_turn(
            db, resp, user_id="u", question=question, persist_thread=True,
            user_client_id=f"typed-{question}", user_created_at=None, intent=intent))


def test_someone_else_opens_one_follow_up_answered_in_own_words(monkeypatch):
    _quiet(monkeypatch)
    db = _Db()
    _asked(db, "audience_check", chips=CHIPS["audience_check"], heard="the board")
    rows = _tap(db, "Someone else")
    assert [r["body"] for r in rows] == ["Someone else", FOLLOW_AT["audience_check"][1]]
    assert after_take.held(db, "u") is not None and "t1" not in db.takes.ctx  # it waits
    resp = _typed(db, monkeypatch, "The investors. The board only signs off.")
    assert resp["answer"] == THANKS
    assert db.takes.ctx["t1"]["audience"] == "The investors. The board only signs off."
    assert db.bodies()[-1] == after_take.NEXT_TAKE and after_take.held(db, "u") is None

    skipped = _Db()  # Skip under the follow-up lets the message go too
    _asked(skipped, "pause", chips=CHIPS["pause"])
    assert [r["body"] for r in _tap(skipped, "Something's missing")][-1] == FOLLOW_AT["pause"][1]
    assert [r["body"] for r in _tap(skipped, will_question.SKIP)] == ["Skip", after_take.NEXT_TAKE]
    assert will_question.open_question(skipped, "u") is None


def test_skip_lets_the_message_go_and_a_repeat_tap_writes_nothing(monkeypatch):
    _quiet(monkeypatch)
    db = _Db()
    _asked(db)
    assert [r["body"] for r in _tap(db, will_question.SKIP)] == ["Skip", after_take.NEXT_TAKE]
    assert db.events[-1]["payload"] == {"question": "audience", "skipped": True}
    assert _tap(db, "The board") == [] and "t1" not in db.takes.ctx


def test_distress_typed_under_the_question_gets_the_safety_reply(monkeypatch):
    _quiet(monkeypatch)
    db = _Db()
    _asked(db, "pause", chips=CHIPS["pause"])
    resp = _typed(db, monkeypatch, "Honestly I can't go on like this")
    assert resp["answer"] != THANKS and "sorry" in resp["answer"].lower()
    assert db.events == []  # never kept as an answer


def test_typed_words_are_the_answer_and_fill_the_call_to_action(monkeypatch):
    _quiet(monkeypatch)
    db = _Db()
    db.takes.ctx["t1"] = {"strategic_context": "Additional context: they cut budgets last year."}
    _asked(db, "goal", chips=["Say yes", "Trust me", "Get it"])
    resp = _typed(db, monkeypatch, "Approve two hires by March")
    assert resp["answer"] == THANKS and db.bodies()[-1] == after_take.NEXT_TAKE
    assert db.takes.ctx["t1"]["strategic_context"] == (
        "Desired call to action: Approve two hires by March\n"
        "Additional context: they cut budgets last year.")
    assert will_question.talk_goal([{"intake_context": db.takes.ctx["t1"]}]) == "Approve two hires by March"


class _SummaryDb(_Db):
    def get_v4_dark_frame(self, take):
        return {"blocks": [{"block_id": "b1", "snippet_ids": ["s1"]}]}

    def get_snippets_by_session(self, take):
        return [{"id": "s1", "transcript": "We can match their price. The board decides today."}]

    def list_v4_willfidence_reads(self, take):
        return [{"block_id": "b1", "s": 0.6, "w": 0.6, "willfident": 0.5}]


TAKES = [{"id": "t1", "intake_context": {"topic": "Q3 Board pitch"}}]


def _summary(db, monkeypatch, takes=TAKES, take="t1", heard=None, carried=None):
    seen = {}

    def write(anchor, facts, **kw):
        seen["facts"] = facts
        return "Q3 Board pitch, the endings landed! Record the next take when you're ready."
    monkeypatch.setattr("services.whatsapp_notify.whatsapp_state", lambda _db, _u: {"phone": "+44"})
    monkeypatch.setattr("services.person_asks.next_for", lambda _u: None)
    monkeypatch.setattr(take_summary, "_under_authority", lambda _db, _take, w: w())
    monkeypatch.setattr(take_summary, "write_summary", write)
    monkeypatch.setattr(will_question, "heard", lambda *a, **k: heard or {})
    monkeypatch.setattr(will_question, "vary", lambda *a, **k: None)
    monkeypatch.setattr(will_question, "carried_over", lambda *a, **k: carried)
    msg = take_summary.summary_message(db, user_id="u", arc_id="arc", takes=takes,
                                       take_session_id=take, body={"practice": "better"})
    return msg, seen


def test_the_summary_holds_its_message_under_wills_question(monkeypatch):
    _quiet(monkeypatch)
    db = _SummaryDb()
    msg, _ = _summary(db, monkeypatch, heard={"audience": "the board", "audience_times": 2})
    asked = [r for r in db.thread.values() if (r.get("metadata") or {}).get("offer") == "will_question"]
    closing = next(r for r in db.thread.values() if (r.get("metadata") or {}).get("next_take"))
    assert closing["metadata"]["held_for"] == "will_question" and len(asked) == 1
    assert "held_for" not in msg["metadata"]
    assert asked[0]["body"] == QUESTIONS["audience_check"].format(heard="the board")
    assert asked[0]["client_created_at"] > msg["client_created_at"]


def test_the_summary_hears_the_practised_line_when_it_came_back(monkeypatch):
    _quiet(monkeypatch)
    db = _SummaryDb()
    takes = TAKES + [{"id": "t2", "intake_context": {"topic": "Q3 Board pitch", "audience": "The board",
                                                      "strategic_context": "Desired call to action: say yes"}}]
    _, seen = _summary(db, monkeypatch, takes=takes, take="t2",
                       carried={"passage": "We can match their price.", "used": True})
    assert any("We can match their price." in f for f in seen["facts"])
    assert not [r for r in db.thread.values() if (r.get("metadata") or {}).get("offer")]  # nothing to ask


def test_the_founders_words_are_what_will_asks():
    db = _Db()
    view = will_question.admin_view(db)
    assert (view["questions"], view["empty"]) == (9, 2)
    check = next(i for g in view["groups"] for i in g["items"] if i["key"] == "audience_check")
    assert "{the board}" in check["question"] and check["chips"] == ["Yes", "Someone else"]
    will_question.save_bank(db, [
        {"key": "audience_check", "question": "So this one's for {the board}? 🎯", "chips": ["Spot on", "Not quite"]},
        {"key": "slot_1", "question": "What would make you proud of this talk?", "chips": []}])
    words = will_question.bank(db)
    found = will_question.Plan(key="audience", arc_id="arc", take="t1", words=words,
                               heard=lambda: {"audience": "the board", "audience_times": 2})
    key, text, chips, _ = will_question.words_for(found)
    assert (key, text, chips) == ("audience_check", "So this one's for the board? 🎯", ["Spot on", "Not quite"])
    assert will_question.follow_up("audience_check", "Not quite", chips) == FOLLOW_AT["audience_check"][1]
    assert will_question.resolved("audience_check", "Spot on", {"chips": chips, "heard": "the board"}) == "the board"
    filled = tuple(k for k in PRINCIPLES if words[k]["question"])
    assert _key(take_index=3, audience="The board", goal="Say yes", asked=set(PRINCIPLES[:4]), deeper=filled) == "slot_1"
    assert will_question.admin_view(db)["empty"] == 1
    for bad in ({"key": "audience_check", "question": "Is it for the board?", "chips": ["Yes", "No"]},
                {"key": "goal", "question": "Give me 3 reasons", "chips": ["Say yes", "Trust me", "Get it"]},
                {"key": "pause", "question": "Need a break?", "chips": ["Yes"]}):
        with pytest.raises(will_question.QuestionError):
            will_question.save_bank(db, [bad])


def test_will_varies_his_words_lightly_or_says_them_as_written():
    signed = will_question.QUESTIONS["audience"]
    check = will_question.QUESTIONS["audience_check"]
    light = "Quick one: who is this talk actually for? 🎯"
    assert will_question.read_varied("audience", light, signed) == light
    # a number, a lost or doubled placeholder, no question, another meaning: as written
    assert will_question.read_varied("audience", "Quick one: who are the 2 people this talk is for?", signed) is None
    assert will_question.read_varied("audience_check", "Sounds like this one's for the board. Right? 🎯", check) is None
    assert will_question.read_varied("audience_check", "Sounds like {heard} is who {heard} is for. Right?", check) is None
    assert will_question.read_varied("audience", "Quick one: this talk is for someone. 🎯", signed) is None
    assert will_question.read_varied("audience", "Do you like pizza? 🎯", signed) is None
    # the varied words are what Will asks; the tap answers stay as signed
    found = _plan("audience", heard={"audience": None, "audience_times": 0})
    found.varied = lambda: {"audience": light}
    key, text, chips, _ = will_question.words_for(found)
    assert (key, text) == ("audience", light)
    assert chips == ["A buyer", "Their team", "The decision maker"]
