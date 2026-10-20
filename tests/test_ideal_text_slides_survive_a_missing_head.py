"""
STORY    As a speaker, I want my talk to stay split across its slides even
         when the project has no published head, and opening it not to be
         slow, so that I never see my talk squashed into two pages (the
         Ideal Text step of the critical path).
OUTCOME
  O1  Publishing a head for a Take with no owner copy (most Takes) uses the
      project's owner and keeps every paragraph on its slide.
  O2  Opening a project with no head builds one and serves it, its pieces
      still on their slides.
  O3  After three failed builds the open answers "pending" at once, until a
      new Take finishes.
PROVES   O1 -> test_a_take_without_an_owner_copy_publishes_with_its_slides
         O2 -> test_an_owner_opening_a_project_with_no_head_gets_one_built
         O3 -> test_a_head_that_keeps_failing_to_build_stops_slowing_every_open
WHY      Founder 2026-09-28: "the text was not assigned to the slides ...
         it was all concatenated into two pages"; 2026-10-18: a 404 took 5.9 s.
"""
from __future__ import annotations

from unittest.mock import Mock, patch

from flask import Flask, request

from services import ideal_text_core_snapshot as core

ARC = "00000000-0000-0000-0000-000000000040"
USER = "00000000-0000-0000-0000-000000000030"
TEXT = "Hello everybody.\n\nSo, what we came up with is a.\n\nshort mechanism."
SLIDES = [0, 1, 1]
PIECES = [{"piece_key": i, "text": p, "slide_index": slide}
          for i, (p, slide) in enumerate(zip(TEXT.split("\n\n"), SLIDES))]


def _open_core(monkeypatch, *, reads, owned=True, published=True,
               sessions=(), publish=None):
    import routes.v2.explore_ideal_text as route

    database = Mock()
    database.get_ideal_text_document_core_v2.side_effect = reads
    database.get_ideal_text_document_generation.return_value = 7
    monkeypatch.setattr(route, "db", database)
    monkeypatch.setattr(route, "_arc_owned_by_caller",
                        lambda arc_id: (owned, list(sessions)))
    if publish is None:
        publish = Mock(return_value={"id": "head"} if published else None)
    monkeypatch.setattr(core, "publish_for_arc", publish)
    core._missing_head_publish_attempts.clear()  # noqa: SLF001
    app = Flask(__name__)
    with app.test_request_context("/v2/core"):
        request.user_id = USER
        response = route.v2_explore_get_ideal_text_core.__wrapped__(ARC)
    return response, database, publish


def _core_read():
    return {
        "snapshot": {"id": "s", "payload_sha256": "a" * 64,
                     "payload": {"text": TEXT, "pieces": PIECES}},
        "dynamic_overlay": {
            "owner_edit": None, "confident_moment_summary": None,
            "confident_moment_summary_status": None,
        },
    }


def test_an_owner_opening_a_project_with_no_head_gets_one_built(monkeypatch):
    response, database, publish = _open_core(
        monkeypatch, reads=[None, _core_read()])

    publish.assert_called_once()
    assert publish.call_args.args[1:] == (ARC, USER)
    assert database.get_ideal_text_document_core_v2.call_count == 2
    assert response.status_code == 200
    body = response.get_json()
    assert body["text"] == TEXT
    assert [p["slide_index"] for p in body["pieces"]] == SLIDES


class _PartsDb:
    """What `build_snapshot` asks of the database beyond the resolvers."""

    def __init__(self):
        self.rows: list = []
        self.owner_asked: list = []
        self.ideal_text = self

    def get_coach_arc_ideal_text(self, _arc):
        return {"auto_text": TEXT, "document": {"paragraphs": [
            {"slide_index": slide, "snippet_id": f"snip-{i}"}
            for i, slide in enumerate(SLIDES)]}}

    def get_project_owner_principal(self, project_id):
        self.owner_asked.append(project_id)
        return "project-owner"

    def get_ideal_text_parts(self, *_a, **_k):
        return list(self.rows)

    def replace_ideal_text_parts(self, _arc, _user, parts, revision_action=None):
        self.rows = [{**p, "locked_at": None, "iteration": 0} for p in parts]
        return True


def test_a_take_without_an_owner_copy_publishes_with_its_slides():
    database = _PartsDb()
    source = type("_Source", (), {"machine_text": TEXT, "version": 1})
    live = type("_Live", (), {"text": TEXT, "user_edited": False,
                              "status": "ready", "prior_edit": None})
    display = type("_Display", (), {"text": TEXT, "enabled": False})
    project = type("_Project", (), {
        # The Take carries no owner_principal_id copy.
        "spoken_rows": [{"id": "t1", "project_id": ARC}],
        "latest_take_session_id": "t1", "title": "A talk",
        "can_record_take": True, "presentation_ref": None, "slide_titles": []})
    with patch.object(core, "resolve_ideal_text_source", return_value=source()), \
            patch.object(core, "resolve_live_text", return_value=live()), \
            patch.object(core, "resolve_suggestion_display", return_value=display()), \
            patch.object(core, "resolve_project_read", return_value=project()):
        payload, _seed, lineage = core.build_snapshot(database, ARC, USER, sessions=[])
    assert (lineage["acquisition_principal_id"], lineage["project_id"]) == (
        "project-owner", ARC)
    assert database.owner_asked == [ARC]
    assert payload["text"] == TEXT
    assert [p["slide_index"] for p in payload["pieces"]] == SLIDES


class _FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, int] = {}

    def incr(self, key: str) -> int:
        self.store[key] = self.store.get(key, 0) + 1
        return self.store[key]

    def expire(self, key: str, seconds: int) -> None:
        pass

    def get(self, key: str):
        value = self.store.get(key)
        return None if value is None else str(value).encode()


def test_a_head_that_keeps_failing_to_build_stops_slowing_every_open(
        monkeypatch):
    """Founder 2026-10-18: a 404 took 5.9 s because every open rebuilt a head
    that could not be built. After three failures the open answers "pending"
    at once, until a new Take finishes."""
    from services import job_queue
    redis = _FakeRedis()
    monkeypatch.setattr(job_queue, "get_redis", lambda **_k: redis)
    take_one = [{"id": "t1", "take_index": 1, "analysis_state": "ready"}]
    failing = Mock(return_value=None)

    for _ in range(3):
        response, _db, _ = _open_core(
            monkeypatch, reads=[None], sessions=take_one, publish=failing)
        assert response.status_code == 404
    assert failing.call_count == 3

    response, _db, _ = _open_core(
        monkeypatch, reads=[None], sessions=take_one, publish=failing)
    assert response.status_code == 404
    assert failing.call_count == 3  # resting: no fourth build

    take_two = take_one + [
        {"id": "t2", "take_index": 2, "analysis_state": "ready"}]
    response, _db, publish = _open_core(
        monkeypatch, reads=[None, _core_read()], sessions=take_two)
    publish.assert_called_once()
    assert response.status_code == 200
