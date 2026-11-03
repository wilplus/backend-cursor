"""
STORY    As a speaker, after a Take I want Will to ask me a short question
         about the moment the walk just worked on, only when something is
         off or missing, that I answer with a tap or in my own words, so
         that the next feedback knows my talk without a form in front of my
         next Take.
OUTCOME
  O1  Will asks only when something is off or missing, the first that
      holds: a breather when the practice missed or the voice dipped two
      Takes in a row; "On purpose?" when the clearer line I practised last
      Take did not come back; who the talk is for; what I want them to do;
      from Take 3, with both known, one deeper question. Nothing missing, no
      question; each of these once per talk, a breather never twice in a row.
  O2  The tap answers come from what Will heard, the recording first: a
      Take that names its audience twice is checked ("Right?"); named
      once, those words come first, then what I said for an earlier talk,
      then the signed answers for my field, and no "Someone else": my own
      words go into "Something else" in the bar (N406 item 2); what I want
      them to do the same way. From the AI's read only
      words my Take says, word for word, short and without a number, are
      kept.
  O3  A tap is kept for Will and fills the talk's setup, so the next Take
      carries who it is for; Will says it back, "{who}. I'll keep them in
      mind." (N294 item 5), any other answer gets "Got it, thanks 🙏"; then
      the message after the Take. "Someone else" under the check opens one
      follow-up, "Who is it for, then? 👀", with no tap answers, and the
      message waits; my typed words under it are the answer, or Skip. Skip
      lets the message go; a repeat tap writes nothing.
  O4  Typed words under the question are the answer: what I want them to
      do lands as the talk's call to action, my own note on the talk kept.
      Distress is never taken as an answer: the chat's safety reply comes.
  O5  After a Take that needs it, the summary's batch holds the message
      under Will's question, a bridge line between the summary and the
      question ("Ok, now let's dive into the content for a bit.", founder
      2026-10-21, N94), and the summary hears the line I practised last
      Take when this Take said it.
  O8  The question opens on my own words of the last moment the walk showed
      (N294 item 1): "When you said “…”, " where it reads on, else "We just
      worked on “…”. "; "On purpose?" quotes its own line and nothing more;
      with no moment the question is as signed.
  O9  One at a time (N294 item 4): when both who the talk is for and what I
      want them to do are missing, what I want them to do follows my answer
      to who, from what Will heard first; a Skip ends them.
  O10 The key line is asked last, by voice (N294 item 2): once who the talk
      is for and what I want them to do are known and my key line is
      missing, Will asks the plan's signed question with who in it, opened
      on the moment, no tap answers; it follows my answer to what I want
      them to do, naming who I said; my answer is kept as the talk's key
      line (sure) where the plan and the picker read it, and for Will.
  O12 Will says who it is for from my side (N406 items 1, 3 and 4): "my
      team" back as "Your team. I'll keep them in mind."; "Myself" as
      "I'll keep you in mind.", then what I want to do with no "them" and
      no taps, and the key line keeps "your audience". After a typed answer
      the goodbye waits under his next question until I answer it, even
      when the Lounge asks to let it go.
  O11 An answer by voice answers Will's open question (N294 item 3, N319
      item 1): the words heard are my voice bubble, Will thanks me, the
      chain goes on; nothing heard, or no question open, writes nothing.
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
         O8 -> test_the_question_opens_on_the_moment_the_walk_just_worked_on
         O9 -> test_what_they_should_do_follows_an_answered_who
         O10 -> test_the_key_line_is_asked_last_by_voice_and_kept
         O11 -> test_a_voice_answer_answers_wills_question
         O12 -> test_will_says_who_from_my_side_and_the_goodbye_waits
WHY      Founder 2026-10-20 (N82): "ask me a lot of questions … a natural
         flow in the walk and in the lounge"; the bank signed the same day.
         2026-10-31 (N294): "these questions, they should be related to the
         moment"; "they can be only one at a time. Only once you answer".
"""
import json

from services import after_take, chat_query, speaker_memory, take_summary, will_question
import pytest

