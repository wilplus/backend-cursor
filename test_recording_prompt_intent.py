"""Regression tests for the in-app recording prompts.

Two surfaces ship the "record here" gesture and both used to break:

  1. The coaching state-machine chat. After the user walked through
     the Director's Script + acoustic targets, the chat ended without
     ever inviting them to record a fresh take — even though the
     POST /v2/coaching/trial-recording endpoint was wired and ready to
     accept that take. STEP 8 has been split into a BRIDGE (acoustic
     targets card, end=false) and a new STEP 9 (the re-record ask,
     trigger=show_trial_recording_mic). This file's first test class
     locks the prompt + schema in.

  2. The Lounge FAQ chat (services/master_doc_rag). RULE H used to
     bundle "microphone hardware" into the hard-decline list, so the
     LLM responded to "can I just record here?" with the camera-decline
     template — even though the chat endpoint accepts a multipart
     audio_file and dispatches it to casual_voice_analytics. RULE H
     now carves the in-app mic out; new RULE I detects record intent
     and sets show_record_ui=true. The second test class verifies the
     payload flows that flag through and that the answer never
     borrows the camera-decline language.

Tests are pure-Python: the state-machine tests work against the
prompt builder + schema directly (no LLM call), and the RAG tests
inject a fake OpenAIService whose client returns a canned structured
response. No network, no env vars.
"""
import json
import unittest

try:
    from services.coaching_state_machine import (
        STATE_MACHINE_RESPONSE_SCHEMA,
        build_state_machine_system_prompt,
        parse_state_machine_response,
    )
    _STATE_MACHINE_IMPORT_ERROR = None
except Exception as import_err:  # pragma: no cover - env/bootstrap guard
    STATE_MACHINE_RESPONSE_SCHEMA = None
    build_state_machine_system_prompt = None
    parse_state_machine_response = None
    _STATE_MACHINE_IMPORT_ERROR = import_err

# master_doc_rag itself imports lazily; the dependency the tests
# actually need is services.openai_service, which pulls in the
# `openai` package. Probe it at module-load so the skipIf reflects
# the real environment (a lightweight CI shard without `openai`
# installed skips the RAG class cleanly).
try:
    from services import master_doc_rag
    import services.openai_service  # noqa: F401 — import-only probe
    _RAG_IMPORT_ERROR = None
except Exception as import_err:  # pragma: no cover - env/bootstrap guard
    master_doc_rag = None
    _RAG_IMPORT_ERROR = import_err


# Reusable fixtures for the state-machine builder. The values are
# intentionally banal — the assertions look at structure and trigger
# strings, not pedagogy.
_FAKE_SNIPPET = {
    "id": "11111111-1111-4111-8111-111111111111",
    "admin_comment": "You sounded grounded right here.",
    "coach_label": "charisma",
}
_FAKE_TARGETS = {
    "target_wpm": 135,
    "ideal_wpm_min": 125,
    "ideal_wpm_max": 140,
    "target_dynamic_db": 9.5,
    "target_fillers_per_min": 1.0,
    "target_fillers_total": 3,
    "current_wpm": 168,
    "current_fillers": 7,
    "current_dynamic_db": 7.5,
}
_FAKE_SCRIPT = [
    {"position": 1, "text": "What were you trying to convey there?"},
    {"position": 2, "text": "What did the audience need from you?"},
    {"position": 3, "text": "What changed mid-sentence?"},
    {"position": 4, "text": "Where else does that show up?"},
    {"position": 5, "text": "What would you do differently?"},
]
_FAKE_COACHING_ID = "22222222-2222-4222-8222-222222222222"


