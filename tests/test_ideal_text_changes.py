"""The `changes` block, stage by stage (audit Q-C1, Phase 5).

``services.ideal_text_changes`` is the former 900-line route helper, split
into stages that run through one ``DegradationLog``. These tests drive the
stages with a small fake database and a fake ``ChangesDeps``: each stage
that used to be a swallow-all still serves its fallback, and now names
itself in `degraded`. The Manager gate (L2) is exercised through the real
``intervention_candidates.select``.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from config import Config
from services.degradation import DegradationLog
from services.ideal_text_changes import (
    ChangesDeps, _ChangesRun, build_changes_block,
)

ARC = "11111111-1111-4111-8111-111111111111"
T1 = "22222222-2222-4222-8222-222222222222"
S1 = "33333333-3333-4333-8333-333333333333"
S2 = "44444444-4444-4444-8444-444444444444"
DOC = "We started small. And then we shipped it fast."


class FakeDB:
    """Only the reads the block makes on the legacy (no-contract) lane."""

    def __init__(self, *, sugs=None, snippets=None, boom=()):
        self.sugs = sugs or {}
        self.snippets = snippets if snippets is not None else [
            {"id": S1, "start_offset_ms": 0,
             "transcript": "We started small.",
             "metrics": {"piece": {"slide_index": 0}}},
            {"id": S2, "start_offset_ms": 10,
             "transcript": "And then we shipped it fast.",
             "metrics": {"piece": {"slide_index": 0}}},
        ]
        self.boom = set(boom)
        self.calls: list[str] = []

    def _maybe_boom(self, name):
        self.calls.append(name)
        if name in self.boom:
            raise RuntimeError(f"{name} is down")

    def get_arc_sessions(self, arc_id):
        self._maybe_boom("get_arc_sessions")
        return [{"id": T1, "take_index": 1, "recording_kind": "spoken"}]

    @property
    def takes(self):
        # audit Q-A2: production now calls db.takes.<method>();
        # this fake implements those methods directly on itself.
        return self

    def get_snippets_by_session(self, session_id):
        self._maybe_boom("get_snippets_by_session")
        return self.snippets

    def get_coach_snippet_drafts(self, *a, **k):
        return []

    def get_user_transcript_edits(self, *a, **k):
        return []

    def get_moment_suggestions_by_arc(self, arc_id):
        self._maybe_boom("get_moment_suggestions_by_arc")
        return dict(self.sugs)

    def get_suggestion_feedback_by_session(self, *a, **k):
        return []

    def get_coach_arc_ideal_text(self, arc_id):
        self._maybe_boom("get_coach_arc_ideal_text")
        return {}

    @property
    def ideal_text(self):
        # audit Q-A2: production now calls db.ideal_text.<method>(); this
        # fake implements those methods (and the boom/call tracking) on
        # itself, so the same instance serves both call shapes.
        return self

    def get_star_verdicts_by_snippet_ids(self, ids):
        return {}

    def get_snippets_by_ids(self, ids):
        self._maybe_boom("get_snippets_by_ids")
        return []

    def list_owner_voice_album_routes(self, arc_id):
        return []

    def v2_get_session_by_id(self, sid):
        self._maybe_boom("v2_get_session_by_id")
        return {}

    def get_ideal_text_parts(self, *a, **k):
        return []

    def list_ideal_decisions(self, *a, **k):
        return []

    def __getattr__(self, name):
        # Any read this fake does not model is a fault the stage must name.
        def _missing(*a, **k):
            raise AttributeError(f"FakeDB has no {name}")
        return _missing


def _deps(db, **overrides):
    base = dict(
        database=db,
        first_client_repository=None,
        applied_map=lambda ids: {},
        playback_map=lambda ids: {},
        previous_spoken_session=lambda arc_id, sid: None,
        locked_parts=lambda arc_id, user_id, text: [],
        with_evidence_coordinates=lambda rows, **k: rows,
        record_arms=lambda result, sid, uid: None,
    )
    base.update(overrides)
    return ChangesDeps(**base)


def _block(db, *, deps=None, degradation=None, **kw):
    with patch.object(Config, "LIVING_TRANSCRIPT_ENABLED", True):
        return build_changes_block(
            ARC, DOC, deps=deps or _deps(db), degradation=degradation, **kw)


def test_flag_off_means_no_block_and_no_marker():
    with patch.object(Config, "LIVING_TRANSCRIPT_ENABLED", False):
        assert build_changes_block(ARC, DOC, deps=_deps(FakeDB())) == {}


def test_a_healthy_read_has_no_degraded_key():
    out = _block(FakeDB())
    assert out["changes"] == []
    assert "degraded" not in out


def test_a_suggestion_becomes_an_anchored_change_through_the_gate():
    db = FakeDB(sugs={S2: {"kind": "replace", "trigger": "polish",
                           "replacement_text": "And then we launched it fast.",
                           "why": "Tighter."}})
    out = _block(db)
    assert [c["kind"] for c in out["changes"]] == ["replace"]
    c = out["changes"][0]
    assert DOC[c["span"]["start"]:c["span"]["end"]] == c["quote"]
    assert "degraded" not in out


def test_the_whole_block_failing_is_named_not_vanished():
    # The suggestions read is not optional in the old code either: it took
    # the whole block down, which used to mean the key silently vanished.
    out = _block(FakeDB(boom={"get_moment_suggestions_by_arc"}))
    assert "changes" not in out
    assert out["degraded"] == [
        {"stage": "ideal_text.changes", "kind": "RuntimeError"}]


def test_an_optional_stage_failing_keeps_the_changes_and_names_itself():
    db = FakeDB(sugs={S2: {"kind": "emphasize", "trigger": "acoustic",
                           "why": "Land it."}},
                boom={"get_snippets_by_ids"})
    out = _block(db)
    # The emphasis key phrases could not be read: the fallback is the whole
    # fragment (served as a `bold`), as before — and the payload says so.
    assert [c["kind"] for c in out["changes"]] == ["bold"]
    assert {"stage": "ideal_text.changes.emphasis_key_phrases",
            "kind": "RuntimeError"} in out["degraded"]


def test_a_failing_helper_is_named_by_its_stage():
    def broken_playback(ids):
        raise KeyError("audio")

    def broken_applied(ids):
        raise ValueError("applied")

    db = FakeDB(sugs={S2: {"kind": "replace", "trigger": "polish",
                           "replacement_text": "And then we launched it fast.",
                           "why": "Tighter."}})
    out = _block(db, deps=_deps(db, playback_map=broken_playback,
                                applied_map=broken_applied))
    assert len(out["changes"]) == 1
    stages = {d["stage"]: d["kind"] for d in out["degraded"]}
    assert stages["ideal_text.changes.applied_map"] == "ValueError"
    # No praise row was selected, so the playback map was never asked.
    assert "ideal_text.changes.praise_playback" not in stages


def test_a_shared_log_carries_the_markers_and_the_block_stays_clean():
    log = DegradationLog("ideal_text")
    db = FakeDB(boom={"get_snippets_by_ids"},
                sugs={S1: {"kind": "emphasize", "trigger": "acoustic",
                           "why": "Land it."}})
    out = _block(db, degradation=log)
    assert "degraded" not in out
    assert [d.stage for d in log.items] == [
        "ideal_text.changes.emphasis_key_phrases"]


def test_the_canonical_provenance_read_is_optional():
    out = _block(FakeDB(boom={"get_coach_arc_ideal_text"}))
    assert out["changes"] == []
    assert out["degraded"] == [{
        "stage": "ideal_text.changes.canonical_provenance",
        "kind": "RuntimeError"}]


def test_the_span_check_serving_none_is_a_named_fallback():
    db = FakeDB(sugs={S2: {"kind": "replace", "trigger": "polish",
                           "replacement_text": "And then we launched it fast.",
                           "why": "Tighter."}})

    def corrupt_spans(rows, **k):
        for row in rows:
            row["span"] = {"start": 0, "end": 1}
            row["quote"] = "ZZZ"
        return rows

    out = _block(db, deps=_deps(db, with_evidence_coordinates=corrupt_spans))
    assert out["changes"] == []
    assert {"stage": "ideal_text.changes.span_check",
            "kind": "span_check_failed"} in out["degraded"]


def test_the_stage_order_is_the_documented_one():
    """The orchestrator runs the stages in the order the one-function
    version did; the gate comes after every lane has proposed."""
    import ast
    import inspect
    import textwrap
    tree = ast.parse(textwrap.dedent(inspect.getsource(_ChangesRun.execute)))
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Attribute) and fn.attr == "run":
                found.append((node.lineno, node.args[1].attr))
            elif (isinstance(fn, ast.Attribute)
                  and isinstance(fn.value, ast.Name) and fn.value.id == "self"):
                found.append((node.lineno, fn.attr))
    calls = [name for _, name in sorted(found)]
    lanes = calls.index("_prior_take")
    gate = calls.index("_select")
    assert lanes < gate
    assert calls.index("_build_candidates") < calls.index("_select")
    assert calls[-1] == "_finish"


@pytest.mark.parametrize("stage", [
    "_canonical_provenance", "_applied_map", "_emphasis_key_phrases",
    "_current_take_confident_voice", "_praise_playback", "_upgrade_changes",
    "_block_additions", "_prior_take", "_v3_shadow", "_decision_backfill",
    "_practice_offer", "_canonical_dual_write", "_first_client_feedback",
])
def test_every_former_swallow_all_runs_through_the_log(stage):
    import inspect
    src = inspect.getsource(_ChangesRun)
    assert f"self.{stage})" in src or f"self.{stage}\n" in src, stage
    # Named in a `log.run(...)` call, never called bare.
    bare = f"self.{stage}()"
    assert bare not in src, f"{stage} is called outside the log"


# ── THE CLIP UNDER A V3 ROW (founder 2026-09-20) ──────────────────────────
#
# "there is no playback on the overlay so you cannot play the confident
#  moment and actually see whether it sounded confident or not. there is
#  nothing at the bottom."
#
# `_praise_playback` attaches the recording. It runs early, because
# `_feedback_set_and_fallbacks` classifies through `feedback_family_of`,
# which will only call a row Confident Voice once it has a playable excerpt.
# Then `_first_client_feedback` REPLACES `self.changes` wholesale with V3's
# rows — and every clip attached upstream went out with the list it was
# attached to. Since the V3 cutover, not one served Confident Voice item had
# a recording under it.
#
# The product's own rule, stated twice in the source: the claim is about how
# it SOUNDED, and it is the only claim this product makes that the student
# cannot check by reading.


def _run_for_playback(deps):
    from services.ideal_text_changes import _ChangesRun
    return _ChangesRun(ARC, DOC, "user-1", T1, 1, deps,
                       DegradationLog("ideal_text"))


def _v3_row(snippet_id):
    """The shape `take_feedback_policy_v3_service` actually emits."""
    return {
        "id": f"cand:{snippet_id}",
        "kind": "bold",
        "source": "confident_voice",
        "feedback_family": "confident_voice",
        "snippet_id": snippet_id,
        "take_session_id": T1,
        "span": {"start": 0, "end": 17},
        "quote": "We started small.",
    }


def test_a_v3_confident_voice_row_gets_its_recording():
    clip = {"snippet_audio_ref": "https://audio/take-1.m4a",
            "start_offset_ms": 0, "duration_ms": 1700}
    db = FakeDB()
    run = _run_for_playback(_deps(db, playback_map=lambda ids: {S1: clip}))
    run.changes = [_v3_row(S1)]
    run._praise_playback()
    assert run.changes[0]["snippet_audio_ref"] == "https://audio/take-1.m4a"
    assert run.changes[0]["start_offset_ms"] == 0
    assert run.changes[0]["duration_ms"] == 1700


def test_a_v3_row_with_no_clip_still_surfaces_rather_than_vanishing():
    # 24b puts one relative-best item on every valid block of every Take.
    # A missing recording is a missing player, never a missing bookmark —
    # the FE renders the card without the audio block.
    db = FakeDB()
    run = _run_for_playback(_deps(db, playback_map=lambda ids: {}))
    run.changes = [_v3_row(S1)]
    run._praise_playback()
    assert len(run.changes) == 1
    assert "snippet_audio_ref" not in run.changes[0]


def test_the_replacement_flag_is_what_re_arms_the_attach():
    db = FakeDB()
    run = _run_for_playback(_deps(db))
    # Nothing has replaced the rows yet, so the second attach must not run:
    # a Take V3 does not own pays nothing for this fix.
    assert run.v3_replaced_changes is False


def test_playback_is_attached_on_BOTH_sides_of_the_v3_replacement():
    """The ordering contract, stated so it cannot silently regress.

    Both readers are right and they disagree about when: V2 needs the clip
    BEFORE `_feedback_set_and_fallbacks` classifies, V3 needs it AFTER
    `_first_client_feedback` replaces. Moving the stage fixes one and breaks
    the other, which is why it runs twice.
    """
    import ast
    import inspect
    import textwrap
    from services.ideal_text_changes import _ChangesRun
    tree = ast.parse(textwrap.dedent(inspect.getsource(_ChangesRun.execute)))
    calls = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            if isinstance(fn, ast.Attribute) and fn.attr == "run":
                calls.append((node.lineno, node.args[1].attr))
            elif (isinstance(fn, ast.Attribute)
                  and isinstance(fn.value, ast.Name)
                  and fn.value.id == "self"):
                calls.append((node.lineno, fn.attr))
    order = [name for _, name in sorted(calls)]
    playbacks = [i for i, name in enumerate(order)
                 if name == "_praise_playback"]
    assert len(playbacks) == 2, "the attach must run on both sides"
    assert playbacks[0] < order.index("_feedback_set_and_fallbacks"), \
        "V2 classifies on the clip; the first attach must precede it"
    assert playbacks[1] > order.index("_first_client_feedback"), \
        "V3 replaces the rows; the second attach must follow it"


# ── #592: a superseded set must not filter the rows that superseded it ─────


def _v2_frozen_set():
    """V2's three, as every Take frozen before #591 still holds them."""
    return {
        "arc_id": ARC,
        "take_session_id": T1,
        "selected_keys": [
            {"id": "v2-cv", "kind": "bold", "source": "confident_voice",
             "feedback_family": "confident_voice"},
            {"id": "v2-rw", "kind": "replace", "source": "wording",
             "feedback_family": "rewrite_clarity"},
            {"id": "v2-gf", "kind": "advice", "source": "structural",
             "feedback_family": "great_formulation"},
        ],
    }


