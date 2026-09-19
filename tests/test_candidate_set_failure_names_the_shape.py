"""When the candidate-set write fails, say what shape was sent -- not what.

PRODUCTION, 2026-09-19. The V3 lane reached its candidate-set write for the
FIRST TIME (until `piece_has_no_part_id` was fixed, `prepare_v3_service_
inventory` always returned None, so this RPC had never once been called), and
PostgreSQL answered:

    {'code': '22P02', 'details': 'Token "feedback" is invalid.',
     'message': 'invalid input syntax for type json'}

That is the JSON lexer reading a bare word and stopping at a `-`. The only
`feedback-` strings in the call are the bundle's own `idempotency_key`
(`feedback-exposure:<take>:<version>:<hash>`) and one SQL literal
(`feedback-v3-service-candidate-set:`). So some TEXT is being read as JSON,
and the question is only which field.

Static reading did not answer it: the function body has no text->json cast of
a bundle field, every `idempotency_key` column is TEXT, both triggers on the
inserted tables fire only on UPDATE/DELETE, and the client sends a plain JSON
body. The remaining way to find it cheaply is to see which field arrives as a
string that should not be one.

THE PRIVACY LINE, which is the whole reason this file exists. The bundle
carries the speaker's transcript. Logging it to chase a type error would
trade one day of debugging for a permanent copy of someone's words in a log
aggregator. `_payload_shape` renders KINDS and LENGTHS only, and these tests
exist to keep it that way -- a future hand that "just adds the value to make
it easier" fails here.
"""
from __future__ import annotations

import logging
import unittest
from unittest.mock import PropertyMock, patch

from services.first_client_repository import _payload_shape

SECRET = "the exact words the speaker said out loud"


class ItRendersTheShape(unittest.TestCase):
    def test_each_kind_reads_at_a_glance(self):
        shape = _payload_shape({
            "obj": {"a": 1, "b": 2},
            "arr": [1, 2, 3],
            "text": "abcd",
            "flag": True,
            "missing": None,
            "count": 7,
        })
        self.assertIn("obj=o2", shape)
        self.assertIn("arr=a3", shape)
        self.assertIn("text=s4", shape)
        self.assertIn("flag=b", shape)
        self.assertIn("missing=n", shape)
        self.assertIn("count=int", shape)

    def test_keys_are_sorted_so_two_failures_can_be_compared(self):
        shape = _payload_shape({"zulu": 1, "alpha": 2})
        self.assertLess(shape.index("alpha"), shape.index("zulu"))

    def test_a_bundle_that_is_not_an_object_says_so(self):
        # The case that would explain the error: a field arriving as a string
        # where the SQL expects an object.
        self.assertEqual(_payload_shape("feedback-exposure:x"), "<str>")
        self.assertEqual(_payload_shape(None), "<NoneType>")
        self.assertEqual(_payload_shape([1, 2]), "<list>")

    def test_a_string_field_is_visibly_a_string(self):
        # `transcript=s1200` instead of `transcript=o7` IS the answer, and no
        # content is needed to see it.
        self.assertIn("transcript=s19",
                      _payload_shape({"transcript": "feedback-exposure:x"}))


