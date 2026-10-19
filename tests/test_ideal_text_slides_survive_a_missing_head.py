"""The deck keeps its slides when a project has no published head
(founder 2026-09-28: "the text was not assigned to the slides ... there
should be at least five slides and it was all concatenated into two pages").

Three defects, one screen: the unlinked "Your talk" section with no slide
picture.

1. A Take without the denormalised ``owner_principal_id`` copy -- most of
   them -- made ``build_snapshot`` refuse (LINEAGE_REQUIRED), so the project
   never got a head at all.
2. With no head, every open fell back to the composing read, whose
   provenance threw every Slide away the moment the served words differed
   from the stored Take-1 body.
3. Nothing ever repaired the missing head (decision 16A: build and save it
   the moment it's opened).
"""
from __future__ import annotations

from unittest.mock import Mock

from flask import Flask, request

from services import ideal_text_core_snapshot as core

ARC = "00000000-0000-0000-0000-000000000040"
USER = "00000000-0000-0000-0000-000000000030"
TEXT = "Hello everybody.\n\nSo, what we came up with is a.\n\nshort mechanism."


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
                     "payload": {"text": TEXT}},
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
    assert response.get_json()["text"] == TEXT


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
