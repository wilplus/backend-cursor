"""Stable parts — Step 0 of SPEC-parts-locking-and-layers.

The document stops being a string and becomes an ordered list whose ids survive
reordering and rewording. PR 3 hangs a lock on those ids, which is why the
validation here is unusually strict: a parts list that disagrees with the text
would anchor a lock to words the student is not looking at, and afterwards a
wrong anchor is indistinguishable from a right one.

TWO THINGS THIS FILE GUARDS THAT ARE NOT OBVIOUS:

  * `joined()` must MIRROR the FE's `joinSegments` exactly. The write path
    refuses a payload whose parts do not join to its text, so a drift between
    the two implementations does not degrade — it makes every save 400.
  * `serve()` distinguishes ABSENT from EMPTY. "This document has no stored
    identity" and "this document is empty" are different states, and the FE
    branches on exactly that difference.

Run: python3 -m unittest test_ideal_text_parts
"""
from __future__ import annotations

import unittest
import uuid
from unittest.mock import patch

from services import intervention_candidates as ic
from services.ideal_text_parts import (
    ACCENTUATION,
    COMPOSITION,
    MAX_DOCUMENT_CHARS,
    MAX_PARTS,
    InvalidParts,
    agrees_with_text,
    allowed_layer,
    joined,
    layer_of_kind,
    part_at,
    part_spans,
    serve,
    validate,
)


def _id() -> str:
    return str(uuid.uuid4())


class TestValidate(unittest.TestCase):

    def test_a_clean_list_gets_ords_from_its_own_order(self):
        a, b = _id(), _id()
        self.assertEqual(
            validate([{"id": a, "text": "one"}, {"id": b, "text": "two"}]),
            [{"id": a, "ord": 0, "text": "one"},
             {"id": b, "ord": 1, "text": "two"}])

    def test_a_client_ord_is_IGNORED(self):
        """The order of the list IS the order of the document. Accepting a
        client `ord` would allow a list whose positions disagree with its own
        sequence, and nothing could say which one the student meant."""
        a, b = _id(), _id()
        out = validate([{"id": a, "ord": 99, "text": "one"},
                        {"id": b, "ord": 0, "text": "two"}])
        self.assertEqual([p["ord"] for p in out], [0, 1])
        self.assertEqual([p["id"] for p in out], [a, b])

    def test_text_is_trimmed(self):
        out = validate([{"id": _id(), "text": "  padded  "}])
        self.assertEqual(out[0]["text"], "padded")

    def test_ids_are_lowercased_so_one_part_has_ONE_id(self):
        """Postgres uuid comparison is case-insensitive but a Python dict key
        is not. Normalising here stops the same part arriving twice under two
        spellings and passing the duplicate check."""
        raw = _id().upper()
        self.assertEqual(validate([{"id": raw, "text": "x"}])[0]["id"],
                         raw.lower())

    def test_an_empty_list_is_a_valid_empty_document(self):
        # Distinct from the key being absent, which the ROUTE decides on.
        self.assertEqual(validate([]), [])


