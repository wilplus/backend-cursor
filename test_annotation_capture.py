"""willab — the publish-time RLHF capture repair + the Say-It-Stronger and
moment-suggestion text lanes (founder 2026-07-27, learning-pipeline item 2).

THE REPAIR THIS PINS DOWN (so it can never silently regress the same way):
``_emit_publish_event_if_signal`` used to call
``self.insert_admin_annotation_event`` — a method that has never existed in
any commit — with ``user_id=None`` against the table's NOT NULL. The
AttributeError was swallowed and every publish wrote ZERO rlhf rows. These
tests exercise the real emit path down to ``create_admin_annotation_event``'s
kwargs, unmocked in between, which is exactly what the old tests didn't do.

Also pinned:
  * the say_it_stronger (draft, coach-final) pair at publish — canonical JSON,
    volatile stamps stripped, missing final == approved_as_is;
  * the keep-verdict → writer-corpus flip guard (once per star, re-keep never
    double-writes) and the star text serialization (a delivery star has no
    text → no event).

Run: python3 -m unittest test_annotation_capture
"""
from __future__ import annotations

import json
import sys
import types
import unittest
from unittest.mock import MagicMock

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
class EmitRepairTests(unittest.TestCase):
    """The dead-emitter repair, exercised down to the real insert helper."""

    def _svc(self):
        svc = DatabaseService.__new__(DatabaseService)
        svc.create_admin_annotation_event = MagicMock()
        return svc

    def test_emit_reaches_the_real_helper_with_the_owner(self):
        svc = self._svc()
        n = svc._emit_publish_event_if_signal(
            session_id="sess-1", admin_user_id="coach-1",
            section_type="charisma_snippet", field_name="admin_comment",
            draft="draft text", final="final text", draft_id="snip-1",
            owner_user_id="student-1",
        )
        self.assertEqual(n, 1)
        kwargs = svc.create_admin_annotation_event.call_args.kwargs
        self.assertEqual(kwargs["user_id"], "student-1")
        self.assertEqual(kwargs["created_by"], "coach-1")
        self.assertEqual(kwargs["ai_original_text"], "draft text")
        self.assertEqual(kwargs["coach_final_text"], "final text")
        self.assertIsNone(kwargs["reason_chip"])
        self.assertEqual(kwargs["draft_id"], "snip-1")

    def test_approved_as_is_on_normalized_equality(self):
        svc = self._svc()
        svc._emit_publish_event_if_signal(
            session_id="s", admin_user_id="c", section_type="x",
            field_name="f", draft="Same  Text", final="same text",
            draft_id=None, owner_user_id="u",
        )
        kwargs = svc.create_admin_annotation_event.call_args.kwargs
        self.assertEqual(kwargs["reason_chip"], "approved_as_is")

    def test_no_owner_skips_instead_of_violating_not_null(self):
        svc = self._svc()
        n = svc._emit_publish_event_if_signal(
            session_id="s", admin_user_id="c", section_type="x",
            field_name="f", draft="d", final="f", draft_id=None,
            owner_user_id=None,
        )
        self.assertEqual(n, 0)
        svc.create_admin_annotation_event.assert_not_called()

    def test_no_signal_no_row(self):
        svc = self._svc()
        n = svc._emit_publish_event_if_signal(
            session_id="s", admin_user_id="c", section_type="x",
            field_name="f", draft="  ", final=None, draft_id=None,
            owner_user_id="u",
        )
        self.assertEqual(n, 0)

    def test_insert_failure_returns_zero_never_raises(self):
        svc = self._svc()
        svc.create_admin_annotation_event.side_effect = RuntimeError("db down")
        n = svc._emit_publish_event_if_signal(
            session_id="s", admin_user_id="c", section_type="x",
            field_name="f", draft="d", final="f2", draft_id=None,
            owner_user_id="u",
        )
        self.assertEqual(n, 0)


