"""
GUARD    Will learns about each speaker: every answer to "Did this help?",
         every Take's outcome and transcript, what their coach sent them and
         their own chat messages are kept, a private note is rewritten from
         them, and Will reads that note in the chat and in the summary after
         a Take.
CATCHES
  C1  an answer that is no longer kept as an event, or no longer rewrites the note
  C2  the chat no longer handing the note to Will
  C3  the summary after a Take no longer hearing the note
  C4  a note carrying a number reaching Will, the founder unable to correct
      it, or a number in a transcript reaching the model's input
  C5  the note or its events surviving the speaker's account deletion
  C6  a Take's transcript, a word or moment answer the coach sent, or the
      speaker's own chat message no longer kept, or no longer reaching the
      note's input
  C7  a coach's unsent word or answer, Will's own reply, or an answer to
      "Did this help?" kept as something Will learns from
  C8  an event surviving the erasure of its project or its Take
  C9  a line from a Take whose authorization is gone, or a chat line without
      current authority, reaching the model; a failed check letting any through
IF REMOVED  Will stops learning about each speaker without anyone noticing
         (founder 2026-10-20: "a permanent part of our application").
PROVES   C1 -> test_an_answer_is_kept_and_rewrites_the_note
         C2 -> test_will_reads_the_note_in_the_chat
         C3 -> test_the_summary_after_a_take_hears_the_note
         C4 -> test_a_note_with_a_number_is_refused_and_the_founder_can_correct_it
         C5 -> test_the_note_and_its_events_go_with_the_account
         C6 -> test_transcripts_coach_words_and_chat_reach_the_note
         C7 -> test_drafts_wills_replies_and_feedback_answers_are_never_learned
         C8 -> test_an_erased_project_or_take_takes_its_events
         C9 -> test_lines_whose_authorization_is_gone_never_reach_the_model
"""
import re
from types import SimpleNamespace

from services import chat_query, feedback_check, speaker_memory, take_summary

ARC, TAKE = "arc-1", "take-1"


class _Db:
    client = None

    def __init__(self):
        self.events, self.memory, self.checks, self.thread = [], {}, {}, {}
        self.sessions = {TAKE: {"id": TAKE, "user_id": "u", "arc_id": ARC}}
        self.rows = []   # the Lounge thread, newest first

    def v2_get_session_by_id(self, take):
        return self.sessions.get(take)

    def count_speaker_memory_events(self, user_id, *, kind, since):
        return sum(1 for e in self.events if e["user_id"] == user_id and e["kind"] == kind)

    def get_lounge_messages_page(self, user_id, *, limit):
        return self.rows[:limit]

    def get_owner_principal_for_user(self, user_id):
        return {"id": f"principal-of-{user_id}"}

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
    monkeypatch.setattr(speaker_memory, "_under_authority", lambda _db, _uid, _take, write: write())
    monkeypatch.setattr("services.parallel.start_scoped_thread", lambda fn, **kw: fn())
    monkeypatch.setattr("services.speaker_lookup.hidden_arcs", lambda _db, _takes: set())
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
    seen = _synchronous(monkeypatch, reply="- Improved 20 percent on closings.")
    db = _Db()
    db.memory["u"] = {"note": "- Struggles with closings.", "written_by": "ai"}
    speaker_memory.record(db, "u", "transcript",
                          {"opening": "We grew 20% in 2025, three times faster"}, TAKE)
    # The model reads the words, never the digits, so its note is not refused for them.
    assert "three times faster" in seen["user"] and not re.search(r"\d|%", seen["user"])
    speaker_memory.record(db, "u", "take", {"practice": "better", "moved": "rose"}, TAKE)
    assert db.memory["u"]["note"] == "- Struggles with closings."  # the old note stays
    assert speaker_memory.set_note(db, "u", "Ask about the opening next.") == "- Ask about the opening next."
    assert db.memory["u"]["written_by"] == "founder"
    assert speaker_memory.set_note(db, "u", "Score 3 of 5") is None


