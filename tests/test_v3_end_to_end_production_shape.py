"""The whole V3 chain, with the shape production actually has.

WHY THIS FILE EXISTS (founder, 2026-09-19: "it's been like a 10th or
something iteration that you are saying it's the last step... at this stage
we are very slow").

He was right, and the reason was not the code. V3's back half had never once
executed in production -- ``piece_has_no_part_id`` stood it down before the
first write until #568 -- so every gate past that point was a FIRST
execution, and each one was being discovered through a fifteen-minute
deploy-record-read-the-log cycle.

Meanwhile ``tests/test_mlc3_first_client_feedback.py`` was green. It still is.
That is the part worth understanding, because a passing test suite over a
path that cannot run in production is worse than no test at all: it says the
path is fine.

TWO FIXTURE CHEATS HID EVERYTHING. In ``_source()`` there:

  1. ``served_text=document["text"]`` -- the Ideal Text IS the transcript.
     A V3 Confident Voice candidate carries ``document_span`` =
     ``{piece["start"], piece["end"]}``, which are character offsets into the
     TRANSCRIPT; ``_exact_transcript_evidence`` slices ``served_text`` with
     them. Make the two documents the same string and that is trivially
     correct. In production they are different documents of different
     lengths and the slice is meaningless or out of range.
  2. The bundle is built with no ``document_snapshot_id`` and no
     ``document_surface_sha256``, so ``snapshot_bound`` is False and the
     branch requiring ``target_text is not None`` is never entered.
     Production always passes both, so production is always snapshot-bound.

So the tests exercise the non-snapshot-bound path across one degenerate
document, and production runs the snapshot-bound path across two real ones.

THIS HARNESS IS THE OTHER SHAPE. The transcript carries exactly the fields
``build_transcript_document`` writes (no ``part_id`` -- #568 adds that
afterwards via ``bind_pieces_to_parts``, which is applied here too, the same
way the live path applies it). The Ideal Text is a DIFFERENT, shorter
document. The snapshot RPC returns the Ideal Text as its surface, because
that is what the live one returns. Nothing is hand-fitted to pass.

It is a harness before it is a regression test: it runs the chain end to end
in milliseconds so the remaining gates can be found together instead of one
per take recorded at midnight.
"""
from __future__ import annotations

import unittest
from hashlib import sha256
from unittest.mock import PropertyMock, patch

from services.ideal_text_parts import bind_pieces_to_parts

OWNER = "9f4e75b8-268b-468d-9111-000000000001"
PROJECT = "11111111-2222-4333-8444-555555555555"
TAKE = "8875d24c-a7c6-4881-88eb-e46fcb3b4177"
USER = "22222222-3333-4444-8555-666666666666"
RECORDING = "44444444-5555-4666-8777-888888888888"
SNIPPET = "d1b577c3-c1b9-463b-96d9-89f614f5a4c8"
SNAPSHOT = "33333333-4444-4555-8666-777777777777"
MEMBERSHIP = "55555555-6666-4777-8888-999999999999"

# ── THE TWO DOCUMENTS, AND THEY ARE NOT THE SAME ────────────────────────────
#
# What was SAID (the transcript): verbatim, hesitant, longer.
SPOKEN = (
    "So um what I wanted to say today is that our approach here is really "
    "quite different from what everyone else in this space has been doing "
    "for the last couple of years and I think that matters a lot actually"
)
# What the Ideal Text SAYS: the machine's cleaned-up document. Shorter, and
# every character offset into it means something different.
IDEAL = "Our approach is different from everyone else's, and that matters."


