"""The bookmarks are computed during processing, not when the document opens.

FOUNDER, 2026-09-20: "it's unacceptable that we open the ideal text after the
processing and there are no bookmarks. There need to be bookmarks right away
the moment we see it. Otherwise, that makes no sense because people will
quit."

They were never stored. ``document_layers`` ran the whole Manager pipeline on
every GET, so the marks were COMPUTED at open time and kept missing their
budget. These tests hold the two properties that make moving that computation
safe: it happens AFTER the snapshot is published, and it can fail in every
direction without costing anyone their document.
"""
from __future__ import annotations

import pytest

from services import ideal_text_core_snapshot as core
from services import ideal_text_feedback_bake as bake


@pytest.fixture(autouse=True)
def _bake_on(monkeypatch):
    """The bake ships OFF (2026-09-20) because it delayed Take 1 document
    creation. These tests are about what it does WHEN ON, so they turn it on
    explicitly — and `test_the_flag_is_off_by_default` below holds the
    shipped default, which is the part that protects the live loop.

    Patched on the SERVICE's own predicate, not on `Config`: other modules
    reload `config`, so patching the class passes this file in isolation and
    fails it in the full suite. It did."""
    monkeypatch.setattr(bake, "_bake_enabled", lambda: True)

ARC = "arc-1"
ACTOR = "actor-1"
SNAPSHOT = "11111111-1111-4111-8111-111111111111"
TAKE = "22222222-2222-4222-8222-222222222222"

PUBLISHED = {
    "id": SNAPSHOT,
    "payload": {
        "text": "We started small. And then we shipped it fast.",
        "latest_take_session_id": TAKE,
        "version": 1,
    },
}

BLOCK = {
    "changes": [{"id": "cand-1", "source": "confident_voice"}],
    "style_changes": [],
    "key_points": [],
}


class RecordingDatabase:
    def __init__(self, stored=True):
        self.stored = stored
        self.writes: list[tuple] = []

    def write_ideal_text_feedback_bake(
        self, arc_id, actor_id, snapshot_id, payload,
    ):
        self.writes.append((arc_id, actor_id, snapshot_id, payload))
        return self.stored


def _block_returns(monkeypatch, value):
    """Patch the ONE Manager the route also calls. Not a second copy of it."""
    import routes.v2.explore_ideal_text as route
    monkeypatch.setattr(
        route, "_tracked_changes_block",
        lambda *args, **kwargs: (
            value() if callable(value) else value
        ),
    )


# ── the happy path ─────────────────────────────────────────────────────────


def test_the_block_is_stored_against_the_snapshot_it_was_computed_over(
    monkeypatch,
):
    _block_returns(monkeypatch, BLOCK)
    database = RecordingDatabase()
    assert bake.bake_for_snapshot(database, ARC, ACTOR, PUBLISHED) is True
    assert database.writes == [(ARC, ACTOR, SNAPSHOT, BLOCK)]


def test_it_calls_the_same_manager_the_read_calls(monkeypatch):
    """One arbitration, one answer.

    A parallel 'fast path' that could disagree with the real one is how a
    product ends up with two answers and no way to say which is true. The
    bake calls `_tracked_changes_block` — the function the enrichment route
    calls — with this document's own text, take and version.
    """
    seen: list[tuple] = []

    import routes.v2.explore_ideal_text as route

    def spy(arc_id, served_text, user_id, take_session_id, **kwargs):
        seen.append((arc_id, served_text, user_id, take_session_id,
                     kwargs.get("review_version")))
        return BLOCK

    monkeypatch.setattr(route, "_tracked_changes_block", spy)
    bake.bake_for_snapshot(RecordingDatabase(), ARC, ACTOR, PUBLISHED)
    assert seen == [(
        ARC, PUBLISHED["payload"]["text"], ACTOR, TAKE, 1,
    )]


# ── every way it may decline, and none of them may hurt ────────────────────


@pytest.mark.parametrize("published", [
    None,
    {},
    {"id": SNAPSHOT},                                  # no payload
    {"id": SNAPSHOT, "payload": {"text": ""}},          # no words
    {"id": SNAPSHOT, "payload": {"text": "Hi"}},        # no take
    {"payload": PUBLISHED["payload"]},                  # no snapshot id
])
def test_an_unusable_publish_result_stores_nothing(monkeypatch, published):
    _block_returns(monkeypatch, BLOCK)
    database = RecordingDatabase()
    assert bake.bake_for_snapshot(database, ARC, ACTOR, published) is False
    assert database.writes == []