class TestWhatIsRefused(unittest.TestCase):
    """Refused whole, never repaired in part. Half-accepting a list persists an
    identity map that disagrees with the words on screen."""

    def _refuses(self, raw, because):
        with self.assertRaises(InvalidParts, msg=because):
            validate(raw)

    def test_not_a_list(self):
        for raw in ("nope", {"id": _id()}, 7, None):
            self._refuses(raw, "not a list")

    def test_a_non_object_entry(self):
        self._refuses([{"id": _id(), "text": "ok"}, "nope"], "not an object")

    def test_an_id_that_is_not_a_uuid(self):
        """Validated as a real UUID, not "some string". An unvalidated id lets
        a caller mint colliding or guessable ids across arcs, and the collision
        surfaces as one document's lock appearing on another's paragraph."""
        for bad in ("", "abc", "1234", None, 7,
                    "zzzzzzzz-zzzz-zzzz-zzzz-zzzzzzzzzzzz",
                    _id()[:-1]):
            self._refuses([{"id": bad, "text": "x"}], f"bad id {bad!r}")

    def test_a_duplicate_id(self):
        """The most damaging shape here: a lock set on that id would apply to
        whichever row won, and nothing downstream could detect it."""
        a = _id()
        self._refuses([{"id": a, "text": "one"}, {"id": a, "text": "two"}],
                      "duplicate")

    def test_a_duplicate_id_in_DIFFERENT_CASE(self):
        a = _id()
        self._refuses([{"id": a, "text": "one"},
                       {"id": a.upper(), "text": "two"}], "duplicate")

    def test_missing_or_blank_text(self):
        for bad in (None, 7, "", "   ", "\n\n"):
            self._refuses([{"id": _id(), "text": bad}], f"bad text {bad!r}")

    def test_too_many_parts(self):
        self._refuses(
            [{"id": _id(), "text": f"p{i}"} for i in range(MAX_PARTS + 1)],
            "unbounded write")

    def test_the_ceiling_is_on_the_JOINED_document(self):
        """A per-part limit would let 500 parts of 100 chars through — the
        parts join into the same 20k document the text ceiling guards."""
        big = [{"id": _id(), "text": "x" * 500} for _ in range(200)]
        self.assertGreater(len(joined(big)), MAX_DOCUMENT_CHARS)
        self._refuses(big, "too long joined")


class TestJoined(unittest.TestCase):
    """MIRRORS the FE's joinSegments. Not a nicety: the write path refuses a
    payload whose parts do not join to its text, so a drift makes every save
    400 rather than degrade."""

    def test_trims_drops_blanks_and_joins_on_a_blank_line(self):
        self.assertEqual(
            joined([{"text": "  one  "}, {"text": "   "}, {"text": "two"}]),
            "one\n\ntwo")

    def test_survives_junk(self):
        self.assertEqual(joined(None), "")
        self.assertEqual(joined([None, "nope", {}, {"text": None}]), "")

    def test_a_blank_part_would_double_the_separator(self):
        # Dropped rather than preserved: "\n\n" IS the separator, so an empty
        # part emits a doubled one and the next split does not round-trip.
        self.assertNotIn("\n\n\n", joined([{"text": "a"}, {"text": ""},
                                           {"text": "b"}]))


class TestAgreesWithText(unittest.TestCase):
    """The invariant that stops two representations of one document drifting.
    `text` stays canonical for every read-only consumer; `parts` carries
    identity for the same words."""

    def test_the_matching_pair_agrees(self):
        parts = validate([{"id": _id(), "text": "one"},
                          {"id": _id(), "text": "two"}])
        self.assertTrue(agrees_with_text(parts, "one\n\ntwo"))

    def test_surrounding_whitespace_on_the_text_is_not_a_disagreement(self):
        parts = validate([{"id": _id(), "text": "one"}])
        self.assertTrue(agrees_with_text(parts, "  one \n"))

    def test_different_words_disagree(self):
        parts = validate([{"id": _id(), "text": "one"}])
        self.assertFalse(agrees_with_text(parts, "something else"))

    def test_a_missing_part_disagrees(self):
        parts = validate([{"id": _id(), "text": "one"}])
        self.assertFalse(agrees_with_text(parts, "one\n\ntwo"))

    def test_reordered_parts_disagree_with_the_old_text(self):
        # Order is meaning. Two parts swapped is a different document, and the
        # pair must be written together or not at all.
        a, b = _id(), _id()
        parts = validate([{"id": b, "text": "two"}, {"id": a, "text": "one"}])
        self.assertFalse(agrees_with_text(parts, "one\n\ntwo"))
        self.assertTrue(agrees_with_text(parts, "two\n\none"))

    def test_junk_text(self):
        self.assertFalse(agrees_with_text([{"text": "x"}], None))
        self.assertTrue(agrees_with_text([], ""))


