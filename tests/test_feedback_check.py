"""
STORY    As a speaker, I want to be asked "Did this help?" after the
         Feedback walk and have my answer kept, and as a coach I want a card
         when my speaker's goal changes, so that the founder learns whether
         feedback helps and coaches follow each speaker's goal.
OUTCOME
  O1  The question closes the Take summary, but waits when another offer is
      already there (one ask at a time).
  O2  "Yes" is kept and answered once with the signed words; a second tap
      changes nothing.
  O3  "No" asks what would help; my next typed message is kept as
      that answer (even if it sounds like a goal change), then the chat is
      ordinary again.
  O4  "Skip" ends it with no answer kept; typing a button's words counts as
      tapping it, and any other message goes to the chat as usual.
  O5  A new goal is kept in the history and every coach except the speaker
      gets one card a day showing before and now; no change, no card.
  O6  A Take that went fine is not asked; one whose practice did not land,
      or whose voice dipped, is (founder 2026-10-20).
  O7  The founder's weekly note says how often the voice rose, how many
      answered, and what would help, in the speakers' own words.
PROVES   O1 -> test_the_question_closes_the_summary_but_waits_when_another_offer_is_there
         O2 -> test_yes_is_kept_and_answered_with_the_signed_words_once
         O3 -> test_not_really_asks_what_was_missing_and_the_chat_keeps_the_answer
         O4 -> test_skip_ends_it_without_an_answer,
               test_typing_a_button_counts_as_tapping_it_and_anything_else_goes_to_will
         O5 -> test_a_new_goal_is_kept_and_every_coach_but_the_speaker_gets_one_card_a_day
         O6 -> test_a_take_that_went_fine_is_not_asked
         O7 -> test_the_weekly_note_says_what_was_missing_in_their_words
WHY      WIL-74, founder 2026-10-19 (words signed the same day; the question
         and the thank-you simplified by the founder, 2026-10-20).
"""
from services import chat_query, feedback_check, goal_history
from services.feedback_check import COPY

ARC, TAKE = "arc-1", "take-1"


class _Db:
    def __init__(self):
        self.thread = {}
        self.checks = {}
        self.goals = []
        self.coaches = []

    # lounge_messages
    def insert_lounge_messages(self, user_id, rows):
        for r in rows:
            self.thread.setdefault((user_id, r["client_id"]), {**r, "user_id": user_id})
        return [self.thread[(user_id, r["client_id"])] for r in rows]

    def get_lounge_messages_page(self, user_id, limit=50):
        mine = [r for (u, _), r in self.thread.items() if u == user_id]
        return list(reversed(mine))[:limit]  # newest first

    def get_lounge_message_by_client_id(self, user_id, client_id):
        return self.thread.get((user_id, client_id))

    def rewrite_lounge_message(self, user_id, client_id, body, metadata):
        row = self.thread[(user_id, client_id)]
        row.update(body=body, metadata=metadata)
        return row

    # take_feedback_checks
    def save_take_feedback_check(self, row):
        key = (row["user_id"], row["take_session_id"])
        self.checks[key] = {**self.checks.get(key, {}), **row}
        return True

    def get_take_feedback_check(self, user_id, take):
        return self.checks.get((user_id, take))

    # user_goal_history
    def insert_goal_history(self, row):
        self.goals.append(row)
        return True

    def active_coach_user_ids(self):
        return self.coaches

    def bodies(self, user_id="u"):
        return [r["body"] for r in reversed(self.get_lounge_messages_page(user_id))]


def _summary_batch(db, *, whatsapp: bool):
    batch = [{"client_id": "s", "role": "bot", "kind": "cadence", "body": "Summary.",
              "metadata": {"summary": True}, "client_created_at": "t"}]
    if whatsapp:
        batch.append({"client_id": "w", "role": "bot", "kind": "text", "body": "WhatsApp?",
                      "metadata": {"offer": "whatsapp"}, "client_created_at": "t"})
    batch += feedback_check.ask_rows(db, user_id="u", arc_id=ARC, take_session_id=TAKE,
                                     batch=batch, at="t")
    db.insert_lounge_messages("u", batch)
    return batch


def _turn(db, monkeypatch, question):
    """One typed chat turn, through the chat's whole chain of voices."""
    monkeypatch.setattr("services.db.db", db, raising=False)
    monkeypatch.setattr(chat_query, "_librarian",
                        lambda *a, **k: ({"answer": "librarian"}, "faq"))
    monkeypatch.setattr(chat_query, "thread_history", lambda *a, **k: [])
    db.insert_lounge_messages("u", [{"client_id": f"me-{question}", "role": "user",
                                     "kind": "text", "body": question,
                                     "metadata": None, "client_created_at": "t"}])
    return chat_query.answer_chat(db, user_id="u", question=question, history=[],
                                  context=None, app_config=object(),
                                  finalize=lambda resp, intent: (resp, intent))