class ItLeaksNothing(unittest.TestCase):
    """The property that must survive every future edit to this diagnostic."""

    def test_no_string_value_appears_in_the_shape(self):
        shape = _payload_shape({
            "transcript": SECRET,
            "idempotency_key": "feedback-exposure:take:version:hash",
        })
        self.assertNotIn(SECRET, shape)
        self.assertNotIn("feedback-exposure", shape)
        self.assertIn("transcript=s", shape)

    def test_nested_content_is_not_reached_at_all(self):
        # One level only. A nested transcript is `o3`, and its words stay in
        # the database where they belong.
        shape = _payload_shape({
            "transcript": {"text": SECRET, "slides": [SECRET], "id": "x"},
        })
        self.assertNotIn(SECRET, shape)
        self.assertEqual(shape, "transcript=o3")

    def test_the_caller_logs_the_shape_and_not_the_bundle(self):
        # Asserted on the log record, because the leak would happen at the
        # call site, not in the helper.
        from services import first_client_repository as repo

        class _Boom:
            def rpc(self, *_args, **_kwargs):
                raise RuntimeError("22P02 invalid input syntax for type json")

        instance = repo.FirstClientRepository.__new__(
            repo.FirstClientRepository)
        bundle = {
            "owner_principal_id": "o", "project_id": "p", "take_id": "t",
            "candidates": [{}], "selected_keys": [{}], "versions": {"v": 1},
            "input_hash": "h", "idempotency_key": "feedback-exposure:t",
            "transcript": {"text": SECRET},
        }
        with patch.object(
            repo.FirstClientRepository, "client",
            new_callable=PropertyMock, return_value=_Boom(),
        ), self.assertLogs(
            "services.first_client_repository", level="WARNING",
        ) as caught:
            self.assertIsNone(
                instance.record_feedback_v3_service_candidate_set(bundle))
        line = caught.output[0]
        self.assertNotIn(SECRET, line)
        self.assertIn("shape=[", line)
        self.assertIn("transcript=o1", line)

    def test_the_error_leads_the_line_and_is_readable_on_a_phone(self):
        # SECOND CORRECTION TO THIS ORDERING (2026-09-20). #566 promoted the
        # shape ahead of the take id so a 36-character id could not clip the
        # answer. Right lesson, too literal: the shape is ~220 characters,
        # so it clipped `error=` instead -- and a production stand-down was
        # then read as "the RPC did not raise at all", from a line that had
        # simply run out of room. A phone log list shows roughly the first
        # sixty characters, so the error has to start inside them.
        from services import first_client_repository as repo

        class _Boom:
            def rpc(self, *_args, **_kwargs):
                raise RuntimeError("22P02 invalid input syntax for type json")

        instance = repo.FirstClientRepository.__new__(
            repo.FirstClientRepository)
        with patch.object(
            repo.FirstClientRepository, "client",
            new_callable=PropertyMock, return_value=_Boom(),
        ), self.assertLogs(
            "services.first_client_repository", level="WARNING",
        ) as caught:
            instance.record_feedback_v3_service_candidate_set({
                "owner_principal_id": "o", "project_id": "p",
                "take_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                "candidates": [{}], "selected_keys": [{}],
                "versions": {"v": 1}, "input_hash": "h",
                "idempotency_key": "feedback-exposure:" + "x" * 130,
                "transcript": {"text": SECRET},
            })
        line = caught.output[0]
        message = line.split(":", 2)[-1]
        self.assertLess(message.index("RuntimeError"), 60)
        self.assertLess(line.index("shape=["), line.index("take="))


