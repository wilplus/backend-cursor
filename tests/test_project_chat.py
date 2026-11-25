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
  O5  A regular project reply can use the word and vocal evidence for its
      exact passage and show it without bringing weekly principles into the project.
  O6  Live feedback pairs an improvement with an intervention and can offer
      the Ideal Text, a readiness note in words, and another Take.
  O7  A topic request retrieves the exact passage even when the coach only has
      its words, and its practice points to the same recording.
  O8  Follow-up practice can use a previously cited authorised Take after
      reload, without moving the active exchange.
  O9  A direct request to record again after Ideal Text offers the existing
      next-Take action.
  O10 A request for the same fragment retrieves the exact recording and
      words from the project even after a reply without an attached clip.
  O11 Each new chat recording is coached as a new attempt using its own
      words and cues; a typed revision has no new vocal evidence.
PROVES   O1 -> test_context_is_bounded_to_current_project_and_carries_feedback_deck_ideal_text
         O2 -> test_state_skips_known_audience_and_goal_and_asks_one_slot_at_a_time
         O3 -> test_tone_and_content_language_are_passed_to_the_single_generation
         O4 -> test_unknown_arc_fails_closed
         O5 -> test_ordinary_project_reply_uses_its_own_vocal_evidence_and_attaches_the_passage
         O6 -> test_live_feedback_pairs_an_improvement_with_an_intervention_and_offers_the_ideal_text
         O7 -> test_topic_request_can_practise_a_words_only_fragment_after_ideal_text
         O8 -> test_practice_follow_up_can_refer_to_an_older_take
         O9 -> test_record_again_is_available_after_ideal_text
         O10 -> test_fragment_follow_ups_use_the_quoted_recording_when_the_first_reply_has_no_clip
         O11 -> test_successive_recorded_endings_and_a_typed_revision_use_the_latest_attempt
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
    assert "pause before the ask" in context.recorded_passages[0].text
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


def test_a_review_question_uses_the_exact_old_moment_without_capturing_setup():
    database = FakeDB()
    database.project_rows.append({
        "role": "bot", "kind": "text", "body": "Who are you speaking to?",
        "metadata": {"arc_id": ARC, "project_chat": True, "next_slot": "audience"},
    })
    focus = {"step": "feedback", "snippet_id": "s1"}
    with patch("services.llm.chat_complete", return_value=_config_result("Try saying the decision first.")) as complete:
        result, _ = project_chat.answer(
            database, USER, ARC, "How do I improve that?", take_session_id="take-a1", review_focus=focus,
        )
    words = json.loads(complete.call_args.kwargs["user"])["speaker_is_reviewing"]
    assert words == {"anchor": focus, "exact_take_words": "The old opening."}
    assert result["row_metadata"]["review_focus"] == focus
    assert result["row_metadata"]["coach_moment"] == {
        "arc_id": ARC, "take_session_id": "take-a1", "snippet_id": "s1", "practise": True, "playback": False,
    }
    assert result["row_metadata"]["take_session_id"] == "take-a1"
    assert result["row_metadata"]["next_slot"] == ""
    assert database.takes.saved == []


def test_a_review_can_point_to_its_practice_or_ideal_text_from_the_reply():
    database = FakeDB(audience="the board", goal="approve the plan")
    focus = {"step": "feedback", "snippet_id": "s2"}
    for offered in ("practise", "ideal"):
        result = _config_result("Here is the next step for this passage.")
        result.parsed = {**json.loads(result.text), "moment": None, "next_review_step": offered}
        with patch("services.llm.chat_complete", return_value=result) as complete:
            response, _ = project_chat.answer(
                database, USER, ARC, "What comes next?", take_session_id=TAKE, review_focus=focus,
            )
        review = json.loads(complete.call_args.kwargs["user"])["speaker_is_reviewing"]
        assert review["delivery_observations"] == ["deliberate pause before the ask"]
        assert response["row_metadata"]["review_focus"] == focus
        assert response["row_metadata"]["review_destination"] == {"step": offered}
        assert "coach_moment" not in response["row_metadata"]


