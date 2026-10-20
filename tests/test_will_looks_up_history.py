"""
STORY    Before Will answers in the chat, he looks up the speaker's own
         history (their Takes' transcripts, what their coach sent them, what
         they told him before) and reads the few pieces that best match the
         question as a private block (founder 2026-10-20, step 1).
OUTCOME
  O1  only this speaker's rows can reach Will, never another speaker's,
      never Will's own replies, never an answer to "Did this help?"
  O2  a coach's unsent word or draft never reaches Will; what they sent does
  O3  the piece that matches the question best comes first
  O4  a failing read gives no block and no error: Will answers as today
  O5  a signed-in speaker's chat hands the block to Will; a visitor's does not
  O6  a Take whose processing authorization is gone (withdrawn, expired)
      never reaches Will, nor what the coach sent on it; a failed check
      lets no Take through
PROVES   O1 -> test_only_this_speakers_own_words_reach_will
         O2 -> test_only_what_the_coach_sent_reaches_will
         O3 -> test_the_most_relevant_piece_comes_first
         O4 -> test_a_failing_read_gives_no_block_and_no_error
         O5 -> test_will_reads_the_lookup_in_the_chat
         O6 -> test_a_take_whose_authorization_is_gone_never_reaches_will
WHY      Will's answers should build on what this speaker already said and
         heard, without anything private to someone else, or to the coach,
         leaking in.
"""
from services import chat_query, speaker_memory
from services.speaker_lookup import lookup

ME, OTHER = "user-me", "user-other"
QUESTION = "How do I make my closing land better?"


class _Takes:
    def __init__(self, rows):
        self.rows = rows

    def list_speaker_take_transcripts(self, user_id, *, limit):
        return [r for r in self.rows if r["user_id"] == user_id][:limit]


def _take(take_id, user_id, index, words, at):
    return {"id": take_id, "user_id": user_id, "arc_id": None, "take_index": index,
            "created_at": at, "analysis_state": "ready",
            "slide_transcripts": [{"index": 0, "transcript": words}]}


def _row(role, body, at, meta=None):
    return {"role": role, "kind": "text", "body": body, "metadata": meta,
            "client_created_at": at}


class _Db:
    """The speaker's rows, newest Take first; the thread oldest first."""
    client = None

    def __init__(self, takes=(), words=(), answers=(), thread=None):
        self.takes = _Takes(list(takes))
        self.words, self.answers, self.thread = list(words), list(answers), thread or {}
        self.memory = {}

    def list_sent_coach_take_words(self, ids, *, limit):
        # Every row on the Takes, shared or not: the lookup must hold the line.
        return [w for w in self.words if w["take_session_id"] in ids][:limit]

    def list_shared_moment_answers(self, user_id, ids, *, limit):
        return [a for a in self.answers if a["take_session_id"] in ids][:limit]

    def get_lounge_messages_page(self, user_id, *, limit):
        return list(reversed(self.thread.get(user_id, [])))[:limit + 1]

    def get_speaker_memory(self, user_id):
        return self.memory.get(user_id)


def _padding(n=24):
    """The newest rows: the conversation Will already reads."""
    return [_row("user" if i % 2 == 0 else "bot", "hello there", f"2026-10-20T12:{i:02d}")
            for i in range(n)]


def test_only_this_speakers_own_words_reach_will():
    thread = {ME: [
        _row("user", "My closing always fizzles out", "2026-10-19T09:00"),
        _row("bot", "Your closing could land with one clear ask", "2026-10-19T09:01"),
        _row("bot", "What would help?", "2026-10-19T10:00", {"feedback_check": "missing"}),
        _row("user", "A better closing example", "2026-10-19T10:01"),
        _row("bot", "Thanks!", "2026-10-19T10:02", {"feedback_check": "missing_answered"}),
        *_padding()]}
    db = _Db(takes=[_take("t-other", OTHER, 1, "my closing lands better now", "2026-10-18")],
             thread=thread)
    found = lookup(db, ME, QUESTION)
    assert [(s.label, s.text) for s in found] == [
        ("you said earlier", "My closing always fizzles out")]


