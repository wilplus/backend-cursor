"""
STORY    As a speaker, I want Will to remember my speaking work across
         projects without turning private rows or machine labels into a
         verdict, so that the conversation feels longitudinal and honest.
OUTCOME
  O1  Ordinary chat, jokes and short follow-ups use deterministic routing and
      never pay for a separate intent-classifier call.
  O2  Sparse and rich histories both produce a bounded, source-labelled
      context packet, with calibrated sparse-data instructions.
  O3  Only the speaker's own visible Takes, current Ideal Text and shared
      coach words reach the prompt; project chat, foreign rows and private
      settings do not.
  O4  English and Polish target the immediate typed message language.
O5  A source change, explicit invalidation or TTL expiry refreshes the derived
     packet; cache hits and logical DB reads are observable within a budget.
  O6  Scores, rankings, verdicts, digits and other forbidden output fail
      closed to the existing chat path.
  O7  An older named talk keeps its exact Take, saved audience and goal.
  O8  Similar talks require a clear choice, and comparable passages stay on the same slide.
  O9  When feedback is missing, the coach uses available passages and one relevant reviewed exercise.
  O10 Saved vocal observations reach the coach with the exact spoken passage from the selected Take.
  O11 A comparison uses the two requested recent Takes and gives its example in the reply text.
  O12 A missing clip can receive a speakable example with a delivery direction from words alone.
PROVES   O11 -> test_last_two_recordings_get_one_sayable_line_in_speaking_coach_text
         O12 -> test_missing_audio_can_offer_the_words_and_an_example_delivery
         O1 -> test_routes_without_an_llm_classifier
         O2 -> test_sparse_and_rich_contexts_are_explicit
         O3 -> test_rich_context_is_owner_scoped_and_has_no_project_chat
         O4 -> test_content_language_is_preserved_for_english_and_polish
         O5 -> test_cache_refreshes_and_respects_the_read_budget
         O6 -> test_forbidden_generated_output_falls_back
         O7 -> test_named_older_talk_uses_exact_take_and_hybrid_retrieval
         O8 -> test_similar_talks_are_disambiguated_before_retrieval, test_comparison_grounds_the_same_slide_without_feedback
         O9 -> test_missing_feedback_uses_one_relevant_library_exercise
         O10 -> test_selected_take_supplies_passage_and_delivery_without_shared_feedback
WHY      Speaking Coach redesign and activation, 2026-11-18.
"""
from __future__ import annotations

import json
import re
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from services import speaking_coach

USER = "speaker-1"


def _take(take_id, arc_id, created_at, text, *, user_id=USER, index=1):
    return {
        "id": take_id,
        "user_id": user_id,
        "owner_principal_id": f"principal-{user_id}",
        "recording_id": f"recording-{take_id}",
        "arc_id": arc_id,
        "take_index": index,
        "created_at": created_at,
        "analysis_state": "ready",
        "recording_kind": "spoken",
        "paired_session_id": None,
        "intake_context": {"topic": f"topic-{arc_id}", "audience": "team"},
        "slide_transcripts": [{"index": 0, "transcript": text}],
    }


class FakeTakes:
    def __init__(self, index_rows, sessions):
        self.index_rows = index_rows
        self.sessions = sessions
        self.calls = {"index": 0, "many": 0, "slides": 0}

    def list_user_arc_sessions(self, user_id, **_kwargs):
        self.calls["index"] += 1
        return [row for row in self.index_rows if row.get("user_id", user_id) == user_id]

    def get_arc_sessions_many(self, arc_ids):
        self.calls["many"] += 1
        return {
            arc: [
                {key: value for key, value in row.items()
                 if key != "slide_transcripts"}
                for row in self.sessions.get(arc, [])
            ]
            for arc in arc_ids
        }

    def get_slide_transcripts_many(self, session_ids):
        self.calls["slides"] += 1
        return {
            str(row["id"]): {
                "id": row["id"],
                "user_id": row.get("user_id"),
                "slide_transcripts": row.get("slide_transcripts"),
            }
            for rows in self.sessions.values()
            for row in rows
            if str(row.get("id")) in {str(value) for value in session_ids}
        }


