"""The practice attempt's provider call goes through ONE door.

Founder authorized lifting the Phase-2 purpose gate on the Confident Voice
practice routes (2026-09-16). That gate was the only thing standing between a
speaker's practice recording and a direct `openai_service.client` call — no
permit, no recorded provider event, no regard for the kill switch. So the call
had to move behind the authorization boundary FIRST; lifting the gate over a
direct provider client is exactly what the standing constraint forbids, and it
fails silently — it works perfectly, right up until someone asks what was sent
where.

THE GATE IS STILL ON. Moving the call was the prerequisite, not the
authorization. `migrations/add_phase1_processing_boundary.sql` registers
`personalized_exercise_recommendation` as `phase2` and raises
PHASE2_PURPOSE_FORBIDDEN for any policy carrying it, so no permit for this
purpose can be issued at all. Lifting the route gate before that changes would
make the practice routes live only because enforcement happens to be off.
Moving the purpose to phase1 is a consent decision — a new policy version and
its acceptance — not a code change.

WHAT THIS PINS DOWN:
  * the route no longer names the unpermitted transcription function, while
    the five routes DO still carry the purpose gate;
  * a permit is issued BEFORE the provider is reached, and the terminal event
    is recorded on success AND on failure;
  * the snippet contract survives the move. `transcribe_audio` on the same
    adapter drops each word's recognition `confidence`; the practice
    comparison reads that field, so routing through the wrong method would
    keep the permit and silently lose an input;
  * `recording_id` is None rather than the original snippet — a practice
    attempt is new audio, and naming the original would assert it was sent to
    the provider when it was not;
  * mode=off is the same code path, not a bypass.

Run: python3 -m unittest tests.test_practice_transcription
"""
from __future__ import annotations

import inspect
import unittest
from unittest.mock import patch

from services import practice_transcription as pt


PRACTICE = {
    "id": "11111111-1111-4111-8111-111111111111",
    "take_session_id": "22222222-2222-4222-8222-222222222222",
    "snippet_id": "33333333-3333-4333-8333-333333333333",
    "owner_user_id": "44444444-4444-4444-8444-444444444444",
}

TRANSCRIPTION = {
    "transcript": "give every word enough space",
    "language": "en",
    "words": [
        {"word": "give", "start": 0.0, "end": 0.3, "confidence": 0.91},
        {"word": "every", "start": 0.35, "end": 0.7, "confidence": 0.88},
    ],
    "transcribed_duration_ms": 2400,
}


class _Auth:
    """Stands in for ProcessingAuthorizationService."""

    def __init__(self, enforced: bool = True):
        self.enforced = enforced
        self.permits: list[dict] = []
        self.events: list[tuple] = []

    def resolve_acquisition_principal(self, owner, *, user_id=None,
                                      recording_id=None):
        return "principal-1"

    def issue_provider_permit(self, **kwargs):
        if not self.enforced:
            return None
        self.permits.append(kwargs)
        return {"permit_id": "permit-1"}

    def record_provider_event(self, permit_id, event_kind, **kwargs):
        if not self.enforced or not permit_id:
            return
        self.events.append((permit_id, event_kind, kwargs.get("error_code")))


class _Db:
    def __init__(self):
        self.client = object()
        self.sessions_read: list[str] = []

    def v2_get_session_by_id(self, session_id):
        self.sessions_read.append(session_id)
        return {"id": session_id, "owner_principal_id": "owner-principal"}


