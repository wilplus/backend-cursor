from __future__ import annotations

import ast
import inspect
import time
from pathlib import Path
from unittest.mock import Mock

import pytest
from flask import Flask, request
from services import ideal_text_core_snapshot as core
from services.ideal_text_enrichment import run_sections


ROOT = Path(__file__).resolve().parents[1]


def test_stable_paragraph_identity_carries_proven_slide_lineage():
    previous = {
        "parts": [{"id": "p-1", "text": "Before."}],
        "pieces": [{
            "slide_index": 2,
            "snippet_id": "snippet-1",
            "take_session_id": "take-1",
            "take_index": 1,
        }],
    }
    pieces = core._exact_pieces(  # noqa: SLF001 - pure contract test
        {"auto_text": "Before.", "document": {"paragraphs": []}},
        "After.",
        [{"id": "p-1", "text": "After.", "root_phrase": "After"}],
        previous_payload=previous,
    )
    assert pieces == [{
        "piece_key": 0,
        "part_id": "p-1",
        "text": "After.",
        "root_phrase": "After",
        "root_type": "flagship",
        "slide_index": 2,
        "block_key": None,
        "snippet_id": "snippet-1",
        "take_session_id": "take-1",
        "take_index": 1,
        "status": "settled",
        "challenger": None,
    }]


def test_new_paragraph_identity_never_guesses_a_slide():
    pieces = core._exact_pieces(  # noqa: SLF001 - pure contract test
        {"auto_text": "Before.", "document": {"paragraphs": []}},
        "After.",
        [{"id": "new-id", "text": "After."}],
        previous_payload={
            "parts": [{"id": "old-id", "text": "Before."}],
            "pieces": [{"slide_index": 4}],
        },
    )
    assert pieces[0]["slide_index"] is None


def test_legacy_first_edit_preserves_slide_slots_when_structure_is_unchanged():
    pieces = core._exact_pieces(  # noqa: SLF001 - pure contract test
        {
            "auto_text": "Original one.\n\nOriginal two.",
            "document": {"paragraphs": [
                {"slide_index": 0, "snippet_id": "s-1"},
                {"slide_index": 1, "snippet_id": "s-2"},
            ]},
        },
        "Edited one.\n\nOriginal two.",
        [
            {"id": "p-1", "text": "Edited one."},
            {"id": "p-2", "text": "Original two."},
        ],
    )
    assert [(piece["part_id"], piece["slide_index"])
            for piece in pieces] == [("p-1", 0), ("p-2", 1)]


def test_legacy_first_edit_refuses_structural_slide_guess():
    pieces = core._exact_pieces(  # noqa: SLF001 - pure contract test
        {
            "auto_text": "Original one.\n\nOriginal two.",
            "document": {"paragraphs": [
                {"slide_index": 0}, {"slide_index": 1},
            ]},
        },
        "Merged and changed.",
        [{"id": "new", "text": "Merged and changed."}],
    )
    assert pieces[0]["slide_index"] is None


def test_enrichment_sections_fail_independently_and_run_concurrently():
    def slow(value):
        time.sleep(0.06)
        return value

    def broken():
        raise RuntimeError("optional failure")

    started = time.perf_counter()
    sections, _timings = run_sections({
        "one": lambda: slow({"one": True}),
        "two": lambda: slow({"two": True}),
        "broken": broken,
    }, timeout_seconds=0.3)
    elapsed = time.perf_counter() - started
    assert elapsed < 0.11
    assert sections["one"] == {"status": "ready", "data": {"one": True}}
    assert sections["two"] == {"status": "ready", "data": {"two": True}}
    assert sections["broken"] == {"status": "failed", "retryable": True}


def test_enrichment_timeout_is_retryable_and_does_not_block_response():
    started = time.perf_counter()
    sections, _timings = run_sections({
        "slow": lambda: (time.sleep(0.15), {"late": True})[1],
    }, timeout_seconds=0.02)
    assert time.perf_counter() - started < 0.08
    assert sections["slow"] == {"status": "pending", "retryable": True}