def test_live_feedback_pairs_an_improvement_with_an_intervention_and_offers_the_ideal_text():
    database = FakeDB(audience="the board", goal="approve the plan")
    database.drafts[TAKE][0]["kind"] = "fix"
    focus = {"step": "feedback", "snippet_id": "s2"}
    result = _config_result("Give the decision a little more space.")
    result.parsed = {"answer": "Give the decision a little more space.",
                     "moment": "reviewed", "intervention": "Say the ask again and pause before 'approve'."}
    with patch("services.llm.chat_complete", return_value=result):
        reply, _ = project_chat.answer(
            database, USER, ARC, "What can I work on?", take_session_id=TAKE,
            review_focus=focus, live_take_feedback=True,
        )
    meta = reply["row_metadata"]
    assert meta["coach_moment"]["snippet_id"] == "s2"
    assert meta["coach_moment"]["practise"] is True
    assert meta["chat_artifact"]["intervention"] == result.parsed["intervention"]

    result = _config_result("Spójrz na swój Ideal Text i wybierz słowa pomocnicze.")
    result.parsed = {"answer": "Spójrz na swój Ideal Text i wybierz słowa pomocnicze.",
                     "next_review_step": "ideal", "offer_next_take": True,
                     "after_ideal_text": "Prośba jest jasna. Warto przećwiczyć pauzę. Chcesz spróbować jeszcze raz?"}
    with patch("services.llm.chat_complete", return_value=result):
        reply, _ = project_chat.answer(
            database, USER, ARC, "Myślę, że na dziś wystarczy.", take_session_id=TAKE,
            review_focus=focus, live_take_feedback=True,
        )
    assert reply["row_metadata"]["review_destination"] == {"step": "ideal"}
    assert reply["row_metadata"]["after_ideal_text"] == result.parsed["after_ideal_text"]
    assert reply["suggested_action"] == "record_again"


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


def test_project_chat_only_attaches_a_published_moment_from_this_take():
    database = FakeDB(audience="the board", goal="approve the plan")
    result = _config_result("The pause gives your ask room.")
    result.parsed = {**json.loads(result.text), "moment": "M0", "practise": True}
    with patch("services.llm.chat_complete", return_value=result):
        response, _ = project_chat.answer(database, USER, ARC, "How did the ask land?", take_session_id=TAKE)
        assert response["row_metadata"]["coach_moment"] == {
            "arc_id": ARC, "take_session_id": TAKE, "snippet_id": "s2", "practise": True, "playback": False,
        }
        result.parsed["moment"] = "M1"
        response, _ = project_chat.answer(database, USER, ARC, "How did the ask land?", take_session_id=TAKE)
    assert "coach_moment" not in response["row_metadata"]


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


@pytest.mark.parametrize("invalid_answer", ["rating: 4/5", "What would you like to work through first?"])
def test_invalid_conversation_reply_reports_the_failure_clearly(invalid_answer):
    database = FakeDB(audience="the board", goal="approve the plan")
    database.project_rows.append({
        "client_id": "prior-bot",
        "role": "bot",
        "kind": "text",
        "body": "Let's keep working on the decision.",
        "metadata": {"arc_id": ARC, "project_chat": True, "next_slot": "conversation"},
        "client_created_at": "2026-11-18T10:05:00Z",
    })
    with patch("services.llm.chat_complete", return_value=_config_result(invalid_answer)):
        reply, _ = project_chat.answer(database, USER, ARC, "What next?", take_session_id=TAKE)
    assert reply["answer"] == "I couldn’t finish that reply. Please send your question again."


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
    with patch("services.project_deletion.ProjectDeletionService.archived_projects", return_value={ARC}):
        with pytest.raises(project_chat.ProjectChatNotFound):
            project_chat.build_context(database, USER, ARC)


def test_coaching_advice_contains_the_actual_line_and_uses_the_project_scope():
    database = FakeDB(audience="the team", goal="find someone to lead the pilot")
    result = _config_result("Zakończ jednym pytaniem.")
    result.parsed = {"answer": "Zakończ jednym pytaniem.", "wording": {
        "words": "Jeśli dostaniemy zgodę, kto z was chciałby poprowadzić pilotaż?",
        "arc_id": OTHER_ARC, "take_session_id": "foreign",
    }}
    with patch("services.llm.chat_complete", return_value=result):
        response, _ = project_chat.answer(
            database, USER, ARC, "Jak mogę to powiedzieć zespołowi?", take_session_id=TAKE,
            review_focus={"step": "feedback"},
        )
    wording = response["row_metadata"]["coach_wording"]
    assert wording == {
        "words": "Jeśli dostaniemy zgodę, kto z was chciałby poprowadzić pilotaż?",
        "arc_id": ARC, "take_session_id": TAKE,
    }


