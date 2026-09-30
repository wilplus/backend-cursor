"""One draft per coach request, by its kind (founder 2026-09-30, C2; P2-2).

Pins: the surface follows the kind and an ambiguity has none; the draft is
composed from the moment's own passage; a provider that gives nothing is a
503 and never blocks the answer; the draft is kept on the row; the route
sits behind the blind gate; the prompts are locked and the surfaces have
golden datasets and adapters.
"""
from __future__ import annotations

import json
import pathlib
import unittest
from types import SimpleNamespace
from unittest import mock

from services import coach_request_drafts as crd

ROOT = pathlib.Path(__file__).resolve().parents[1]


class _Db:
    def __init__(self, *, transcript="we, we rebuilt the pipeline"):
        self.transcript = transcript
        self.kept = []

    def get_snippets_by_session(self, _take):
        return [{"id": "snip-1", "transcript": self.transcript}]

    def list_speaking_errors(self):
        return [{"error_id": "restart_repair", "label": "Restarting a phrase"}]

    def set_exercise_coach_request_draft(self, **fields):
        self.kept.append(fields)
        return {"id": fields["request_id"], **fields}


def _request(kind="error", **extra):
    return {"id": "req-1", "take_session_id": "take-1", "snippet_id": "snip-1",
            "kind": kind, "observed_tags": ["restart_repair"], "resolution": None,
            **extra}


class SurfaceTests(unittest.TestCase):
    def test_the_surface_follows_the_kind(self):
        self.assertEqual(crd.surface_for(_request("error")), "exercise_script")
        self.assertEqual(crd.surface_for(_request("praise")), "praise_line")
        self.assertEqual(crd.surface_for(_request("rewrite")), "clearer_version")
        self.assertIsNone(crd.surface_for(_request("ambiguity")))


class DraftTests(unittest.TestCase):
    def _complete(self, text="Say the phrase once, then pause."):
        return mock.patch("services.llm.chat_complete",
                          return_value=SimpleNamespace(text=text, model="gpt-x"))

    def test_the_draft_is_written_from_the_passage_and_kept(self):
        db = _Db()
        with self._complete() as complete:
            status, payload = crd.draft_for_request(db, _request(), {}, coach_id="coach-1")
        self.assertEqual(status, 200)
        self.assertEqual(payload["draft"]["surface"], "exercise_script")
        self.assertTrue(payload["draft"]["kept"])
        kwargs = complete.call_args.kwargs
        self.assertIn("we rebuilt the pipeline", kwargs["user"])
        self.assertIn("Restarting a phrase", kwargs["user"])
        self.assertEqual(kwargs["surface"], "exercise_script")
        self.assertEqual(db.kept[0]["model_version"], "gpt-x")

    def test_an_ambiguity_has_no_draft(self):
        status, payload = crd.draft_for_request(_Db(), _request("ambiguity"), {}, coach_id="c")
        self.assertEqual((status, payload["code"]), (409, "NO_DRAFT_FOR_KIND"))

    def test_a_resolved_request_is_not_redrafted(self):
        status, payload = crd.draft_for_request(
            _Db(), _request(resolution="no_safe_match"), {}, coach_id="c")
        self.assertEqual((status, payload["code"]), (409, "ALREADY_RESOLVED"))

    def test_no_provider_answer_is_a_503(self):
        with mock.patch("services.llm.chat_complete", return_value=None):
            status, payload = crd.draft_for_request(_Db(), _request(), {}, coach_id="c")
        self.assertEqual((status, payload["code"]), (503, "DRAFT_UNAVAILABLE"))

    def test_no_passage_is_named(self):
        status, payload = crd.draft_for_request(_Db(transcript=""), _request(), {}, coach_id="c")
        self.assertEqual((status, payload["code"]), (409, "NO_PASSAGE"))

    def test_the_draft_on_a_row_is_coach_only_shape(self):
        self.assertIsNone(crd.draft_on(_request()))
        self.assertEqual(
            crd.draft_on(_request(draft_text="x", draft_surface="praise_line",
                                  draft_model_version="m", drafted_at="t")),
            {"surface": "praise_line", "text": "x", "model_version": "m", "drafted_at": "t"})


class LockTests(unittest.TestCase):
    def test_the_prompts_are_locked_and_evaluable(self):
        locked = json.loads((ROOT / "services/prompts/prompts.lock.json").read_text())["prompts"]
        from tests.evals.surfaces import ADAPTERS
        for surface in ("exercise_script", "praise_line", "clearer_version"):
            self.assertIn(f"{surface}.system", locked)
            self.assertIn(f"{surface}.user", locked)
            self.assertIn(surface, ADAPTERS)
            self.assertTrue((ROOT / "tests/evals/golden" / f"{surface}.jsonl").exists())

    def test_every_prompt_forbids_scores(self):
        from services.prompts import coach_answer_drafts as p
        for system in (p.EXERCISE_SCRIPT_SYSTEM, p.PRAISE_LINE_SYSTEM, p.CLEARER_VERSION_SYSTEM):
            self.assertIn("Never give a score", system)


class RouteTests(unittest.TestCase):
    def test_the_draft_and_the_named_errors_sit_behind_the_blind_gate(self):
        source = (ROOT / "routes/v2/coach.py").read_text()
        gate = source[source.index("def _moment_gate"):source.index("@v2_bp.route", source.index("def _moment_gate"))]
        self.assertIn("BLIND_RATING_REQUIRED", gate)
        for name in ("v2_coach_exercise_request_draft", "v2_coach_named_errors"):
            start = source.index(f"def {name}")
            body = source[start:source.index("@v2_bp.route", start)]
            self.assertIn("_moment_gate(session_id, snippet_id)", body)
            self.assertLess(body.index("_moment_gate"), body.index("from services."))


if __name__ == "__main__":
    unittest.main()