def test_core_handler_is_strictly_read_only_by_architecture():
    path = ROOT / "routes" / "v2" / "explore_ideal_text.py"
    source = path.read_text()
    tree = ast.parse(source)
    handler = next(
        node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "v2_explore_get_ideal_text_core"
    )
    body = ast.get_source_segment(source, handler) or ""
    assert "get_ideal_text_document_core" in body
    called = set()
    for node in ast.walk(handler):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            called.add(node.func.id)
        elif isinstance(node.func, ast.Attribute):
            called.add(node.func.attr)
    assert not called.intersection({
        "compose_locked", "persist_auto_ideal_text",
        "prepare_ideal_text_presentation", "_tracked_changes_block",
        "_moment_explanations_map", "_moment_playback_map",
        "_confidence_review_status_map", "ensure_service_enrollment",
    })


def _call_core(monkeypatch, *, principal, projection=None, projection_error=None):
    import routes.v2.explore_ideal_text as route

    snapshot = {
        "id": "00000000-0000-0000-0000-000000000010",
        "payload_sha256": "a" * 64,
        "payload": {
            "text": "The F1 Ideal Text remains available.",
            "latest_take_session_id": (
                "00000000-0000-0000-0000-000000000020"
            ),
        },
    }
    status = {
        "state": "available" if projection is not None else "disabled",
        "code": None,
        "retryable": False,
    }
    if projection_error is not None:
        code = str(projection_error)
        status = {
            "state": "unavailable", "code": code,
            "retryable": code == "CONFIDENT_MOMENT_PROJECTION_RETRY_REQUIRED",
        }
    core_read = {
        "snapshot": snapshot,
        "dynamic_overlay": {
            "owner_edit": {
                "text": None, "source_document_version": None,
                "user_text_revision": None, "user_text_sha256": None,
                "parts": [], "current_bundle_text_update_binding": None,
            },
            "confident_moment_summary": projection,
            "confident_moment_summary_status": status,
        },
        "read_sha256": "b" * 64,
    }
    database = Mock()
    database.get_ideal_text_document_core_v2.return_value = core_read
    service_repository = Mock()
    monkeypatch.setattr(route, "db", database)
    monkeypatch.setattr(route, "first_client_repository", service_repository)
    app = Flask(__name__)
    with app.test_request_context("/v2/core"):
        request.user_id = "00000000-0000-0000-0000-000000000030"
        response = route.v2_explore_get_ideal_text_core.__wrapped__(
            "00000000-0000-0000-0000-000000000040"
        )
    return response, database, service_repository


def test_core_omits_optional_f2_for_absent_principal_without_enrollment(monkeypatch):
    response, _database, service_repository = _call_core(
        monkeypatch, principal=None
    )
    assert response.status_code == 200
    assert response.get_json()["text"] == "The F1 Ideal Text remains available."
    assert response.get_json()["confident_moment_summary"] is None
    assert response.get_json()["confident_moment_summary_status"] == {
        "state": "disabled", "code": None, "retryable": False,
    }
    _database.get_ideal_text_document_core_v2.assert_called_once()
    _database.get_owner_principal_for_user.assert_not_called()
    service_repository.ensure_service_enrollment.assert_not_called()


@pytest.mark.parametrize(
    "code",
    [
        "MLC3_CURRENT_ENROLLMENT_REQUIRED",
        "MLC3_COHORT_MEMBERSHIP_REQUIRED",
        "MLC3_ENROLLMENT_AUTHORITY_STALE",
    ],
)
def test_core_omits_optional_f2_for_foreign_or_revoked_participant(
    monkeypatch, code
):
    response, _database, service_repository = _call_core(
        monkeypatch,
        principal={"id": "00000000-0000-0000-0000-000000000050"},
        projection_error=RuntimeError(code),
    )
    payload = response.get_json()
    assert response.status_code == 200
    assert payload["text"] == "The F1 Ideal Text remains available."
    assert payload["confident_moment_summary"] is None
    assert payload["confident_moment_summary_status"] == {
        "state": "unavailable", "code": code, "retryable": False,
    }
    service_repository.ensure_service_enrollment.assert_not_called()


@pytest.mark.parametrize(
    ("code", "retryable"),
    [
        ("CONFIDENT_MOMENT_PROJECTION_RETRY_REQUIRED", True),
        ("CONFIDENT_MOMENT_PROJECTION_INVALID", False),
    ],
)
def test_core_preserves_f1_and_reports_typed_f2_failure(
    monkeypatch, code, retryable
):
    response, _database, service_repository = _call_core(
        monkeypatch,
        principal={"id": "00000000-0000-0000-0000-000000000050"},
        projection_error=RuntimeError(code),
    )
    payload = response.get_json()
    assert response.status_code == 200
    assert payload["text"] == "The F1 Ideal Text remains available."
    assert payload["confident_moment_summary"] is None
    assert payload["confident_moment_summary_status"] == {
        "state": "unavailable",
        "code": code,
        "retryable": retryable,
    }
    service_repository.ensure_service_enrollment.assert_not_called()