def test_an_empty_block_is_not_stored(monkeypatch):
    """An empty block is a legitimate answer AND what a silent failure looks
    like. They are not worth telling apart here: storing nothing costs one
    live computation, storing a wrong nothing costs the user their marks."""
    _block_returns(monkeypatch, {})
    database = RecordingDatabase()
    assert bake.bake_for_snapshot(database, ARC, ACTOR, PUBLISHED) is False
    assert database.writes == []


def test_a_manager_that_raises_is_named_and_swallowed(monkeypatch, caplog):
    def boom(*_args, **_kwargs):
        raise RuntimeError("manager is down")

    import routes.v2.explore_ideal_text as route
    monkeypatch.setattr(route, "_tracked_changes_block", boom)
    database = RecordingDatabase()
    with caplog.at_level("WARNING"):
        assert bake.bake_for_snapshot(database, ARC, ACTOR, PUBLISHED) is False
    assert database.writes == []
    assert "bake compute failed" in caplog.text


def test_a_refused_write_is_reported_as_not_baked(monkeypatch):
    _block_returns(monkeypatch, BLOCK)
    database = RecordingDatabase(stored=False)
    assert bake.bake_for_snapshot(database, ARC, ACTOR, PUBLISHED) is False
    assert len(database.writes) == 1


@pytest.mark.parametrize(("arc_id", "actor_id"), [
    ("", ACTOR), (ARC, ""), ("", ""),
])
def test_incomplete_identity_stores_nothing(monkeypatch, arc_id, actor_id):
    _block_returns(monkeypatch, BLOCK)
    database = RecordingDatabase()
    assert bake.bake_for_snapshot(
        database, arc_id, actor_id, PUBLISHED) is False
    assert database.writes == []


# ── the ordering, which is the whole correctness of it ─────────────────────


def _publish_fake(monkeypatch, order):
    class FakeDatabase:
        def get_arc_sessions(self, _arc_id):
            return [{
                "id": TAKE, "take_index": 1, "analysis_state": "ready",
                "recording_kind": "spoken", "user_id": ACTOR,
            }]

        @property
        def takes(self):
            return self

        def get_ideal_text_document_generation(self, _arc_id):
            return 7

        def get_ideal_text_document_snapshot(self, *_args):
            return None

        def publish_ideal_text_document_snapshot(self, **_kwargs):
            order.append("publish")
            return PUBLISHED

        def write_ideal_text_feedback_bake(self, *_args, **_kwargs):
            order.append("bake")
            return True

    monkeypatch.setattr(core, "build_snapshot", lambda *_a, **_k: (
        dict(PUBLISHED["payload"]), {}, {
            "acquisition_principal_id": "owner-1",
            "project_id": "project-1",
            "source_take_session_id": TAKE,
            "version": 1,
            "source_fingerprint_sha256": "a" * 64,
        },
    ))
    return FakeDatabase()


def test_the_bake_runs_AFTER_the_publish(monkeypatch):
    """Not a style preference — V3 declines outright if this is reversed.

    `read_feedback_v3_candidate_source_snapshot_v1` binds on
    `surface = served_text` against the CURRENT published snapshot. A block
    computed a moment before publication is one V3 refuses with
    `source_snapshot_does_not_match_served_text`, so the bake would store an
    empty answer and the user would see no bookmarks at all — the exact
    defect this feature exists to end.
    """
    order: list[str] = []
    _block_returns(monkeypatch, BLOCK)
    database = _publish_fake(monkeypatch, order)
    assert core.publish_for_arc(database, ARC, ACTOR) == PUBLISHED
    assert order == ["publish", "bake"]


def test_a_bake_that_explodes_does_not_cost_the_publish(monkeypatch):
    """The document is F1 and the bake is an optimisation over it. A failure
    to make one must never be able to fail the thing it optimises."""
    order: list[str] = []
    database = _publish_fake(monkeypatch, order)

    def boom(*_args, **_kwargs):
        raise RuntimeError("bake is down")

    monkeypatch.setattr(bake, "bake_for_snapshot", boom)
    assert core.publish_for_arc(database, ARC, ACTOR) == PUBLISHED
    assert order == ["publish"]


# ── serving it: the fast path may only be taken when it is safe ────────────


CORE = {
    "text": PUBLISHED["payload"]["text"],
    "latest_take_session_id": TAKE,
    "version": 1,
}