class TheGuardThatFiredIsTheFirstThingOnTheLine(unittest.TestCase):
    """THIRD CORRECTION TO ONE LINE (2026-09-20), and the last layer.

    #566 put the shape ahead of the take id. #572 put the error ahead of
    the shape. Both right, neither enough: PostgREST renders
    ``{'code': ..., 'details': ..., 'hint': ..., 'message': ...}`` and
    ``message`` -- the only field naming WHICH guard fired -- sorts last.
    On a phone that reads ``error={'code': 'P000...`` and stops, and
    ``P0001`` means only "some plpgsql RAISE fired"; there are eight in
    this one function.
    """

    def _line(self, raised: Exception) -> str:
        from services import first_client_repository as repo

        class _Boom:
            def rpc(self, *_args, **_kwargs):
                raise raised

        instance = repo.FirstClientRepository.__new__(
            repo.FirstClientRepository)
        with patch.object(
            repo.FirstClientRepository, "client",
            new_callable=PropertyMock, return_value=_Boom(),
        ), self.assertLogs(
            "services.first_client_repository", level="WARNING",
        ) as caught:
            instance.record_feedback_v3_service_candidate_set({
                "owner_principal_id": "o", "project_id": "p",
                "take_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                "candidates": [{}], "selected_keys": [{}],
                "versions": {"v": 1}, "input_hash": "h",
                "idempotency_key": "feedback-exposure:" + "x" * 130,
                "transcript": {"text": SECRET},
            })
        return caught.output[0]

    def test_the_postgres_code_and_message_lead(self):
        # The exact production shape: a dict in args[0], message last.
        error = Exception({
            "code": "P0001",
            "details": None,
            "hint": None,
            "message": "FEEDBACK_V3_SERVICE_SOURCE_NOT_LIVE",
        })
        line = self._line(error)
        body = line.split(":", 2)[-1]
        self.assertLess(body.index("P0001/FEEDBACK_V3_SERVICE_SOURCE_NOT_LIVE"),
                        60)
        self.assertLess(line.index("P0001/"), line.index("shape=["))

    def test_the_full_error_still_follows(self):
        # The head is a convenience, not a replacement: `details` and `hint`
        # were what solved the 22P02, so nothing may be dropped.
        line = self._line(Exception({
            "code": "22P02", "details": 'Token "feedback" is invalid.',
            "message": "invalid input syntax for type json",
        }))
        self.assertIn("raw=", line)
        self.assertIn('Token "feedback" is invalid.', line)

    def test_an_error_with_attributes_rather_than_a_dict(self):
        class _ApiError(Exception):
            code = "P0001"
            message = "FEEDBACK_V3_SERVICE_LEDGER_INCOMPLETE"

        self.assertIn("P0001/FEEDBACK_V3_SERVICE_LEDGER_INCOMPLETE",
                      self._line(_ApiError("boom")))

    def test_a_plain_exception_falls_back_to_its_type(self):
        # Never blank, and never a guess.
        self.assertIn("TimeoutError", self._line(TimeoutError("slow")))

    def test_the_head_leaks_no_transcript(self):
        from services.first_client_repository import _error_head
        self.assertNotIn(SECRET, _error_head(Exception({
            "code": "P0001", "message": SECRET[:0] or "GUARD",
        })))
        self.assertNotIn(SECRET, self._line(Exception({
            "code": "P0001", "message": "GUARD",
        })))

    def test_the_shape_leads_the_line_not_the_take_id(self):
        # Same ordering lesson as `_decline`: a 36-character id in front of
        # the answer means the line is clipped before anyone reads it.
        from services import first_client_repository as repo

        class _Boom:
            def rpc(self, *_args, **_kwargs):
                raise RuntimeError("boom")

        instance = repo.FirstClientRepository.__new__(
            repo.FirstClientRepository)
        with patch.object(
            repo.FirstClientRepository, "client",
            new_callable=PropertyMock, return_value=_Boom(),
        ), self.assertLogs(
            "services.first_client_repository", level="WARNING",
        ) as caught:
            instance.record_feedback_v3_service_candidate_set({
                "owner_principal_id": "o", "project_id": "p",
                "take_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                "candidates": [{}], "selected_keys": [{}], "versions": {"v": 1},
                "input_hash": "h", "idempotency_key": "k",
            })
        line = caught.output[0]
        self.assertLess(line.index("shape=["), line.index("take="))


class TheGuardsThatAlreadyExistStillHold(unittest.TestCase):
    def test_an_incomplete_bundle_is_still_refused_before_the_call(self):
        # The required-key check returns None WITHOUT calling the RPC. Keeping
        # that means the shape log only ever describes a bundle that was
        # actually sent.
        from services import first_client_repository as repo

        class _NeverCalled:
            def rpc(self, *_args, **_kwargs):  # pragma: no cover
                raise AssertionError("the RPC must not be reached")

        instance = repo.FirstClientRepository.__new__(
            repo.FirstClientRepository)
        with patch.object(
            repo.FirstClientRepository, "client",
            new_callable=PropertyMock, return_value=_NeverCalled(),
        ):
            with self.assertLogs(
                "services.first_client_repository", level="WARNING",
            ) as caught:
                self.assertIsNone(
                    instance.record_feedback_v3_service_candidate_set(
                        {"take_id": "t"}))
            # Refused, but no longer SILENTLY: the caller turns this into
            # `candidate_set_write_failed`, identical to an RPC error from the
            # outside, so it has to say which field was empty.
            self.assertIn("missing=", caught.output[0])
            self.assertIn("owner_principal_id", caught.output[0])
            self.assertIsNone(
                instance.record_feedback_v3_service_candidate_set("not a dict"))


if __name__ == "__main__":  # pragma: no cover
    logging.basicConfig(level=logging.WARNING)
    unittest.main()