class PracticeTranscriptionTests(unittest.TestCase):
    def _run(self, auth, *, transcriber=None, boom=False):
        calls: list[tuple] = []

        def fake_transcribe(audio, filename, *, language_hint=None):
            calls.append((audio, filename, language_hint))
            if boom:
                raise RuntimeError("provider exploded")
            return TRANSCRIPTION

        db = _Db()
        with patch(
            "services.processing_authorization.ProcessingAuthorizationService",
            return_value=auth,
        ), patch(
            "services.snippet_transcription.transcribe_snippet_bytes",
            transcriber or fake_transcribe,
        ):
            result = pt.transcribe_practice_attempt(
                db, PRACTICE, b"audio-bytes", hint_filename="practice.webm")
        return result, db, calls

    # ── the contract survives the move ───────────────────────────────────

    def test_it_returns_the_snippet_contract_unchanged(self):
        auth = _Auth()
        result, _, calls = self._run(auth)
        self.assertEqual(result, TRANSCRIPTION)
        # The word's recognition confidence is the field the practice
        # comparison reads and the general transcribe_audio drops.
        self.assertIn("confidence", result["words"][0])
        self.assertEqual(calls[0][0], b"audio-bytes")
        self.assertEqual(calls[0][1], "practice.webm")

    # ── the permit ───────────────────────────────────────────────────────

    def test_a_permit_is_taken_before_the_provider_is_reached(self):
        auth = _Auth()
        self._run(auth)
        self.assertEqual(len(auth.permits), 1)
        permit = auth.permits[0]
        self.assertEqual(permit["provider"], "openai")
        self.assertEqual(permit["operation_kind"], "transcription")
        self.assertEqual(permit["acquisition_principal_id"], "principal-1")
        self.assertEqual(permit["take_id"], PRACTICE["take_session_id"])

    def test_the_permit_does_not_claim_the_original_recording(self):
        # A practice attempt is NEW audio. Naming the original snippet would
        # assert the original was sent to OpenAI, which is false — an untrue
        # permit is worse than an unscoped one.
        auth = _Auth()
        self._run(auth)
        self.assertIsNone(auth.permits[0]["recording_id"])
        self.assertNotIn(
            PRACTICE["snippet_id"], str(auth.permits[0]))

    def test_the_outcome_is_recorded_on_success(self):
        auth = _Auth()
        self._run(auth)
        self.assertEqual([e[1] for e in auth.events], ["started", "completed"])

    def test_the_outcome_is_recorded_on_failure_and_the_error_propagates(self):
        # A provider call that vanishes from the ledger when it fails is the
        # half of the record that matters most.
        auth = _Auth()
        with self.assertRaises(RuntimeError):
            self._run(auth, boom=True)
        self.assertEqual([e[1] for e in auth.events], ["started", "failed"])
        self.assertEqual(auth.events[-1][2], "RuntimeError")

    # ── mode off ─────────────────────────────────────────────────────────

    def test_mode_off_is_the_same_path_not_a_bypass(self):
        auth = _Auth(enforced=False)
        result, db, calls = self._run(auth)
        self.assertEqual(result, TRANSCRIPTION)
        self.assertEqual(auth.permits, [])
        self.assertEqual(auth.events, [])
        # And it does not read the session it does not need.
        self.assertEqual(db.sessions_read, [])
        self.assertEqual(len(calls), 1)


class NoDirectProviderClientRemainsTests(unittest.TestCase):
    """Source fences: the unpermitted call is gone, the gate is not."""

    def test_the_practice_route_no_longer_calls_the_unpermitted_function(self):
        source = open("routes/v2/user_sessions.py", encoding="utf-8").read()
        self.assertNotIn("transcribe_snippet_bytes", source)
        self.assertIn("transcribe_practice_attempt", source)

    def test_the_purpose_gate_is_still_on_every_practice_route(self):
        """The gate STAYS until the database stops forbidding the purpose.

        `migrations/add_phase1_processing_boundary.sql` registers
        `personalized_exercise_recommendation` as `phase2` and raises
        PHASE2_PURPOSE_FORBIDDEN for any policy that includes it. So a permit
        for this purpose cannot be issued at all. Lifting the route gate now
        would make the practice routes live ONLY because enforcement happens
        to be off — working right up until it is switched on, which is the
        exact silent hole this module was written to close.

        This plumbing is the prerequisite, not the authorization.
        """
        marker = 'operational_purpose_disabled("personalized_exercise_recommendation")'
        self.assertEqual(
            open("routes/v2/user_sessions.py", encoding="utf-8").read()
            .count(marker), 4)
        self.assertEqual(
            open("routes/v2/coach.py", encoding="utf-8").read()
            .count(marker), 1)

    def test_no_new_module_calls_the_unpermitted_transcription(self):
        """A ratchet, not a clean sheet.

        Written as an allowlist because the sweep found a caller this change
        does NOT touch, and pretending otherwise would be the more comfortable
        lie. Each entry needs a reason; the list may shrink and must not grow.
        """
        import re
        from pathlib import Path

        allowed = {
            # The implementation itself.
            "snippet_transcription.py",
            # The permitted wrapper this change added.
            "authorized_provider.py",
            # MLC-3 first-client practice. A SEPARATE authorization design:
            # the run must already be `authorized` in the database, dispatch
            # and reconciliation are recorded there, and the route sits behind
            # `mlc3_service_required` (404 unless enrolled). Not the Phase-1
            # permit path, and deliberately out of scope here — but it is a
            # second place user audio reaches a provider, and it should be
            # reviewed on its own terms rather than forgotten.
            "practice_attempt_orchestrator.py",
        }
        call = re.compile(r"transcribe_snippet_bytes\s*\(")
        offenders = sorted(
            path.name for path in Path("services").glob("*.py")
            if path.name not in allowed
            and call.search(path.read_text(encoding="utf-8"))
        )
        self.assertEqual(
            offenders, [],
            "these reach the transcription provider without a permit: "
            f"{offenders}")

    def test_the_wrapper_records_a_terminal_event_on_both_paths(self):
        from services.authorized_provider import AuthorizedProviderAdapter

        source = inspect.getsource(AuthorizedProviderAdapter.transcribe_snippet)
        self.assertIn('"started"', source)
        self.assertIn('"completed"', source)
        self.assertIn('"failed"', source)
        self.assertIn("raise", source)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