def test_a_v2_freeze_does_not_blank_the_v3_rows_it_predates():
    """THE REGRESSION #591 SHIPPED, caught the same afternoon.

    `load_feedback_set` runs at `_feedback_set_and_fallbacks`, long before
    V3 selects. #591 moved the claim BELOW `_first_client_feedback`, so on
    every Take frozen earlier the served rows are V3's while the frozen keys
    are V2's three. They share no identity, `filter_to_selected` returns [],
    and the entire bookmark surface goes blank — the founder's original
    complaint, reintroduced by the fix for the one after it.

    Those Takes keep V2's set forever (the claim is insert-once) and their
    answers stay unvalidatable. That is where they already were. Serving
    them no marks at all would be strictly worse.
    """
    db = FakeDB()
    run = _run_for_playback(_deps(db))
    run.feedback_set = _v2_frozen_set()
    run.changes = [_v3_row(S1)]
    run.v3_replaced_changes = True
    run._claim_or_filter()
    assert [row["id"] for row in run.changes] == [f"cand:{S1}"]


def test_a_v2_take_is_still_filtered_to_its_frozen_set():
    """The guard this branch exists for, unchanged where it still applies.

    When V3 did not replace the rows, the served payload is V2's and the
    frozen set describes it exactly — so accepting item one must still never
    reveal item four.
    """
    db = FakeDB()
    run = _run_for_playback(_deps(db))
    run.feedback_set = _v2_frozen_set()
    run.changes = [
        {"id": "v2-cv", "kind": "bold", "source": "confident_voice",
         "feedback_family": "confident_voice"},
        {"id": "v2-unfrozen", "kind": "replace", "source": "wording",
         "feedback_family": "rewrite_clarity"},
    ]
    run.v3_replaced_changes = False
    run._claim_or_filter()
    assert [row["id"] for row in run.changes] == ["v2-cv"]