def test_snapshot_contract_is_rpc_only_and_owner_checked():
    sql = (ROOT / "migrations"
           / "add_ideal_text_core_snapshot.sql").read_text()
    assert "read_ideal_text_document_core_v1" in sql
    assert "publish_ideal_text_document_snapshot_v1" in sql
    assert "p_payload ?& ARRAY" in sql
    assert "source_generation" in sql
    assert "IDEAL_TEXT_DOCUMENT_SOURCE_STALE" in sql
    assert "advance_ideal_text_document_generation_v1" in sql
    assert "ready_take_advances_ideal_text_document_generation" in sql
    assert "generation.generation=snapshot.source_generation" in sql
    assert "REVOKE ALL ON public.ideal_text_document_snapshots" in sql
    assert "GRANT EXECUTE ON FUNCTION" in sql
    assert "owner.user_id::text=p_actor_id" in sql


def test_every_canonical_writer_publishes_the_cold_open_snapshot():
    required = {
        "services/ideal_text_block.py": "publish_for_arc(database",
        "services/take_review.py": "publish_for_arc(database",
        "routes/v2/explore_ideal_text.py": "_publish_ideal_text_core",
        "routes/v2/coach.py": "publish_for_arc(db",
    }
    for relative, needle in required.items():
        assert needle in (ROOT / relative).read_text()


def test_publisher_retries_one_generation_race(monkeypatch):
    class FakeDatabase:
        generations = iter((5, 6))
        calls: list[int] = []

        def get_arc_sessions(self, _arc_id):
            return [{
                "id": "take-1", "take_index": 1, "analysis_state": "ready",
                "recording_kind": "spoken", "user_id": "actor-1",
            }]

        @property
        def takes(self):
            # audit Q-A2: production now calls db.takes.<method>();
            # this fake implements those methods directly on itself.
            return self

        def get_ideal_text_document_generation(self, _arc_id):
            return next(self.generations)

        def get_ideal_text_document_snapshot(self, *_args):
            return None

        def publish_ideal_text_document_snapshot(self, **kwargs):
            self.calls.append(kwargs["source_generation"])
            return None if len(self.calls) == 1 else {"id": "snapshot-2"}

    monkeypatch.setattr(core, "build_snapshot", lambda *_args, **_kwargs: (
        {"text": "Current"}, {}, {
            "acquisition_principal_id": "owner-1",
            "project_id": "project-1",
            "source_take_session_id": "take-1",
            "version": 1,
            "source_fingerprint_sha256": "a" * 64,
        },
    ))
    database = FakeDatabase()
    result = core.publish_for_arc(database, "arc-1")
    assert result == {"id": "snapshot-2"}
    assert database.calls == [5, 6]


def test_durable_generation_sweeper_requeues_only_pending_rows(monkeypatch):
    class FakeDatabase:
        def list_pending_ideal_text_document_publications(self, _limit):
            return [
                {"arc_id": "arc-a", "generation": 3},
                {"arc_id": "", "generation": 4},
                {"arc_id": "arc-b", "generation": "bad"},
            ]

    queued = []
    monkeypatch.setattr(
        core, "enqueue_pending_publication",
        lambda arc_id, generation: queued.append((arc_id, generation)) or True,
    )
    assert core.sweep_pending_publications(FakeDatabase(), limit=20) == 1
    assert queued == [("arc-a", 3)]