class TestServe(unittest.TestCase):

    def test_no_rows_is_ABSENT_not_empty(self):
        """None means "no identity stored, derive as you always did"; []
        would mean "this document is empty". The FE branches on exactly that
        difference, so collapsing them makes a fresh document look cleared."""
        self.assertIsNone(serve([]))
        self.assertIsNone(serve(None))

    def test_rows_come_back_in_ord_order(self):
        a, b, c = _id(), _id(), _id()
        out = serve([{"id": b, "ord": 1, "text": "two"},
                     {"id": c, "ord": 2, "text": "three"},
                     {"id": a, "ord": 0, "text": "one"}])
        self.assertEqual([p["text"] for p in out], ["one", "two", "three"])

    def test_ord_is_REINDEXED_on_the_way_out(self):
        """A gap (a partial write, a row deleted by hand) would otherwise
        reach the client as a position it cannot use — the client renders from
        its own list index."""
        out = serve([{"id": _id(), "ord": 0, "text": "one"},
                     {"id": _id(), "ord": 7, "text": "two"}])
        self.assertEqual([p["ord"] for p in out], [0, 1])

    def test_a_broken_row_is_dropped_not_repaired(self):
        good = _id()
        out = serve([{"id": None, "ord": 0, "text": "x"},
                     {"id": _id(), "ord": 1, "text": None},
                     {"id": _id(), "ord": None, "text": "y"},
                     {"id": good, "ord": 3, "text": "kept"},
                     "nope"])
        self.assertEqual([p["id"] for p in out], [good])

    def test_all_rows_broken_is_ABSENT(self):
        self.assertIsNone(serve([{"id": None, "ord": 0, "text": "x"}]))

    def test_ord_true_is_not_an_integer(self):
        # `isinstance(True, int)` is True in Python and has bitten this repo
        # before.
        self.assertIsNone(serve([{"id": _id(), "ord": True, "text": "x"}]))


class TestTheRoundTrip(unittest.TestCase):
    """What a save then a read has to preserve."""

    def test_validate_then_serve_is_stable(self):
        raw = [{"id": _id(), "text": "Hook."},
               {"id": _id(), "text": "Body."},
               {"id": _id(), "text": "Close."}]
        stored = validate(raw)
        served = serve([dict(p) for p in stored])
        self.assertEqual(served, stored)
        self.assertTrue(agrees_with_text(served, joined(stored)))

    def test_a_reorder_keeps_every_id_and_changes_only_ord(self):
        raw = [{"id": _id(), "text": "A"}, {"id": _id(), "text": "B"}]
        first = validate(raw)
        moved = validate([raw[1], raw[0]])
        self.assertEqual({p["id"] for p in moved}, {p["id"] for p in first})
        self.assertEqual([p["ord"] for p in moved], [0, 1])
        self.assertEqual(moved[0]["id"], first[1]["id"])

    def test_a_reword_keeps_the_id(self):
        pid = _id()
        before = validate([{"id": pid, "text": "Original words."}])
        after = validate([{"id": pid, "text": "Reworded, same part."}])
        self.assertEqual(before[0]["id"], after[0]["id"])
        self.assertNotEqual(before[0]["text"], after[0]["text"])


class TestTheDerivedLayer(unittest.TestCase):
    """§4 — the phase is derived from the lock and NEVER stored. A stored phase
    can desync from the lock that implies it, and then two places disagree
    about whether a rewrite is legal on this paragraph."""

    def test_an_open_part_is_composition(self):
        self.assertEqual(allowed_layer({"locked_at": None}), COMPOSITION)
        self.assertEqual(allowed_layer({}), COMPOSITION)

    def test_a_locked_part_is_accentuation(self):
        self.assertEqual(allowed_layer({"locked_at": "2026-08-07T10:00:00Z"}),
                         ACCENTUATION)

    def test_progressive_locking_needs_no_special_case(self):
        """Part 1 locked while part 2 is open is simply what per-part state
        means — the behaviour §4 says deriving buys for free."""
        parts = [{"locked_at": "2026-08-07T10:00:00Z"}, {"locked_at": None}]
        self.assertEqual([allowed_layer(p) for p in parts],
                         [ACCENTUATION, COMPOSITION])

    def test_the_kind_split_is_what_the_change_does_to_the_text(self):
        # §2: sort the four `kind` enums and they fall cleanly in two.
        self.assertEqual(layer_of_kind("replace"), COMPOSITION)
        self.assertEqual(layer_of_kind("insert"), COMPOSITION)
        self.assertEqual(layer_of_kind("bold"), ACCENTUATION)
        self.assertEqual(layer_of_kind("advice"), ACCENTUATION)

    def test_an_unknown_kind_is_refused_not_defaulted(self):
        """A kind nobody classified is one nobody decided the phase rules for.
        Defaulting it into composition would let an unnamed lane rewrite
        locked text."""
        for bad in ("mystery", "", None, 7):
            self.assertIsNone(layer_of_kind(bad))