@pytest.mark.parametrize(("question", "answer"), [
    ("How can I practise the ending?", "Give the request a short pause before today."),
    ("and some critics?", "Give the request a short pause before today."),
    ("Pokaż najsłabszy fragment", "Zrób krótką pauzę przed słowem »today«."),
])
def test_ordinary_project_reply_uses_its_own_vocal_evidence_and_attaches_the_passage(question, answer):
    from services.llm_config import SPEC_PROJECT_CHAT_TAKE

    database = FakeDB(audience="the board", goal="approve the plan")
    words = "Please approve the pilot today."
    database.snippets[TAKE] = [{"id": "closing", "transcript": words,
                                "metrics": {"wpm": 188, "pause_ratio": 0.04}}]
    database.project_rows.append({"role": "bot", "kind": "text", "body": "PRIVATE WEEKLY PRINCIPLE",
                                  "metadata": {"arc_id": ARC, "project_chat": True, "sunday_step": "suggested"}})

    def generate(**kwargs):
        assert kwargs["spec"] is SPEC_PROJECT_CHAT_TAKE
        prompt = json.loads(kwargs["user"])
        passage, = prompt["project_context"]["recorded_passages"]
        assert words in passage["evidence"]
        assert "pace: a bit fast" in passage["evidence"] and "188" not in passage["evidence"]
        assert "PRIVATE WEEKLY PRINCIPLE" not in kwargs["user"]
        assert "FOREIGN PROJECT SECRET" not in kwargs["user"]
        result = _config_result(answer)
        result.parsed = {**json.loads(result.text), "moment": passage["reference"], "practise": False}
        return result

    with patch("services.llm.chat_complete", generate):
        response, _ = project_chat.answer(database, USER, ARC, question)
    assert response["row_metadata"]["coach_moment"] == {
        "arc_id": ARC, "take_session_id": TAKE, "snippet_id": "closing", "practise": True, "playback": False,
    }


@pytest.mark.parametrize(("question", "intervention"), [
    ("actually I would like to try sniper here?", "sniper"),
    ("Can I try the AI audio for this passage?", "ai_audio"),
    ("pokażesz mi AI audio tego?", "ai_audio"),
    ("Pokaż tutaj wideo od trenera", "coach_video"),
])
def test_a_practice_follow_up_keeps_the_saved_moment_in_its_take(question, intervention):
    database = FakeDB()
    previous = {"arc_id": ARC, "take_session_id": TAKE, "snippet_id": "s2", "practise": False}
    for take, snippet, day in ((TAKE, "s2", 18), ("take-a1", "s2", 19)):
        database.project_rows.append({
            "role": "bot", "kind": "text", "body": "Here is the fragment we just discussed.",
            "client_created_at": f"2026-11-{day}T09:00:00Z",
            "metadata": {
                "arc_id": ARC, "project_chat": True, "next_slot": "audience",
                "coach_moment": {**previous, "take_session_id": take, "snippet_id": snippet},
            },
        })

    with patch("services.llm.chat_complete") as generate:
        reply, _ = project_chat.answer(database, USER, ARC, question)
    generate.assert_not_called()
    metadata = reply["row_metadata"]
    assert metadata["coach_moment"] == {**previous, "practise": True, "intervention": intervention, "playback": False}
    assert reply["answer"]
    assert "review_focus" not in metadata
    assert "chat_artifact" not in metadata
    assert database.takes.saved == []


def test_a_rephrase_returns_the_words_and_exact_original_moment_together():
    database = FakeDB()
    database.project_rows.append({
        "role": "bot", "kind": "text", "body": "Here is the original.",
        "client_created_at": "2026-11-24T11:00:00Z",
        "metadata": {"arc_id": ARC, "project_chat": True,
                     "coach_moment": {"arc_id": ARC, "take_session_id": TAKE, "snippet_id": "s2"}},
    })

    def generate(**kwargs):
        passage = json.loads(kwargs["user"])["passage_to_practise"]
        assert "speaking to the board" in passage["evidence"]
        result = _config_result("Try this opening.")
        result.parsed = {
            "answer": "Try this opening.",
            "wording": {"words": "I’m asking the board to approve our plan.", "source": "practice_passage"},
        }
        return result

    with patch("services.llm.chat_complete", generate):
        reply, _ = project_chat.answer(database, USER, ARC, "Can you rephrase that?")
    assert reply["row_metadata"]["coach_wording"]["take_session_id"] == TAKE
    assert reply["row_metadata"]["coach_moment"] == {
        "arc_id": ARC, "take_session_id": TAKE, "snippet_id": "s2", "practise": False, "playback": False,
    }


def test_asking_to_see_ideal_text_serves_its_destination_if_the_model_misses_it():
    database = FakeDB()
    with patch("services.llm.chat_complete", return_value=_config_result("What would you like to work through first?")):
        reply, _ = project_chat.answer(database, USER, ARC, "Show me my full Ideal Text.")
    assert reply["answer"] == "Here’s your Ideal Text."
    assert reply["row_metadata"]["review_destination"] == {"step": "ideal"}
    assert reply["row_metadata"]["take_session_id"] == TAKE


