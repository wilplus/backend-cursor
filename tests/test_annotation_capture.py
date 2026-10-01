"""willab — the Say-It-Stronger serialization + moment-suggestion text lanes
(founder 2026-07-27, learning-pipeline item 2).

HISTORY: this file used to pin the publish-time RLHF capture
(``record_snippet_publish_annotations`` and its emitter repair). The
arc-level publish and its delivery job are retired (P2-19, contract 65), and
that writer is deleted with them — pairs come from the three answer surfaces
on the coach's walk (35g-2a, services/feedback_pairs.py), with no
replacement publish-time writer.

Still pinned here:
  * the say_it_stronger card serialization: canonical JSON, volatile stamps
    stripped, so a card saved untouched reads equal to its draft;
  * the keep-verdict → writer-corpus flip guard (once per star, re-keep never
    double-writes) and the star text serialization (a delivery star has no
    text → no event);
  * the export prompt coverage and the moment-suggestion final sentinels.

Run: python3 -m unittest tests.test_annotation_capture
"""
from __future__ import annotations

import json
import sys
import types
import unittest

# Prefer the REAL supabase/sentry_sdk (installed in the venv) and stub only
# when genuinely absent. This file sorts early in unittest discovery, so a
# blanket empty-module stub here (the test_db_session_status preamble, which
# gets away with it by sorting late) would poison every later test module's
# import of the real packages.
try:
    import supabase  # noqa: F401
    import sentry_sdk  # noqa: F401
except Exception:  # pragma: no cover - minimal env fallback
    for _m in ("supabase", "sentry_sdk"):
        if _m not in sys.modules:
            sys.modules[_m] = types.ModuleType(_m)
    if not hasattr(sys.modules["supabase"], "create_client"):
        sys.modules["supabase"].create_client = lambda *a, **k: None  # type: ignore[attr-defined]
        sys.modules["supabase"].Client = object  # type: ignore[attr-defined]

try:
    from services.db import DatabaseService, _sis_annotation_text
    _IMPORT_ERR = None
except Exception as e:  # pragma: no cover - env/bootstrap guard
    DatabaseService = None  # type: ignore[assignment]
    _sis_annotation_text = None  # type: ignore[assignment]
    _IMPORT_ERR = e


class _FakeTable:
    def __init__(self, rows, fail_when=None):
        self._rows = rows
        self._fail_when = fail_when
        self._cols = ""

    def select(self, cols):
        self._cols = cols
        return self

    def eq(self, _col, _val):
        return self

    def in_(self, _col, _vals):
        return self

    def limit(self, _n):
        return self

    def execute(self):
        if self._fail_when and self._fail_when(self._cols):
            raise RuntimeError(f'column does not exist in "{self._cols}"')
        return types.SimpleNamespace(data=self._rows)


class _FakeClient:
    """Routes .table(name) to canned per-table rows. ``fail_when`` maps a
    table name to a predicate over the selected column string — raising lets
    tests simulate a missing-column (unrun-migration) DB."""

    def __init__(self, rows_by_table, fail_when=None):
        self.rows_by_table = rows_by_table
        self.fail_when = fail_when or {}

    def table(self, name):
        return _FakeTable(self.rows_by_table.get(name, []),
                          self.fail_when.get(name))


def _card(**over):
    c = {
        "already_strong": False,
        "upgrades": [{"original": "good", "upgrade": "excellent",
                      "reason": None, "kind": "upgrade", "scope": "word"}],
        "rewrite_your_voice": "This is my line.",
        "rewrite_polished": "This is my polished line.",
        "why": "It lands cleanly.",
        "version": 2, "model": "gpt-x", "generated_at": "2026-07-27T00:00:00Z",
    }
    c.update(over)
    return c


@unittest.skipIf(DatabaseService is None, f"services.db import failed: {_IMPORT_ERR}")
class SisAnnotationTextTests(unittest.TestCase):

    def test_volatile_stamps_are_stripped(self):
        text = _sis_annotation_text(_card(edited_by_coach=True))
        self.assertIsNotNone(text)
        parsed = json.loads(text)
        for k in ("model", "generated_at", "version", "edited_by_coach"):
            self.assertNotIn(k, parsed)
        self.assertIn("rewrite_your_voice", parsed)

    def test_canonical_and_deterministic(self):
        a = _sis_annotation_text(_card())
        b = _sis_annotation_text(dict(reversed(list(_card().items()))))
        self.assertEqual(a, b, "key order must not change the serialization")

    def test_volatile_only_difference_serializes_equal(self):
        """The draft carries model/generated_at, the final carries
        edited_by_coach — a coach who saved the card untouched must read as
        approved_as_is, not as a correction."""
        draft = _sis_annotation_text(_card())
        final = _sis_annotation_text(
            {k: v for k, v in _card(edited_by_coach=True).items()
             if k not in ("model", "generated_at")})
        self.assertEqual(draft, final)

    def test_non_dict_and_empty_are_none(self):
        self.assertIsNone(_sis_annotation_text(None))
        self.assertIsNone(_sis_annotation_text("card"))
        self.assertIsNone(_sis_annotation_text(
            {"model": "m", "version": 2}))   # volatile-only → no content


