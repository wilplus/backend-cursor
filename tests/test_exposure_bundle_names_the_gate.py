"""Seven conditions had one name, and six of them were not a count mismatch.

PRODUCTION, 2026-09-19, minutes after #568. The founder's take got past
``service_inventory_unavailable`` for the first time since the V3 cutover --
the binder logged ``placed=4/4 parts=3``, so every spoken piece finally knew
its Paragraph -- and stood down one gate later:

    first_client: v3 stood down reason=exposure_bundle_membership_c…

That reason covered SEVEN separate conditions: the six ``return None`` exits
inside ``build_feedback_exposure_bundle`` and the caller's own membership-count
check. Six of them have nothing to do with a count, so the one name the log
offered was not merely vague, it pointed the reader at the wrong question.

This is the fourth time in one day that a typed reason named a STEP instead of
a CONDITION (``_row_rejection``'s ten, ``prepare_v3_service_inventory``'s six,
``_decline``'s clipped ordering, and now this). The fix is the same one that
worked three times: pass a ``detail`` list, append the gate that closed, and
split the caller's single reason into the two things it actually meant.

WHAT THIS IS NOT. It does not weaken the complete-inventory invariant. #567
excluded rows that could not be PROVEN, at the policy layer, before anything
was written; this is the write itself, and a bundle that quietly omits a row
it was handed is an audit record that lies about what the service considered.
The invariant stays -- it just says the counts out loud now.

AC-9 is untouched: none of this reaches a user. Identifiers, families and
counts only -- never a candidate's words, never a score.
"""
from __future__ import annotations

import unittest

from services.feedback_data_contract import (
    _valid_feedback_bundle_selection, build_feedback_exposure_bundle,
)

TAKE = {
    "id": "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
    "project_id": "11111111-2222-4333-8444-555555555555",
    "owner_principal_id": "99999999-8888-4777-8666-555555555555",
    "take_index": 1,
}

# V3 requires a non-empty key list containing `confident_voice`, so the
# default fixture has to carry one to reach any gate past `selected_keys`.
KEYS = [{"id": "k1", "feedback_family": "confident_voice"}]

# A document whose transcript snapshot BUILDS, so the candidate loop below is
# actually reached. The default fixture's empty `paragraphs` stops one gate
# earlier, which is its own test above.
WORDS = "Some words."
DOC = {
    "text": WORDS,
    "paragraphs": [{"start": 0, "end": len(WORDS), "slide_index": 0}],
}


def _gates(**overrides) -> list[str]:
    """The gates that closed for one call, in the order they closed."""
    detail: list[str] = []
    kwargs = {
        "session": TAKE,
        "transcript_document": {"text": "Some words.", "paragraphs": []},
        "served_text": "Some words.",
        "candidates": [],
        "selected_keys": KEYS,
        "manager_rules_version": "take-feedback-policy-v3-serving-v1",
        "detail": detail,
    }
    kwargs.update(overrides)
    build_feedback_exposure_bundle(**kwargs)
    return detail


class EachExitSaysWhichOneItWas(unittest.TestCase):
    def test_a_session_that_is_not_a_dict(self):
        self.assertIn("session_or_document_not_a_dict",
                      _gates(session="not a dict"))

    def test_a_document_that_is_not_a_dict(self):
        self.assertIn("session_or_document_not_a_dict",
                      _gates(transcript_document=None))

    def test_a_take_with_no_usable_identity(self):
        self.assertIn("take_identity_invalid", _gates(session={}))

    def test_an_empty_served_text(self):
        self.assertIn("served_text_empty", _gates(served_text=""))

    def test_selected_keys_of_the_wrong_shape(self):
        self.assertIn("selected_keys_invalid",
                      _gates(selected_keys="not a list"))

    def test_a_transcript_snapshot_that_cannot_be_built(self):
        # No paragraph rows -> no transcript -> no bundle. Previously
        # indistinguishable from a count mismatch.
        self.assertIn("transcript_snapshot_unbuildable", _gates())

    def test_the_first_gate_wins_and_the_rest_are_not_reported(self):
        # Fail-closed at the FIRST bad thing, so the detail names the gate
        # that actually stopped this take rather than every downstream
        # consequence of it.
        self.assertEqual(_gates(session={}), ["take_identity_invalid"])


class ADroppedCandidateNamesItself(unittest.TestCase):
    def test_the_family_and_key_of_a_row_that_did_not_canonicalise(self):
        detail = _gates(transcript_document=DOC, candidates=[
            {"id": "cand-7", "feedback_family": "not_a_family"}])
        self.assertIn("candidate_not_canonical:not_a_family/cand-7", detail)

    def test_a_row_with_neither_family_nor_key_still_names_its_slot(self):
        self.assertIn("candidate_not_canonical:∅/∅",
                      _gates(transcript_document=DOC, candidates=[{}]))

    def test_no_candidate_content_reaches_the_detail(self):
        # THE LINE THAT MUST SURVIVE EVERY FUTURE EDIT. The candidate carries
        # the speaker's words; the diagnostic carries its family and its id.
        spoken = "the exact words the speaker said out loud"
        detail = _gates(transcript_document=DOC, candidates=[{
            "id": "cand-7", "feedback_family": "not_a_family",
            "quote": spoken, "proposed_text": spoken,
        }])
        self.assertNotIn(spoken, "; ".join(detail))