@pytest.mark.parametrize("model_reference", ["D1", "reviewed", "M0"])
def test_a_question_about_later_slides_moves_on_from_the_cited_opening(model_reference):
    database = FakeDB(audience="the board", goal="approve the pilot")
    opening = database.snippets[TAKE][0]
    opening["metrics"]["piece"] = {"slide_index": 0}
    database.snippets[TAKE].extend([
        {"id": "middle", "start_offset_ms": 9000, "transcript": "Pilotaż obejmie dwa zespoły.",
         "metrics": {"piece": {"slide_index": 1}}},
        {"id": "ending", "start_offset_ms": 18000, "transcript": "Na koniec opowiem o naszej nowej stronie.",
         "metrics": {"piece": {"slide_index": 2}}},
    ])
    question = "Czy na kolejnych slajdach trzymałem się celu, czy mówiłem o czymś innym?"

    def generate(**kwargs):
        prompt = json.loads(kwargs["user"])
        assert "speaker_is_reviewing" not in prompt
        scoped = prompt["project_context"]
        assert "transcript" not in scoped["current_take"]
        assert scoped["published_feedback_moments"] == []
        assert [row["slide_number"] for row in scoped["recorded_passages"]] == [2, 3]
        assert all(row["evidence_kind"] == "speaker_words" for row in scoped["recorded_passages"])
        answer = "Na końcu przeszedłeś z pilotażu do nowej strony."
        result = _config_result(answer)
        result.parsed = {"answer": answer,
                         "moment": model_reference, "practise": True,
                         "intervention": "Zamknij prośbą o decyzję w sprawie pilotażu."}
        return result

    with patch("services.llm.chat_complete", generate):
        reply, _ = project_chat.answer(
            database, USER, ARC, question, take_session_id=TAKE,
            review_focus={"step": "feedback", "snippet_id": "s2"}, live_take_feedback=True,
        )
    metadata = reply["row_metadata"]
    if model_reference == "D1":
        assert metadata["coach_moment"]["snippet_id"] == "ending"
        assert metadata["chat_artifact"]["intervention"].startswith("Zamknij prośbą")
    else:
        assert "coach_moment" not in metadata
    assert metadata["live_take_feedback"] is True


def test_a_general_improvement_question_cites_the_published_tempo_piece(monkeypatch):
    database = FakeDB()
    words = "The pilot will cover the support and implementation teams."
    database.snippets[TAKE].append({"id": "tempo", "start_offset_ms": 14000, "transcript": words})
    database.get_ideal_text_document_core = lambda *_: {
        "id": "snapshot", "source_take_session_id": TAKE, "payload": {"text": words},
    }
    database.read_ideal_text_feedback_bake = lambda *_: {"changes": [
        {"snippet_id": "s2", "presentation": {"one_fix": "tempo"}},
    ]}
    database.get_snippets_by_session = lambda sid: database.snippets[sid]
    monkeypatch.setattr("services.ideal_text_feedback_bake._bake_enabled", lambda: True)
    monkeypatch.setattr("services.tempo_stretch.pick_for_take", lambda *_: {"index": 1, "reading": "rushed"})

    with patch("services.llm.chat_complete") as generate:
        reply, _ = project_chat.answer(
            database, USER, ARC, "What’s the next thing to improve?", take_session_id=TAKE,
            review_focus={"step": "feedback", "snippet_id": "s2"}, live_take_feedback=True,
        )
    generate.assert_not_called()
    assert reply["row_metadata"]["coach_moment"] == {
        "arc_id": ARC, "take_session_id": TAKE, "snippet_id": "tempo", "practise": True, "intervention": "sniper", "playback": False,
    }
    assert reply["row_metadata"]["chat_practice"] == {"tool": "sniper", "words": words, "reading": "rushed"}


def test_coaching_eval_fixture_reads_only_its_authorised_recordings(monkeypatch):
    from services.processing_authorization import ProcessingAuthorizationError
    from services.speaker_lookup import _takes_in_force
    from tests.evals.surfaces import _synthetic_chat_client

    monkeypatch.setenv("PLF1_PROCESSING_AUTHORIZATION_MODE", "enforce")
    database = SimpleNamespace(client=_synthetic_chat_client(USER))
    assert _takes_in_force(database, [{"id": TAKE, "user_id": USER}]) == {TAKE}
    with pytest.raises(ProcessingAuthorizationError):
        _takes_in_force(database, [{"id": "foreign-take", "user_id": "another-speaker"}])