def _transcript_document() -> dict:
    """Exactly the shape `build_transcript_document` returns.

    Field-for-field from that function's own construction: pieces carry
    snippet/recording/audio/clip lineage and CHARACTER OFFSETS INTO `text`;
    paragraphs carry slide lineage and their own offsets. Neither carries
    `part_id` -- nothing in the builder writes one, which is the whole of
    what #564/#568 were about.
    """
    return {
        "text": SPOKEN,
        "take_session_id": TAKE,
        "take_index": 1,
        "pieces": [{
            "snippet_id": SNIPPET,
            "recording_id": RECORDING,
            "audio_ref": "https://audio.invalid/take.webm",
            "language": "en",
            "take_session_id": TAKE,
            "take_index": 1,
            "start": 0,
            "end": len(SPOKEN),
            "text": SPOKEN,
            "slide_index": 0,
            "start_offset_ms": 120,
            "duration_ms": 9400,
        }],
        "paragraphs": [{
            "slide_index": 0,
            "snippet_id": SNIPPET,
            "take_session_id": TAKE,
            "take_index": 1,
            "start": 0,
            "end": len(SPOKEN),
        }],
    }


def _bound_document() -> dict:
    """The transcript after the live path attaches Paragraph identity (#568).

    `_first_client_feedback` calls exactly this before handing the document
    to V3, so the harness does too. The parts are the ones the publish
    boundary now mints for the Ideal Text.
    """
    from services.ideal_text_parts import mint_machine_parts
    parts = mint_machine_parts(IDEAL)
    return bind_pieces_to_parts(
        _transcript_document(),
        served_text=IDEAL,
        slide_regions={0: (0, len(IDEAL))},
        parts=parts,
    )


def _snippets() -> list[dict]:
    return [{
        "id": SNIPPET,
        "session_id": TAKE,
        "recording_id": RECORDING,
        "start_offset_ms": 120,
        "duration_ms": 9400,
        "metrics": {"voice_confidence": {
            "version": "voice-confidence-universal-v3",
            "score": 0.63,
        }},
    }]


def _session() -> dict:
    return {
        "id": TAKE,
        "user_id": USER,
        "owner_principal_id": OWNER,
        "project_id": PROJECT,
        "recording_1_id": RECORDING,
        "take_index": 1,
    }


class _Database:
    """The four writes the live path makes, each succeeding.

    Succeeding ON PURPOSE. The point of the harness is to find every gate
    that fails on the DATA, so nothing here may fail on the plumbing -- a
    fake that refuses would just re-hide the next real gate behind itself.
    """

    def __init__(self) -> None:
        self.client = self
        self.bundle = None
        self.membership_payload = None
        self._rpc_data: dict = {}

    def rpc(self, _name, _payload):
        # THE SURFACE IS THE IDEAL TEXT, not the transcript. This one line is
        # the difference between this harness and the green suite: the live
        # RPC names the document on the SCREEN, and `prepare_first_client_
        # feedback` refuses unless `served_text` matches it byte for byte.
        self._rpc_data = {
            "snapshot_contract_version":
                "feedback-v3-candidate-source-snapshot-v1",
            "document_snapshot_id": SNAPSHOT,
            "source_generation": 1,
            "surface": IDEAL,
            "surface_sha256": sha256(IDEAL.encode("utf-8")).hexdigest(),
        }
        return self

    def execute(self):
        class _Result:
            data = self._rpc_data
        return _Result()

    def ensure_service_enrollment(self, **_payload):
        return {
            "id": "c0000000-0000-4000-8000-000000000001",
            "rollout_revision_id": "d0000000-0000-4000-8000-000000000001",
            "operation_mode": "general_service",
        }

    def record_feedback_v3_service_candidate_set(self, bundle):
        # THE REAL REPOSITORY METHOD, not a stand-in (2026-09-19). The first
        # version of this fake returned `{"candidate_set_id": ...}` directly
        # and so skipped the method entirely -- its required-key check, its
        # list/dict unwrapping, and its id comparison. That is the same kind
        # of hole the fixtures in `test_mlc3_first_client_feedback.py` had:
        # a harness that proves the data is good by not running the code
        # that judges it. Only the PostgreSQL call below is faked.
        self.bundle = bundle
        from services.first_client_repository import FirstClientRepository

        rpc_result = self._candidate_set_rpc_result(bundle)

        class _Client:
            def rpc(self, _name, _payload):
                return self

            def execute(self):
                class _R:
                    data = rpc_result
                return _R()

        instance = FirstClientRepository.__new__(FirstClientRepository)
        with patch.object(FirstClientRepository, "client",
                          new_callable=PropertyMock,
                          return_value=_Client()):
            return instance.record_feedback_v3_service_candidate_set(bundle)

    def _candidate_set_rpc_result(self, bundle):
        """What PostgreSQL hands back on the happy path.

        Overridden by the subclasses below to model the answers that are
        NOT exceptions -- the two the caller refuses in silence.
        """
        return {
            "candidate_set_id": bundle["candidate_set_id"],
            "candidate_count": len(bundle.get("candidates") or []),
            "selected_count": len(bundle.get("selected_keys") or []),
            "replayed": False,
        }

    def get_current_ideal_text_document_snapshot(self, _project_id):
        return {"id": SNAPSHOT, "source_take_session_id": TAKE}

    def freeze_feedback_v3_service_membership(self, payload):
        self.membership_payload = payload
        return {"id": MEMBERSHIP, "content_identity_sha256": "c" * 64}

    def prepare_feedback_v3_service_context(self, _payload):
        return {
            "n1_candidate_set_id": "66666666-7777-4888-8999-aaaaaaaaaaaa",
            "authorization_check_id": "77777777-8888-4999-8aaa-bbbbbbbbbbbb",
            "source_acquisition_receipt_id":
                "88888888-9999-4aaa-8bbb-cccccccccccc",
        }


