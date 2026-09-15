"""Regression tests for the in-app recording prompts.

One surface ships the "record here" gesture and it used to break
(the second, the state-machine coaching chat, was deleted on 2026-09-15
with the coaching lane — audit Q-A6 — and its STEP 9 tests with it):

  The Lounge FAQ chat (services/master_doc_rag). RULE H used to
     bundle "microphone hardware" into the hard-decline list, so the
     LLM responded to "can I just record here?" with the camera-decline
     template — even though the chat endpoint accepts a multipart
     audio_file and dispatches it to casual_voice_analytics. RULE H
     now carves the in-app mic out; RULE I owns the record path. NOTE:
     show_record_ui is now FORCED FALSE in code (the in-app mic was
     removed — the official-recording button is always present), so the
     tests verify it stays false even when the model returns true, and
     that the answer never borrows the camera-decline language.

Tests are pure-Python: the RAG tests
inject a fake OpenAIService whose client returns a canned structured
response. No network, no env vars.
"""
import json
import unittest

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
_FAKE_SCRIPT = [
    {"position": 1, "text": "What were you trying to convey there?"},
    {"position": 2, "text": "What did the audience need from you?"},
    {"position": 3, "text": "What changed mid-sentence?"},
    {"position": 4, "text": "Where else does that show up?"},
    {"position": 5, "text": "What would you do differently?"},
]
_FAKE_COACHING_ID = "22222222-2222-4222-8222-222222222222"


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

    def test_record_intent_keeps_show_record_ui_false_and_avoids_camera_decline(self):
        """answer_question on 'can I just record it here' keeps
        show_record_ui=FALSE (forced in code — the in-app mic was removed; the
        official-recording button is always present) EVEN when the model returns
        true, and the answer does NOT borrow the camera-decline template."""
        canned = json.dumps({
            "answer": "Sure — tap the mic to record.",
            "show_record_ui": True,  # the model's value is ignored now
        })
        self._install_fake(canned)
        payload, _debug = master_doc_rag.answer_question(
            "can I just record it here"
        )
        # Always false — the model's true is overridden in code.
        self.assertFalse(payload["show_record_ui"])
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

    def test_fallback_payload_defaults_record_flag_false(self):
        """When the LLM is unavailable, the record flag must default
        False. The fallback is a polite document-grounded message, not
        a record prompt. (show_upload_ui was removed end-to-end.)"""
        fallback = master_doc_rag._fallback_payload()
        self.assertIn("answer", fallback)
        self.assertFalse(fallback["show_record_ui"])
        self.assertNotIn("show_upload_ui", fallback)

    def test_empty_question_returns_record_flag_false(self):
        """Sanity: the empty-question short-circuit must include the
        record flag so the route handler's lookups don't KeyError."""
        payload, debug = master_doc_rag.answer_question("")
        self.assertEqual(debug.get("error"), "empty_question")
        self.assertFalse(payload["show_record_ui"])
        self.assertNotIn("show_upload_ui", payload)


if __name__ == "__main__":
    unittest.main()