class TestPartSpans(unittest.TestCase):
    """Offsets over the joined document. Exact, because `joined()` is the only
    mapping from parts to text and it is deterministic."""

    PARTS = [{"id": "a", "text": "One."}, {"id": "b", "text": "Two."},
             {"id": "c", "text": "Three."}]

    def test_spans_account_for_the_separator(self):
        doc = joined(self.PARTS)
        for start, end, part in part_spans(self.PARTS):
            self.assertEqual(doc[start:end], part["text"])

    def test_a_span_inside_a_part_finds_it(self):
        spans = part_spans(self.PARTS)
        self.assertEqual(part_at(spans, 6, 10)["id"], "b")

    def test_a_span_covering_a_whole_part_finds_it(self):
        spans = part_spans(self.PARTS)
        self.assertEqual(part_at(spans, 0, 4)["id"], "a")

    def test_a_STRADDLING_span_belongs_to_no_part(self):
        """Half in a locked paragraph and half in an open one. There is no
        honest layer for that, and picking either would let a rewrite touch
        locked words or suppress a legal one."""
        spans = part_spans(self.PARTS)
        self.assertIsNone(part_at(spans, 2, 8))

    def test_a_span_in_the_separator_belongs_to_no_part(self):
        spans = part_spans(self.PARTS)
        self.assertIsNone(part_at(spans, 4, 6))

    def test_junk(self):
        self.assertEqual(part_spans(None), [])
        self.assertEqual(part_spans([None, "x", {}]), [])
        self.assertIsNone(part_at([], 0, 1))
        self.assertIsNone(part_at(part_spans(self.PARTS), None, "x"))


