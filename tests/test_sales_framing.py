"""
STORY    As a salesperson, I want a lost deal I note down to point me at the
         step that stalled and one change to it, never at me, so that the
         next call goes better and the note does not feel like a verdict.
OUTCOME
  O1  A note about a sale that stalled gets "Which step did it stall at?"
      once, under its "Noted.", with the sale's four steps to tap (N241 P2).
  O2  A tap on a step gets that step as my bubble and one change to that
      step from Will's guide; even when the model cannot answer, the guide's
      own change for that step; a second tap changes nothing.
  O3  A sales note gets the step question, never also the worry answer; a
      note that is not a sale goes on to the worry answer.
  O4  Without the ring row, or for a crisis note, nothing is asked.
PROVES   O1 -> test_a_stalled_sale_asks_which_step_once
         O2 -> test_a_step_gets_one_change_and_only_once
         O3 -> test_a_sale_is_never_also_sorted_as_a_worry
         O4 -> test_no_ring_or_a_crisis_asks_nothing
WHY      Linear WIL-114; Will's guide signed 2026-10-29 (N258).
"""
import pytest

from services import sales_framing as sf


class _Db:
    def __init__(self):
        self.thread = {}
        self.notes = []

    def insert_lounge_messages(self, user_id, rows):
        for r in rows:
            self.thread.setdefault((user_id, r["client_id"]), {**r, "user_id": user_id})
        return [self.thread[(user_id, r["client_id"])] for r in rows]

    def get_lounge_messages_page(self, user_id, limit=50):
        mine = [r for (u, _), r in self.thread.items() if u == user_id]
        return list(reversed(mine))[:limit]

    def list_voice_notes(self, user_id, limit=20):
        return [n for n in self.notes if n["user_id"] == user_id][-limit:]

    def note(self, text, user_id="u"):
        self.notes.append({"id": f"n{len(self.notes) + 1}", "user_id": user_id, "text_clean": text})


@pytest.fixture
def will(monkeypatch):
    """Both ring rows on for "u", nobody onboarded; the model's answers per
    spec are queued, and the worry answer is a stub that says it ran."""
    monkeypatch.setattr("services.rings.feature_is_on_for_user",
                        lambda feature, user, database=None: user == "u")
    monkeypatch.setattr("services.plan_flow.onboarding", lambda database, user: False)
    answers = {"SPEC_SALES_NOTE": [], "SPEC_SALES_CHANGE": []}

    def model(task, user, user_id, spec_name):
        queue = answers[spec_name]
        if not queue:
            raise RuntimeError("provider down")
        return queue.pop(0)

    monkeypatch.setattr(sf, "_model", model)
    worries = []
    monkeypatch.setattr("services.in_control.after_note",
                        lambda database, user_id: worries.append(user_id) or ["worry"])
    return answers, worries


def _ask(rows):
    return [r for r in rows if (r["metadata"] or {}).get("offer") == sf.OFFER]


def test_a_stalled_sale_asks_which_step_once(will):
    answers, _ = will
    db = _Db()
    db.note("# Lost the Acme deal. They went with the cheaper one")
    answers["SPEC_SALES_NOTE"].append({"sales": True})
    rows = sf.after_note(db, "u")
    assert [r["body"] for r in rows] == ["Which step did it stall at?"]
    assert rows[0]["metadata"] == {"offer": "sales_step", "sales_note": "n1"}
    answers["SPEC_SALES_NOTE"].append({"sales": True})
    sf.after_note(db, "u")
    assert len(_ask(list(db.thread.values()))) == 1  # the same note asks once


def test_a_step_gets_one_change_and_only_once(will):
    answers, _ = will
    db = _Db()
    db.note("# Lost the Acme deal. They went with the cheaper one")
    answers["SPEC_SALES_NOTE"].append({"sales": True})
    sf.after_note(db, "u")
    change = ["Their budget is a variable.",
              "The offer is a constant: next time, ask what the cheaper option misses before you send the price."]
    answers["SPEC_SALES_CHANGE"].append({"lines": change})
    rows = sf.answer(db, "u", "n1", "offer")
    assert [r["body"] for r in rows] == ["The offer"] + change
    assert rows[0]["role"] == "user"
    assert sf.answer(db, "u", "n1", "opening") == []  # answered once

    db.note("# The Bauer proposal went quiet")
    answers["SPEC_SALES_NOTE"].append({"sales": True})
    sf.after_note(db, "u")
    rows = sf.answer(db, "u", "n2", "follow_up")  # the model is down
    assert [r["body"] for r in rows] == ["The follow-up", "Book the next step before the call ends."]

    with pytest.raises(sf.SalesError):
        sf.answer(db, "u", "n2", "closing")
    with pytest.raises(sf.SalesError):
        sf.answer(db, "u", "n9", "offer")  # never asked


def test_a_sale_is_never_also_sorted_as_a_worry(will):
    answers, worries = will
    db = _Db()
    db.note("# Lost the Acme deal")
    answers["SPEC_SALES_NOTE"].append({"sales": True})
    rows = sf.answers_after_note(db, "u")
    assert [r["body"] for r in rows] == ["Which step did it stall at?"] and not worries

    db.note("# The hotel is awful")
    answers["SPEC_SALES_NOTE"].append({"sales": False})
    assert sf.answers_after_note(db, "u") == ["worry"] and worries == ["u"]


def test_no_ring_or_a_crisis_asks_nothing(will):
    answers, _ = will
    db = _Db()
    db.note("# Lost the deal, I want to die", user_id="u")
    assert sf.after_note(db, "u") == []
    db.note("# Lost the Acme deal", user_id="someone")
    assert sf.after_note(db, "someone") == []
    with pytest.raises(sf.SalesError):
        sf.answer(db, "someone", "n2", "offer")
    assert not db.thread and answers["SPEC_SALES_NOTE"] == []