def run_chain(database=None):
    """Drive the live entry point once. Returns whatever it returns."""
    from services.mlc3_first_client_feedback import (
        prepare_first_client_feedback,
    )
    return prepare_first_client_feedback(
        database=database if database is not None else _Database(),
        session=_session(),
        take_document=_bound_document(),
        served_text=IDEAL,
        snippets=_snippets(),
        suggestions={},
        feedback_candidates=[],
        owner_user_id=USER,
    )


class TheFixturesThemselvesAreTheFinding(unittest.TestCase):
    """Pin the two cheats, so neither can come back quietly."""

    def test_the_ideal_text_and_the_transcript_are_different_documents(self):
        # If a future edit makes these equal "to get the test passing", the
        # coordinate bug becomes invisible again exactly as it was.
        self.assertNotEqual(IDEAL, SPOKEN)
        self.assertLess(len(IDEAL), len(SPOKEN))

    def test_a_transcript_span_does_not_address_the_ideal_text(self):
        # THE BUG IN ONE ASSERTION. The candidate's `document_span` is
        # {piece.start, piece.end} -- transcript offsets -- and the evidence
        # builder slices `served_text` with them.
        piece = _transcript_document()["pieces"][0]
        self.assertGreater(piece["end"], len(IDEAL))

    def test_the_document_reaching_v3_is_snapshot_bound(self):
        # Production always passes both, so the branch requiring
        # `target_text is not None` is always entered. The green suite never
        # enters it.
        database = _Database()
        database.rpc("read_feedback_v3_candidate_source_snapshot_v1", {})
        self.assertEqual(database._rpc_data["surface"], IDEAL)
        self.assertNotEqual(database._rpc_data["surface"], SPOKEN)

    def test_the_builder_still_writes_no_part_id_of_its_own(self):
        # #568 attaches it afterwards; if the builder ever starts writing
        # one, this harness is modelling a shape that no longer exists.
        raw = _transcript_document()
        self.assertIsNone(raw["pieces"][0].get("part_id"))
        self.assertIsNone(raw["paragraphs"][0].get("part_id"))

    def test_binding_attaches_the_paragraph_the_live_path_attaches(self):
        bound = _bound_document()
        self.assertTrue(bound["pieces"][0].get("part_id"))