def test_only_what_the_coach_sent_reaches_will():
    db = _Db(
        takes=[_take("t2", ME, 2, "and that is the end of my talk", "2026-10-19")],
        words=[{"take_session_id": "t2", "text": "Slow down for the closing line.",
                "shared_at": "2026-10-19T12:00", "video_ref": "v.mp4",
                "transcript": "Land the closing with a pause."},
               {"take_session_id": "t2", "text": "Unsent: your closing is weak.",
                "draft_text": "Draft: closing closing closing", "shared_at": None}],
        answers=[{"take_session_id": "t2", "owner_user_id": ME, "resolution": "note_written",
                  "answer_text": "A shared closing note", "shared_at": "2026-10-19T13:00"},
                 {"take_session_id": "t2", "owner_user_id": ME, "resolution": "note_written",
                  "answer_text": "An unshared closing note", "shared_at": None}])
    texts = {s.text for s in lookup(db, ME, QUESTION)}
    assert texts == {"Slow down for the closing line.", "Land the closing with a pause.",
                     "A shared closing note"}


def test_the_most_relevant_piece_comes_first():
    db = _Db(takes=[
        _take("t3", ME, 3, "My closing tries to land the main point", "2026-10-19"),
        _take("t2", ME, 2, "Make the closing land better than the opening", "2026-10-18"),
        _take("t1", ME, 1, "This opening has no story at all", "2026-10-17")])
    found = lookup(db, ME, QUESTION)
    assert [s.label for s in found] == ["Take 2 transcript", "Take 3 transcript"]
    assert all(len(s.text) <= 201 for s in found)


class _Broken(_Db):
    def __getattribute__(self, name):
        if name in ("takes", "get_lounge_messages_page", "get_speaker_memory"):
            raise RuntimeError("database down")
        return super().__getattribute__(name)


def _chat_prompt(monkeypatch, db, user_id):
    captured = {}

    def answer_question(question, **kw):
        from services.master_doc_rag import render_app_context
        captured["prompt"] = render_app_context(kw["app_context"])
        return {"answer": "ok"}, {"intent": "faq"}
    monkeypatch.setattr("services.master_doc_rag.answer_question", answer_question)
    monkeypatch.setattr("services.chat_app_context.status_card", lambda *_a: None)
    monkeypatch.setattr("services.chat_app_context.signup_gate", lambda *_a: None)
    monkeypatch.setattr(chat_query, "_admin_notes", lambda *_a: None)
    reply, _ = chat_query._librarian(db, user_id, QUESTION, [], object())
    return reply, captured["prompt"]


def test_a_failing_read_gives_no_block_and_no_error(monkeypatch):
    assert speaker_memory.history_for(_Broken(), ME, QUESTION) == ""
    reply, prompt = _chat_prompt(monkeypatch, _Broken(), ME)
    assert reply["answer"] == "ok"
    assert "OWN HISTORY" not in prompt


def test_will_reads_the_lookup_in_the_chat(monkeypatch):
    db = _Db(takes=[_take("t2", ME, 2, "Make the closing land with one ask", "2026-10-18")])
    db.memory[ME] = {"note": "- Struggles with closings."}
    _, prompt = _chat_prompt(monkeypatch, db, ME)
    assert "Struggles with closings." in prompt
    assert "FROM THIS SPEAKER'S OWN HISTORY" in prompt
    assert '• Take 2 transcript: "Make the closing land with one ask"' in prompt
    assert 'Never repeat their answers to "Did this help?"' in prompt
    _, visitor = _chat_prompt(monkeypatch, db, None)
    assert "OWN HISTORY" not in visitor


def test_a_take_whose_authorization_is_gone_never_reaches_will(monkeypatch):
    from services.processing_authorization import ProcessingAuthorizationService as Service
    monkeypatch.setenv("PLF1_PROCESSING_AUTHORIZATION_MODE", "enforce")
    monkeypatch.setattr(Service, "resolve_acquisition_principal",
                        lambda self, owner, **kw: owner)
    monkeypatch.setattr(Service, "status", lambda self, principal: (
        {"authorized": True, "pooled_learning_eligible": False} if principal == "p-live"
        else {"authorized": False, "code": "PROCESSING_AUTHORIZATION_WITHDRAWN"}))
    live = {**_take("t2", ME, 2, "My closing lands with one ask", "2026-10-19"),
            "owner_principal_id": "p-live"}
    gone = {**_take("t1", ME, 1, "My closing was rushed", "2026-10-18"),
            "owner_principal_id": "p-gone"}
    db = _Db(takes=[live, gone],
             words=[{"take_session_id": "t1", "text": "Closing: breathe first.",
                     "shared_at": "2026-10-18T12:00"}])
    assert [s.text for s in lookup(db, ME, QUESTION)] == ["My closing lands with one ask"]

    def broken(self, principal):
        raise RuntimeError("authority unreachable")
    monkeypatch.setattr(Service, "status", broken)
    monkeypatch.setattr(Service, "require_current", lambda self, *a, **kw: broken(self, a))
    assert lookup(db, ME, QUESTION) == []