@unittest.skipIf(
    _STATE_MACHINE_IMPORT_ERROR is not None,
    "state-machine tests require services.coaching_state_machine: "
    f"{_STATE_MACHINE_IMPORT_ERROR}",
)
class TestStateMachineStep9(unittest.TestCase):
    """The 9-step prompt must reach a re-record ask the frontend can
    wire up to /v2/coaching/trial-recording."""

    def test_schema_allows_step_9(self):
        """The structured-output schema must let the LLM emit step=9.

        Without this, the LLM cannot legally return the new terminal
        step and the response is rejected at parse time.
        """
        step_spec = STATE_MACHINE_RESPONSE_SCHEMA["schema"]["properties"]["step"]
        self.assertEqual(step_spec["minimum"], 1)
        self.assertEqual(step_spec["maximum"], 9)

    def test_schema_lists_show_trial_recording_mic_trigger(self):
        """The triggers enum must include the new mic-unlock value."""
        triggers_spec = (
            STATE_MACHINE_RESPONSE_SCHEMA["schema"]["properties"]["triggers"]
        )
        enum_values = triggers_spec["items"]["enum"]
        self.assertIn("show_trial_recording_mic", enum_values)

    def test_schema_exposes_trial_recording_object(self):
        """The trial_recording passthrough must be on the schema with
        the coaching_id + prompt_text shape the frontend expects."""
        props = STATE_MACHINE_RESPONSE_SCHEMA["schema"]["properties"]
        self.assertIn("trial_recording", props)
        tr_props = props["trial_recording"]["properties"]
        self.assertIn("coaching_id", tr_props)
        self.assertIn("prompt_text", tr_props)
        self.assertFalse(
            props["trial_recording"].get("additionalProperties", True),
            "trial_recording must be a closed object — additionalProperties=False",
        )

    def test_prompt_describes_step_9_and_emits_mic_trigger(self):
        """The system prompt must instruct the model on STEP 9 and
        tell it to set show_trial_recording_mic in triggers there."""
        prompt = build_state_machine_system_prompt(
            snippet=_FAKE_SNIPPET,
            acoustic_targets=_FAKE_TARGETS,
            director_script_questions=_FAKE_SCRIPT,
            user_first_name="Artur",
            coaching_id=_FAKE_COACHING_ID,
        )
        self.assertIn("STEP 9", prompt)
        self.assertIn("show_trial_recording_mic", prompt)
        # The trigger must be wired to STEP 9 specifically, not just
        # mentioned somewhere — guard against the trigger landing in
        # STEP 8 by accident.
        step_9_block = prompt.split("STEP 9", 1)[1]
        self.assertIn("show_trial_recording_mic", step_9_block)
        self.assertIn("trial_recording", step_9_block)

    def test_prompt_makes_step_8_a_bridge_not_a_close(self):
        """STEP 8 (acoustic targets) must hand off to STEP 9 — it is
        no longer the terminal step."""
        prompt = build_state_machine_system_prompt(
            snippet=_FAKE_SNIPPET,
            acoustic_targets=_FAKE_TARGETS,
            director_script_questions=_FAKE_SCRIPT,
            coaching_id=_FAKE_COACHING_ID,
        )
        # Split on the section header literal so we don't pick up an
        # incidental "STEP 8" reference inside an earlier step's
        # fallback instructions.
        step_8_marker = "STEP 8 — THE ACOUSTIC BRIDGE"
        step_9_marker = "STEP 9 — THE RE-RECORD ASK"
        self.assertIn(step_8_marker, prompt)
        self.assertIn(step_9_marker, prompt)
        step_8_block = (
            prompt.split(step_8_marker, 1)[1].split(step_9_marker, 1)[0]
        )
        # end=false on the bridge.
        self.assertIn("end=false", step_8_block)
        # STEP 8's emitted triggers must be exactly the targets card
        # (the mic-unlock trigger fires on STEP 9). The block also
        # contains an explicit "Do NOT emit show_trial_recording_mic
        # here" prohibition for the LLM, so we can't just substring-
        # match the trigger string — we look at the triggers= line.
        self.assertIn(
            "triggers=['show_acoustic_targets_card']", step_8_block
        )
        self.assertNotIn(
            "triggers=['show_trial_recording_mic']", step_8_block
        )

    def test_prompt_threads_coaching_id_for_step_9_payload(self):
        """The builder must echo coaching_id into the prompt so the
        LLM can pass it through on trial_recording.coaching_id."""
        prompt = build_state_machine_system_prompt(
            snippet=_FAKE_SNIPPET,
            acoustic_targets=_FAKE_TARGETS,
            director_script_questions=_FAKE_SCRIPT,
            coaching_id=_FAKE_COACHING_ID,
        )
        self.assertIn(_FAKE_COACHING_ID, prompt)

    def test_parse_accepts_step_9_with_mic_trigger(self):
        """parse_state_machine_response must accept a well-formed
        STEP 9 turn so the route handler doesn't drop it as
        malformed."""
        raw = json.dumps({
            "narration": (
                "Beautiful — now let's hear it again. Tap the mic "
                "and re-do that moment at around 135 WPM."
            ),
            "step": 9,
            "current_question_position": None,
            "triggers": ["show_trial_recording_mic"],
            "end": False,
            "trial_recording": {
                "coaching_id": _FAKE_COACHING_ID,
                "prompt_text": (
                    "Re-record that moment aiming for 135 WPM."
                ),
            },
        })
        parsed = parse_state_machine_response(raw)
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["step"], 9)
        self.assertIn("show_trial_recording_mic", parsed["triggers"])
        self.assertEqual(
            parsed["trial_recording"]["coaching_id"], _FAKE_COACHING_ID
        )


# ── Fake OpenAI plumbing for master_doc_rag tests ────────────────────


class _FakeMessage:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, content):
        self.message = _FakeMessage(content)


class _FakeResponse:
    def __init__(self, content):
        self.choices = [_FakeChoice(content)]