@unittest.skipIf(DatabaseService is None, f"services.db import failed: {_IMPORT_ERR}")
class GetStarVerdictFailClosedTests(unittest.TestCase):
    """The error-distinguishing verdict read behind the keep-flip guard."""

    def _svc(self, rows=None, fail=None):
        svc = DatabaseService.__new__(DatabaseService)
        svc.client = _FakeClient(
            {"star_verdicts": rows or []},
            fail_when={"star_verdicts": fail} if fail else None)
        return svc

    def test_existing_row(self):
        row, ok = self._svc([{"snippet_id": "s1", "verdict": "keep"}]) \
            .get_star_verdict("s1")
        self.assertTrue(ok)
        self.assertEqual(row["verdict"], "keep")

    def test_genuinely_absent_is_ok_true(self):
        row, ok = self._svc([]).get_star_verdict("s1")
        self.assertTrue(ok)
        self.assertIsNone(row)

    def test_transient_error_is_ok_false(self):
        """ok=False on a failed read — the route fails the emission CLOSED
        instead of treating the error as 'no prior verdict' (review
        finding: that re-emitted the corpus row on a re-keep)."""
        row, ok = self._svc(fail=lambda cols: True).get_star_verdict("s1")
        self.assertFalse(ok)
        self.assertIsNone(row)

    def test_missing_table_is_a_real_no_prior(self):
        """A missing star_verdicts table means no verdict CAN exist — that is
        a true 'no prior' (ok=True), not an unknown."""
        def _missing_table(_cols):
            raise RuntimeError('relation "star_verdicts" does not exist '
                               "(42P01)")
        row, ok = self._svc(fail=_missing_table).get_star_verdict("s1")
        self.assertTrue(ok)
        self.assertIsNone(row)


class ExportPromptCoverageTests(unittest.TestCase):
    """The new field_names must not fall through to the bare default prompt
    — SFT would teach 'write prose' against JSON completions (review
    finding)."""

    def test_new_field_names_have_prompts(self):
        from services.ml_finetuning_export import _FIELD_SYSTEM_PROMPTS
        for field in ("say_it_stronger", "moment_suggestion",
                      "ideal_text_sentence", "ideal_text_block"):
            self.assertIn(field, _FIELD_SYSTEM_PROMPTS)
        for field in ("say_it_stronger", "moment_suggestion"):
            self.assertIn("JSON", _FIELD_SYSTEM_PROMPTS[field])


@unittest.skipIf(DatabaseService is None, f"services.db import failed: {_IMPORT_ERR}")
class SetFinalSentinelTests(unittest.TestCase):
    """set_moment_suggestion_final: omitted = preserve, None = clear."""

    class _CapTable:
        def __init__(self, cap):
            self.cap = cap

        def update(self, payload):
            self.cap["update"] = dict(payload)
            return self

        def eq(self, col, val):
            self.cap["eq"] = (col, val)
            return self

        def execute(self):
            return types.SimpleNamespace(data=[])

    def _svc(self, cap):
        svc = DatabaseService.__new__(DatabaseService)
        svc.client = types.SimpleNamespace(
            table=lambda name: self._CapTable(cap))
        return svc

    def test_partial_write_preserves_the_missing_column(self):
        cap: dict = {}
        ok = self._svc(cap).set_moment_suggestion_final(
            "snip-1", why_final="the coach's why", edited_by="coach-1")
        self.assertTrue(ok)
        self.assertIn("why_final", cap["update"])
        self.assertNotIn("replacement_text_final", cap["update"],
                         "an omitted field must not be written (and "
                         "certainly not nulled)")

    def test_explicit_none_still_clears(self):
        cap: dict = {}
        self._svc(cap).set_moment_suggestion_final(
            "snip-1", why_final=None, replacement_text_final="keep",
            edited_by="coach-1")
        self.assertIsNone(cap["update"]["why_final"])
        self.assertEqual(cap["update"]["replacement_text_final"], "keep")

    def test_nothing_provided_is_a_noop(self):
        cap: dict = {}
        ok = self._svc(cap).set_moment_suggestion_final(
            "snip-1", edited_by="coach-1")
        self.assertTrue(ok)
        self.assertNotIn("update", cap)


@unittest.skipIf(DatabaseService is None, f"services.db import failed: {_IMPORT_ERR}")
class SuggestionFoldTests(unittest.TestCase):
    """get_moment_suggestions_by_arc folds coach final over machine draft at
    the ONE reader, with *_draft passthroughs for the corpus/coach review."""

    def _svc(self, rows):
        svc = DatabaseService.__new__(DatabaseService)
        svc.client = _FakeClient({"moment_suggestions": rows})
        return svc

    def test_final_folds_over_draft(self):
        out = self._svc([{
            "snippet_id": "s1", "kind": "replace",
            "why": "machine why", "replacement_text": "machine line",
            "why_final": "coach why", "replacement_text_final": "coach line",
        }]).get_moment_suggestions_by_arc("arc-1")
        row = out["s1"]
        self.assertEqual(row["why"], "coach why")
        self.assertEqual(row["replacement_text"], "coach line")
        self.assertEqual(row["why_draft"], "machine why")
        self.assertEqual(row["replacement_text_draft"], "machine line")

    def test_no_final_is_a_no_op_fold(self):
        out = self._svc([{
            "snippet_id": "s1", "kind": "emphasize", "why": "machine why",
        }]).get_moment_suggestions_by_arc("arc-1")
        row = out["s1"]
        self.assertEqual(row["why"], "machine why")
        self.assertEqual(row["why_draft"], "machine why")


if __name__ == "__main__":
    unittest.main()