from services.will_question import AUDIENCE_BY_FIELD, CHIPS, FOLLOW_AT, PRINCIPLES, QUESTIONS, THANKS

SEE_YOU = "Good job. See you next time."

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
    both = dict(audience="The board", goal="Approve two hires")
    assert _key(**both) == "key_line"  # who and what known, the key line missing (N294 item 2)
    assert _key(**both, asked={"key_line"}) is None  # once per talk
    assert _key(**both, key_line="We grow by owning the night shift.") is None  # nothing missing
    known = dict(take_index=3, audience="The board", goal="Approve two hires",
                 key_line="We grow by owning the night shift.")
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
    goal = _plan("goal", {"ask": "approve the pilot"}, earlier=["sign the contract"])
    assert will_question.words_for(goal)[2] == ["Approve the pilot", "Sign the contract", "Say yes"]
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
    assert [r["body"] for r in rows] == ["Yes", "The board. I'll keep them in mind.", SEE_YOU]
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
    resp = _typed(db, monkeypatch, "The investors.")
    assert resp["answer"] == "The investors. I'll keep them in mind."
    assert db.takes.ctx["t1"]["audience"] == "The investors."
    assert db.bodies()[-1] == SEE_YOU and after_take.held(db, "u") is None

    skipped = _Db()  # Skip under the follow-up lets the message go too
    _asked(skipped, "pause", chips=CHIPS["pause"])
    assert [r["body"] for r in _tap(skipped, "Something's missing")][-1] == FOLLOW_AT["pause"][1]
    assert [r["body"] for r in _tap(skipped, will_question.SKIP)] == ["Skip", SEE_YOU]
    assert will_question.open_question(skipped, "u") is None


def test_skip_lets_the_message_go_and_a_repeat_tap_writes_nothing(monkeypatch):
    _quiet(monkeypatch)
    db = _Db()
    _asked(db)
    assert [r["body"] for r in _tap(db, will_question.SKIP)] == ["Skip", SEE_YOU]
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
    assert resp["answer"] == THANKS and db.bodies()[-1] == SEE_YOU
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
    # The bridge line between the summary and the question (N94).
    bridge = next(r for r in db.thread.values() if (r.get("metadata") or {}).get("bridge"))
    assert bridge["body"] in after_take.BRIDGE
    assert msg["client_created_at"] < bridge["client_created_at"] < asked[0]["client_created_at"]


def test_what_they_should_do_follows_an_answered_who(monkeypatch):
    _quiet(monkeypatch)
    db = _SummaryDb()
    _summary(db, monkeypatch, heard={"audience": "the board", "audience_times": 1,
                                     "ask": "approve two hires"})
    closing = next(r for r in db.thread.values() if (r.get("metadata") or {}).get("next_take"))
    assert closing["metadata"]["chain"] == ["will_next"]
    rows = _tap(db, "The board")
    assert [r["body"] for r in rows] == ["The board", "The board. I'll keep them in mind.", QUESTIONS["goal"]]
    assert rows[-1]["metadata"]["chips"] == ["Approve two hires", "Say yes", "Trust me"]
    assert after_take.held(db, "u") is not None  # one at a time: the goodbye waits
    rows = _tap(db, "Approve two hires")
    assert [r["body"] for r in rows] == ["Approve two hires", THANKS, SEE_YOU]
    assert will_question.talk_goal([{"intake_context": db.takes.ctx["t1"]}]) == "Approve two hires"

    skipped = _SummaryDb()  # a Skip ends them
    _summary(skipped, monkeypatch, heard={"audience": "the board", "audience_times": 1})
    assert [r["body"] for r in _tap(skipped, will_question.SKIP)] == ["Skip", SEE_YOU]