class _FakeCompletions:
    """Captures the messages list so tests can assert on the system
    prompt the LLM was given, and returns a caller-injected canned
    JSON string."""

    def __init__(self, canned_json):
        self.canned_json = canned_json
        self.last_messages = None
        self.last_kwargs = None

    def create(self, **kwargs):
        self.last_messages = kwargs.get("messages")
        self.last_kwargs = kwargs
        return _FakeResponse(self.canned_json)


class _FakeChat:
    def __init__(self, canned_json):
        self.completions = _FakeCompletions(canned_json)


class _FakeClient:
    def __init__(self, canned_json):
        self.chat = _FakeChat(canned_json)


class _FakeOpenAIService:
    """Stand-in for services.openai_service.OpenAIService. The
    constructor takes the JSON string we want chat.completions.create
    to return; the test inspects it via .client.chat.completions."""

    def __init__(self, canned_json):
        self.client = _FakeClient(canned_json)


@unittest.skipIf(
    _RAG_IMPORT_ERROR is not None,
    "master_doc_rag tests require services.openai_service "
    f"(install `openai` to run them locally): {_RAG_IMPORT_ERROR}",
)
class TestMasterDocRagRecordIntent(unittest.TestCase):
    """RULE I (record intent) must fire on 'can I record here' and
    must NOT fall through to RULE H's camera-decline template."""

    def setUp(self):
        # Re-imported per-test so the patches always start clean.
        import importlib
        import services.openai_service as openai_service_module
        self._openai_module = openai_service_module
        self._original_service = openai_service_module.OpenAIService

    def tearDown(self):
        self._openai_module.OpenAIService = self._original_service

    def _install_fake(self, canned_json):
        """Patch services.openai_service.OpenAIService to return a
        fake whose chat.completions.create yields canned_json."""
        captured: dict = {}

        def _factory():
            svc = _FakeOpenAIService(canned_json)
            captured["service"] = svc
            return svc

        self._openai_module.OpenAIService = _factory
        return captured

    def test_record_intent_sets_show_record_ui_and_avoids_camera_decline(self):
        """answer_question on 'can I just record it here' must return
        show_record_ui=True, show_upload_ui=False, and an answer that
        does NOT borrow the camera-decline template."""
        canned = json.dumps({
            "answer": "Sure — tap the mic to record.",
            "show_upload_ui": False,
            "show_record_ui": True,
        })
        self._install_fake(canned)
        payload, _debug = master_doc_rag.answer_question(
            "can I just record it here"
        )
        self.assertTrue(payload["show_record_ui"])
        self.assertFalse(payload["show_upload_ui"])
        # Spec invariant: must not echo the camera-decline template
        # even if the user says something that brushes capabilities.
        lowered = payload["answer"].lower()
        self.assertNotIn("camera", lowered)
        self.assertNotIn("cannot access", lowered)

    def test_system_prompt_carries_rule_i_and_carves_out_mic(self):
        """The prompt the LLM sees must teach it that RULE H excludes
        the mic and that RULE I owns the record path. Without these
        the model regresses to the camera decline."""
        canned = json.dumps({
            "answer": "Sure — tap the mic to record.",
            "show_upload_ui": False,
            "show_record_ui": True,
        })
        captured = self._install_fake(canned)
        master_doc_rag.answer_question("can I just record it here")

        svc = captured["service"]
        messages = svc.client.chat.completions.last_messages
        self.assertIsNotNone(messages, "fake OpenAI was never called")
        system_msg = next(m for m in messages if m["role"] == "system")
        sys_content = system_msg["content"]

        # New RULE I exists and names show_record_ui as its signal.
        self.assertIn("RULE I", sys_content)
        self.assertIn("show_record_ui", sys_content)
        # RULE H must explicitly mark recording as SUPPORTED so the
        # model knows not to route the user through the decline path.
        self.assertIn("SUPPORTED", sys_content)
        self.assertIn("RECORDING audio in-app", sys_content)
        # Guard against the bug we're fixing: the prompt must NOT
        # tell the model the app can't access the microphone.
        self.assertNotIn(
            "microphone hardware",
            sys_content,
            "RULE H still lists microphone hardware as non-capability — "
            "this is the bug we shipped to fix",
        )

    def test_fallback_payload_defaults_both_intent_flags_false(self):
        """When the LLM is unavailable, both intent flags must
        default False. The fallback is a polite document-grounded
        message, not a record-or-upload prompt."""
        fallback = master_doc_rag._fallback_payload()
        self.assertIn("answer", fallback)
        self.assertFalse(fallback["show_upload_ui"])
        self.assertFalse(fallback["show_record_ui"])

    def test_empty_question_returns_both_flags_false(self):
        """Sanity: the empty-question short-circuit must include both
        flags so the route handler's lookups don't KeyError."""
        payload, debug = master_doc_rag.answer_question("")
        self.assertEqual(debug.get("error"), "empty_question")
        self.assertFalse(payload["show_upload_ui"])
        self.assertFalse(payload["show_record_ui"])


if __name__ == "__main__":
    unittest.main()