@pytest.mark.parametrize("question", [
    "How can I fix this?", "What is the weakest part of this fragment?", "What is the weakest part of this clip?",
])
def test_how_to_fix_the_reviewed_passage_ignores_an_offer_from_another_take(monkeypatch, question):
    from services import chat_practice

    database = FakeDB()
    earlier_id = "78df3a7f-4d38-42a4-b763-380e688d3ba0"
    _, earlier = chat_practice.sniper(ARC, "take-a1", "s1", "The old opening.", "rushed", "en")
    monkeypatch.setattr(chat_practice.Config, "SUPABASE_JWT_SECRET", "unit-test-secret")
    earlier["arc_id"] = ARC
    chat_practice.sign_bot_metadata(USER, earlier_id, earlier)
    database.project_rows.append({"client_id": earlier_id, "role": "bot", "kind": "text",
                                  "metadata": earlier, "client_created_at": "2026-11-24T14:00:00Z"})
    database.get_ideal_text_document_core = lambda *_: {"id": "snapshot", "source_take_session_id": TAKE}
    database.read_ideal_text_feedback_bake = lambda *_: {"changes": [{"one_fix": "tempo"}]}
    database.get_snippets_by_session = lambda sid: database.snippets[sid]
    monkeypatch.setattr("services.ideal_text_feedback_bake._bake_enabled", lambda: True)
    monkeypatch.setattr("services.tempo_stretch.pick_for_take", lambda *_: {"index": 0, "reading": "rushed"})

    reply, _ = project_chat.answer(
        database, USER, ARC, question, take_session_id=TAKE,
        review_focus={"step": "feedback", "snippet_id": "s2"},
    )
    assert reply["row_metadata"]["coach_moment"]["take_session_id"] == TAKE
    assert reply["row_metadata"]["coach_moment"]["snippet_id"] == "s2"
    assert reply["row_metadata"]["chat_practice"]["words"] == database.snippets[TAKE][0]["transcript"]
    database.snippets[TAKE].append({"id": "unrelated", "transcript": "An unrelated fast moment."})
    monkeypatch.setattr("services.tempo_stretch.pick_for_take", lambda *_: {"index": 1, "reading": "rushed"})
    with patch("services.llm.chat_complete", return_value=_config_result("Let's keep the request in one sentence.")):
        reply, _ = project_chat.answer(
            database, USER, ARC, question, take_session_id=TAKE,
            review_focus={"step": "feedback", "snippet_id": "s2"},
        )
    assert reply["row_metadata"].get("coach_moment", {}).get("snippet_id") != "unrelated"


@pytest.mark.parametrize("model_asks", [True, False])
def test_topic_request_can_practise_a_words_only_fragment_after_ideal_text(model_asks):
    database = FakeDB()
    words = "We changed cars before the second brake test."
    database.snippets[TAKE].extend([
        {"id": f"other-{index}", "start_offset_ms": index * 1000, "transcript": "The report comes out next week."}
        for index in range(1, 8)
    ])
    database.snippets[TAKE].append({"id": "cars", "start_offset_ms": 8000, "transcript": words})
    focus = {"step": "ideal"}

    def generate(**kwargs):
        prompt = json.loads(kwargs["user"])
        target = next(item for item in prompt["project_context"]["recorded_passages"] if words in item["evidence"])
        assert target["evidence_kind"] == "speaker_words"
        assert words in prompt["passage_to_practise"]["evidence"]
        answer = "You said the cars felt tricky. Try saying the change as one short line first."
        if model_asks:
            answer += " What felt uncertain? Was it the example?"
        result = _config_result(answer)
        result.parsed = {**json.loads(result.text), "moment": None, "practise": True}
        return result

    with patch("services.llm.embed", return_value=None) as embed, patch("services.llm.chat_complete", generate):
        reply, _ = project_chat.answer(
            database, USER, ARC, "The part when I was talking about the cars, I felt insecure. Can we practise it?",
            take_session_id=TAKE, review_focus=focus, live_take_feedback=True,
        )
    embed.assert_not_called()
    assert reply["row_metadata"]["coach_moment"] == {
        "arc_id": ARC, "take_session_id": TAKE, "snippet_id": "cars", "practise": True, "playback": False,
    }
    assert reply["row_metadata"]["review_focus"] == focus
    expected_question = "What felt uncertain?" if model_asks else "What made this part feel uncertain to you?"
    assert reply["answer"].endswith(expected_question)


def test_practice_follow_up_can_refer_to_an_older_take():
    database = FakeDB()
    database.takes.sessions[ARC] += [_session(f"take-a{index}", index=index) for index in range(3, 6)]
    last = {"arc_id": ARC, "take_session_id": "take-a1", "snippet_id": "s1", "practise": False}
    database.project_rows.append({
        "role": "bot", "kind": "text", "body": "That was the older opening.",
        "metadata": {"arc_id": ARC, "project_chat": True, "coach_moment": last},
    })

    def generate(**kwargs):
        passage = json.loads(kwargs["user"])["passage_to_practise"]
        assert "The old opening." in passage["evidence"]
        return _config_result("Give the opening a beat before continuing.")

    with patch("services.llm.chat_complete", generate):
        reply, _ = project_chat.answer(
            database, USER, ARC, "Can we practise it?", take_session_id="take-a5",
            review_focus={"step": "feedback"}, live_take_feedback=True,
        )
    assert reply["row_metadata"]["take_session_id"] == "take-a5"
    assert reply["row_metadata"]["coach_moment"] == {**last, "practise": True, "playback": False}


