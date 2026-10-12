"""Several Paragraphs' histories in one request (F5, founder 2026-10-08).

``GET /v2/explore/arc/<arc_id>/part-histories`` answers every named
Paragraph with exactly the single history endpoint's body, reading what the
Paragraphs share once instead of once per Paragraph.
"""
from __future__ import annotations

import inspect
from collections import Counter
from unittest.mock import patch

from flask import Flask, request

from routes.v2 import arcs as arcs_route
from routes.v2 import explore_ideal_text as route

ARC = "arc-1"
OWNER = "owner-1"
P1 = "aaaaaaaa-0000-4000-8000-000000000001"
P2 = "aaaaaaaa-0000-4000-8000-000000000002"
P3 = "aaaaaaaa-0000-4000-8000-000000000003"
T1, T2 = "take-1", "take-2"


def _version(version, take_index, slide0, slide1):
    return {"version": version, "created_at": f"2026-10-0{version}T10:00:00Z",
            "text": f"{slide0}\n\n{slide1}",
            "document": {"take_index": take_index, "paragraphs": [
                {"slide_index": 0}, {"slide_index": 1}]}}


class _Takes:
    def __init__(self, calls):
        self.calls = calls

    def get_arc_sessions(self, _arc):
        self.calls["takes.get_arc_sessions"] += 1
        return [{"id": T1, "user_id": OWNER, "take_index": 1,
                 "recording_kind": "spoken"},
                {"id": T2, "user_id": OWNER, "take_index": 2,
                 "recording_kind": "spoken"}]


class _Db:
    """The reads a Paragraph's history makes, each one counted."""

    def __init__(self):
        self.calls: Counter = Counter()
        self.takes = _Takes(self.calls)

    def _count(self, name):
        self.calls[name] += 1

    def get_ideal_text_document_core(self, _arc, _user):
        self._count("core")
        return {"payload": {
            "parts": [{"id": P1}, {"id": P2}, {"id": P3}],
            "pieces": [{"slide_index": 0}, {"slide_index": 1},
                       {"slide_index": 1}]}}

    def list_ideal_text_versions(self, _arc):
        self._count("versions")
        return [_version(1, 1, "We began.", "Then we grew."),
                _version(2, 2, "We began small.", "Then we grew.")]

    _LOG = {0: [{"phrases": ["began"], "created_at": "2026-10-01T11:00:00Z"}],
            1: [{"phrases": ["grew"], "created_at": "2026-10-02T11:00:00Z"},
                {"phrases": ["we grew"], "created_at": "2026-10-03T11:00:00Z"}]}
    _ADOPT = {1: [{"before_text": "grew", "after_text": "grew fast",
                   "created_at": "2026-10-02T12:00:00Z"}]}
    _REV = {P2: [{"text": "Then we grew fast.",
                  "created_at": "2026-10-01T12:00:00Z"}]}

    def list_slide_helper_words_log(self, _arc, _user, slide):
        self._count("helper_log")
        return [dict(r) for r in self._LOG.get(slide, [])]

    def list_slide_helper_words_log_for_slides(self, _arc, _user, slides):
        self._count("helper_log_batch")
        return {s: [dict(r) for r in self._LOG.get(s, [])] for s in slides}

    def list_practice_adoptions(self, _arc, _user, slide):
        self._count("adoptions")
        return [dict(r) for r in self._ADOPT.get(slide, [])]

    def list_practice_adoptions_for_slides(self, _arc, _user, slides):
        self._count("adoptions_batch")
        return {s: [dict(r) for r in self._ADOPT.get(s, [])] for s in slides}

    def list_accepted_rewrite_revisions(self, _arc, _user, part_id):
        self._count("revisions")
        return [dict(r) for r in self._REV.get(part_id, [])]

    def list_accepted_rewrite_revisions_for_parts(self, _arc, _user, parts):
        self._count("revisions_batch")
        return {p.lower(): [dict(r) for r in self._REV.get(p, [])]
                for p in parts}

    def get_snippet_slide_corrections(self, _sid):
        self._count("corrections")
        return {}

    def get_snippets_by_session(self, sid):
        self._count("snippets")
        return [{"id": f"{sid}-s{slide}", "start_offset_ms": 1000 * slide,
                 "duration_ms": 900, "metrics": {"piece": {"slide_index": slide}}}
                for slide in (0, 1)]

    def list_take_feedback_self_reports(self, sid, _user):
        self._count("self_reports")
        return [{"feedback_family": "confident_voice",
                 "snippet_id": f"{sid}-s1", "response": "yes"}]


def _get(database, view, *args, query="", user=OWNER):
    app = Flask(__name__)
    raw = inspect.unwrap(view)
    with app.test_request_context(f"/x{query}", method="GET"), \
            patch.object(route, "db", database), \
            patch.object(arcs_route, "db", database), \
            patch("services.snippet_audio_url.resolve_snippet_audio_url",
                  lambda snippet, _db=None: f"https://audio/{snippet['id']}"):
        request.user_id = user
        result = raw(*args)
    resp, status = result if isinstance(result, tuple) else (result, 200)
    return resp.get_json(), status


def _single(database, part_id):
    return _get(database, route.v2_explore_get_part_history, ARC, part_id)


def _batch(database, query=""):
    return _get(database, route.v2_explore_get_part_histories, ARC, query=query)


def test_a_failed_batched_read_falls_back_to_the_per_paragraph_read():
    database = _Db()
    database.list_accepted_rewrite_revisions_for_parts = lambda *a: None
    body, status = _batch(database, f"?part_ids={P2}")
    single, _ = _single(_Db(), P2)
    assert status == 200 and body["histories"][P2] == single
    assert database.calls["revisions"] == 1


# ── the batched reads return exactly what the per-value reads return ─────