class ServingDatabase:
    def __init__(self, baked):
        self.baked = baked
        self.reads: list[tuple] = []

    def read_ideal_text_feedback_bake(self, arc_id, actor_id, snapshot_id):
        self.reads.append((arc_id, actor_id, snapshot_id))
        return self.baked


def test_a_fresh_bake_is_served_without_running_the_manager(monkeypatch):
    def never(*_args, **_kwargs):
        raise AssertionError("the Manager must not run on a bake hit")

    import routes.v2.explore_ideal_text as route
    monkeypatch.setattr(route, "_tracked_changes_block", never)
    database = ServingDatabase(BLOCK)
    assert bake.changes_block_for(
        database, ARC, ACTOR, SNAPSHOT, CORE) == BLOCK
    assert database.reads == [(ARC, ACTOR, SNAPSHOT)]


@pytest.mark.parametrize("baked", [None, {}, [], "nope", 0])
def test_every_kind_of_miss_falls_through_to_the_live_computation(
    monkeypatch, baked,
):
    """A miss is not a failure.

    Absent function, absent row, wrong snapshot, or any write to the mutable
    feedback surface since the bake — the SQL returns nothing for all of
    them, and this must then do exactly what every reader did before the
    bake existed. That is what makes the fast path unable to regress
    anything.
    """
    _block_returns(monkeypatch, BLOCK)
    database = ServingDatabase(baked)
    assert bake.changes_block_for(
        database, ARC, ACTOR, SNAPSHOT, CORE) == BLOCK


def test_the_live_path_is_given_this_document_and_not_another(monkeypatch):
    seen: list[tuple] = []

    import routes.v2.explore_ideal_text as route

    def spy(arc_id, served_text, user_id, take_session_id, **kwargs):
        seen.append((arc_id, served_text, user_id, take_session_id,
                     kwargs.get("review_version")))
        return BLOCK

    monkeypatch.setattr(route, "_tracked_changes_block", spy)
    bake.changes_block_for(ServingDatabase(None), ARC, ACTOR, SNAPSHOT, CORE)
    assert seen == [(ARC, CORE["text"], ACTOR, TAKE, 1)]


def test_a_missing_snapshot_id_still_answers_rather_than_raising(monkeypatch):
    # The route only reaches here with a validated snapshot, but an empty
    # string must degrade to the live read rather than take down the section.
    _block_returns(monkeypatch, BLOCK)
    assert bake.changes_block_for(
        ServingDatabase(None), ARC, ACTOR, "", CORE) == BLOCK


# ── the regression this feature caused on its first real take ──────────────
#
# FOUNDER, 2026-09-20, minutes after #580 shipped: "I just recorded and none
# of the bookmarks appeared."
#
# `build_changes_block` returns `{"changes": [], ...}` when the Manager has
# nothing to say at that moment — a TRUTHY dict with nothing in it. The guard
# was `not block`, which does not catch it. And the moment the bake runs is
# during assembly: `ideal_text_confirmation` is called at
# analysis_worker.py:282, BEFORE the pipeline's feedback stages at 288 and
# 299. So a fresh take routinely baked an empty block, stored it, and every
# read afterwards served "no bookmarks" for the life of that snapshot.


@pytest.mark.parametrize("block", [
    {"changes": []},
    {"changes": [], "style_changes": [], "key_points": []},
    {"changes": [], "is_saved": False, "additions": []},
    {"style_changes": [{"id": "s1"}]},   # lanes, but no marks
    {"is_saved": True},
])
def test_a_block_with_no_marks_is_never_stored(monkeypatch, block):
    """Each of these is truthy. Not one of them is a bake.

    Storing any of them serves "no bookmarks" until the next snapshot, which
    is the exact defect this whole feature exists to end.
    """
    _block_returns(monkeypatch, block)
    database = RecordingDatabase()
    assert bake.bake_for_snapshot(database, ARC, ACTOR, PUBLISHED) is False
    assert database.writes == []


def test_a_block_with_marks_is_still_stored(monkeypatch):
    """The guard tightened; it did not turn the feature off. A publish that
    happens at the END of a run — where the Manager has really finished — bakes
    exactly as before."""
    _block_returns(monkeypatch, BLOCK)
    database = RecordingDatabase()
    assert bake.bake_for_snapshot(database, ARC, ACTOR, PUBLISHED) is True
    assert database.writes == [(ARC, ACTOR, SNAPSHOT, BLOCK)]