@pytest.mark.parametrize("generated", [True, False])
def test_record_again_is_available_after_ideal_text(generated):
    database = FakeDB()
    focus = {"step": "ideal"}
    model = _config_result("Yes. Give the opening another try.") if generated else None
    with patch("services.llm.chat_complete", return_value=model):
        reply, _ = project_chat.answer(
            database, USER, ARC, "Can I record again?", take_session_id=TAKE,
            review_focus=focus, live_take_feedback=True,
        )
    assert reply["suggested_action"] == "record_again"
    assert reply["row_metadata"]["review_focus"] == focus


def test_fragment_follow_ups_use_the_quoted_recording_when_the_first_reply_has_no_clip():
    database = FakeDB(audience="the board", goal="approve the plan")
    snippet = "cars"
    words = "We changed cars before the second brake test."
    database.snippets[TAKE].append({"id": snippet, "transcript": words})
    for index, (role, body) in enumerate([
        ("user", words),
        ("user", "can you find this fragment anywhere?"),
        ("bot", "Tak, ten fragment jest częścią obecnego nagrania."),
    ]):
        database.project_rows.append({
            "role": role, "kind": "text", "body": body,
            "client_created_at": f"2026-11-24T11:10:0{index}Z",
            "metadata": {"arc_id": ARC, "project_chat": True},
        })

    with patch("services.llm.chat_complete") as generate:
        reply, _ = project_chat.answer(database, USER, ARC, "can oyu give me that fragment?", take_session_id=TAKE)
        assert reply["answer"] == f"“{words}”"
        assert reply["row_metadata"]["coach_moment"] == {
            "arc_id": ARC, "take_session_id": TAKE, "snippet_id": snippet, "practise": False, "playback": True,
        }
        database.project_rows.append({
            "role": "bot", "kind": "text", "body": reply["answer"], "metadata": reply["row_metadata"],
            "client_created_at": "2026-11-24T11:10:04Z",
        })
        retry, _ = project_chat.answer(database, USER, ARC,
                                       "I would like to see the text and record my take of it.", take_session_id=TAKE)
    generate.assert_not_called()
    assert words in retry["answer"]
    assert "record your version" in retry["answer"]
    assert retry["row_metadata"]["coach_moment"] == {
        **reply["row_metadata"]["coach_moment"], "practise": True, "playback": False,
    }


def test_fragment_request_marks_the_exact_older_clip_and_keeps_the_current_take():
    database = FakeDB()
    database.takes.sessions[ARC] += [_session(f"take-a{index}", index=index) for index in range(3, 6)]
    original = {"arc_id": ARC, "take_session_id": "take-a1", "snippet_id": "s1", "practise": False}
    database.project_rows.append({
        "role": "bot", "kind": "text", "body": "That was the older opening.",
        "metadata": {"arc_id": ARC, "project_chat": True, "coach_moment": original},
    })
    reply, _ = project_chat.answer(database, USER, ARC, "Can you play that fragment?", take_session_id="take-a5",
                                   review_focus={"step": "ideal"}, live_take_feedback=True)
    assert "The old opening." in reply["answer"]
    assert reply["row_metadata"]["coach_moment"] == {**original, "playback": True}
    assert reply["row_metadata"]["take_session_id"] == "take-a5"
    assert reply["row_metadata"]["live_take_feedback"] is True


def test_missing_fragment_asks_for_a_few_words_instead_of_guessing():
    database = FakeDB()
    reply, _ = project_chat.answer(database, USER, ARC, "Pokaż mi ten fragment", take_session_id=TAKE)
    assert "Podaj kilka słów z nagrania." in reply["answer"]
    assert "coach_moment" not in reply["row_metadata"]


def test_a_valid_follow_up_survives_an_extra_model_question():
    database = FakeDB(audience="the board", goal="approve the plan")
    database.project_rows.append({
        "role": "bot", "kind": "text", "body": "The board is the audience.",
        "metadata": {"arc_id": ARC, "project_chat": True},
    })
    words = "Give the board one clear decision. What should they approve today?"
    with patch("services.llm.chat_complete", return_value=_config_result(words + " Will they be ready?")):
        reply, _ = project_chat.answer(database, USER, ARC, "Can you help me sharpen the ask?", take_session_id=TAKE)
    assert reply["answer"] == words


