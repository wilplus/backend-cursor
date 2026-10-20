"""
STORY    As the founder, I want every outside AI call made from a background
         thread to carry the speaker's permit, so that no transcript leaves
         our servers without a record we can later delete.
OUTCOME
  O1  Work started with start_scoped_thread inside a protected scope gets
      a permit, issued by the same authority.
PROVES   O1 -> TestTheScopeSurvivesAThread::test_fanout_threads_inherit_protected_scope
WHY      B-6, ML provenance audit 2026-09-22: four background threads called
         the provider with no permit and nothing was recorded.
"""
from __future__ import annotations

from services.authorized_provider import (
    ProviderCoordinates,
    authorize_protected_generation,
    protected_provider_scope,
)
from services.parallel import start_scoped_thread


class _Permit:
    """The smallest thing the scope needs: an adapter that issues a permit."""

    def __init__(self):
        self.authorization = self
        self.coordinates = ProviderCoordinates("principal-1", "take-1", "rec-1")
        self.keys: list[str] = []

    def authorize_operation(self, _kind, *, manifest, idempotency_key):
        self.keys.append(idempotency_key)
        return {"permit_id": f"permit-{len(self.keys)}"}

    def record_provider_event(self, *_a, **_k):
        return None


class TestTheScopeSurvivesAThread:

    def test_fanout_threads_inherit_protected_scope(self):
        """The named regression test for B-6.

        Runs the real helper across a real thread boundary and asserts the
        child got a permit. Against `threading.Thread` this returns None.
        """
        adapter = _Permit()
        seen: dict = {}

        def work():
            service, permit_id = authorize_protected_generation("say_it_stronger")
            seen["service"] = service
            seen["permit_id"] = permit_id

        with protected_provider_scope(adapter, idempotency_prefix="take-1"):
            start_scoped_thread(work).join(timeout=5)

        assert seen.get("permit_id"), (
            "the thread called the provider with no permit — nothing would "
            "record that the transcript went out"
        )
        assert seen["service"] is adapter.authorization