def test_will_says_who_from_my_side_and_the_goodbye_waits(monkeypatch):
    _quiet(monkeypatch)
    db = _SummaryDb()
    _summary(db, monkeypatch)
    asked = next(r for r in db.thread.values() if (r.get("metadata") or {}).get("offer") == "will_question")
    assert will_question.SOMEONE_ELSE not in asked["metadata"]["chips"]  # "Something else" in the bar
    resp = _typed(db, monkeypatch, "Myself")
    assert resp["answer"] == "I'll keep you in mind."
    assert db.bodies()[-1] == will_question.GOAL_SELF
    assert will_question.open_question(db, "u")["chips"] == []
    # The Lounge asks to let the goodbye go before it reads the thread again.
    assert after_take.release_from_lounge(db, "u") == [] and db.bodies()[-1] == will_question.GOAL_SELF
    resp = _typed(db, monkeypatch, "Feel calm")
    assert resp["answer"] == THANKS and db.bodies()[-1] == SEE_YOU
    assert will_question.key_line_question("Myself") == will_question.key_line_question(None)

    mine = _SummaryDb()
    _summary(mine, monkeypatch)
    resp = _typed(mine, monkeypatch, "my manager and her two leads")
    assert resp["answer"] == "Your manager and her two leads. I'll keep them in mind."
    assert mine.bodies()[-1] == QUESTIONS["goal"]
    assert will_question.key_line_question("my team").startswith("If your team remembers")


def test_the_summary_hears_the_practised_line_when_it_came_back(monkeypatch):
    _quiet(monkeypatch)
    db = _SummaryDb()
    takes = TAKES + [{"id": "t2", "intake_context": {"topic": "Q3 Board pitch", "audience": "The board",
                                                      "strategic_context": "Desired call to action: say yes",
                                                      "key_line": "We can match their price."}}]
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
    assert _key(take_index=3, audience="The board", goal="Say yes", key_line="Say yes today.",
                asked=set(PRINCIPLES[:4]), deeper=filled) == "slot_1"
    assert will_question.admin_view(db)["empty"] == 1
    for bad in ({"key": "audience_check", "question": "Is it for the board?", "chips": ["Yes", "No"]},
                {"key": "goal", "question": "Give me 3 reasons", "chips": ["Say yes", "Trust me", "Get it"]},
                {"key": "pause", "question": "Need a break?", "chips": ["Yes"]}):
        with pytest.raises(will_question.QuestionError):
            will_question.save_bank(db, [bad])


def test_will_varies_his_words_lightly_or_says_them_as_written():
    signed = will_question.QUESTIONS["audience"]
    check = will_question.QUESTIONS["audience_check"]
    light = "Who were you really talking to? 🎯"
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


def test_the_question_opens_on_the_moment_the_walk_just_worked_on():
    said = "That should get us back above ninety percent."
    snippets = [{"id": "s1", "transcript": "We start today."}, {"id": "s2", "transcript": said}]
    thread = [  # newest first: the walk's last moment played s2
        {"kind": "walk_step", "metadata": {"take_session_id": "t1", "step": "end"}},
        {"kind": "walk_step", "metadata": {"take_session_id": "t1", "clip": {"snippet_id": "s2"}}},
        {"kind": "walk_step", "metadata": {"take_session_id": "t1", "clip": {"snippet_id": "s1"}}},
        {"kind": "walk_step", "metadata": {"take_session_id": "t0", "clip": {"snippet_id": "s1"}}}]
    moment = will_question.moment_of(thread, "t1", snippets)
    assert moment == "That should get us back above ninety percent"
    assert will_question.moment_of(thread, "t9", snippets) is None

    audience = _plan("audience", field_name=None)
    audience.moment = moment
    assert will_question.words_for(audience)[1] == (
        f"We just worked on “{moment}”. Who were you talking to? 🎯")
    check = _plan("audience", {"audience": "the board", "audience_times": 2})
    check.moment = moment
    assert will_question.words_for(check)[1] == (
        f"When you said “{moment}”, sounds like this one's for the board. Right? 🎯")
    practised = _plan("not_used")
    practised.passage, practised.moment = "We can match their price.", moment
    assert will_question.words_for(practised)[1] == QUESTIONS["not_used"].format(
        words="We can match their price.")
    assert will_question.words_for(_plan("goal"))[1] == QUESTIONS["goal"]  # no moment