@pytest.mark.parametrize("selection, use_mic", [("The one I just recorded.", True), ("The Take.", False)])
def test_delivery_question_lets_the_speaker_choose_the_scoped_recording_after_reload(selection, use_mic):
    database = FakeDB(audience="The board", goal="Approve the plan")
    database.takes.sessions[ARC][-1]["transcription_language"] = "pl"
    clip = "fed26b2c-279c-4ee0-8639-03723fc07f14"
    question = "Do I sound confident when I talk like that?"
    database.project_rows.extend([
        {"client_id": "cited", "kind": "text", "role": "bot", "body": "Here is the board pitch.",
         "metadata": {"arc_id": ARC, "coach_moment": {"arc_id": ARC, "take_session_id": TAKE, "snippet_id": "s2"}},
         "client_created_at": "2026-11-18T09:10:00Z"},
        {"client_id": clip, "kind": "text", "role": "user", "body": question,
         "metadata": {"arc_id": ARC, "take_session_id": TAKE, "voice_clip": True},
         "client_created_at": "2026-11-18T09:11:00Z"},
    ])
    evidence = {"transcript": question, "delivery": "Delivery across the whole passage: natural rise and fall"}
    with patch("services.lounge_voice_reply.read_analysis", return_value=evidence) as read, \
            patch("services.llm.chat_complete") as llm:
        clarification, _ = project_chat.answer(database, USER, ARC, question, take_session_id=TAKE, user_client_id=clip)
        assert clarification["answer"] == "Do you mean the fragment from your Take or the moment you just recorded?"
        llm.assert_not_called()
        database.project_rows.append(
            {"client_id": "clarification", "kind": "text", "role": "bot", "body": clarification["answer"],
             "metadata": {**clarification["row_metadata"], "reply_to_client_id": clip},
             "client_created_at": "2026-11-18T09:12:00Z"}
        )
        project_chat.clear_cache()
        llm.return_value = (SimpleNamespace(parsed={"answer": "Your voice lifts naturally at the end.",
                                                   "correction": False, "wording": None, "playback": True}) if use_mic
                            else _config_result("You leave the decision room to land."))
        result, _ = project_chat.answer(
            database, USER, ARC, selection, take_session_id=TAKE,
            user_client_id="8c66a885-a914-4ac4-bd07-3b859db37751",
        )
        prompt = json.loads(llm.call_args.kwargs["user"])
        assert "TARGET CONTENT LANGUAGE: English (en)" in llm.call_args.kwargs["system"]
        if use_mic:
            assert prompt["question"] == question
            assert prompt["spoken_words"] == question
            assert "natural rise and fall" in prompt["observations"]
            assert prompt["project"]["audience"] == "The board"
            assert result["row_metadata"]["chat_voice_focus"] == {"source": "clip", "turn_id": clip, "playback": True}
        else:
            assert "I am speaking to the board" in llm.call_args.kwargs["user"]
            assert question in llm.call_args.kwargs["user"]
            assert "natural rise and fall" not in llm.call_args.kwargs["user"]
        assert not database.global_thread_read
        read.assert_called_with(database, USER, clip, ARC)


def test_chat_recording_can_be_coached_in_an_owned_project_before_its_first_take():
    database = FakeDB()
    database.takes.sessions[ARC] = []
    database.get_owner_principal_for_user = lambda user: {"id": "principal-1"} if user == USER else None
    database.get_project_for_owner = lambda arc, principal: database.project if (arc, principal) == (ARC, "principal-1") else None
    clip = "fed26b2c-279c-4ee0-8639-03723fc07f14"
    question = "Czy brzmię tutaj pewnie?"
    database.project_rows.append(
        {"client_id": clip, "kind": "text", "role": "user", "body": question,
         "metadata": {"arc_id": ARC, "voice_clip": True}, "client_created_at": "2026-11-18T09:11:00Z"}
    )
    with patch("services.lounge_voice_reply.read_analysis", return_value={
        "transcript": question, "delivery": "pace: comfortable", "language": "pl",
    }), patch("services.llm.chat_complete", return_value=SimpleNamespace(parsed={
        "answer": "Mówisz w spokojnym, równym rytmie.", "correction": False, "wording": None, "playback": False,
    })):
        result, _ = project_chat.answer(database, USER, ARC, question, user_client_id=clip)

    assert result["answer"] == "Mówisz w spokojnym, równym rytmie."
    assert result["row_metadata"]["arc_id"] == ARC
    assert database.takes.sessions[ARC] == []


