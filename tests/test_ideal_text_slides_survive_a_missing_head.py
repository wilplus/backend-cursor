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


def _open_core(monkeypatch, *, reads, owned=True, published=True):
    import routes.v2.explore_ideal_text as route

    database = Mock()
    database.get_ideal_text_document_core_v2.side_effect = reads
    monkeypatch.setattr(route, "db", database)
    monkeypatch.setattr(route, "_arc_owned_by_caller",
                        lambda arc_id: (owned, []))
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