class TestR1TheLayerFilter(unittest.TestCase):
    """R1 — the filter runs BEFORE budget selection, and the ORDER is the rule.

    Filtering afterwards would spend budget slots proposing rewrites on text
    the speaker has committed to memory: the slots get consumed, the notes get
    dropped at render, and the student sees one intervention where the engine
    believes it served three.

    This is also what enforces L1 mechanically rather than by convention —
    accentuation must never rewrite, and this is where "must never" stops
    being a comment."""

    def _parts(self, *locked):
        return [{"id": f"p{i}", "text": f"Part {i} words.",
                 "locked_at": "2026-08-07T10:00:00Z" if lk else None}
                for i, lk in enumerate(locked)]

    def _change(self, parts, i, kind):
        start, end, _p = part_spans(parts)[i]
        return {"id": f"c{i}-{kind}", "kind": kind, "source": "polish",
                "span": {"start": start, "end": end}}

    def test_a_locked_part_refuses_a_rewrite(self):
        parts = self._parts(True)
        self.assertEqual(
            ic.filter_by_layer([self._change(parts, 0, "replace")], parts), [])

    def test_a_locked_part_accepts_an_emphasis(self):
        parts = self._parts(True)
        c = self._change(parts, 0, "bold")
        self.assertEqual(ic.filter_by_layer([c], parts), [c])

    def test_an_open_part_accepts_a_rewrite(self):
        parts = self._parts(False)
        c = self._change(parts, 0, "replace")
        self.assertEqual(ic.filter_by_layer([c], parts), [c])

    def test_an_open_part_refuses_an_emphasis(self):
        """Styling a sentence that is about to be replaced is worse than
        offering nothing — §1's other half."""
        parts = self._parts(False)
        self.assertEqual(
            ic.filter_by_layer([self._change(parts, 0, "bold")], parts), [])

    def test_both_layers_live_at_once_on_one_document(self):
        parts = self._parts(True, False)
        keep_bold = self._change(parts, 0, "bold")
        keep_repl = self._change(parts, 1, "replace")
        drop_repl = self._change(parts, 0, "replace")
        drop_bold = self._change(parts, 1, "bold")
        out = ic.filter_by_layer(
            [keep_bold, drop_repl, keep_repl, drop_bold], parts)
        self.assertEqual([c["id"] for c in out],
                         [keep_bold["id"], keep_repl["id"]])

    def test_NO_PARTS_means_everything_passes(self):
        """A document with no stored identity has no locks either. Gating on
        absent parts would silence the whole surface the moment a document had
        not been saved yet."""
        parts = self._parts(False)
        changes = [self._change(parts, 0, "replace"),
                   self._change(parts, 0, "bold")]
        self.assertEqual(ic.filter_by_layer(changes, []), changes)
        self.assertEqual(ic.filter_by_layer(changes, None), changes)

    def test_a_straddling_change_is_dropped(self):
        parts = self._parts(True, False)
        spans = part_spans(parts)
        straddle = {"id": "x", "kind": "replace", "source": "polish",
                    "span": {"start": spans[0][1] - 2, "end": spans[1][0] + 2}}
        self.assertEqual(ic.filter_by_layer([straddle], parts), [])

    def test_an_unknown_kind_is_dropped(self):
        parts = self._parts(False)
        self.assertEqual(
            ic.filter_by_layer([self._change(parts, 0, "mystery")], parts), [])

    def test_THE_FILTER_RUNS_BEFORE_THE_BUDGET(self):
        """The whole point of R1. Four rewrites where the first part is locked:
        if the filter ran AFTER selection, the locked part's rewrite would take
        a budget slot and then be dropped, leaving two notes. Before, it never
        competes and all three surviving slots carry real notes."""
        parts = self._parts(True, False, False, False)
        changes = [self._change(parts, i, "replace") for i in range(4)]
        out = ic.select(changes, parts=parts)["changes"]
        self.assertEqual(len(out), 3)
        self.assertNotIn("c0-replace", [c["id"] for c in out])

    def test_select_without_parts_is_unchanged(self):
        # Safe-ahead: every existing caller keeps working.
        parts = self._parts(False, False)
        changes = [self._change(parts, 0, "replace"),
                   self._change(parts, 1, "replace")]
        self.assertEqual(len(ic.select(changes)["changes"]), 2)


try:
    from flask import Flask, request
    from routes import v2_routes as v2
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    Flask = None
    request = None
    v2 = None
    _IMPORT_ERROR = e

ARC = "a1"