@unittest.skipIf(DatabaseService is None, f"services.db import failed: {_IMPORT_ERR}")
class PublishCaptureTests(unittest.TestCase):
    """record_snippet_publish_annotations end-to-end over a fake client."""

    def _svc(self, charisma_rows, owner="student-1", fail_when=None,
             already_captured=False):
        svc = DatabaseService.__new__(DatabaseService)
        svc.client = _FakeClient({
            "charisma_snippets": charisma_rows,
            "recordings": [],
            # the idempotency probe reads this table: [] = not yet captured
            "admin_annotation_events": ([{"id": "e1"}] if already_captured
                                        else []),
        }, fail_when=fail_when)
        svc.v2_get_session_by_id = MagicMock(
            return_value={"id": "sess-1", "user_id": owner} if owner else {})
        svc.get_coach_snippet_drafts = MagicMock(return_value=[])
        svc.create_admin_annotation_event = MagicMock()
        return svc

    def _events(self, svc):
        return [c.kwargs for c in
                svc.create_admin_annotation_event.call_args_list]

    def test_say_it_stronger_draft_only_is_approved_as_is(self):
        svc = self._svc([{"id": "snip-1", "say_it_stronger": _card()}])
        n = svc.record_snippet_publish_annotations(
            session_id="sess-1", admin_user_id="coach-1")
        events = self._events(svc)
        sis = [e for e in events if e["field_name"] == "say_it_stronger"]
        self.assertEqual(len(sis), 1)
        self.assertEqual(n, len(events))
        e = sis[0]
        self.assertEqual(e["reason_chip"], "approved_as_is")
        self.assertEqual(e["ai_original_text"], e["coach_final_text"])
        self.assertEqual(e["user_id"], "student-1")
        self.assertEqual(e["section_type"], "charisma_snippet")
        parsed = json.loads(e["ai_original_text"])
        self.assertNotIn("model", parsed)

    def test_say_it_stronger_correction_pair(self):
        final = _card(rewrite_polished="A very different polished line.",
                      edited_by_coach=True)
        svc = self._svc([{"id": "snip-1", "say_it_stronger": _card(),
                          "say_it_stronger_final": final}])
        svc.record_snippet_publish_annotations(
            session_id="sess-1", admin_user_id="coach-1")
        sis = [e for e in self._events(svc)
               if e["field_name"] == "say_it_stronger"]
        self.assertEqual(len(sis), 1)
        self.assertIsNone(sis[0]["reason_chip"])
        self.assertNotEqual(sis[0]["ai_original_text"],
                            sis[0]["coach_final_text"])

    def test_final_differing_only_in_stamps_is_approved_as_is(self):
        final = _card(edited_by_coach=True)
        del final["model"], final["generated_at"]
        svc = self._svc([{"id": "snip-1", "say_it_stronger": _card(),
                          "say_it_stronger_final": final}])
        svc.record_snippet_publish_annotations(
            session_id="sess-1", admin_user_id="coach-1")
        sis = [e for e in self._events(svc)
               if e["field_name"] == "say_it_stronger"]
        self.assertEqual(sis[0]["reason_chip"], "approved_as_is")

    def test_no_card_no_sis_event(self):
        svc = self._svc([{"id": "snip-1", "admin_comment": "nice",
                          "ai_draft_admin_comment": "draft nice"}])
        svc.record_snippet_publish_annotations(
            session_id="sess-1", admin_user_id="coach-1")
        events = self._events(svc)
        self.assertFalse([e for e in events
                          if e["field_name"] == "say_it_stronger"])
        # ...and the classic admin_comment lane still fires (the repair).
        comments = [e for e in events if e["field_name"] == "admin_comment"]
        self.assertEqual(len(comments), 1)
        self.assertEqual(comments[0]["user_id"], "student-1")

    def test_missing_owner_captures_nothing(self):
        svc = self._svc([{"id": "snip-1", "say_it_stronger": _card(),
                          "admin_comment": "x",
                          "ai_draft_admin_comment": "y"}], owner=None)
        n = svc.record_snippet_publish_annotations(
            session_id="sess-1", admin_user_id="coach-1")
        self.assertEqual(n, 0)
        svc.create_admin_annotation_event.assert_not_called()

    def test_final_only_card_still_captured(self):
        """Coach wrote the card from scratch (draft never generated) — the
        empty-draft pair must still enter the corpus (review finding)."""
        final = _card(edited_by_coach=True)
        svc = self._svc([{"id": "snip-1", "say_it_stronger": None,
                          "say_it_stronger_final": final}])
        svc.record_snippet_publish_annotations(
            session_id="sess-1", admin_user_id="coach-1")
        sis = [e for e in self._events(svc)
               if e["field_name"] == "say_it_stronger"]
        self.assertEqual(len(sis), 1)
        self.assertIsNone(sis[0]["reason_chip"])
        self.assertIsNone(sis[0]["ai_original_text"])
        self.assertIn("rewrite_polished", sis[0]["coach_final_text"])

    def test_republish_is_skipped_by_the_probe(self):
        """The repaired emitter made the documented re-publish double-write
        LIVE — the session-level probe closes it (review finding)."""
        svc = self._svc([{"id": "snip-1", "say_it_stronger": _card()}],
                        already_captured=True)
        n = svc.record_snippet_publish_annotations(
            session_id="sess-1", admin_user_id="coach-1")
        self.assertEqual(n, 0)
        svc.create_admin_annotation_event.assert_not_called()

    def test_probe_failure_reads_as_captured(self):
        """Never double-write on uncertainty (the backfill's rule): a probe
        error must skip the capture, not fall through to writing blind."""
        svc = self._svc([{"id": "snip-1", "say_it_stronger": _card()}],
                        fail_when={"admin_annotation_events":
                                   lambda cols: True})
        n = svc.record_snippet_publish_annotations(
            session_id="sess-1", admin_user_id="coach-1")
        self.assertEqual(n, 0)
        svc.create_admin_annotation_event.assert_not_called()

    def test_half_migrated_db_still_captures_the_draft(self):
        """add_say_it_stronger.sql run, add_say_it_stronger_final.sql NOT:
        tier 0 fails on the missing final column, but the next tier must
        still carry say_it_stronger — the draft-only approved_as_is capture
        survives (review finding: the coarse ladder dropped both)."""
        svc = self._svc(
            [{"id": "snip-1", "say_it_stronger": _card()}],
            fail_when={"charisma_snippets":
                       lambda cols: "say_it_stronger_final" in cols})
        svc.record_snippet_publish_annotations(
            session_id="sess-1", admin_user_id="coach-1")
        sis = [e for e in self._events(svc)
               if e["field_name"] == "say_it_stronger"]
        self.assertEqual(len(sis), 1)
        self.assertEqual(sis[0]["reason_chip"], "approved_as_is")


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

    def test_backfill_probe_knows_every_emitted_field(self):
        """KEEP IN SYNC pin: a field the writer emits but the backfill probe
        doesn't know lets a backfill re-run double-write it. Source-level on
        purpose — the script imports heavy deps at module top."""
        with open("scripts/backfill_few_shot_annotations.py",
                  encoding="utf-8") as fh:
            source = fh.read()
        from services.db import DatabaseService as _DS
        for field in _DS._PUBLISH_CAPTURE_FIELDS:
            self.assertIn(f'"{field}"', source,
                          f"{field} missing from _PUBLISH_PATH_FIELDS")


