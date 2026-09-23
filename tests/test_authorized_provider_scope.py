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

import pathlib
import re
import threading
from contextvars import copy_context

from services.authorized_provider import (
    ProviderCoordinates,
    authorize_protected_generation,
    protected_provider_scope,
)
from services.parallel import start_scoped_thread

ROOT = pathlib.Path(__file__).resolve().parents[1]

# The four dispatches the audit named, each reached from a live Take path.
FANOUT_SITES = (
    "services/say_it_stronger.py",
    "services/coach_comment_drafter.py",
    "services/conversation_summary.py",
    "services/snippet_truncation.py",
)


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

    def test_a_raw_thread_is_exactly_what_this_replaces(self):
        """The defect itself, pinned.

        If this ever starts passing, contextvars changed under us and the
        helper's whole reason for existing needs re-reading.
        """
        adapter = _Permit()
        seen: dict = {}

        def work():
            _, permit_id = authorize_protected_generation("say_it_stronger")
            seen["permit_id"] = permit_id

        with protected_provider_scope(adapter, idempotency_prefix="take-1"):
            raw = threading.Thread(target=work, daemon=True)
            raw.start()
            raw.join(timeout=5)

        assert seen.get("permit_id") is None

    def test_each_thread_gets_its_own_context_copy(self):
        """A loop spawning one thread per snippet is the normal case here, and
        one `Context` cannot be entered by two threads at once — so the copy
        has to happen per call, not once in the caller."""
        adapter = _Permit()
        # Four parties: the three workers plus this thread, so all of
        # them are inside authorize_protected_generation at once. That
        # overlap is the point — a shared Context would raise here.
        started = threading.Barrier(4, timeout=5)
        results: list = []
        lock = threading.Lock()

        def work():
            started.wait()
            _, permit_id = authorize_protected_generation("draft")
            with lock:
                results.append(permit_id)

        with protected_provider_scope(adapter, idempotency_prefix="take-1"):
            threads = [start_scoped_thread(work) for _ in range(3)]
            started.wait()
            for thread in threads:
                thread.join(timeout=5)

        assert len(results) == 3 and all(results), (
            "concurrent threads did not each get their own context"
        )
        assert len(set(adapter.keys)) == 3, (
            "two calls shared an idempotency key, so one permit would be "
            "reused for two provider calls"
        )

    def test_the_helper_and_run_parallel_agree(self):
        """Both are the same rule. `run_parallel` is the pooled form and this
        is the detached form; a scope that survives one must survive the
        other, or the next person picks whichever happens to be broken."""
        adapter = _Permit()

        with protected_provider_scope(adapter, idempotency_prefix="take-1"):
            pooled = copy_context().run(
                lambda: authorize_protected_generation("pooled")[1]
            )

        assert pooled, "run_parallel's copy_context form lost the scope"


class TestTheFourSitesUseIt:
    """Source-level, and deliberately narrow: it catches a REGRESSION at the
    four dispatches the audit found, which the property tests above cannot see
    because they never import these modules' call sites."""

    def test_no_named_fanout_starts_a_raw_thread(self):
        offenders = []
        for name in FANOUT_SITES:
            source = (ROOT / name).read_text(encoding="utf-8")
            stripped = re.sub(r"#[^\n]*", "", source)
            if re.search(r"threading\.Thread\s*\(", stripped):
                offenders.append(name)

        assert offenders == [], (
            "a fire-and-forget dispatch went back to threading.Thread, which "
            f"silently drops the Take's provider scope: {offenders}"
        )

    def test_every_named_fanout_reaches_the_helper(self):
        missing = [
            name for name in FANOUT_SITES
            if "start_scoped_thread" not in (ROOT / name).read_text(encoding="utf-8")
        ]
        assert missing == [], f"fan-out no longer routed through the helper: {missing}"