def test_the_note_and_its_events_go_with_the_account():
    from services.data_purge_registry import DEPENDENCIES
    purged = {d.relation for d in DEPENDENCIES if d.locator_kind == "user"}
    assert {"speaker_memory", "speaker_memory_events"} <= purged


# ── step 2 (founder 2026-10-20): transcripts, coach words and chat ──────────

def _coach(monkeypatch, db):
    """The coach's two save paths, with what they tell the speaker left out."""
    from services import coach_take_word, exercise_coach_requests as requests
    monkeypatch.setattr(coach_take_word, "_tell_the_speaker", lambda *a, **kw: None)
    monkeypatch.setattr(coach_take_word, "_the_pair", lambda *a, **kw: None)
    monkeypatch.setattr(requests, "_file_answer", lambda *a, **kw: None)
    monkeypatch.setattr(requests, "_tell_the_speaker", lambda *a, **kw: None)
    monkeypatch.setattr(requests, "coach_request_payload", lambda row, _db: dict(row))

    def upsert(**kw):
        row = {"take_session_id": kw["take_session_id"], "text": kw["text"],
               "video_ref": None, "updated_at": "t1",
               "shared_at": "t1" if kw["share"] else None}
        return row
    db.upsert_coach_take_word = upsert
    db.resolve_exercise_coach_request = lambda **kw: {
        "id": kw["request_id"], "take_session_id": TAKE, "owner_user_id": "u",
        "resolution": kw["resolution"], "answer_text": kw["answer_text"],
        "shared_at": "t2" if kw["share"] else None}

    def word(text, share):
        coach_take_word.save_take_word(db, take_session_id=TAKE, coach_id="c",
                                       body={"text": text, "share": share})

    def answer(text, share):
        requests.resolve_request(db, {"id": "r1", "take_session_id": TAKE, "owner_user_id": "u"},
                                 {"resolution": "note_written", "answer_text": text,
                                  "share_with_user": share}, "c")
    return word, answer


def _chat(monkeypatch, db, question, reply="Try ending on one clear ask."):
    def answer_question(_question, **kw):
        return {"answer": reply}, {"intent": "faq"}
    monkeypatch.setattr("services.db.db", db)
    monkeypatch.setattr("services.master_doc_rag.answer_question", answer_question)
    monkeypatch.setattr("services.chat_app_context.status_card", lambda *_a: None)
    monkeypatch.setattr(chat_query, "_admin_notes", lambda *_a: None)
    return chat_query.answer_chat(
        db, user_id="u", question=question, history=[], context=None, app_config=object(),
        finalize=lambda resp, intent: chat_query.finish_chat_turn(
            db, resp, user_id="u", question=question, persist_thread=False,
            user_client_id=None, user_created_at=None, intent=intent))


def test_transcripts_coach_words_and_chat_reach_the_note(monkeypatch):
    seen = _synchronous(monkeypatch)
    db = _Db()
    from services.lab_recording import _learn_from_the_transcript
    _learn_from_the_transcript(db, session_id=TAKE, user_id="u", spoken=True,
                               text="Good morning everyone, today I want to talk about trust.")
    word, answer = _coach(monkeypatch, db)
    word("Slow down for the closing line.", share=True)
    answer("Pause before the ask.", share=True)
    _chat(monkeypatch, db, "How do I stop rushing my closing?")
    assert [(e["kind"], e["take_session_id"], e["arc_id"]) for e in db.events] == [
        ("transcript", TAKE, ARC), ("coach_word", TAKE, ARC), ("coach_word", TAKE, ARC),
        ("chat", None, None)]
    for line in ('In a take they said: "Good morning everyone, today I want to talk about trust."',
                 'Their coach wrote to them: "Slow down for the closing line."',
                 'Their coach answered one of their moments: "Pause before the ask."',
                 'They wrote in the chat: "How do I stop rushing my closing?"'):
        assert line in seen["user"]