class TheSelectionValidatorSaysWhichWay(unittest.TestCase):
    def test_a_selected_key_with_no_canonical_candidate_is_named(self):
        detail: list[str] = []
        self.assertFalse(_valid_feedback_bundle_selection(
            [], [{"id": "k1", "feedback_family": "confident_voice"}],
            service_v3=True, candidate_inputs=[], detail=detail,
        ))
        self.assertEqual(detail,
                         ["selected_key_not_canonical:confident_voice/k1"])

    def test_an_incomplete_inventory_carries_both_counts(self):
        # THE ONE THAT SAYS HOW MANY WERE LOST. "canonical=2,input=3" is the
        # whole diagnosis: one row of three failed to canonicalise, and the
        # `candidate_not_canonical:` line above says which.
        detail: list[str] = []
        canonical = [{"candidate_key": f"k{i}",
                      "feedback_family": "confident_voice"} for i in range(2)]
        self.assertFalse(_valid_feedback_bundle_selection(
            canonical, [], service_v3=True,
            candidate_inputs=[{}, {}, {}], detail=detail,
        ))
        self.assertEqual(detail, ["incomplete_inventory:canonical=2,input=3"])

    def test_the_invariant_itself_is_unchanged(self):
        # #567 excluded unprovable rows at the POLICY layer. This is the
        # write, and it still refuses an incomplete audit record. Naming it
        # is the change; permitting it is not.
        self.assertFalse(_valid_feedback_bundle_selection(
            [{"candidate_key": "k", "feedback_family": "confident_voice"}],
            [], service_v3=True, candidate_inputs=[{}, {}],
        ))

    def test_a_complete_v3_inventory_still_passes(self):
        detail: list[str] = []
        canonical = [{"candidate_key": "k1",
                      "feedback_family": "confident_voice"}]
        self.assertTrue(_valid_feedback_bundle_selection(
            canonical, [{"id": "k1", "feedback_family": "confident_voice"}],
            service_v3=True, candidate_inputs=[{}], detail=detail,
        ))
        self.assertEqual(detail, [])

    def test_detail_stays_optional_for_every_existing_caller(self):
        # The out-param is additive: omitting it must behave exactly as before.
        self.assertTrue(_valid_feedback_bundle_selection(
            [], [], service_v3=False, candidate_inputs=[]))


class TheDeclineSplitsIntoTwoReasons(unittest.TestCase):
    """`bundle is None` and a real count mismatch are different problems.

    Asserted on BEHAVIOUR, not on the caller's source text. The first draft
    of this class read `inspect.getsource(prepare_first_client_feedback)` and
    looked for the reason strings in it -- which broke the moment the decision
    was lifted into its own function for the complexity ratchet, while the
    behaviour it was meant to protect had not changed at all. A test that
    fails on a move it should not care about is a test that gets deleted.
    """

    def _call(self, *, inventory, document=None):
        from services.mlc3_first_client_feedback import (
            _exposure_bundle_or_reason,
        )
        return _exposure_bundle_or_reason(
            take=TAKE,
            take_document=document if document is not None else DOC,
            served_text=WORDS,
            inventory=inventory,
            source_snapshot={
                "document_snapshot_id": "33333333-4444-4555-8666-777777777777",
                "surface_sha256": "deadbeef",
            },
        )

    def test_an_unbuildable_bundle_carries_the_builders_own_gate(self):
        bundle, reason, detail = self._call(
            inventory={"candidates": [], "selected_keys": KEYS,
                       "membership_items": []},
            document={"text": WORDS, "paragraphs": []},
        )
        self.assertIsNone(bundle)
        self.assertEqual(reason, "exposure_bundle_unbuildable")
        self.assertIn("transcript_snapshot_unbuildable", detail)

    def test_an_invalid_key_list_reaches_the_same_reason_with_its_own_gate(self):
        # The point of the split: two very different causes, one reason
        # before, and now each names itself in `detail`.
        _bundle, reason, detail = self._call(
            inventory={"candidates": [], "selected_keys": "not a list",
                       "membership_items": []},
        )
        self.assertEqual(reason, "exposure_bundle_unbuildable")
        self.assertIn("selected_keys_invalid", detail)

    def test_the_count_mismatch_reason_now_means_what_it_says(self):
        # It is only reached with a bundle IN HAND, so the name is no longer
        # applied to six conditions that never counted anything.
        from unittest.mock import patch
        from services import mlc3_first_client_feedback as mod
        with patch.object(mod, "build_feedback_exposure_bundle",
                          return_value={"candidates": [{}, {}]}):
            bundle, reason, detail = self._call(
                inventory={"candidates": [], "selected_keys": KEYS,
                           "membership_items": [{}, {}, {}]},
            )
        self.assertIsNone(bundle)
        self.assertEqual(reason, "exposure_bundle_membership_count_mismatch")
        self.assertEqual(detail, "bundle=2,membership=3")

    def test_a_matching_bundle_passes_through_with_no_reason(self):
        from unittest.mock import patch
        from services import mlc3_first_client_feedback as mod
        built = {"candidates": [{}]}
        with patch.object(mod, "build_feedback_exposure_bundle",
                          return_value=built):
            bundle, reason, detail = self._call(
                inventory={"candidates": [], "selected_keys": KEYS,
                           "membership_items": [{}]},
            )
        self.assertIs(bundle, built)
        self.assertEqual((reason, detail), ("", ""))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
