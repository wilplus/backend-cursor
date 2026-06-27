"""F1 degrade observability (no contract change). Pure / best-effort.

Run: python3 -m unittest test_f1_observability
"""
from __future__ import annotations

import sys
import unittest
from unittest import mock

from services.f1_observability import observe_f1_degrade


class _FakeScope:
    def __init__(self, sink):
        self.sink = sink

    def set_tag(self, k, v):
        self.sink.tags.append((k, v))

    def set_context(self, k, v):
        self.sink.contexts.append((k, v))


class _FakeScopeCM:
    def __init__(self, sink):
        self.sink = sink

    def __enter__(self):
        return _FakeScope(self.sink)

    def __exit__(self, *a):
        return False


class _FakeSentry:
    def __init__(self):
        self.messages, self.exceptions, self.tags, self.contexts = [], [], [], []

    def push_scope(self):
        return _FakeScopeCM(self)

    def capture_message(self, msg, level=None):
        self.messages.append(msg)

    def capture_exception(self, exc):
        self.exceptions.append(exc)


class F1ObservabilityTests(unittest.TestCase):
    def test_never_raises_when_sentry_absent(self):
        # import sentry_sdk → ImportError must be swallowed (no behavior change).
        with mock.patch.dict(sys.modules, {"sentry_sdk": None}):
            observe_f1_degrade("polish_compose_failed", slides=3)
            observe_f1_degrade("x", exc=ValueError("boom"))

    def test_condition_degrade_captures_message(self):
        fake = _FakeSentry()
        with mock.patch.dict(sys.modules, {"sentry_sdk": fake}):
            observe_f1_degrade("polish_empty_result", slides=2)
        self.assertEqual(fake.messages, ["f1.degrade:polish_empty_result"])
        self.assertEqual(fake.exceptions, [])
        self.assertIn(("f1_degrade", "polish_empty_result"), fake.tags)

    def test_exception_degrade_captures_exception(self):
        fake = _FakeSentry()
        err = ValueError("boom")
        with mock.patch.dict(sys.modules, {"sentry_sdk": fake}):
            observe_f1_degrade("polish_compose_failed", exc=err, slides=1)
        self.assertEqual(fake.exceptions, [err])
        self.assertEqual(fake.messages, [])  # exc path doesn't double-emit a message

    def test_scopeless_sentry_still_captures(self):
        # An older/odd sentry without push_scope/new_scope must still capture.
        class _Bare:
            def __init__(self): self.msgs = []
            def capture_message(self, msg, level=None): self.msgs.append(msg)
        bare = _Bare()
        with mock.patch.dict(sys.modules, {"sentry_sdk": bare}):
            observe_f1_degrade("readout_rederive_failed")
        self.assertEqual(bare.msgs, ["f1.degrade:readout_rederive_failed"])


if __name__ == "__main__":
    unittest.main()