def test_enrichment_rejects_snapshot_that_turns_stale_during_readers(
        monkeypatch):
    import routes.v2.explore_ideal_text as route
    import services.learning_exposures as exposures

    selected = {
        "id": "snapshot-old",
        "payload": {
            "latest_take_session_id": "take-1",
            "take_count": 1,
            "version": 1,
            "title": "Test",
            "text": "Exact text.",
            "parts": [],
        },
        "enrichment_seed": {},
    }
    database = Mock()
    database.get_ideal_text_document_core.side_effect = [
        selected,
        {**selected, "id": "snapshot-new"},
    ]
    database.get_ideal_text_document_snapshot.return_value = selected
    monkeypatch.setattr(route, "db", database)
    monkeypatch.setattr(route, "_arc_owned_by_caller", lambda _arc: (
        True,
        [{
            "id": "take-1",
            "owner_principal_id": "owner-1",
            "project_id": "project-1",
        }],
    ))
    prepared = Mock(return_value={
        "presentation_id": "presentation-1",
        "acknowledgement_token": "must-not-leave-server",
    })
    monkeypatch.setattr(
        exposures, "prepare_ideal_text_presentation", prepared)

    app = Flask(__name__)

    @app.before_request
    def actor():
        request.user_id = "actor-1"

    app.add_url_rule(
        "/test/<arc_id>",
        view_func=inspect.unwrap(route.v2_explore_get_ideal_text_enrichment),
    )
    response = app.test_client().get(
        "/test/arc-1?document_snapshot_id=snapshot-old&sections=learning")

    assert response.status_code == 409
    assert response.get_json() == {
        "code": "SNAPSHOT_STALE",
        "current_document_snapshot_id": "snapshot-new",
    }
    assert b"must-not-leave-server" not in response.data
    assert database.get_ideal_text_document_core.call_count == 2
    prepared.assert_called_once()


# ---------------------------------------------------------------------------
#  A DEGRADED read must not be a SILENT one (2026-09-15)
#
#  The cold-open read is built to never 500: when the v2 RPC or its validator
#  fails, the arc is served the pre-#490 v1 document, and when that is missing
#  too the route answers `404 IDEAL_TEXT_DOCUMENT_PENDING, state=pending`.
#  Both are the right wire behaviour — a read fault must not take the recording
#  loop down with it.
#
#  What was missing is the other half. The fallbacks were recorded with
#  `logger.warning` into a stream nobody watches, so on 2026-09-15 every core
#  read in production degraded and the only signal that reached a human was the
#  founder opening the app. These tests pin the fallbacks as COUNTABLE, and pin
#  the two expected quiet paths as quiet, so the signal keeps meaning something.
# ---------------------------------------------------------------------------


def _db_with_client(client):
    """A DatabaseService bound to `client`, skipping the real connect()."""
    from services.db import DatabaseService

    service = DatabaseService.__new__(DatabaseService)
    service.client = client
    return service


def _rpc_router(handlers):
    """A client whose `.rpc(name, ...).execute()` is routed by RPC name.

    An `Exception` value is raised from `execute()`; anything else is returned
    as `.data`. Routing by name matters here: the v2 read falls back to the v1
    read inside its own except block, so a client that failed both would make a
    one-event assertion pass for the wrong reason.
    """
    client = Mock()

    def _rpc(name, _args=None):
        holder = Mock()
        outcome = handlers.get(name)
        if isinstance(outcome, Exception):
            holder.execute.side_effect = outcome
        else:
            holder.execute.return_value = Mock(data=outcome)
        return holder

    client.rpc.side_effect = _rpc
    return client


@pytest.fixture
def observed(monkeypatch):
    """Collect what the read path reports, instead of sending it to Sentry."""
    events: list[tuple[str, dict]] = []
    from services import f1_observability

    monkeypatch.setattr(
        f1_observability, "observe_f1_degrade",
        lambda reason, **kw: events.append((reason, kw)))
    return events


def test_a_failing_v2_read_reports_before_it_falls_back(observed):
    # The shape production raised: an error from INSIDE the function body, so
    # it carries neither the function name nor a PGRST code and does not match
    # the quiet "not deployed yet" branch below.
    boom = Exception("{'code': 'P0002', 'message': 'query returned no rows'}")
    database = _db_with_client(_rpc_router({
        "read_ideal_text_document_core_v2": boom,
        "read_ideal_text_document_core_v1": [],
    }))

    # Unchanged on the wire: still no exception, still a falsy document.
    assert database.get_ideal_text_document_core_v2("arc-1", "actor-1") is None

    # Changed for us: the degrade is now an event with the arc on it, so one
    # bad arc and a product-wide outage no longer look identical.
    assert [r for r, _ in observed] == ["ideal_text_core_v2_read_failed"]
    assert observed[0][1]["exc"] is boom
    assert observed[0][1]["arc_id"] == "arc-1"


def test_the_last_read_standing_reports_when_it_fails_too(observed):
    boom = Exception("connection reset by peer")
    database = _db_with_client(_rpc_router({
        "read_ideal_text_document_core_v1": boom,
    }))

    assert database.get_ideal_text_document_core("arc-1", "actor-1") is None
    assert [r for r, _ in observed] == ["ideal_text_core_read_failed"]