def test_the_question_closes_the_summary_but_waits_when_another_offer_is_there():
    db = _Db()
    batch = _summary_batch(db, whatsapp=False)
    assert batch[-1]["body"] == COPY["ask"]
    assert batch[-1]["metadata"]["offer"] == "feedback_check"

    other = _Db()
    batch = _summary_batch(other, whatsapp=True)
    assert COPY["ask"] not in [r["body"] for r in batch]  # one ask at a time


def test_yes_is_kept_and_answered_with_the_signed_words_once():
    db = _Db()
    _summary_batch(db, whatsapp=False)
    rows = feedback_check.answer(db, user_id="u", arc_id=ARC, take_session_id=TAKE,
                                 choice="yes")
    assert [r["body"] for r in rows] == ["Yes", COPY["thanks"]]
    assert db.checks[("u", TAKE)]["helped"] is True
    assert feedback_check.answer(db, user_id="u", arc_id=ARC, take_session_id=TAKE,
                                 choice="not_really") == []  # a second tap changes nothing


def test_not_really_asks_what_was_missing_and_the_chat_keeps_the_answer(monkeypatch):
    db = _Db()
    _summary_batch(db, whatsapp=False)
    rows = feedback_check.answer(db, user_id="u", arc_id=ARC, take_session_id=TAKE,
                                 choice="not_really")
    assert rows[-1]["body"] == COPY["missing"]
    assert rows[-1]["metadata"]["suggested_action"] == "feedback_skip"

    # "I want my goal to be shorter answers" would be a goal change anywhere
    # else; under "What was missing?" it is the answer.
    resp, intent = _turn(db, monkeypatch, "Change my goal: it never said why the opening dragged")
    assert intent == "feedback_check" and resp["answer"] == COPY["thanks"]
    assert db.checks[("u", TAKE)]["missing"].startswith("Change my goal")

    resp, intent = _turn(db, monkeypatch, "what next?")
    assert intent == "faq"  # answered once; the chat is the chat again


def test_skip_ends_it_without_an_answer():
    db = _Db()
    _summary_batch(db, whatsapp=False)
    feedback_check.answer(db, user_id="u", arc_id=ARC, take_session_id=TAKE, choice="not_really")
    rows = feedback_check.answer(db, user_id="u", arc_id=ARC, take_session_id=TAKE, choice="skip")
    assert [r["body"] for r in rows] == ["Skip", COPY["thanks"]]
    assert db.checks[("u", TAKE)]["skipped"] is True and not db.checks[("u", TAKE)].get("missing")


def test_typing_a_button_counts_as_tapping_it_and_anything_else_goes_to_will(monkeypatch):
    db = _Db()
    _summary_batch(db, whatsapp=False)
    resp, intent = _turn(db, monkeypatch, "How do I sound calmer?")
    assert intent == "faq"
    resp, intent = _turn(db, monkeypatch, "No.")
    assert intent == "feedback_check" and resp["answer"] == COPY["missing"]
    assert db.checks[("u", TAKE)]["helped"] is False


def test_a_new_goal_is_kept_and_every_coach_but_the_speaker_gets_one_card_a_day(monkeypatch):
    monkeypatch.setattr("services.coach_pseudonym.coach_pseudonym", lambda _u: "Playful Octopus")
    db = _Db()
    db.coaches = ["coach", "u"]
    assert goal_history.record(db, "u", "Speak slower", "Open with a story", "chat")
    assert goal_history.record(db, "u", "Open with a story", "Close with a question", "profile")
    assert [g["goal"] for g in db.goals] == ["Open with a story", "Close with a question"]

    cards = db.get_lounge_messages_page("coach")
    assert len(cards) == 1 and not db.get_lounge_messages_page("u")
    assert cards[0]["body"] == ("Playful Octopus has a new goal\n"
                                "Before: Speak slower\nNow: Close with a question")
    assert cards[0]["about_user_id"] == "u"  # deleted with the speaker

    assert not goal_history.record(db, "u", "Same", "Same", "chat")  # no change, no card


def test_a_take_that_went_fine_is_not_asked():
    """Founder 2026-10-20: let the next Take answer it; ask only when the
    practice did not land or the voice dipped."""
    db = _Db()
    batch = [{"client_id": "s", "role": "bot", "kind": "cadence", "body": "Summary.",
              "metadata": {"summary": True}, "client_created_at": "t"}]
    fine = feedback_check.looks_off("better", "rose")
    assert feedback_check.ask_rows(db, user_id="u", arc_id=ARC, take_session_id=TAKE,
                                   batch=batch, at="t", off=fine) == []
    assert feedback_check.looks_off("not_yet", "rose")
    assert feedback_check.looks_off("better", "dipped")


def test_the_weekly_note_says_what_was_missing_in_their_words():
    from services.feedback_digest import note
    words = note([{"moved": "rose"}, {"moved": "held"}, {"moved": None}],
                 [{"helped": False, "missing": "Why my close felt rushed"},
                  {"helped": True}, {"helped": None, "skipped": False}])
    assert words.splitlines() == [
        "Feedback, the last 7 days",
        "The voice rose since the last Take in 1 of 2 Takes",
        "Asked \"Did this help?\": 2 · it helped: 1",
        "What would help:",
        "“Why my close felt rushed”",
    ]