class TheChainProducesFeedback(unittest.TestCase):
    """The one that matters. Every gate, on production's shape."""

    def setUp(self) -> None:
        # The service flag, exactly as the existing suite sets it. Without
        # it `principal_is_allowlisted` is False and the function returns
        # None -- "not applicable" -- which is a correct answer to the wrong
        # question and would quietly make this harness vacuous.
        from unittest.mock import patch
        from config import Config
        patcher = patch.object(Config, "MLC3_SERVICE_ENABLED", True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_healthy_take_yields_at_least_one_visible_row(self):
        from services.mlc3_first_client_feedback import V3Unavailable
        result = run_chain()
        if isinstance(result, V3Unavailable):
            self.fail(f"V3 stood down: {result.reason}")
        self.assertIsNotNone(result, "V3 treated a service take as not applicable")
        assert result is not None
        self.assertGreaterEqual(len(result), 1)

    def test_the_confident_voice_row_points_at_the_ideal_text(self):
        from services.mlc3_first_client_feedback import V3Unavailable
        result = run_chain()
        if isinstance(result, V3Unavailable) or not result:
            self.skipTest("covered by the failure above")
        row = next(r for r in result
                   if r.get("feedback_family") == "confident_voice")
        span = row.get("span") or {}
        self.assertLessEqual(span.get("end", 10 ** 9), len(IDEAL))


class _ReturnsNothingUsable(_Database):
    """PostgreSQL ran the function and handed back no row."""

    def _candidate_set_rpc_result(self, bundle):
        return None


class _ReturnsADifferentSet(_Database):
    """A row came back, for a different candidate set."""

    def _candidate_set_rpc_result(self, bundle):
        return {"candidate_set_id": "00000000-0000-4000-8000-00000000dead"}


class TheWriteThatSucceedsAndSaysNothing(unittest.TestCase):
    """PRODUCTION, 2026-09-19, 23:59 — `candidate_set_write_failed` with no
    `shape=[` line beside it.

    That combination is itself the diagnosis: `shape=[` is logged only when
    the RPC RAISES, so its absence means PostgreSQL ran the function and
    returned cleanly. The write then failed on what came back -- and both of
    the ways that can happen returned None with no log at all, so the log
    could say only that something went wrong somewhere.
    """

    def setUp(self) -> None:
        from config import Config
        patcher = patch.object(Config, "MLC3_SERVICE_ENABLED", True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_no_usable_row_now_names_itself(self):
        from services.mlc3_first_client_feedback import V3Unavailable
        with self.assertLogs(
            "services.first_client_repository", level="WARNING",
        ) as caught:
            result = run_chain(_ReturnsNothingUsable())
        self.assertIsInstance(result, V3Unavailable)
        assert isinstance(result, V3Unavailable)
        self.assertEqual(result.reason, "candidate_set_write_failed")
        self.assertIn("returned no usable row", caught.output[0])
        self.assertIn("kind=NoneType", caught.output[0])

    def test_a_different_candidate_set_names_both_ids(self):
        from services.mlc3_first_client_feedback import V3Unavailable
        with self.assertLogs(
            "services.first_client_repository", level="WARNING",
        ) as caught:
            result = run_chain(_ReturnsADifferentSet())
        self.assertIsInstance(result, V3Unavailable)
        self.assertIn("id mismatch", caught.output[0])
        self.assertIn("0000dead", caught.output[0])

    def test_the_happy_path_logs_nothing(self):
        # A diagnostic that fires on success is a diagnostic people filter
        # out, and then it is not there when it matters.
        import logging
        with self.assertNoLogs(
            "services.first_client_repository", level=logging.WARNING,
        ):
            run_chain()

    def test_the_real_repository_method_is_what_runs(self):
        # THE HOLE THIS CLASS CLOSES. The first version of the fake returned
        # `{"candidate_set_id": ...}` directly, so the method that judges the
        # bundle never executed. Proven here by its required-key check: strip
        # a key and the REAL method must refuse before the RPC, naming the
        # field. A stand-in would happily return success.
        class _Incomplete(_Database):
            def record_feedback_v3_service_candidate_set(self, bundle):
                return super().record_feedback_v3_service_candidate_set(
                    {k: v for k, v in bundle.items() if k != "input_hash"})

        with self.assertLogs(
            "services.first_client_repository", level="WARNING",
        ) as caught:
            run_chain(_Incomplete())
        self.assertIn("missing=input_hash", caught.output[0])

    def test_the_chain_still_produces_rows_through_the_real_method(self):
        # And the happy path is unchanged by routing through it.
        from services.mlc3_first_client_feedback import V3Unavailable
        result = run_chain()
        self.assertNotIsInstance(result, V3Unavailable)
        assert result is not None
        self.assertGreaterEqual(len(result), 1)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