def test_both_reads_failing_is_distinguishable_from_one(observed):
    # v2 degrading to v1 is survivable; v2 AND v1 failing is the arc being
    # unreadable. They must not arrive as the same single event.
    database = _db_with_client(_rpc_router({
        "read_ideal_text_document_core_v2": Exception("boom v2"),
        "read_ideal_text_document_core_v1": Exception("boom v1"),
    }))

    # A non-transient failure on both reads stays "pending" (only a dropped
    # connection is a 503 — see test_ideal_text_core_read_failure_is_not_pending).
    assert database.get_ideal_text_document_core_v2("arc-1", "actor-1") is None
    assert [r for r, _ in observed] == [
        # The v2 degrade is reported BEFORE the fallback is attempted, so it
        # is recorded whether or not the fallback goes on to succeed.
        "ideal_text_core_v2_read_failed",
        "ideal_text_core_read_failed",
    ]


def test_an_arc_with_no_document_yet_raises_no_alarm(observed):
    # The counterweight. If an honest empty arc reported, the signal would fire
    # on every cold open of a new project and be worth nothing.
    database = _db_with_client(_rpc_router({
        "read_ideal_text_document_core_v2": None,
        "read_ideal_text_document_core_v1": [],
    }))

    assert database.get_ideal_text_document_core_v2("arc-1", "actor-1") is None
    assert observed == []


def test_an_rpc_not_deployed_yet_still_degrades_quietly(observed):
    # Code ships before or after its migration depending on the deploy, so
    # "the function is not in the schema cache" is an expected state during a
    # rollout, not a fault worth waking anyone for.
    absent = Exception(
        "{'code': 'PGRST202', 'message': 'Could not find the function "
        "public.read_ideal_text_document_core_v2 in the schema cache'}")
    database = _db_with_client(_rpc_router({
        "read_ideal_text_document_core_v2": absent,
        "read_ideal_text_document_core_v1": [],
    }))

    assert database.get_ideal_text_document_core_v2("arc-1", "actor-1") is None
    assert observed == []


def test_a_broken_snapshot_read_reports_too(observed):
    client = Mock()
    client.table.side_effect = Exception("connection reset by peer")
    database = _db_with_client(client)

    assert database.get_ideal_text_document_snapshot("arc-1", "actor-1") is None
    assert [r for r, _ in observed] == ["ideal_text_snapshot_read_failed"]


def test_THE_LOCK_DEFECT_slides_survive_a_snapshot_with_no_parts_list():
    """A lock must not cost every paragraph its slide.

    Founder 2026-09-17, with a screenshot whose kicker read "YOUR TALK" on a
    deck that had slides a moment earlier: "after the lock the different text
    shows ... something without the slide, entirely wrong".

    THE CHAIN. A lock recomposes the served text, so `aligned` fails — the
    words are no longer the machine's original. The carry by `part_id` is
    next and needs a parts list, but `build_snapshot` drops `served_parts` to
    None whenever they do not agree with the composed text, so `part_rows`
    arrives EMPTY. `ordinal_adoption` then could not fire either, because it
    demanded `bool(part_rows)` — and every paragraph published with
    slide_index None. `groupChunksBySlide` fails on the first of those
    (missing_parent_slide) and collapses the whole deck into one untitled
    section with no slide picture.

    And it did not recover: that snapshot is now the one without parts, so
    the next publication had nothing to carry from either.

    `bool(part_rows)` was never what made the branch sound. The proof is
    about PARAGRAPHS — the edit surface mutates slots in place and cannot
    insert, delete, split, merge or reorder them — so on equal counts slot N
    is still the same Slide-bounded Paragraph, with or without ids to hand.
    """
    pieces = core._exact_pieces(  # noqa: SLF001 - pure contract test
        {
            "auto_text": "Original one.\n\nOriginal two.\n\nOriginal three.",
            "document": {"paragraphs": [
                {"slide_index": 0, "snippet_id": "s-1"},
                {"slide_index": 1, "snippet_id": "s-2"},
                {"slide_index": 1, "snippet_id": "s-3"},
            ]},
        },
        # What the lock composed — same three slots, one of them settled.
        "Original one.\n\nThe locked wording.\n\nOriginal three.",
        None,          # served_parts was dropped: this is the whole defect
        previous_payload=None,   # ...and there is nothing to carry from
    )
    assert [piece["slide_index"] for piece in pieces] == [0, 1, 1]
    # The snippet lineage rides along with the slide it proves.
    assert [piece["snippet_id"] for piece in pieces] == ["s-1", "s-2", "s-3"]


