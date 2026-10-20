"""
STORY    As a speaker, I want my answer to Confident Voice feedback recorded
         as a valid decision on real production-shaped data, so that the
         feedback loop works outside tests.
OUTCOME
  O1  On production-shaped data (a transcript and a DIFFERENT, shorter Ideal
      Text, snapshot-bound), the chain runs end to end and serves a Confident
      Voice row that quotes the Ideal Text and is backed by the spoken words.
  O2  The speaker's answer to that row becomes a canonical decision carrying
      the row's own candidate, membership and exposure ids.
  O3  A candidate-set write that returns nothing usable (or another set's id)
      is logged, not silent; the feedback is still served, but without
      lineage, so no answer can attach to it.
PROVES   O1 -> test_the_chain_serves_feedback_on_two_real_documents
         O2 -> test_the_answer_is_a_canonical_decision_on_the_served_row
         O3 -> test_a_write_that_returns_nothing_is_logged_not_silent
WHY      Founder 2026-09-19: V3's back half had never run in production, and
         `candidate_set_write_failed` arrived with no line saying why.
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
        "recording_id": RECORDING,
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
        self.context_calls: list[dict] = []
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

        Overridden by `_WriteReturns` below to model the answers that are
        not exceptions: no usable row, or another set's id.
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

    def prepare_feedback_v3_service_context(self, payload):
        # Retired from serving (L8, contract 66). Answered the way it would
        # be if an N1 snapshot existed, so a reintroduced call is counted AND
        # would put `mlc3_service` back on the row.
        self.context_calls.append(payload)
        return {
            "n1_candidate_set_id": "66666666-7777-4888-8999-aaaaaaaaaaaa",
            "authorization_check_id": "77777777-8888-4999-8aaa-bbbbbbbbbbbb",
            "source_acquisition_receipt_id":
                "88888888-9999-4aaa-8bbb-cccccccccccc",
        }


def run_chain(database=None, document=None):
    """Drive the live entry point once. Returns whatever it returns."""
    from services.mlc3_first_client_feedback import (
        prepare_first_client_feedback,
    )
    return prepare_first_client_feedback(
        database=database if database is not None else _Database(),
        session=_session(),
        take_document=document if document is not None else _bound_document(),
        served_text=IDEAL,
        snippets=_snippets(),
        suggestions={},
        feedback_candidates=[],
        owner_user_id=USER,
    )


class _WriteReturns(_Database):
    """The RPC runs cleanly and hands back something that is not our set."""

    def __init__(self, answer) -> None:
        super().__init__()
        self._answer = answer

    def _candidate_set_rpc_result(self, bundle):
        return self._answer


def _decision(row: dict) -> dict | None:
    from services.feedback_data_contract import canonical_feedback_decision
    return canonical_feedback_decision(
        take_id=TAKE, rater_id=USER, feedback_id=str(row["id"]),
        feedback_family="confident_voice", response="yes",
        candidate_id=row.get("candidate_id"),
        feedback_membership_id=row.get("feedback_membership_id"),
        feedback_exposure_id=row.get("feedback_exposure_id"),
    )


class TheConfidentVoiceAnswerOnProductionShape(unittest.TestCase):

    def setUp(self) -> None:
        from config import Config
        patcher = patch.object(Config, "MLC3_SERVICE_ENABLED", True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _served_row(self, database) -> dict:
        rows = run_chain(database)
        self.assertIsInstance(rows, list)
        voice = [row for row in rows
                 if row["feedback_family"] == "confident_voice"]
        self.assertEqual(len(voice), 1)
        return voice[0]

    def test_the_chain_serves_feedback_on_two_real_documents(self):
        database = _Database()
        row = self._served_row(database)
        # The row is drawn on the Ideal Text the speaker sees...
        span = row["span"]
        self.assertEqual(row["quote"], IDEAL[span["start"]:span["end"]])
        # ...and its evidence is the words they actually said.
        [candidate] = [c for c in database.bundle["candidates"]
                       if c["id"] == row["candidate_id"]]
        evidence = candidate["evidence"]
        self.assertEqual(evidence["exact_text"], SPOKEN)
        self.assertEqual(evidence["target_locator"]["exact_text"],
                         row["quote"])
        self.assertEqual(evidence["document_snapshot_id"], SNAPSHOT)
        self.assertEqual((evidence["start_ms"], evidence["end_ms"]),
                         (120, 120 + 9400))
        self.assertEqual(database.context_calls, [])

    def test_the_answer_is_a_canonical_decision_on_the_served_row(self):
        database = _Database()
        row = self._served_row(database)
        [candidate] = [c for c in database.bundle["candidates"]
                       if c["feedback_family"] == "confident_voice"]
        decision = _decision(row)
        self.assertIsNotNone(decision)
        self.assertEqual(
            {key: decision[key] for key in (
                "take_id", "rater_id", "feedback_id", "feedback_family",
                "value", "candidate_id", "feedback_membership_id",
                "feedback_exposure_id")},
            {"take_id": TAKE, "rater_id": USER, "feedback_id": row["id"],
             "feedback_family": "confident_voice", "value": "yes",
             "candidate_id": candidate["id"],
             "feedback_membership_id": MEMBERSHIP,
             "feedback_exposure_id": candidate["exposure_id"]},
        )
        self.assertTrue(
            decision["idempotency_key"].startswith("feedback-decision:"))
        # The same answer again is the same decision, not a second one.
        self.assertEqual(decision, _decision(self._served_row(_Database())))

    def test_a_write_that_returns_nothing_is_logged_not_silent(self):
        for name, answer, logged in (
            ("no row", [], "returned no usable row kind=list"),
            ("null", None, "returned no usable row kind=NoneType"),
            ("another set", {"candidate_set_id":
                             "00000000-0000-4000-8000-000000000000"},
             "id mismatch"),
        ):
            with self.subTest(name):
                with self.assertLogs("services.first_client_repository",
                                     "WARNING") as logs:
                    row = self._served_row(_WriteReturns(answer))
                self.assertIn(logged, "\n".join(logs.output))
                self.assertIn(TAKE, "\n".join(logs.output))
                # Served without lineage, so no answer can attach to it.
                self.assertIsNone(row.get("feedback_membership_id"))
                self.assertIsNone(_decision(row))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
