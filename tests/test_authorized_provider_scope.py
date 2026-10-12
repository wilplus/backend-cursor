"""A fire-and-forget thread keeps the Take's provider authority.

B-6 (major), ML provenance audit 2026-09-22.

`threading.Thread` does not copy contextvars — a raw daemon thread starts with
an EMPTY context. Four fire-and-forget dispatches started one from inside
`protected_provider_scope`, so in the child thread
`authorize_protected_generation` found no scope, returned `(None, None)`, and
`llm.chat_complete` went to the provider with the speaker's transcript and no
permit. Nothing raised and nothing was logged: no
`processing_provider_permits` row and no `processing_provider_operations` row,
so the purge subject graph never learns the transcript left the building and
the provider-deletion contract has nothing to act on.

`services.parallel.run_parallel` already had this right. The defect was that
the rule lived at that one call site rather than in a named function, so the
next four people who needed a thread wrote `threading.Thread(...)`.

These cases assert the PROPERTY (the scope survives the thread boundary) and
then the four call sites that had lost it, by source — a source assertion is
weak evidence on its own, which is why the property case above it drives the
real helper across a real thread.
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