class KeepFlipGuardTests(unittest.TestCase):
    """The once-per-star guard + the star text serialization (pure)."""

    def test_flip_to_keep_emits(self):
        from services.star_verdicts import should_emit_keep_text
        self.assertTrue(should_emit_keep_text("keep", None))
        self.assertTrue(should_emit_keep_text("keep", "wrong_kind"))
        self.assertTrue(should_emit_keep_text("keep", "should_not_fire"))

    def test_re_keep_and_non_keep_do_not(self):
        from services.star_verdicts import should_emit_keep_text
        self.assertFalse(should_emit_keep_text("keep", "keep"))
        self.assertFalse(should_emit_keep_text("wrong_kind", None))
        self.assertFalse(should_emit_keep_text("should_not_fire", "keep"))

    def test_untouched_star_pair_is_equal_sides(self):
        from services.star_verdicts import annotation_pair_for_star
        pair = annotation_pair_for_star({
            "snippet_id": "s1", "arc_id": "a1", "kind": "replace",
            "trigger": "profanity", "why": "swap the swear",
            "why_draft": "swap the swear",
            "replacement_text": "a cleaner line",
            "replacement_text_draft": "a cleaner line",
            "created_at": "2026-01-01",
        })
        self.assertIsNotNone(pair)
        draft, final = pair
        self.assertEqual(draft, final)   # → the caller stamps approved_as_is
        parsed = json.loads(final)
        self.assertEqual(
            set(parsed), {"kind", "trigger", "why", "replacement_text"})

    def test_coach_corrected_star_pair_differs(self):
        from services.star_verdicts import annotation_pair_for_star
        draft, final = annotation_pair_for_star({
            "kind": "replace", "trigger": "profanity",
            "why": "the coach's better why", "why_draft": "machine why",
            "replacement_text": "the coach's line",
            "replacement_text_draft": "machine line",
        })
        self.assertNotEqual(draft, final)
        self.assertIn("machine line", draft)
        self.assertIn("the coach's line", final)

    def test_textless_delivery_star_yields_none(self):
        from services.star_verdicts import annotation_pair_for_star
        self.assertIsNone(annotation_pair_for_star(
            {"kind": "delivery", "trigger": "pace_fast",
             "why": None, "replacement_text": None}))
        self.assertIsNone(annotation_pair_for_star(None))

    def test_structure_star_quote_survives(self):
        from services.star_verdicts import annotation_pair_for_star
        _draft, final = annotation_pair_for_star(
            {"kind": "structure", "trigger": "contrast",
             "why": "it's not speed, it's control", "replacement_text": None})
        self.assertIn("it's not speed", final)


