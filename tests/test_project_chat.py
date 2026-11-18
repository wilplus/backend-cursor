"""
STORY    As a speaker who has just completed a Take, I want Project Chat to
         remember this project's feedback, audience and desired impact without
         mixing in another project, so that the next conversation helps me act
         on the feedback.
OUTCOME
  O1  The opening is grounded in the current transcript, surfaced feedback,
      deck and Ideal Text, while sparse evidence is acknowledged rather than
      invented.
  O2  Audience and desired-impact setup skips known values, persists new
      answers structurally, and asks one clear question at a time.
  O3  English, Polish, formal and playful turns use one bounded model path;
      lightweight acknowledgements use the fast path.
  O4  Project Chat reads and writes only the owner-scoped arc and remembers
      scoped follow-ups without exposing the global Lounge.
PROVES   O1 -> test_context_is_bounded_to_current_project_and_carries_feedback_deck_ideal_text
         O2 -> test_state_skips_known_audience_and_goal_and_asks_one_slot_at_a_time
         O3 -> test_tone_and_content_language_are_passed_to_the_single_generation
         O4 -> test_unknown_arc_fails_closed
WHY      Project Chat redesign, 2026-11-18; preserve the current-project
         processing boundary and the Feedback walk's record -> process -> Take loop.

Project Chat contract tests.

The fakes expose only one project at a time to make an accidental global
thread read fail loudly.  The model is patched at the shared LLM wrapper so
the tests assert the actual prompt/model path without making a provider call.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from services import project_chat
from services.chat_query import thread_history

USER = "speaker-1"
ARC = "project-a"
OTHER_ARC = "project-b"
TAKE = "take-a2"


def _session(session_id: str, arc_id: str = ARC, index: int = 2, *, audience=None, goal=None):
    strategic = f"Desired call to action: {goal}" if goal else ""
    return {
        "id": session_id,
        "user_id": USER,
        "owner_principal_id": "principal-1",
        "arc_id": arc_id,
        "take_index": index,
        "created_at": f"2026-11-{index:02d}T10:00:00Z",
        "status": "completed",
        "analysis_state": "ready",
        "recording_kind": "spoken",
        "paired_session_id": None,
        "results_published_at": "2026-11-18T10:01:00Z",
        "coach_feedback_saved_at": "2026-11-18T10:02:00Z",
        "intake_context": {
            "topic": "Board update",
            "audience": audience,
            "strategic_context": strategic,
            "slides": [{"title": "Decision", "body": "Approve the plan"}],
        },
    }


class FakeTakes:
    def __init__(self, sessions):
        self.sessions = sessions
        self.saved = []

    def get_arc_sessions(self, arc_id):
        return list(self.sessions.get(str(arc_id), []))

    def get_session_intake_context(self, session_id):
        for rows in self.sessions.values():
            for row in rows:
                if str(row.get("id")) == str(session_id):
                    return dict(row.get("intake_context") or {})
        return None

    def set_session_intake_context(self, session_id, value):
        self.saved.append((str(session_id), dict(value or {})))
        for rows in self.sessions.values():
            for row in rows:
                if str(row.get("id")) == str(session_id):
                    row["intake_context"] = dict(value or {})
                    return True
        return False


class FakeDB:
    def __init__(self, *, audience=None, goal=None):
        self.client = None
        current = _session(TAKE, audience=audience, goal=goal)
        previous = _session("take-a1", index=1, audience=audience, goal=goal)
        self.takes = FakeTakes({ARC: [previous, current], OTHER_ARC: [_session("foreign", OTHER_ARC, 1)]})
        self.snippets = {
            "take-a1": [{"id": "s1", "start_offset_ms": 0, "transcript": "The old opening."}],
            TAKE: [{
                "id": "s2",
                "start_offset_ms": 0,
                "transcript": "I am speaking to the board so they can approve this plan.",
                "metrics": {"verbal_cues": ["deliberate pause before the ask"], "wpm": 150},
            }],
            "foreign": [{"id": "sx", "start_offset_ms": 0, "transcript": "FOREIGN PROJECT SECRET"}],
        }
        self.drafts = {
            TAKE: [{
                "snippet_id": "s2",
                "surfaced": True,
                "note": "The pause before the ask gave the decision room to land.",
                "transcript_corrected": "I am speaking to the board.",
                "kind": "praise",
            }]
        }
        self.project_rows = [
            {"client_id": "foreign-row", "role": "bot", "kind": "text",
             "body": "FOREIGN PROJECT SECRET", "metadata": {"arc_id": OTHER_ARC},
             "client_created_at": "2026-11-18T09:00:00Z"},
        ]
        self.project = {
            "id": ARC,
            "owner_principal_id": "principal-1",
            "setup": {"slides": [{"title": "Decision", "body": "Approve the plan"}]},
        }
        self.ideal = {"text": "A clear decision request for the board.", "approved_at": "2026-11-18T10:03:00Z"}
        self.inserted = []
        self.global_thread_read = False

    def get_snippets_by_sessions(self, session_ids, **_kwargs):
        return {str(sid): list(self.snippets.get(str(sid), [])) for sid in session_ids}

    def get_coach_snippet_drafts(self, session_id):
        return list(self.drafts.get(str(session_id), []))

    def get_project_row(self, arc_id):
        return self.project if str(arc_id) == ARC else None

    def get_coach_arc_ideal_text(self, arc_id):
        return self.ideal if str(arc_id) == ARC else None

    def get_project_lounge_messages_page(self, user_id, arc_id, *, limit, before=None):
        assert user_id == USER
        assert arc_id == ARC
        rows = [row for row in self.project_rows if (row.get("metadata") or {}).get("arc_id") == ARC]
        return rows[:limit + 1]

    def get_lounge_messages_page(self, *_args, **_kwargs):
        self.global_thread_read = True
        raise AssertionError("Project Chat must not read the global Lounge")

    def insert_lounge_messages(self, user_id, rows):
        self.inserted.append((user_id, rows))
        return rows


def _config_result(answer: str, chips=None):
    return SimpleNamespace(
        text=json.dumps({"answer": answer, "chips": chips or []}, ensure_ascii=False),
        parsed=None,
        model="gpt-4o-mini",
        duration_ms=18,
    )


@pytest.fixture(autouse=True)
def clear_project_cache():
    project_chat.clear_cache()
    yield
    project_chat.clear_cache()


def test_context_is_bounded_to_current_project_and_carries_feedback_deck_ideal_text():
    database = FakeDB()
    context = project_chat.build_context(database, USER, ARC, take_session_id=TAKE)

    assert context.arc_id == ARC
    assert context.take_session_id == TAKE
    assert context.current_take["transcript"].startswith("I am speaking to the board")
    assert context.feedback_moments[0]["moment"] == "I am speaking to the board."
    assert "pause before the ask" in context.current_take["spoken_cues"][0]
    assert context.ideal_text.startswith("A clear decision")
    assert context.deck[0]["title"] == "Decision"
    assert "FOREIGN PROJECT SECRET" not in json.dumps(context, default=str)
    assert not database.global_thread_read


def test_state_skips_known_audience_and_goal_and_asks_one_slot_at_a_time():
    unknown = FakeDB()
    context = project_chat.build_context(unknown, USER, ARC, take_session_id=TAKE)
    state = project_chat.derive_state(context, context.project_rows)
    # The Take's explicit spoken evidence establishes both slots without a
    # second generic re-ask; the model can reflect it or answer the latest ask.
    assert state.audience_known is True
    assert state.goal_known is True
    assert state.next_slot == "conversation"

    known = FakeDB(audience="the board", goal="approve the plan")
    context = project_chat.build_context(known, USER, ARC, take_session_id=TAKE)
    state = project_chat.derive_state(context, context.project_rows)
    assert state.phase is project_chat.ConversationPhase.OPENING
    assert state.next_slot == "conversation"


def test_opening_generation_is_grounded_and_uses_one_project_model_path():
    database = FakeDB(audience="the board")
    calls = []

    def generate(**kwargs):
        calls.append(kwargs)
        return _config_result(
            "Nice work on that pause before the ask. What do you want the board to do or feel?"
        )

    with patch("services.llm.chat_complete", generate):
        response, intent = project_chat.answer(database, USER, ARC, "Please help me frame this", take_session_id=TAKE)

    assert intent == "project_chat"
    assert response["answer"].startswith("Nice work on that pause")
    assert response["project_state"]["next_slot"] == "conversation"
    assert calls[0]["surface"] == "project_chat"
    assert "The pause before the ask gave the decision room to land." in calls[0]["user"]
    assert "FOREIGN PROJECT SECRET" not in calls[0]["user"]
    assert "score" not in calls[0]["user"].lower()
    assert "TARGET CONTENT LANGUAGE" in calls[0]["system"]


@pytest.mark.parametrize(
    ("question", "tone", "answer"),
    [
        ("Could you keep this formal, please?", "formal", "Certainly — I will keep the project conversation precise."),
        ("Hey 😏 what next?", "playful", "Let's keep the ask sharp and see what the board needs next."),
        ("Co dalej z tym projektem, jeśli chcemy to dopracować?", "warm", "Widzę ten moment. Możemy teraz dopracować następny krok."),
    ],
)
def test_tone_and_content_language_are_passed_to_the_single_generation(question, tone, answer):
    database = FakeDB(audience="the board", goal="approve the plan")
    calls = []

    def generate(**kwargs):
        calls.append(kwargs)
        return _config_result(answer)

    with patch("services.llm.chat_complete", generate):
        response, _ = project_chat.answer(database, USER, ARC, question, take_session_id=TAKE)

    assert response["answer"] == answer
    assert f"Requested tone: {tone}" in calls[0]["system"]
    if question.startswith("Co "):
        assert "TARGET CONTENT LANGUAGE: Polish (pl)" in calls[0]["system"]


def test_structured_answer_is_saved_and_follow_up_uses_project_history():
    database = FakeDB()
    database.project_rows.append({
        "client_id": "ask",
        "role": "bot",
        "kind": "text",
        "body": "Who were you talking to? 🎯",
        "metadata": {
            "arc_id": ARC,
            "project_chat": True,
            "next_slot": "audience",
        },
        "client_created_at": "2026-11-18T10:05:00Z",
    })
    calls = []

    def generate(**kwargs):
        calls.append(kwargs)
        return _config_result("Great — now we can shape the ask around that room.")

    with patch("services.llm.chat_complete", generate):
        response, _ = project_chat.answer(database, USER, ARC, "The board", take_session_id=TAKE)

    assert database.takes.saved[-1][0] == TAKE
    assert database.takes.saved[-1][1]["audience"] == "The board"
    assert response["row_metadata"]["captured_slots"]["audience"] == "The board"
    assert calls and "The board" in calls[0]["user"]
    assert "Who were you talking to?" in calls[0]["user"]


def test_sparse_evidence_is_acknowledged_without_inventing_feedback():
    database = FakeDB()
    database.snippets[TAKE] = []
    database.drafts[TAKE] = []
    database.ideal = {}
    database.project["setup"] = {}
    with patch("services.llm.chat_complete", return_value=_config_result("rating: 4/5")):
        response, _ = project_chat.answer(
            database, USER, ARC, "What happened here?", take_session_id=TAKE
        )

    assert "don't have a published coach note yet" in response["answer"]
    assert "pause before the ask" not in response["answer"]


def test_lightweight_follow_up_uses_fast_path_without_a_model_call():
    database = FakeDB(audience="the board", goal="approve the plan")
    database.project_rows.extend([
        {"client_id": "bot", "role": "bot", "kind": "text", "body": "Let's continue.",
         "metadata": {"arc_id": ARC, "project_chat": True},
         "client_created_at": "2026-11-18T10:05:00Z"},
    ])
    with patch("services.llm.chat_complete", side_effect=AssertionError("fast path called the model")):
        response, _ = project_chat.answer(database, USER, ARC, "Thanks", take_session_id=TAKE)
    assert response["fast_path"] is True
    assert response["answer"] == "Got it, thanks 🙏"


def test_invalid_opening_fallback_does_not_reask_known_audience_or_goal():
    database = FakeDB(audience="the board", goal="approve the plan")
    with patch("services.llm.chat_complete", return_value=_config_result("score: 91")):
        response, _ = project_chat.answer(
            database, USER, ARC, "What should I focus on?", take_session_id=TAKE
        )

    assert "board" in response["answer"]
    assert "approve the plan" in response["answer"]
    assert "Who were you talking to?" not in response["answer"]
    assert response["answer"].count("?") == 1


def test_invalid_conversation_fallback_stays_in_project_follow_up_mode():
    database = FakeDB(audience="the board", goal="approve the plan")
    database.project_rows.append({
        "client_id": "prior-bot",
        "role": "bot",
        "kind": "text",
        "body": "Let's keep working on the decision.",
        "metadata": {"arc_id": ARC, "project_chat": True, "next_slot": "conversation"},
        "client_created_at": "2026-11-18T10:05:00Z",
    })
    with patch("services.llm.chat_complete", return_value=_config_result("rating: 4/5")):
        response, _ = project_chat.answer(
            database, USER, ARC, "What next?", take_session_id=TAKE
        )

    assert response["answer"] == "What would you like to work through first?"
    assert "Who were you talking to?" not in response["answer"]


def test_project_chat_rows_do_not_appear_in_the_speaking_coach_history():
    rows = [
        {
            "client_id": "project-turn",
            "role": "bot",
            "kind": "text",
            "body": "Only the project should see this.",
            "metadata": {"project_chat": True, "arc_id": ARC},
            "client_created_at": "2026-11-18T10:00:00Z",
        },
        {
            "client_id": "global-turn",
            "role": "bot",
            "kind": "text",
            "body": "The global Lounge turn.",
            "metadata": {"intent": "help"},
            "client_created_at": "2026-11-18T10:01:00Z",
        },
    ]

    database = SimpleNamespace(get_lounge_messages_page=lambda *_args, **_kw: list(reversed(rows)))
    history = thread_history(database, USER, "How am I progressing?")
    assert [row["content"] for row in history] == ["The global Lounge turn."]


def test_unknown_arc_fails_closed():
    with pytest.raises(project_chat.ProjectChatNotFound):
        project_chat.build_context(FakeDB(), USER, "not-owned")


def test_an_initial_request_is_not_saved_as_the_audience():
    database = FakeDB()
    with patch("services.llm.chat_complete", return_value=_config_result("Who is this talk for?")):
        response, _ = project_chat.answer(database, USER, ARC, "Please help me with this")
    assert database.takes.saved == []
    assert response["row_metadata"].get("captured_slots", {}) == {}


def test_foreign_and_withdrawn_takes_cannot_enter_project_context():
    database = FakeDB()
    foreign = {**_session("foreign-in-owned-arc", index=9), "user_id": "another-user"}
    database.takes.sessions[ARC].append(foreign)
    context = project_chat.build_context(database, USER, ARC)
    assert context.take_session_id == TAKE
    assert all(take["index"] != 9 for take in context.recent_takes)
    with patch("services.speaker_lookup._takes_in_force", return_value=set()):
        with pytest.raises(project_chat.ProjectChatNotFound):
            project_chat.build_context(database, USER, ARC)