def _row(**over):
    row = {"arc_id": ARC, "text": "machine text", "auto_text": "machine text",
           "updated_by": None, "approved_at": None, "version": 3,
           "verified_version": None, "verified_text": None}
    row.update(over)
    return row


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class ThePutStoresIdentityWithTheWords(unittest.TestCase):
    """`parts` is OPTIONAL on the user-edit PUT — absent is today's behaviour
    byte for byte — and when present it is written with the text or not at
    all."""

    def setUp(self):
        self.app = Flask(__name__)

    def _put(self, body, *, edit_ok=True, parts_ok=True):
        with self.app.test_request_context(json=body):
            request.user_id = "u1"
            with patch("routes.v2.explore_ideal_text._arc_owned_by_caller",
                       return_value=(True, [])), \
                 patch.object(v2.db, "get_coach_arc_ideal_text",
                              return_value=_row()), \
                 patch.object(v2.db, "upsert_user_ideal_edit",
                              return_value=edit_ok), \
                 patch.object(v2.db, "replace_ideal_text_parts",
                              return_value=parts_ok, create=True) as m_parts:
                out = v2.v2_explore_put_ideal_user_edit.__wrapped__(ARC)
                resp, status = out if isinstance(out, tuple) else (out, 200)
                return resp.get_json(), status, m_parts

    def test_no_parts_key_writes_no_parts(self):
        """The whole safe-ahead property: an older client keeps working and
        does not wipe identity a newer one stored."""
        _b, status, m = self._put({"text": "one\n\ntwo", "version": 3})
        self.assertEqual(status, 200)
        m.assert_not_called()

    def test_parts_are_stored_alongside_the_text(self):
        a, b = _id(), _id()
        _b, status, m = self._put({
            "text": "one\n\ntwo", "version": 3,
            "parts": [{"id": a, "text": "one"}, {"id": b, "text": "two"}]})
        self.assertEqual(status, 200)
        m.assert_called_once()
        self.assertEqual(m.call_args[0][2],
                         [{"id": a, "ord": 0, "text": "one"},
                          {"id": b, "ord": 1, "text": "two"}])

    def test_parts_that_do_not_join_to_the_text_are_REFUSED(self):
        """Never repaired. Storing a disagreement leaves identity pointing at
        words the student is not looking at, and a lock set against it in PR 3
        guards the wrong paragraph."""
        body, status, m = self._put({
            "text": "one\n\ntwo", "version": 3,
            "parts": [{"id": _id(), "text": "something else"}]})
        self.assertEqual(status, 400)
        self.assertEqual(body["code"], "INVALID_INPUT")
        m.assert_not_called()

    def test_a_malformed_part_is_a_400_and_writes_NOTHING(self):
        for parts in ([{"id": "not-a-uuid", "text": "one\n\ntwo"}],
                      [{"id": _id()}],
                      "nope"):
            _b, status, m = self._put({"text": "one\n\ntwo", "version": 3,
                                       "parts": parts})
            self.assertEqual(status, 400, parts)
            m.assert_not_called()

    def test_html_is_stripped_from_a_part_the_same_way_as_the_text(self):
        """The text is stripped of tags before storage. If parts were not
        stripped identically, the join check would fail on a document that is
        perfectly fine — so the two run the same expression, adjacently."""
        a = _id()
        _b, status, m = self._put({
            "text": "<b>one</b>\n\ntwo", "version": 3,
            "parts": [{"id": a, "text": "<b>one</b>"},
                      {"id": _id(), "text": "two"}]})
        self.assertEqual(status, 200)
        self.assertEqual(m.call_args[0][2][0], {"id": a, "ord": 0,
                                                "text": "one"})

    def test_a_failed_parts_write_does_not_fail_the_EDIT(self):
        """The words are what matter. A parts write that fails leaves the GET
        omitting the key, the client re-mints, and the next save stores them —
        losing identity costs the ids; failing here would cost the words."""
        _b, status, _m = self._put(
            {"text": "one\n\ntwo", "version": 3,
             "parts": [{"id": _id(), "text": "one"},
                       {"id": _id(), "text": "two"}]},
            parts_ok=False)
        self.assertEqual(status, 200)


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class TheGetServesIdentityOnlyWhenItStillFits(unittest.TestCase):

    def setUp(self):
        self.app = Flask(__name__)

    def _block(self, rows, text):
        with self.app.test_request_context():
            request.user_id = "u1"
            with patch.object(v2.db, "get_ideal_text_parts",
                              return_value=rows, create=True):
                return v2._ideal_parts_block(ARC, "u1", text)

    def test_stored_parts_that_match_are_served(self):
        a, b = _id(), _id()
        out = self._block([{"id": a, "ord": 0, "text": "one"},
                           {"id": b, "ord": 1, "text": "two"}],
                          "one\n\ntwo")
        self.assertEqual([p["id"] for p in out["parts"]], [a, b])

    def test_no_stored_parts_omits_the_KEY(self):
        # Absent, not []. The FE reads absent as "mint locally" and [] as
        # "this document is empty".
        self.assertEqual(self._block([], "one\n\ntwo"), {})

    def test_STALE_parts_are_not_served(self):
        """A new take or a coach verify rewrites the document without going
        through the arranger. Identity pointing at words no longer on screen is
        worse than none — the same rule that refuses to re-point a moved
        tracked change (#219)."""
        self.assertEqual(
            self._block([{"id": _id(), "ord": 0, "text": "the old words"}],
                        "completely different words now"),
            {})

    def test_a_partial_rewrite_is_still_stale(self):
        # All or nothing: the join must match exactly, because a part-by-part
        # rescue would be the guesswork this refuses.
        self.assertEqual(
            self._block([{"id": _id(), "ord": 0, "text": "one"},
                         {"id": _id(), "ord": 1, "text": "two"}],
                        "one\n\ntwo rewritten"),
            {})

    def test_a_broken_read_degrades_to_the_pre_migration_payload(self):
        with self.app.test_request_context():
            request.user_id = "u1"
            with patch.object(v2.db, "get_ideal_text_parts",
                              side_effect=RuntimeError("boom"), create=True):
                self.assertEqual(v2._ideal_parts_block(ARC, "u1", "x"), {})


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class TheLockEndpoint(unittest.TestCase):
    """PUT …/parts/<id>/lock — R2, R3, R5.

    The lock is not a setting: it changes which intervention LAYER may fire on
    this paragraph. So the gates matter more than the write."""

    PA, PB = "11111111-1111-4111-8111-111111111111", \
             "22222222-2222-4222-8222-222222222222"
    DOC = "First part words.\n\nSecond part words."

    def setUp(self):
        self.app = Flask(__name__)

    def _rows(self, locked_a=None):
        return [{"id": self.PA, "ord": 0, "text": "First part words.",
                 "locked_at": locked_a},
                {"id": self.PB, "ord": 1, "text": "Second part words.",
                 "locked_at": None}]

    def _put(self, body, *, rows=None, changes=None, write_ok=True,
             part_id=None):
        rows = self._rows() if rows is None else rows
        with self.app.test_request_context(json=body):
            request.user_id = "u1"
            with patch("routes.v2.explore_ideal_text._arc_owned_by_caller",
                       return_value=(True, [])), \
                 patch.object(v2.db, "get_ideal_text_parts",
                              return_value=rows, create=True), \
                 patch("routes.v2.explore_ideal_text._tracked_changes_block",
                       return_value={"changes": changes or []}), \
                 patch.object(v2.db, "set_ideal_text_part_lock",
                              return_value=write_ok,
                              create=True) as m_write:
                out = v2.v2_explore_set_part_lock.__wrapped__(
                    "a1", part_id or self.PA)
                resp, status = out if isinstance(out, tuple) else (out, 200)
                return resp.get_json(), status, m_write

    def test_locking_a_clean_part_works(self):
        body, status, m = self._put({"locked": True, "text_echo": self.DOC})
        self.assertEqual(status, 200)
        self.assertTrue(body["locked"])
        self.assertEqual(m.call_args[0][3], True)

    def test_unlocking_is_allowed(self):
        """R5 — the cognitive cost of a permanent mistake during practice is
        too high."""
        _b, status, m = self._put({"locked": False, "text_echo": self.DOC},
                                  rows=self._rows(locked_a="2026-08-07T10:00Z"))
        self.assertEqual(status, 200)
        self.assertEqual(m.call_args[0][3], False)

    def test_R3_an_undecided_intervention_BLOCKS_the_lock(self):
        """Locking makes composition illegal on this part, so a pending
        rewrite there becomes unreachable. Auto-disregarding it would write a
        decision the student never made into the one signal §6 depends on."""
        pending = [{"id": "c1", "kind": "replace",
                    "span": {"start": 0, "end": 17}}]
        body, status, m = self._put(
            {"locked": True, "text_echo": self.DOC}, changes=pending)
        self.assertEqual(status, 409)
        self.assertEqual(body["code"], "UNDECIDED")
        self.assertEqual(body["pending"], 1)
        m.assert_not_called()

    def test_R3_applies_in_reverse_to_UNLOCK(self):
        pending = [{"id": "c1", "kind": "bold",
                    "span": {"start": 0, "end": 17}}]
        _b, status, m = self._put(
            {"locked": False, "text_echo": self.DOC},
            rows=self._rows(locked_a="2026-08-07T10:00Z"), changes=pending)
        self.assertEqual(status, 409)
        m.assert_not_called()

    def test_an_intervention_on_ANOTHER_part_does_not_block(self):
        # The gate is per part, not per document — that is what makes
        # progressive locking usable at all.
        other = [{"id": "c2", "kind": "replace",
                  "span": {"start": 19, "end": 37}}]
        _b, status, m = self._put({"locked": True, "text_echo": self.DOC},
                                  changes=other)
        self.assertEqual(status, 200)
        m.assert_called_once()

    def test_a_MOVED_document_is_refused(self):
        """Between the GET and this PUT a take can assemble or the coach can
        verify. Locking a part id against a document that moved settles a
        paragraph the student never read."""
        body, status, m = self._put(
            {"locked": True, "text_echo": "completely different words"})
        self.assertEqual(status, 409)
        self.assertEqual(body["code"], "STALE_DOCUMENT")
        m.assert_not_called()

    def test_no_stored_parts_is_stale_not_a_crash(self):
        body, status, _m = self._put({"locked": True, "text_echo": self.DOC},
                                     rows=[])
        self.assertEqual(status, 409)
        self.assertEqual(body["code"], "STALE_DOCUMENT")

    def test_a_part_from_another_document_is_404(self):
        _b, status, m = self._put(
            {"locked": True, "text_echo": self.DOC},
            part_id="99999999-9999-4999-8999-999999999999")
        self.assertEqual(status, 404)
        m.assert_not_called()

    def test_the_echo_is_REQUIRED(self):
        """A lock is a claim about specific words, so it has to name them."""
        for body in ({"locked": True},
                     {"locked": True, "text_echo": ""},
                     {"locked": True, "text_echo": "   "},
                     {"locked": True, "text_echo": 7}):
            _b, status, m = self._put(body)
            self.assertEqual(status, 400, body)
            m.assert_not_called()

    def test_locked_must_be_a_boolean(self):
        for bad in ("true", 1, None, {}):
            _b, status, _m = self._put({"locked": bad, "text_echo": self.DOC})
            self.assertEqual(status, 400, bad)

    def test_a_gate_that_cannot_read_the_interventions_REFUSES(self):
        """Locking over an unknown pending set is exactly the corruption R3
        exists to prevent, so the gate fails closed."""
        with self.app.test_request_context(
                json={"locked": True, "text_echo": self.DOC}):
            request.user_id = "u1"
            with patch("routes.v2.explore_ideal_text._arc_owned_by_caller",
                       return_value=(True, [])), \
                 patch.object(v2.db, "get_ideal_text_parts",
                              return_value=self._rows(), create=True), \
                 patch("routes.v2.explore_ideal_text._tracked_changes_block",
                       side_effect=RuntimeError("boom")), \
                 patch.object(v2.db, "set_ideal_text_part_lock",
                              return_value=True, create=True) as m_write:
                out = v2.v2_explore_set_part_lock.__wrapped__("a1", self.PA)
                _resp, status = out if isinstance(out, tuple) else (out, 200)
        self.assertEqual(status, 500)
        m_write.assert_not_called()

    def test_a_failed_write_is_a_500_not_a_silent_200(self):
        body, status, _m = self._put({"locked": True, "text_echo": self.DOC},
                                     write_ok=False)
        self.assertEqual(status, 500)
        self.assertEqual(body["code"], "V2_ERROR")

    def test_R2_the_lock_decides_NO_intervention(self):
        """Approve and Lock are different verbs on different objects. Lock is
        not bulk-approve — nothing here writes a decision."""
        with self.app.test_request_context(
                json={"locked": True, "text_echo": self.DOC}):
            request.user_id = "u1"
            with patch("routes.v2.explore_ideal_text._arc_owned_by_caller",
                       return_value=(True, [])), \
                 patch.object(v2.db, "get_ideal_text_parts",
                              return_value=self._rows(), create=True), \
                 patch("routes.v2.explore_ideal_text._tracked_changes_block",
                       return_value={"changes": []}), \
                 patch.object(v2.db, "set_ideal_text_part_lock",
                              return_value=True, create=True), \
                 patch.object(v2.db, "record_ideal_decision",
                              create=True) as m_dec:
                v2.v2_explore_set_part_lock.__wrapped__("a1", self.PA)
        m_dec.assert_not_called()


if __name__ == "__main__":
    unittest.main()
