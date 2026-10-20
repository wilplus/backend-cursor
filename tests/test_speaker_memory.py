"""
GUARD    Will learns about each speaker: every answer to "Did this help?" and
         every Take's outcome is kept, a private note is rewritten from them,
         and Will reads that note in the chat and in the summary after a Take.
CATCHES
  C1  an answer that is no longer kept as an event, or no longer rewrites the note
  C2  the chat no longer handing the note to Will
  C3  the summary after a Take no longer hearing the note
  C4  a note carrying a number reaching Will, or the founder unable to correct it
  C5  the note or its events surviving the speaker's account deletion
IF REMOVED  Will stops learning about each speaker without anyone noticing
         (founder 2026-10-20: "a permanent part of our application").
PROVES   C1 -> test_an_answer_is_kept_and_rewrites_the_note
         C2 -> test_will_reads_the_note_in_the_chat
         C3 -> test_the_summary_after_a_take_hears_the_note
         C4 -> test_a_note_with_a_number_is_refused_and_the_founder_can_correct_it
         C5 -> test_the_note_and_its_events_go_with_the_account
"""
from types import SimpleNamespace

from services import chat_query, feedback_check, speaker_memory, take_summary

ARC, TAKE = "arc-1", "take-1"


class _Db:
    def __init__(self):
        self.events, self.memory, self.checks, self.thread = [], {}, {}, {}

    def insert_speaker_memory_event(self, row):
        self.events.append(row)
        return True

    def list_speaker_memory_events(self, user_id, limit=None):
        mine = [e for e in self.events if e["user_id"] == user_id]
        return mine[-limit:] if limit else mine

    def get_speaker_memory(self, user_id):
        return self.memory.get(user_id)

    def save_speaker_memory(self, row):
        self.memory[row["user_id"]] = row
        return True

    def save_take_feedback_check(self, row):
        key = (row["user_id"], row["take_session_id"])
        self.checks[key] = {**self.checks.get(key, {}), **row}
        return True

    def get_take_feedback_check(self, user_id, take):
        return self.checks.get((user_id, take))

    def insert_lounge_messages(self, user_id, rows):
        for r in rows:
            self.thread.setdefault((user_id, r["client_id"]), r)
        return rows


def _synchronous(monkeypatch, reply="- Struggles with closings.\n- Wants the why, not just the what."):
    """Run the rewrite now, on a fake model, without the authorization scope."""
    seen = {}

    def chat(**kw):
        seen["user"] = kw["user"]
        return SimpleNamespace(text=reply)
    monkeypatch.setattr("services.llm.chat_complete", chat)
    monkeypatch.setattr(speaker_memory, "_under_authority", lambda _db, _take, write: write())
    monkeypatch.setattr("services.parallel.start_scoped_thread", lambda fn, **kw: fn())
    return seen


def test_an_answer_is_kept_and_rewrites_the_note(monkeypatch):
    seen = _synchronous(monkeypatch)
    db = _Db()
    feedback_check.answer(db, user_id="u", arc_id=ARC, take_session_id=TAKE, choice="not_really")
    assert db.events[-1]["kind"] == "answer" and db.events[-1]["payload"] == {"helped": False}
    assert "did not really help" in seen["user"]
    assert db.memory["u"]["note"].startswith("- Struggles with closings.")
    assert db.memory["u"]["written_by"] == "ai"


def test_will_reads_the_note_in_the_chat(monkeypatch):
    db = _Db()
    db.memory["u"] = {"note": "- Struggles with closings."}
    captured = {}

    def answer_question(question, **kw):
        from services.master_doc_rag import render_app_context
        captured["prompt"] = render_app_context(kw["app_context"])
        return {"answer": "ok"}, {"intent": "faq"}
    monkeypatch.setattr("services.master_doc_rag.answer_question", answer_question)
    monkeypatch.setattr("services.chat_app_context.status_card", lambda *_a: None)
    monkeypatch.setattr(chat_query, "_admin_notes", lambda *_a: None)
    chat_query._librarian(db, "u", "how do I end better?", [], object())
    assert "WHAT HELPS THIS SPEAKER" in captured["prompt"]
    assert "Struggles with closings." in captured["prompt"]


def test_the_summary_after_a_take_hears_the_note():
    db = _Db()
    assert take_summary.memory_facts(db, "u") == []
    db.memory["u"] = {"note": "- Struggles with closings."}
    facts = take_summary.memory_facts(db, "u")
    assert len(facts) == 1 and "Struggles with closings." in facts[0] and "never quote" in facts[0]


def test_a_note_with_a_number_is_refused_and_the_founder_can_correct_it(monkeypatch):
    _synchronous(monkeypatch, reply="- Improved 20 percent on closings.")
    db = _Db()
    db.memory["u"] = {"note": "- Struggles with closings.", "written_by": "ai"}
    speaker_memory.record(db, "u", "take", {"practice": "better", "moved": "rose"}, TAKE)
    assert db.memory["u"]["note"] == "- Struggles with closings."  # the old note stays
    assert speaker_memory.set_note(db, "u", "Ask about the opening next.") == "- Ask about the opening next."
    assert db.memory["u"]["written_by"] == "founder"
    assert speaker_memory.set_note(db, "u", "Score 3 of 5") is None


def test_the_note_and_its_events_go_with_the_account():
    from services.data_purge_registry import DEPENDENCIES
    purged = {d.relation for d in DEPENDENCIES if d.locator_kind == "user"}
    assert {"speaker_memory", "speaker_memory_events"} <= purged