class _Adapter:
    def __init__(self, text):
        self.text, self.calls = text, []

    def transcribe_audio(self, audio, filename, **kw):
        self.calls.append(kw)
        return {"text": self.text, "duration": 3.2}


def _voice(db, monkeypatch, text, take="t1"):
    monkeypatch.setattr("services.plan_flow._heard", lambda audio: True)
    adapter = _Adapter(text)
    rows = will_question.answer_voice(db, adapter, b"voice", user_id="u", arc_id="arc",
                                      take_session_id=take, filename="answer.webm", duration_ms=3200)
    return rows, adapter


def test_the_key_line_is_asked_last_by_voice_and_kept(monkeypatch):
    _quiet(monkeypatch)
    db = _SummaryDb()
    plans = {"id": "plan-1", "facts": {"why": "A promotion"}}
    db.get_open_plan = lambda _u: plans
    db.update_plan = lambda _u, _id, fields: plans.update(fields) or plans
    takes = TAKES + [{"id": "t2", "intake_context": {"topic": "Q3 Board pitch", "audience": "the board"}}]
    _summary(db, monkeypatch, takes=takes, take="t2", heard={"ask": "approve two hires"})
    closing = next(r for r in db.thread.values() if (r.get("metadata") or {}).get("next_take"))
    assert closing["metadata"]["chain"] == ["will_next"]  # the key line follows what they should do
    rows = _tap(db, "Approve two hires", take="t2")
    asked = rows[-1]
    assert asked["body"] == ("If the board remembers one sentence from you, what is it? "
                             "Say it the way you'll say it.")
    assert asked["metadata"]["will_question"] == "key_line" and asked["metadata"]["chips"] == []
    assert after_take.held(db, "u") is not None  # one at a time: the goodbye waits

    rows, adapter = _voice(db, monkeypatch, "We match every transaction the moment it lands.", take="t2")
    assert [r["body"] for r in rows] == ["We match every transaction the moment it lands.", THANKS, SEE_YOU]
    assert rows[0]["role"] == "user" and rows[0]["metadata"]["will_voice"] is True
    assert adapter.calls[0]["usage_surface"] == "will_question_answer"
    kept = "We match every transaction the moment it lands."
    assert db.takes.ctx["t2"]["key_line"] == kept
    assert plans["facts"] == {"why": "A promotion", "key_line": kept}  # the plan had none
    assert db.events[-1]["payload"]["key_line"] == kept and db.events[-1]["payload"]["voice"] is True
    from services import take_context
    assert take_context.assemble(db.takes.ctx["t2"], {})["key_line"] == {
        "value": kept, "state": "sure", "source": "setup"}
    # Asked first when who and what are known: on the moment, said as signed.
    known = will_question.Plan(key="key_line", arc_id="arc", take="t3", who="Investors",
                               moment="We're already seeing real traction")
    assert will_question.words_for(known)[1:3] == (
        "We just worked on “We're already seeing real traction”. If Investors remembers one sentence "
        "from you, what is it? Say it the way you'll say it.", [])
    unknown = will_question.Plan(key="key_line", arc_id="arc", take="t3")
    assert will_question.words_for(unknown)[1].startswith("If your audience remembers one sentence")


def test_a_voice_answer_answers_wills_question(monkeypatch):
    _quiet(monkeypatch)
    db = _Db()
    _asked(db)
    rows, _ = _voice(db, monkeypatch, "  The investors.  ")
    assert [r["body"] for r in rows] == ["The investors.", "The investors. I'll keep them in mind.", SEE_YOU]
    assert db.takes.ctx["t1"]["audience"] == "The investors."
    assert will_question.open_question(db, "u") is None
    with pytest.raises(will_question.QuestionError) as no_question:
        _voice(db, monkeypatch, "The board")  # answered already: nothing open
    assert no_question.value.status == 404

    quiet = _Db()
    _asked(quiet)
    with pytest.raises(will_question.QuestionError) as nothing:
        _voice(quiet, monkeypatch, "")
    assert nothing.value.code == "NO_WORDS" and will_question.open_question(quiet, "u") is not None