class FakeDB:
    def __init__(self, *, rich=True):
        arc_a = "project-a"
        arc_b = "project-b"
        self.client = None
        self.profile = {"domain": "product", "goal": "speak clearly"} if rich else {}
        self.takes = FakeTakes(
            [
                {"id": "a1", "user_id": USER, "arc_id": arc_a,
                 "take_index": 1, "created_at": "2026-01-01", "status": "completed"},
                {"id": "a2", "user_id": USER, "arc_id": arc_a,
                 "take_index": 2, "created_at": "2026-02-01", "status": "completed"},
                {"id": "b1", "user_id": USER, "arc_id": arc_b,
                 "take_index": 1, "created_at": "2026-03-01", "status": "completed"},
            ] if rich else [],
            {
                arc_a: [
                    _take("a1", arc_a, "2026-01-01", "The opening was hesitant and long.", index=1),
                    _take("a2", arc_a, "2026-02-01", "The opening is shorter and clearer.", index=2),
                    _take("foreign", arc_a, "2026-03-01", "FOREIGN PRIVATE TRANSCRIPT", user_id="other", index=3),
                ],
                arc_b: [
                    _take("b1", arc_b, "2026-03-01", "I explain the customer problem plainly.", index=1),
                ],
            },
        )
        self.ideal = {
            arc_a: {"source_take_session_id": "a2", "payload": {"text": "A concise opening about the customer problem."}},
            arc_b: {"source_take_session_id": "b1", "payload": {"text": "A practical story for the team."}},
        }
        self.lounge_was_read = False

    def get_user_profile(self, user_id):
        assert user_id == USER
        return dict(self.profile)

    def get_ideal_text_document_core(self, arc_id, user_id):
        assert user_id == USER
        return self.ideal.get(arc_id)

    def list_sent_coach_take_words(self, take_ids, *, limit):
        assert limit > 0
        return [{"take_session_id": take_ids[0], "text": "Lead with the customer problem.",
                 "shared_at": "2026-02-02"}] if take_ids else []

    def list_shared_moment_answers(self, user_id, take_ids, *, limit):
        assert user_id == USER and limit > 0
        return [{"owner_user_id": USER, "take_session_id": take_ids[0],
                 "answer_text": "The clear opening gave the audience a place to enter.",
                 "shared_at": "2026-02-03"}] if take_ids else []

    def get_lounge_messages_page(self, *_args, **_kwargs):
        self.lounge_was_read = True
        raise AssertionError("Speaking Coach must not read project chat history")


