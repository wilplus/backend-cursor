"""The bookmarks are computed during processing, not when the document opens.

FOUNDER, 2026-09-20: "it's unacceptable that we open the ideal text after the
processing and there are no bookmarks. There need to be bookmarks right away
the moment we see it. Otherwise, that makes no sense because people will
quit."

They were never stored. ``document_layers`` ran the whole Manager pipeline on
every GET, so the marks were COMPUTED at open time and kept missing their
budget. These tests hold the two properties that make moving that computation
safe: it is computed over the PUBLISHED head, and it can fail in every
direction without costing anyone their document.

WHERE it runs moved on 2026-09-20 (#587, task #43) and the tests moved with
it. #580 computed the bake inside ``publish_for_arc``, which seven callers
share — including Take 1 document creation, which it broke. It is now a
queued job asked for on the last line of the analysis run. The section on
the ordering below therefore asserts the OPPOSITE of what it used to: that
the publish does not bake, and that the job reads the head instead of being
handed a snapshot that may since have moved.
"""
from __future__ import annotations

import pytest

from services import ideal_text_core_snapshot as core
from services import ideal_text_feedback_bake as bake


@pytest.fixture(autouse=True)
def _bake_on(monkeypatch):
    """Pin the flag ON regardless of what ships, so every test below is about
    the bake's BEHAVIOUR rather than about today's default. The default has
    already moved twice — off on 2026-09-20 after #580 delayed Take 1
    document creation, back on in #587 once the bake left the publish path —
    and these tests should not have to move with it. The default itself is
    asserted in exactly one place, against the source.

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


def test_publishing_a_head_does_not_bake(monkeypatch):
    """THE #587 INVARIANT, and the reason it is asserted rather than assumed.

    `publish_for_arc` is reached by the cold-open GET, two coach routes,
    block mutation, the later-take finalizer, the RQ publisher and the
    backfill script — and, through `maybe_assemble_ideal_text`, by Take 1
    document creation. Hanging a 20-40s Manager run there is what turned a
    one-second publication into 22 and 42 seconds and terminated a take as
    "we processed your take, but couldn't create your Ideal Text".

    Putting the bake back on this line is the single easiest way to
    reintroduce that incident, and it looks entirely reasonable while you are
    doing it: the snapshot is published and its id is right there. So the
    absence is a test, with the flag ON, where a naive restoration fails.
    """
    order: list[str] = []
    _block_returns(monkeypatch, BLOCK)
    database = _publish_fake(monkeypatch, order)
    assert core.publish_for_arc(database, ARC, ACTOR) == PUBLISHED
    assert order == ["publish"]


def test_the_job_bakes_the_head_as_it_stands_when_it_runs(monkeypatch):
    """Not a style preference — V3 declines outright if this is wrong.

    `read_feedback_v3_candidate_source_snapshot_v1` binds on
    `surface = served_text` against the CURRENT published snapshot. A block
    computed over anything else is one V3 refuses with
    `source_snapshot_does_not_match_served_text`, so the bake would store an
    empty answer and the user would see no bookmarks at all — the exact
    defect this feature exists to end.

    On the publish path that was guaranteed by ordering. From a queue it is
    guaranteed by READING: the job asks the database for the head at the
    moment it runs, rather than trusting an id handed to it when it was
    enqueued, which by then may be a snapshot the document has moved past.
    """
    seen: list[tuple] = []

    class HeadDatabase(RecordingDatabase):
        def get_ideal_text_document_snapshot(self, arc_id, actor_id,
                                             snapshot_id=None):
            seen.append((arc_id, actor_id, snapshot_id))
            return PUBLISHED

    database = HeadDatabase()
    _block_returns(monkeypatch, BLOCK)
    monkeypatch.setattr("services.db.db", database, raising=False)
    bake.run_pending_bake(ARC, ACTOR)
    assert seen == [(ARC, ACTOR, None)], "the head, not a remembered id"
    assert database.writes == [(ARC, ACTOR, SNAPSHOT, BLOCK)]


def test_a_document_with_no_head_yet_bakes_nothing(monkeypatch):
    """A queued job can outrun its document — there is nothing to compute a
    block over, and asking the Manager anyway is how an empty lane gets
    stored for the life of a snapshot that does not exist yet."""
    class NoHead(RecordingDatabase):
        def get_ideal_text_document_snapshot(self, *_args, **_kwargs):
            return None

    def never(*_args, **_kwargs):
        raise AssertionError("the Manager must not run without a head")

    import routes.v2.explore_ideal_text as route
    monkeypatch.setattr(route, "_tracked_changes_block", never)
    database = NoHead()
    monkeypatch.setattr("services.db.db", database, raising=False)
    bake.run_pending_bake(ARC, ACTOR)
    assert database.writes == []


def test_a_job_that_explodes_is_named_and_swallowed(monkeypatch, caplog):
    """A failed RQ job is a red mark on a dashboard for work that is optional
    by construction. It must log and return, never raise."""
    class Exploding(RecordingDatabase):
        def get_ideal_text_document_snapshot(self, *_args, **_kwargs):
            raise RuntimeError("database is down")

    monkeypatch.setattr("services.db.db", Exploding(), raising=False)
    with caplog.at_level("WARNING"):
        bake.run_pending_bake(ARC, ACTOR)
    assert "bake job failed" in caplog.text


# ── asking for the bake: instant, optional, and one per document ───────────


def _queue(monkeypatch, *, configured=True, accepted=True):
    calls: list[tuple] = []
    from services import job_queue
    monkeypatch.setattr(job_queue, "queue_configured", lambda: configured)

    def _enqueue(func_path, *args, **kwargs):
        calls.append((func_path, args, kwargs.get("rq_job_id")))
        return accepted

    monkeypatch.setattr(job_queue, "enqueue", _enqueue)
    return calls


def test_asking_for_a_bake_queues_the_job_and_returns(monkeypatch):
    calls = _queue(monkeypatch)
    assert bake.enqueue_bake(ARC, ACTOR, "spoken") is True
    assert calls == [(
        bake.BAKE_TASK_PATH, (ARC, ACTOR), f"ideal-text-bake:{ARC}:{ACTOR}",
    )]


@pytest.mark.parametrize("kind", ["read", "practice", "", None])
def test_only_a_spoken_take_is_worth_baking(monkeypatch, kind):
    """"Only a spoken take is a real take" (founder bug 2026-07-20).

    A re-read produces no new feedback and a practice clip is not this
    document at all, so a bake on either spends the whole Manager to store
    what is already stored — over a document neither of them changed.
    """
    calls = _queue(monkeypatch)
    assert bake.enqueue_bake(ARC, ACTOR, kind) is False
    assert calls == []


def test_the_call_site_may_pass_the_worker_s_raw_values(monkeypatch):
    """The caller is one unbranched line, so it hands over whatever it holds
    — and in the worker `arc_id` and `user_id` are Optional. `str(None)` is
    the truthy string "None", so a naive guard here would queue a job for an
    arc that does not exist."""
    calls = _queue(monkeypatch)
    assert bake.enqueue_bake(None, ACTOR, "spoken") is False
    assert bake.enqueue_bake(ARC, None, "spoken") is False
    assert calls == []


def test_the_manager_does_not_run_on_the_asking_side(monkeypatch):
    """The entire value of #43 is that this call is instant.

    A version that computed here and queued the storing would move nothing:
    the 20-40 seconds are the Manager, and the caller is the last line of the
    analysis run.
    """
    _queue(monkeypatch)

    def never(*_args, **_kwargs):
        raise AssertionError("the Manager must not run on the enqueue")

    import routes.v2.explore_ideal_text as route
    monkeypatch.setattr(route, "_tracked_changes_block", never)
    bake.enqueue_bake(ARC, ACTOR, "spoken")


def test_no_broker_means_no_bake_and_no_complaint(monkeypatch):
    """Dev, tests and a Redis outage all land here. The read computes live,
    which is what every reader did before any of this existed."""
    calls = _queue(monkeypatch, configured=False)
    assert bake.enqueue_bake(ARC, ACTOR, "spoken") is False
    assert calls == []


def test_a_broker_that_raises_does_not_reach_the_caller(monkeypatch):
    """Its caller is the last line of the analysis run and is deliberately
    NOT wrapped in a degradation guard, because this function cannot raise.
    That claim is only true if it is tested."""
    from services import job_queue
    monkeypatch.setattr(job_queue, "queue_configured", lambda: True)

    def boom(*_args, **_kwargs):
        raise RuntimeError("redis is gone")

    monkeypatch.setattr(job_queue, "enqueue", boom)
    assert bake.enqueue_bake(ARC, ACTOR, "spoken") is False


@pytest.mark.parametrize(("arc_id", "actor_id"), [
    ("", ACTOR), (ARC, ""), ("", ""),
])
def test_an_incomplete_identity_queues_nothing(monkeypatch, arc_id, actor_id):
    calls = _queue(monkeypatch)
    assert bake.enqueue_bake(arc_id, actor_id, "spoken") is False
    assert calls == []


def test_the_flag_gates_the_asking_too(monkeypatch):
    """Off must mean no job exists, not a job that runs and declines. A queue
    full of work that will refuse itself is not a switched-off feature."""
    monkeypatch.setattr(bake, "_bake_enabled", lambda: False)
    calls = _queue(monkeypatch)
    assert bake.enqueue_bake(ARC, ACTOR, "spoken") is False
    assert calls == []


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
# was `not block`, which does not catch it. And the moment the bake ran was
# during assembly: `build_initial_ideal_text_from_stored_artifacts` is called
# BEFORE the pipeline's feedback stages, so a fresh take routinely baked an
# empty block, stored it, and every read afterwards served "no bookmarks" for
# the life of that snapshot.
#
# #587 removed the cause — the bake now runs after those stages — and this
# guard stays anyway. It is the difference between a document that honestly
# has nothing to say and a computation that has not happened yet, and only
# one of the two is safe to store.


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
    """The guard tightened; it did not turn the feature off. A bake run at
    the END of the analysis run — where the Manager has really finished and
    has something to say — stores exactly as designed. Since #587 that is the
    only moment it runs at, which is why the empty case above became rare
    rather than routine."""
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


def test_the_flag_is_on_by_default_now_that_the_bake_is_off_the_publish():
    """FOUNDER, 2026-09-20: "We processed your take, but couldn't create your
    Ideal Text."

    #580 put the whole Manager pipeline inside `publish_for_arc`, which
    `maybe_assemble_ideal_text` calls WHILE A TAKE 1 DOCUMENT IS BEING MADE.
    In production, publication went from about a second to tens of seconds —
    two takes landed their snapshot 22s and 42s after their job had already
    finished, and one never landed at all. #584 switched the flag off and its
    comment named the condition for switching it back: "only once the bake
    runs where it cannot delay creation (task #43)".

    #587 met that condition rather than arguing it away. The bake is not
    reachable from `publish_for_arc` at all — `test_publishing_a_head_does_
    not_bake` above is the assertion — so the failure this flag was turned
    off to stop cannot occur, instead of being unlikely to.

    This test is paired with that one on purpose. Between them, the default
    may only be on while the publish path is clean: restoring the bake to the
    publish fails the other test, and the two cannot be satisfied at once by
    anything except the shipped arrangement.
    """
    # Read the SHIPPED declaration, not the live attribute: the autouse
    # fixture above sets the flag for every other test in this file, and a
    # default test that the fixture can satisfy is a default test that proves
    # nothing.
    import inspect

    import config

    source = inspect.getsource(config)
    assert 'IDEAL_TEXT_FEEDBACK_BAKE_ENABLED", "1"' in source, (
        "the shipped default must be on")
    assert config._env_flag("IDEAL_TEXT_FEEDBACK_BAKE_ENABLED", "1") is True


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
    """The publish must still publish, with the flag in either position.

    Since #587 the publish does not bake either way, so this reads as a
    tautology — and it is kept precisely because it did not used to be. It
    is the OFF half of the pair with `test_publishing_a_head_does_not_bake`:
    whichever way a future change reaches for the publish path, one of the
    two fails.
    """
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
