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
