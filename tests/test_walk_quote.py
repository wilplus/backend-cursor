"""
STORY    As a speaker who just said a better try of a sentence that doubted
         me, I want Will to show me my own words that prove otherwise, so
         that the better sentence feels true, and I want to be able to say
         "Not here".
OUTCOME
  O1  A sentence that doubted me gets one quote: the signed line and my own
      kept words, word for word with their date; the same sentence gets the
      same quote again, and any other sentence in that Take gets none (N268
      items 1, 2, 4).
  O2  When Will finds nothing that fits, or names something I don't keep,
      there is no quote: never invented.
  O3  "Not here" keeps the notebook out of every later walk until the Life
      Panel's switch turns it back on (N268 item 5).
  O4  Without the ring row or the notebook there is no quote and no switch;
      a Take that is not mine is refused (N268 item 3).
PROVES   O1 -> test_a_doubt_gets_one_quote_of_my_own_words_per_take
         O2 -> test_nothing_that_fits_means_no_quote
         O3 -> test_not_here_lasts_until_the_switch_turns_it_on
         O4 -> test_no_ring_no_notebook_or_not_my_take
WHY      Founder 2026-10-29, the Claude Code chat (N268).
"""
import pytest

from services import walk_quote as wq
from services.walk_quote import WalkQuoteError


class _Db:
    def __init__(self):
        self.notes = []

    def v2_get_session_by_id(self, session_id):
        return {"id": session_id, "user_id": "u" if session_id.startswith("t") else "other"}

    def list_voice_notes(self, user_id, limit=20):
        return self.notes[-limit:]


class _Store:
    """The Life Panel's store, in memory."""

    def __init__(self):
        self.quotes, self.settings = {}, {}
        self.strengths = [{"id": "s1", "title": "clear with numbers", "status": "kept"}]
        self.notes = [{"strength_id": "s1", "noted_on": "2026-10-14",
                       "body": "Walked the board through the budget. Nobody had a question left."}]
        self.why = {"vision": "Every village school teaches coding on one laptop."}

    def list_strengths(self, u): return self.strengths
    def strength_notes(self, u): return self.notes
    def get_why(self, u): return self.why
    def get_walk_quote(self, u, s): return dict(self.quotes.get((u, s), {}))
    def get_walk_quote_settings(self, u): return dict(self.settings.get(u, {}))

    def insert_walk_quote(self, u, s, fields):
        if (u, s) in self.quotes:
            return None
        self.quotes[(u, s)] = {**fields, "session_id": s}
        return dict(self.quotes[(u, s)])

    def mark_walk_quote_shown(self, u, s):
        self.quotes[(u, s)].setdefault("shown_at", "now")
        return True

    def save_walk_quote_settings(self, u, fields):
        self.settings.setdefault(u, {}).update(fields)
        return True


@pytest.fixture
def walk(monkeypatch):
    """The ring row and the notebook on for "u"; the model's picks queued."""
    store = _Store()
    monkeypatch.setattr("services.life_store." + "list_strengths", store.list_strengths)
    for name in ("strength_notes", "get_why", "get_walk_quote", "get_walk_quote_settings",
                 "insert_walk_quote", "mark_walk_quote_shown", "save_walk_quote_settings"):
        monkeypatch.setattr(f"services.life_store.{name}", getattr(store, name))
    on = {"ring": True, "notebook": True}
    monkeypatch.setattr("services.rings.feature_is_on_for_user",
                        lambda feature, user, database=None: on["ring"] and feature == wq.FEATURE and user == "u")
    monkeypatch.setattr("services.voice_notebook.consented", lambda database, user: on["notebook"])
    picks = []
    monkeypatch.setattr(wq, "_model", lambda user, user_id: {"pick": picks.pop(0)} if picks else {})
    return store, picks, on


DOUBT = "Sorry, I'm not really a numbers person, but revenue grew 18 percent this quarter."


def test_a_doubt_gets_one_quote_of_my_own_words_per_take(walk):
    store, picks, _ = walk
    db = _Db()
    picks.append("S1")
    quote = wq.ask(db, "u", "t4", DOUBT)
    assert quote == {"kind": "strength", "line": "That's your 💪 clear with numbers again.",
                     "quote": "Walked the board through the budget. Nobody had a question left.",
                     "said_on": "2026-10-14", "said": DOUBT, "first": True}
    assert wq.ask(db, "u", "t4", DOUBT)["quote"] == quote["quote"]
    assert wq.ask(db, "u", "t4", "It's just a small side project, okay?") is None
    wq.shown(db, "u", "t4")
    assert wq.replay(db, "u", "t4")["line"] == quote["line"]
    picks.append("V")
    later = wq.ask(db, "u", "t5", "It's just a small side project, I just wanted to show it.")
    assert later["line"] == "That's the voice of your 🔭 vision." and later["first"] is False


def test_nothing_that_fits_means_no_quote(walk):
    _, picks, _ = walk
    db = _Db()
    picks.extend([None, "S9"])
    assert wq.ask(db, "u", "t1", "We launch in March.") is None
    assert wq.ask(db, "u", "t2", DOUBT) is None


def test_not_here_lasts_until_the_switch_turns_it_on(walk):
    _, picks, _ = walk
    db = _Db()
    assert wq.set_on(db, "u", False) == {"available": True, "on": False}
    picks.append("S1")
    assert wq.ask(db, "u", "t6", DOUBT) is None
    assert wq.set_on(db, "u", True) == {"available": True, "on": True}
    assert wq.ask(db, "u", "t6", DOUBT)["line"] == "That's your 💪 clear with numbers again."


def test_no_ring_no_notebook_or_not_my_take(walk):
    _, picks, on = walk
    db = _Db()
    picks.append("S1")
    with pytest.raises(WalkQuoteError) as refused:
        wq.ask(db, "u", "x1", DOUBT)
    assert refused.value.status == 404
    on["notebook"] = False
    assert wq.ask(db, "u", "t7", DOUBT) is None
    assert wq.setting(db, "u") == {"available": False, "on": False}
    on["notebook"], on["ring"] = True, False
    assert wq.ask(db, "u", "t7", DOUBT) is None