def test_drafts_wills_replies_and_feedback_answers_are_never_learned(monkeypatch):
    _synchronous(monkeypatch)
    db = _Db()
    word, answer = _coach(monkeypatch, db)
    word("Unsent: your closing is weak.", share=False)
    answer("An unshared note.", share=False)
    assert db.events == []
    _chat(monkeypatch, db, "How do I end better?", reply="Will's own reply")
    # "Did this help?" -> "Not really" -> "What would help?" is open: the answer is an answer.
    db.rows = [{"role": "bot", "kind": "text", "body": "What would help?",
                "metadata": {"feedback_check": "missing", "take_session_id": TAKE,
                             "arc_id": ARC}}]
    db.checks[("u", TAKE)] = {"helped": False}
    _chat(monkeypatch, db, "A clearer closing example")
    assert [e["kind"] for e in db.events] == ["chat", "answer"]
    assert db.events[0]["payload"] == {"excerpt": "How do I end better?"}
    assert not any("Will's own reply" in str(e["payload"]) for e in db.events)


def test_an_erased_project_or_take_takes_its_events():
    from services.data_purge import DataPurgeOrchestrator
    from services.data_purge_project_scope import ProjectPurgeOrchestrator
    from tests.test_purge_user_locators import PurgeDb, erase
    rows = [{"id": "on-take", "user_id": "user-1", "take_session_id": "take-1"},
            {"id": "on-project", "user_id": "user-1", "arc_id": "project-1"},
            {"id": "elsewhere", "user_id": "user-1", "take_session_id": "take-9",
             "arc_id": "project-9"},
            {"id": "chat", "user_id": "user-1"}]
    project = PurgeDb({"speaker_memory_events": rows}, kind="project_deletion")
    erase(project, ProjectPurgeOrchestrator)
    assert [r["id"] for r in project.tables["speaker_memory_events"]] == ["elsewhere", "chat"]
    account = PurgeDb({"speaker_memory_events": rows})
    erase(account, DataPurgeOrchestrator)
    assert account.tables["speaker_memory_events"] == []
    # A Take its speaker deletes: its events go and the note is written again.
    db = _Db()
    deleted = []
    db.delete_speaker_memory_events_for_takes = lambda uid, ids: deleted.append((uid, ids))
    db.memory["u"] = {"note": "- Their coach said the closing rushes."}
    speaker_memory.forget(db, "u", [TAKE])
    assert deleted == [("u", [TAKE])] and db.memory["u"]["note"] == ""


def test_lines_whose_authorization_is_gone_never_reach_the_model(monkeypatch):
    from services.processing_authorization import ProcessingAuthorizationService as Service
    seen = _synchronous(monkeypatch)
    monkeypatch.setenv("PLF1_PROCESSING_AUTHORIZATION_MODE", "enforce")
    monkeypatch.setattr(Service, "resolve_acquisition_principal", lambda self, owner, **kw: owner)
    monkeypatch.setattr(Service, "status", lambda self, principal: (
        {"authorized": True, "pooled_learning_eligible": False}
        if principal in ("p-live", "principal-of-u")
        else {"authorized": False, "code": "PROCESSING_AUTHORIZATION_WITHDRAWN"}))
    db = _Db()
    db.sessions = {"t-live": {"id": "t-live", "user_id": "u", "owner_principal_id": "p-live"},
                   "t-gone": {"id": "t-gone", "user_id": "u", "owner_principal_id": "p-gone"}}
    db.events = [
        {"user_id": "u", "kind": "transcript", "take_session_id": "t-live",
         "payload": {"opening": "My closing lands with one ask"}},
        {"user_id": "u", "kind": "coach_word", "take_session_id": "t-gone",
         "payload": {"source": "take_word", "excerpt": "Breathe before the closing."}},
        {"user_id": "u", "kind": "chat", "take_session_id": None,
         "payload": {"excerpt": "How do I end better?"}}]
    speaker_memory.refresh(db, "u", None)
    assert "My closing lands with one ask" in seen["user"]
    assert "How do I end better?" in seen["user"]
    assert "Breathe before the closing." not in seen["user"]

    def broken(self, *_a, **_kw):
        raise RuntimeError("authority unreachable")
    monkeypatch.setattr(Service, "status", broken)
    monkeypatch.setattr(Service, "require_current", broken)
    seen.clear()
    assert speaker_memory.refresh(db, "u", None) is False
    assert "user" not in seen  # nothing went to the model