def test_successive_recorded_endings_and_a_typed_revision_use_the_latest_attempt():
    database = FakeDB(audience="The board", goal="Approve the plan")
    first = "c89bbfcb-7efc-43b1-a06b-1fa99ea83df1"
    second = "026e028d-0a39-45c5-944e-dd3663c5a18f"
    versions = [
        (first, "So these are all the tools we have, and that is it.", "Delivery across the whole passage: rushed"),
        (second, "I recommend the pilot. Please approve the plan today.", "Delivery across the whole passage: comfortable pace"),
    ]
    recordings = {key: {"transcript": words, "delivery": cues} for key, words, cues in versions}

    def read_analysis(db, user, turn, project):
        assert (db, user, project) == (database, USER, ARC)
        return recordings.get(turn)

    def generate(**kwargs):
        prompt = json.loads(kwargs["user"])
        assert prompt["project"] == {"topic": "Board update", "audience": "The board", "goal": "Approve the plan"}
        assert "The old opening." not in kwargs["user"]
        assert "FOREIGN PROJECT SECRET" not in kwargs["user"]
        current = prompt["spoken_words"]
        if current == versions[0][1]:
            assert prompt["recording_is_current_message"] is True
            assert prompt["observations"] == versions[0][2]
            line = "Please approve the pilot today."
        else:
            assert current == versions[1][1]
            assert prompt["observations"] == versions[1][2]
            assert any(row["words"] == versions[0][1] for row in prompt["recent_conversation"])
            line = "Please approve the pilot so the team can start."
        return SimpleNamespace(parsed={
            "answer": "Give the board one clear decision to make.", "correction": True,
            "wording": {"words": line, "delivery": None}, "playback": False,
        })

    with patch("services.lounge_voice_reply.read_analysis", read_analysis), \
            patch("services.llm.chat_complete", autospec=True, side_effect=generate) as model:
        for index, (turn, words, _cues) in enumerate(versions):
            database.project_rows.append({
                "client_id": turn, "kind": "text", "role": "user", "body": words,
                "metadata": {"arc_id": ARC, "take_session_id": TAKE, "voice_clip": True},
                "client_created_at": f"2026-11-18T09:1{index}:00Z",
            })
            project_chat.clear_cache()
            reply, _ = project_chat.answer(database, USER, ARC, words, take_session_id=TAKE, user_client_id=turn)
            assert "coach_moment" not in reply["row_metadata"]
            assert reply["row_metadata"]["chat_voice_focus"] == {"source": "clip", "turn_id": turn, "playback": False}
            assert reply["row_metadata"]["coach_wording"]["words"]
            assert reply["row_metadata"]["coach_wording"]["take_session_id"] == TAKE
            database.project_rows.append({
                "client_id": f"reply-{index}", "kind": "text", "role": "bot", "body": reply["answer"],
                "metadata": {**reply["row_metadata"], "reply_to_client_id": turn},
                "client_created_at": f"2026-11-18T09:1{index}:30Z",
            })

        project_chat.clear_cache()
        typed = "My new ending is: please approve the pilot so we can start."
        reply, _ = project_chat.answer(database, USER, ARC, typed, take_session_id=TAKE, user_client_id="new-typed-turn")
        prompt = json.loads(model.call_args.kwargs["user"])
        assert prompt["question"] == typed
        assert prompt["recording_is_current_message"] is False
        assert prompt["spoken_words"] == versions[1][1]
        assert reply["row_metadata"]["chat_voice_focus"]["playback"] is False


def test_a_chat_recording_can_be_replayed_without_delivery_analysis():
    from services import chat_voice_reference

    clip = "fed26b2c-279c-4ee0-8639-03723fc07f14"
    reference = chat_voice_reference.Reference("clip", "Odtwórz to nagranie", clip, {"transcript": "Proszę o zgodę."})
    with patch("services.llm.chat_complete", return_value=SimpleNamespace(parsed={
        "answer": "Oto to nagranie.", "correction": False, "wording": None, "playback": True,
    })):
        _text, metadata = chat_voice_reference.feedback(reference, "pl", USER, ARC)
    assert metadata["chat_voice_focus"] == {"turn_id": clip, "source": "clip", "playback": True}


def test_a_new_recording_with_missing_analysis_never_falls_back_to_an_older_clip():
    from services import chat_voice_reference

    first = "c89bbfcb-7efc-43b1-a06b-1fa99ea83df1"
    current = "026e028d-0a39-45c5-944e-dd3663c5a18f"
    rows = [{"client_id": turn, "role": "user", "kind": "text", "body": 'Try "the same line again"',
             "metadata": {"arc_id": ARC, "voice_clip": True}} for turn in (first, current)]
    older = {"transcript": "the same line again", "delivery": "quick pace"}
    with patch("services.lounge_voice_reply.read_analysis", side_effect=lambda _db, _user, turn, _arc: older if turn == first else None):
        reference = chat_voice_reference.resolve(None, USER, current, rows[-1]["body"], project=ARC, has_take=True, rows=rows)
    assert reference.source == "missing"
    assert reference.evidence is None