class StarTextValidationTests(unittest.TestCase):
    """The coach star-text PUT body — full-state, guard-rejecting."""

    def test_valid_correction(self):
        from services.star_verdicts import validate_star_text
        row, err = validate_star_text(
            {"why": "this lands because it names the fear",
             "replacement_text": "say the fear out loud"})
        self.assertIsNone(err)
        self.assertEqual(row["why"], "this lands because it names the fear")

    def test_single_field_clears_the_other(self):
        from services.star_verdicts import validate_star_text
        row, err = validate_star_text({"why": "just the why"})
        self.assertIsNone(err)
        self.assertIsNone(row["replacement_text"])   # full-state semantics

    def test_explicit_null_clears(self):
        from services.star_verdicts import validate_star_text
        row, err = validate_star_text({"why": None,
                                       "replacement_text": "keep this"})
        self.assertIsNone(err)
        self.assertIsNone(row["why"])

    def test_digits_are_rejected_loudly_not_nulled(self):
        """Unlike generation (which silently nulls), a coach edit tripping
        the AC-9 guard must 400 — a 'successful' PUT that dropped the text
        would gaslight the coach."""
        from services.star_verdicts import validate_star_text
        row, err = validate_star_text({"why": "pause for 2 beats"})
        self.assertIsNone(row)
        self.assertIn("qualitative guard", err)

    def test_construct_vocabulary_is_rejected(self):
        from services.star_verdicts import validate_star_text
        row, err = validate_star_text(
            {"why": "your charisma score improved"})
        self.assertIsNone(row)

    def test_empty_body_and_junk(self):
        from services.star_verdicts import validate_star_text
        self.assertIsNotNone(validate_star_text({})[1])
        self.assertIsNotNone(validate_star_text(None)[1])
        self.assertIsNotNone(validate_star_text({"why": "   "})[1])
        self.assertIsNotNone(validate_star_text({"why": 42})[1])


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