def test_no_bake_means_the_read_computes_live(monkeypatch):
    """The whole safety argument in one line: when nothing was stored, the
    read does what every read did before any of this existed."""
    _block_returns(monkeypatch, BLOCK)
    assert bake.changes_block_for(
        ServingDatabase(None), ARC, ACTOR, SNAPSHOT, CORE) == BLOCK


# ── the flag, and why its default is the point ─────────────────────────────


def test_the_flag_is_off_by_default():
    """FOUNDER, 2026-09-20: "We processed your take, but couldn't create your
    Ideal Text."

    #580 put the whole Manager pipeline inside `publish_for_arc`, which
    `maybe_assemble_ideal_text` calls WHILE A TAKE 1 DOCUMENT IS BEING MADE.
    In production, publication went from about a second to tens of seconds —
    two takes landed their snapshot 22s and 42s after their job had already
    finished, and one never landed at all.

    An optimisation for the marks that hang off the document is not allowed
    to cost the document. This default is that ruling, and it is the assertion
    that keeps it: the speed-up returns only when the bake runs where it
    cannot delay creation (task #43).
    """
    # Read the SHIPPED declaration, not the live attribute: the autouse
    # fixture above turns the flag on for every other test in this file, and
    # a default test that the fixture can satisfy is a default test that
    # proves nothing.
    import inspect

    import config

    source = inspect.getsource(config)
    assert 'IDEAL_TEXT_FEEDBACK_BAKE_ENABLED", "0"' in source, (
        "the shipped default must be off")
    assert config._env_flag("IDEAL_TEXT_FEEDBACK_BAKE_ENABLED", "0") is False


def test_switched_off_it_computes_nothing_and_stores_nothing(monkeypatch):
    """Not merely "stores nothing" — it must not RUN. The cost being removed
    is the Manager pipeline itself, so a version that computed and then
    discarded would fix nothing."""
    monkeypatch.setattr(bake, "_bake_enabled", lambda: False)

    def never(*_args, **_kwargs):
        raise AssertionError("the Manager must not run with the bake off")

    import routes.v2.explore_ideal_text as route
    monkeypatch.setattr(route, "_tracked_changes_block", never)
    database = RecordingDatabase()
    assert bake.bake_for_snapshot(database, ARC, ACTOR, PUBLISHED) is False
    assert database.writes == []


def test_the_read_still_answers_with_the_bake_off(monkeypatch):
    """Turning it off costs the speed-up and nothing else: with no stored
    row the read computes live, which is what every reader did before any of
    this existed."""
    monkeypatch.setattr(bake, "_bake_enabled", lambda: False)
    _block_returns(monkeypatch, BLOCK)
    assert bake.changes_block_for(
        ServingDatabase(None), ARC, ACTOR, SNAPSHOT, CORE) == BLOCK


def test_publishing_is_untouched_with_the_bake_off(monkeypatch):
    """The publish must still publish. That is the whole point of the
    default."""
    monkeypatch.setattr(bake, "_bake_enabled", lambda: False)
    order: list[str] = []
    database = _publish_fake(monkeypatch, order)
    assert core.publish_for_arc(database, ARC, ACTOR) == PUBLISHED
    assert order == ["publish"]


def test_with_the_bake_off_a_stored_row_is_not_even_read(monkeypatch):
    """FOUNDER, after #584 had already switched the bake off: "No bookmarks."

    #584 gated the WRITER and left the READER open, so a row stored during
    the window when #580 was live kept being served. Turning a writer off
    does nothing about what it already wrote; a switch that silences the
    cause and keeps serving its damage is not a switch.

    With the flag off the stored answer does not exist as far as the read is
    concerned — not "is read and ignored", not read at all.
    """
    monkeypatch.setattr(bake, "_bake_enabled", lambda: False)
    _block_returns(monkeypatch, BLOCK)
    poisoned = ServingDatabase({"changes": [], "style_changes": []})
    assert bake.changes_block_for(
        poisoned, ARC, ACTOR, SNAPSHOT, CORE) == BLOCK
    assert poisoned.reads == [], "the bake table must not be touched"


def test_with_the_bake_on_a_stored_row_is_still_served(monkeypatch):
    """The gate is a rollback, not a removal. With the flag on, the stored
    block is served exactly as designed."""
    monkeypatch.setattr(bake, "_bake_enabled", lambda: True)
    database = ServingDatabase(BLOCK)
    assert bake.changes_block_for(
        database, ARC, ACTOR, SNAPSHOT, CORE) == BLOCK
    assert database.reads == [(ARC, ACTOR, SNAPSHOT)]