def test_a_paragraph_count_that_changed_still_refuses_to_guess():
    """The widening is bounded: equal counts are still the whole proof."""
    pieces = core._exact_pieces(  # noqa: SLF001 - pure contract test
        {
            "auto_text": "Original one.\n\nOriginal two.\n\nOriginal three.",
            "document": {"paragraphs": [
                {"slide_index": 0}, {"slide_index": 1}, {"slide_index": 1},
            ]},
        },
        # Three paragraphs became two: the slots no longer line up, so
        # position means nothing and the unlinked view is the honest answer.
        "Original one.\n\nTwo and three, merged.",
        None,
    )
    assert [piece["slide_index"] for piece in pieces] == [None, None]


def test_the_focused_retry_gets_time_to_finish_the_manager():
    """FOUNDER 2026-09-20: "no bookmarks" — on a document whose Manager work
    had provably succeeded.

    The deck was drawing its reserved slots on every paragraph, which the
    frontend only does while the server is STILL answering `retryable`. It
    answered that eight times across ninety seconds, because the focused
    retry had eight seconds to do work that measurably takes twenty to forty
    (production publication ran 22s and 42s when this same block was briefly
    computed inside `publish_for_arc`).

    `run_sections` cannot kill a running thread, so each detached reader then
    FINISHED and claimed its feedback set with nobody listening — which is
    why a set existed for a take that showed nothing.
    """
    from services.ideal_text_enrichment import (
        COLD_OPEN_BUDGET_SECONDS,
        FOCUSED_RETRY_BUDGET_SECONDS,
    )

    # The first paint must not wait: a section that cannot answer fast says
    # `retryable` and the words go on screen without it.
    assert COLD_OPEN_BUDGET_SECONDS <= 2.0
    # A retry shorter than the Manager's own runtime detaches the reader every
    # time, and the marks never arrive.
    assert FOCUSED_RETRY_BUDGET_SECONDS >= 20.0
    # Longer than a normal request ceiling trades one silent failure for
    # another; past this the answer is task #43, not a bigger number.
    assert FOCUSED_RETRY_BUDGET_SECONDS <= 45.0


def test_the_route_reads_those_budgets_rather_than_its_own_numbers():
    """One place to change, and a literal in the route would silently win."""
    from pathlib import Path

    source = Path("routes/v2/explore_ideal_text.py").read_text()
    assert "enrichment_timeout = budget_for(requested_sections)" in source
    assert "enrichment_timeout = 8.0" not in source


def test_the_budget_is_earned_by_the_slow_section_not_by_asking_at_all():
    """FOUNDER 2026-09-22: "can you do something to make loading of the
    bookmarks faster? cause it is really long."

    The rule used to be "named any section at all → long budget", so a first
    open — which names none — got two seconds for work that measurably takes
    four and a half. It could not succeed. The page spent two seconds failing
    and then asked again, and the speaker paid a whole round trip for a
    certainty.

    Deciding by WHICH sections are asked for lets one open ask in two lanes:
    the marks with room to finish, everything else still tight. One response
    has one deadline, so two deadlines needs two responses.
    """
    from services.ideal_text_enrichment import (
        COLD_OPEN_BUDGET_SECONDS,
        FOCUSED_RETRY_BUDGET_SECONDS,
        SLOW_SECTIONS,
        budget_for,
    )

    assert "document_layers" in SLOW_SECTIONS

    # The marks lane, on a FIRST open, gets room immediately.
    assert budget_for(["document_layers"]) == FOCUSED_RETRY_BUDGET_SECONDS
    # Everything the page draws around them stays tight, however it is asked.
    assert budget_for(
        ["feedback", "notes", "history", "journey", "entitlement", "learning"],
    ) == COLD_OPEN_BUDGET_SECONDS
    assert budget_for([]) == COLD_OPEN_BUDGET_SECONDS
    # One slow section in the set is enough to earn the long budget for it.
    assert budget_for(["feedback", "document_layers"]) == (
        FOCUSED_RETRY_BUDGET_SECONDS)