def _config(**overrides):
    values = {
        "SPEAKING_COACH_ENABLED": True,
        "SPEAKING_COACH_CONTEXT_CACHE_TTL_SECONDS": 60,
        "SPEAKING_COACH_MAX_DB_READS": 16,
        "SPEAKING_COACH_MAX_PROJECTS": 4,
        "SPEAKING_COACH_MAX_EVIDENCE": 12,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _result(answer, evidence=(), **extra):
    return SimpleNamespace(
        text=json.dumps({"answer": answer, "evidence": list(evidence), **extra}), parsed=None,
        model="gpt-4o-mini", duration_ms=12,
    )


def test_routes_without_an_llm_classifier():
    from services.llm_config import SPEC_SPEAKING_COACH

    assert speaking_coach.classify_turn("tell me a joke") == "general"
    assert speaking_coach.classify_turn("powiedz mi żart") == "general"
    assert speaking_coach.classify_turn("what changed between my takes?") == "longitudinal"
    assert speaking_coach.classify_turn("what changed in my recording?") == "longitudinal"
    assert speaking_coach.classify_turn("jak mogę nagrać nowy Take?") == "product_faq"
    assert speaking_coach.classify_turn(
        "and this?", [{"role": "assistant", "content": "What matters most?"}]
    ) == "follow_up"
    assert speaking_coach.classify_turn("what is Willab?") == "product_faq"

    database = FakeDB(rich=False)
    calls = []

    def generate(**kwargs):
        calls.append(kwargs)
        return _result("That sounds like a useful place to start.")

    with patch("services.llm.chat_complete", generate), \
            patch("services.master_doc_rag._classify_intent",
                  side_effect=AssertionError("classifier must not run")):
        answer = speaking_coach.answer(
            database, USER, "what should I practise?", history=[],
            app_config=_config(),
        )
    assert answer is not None
    assert len(calls) == 1
    assert calls[0]["surface"] == "speaking_coach"
    assert calls[0]["spec"] is SPEC_SPEAKING_COACH


def test_chat_librarian_uses_the_coach_before_private_legacy_context():
    from services import chat_query

    database = FakeDB(rich=False)
    payload = {"answer": "A grounded answer.", "show_record_ui": False,
               "suggested_action": None}
    debug = {"route": "longitudinal", "model_calls": 1}
    with patch("services.speaking_coach.answer", return_value=(payload, debug)), \
            patch("services.master_doc_rag.answer_question",
                  side_effect=AssertionError("legacy path must not run")), \
            patch.object(database, "get_user_settings",
                         side_effect=AssertionError("private notes must not run"),
                         create=True):
        # The database double is intentionally minimal: a Coach answer
        # must settle before the legacy context readers are even imported.
        response, intent = chat_query._librarian(
            database, USER, "what changed?", [], _config(), None,
        )
    assert intent == "speaking_coach"
    assert response["answer"] == "A grounded answer."


def test_the_coach_uses_the_speakers_memory_without_exposing_it():
    database = FakeDB()
    database.get_speaker_memory = lambda _uid: {"note": "- Concrete examples help this speaker."}
    captured = []
    def generate(**kwargs):
        captured.append(kwargs)
        return _result("Your examples make the idea concrete.")
    with patch("services.llm.chat_complete", generate):
        response = speaking_coach.answer(database, USER, "What is my strongest point?", app_config=_config())
    assert response is not None
    assert "Concrete examples help this speaker." in captured[0]["system"]
    assert "Concrete examples help this speaker." not in json.dumps(response)
    assert response[1]["model_calls"] == 1


def test_sparse_and_rich_contexts_are_explicit():
    speaking_coach.clear_cache()
    captured = []

    def generate(**kwargs):
        captured.append(kwargs)
        return _result("We can start with one small experiment and see what you notice.")

    with patch("services.llm.chat_complete", generate):
        result = speaking_coach.answer(
            FakeDB(rich=False), USER, "how should I begin?", history=[],
            app_config=_config(),
        )
    assert result is not None
    assert "sparse cold start" in captured[0]["system"]
    assert result[1]["evidence_count"] == 0

    speaking_coach.clear_cache()
    captured.clear()
    rich_database = FakeDB(rich=True)
    with patch("services.llm.chat_complete", generate):
        result = speaking_coach.answer(
            rich_database, USER, "what changed in my opening across my talks?", history=[],
            app_config=_config(),
        )
    assert result is not None
    system = captured[0]["system"]
    assert "progression" in system
    assert "earlier spoken passage" in system
    assert "more recent spoken passage" in system
    assert result[1]["project_count"] == 2
    assert result[1]["take_count"] == 3
    assert rich_database.takes.calls["slides"] == 1


def test_rich_context_is_owner_scoped_and_has_no_project_chat():
    speaking_coach.clear_cache()
    database = FakeDB(rich=True)
    captured = []

    def generate(**kwargs):
        captured.append(kwargs)
        return _result("The newer opening gives us something concrete to explore.")

    with patch("services.llm.chat_complete", generate):
        result = speaking_coach.answer(
            database, USER, "what changed?", history=[], app_config=_config(),
        )
    assert result is not None
    system = captured[0]["system"]
    assert "FOREIGN PRIVATE TRANSCRIPT" not in system
    assert not database.lounge_was_read
    assert "private admin" not in system.lower()
    context_only = system.lower().split("longitudinal context", 1)[-1]
    assert "kpi" not in context_only
    assert "score" not in context_only


def test_screen_history_drops_project_bubbles_when_metadata_is_present():
    from services.chat_query import screen_history

    assert screen_history([
        {"role": "assistant", "content": "project-only",
         "metadata": {"arc_id": "project-a"}},
        {"role": "assistant", "content": "coach-safe"},
    ]) == [{"role": "assistant", "content": "coach-safe"}]


@pytest.mark.parametrize(
    ("question", "generated", "language_marker"),
    [
        ("What changed in my opening overall?", "Your opening is clearer now.", "English (en)"),
        ("Co ogólnie zmieniło się w moim początku?", "Twój początek jest teraz jaśniejszy.", "Polish (pl)"),
    ],
)
def test_content_language_is_preserved_for_english_and_polish(
    question, generated, language_marker,
):
    speaking_coach.clear_cache()
    captured = []

    def generate(**kwargs):
        captured.append(kwargs)
        return _result(generated)

    with patch("services.llm.chat_complete", generate):
        result = speaking_coach.answer(
            FakeDB(rich=True), USER, question, history=[], app_config=_config(),
        )
    assert result is not None
    assert language_marker in captured[0]["system"]
    assert result[1]["model_calls"] == 1
    assert result[1]["total_latency_ms"] == (
        result[1]["retrieval_ms"] + result[1]["model_duration_ms"]
    )


def test_cache_refreshes_and_respects_the_read_budget():
    speaking_coach.clear_cache()
    database = FakeDB(rich=True)
    config = _config()
    first = speaking_coach.build_context(database, USER, app_config=config)
    second = speaking_coach.build_context(database, USER, app_config=config)
    assert not first.cache_hit
    assert second.cache_hit
    assert database.takes.calls["many"] == 1
    assert database.takes.calls["slides"] == 1

    database.takes.index_rows.append({
        "id": "a3", "user_id": USER, "arc_id": "project-a",
        "take_index": 3, "created_at": "2026-04-01", "status": "completed",
    })
    third = speaking_coach.build_context(database, USER, app_config=config)
    assert not third.cache_hit
    assert database.takes.calls["many"] == 2

    speaking_coach.invalidate(USER)
    fourth = speaking_coach.build_context(database, USER, app_config=config)
    assert not fourth.cache_hit

    speaking_coach.clear_cache()
    with patch.object(speaking_coach.time, "monotonic", side_effect=(100.0, 100.0, 102.0)):
        fresh = speaking_coach.build_context(
            database, USER,
            app_config=_config(SPEAKING_COACH_CONTEXT_CACHE_TTL_SECONDS=1),
        )
        warm = speaking_coach.build_context(
            database, USER,
            app_config=_config(SPEAKING_COACH_CONTEXT_CACHE_TTL_SECONDS=1),
        )
        stale = speaking_coach.build_context(
            database, USER,
            app_config=_config(SPEAKING_COACH_CONTEXT_CACHE_TTL_SECONDS=1),
        )
    assert not fresh.cache_hit
    assert warm.cache_hit
    assert not stale.cache_hit

    speaking_coach.clear_cache()
    bounded = speaking_coach.build_context(
        FakeDB(rich=True), USER,
        app_config=_config(SPEAKING_COACH_MAX_DB_READS=3),
    )
    assert bounded.db_reads == 3
    assert bounded.budget_exceeded


def test_cached_evidence_loses_a_withdrawn_take_and_its_ideal_text_immediately():
    speaking_coach.clear_cache()
    database = FakeDB(rich=True)
    first = speaking_coach.build_context(database, USER, app_config=_config())
    assert any("concise opening" in item.text for item in first.evidence)
    with patch("services.speaker_lookup._takes_in_force",
               side_effect=lambda _db, rows: {r["id"] for r in rows if r["id"] != "a2"}):
        refreshed = speaking_coach.build_context(database, USER, app_config=_config())
    assert not refreshed.cache_hit
    assert not any("concise opening" in item.text or "shorter and clearer" in item.text
                   for item in refreshed.evidence)


def test_forbidden_generated_output_falls_back():
    speaking_coach.clear_cache()
    calls = []

    def generate(**kwargs):
        calls.append(kwargs)
        return _result("Your score is 9.")

    with patch("services.llm.chat_complete", generate):
        result = speaking_coach.answer(
            FakeDB(rich=False), USER, "how am I doing?", history=[],
            app_config=_config(),
        )
    assert result is None
    assert len(calls) == 1


def _saved_projects(*takes):
    database = FakeDB(rich=False)
    database.takes.sessions = {}
    for take in takes:
        database.takes.sessions.setdefault(take["arc_id"], []).append(take)
        database.takes.index_rows.append({key: value for key, value in take.items()
                                          if key != "slide_transcripts"})
    return database


def _named_take(title, arc, number, created_at, text, *, deck=None):
    take = _take(f"{arc}-take-{number}", arc, created_at, text, index=number)
    take["intake_context"]["topic"] = title
    if deck:
        take["intake_context"]["slides"] = [{"id": value, "title": value} for value in deck]
    return take


def _reference(system, phrase):
    return next(match[1] for line in system.splitlines()
                if phrase in line and (match := re.match(r"- \[(E\d+);", line)))


@pytest.mark.parametrize(("transcript", "expected"), [
    ("Modlitwa daje mi oparcie przed rozmową. Jutro poproszę o szczerą opinię.", True),
    ("Kolega powiedział: „To ważna rozmowa. Modlitwa daje mi oparcie.” Jutro poproszę o szczerą opinię.", False),
])
def test_only_the_speakers_own_support_is_highlighted_in_the_reflection(transcript, expected):
    take = _named_take("Prośba o opinię", "opinion", 1, "2026-01-01", transcript)
    database = _saved_projects(take)

    def generate(**kwargs):
        assert ("Speaker's explicitly stated source of support" in kwargs["system"]) is expected
        return _result("Mówisz o tym, że jutro poprosisz o szczerą opinię.")

    with patch("services.llm.chat_complete", generate), patch("services.llm.embed", return_value=None):
        assert speaking_coach.answer(
            database, USER, "Co zauważasz o mnie w nagraniu Prośba o opinię?",
            app_config=_config(),
        )


def test_named_older_talk_uses_exact_take_and_hybrid_retrieval():
    from services.chat_query import _librarian

    speaking_coach.clear_cache()
    selected = _named_take("School Garden", "garden", 1, "2025-01-01", "")
    selected["intake_context"].update(
        audience="student council",
        strategic_context="Desired call to action: Approve a garden trial.",
    )
    exact_words = "We can water the raised beds after class."
    selected["slide_transcripts"] = [
        {"index": 0, "transcript": "I'd like you to hear our garden plan. " * 40},
        {"index": 1, "transcript": exact_words},
    ]
    later_takes = [_named_take("School Garden", "garden", number, f"2025-01-0{number}",
                              "THIS IS A DIFFERENT TAKE.") for number in range(2, 7)]
    newer_projects = [_named_take(f"School Club {i}", f"new-{i}", 1, f"2026-01-0{i}",
                                  "DIFFERENT PROJECT.") for i in range(1, 6)]
    db = _saved_projects(selected, *later_takes, *newer_projects)
    db.ideal["garden"] = {
        "source_take_session_id": "garden-take-6",
        "payload": {"text": "The current garden proposal."},
    }
    provider_inputs = []

    def embed(texts, **_kwargs):
        provider_inputs.extend(texts)
        return [[1.0, 0.0], *([1.0, 0.0] if exact_words in text else [0.0, 1.0]
                              for text in texts[1:])]

    def generate(**kwargs):
        prompt = kwargs["system"]
        assert "student council" in prompt and "Approve a garden trial." in prompt
        assert "THIS IS A DIFFERENT TAKE" not in prompt and "DIFFERENT PROJECT" not in prompt
        return _result("You made the upkeep sound manageable.", [_reference(prompt, exact_words), "E999"])

    question = "What makes the upkeep feel manageable in School Garden Take 1?"
    config = _config(SPEAKING_COACH_MAX_EVIDENCE=2)
    with patch("services.llm.embed", embed), patch("services.llm.chat_complete", generate):
        reply, intent = _librarian(db, USER, question, [], config)
        follow_up = speaking_coach.answer(
            db, USER, "What about the ending?", history=[{"role": "user", "content": question}],
            app_config=config,
        )
    assert intent == "speaking_coach"
    debug = reply["debug"]
    assert debug["scope"] == "resolved" and debug["take_count"] == 1 and debug["semantic_search"]
    assert reply["answer"] == "You made the upkeep sound manageable."
    assert reply["bubbles"] == [reply["answer"]]
    assert follow_up is not None and follow_up[0]["answer"] == reply["answer"]
    assert "coach_moment" not in reply.get("row_metadata", {})
    assert any("The current garden proposal." in item for item in provider_inputs)
    assert any("Lead with the customer problem." in item for item in provider_inputs)
    assert not any("DIFFERENT PROJECT" in item or "THIS IS A DIFFERENT TAKE" in item
                   for item in provider_inputs)


def test_similar_talks_are_disambiguated_before_retrieval():
    speaking_coach.clear_cache()
    db = _saved_projects(
        _named_take("Board Update", "board", 1, "2026-01-01", "Unrelated board words."),
        _named_take("Board Update Europe", "europe", 1, "2025-01-01", "The Europe remarks."),
    )
    question = "What should I change in my presentation?"
    with patch("services.llm.chat_complete", side_effect=AssertionError("ask before generating")):
        unclear = speaking_coach.answer(db, USER, question, app_config=_config())
    assert unclear is not None and unclear[1]["scope"] == "clarify"
    assert unclear[0]["answer"].endswith("?")
    assert db.takes.calls["many"] == 0 and db.takes.calls["slides"] == 0

    def generate(**kwargs):
        assert "The Europe remarks." in kwargs["system"]
        assert "Unrelated board words." not in kwargs["system"]
        assert any(question in row["content"] for row in kwargs["messages_override"])
        return _result("Let’s focus on the Europe remarks.")

    with patch("services.llm.embed", return_value=None), patch("services.llm.chat_complete", generate):
        scoped = speaking_coach.answer(
            db, USER, "Board Update Europe", history=[{"role": "user", "content": question}],
            app_config=_config(),
        )
    assert scoped is not None and scoped[1]["project_count"] == 1

    with patch("services.llm.chat_complete", side_effect=AssertionError("the requested Take is absent")):
        unavailable = speaking_coach.answer(db, USER, "Board Update Europe Take 4", app_config=_config())
    assert unavailable is not None and unavailable[1]["scope"] == "unavailable"
    assert db.takes.calls["slides"] == 1


def test_selected_take_supplies_passage_and_delivery_without_shared_feedback():
    from services.llm_config import SPEC_SPEAKING_COACH_TAKE

    speaking_coach.clear_cache()
    words = "Please approve the pilot today."
    selected = _named_take("Campus Pitch", "campus", 1, "2026-01-01", words)
    later = _named_take("Campus Pitch", "campus", 2, "2026-01-02", "LATER TAKE WORDS")
    db = _saved_projects(selected, later)
    reads = []

    def snippets(ids):
        reads.append(ids)
        return {selected["id"]: [
            {"id": "selected-clip", "session_id": selected["id"], "transcript": words,
             "metrics": {"wpm": 188, "pause_ratio": 0.04, "stickiness": {"composite": 0.9}}},
            {"session_id": later["id"], "transcript": "LATER TAKE WORDS",
             "metrics": {"vocal_cues": ["UNRELATED LOUD ENDING"]}},
        ]}

    def generate(**kwargs):
        assert kwargs["spec"] is SPEC_SPEAKING_COACH_TAKE
        prompt = kwargs["system"]
        line = next(line for line in prompt.splitlines() if "; delivery_cues;" in line)
        assert "Take 1" in line and words in line
        assert "pace: a bit fast" in line
        assert "188" not in line and "stickiness" not in line
        assert "UNRELATED LOUD ENDING" not in prompt and "LATER TAKE WORDS" not in prompt
        assert "shared_coach_feedback" not in prompt
        reference = _reference(prompt, "Delivery across the whole passage")
        return _result("You made the request directly and spoke quickly. Where could you give it more room?",
                       [reference], practise=True)

    with (
        patch.object(db, "get_snippets_by_sessions", snippets, create=True),
        patch.object(db, "list_sent_coach_take_words", return_value=[]),
        patch.object(db, "list_shared_moment_answers", return_value=[]),
        patch("services.llm.embed", return_value=None),
        patch("services.llm.chat_complete", generate),
    ):
        result = speaking_coach.answer(
            db, USER, "What can you tell me about my delivery in Campus Pitch Take 1?",
            app_config=_config(),
        )
    assert reads == [[selected["id"]]]
    assert result is not None
    assert "/chat/take/" not in result[0]["answer"]
    assert result[0]["row_metadata"] == {
        "speaking_recording_focus": {
            "arc_id": "campus", "take_session_id": selected["id"], "snippet_id": "selected-clip",
        },
    }
    from services import chat_practice, chat_query

    _, saved = chat_query._chat_turn_rows(
        db, USER, "Look at my delivery", result[0]["answer"],
        row_metadata=result[0]["row_metadata"], place="speaking",
    )
    assert saved[1]["metadata"][chat_practice.SIGNATURE]
    opening = {**snippets([selected["id"]])[selected["id"]][0], "id": "other-clip",
               "transcript": "ANOTHER CLIP FROM THE SAME TAKE."}
    saved_rows = [saved[1], saved[0]]
    with (
        patch.object(db, "get_snippets_by_sessions", return_value={selected["id"]: [
            opening, snippets([selected["id"]])[selected["id"]][0],
        ]}, create=True),
        patch.object(db, "get_lounge_messages_page", return_value=saved_rows),
        patch("services.llm.embed", return_value=None),
        patch("services.llm.chat_complete") as model,
    ):
        def continue_same_clip(**kwargs):
            assert words in kwargs["system"]
            assert "ANOTHER CLIP" not in kwargs["system"]
            assert "LATER TAKE WORDS" not in kwargs["system"]
            return _result("Try the same line with a pause before the request.")

        model.side_effect = continue_same_clip
        follow_up = speaking_coach.answer(db, USER, "Can we practise it?", app_config=_config())
    assert follow_up is not None
    assert follow_up[0]["row_metadata"][chat_practice.RECORDING_FOCUS]["snippet_id"] == "selected-clip"


def test_comparison_grounds_the_same_slide_without_feedback():
    speaking_coach.clear_cache()
    first = _named_take("Campus Pitch", "campus", 1, "2026-01-01", "", deck=["ask", "plan"])
    second = _named_take("Campus Pitch", "campus", 2, "2026-01-02", "", deck=["plan", "ask"])
    first["slide_transcripts"] = [
        {"index": 0, "transcript": "Please support the idea."},
        {"index": 1, "transcript": "Unrelated archived plan."},
    ]
    second["slide_transcripts"] = [
        {"index": 0, "transcript": "The proposed layout is small."},
        {"index": 1, "transcript": "Please approve the pilot today."},
    ]
    db = _saved_projects(first, second)

    def snippets(_ids):
        return {first["id"]: [
            {"session_id": first["id"], "transcript": "Please support the idea.",
             "metrics": {"vocal_cues": ["Steady delivery on the ask."]}},
            {"session_id": first["id"], "transcript": "Unrelated archived plan.",
             "metrics": {"vocal_cues": ["Quicker delivery on the plan."]}},
        ]}

    def generate(**kwargs):
        prompt = kwargs["system"]
        assert "earlier spoken passage: Please support the idea." in prompt
        assert "more recent spoken passage: Please approve the pilot today." in prompt
        assert "Steady delivery on the ask." in prompt
        assert "Quicker delivery on the plan." not in prompt
        assert "Unrelated archived plan." not in prompt
        assert "shared_coach_feedback" not in prompt
        return _result("Your ask now names the decision.", [_reference(prompt, "earlier spoken passage:")])

    with (
        patch.object(db, "get_snippets_by_sessions", snippets, create=True),
        patch.object(db, "list_sent_coach_take_words", return_value=[]),
        patch.object(db, "list_shared_moment_answers", return_value=[]),
        patch("services.llm.embed", return_value=None),
        patch("services.llm.chat_complete", generate),
    ):
        result = speaking_coach.answer(
            db, USER, "Compare slide 2 in Campus Pitch between Takes 1 and 2.",
            app_config=_config(),
        )
    assert result is not None
    assert not result[1]["semantic_search"]
    assert result[0]["answer"] == "Your ask now names the decision."
    assert "coach_moment" not in result[0].get("row_metadata", {})


def test_missing_feedback_uses_one_relevant_library_exercise():
    speaking_coach.clear_cache()
    db = _saved_projects(_named_take("Campus Pitch", "campus", 1, "2026-01-01",
                                    "Please approve the pilot today."))
    catalogue = [
        {"title": "Land the full stop", "instruction": "Pause after your request.",
         "acoustic_problem_tags": ["rushing"]},
        {"title": "Clear syllables", "instruction": "Separate your words.",
         "acoustic_problem_tags": ["word_compression"]},
    ]

    def generate(**kwargs):
        prompt = kwargs["system"]
        assert "Land the full stop" in prompt and "Pause after your request." in prompt
        assert "Clear syllables" not in prompt
        assert "shared_coach_feedback" not in prompt
        return _result("Try Land the full stop. Pause after your request.")

    with (
        patch.object(db, "list_active_diagnostic_exercises", return_value=catalogue, create=True),
        patch.object(db, "list_sent_coach_take_words", return_value=[]),
        patch.object(db, "list_shared_moment_answers", return_value=[]),
        patch("services.llm.chat_complete", generate),
    ):
        result = speaking_coach.answer(
            db, USER, "What exercise can I try for rushing in Campus Pitch?", app_config=_config(),
        )
    assert result is not None and "Pause after your request." in result[0]["answer"]



def test_last_two_recordings_get_one_sayable_line_in_speaking_coach_text():
    speaking_coach.clear_cache()
    pitch = _named_take("Board pitch", "board", 1, "2026-11-20", "I’m asking for approval today.")
    demo = _named_take("Demo", "demo", 2, "2026-11-21", "I think we could maybe start the pilot with support.")
    old = _named_take("Demo", "demo", 1, "2026-11-19", "Old wording outside the comparison.")
    database = _saved_projects(pitch, demo, old)

    def generate(**kwargs):
        prompt = kwargs["system"]
        assert "I’m asking for approval today." in prompt
        assert "start the pilot with support." in prompt
        assert "Old wording outside the comparison." not in prompt
        source = _reference(prompt, "I think we could maybe")
        wording = kwargs["response_format_override"]["json_schema"]["schema"]["properties"]["wording"]
        assert wording["type"] == "object"
        assert source in wording["properties"]["source"]["enum"]
        return _result("In the demo, lead with the recommendation.", [source], wording={
            "words": "I recommend we start the pilot with support.", "delivery": None, "source": source,
            "arc_id": "a-model-cannot-choose-an-id",
        })

    with patch("services.llm.embed", return_value=None), patch("services.llm.chat_complete", generate):
        result = speaking_coach.answer(database, USER,
            "Across my last two recordings, what would make me sound more confident?", app_config=_config())
    assert result is not None
    assert not result[0].get("row_metadata")
    assert result[0]["answer"].split("\n\n")[-1] == "I recommend we start the pilot with support."


def test_missing_audio_can_offer_the_words_and_an_example_delivery():
    speaking_coach.clear_cache()
    take = _named_take("Pilot", "pilot", 1, "2026-11-21", "Zacznijmy w piątek.")
    database = _saved_projects(take)

    def generate(**kwargs):
        prompt = kwargs["system"]
        assert "No recorded delivery observations are available" in prompt
        source = _reference(prompt, "Zacznijmy w piątek.")
        wording = kwargs["response_format_override"]["json_schema"]["schema"]["properties"]["wording"]
        assert wording["properties"]["delivery"]["type"] == "string"
        assert wording["properties"]["source"]["enum"] == [source]
        return _result("Z samych słów prośba jest jasna. Spróbuj tak.", [source], wording={
            "words": "Zacznijmy w piątek.", "delivery": "Zrób krótką pauzę przed „w piątek”.", "source": source,
        })

    with patch("services.llm.embed", return_value=None), patch("services.llm.chat_complete", generate):
        result = speaking_coach.answer(database, USER, "Czy na końcu brzmiałem pewnie?", app_config=_config())
    assert result is not None
    assert not result[0].get("row_metadata")
    assert result[0]["answer"].split("\n\n")[1:] == [
        "Zacznijmy w piątek.", "Zrób krótką pauzę przed „w piątek”.",
    ]
