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
    allowed_layer,
    compose_locked,
    covered_by_locked_part,
    joined,
    part_at,
    part_spans,
    pinned_parts,
    serve,
    validate,
)


def _id() -> str:
    return str(uuid.uuid4())


class TestValidate(unittest.TestCase):


    def test_an_empty_list_is_a_valid_empty_document(self):
        # Distinct from the key being absent, which the ROUTE decides on.
        self.assertEqual(validate([]), [])


class TestWhatIsRefused(unittest.TestCase):
    """Refused whole, never repaired in part. Half-accepting a list persists an
    identity map that disagrees with the words on screen."""

    def _refuses(self, raw, because):
        with self.assertRaises(InvalidParts, msg=because):
            validate(raw)


    def test_a_non_object_entry(self):
        self._refuses([{"id": _id(), "text": "ok"}, "nope"], "not an object")


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


class TestServe(unittest.TestCase):


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


class TestTheDerivedLayer(unittest.TestCase):
    """§4 — the phase is derived from the lock and NEVER stored. A stored phase
    can desync from the lock that implies it, and then two places disagree
    about whether a rewrite is legal on this paragraph."""


    def test_progressive_locking_needs_no_special_case(self):
        """Part 1 locked while part 2 is open is simply what per-part state
        means — the behaviour §4 says deriving buys for free."""
        parts = [{"locked_at": "2026-08-07T10:00:00Z"}, {"locked_at": None}]
        self.assertEqual([allowed_layer(p) for p in parts],
                         [ACCENTUATION, COMPOSITION])


class TestPartSpans(unittest.TestCase):
    """Offsets over the joined document. Exact, because `joined()` is the only
    mapping from parts to text and it is deterministic."""

    PARTS = [{"id": "a", "text": "One."}, {"id": "b", "text": "Two."},
             {"id": "c", "text": "Three."}]


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

    # ── GENERATION TWO (founder decision 2026-08-10, SPEC-lockin-loop §2) ──
    # The first generation allowed the whole accentuation layer on locked
    # parts and refused it on open ones. The founder overruled both halves:
    # "Ordinary AI corrections skip locked text ENTIRELY. The ONLY exception
    # is Confident Voice" — which passes through as a small pending prompt,
    # never a normal offer. Open parts take everything; the budget decides.
    # The tests below ARE that decision; do not "fix" them back.

    def test_a_locked_part_RE_OPENS_on_a_new_rewrite(self):
        """R1 gen-4 (founder 2026-08-11, later the same day): "when the
        engine is locked in keep it there… but if something new appears
        there keep iterating and showing the suggestions."

        Gen-3 dropped composition on locked text outright. It now passes,
        TAGGED, and the chunk re-enters accept/discard → lock again.

        This does NOT touch L1. L1 forbids the machine rewriting committed
        words; it says nothing against the speaker being offered a better
        version and choosing. The offer is still an offer, and the lock is
        what the student re-applies."""
        parts = self._parts(True)
        out = ic.filter_by_layer([self._change(parts, 0, "replace")], parts)
        self.assertEqual(len(out), 1)
        self.assertTrue(out[0]["reopens_locked"])
        # Nothing DECIDED can arrive here to be re-offered: a dismissed
        # proposal's row is deleted and an approved one is baked into the
        # document. "New" is the only thing left.


    def test_a_locked_part_passes_confident_voice_as_pending(self):
        """The ONE exception, tagged rather than served as a normal offer:
        the FE renders the founder's small prompt from `pending_copy`."""
        parts = self._parts(True)
        c = {**self._change(parts, 0, "bold"),
             "trigger": ic.CONFIDENT_VOICE_TRIGGER}
        out = ic.filter_by_layer([c], parts)
        self.assertEqual(len(out), 1)
        self.assertTrue(out[0]["pending_better_version"])
        self.assertEqual(out[0]["pending_copy"],
                         ic.PENDING_BETTER_VERSION_COPY)
        # the original offer fields survive for the FE to anchor the prompt
        self.assertEqual(out[0]["id"], c["id"])


    def test_the_visual_registry(self):
        """SPEC §3: Confident Voice = star; rewrites = underline; accents =
        bold. One table, stamped on survivors in select()."""
        self.assertEqual(
            ic.visual_of({"kind": "bold",
                          "trigger": ic.CONFIDENT_VOICE_TRIGGER}), "star")
        self.assertEqual(ic.visual_of({"kind": "replace"}), "underline")
        self.assertEqual(ic.visual_of({"kind": "insert"}), "underline")
        self.assertEqual(ic.visual_of({"kind": "bold"}), "bold")
        self.assertEqual(ic.visual_of({"kind": "advice"}), "bold")


    def test_a_straddling_change_is_dropped(self):
        parts = self._parts(True, False)
        spans = part_spans(parts)
        straddle = {"id": "x", "kind": "replace", "source": "polish",
                    "span": {"start": spans[0][1] - 2, "end": spans[1][0] + 2}}
        self.assertEqual(ic.filter_by_layer([straddle], parts), [])


class TestCoveredByLockedPart(unittest.TestCase):
    """THE SAVE HOLE (founder-approved fix 2026-08-07).

    Save resolves every unactioned offer as kept-mine so the document is left
    clean. But R1 HIDES composition offers on a locked part — so a student
    could lock a section, say it better in a later take, hit Save, and have
    that upgrade silently declined without it ever reaching the screen. Same
    defect R3 refuses on the lock button: a decision nobody made, written into
    the one signal §6 depends on."""

    LOCKED = [{"id": "a", "text": "We started in a tiny garage.",
               "locked_at": "2026-08-07T10:00:00Z"},
              {"id": "b", "text": "And then we shipped it fast.",
               "locked_at": None}]


    def test_case_and_whitespace_do_not_decide_it(self):
        """The served document is finalize-cased and stored block text is not
        — the #230 raw-vs-document class. A capital must not be the difference
        between holding an offer and silently declining it."""
        self.assertTrue(
            covered_by_locked_part("we  started   in a TINY garage.",
                                   self.LOCKED))


    def test_junk(self):
        self.assertFalse(covered_by_locked_part("", self.LOCKED))
        self.assertFalse(covered_by_locked_part(None, self.LOCKED))
        self.assertFalse(covered_by_locked_part("x", [None, "nope", {}]))


class TestComposeLocked(unittest.TestCase):
    """THE UN-PARKED VERSIONING CHANGE (founder 2026-08-10). The document
    composes per part: a locked paragraph keeps the student's typed words
    verbatim, an unlocked one refreshes to the machine's current text. The
    whole-document version swap — and the card that apologised for it — stop
    happening on this lane."""

    def _rows(self, *specs):
        return [{"id": _id(), "ord": i, "text": t,
                 "locked_at": "2026-08-10T00:00:00Z" if lk else None}
                for i, (t, lk) in enumerate(specs)]


    def test_identity_case_is_unchanged(self):
        rows = self._rows(("One.", False), ("PIN.", True))
        out = compose_locked("One.\n\nPIN.", rows)
        self.assertFalse(out["changed"])
        self.assertEqual(out["text"], "One.\n\nPIN.")


try:
    from flask import Flask, request

    from routes.v2 import explore_ideal_text as v2_explore_ideal_text
    from services.db import db
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    Flask = None
    request = None
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
    """Legacy request shapes are adapted to the one atomic CAS writer."""

    def setUp(self):
        self.app = Flask(__name__)

    def _put(self, body, *, edit_ok=True, parts_ok=True, existing=None):
        with self.app.test_request_context(json=body):
            request.user_id = "u1"
            with patch("routes.v2.explore_ideal_text._arc_owned_by_caller",
                       return_value=(True, [])), \
                 patch.object(db.ideal_text, "get_coach_arc_ideal_text",
                              return_value=_row()), \
                 patch.object(db, "get_ideal_text_parts",
                              return_value=existing or [], create=True), \
                 patch.object(
                     db, "compare_and_set_user_ideal_edit",
                     return_value={
                         "ideal_text_user_edit_contract_version":
                             "ideal-text-user-edit-cas-v2",
                         "saved": True, "arc_id": ARC,
                         "source_document_version": 3,
                         "dataset_eligible": False,
                     } if edit_ok and parts_ok else None,
                 ) as m_parts:
                out = v2_explore_ideal_text.v2_explore_put_ideal_user_edit.__wrapped__(ARC)
                resp, status = out if isinstance(out, tuple) else (out, 200)
                return resp.get_json(), status, m_parts


    def test_explicit_false_reopens_the_paragraph(self):
        # Current clients carry the complete version state. A changed locked
        # Paragraph becomes a working copy until the user commits it again.
        a = _id()
        _b, _s, m = self._put(
            {"text": "one", "version": 3,
             "parts": [{"id": a, "text": "one", "locked": False}]},
            existing=[{"id": a, "ord": 0, "text": "one",
                       "locked_at": "2026-08-01T00:00:00Z"}])
        self.assertIs(
            m.call_args.kwargs["desired_parts_lineage"][0]["locked"], False
        )


    def test_a_non_boolean_lock_is_refused(self):
        _b, status, m = self._put({
            "text": "one", "version": 3,
            "parts": [{"id": _id(), "text": "one", "locked": "yes"}]})
        self.assertEqual(status, 400)
        m.assert_not_called()


    def test_a_malformed_part_is_a_400_and_writes_NOTHING(self):
        for parts in ([{"id": "not-a-uuid", "text": "one\n\ntwo"}],
                      [{"id": _id()}],
                      "nope"):
            _b, status, m = self._put({"text": "one\n\ntwo", "version": 3,
                                       "parts": parts})
            self.assertEqual(status, 400, parts)
            m.assert_not_called()


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class SeedOnLock(unittest.TestCase):
    """SPEC-lockin-loop §2 — the lock PUT adopts the client's parts list when
    no usable identity is stored.

    The founder's DoD locks a paragraph the student never manually edited
    (record → accept a chip → "Lock it"), and an unedited document stores no
    parts — without the seed, that exact flow 409s forever. The trust model is
    the user-edit PUT's, unchanged: client mints, server validates and stores.
    """

    PA, PB = "11111111-1111-4111-8111-111111111111", \
             "22222222-2222-4222-8222-222222222222"
    DOC = "First part words.\n\nSecond part words."

    def setUp(self):
        self.app = Flask(__name__)

    def _seed(self):
        return [{"id": self.PA, "text": "First part words."},
                {"id": self.PB, "text": "Second part words."}]

    def _put(self, body, *, stored=None, changes=None, replace_ok=True,
             part_id=None):
        with self.app.test_request_context(json=body):
            request.user_id = "u1"
            with patch("routes.v2.explore_ideal_text._arc_owned_by_caller",
                       return_value=(True, [])), \
                 patch.object(db, "get_ideal_text_parts",
                              return_value=stored or [], create=True), \
                 patch.object(db, "replace_ideal_text_parts",
                              return_value=replace_ok,
                              create=True) as m_replace, \
                 patch("routes.v2.explore_ideal_text._tracked_changes_block",
                       return_value={"changes": changes or []}), \
                 patch.object(db, "set_ideal_text_part_lock",
                              return_value=True, create=True) as m_write:
                out = v2_explore_ideal_text.v2_explore_set_part_lock.__wrapped__(
                    "a1", part_id or self.PA)
                resp, status = out if isinstance(out, tuple) else (out, 200)
                return resp.get_json(), status, m_replace, m_write


    def test_a_seed_with_open_feedback_locks(self):
        """R3 retired (founder 2026-10-05): a seeded document with open
        feedback on the part locks too."""
        pending = [{"id": "c1", "kind": "replace",
                    "span": {"start": 0, "end": 17}}]
        _b, status, _r, m_write = self._put(
            {"locked": True, "text_echo": self.DOC, "parts": self._seed()},
            changes=pending)
        self.assertEqual(status, 200)
        m_write.assert_called_once()


if __name__ == "__main__":
    unittest.main()


class TestAnchorRule(unittest.TestCase):
    """SPEC §12.1 (founder 2026-08-14): 'Typed words are invincible.' A
    locked part is a hard immutable anchor; the machine aligns around it,
    never through it — and its words can never serve twice."""

    def _rows(self, *specs):
        return [{"id": _id(), "ord": i, "text": t,
                 "locked_at": "2026-08-14T00:00:00Z" if lk else None}
                for i, (t, lk) in enumerate(specs)]


    def test_twin_locks_with_one_machine_copy_pin(self):
        # Two locks with identical text, one machine copy: the first
        # anchors, the second cannot — mixed → pinned, never a guess about
        # which twin the machine kept.
        rows = self._rows(("SAME WORDS.", True), ("SAME WORDS.", True))
        out = compose_locked("SAME WORDS.", rows)
        self.assertEqual(out["text"], "SAME WORDS.\n\nSAME WORDS.")
        self.assertEqual(len([p for p in out["parts"] if p["locked"]]), 2)

    def test_every_branch_upholds_the_invariant(self):
        # Whatever path composes, every locked part reaches the output
        # exactly once with id and text intact.
        cases = [
            ("One NEW.\n\nMachine rework.\n\nThree NEW.",       # positional
             self._rows(("One old.", False), ("PINNED.", True),
                        ("Three old.", False))),
            ("Just one paragraph now.",                          # flat diff
             self._rows(("Old a.", False), ("PINNED.", True),
                        ("Old b.", False))),
            ("PINNED.\n\nNew tail.",                             # anchored
             self._rows(("PINNED.", True), ("Old tail.", False))),
        ]
        for base, rows in cases:
            want = [(r["id"], r["text"]) for r in rows if r["locked_at"]]
            out = compose_locked(base, rows)
            got = [(p["id"], p["text"]) for p in out["parts"]
                   if p["locked"]]
            self.assertEqual(got, want, f"base={base!r}")


class TestPinnedParts(unittest.TestCase):
    """§12.1's failed-rebuild fallback for the route: when compose RAISES,
    the previous composed state serves — never the raw machine text with
    every lock invisible."""


    def test_nothing_to_pin_is_none(self):
        self.assertIsNone(pinned_parts([]))
        self.assertIsNone(pinned_parts(None))
        self.assertIsNone(pinned_parts(
            [{"id": _id(), "ord": 0, "text": "Open.", "locked_at": None}]))


# ---------------------------------------------------------------------------
#  AN EDIT ALONE MAKES A PARAGRAPH REVIEWED (founder 2026-09-21).
#
#  The page shows an untouched paragraph grey with no mark, and counts an
#  answered bookmark, a rooting phrase or a lock cycle as a review. It cannot
#  see an edit on its own — only the server also holds the generation's head
#  snapshot — so the comparison rides on the parts block as one boolean.
# ---------------------------------------------------------------------------

class TheEditedFlag(unittest.TestCase):


    def test_changed_words_are_edited_and_only_those(self):
        from services.ideal_text_parts import mark_edited
        generated = "We started small.\n\nThen we grew."
        served = [{"id": "a", "ord": 0, "text": "We started in a garage."},
                  {"id": "b", "ord": 1, "text": "Then we grew."}]
        out = mark_edited(served, generated)
        self.assertEqual([p["edited"] for p in out], [True, False])


    def test_no_generated_text_means_no_flag_at_all(self):
        from services.ideal_text_parts import mark_edited
        served = [{"id": "a", "ord": 0, "text": "Anything."}]
        for generated in (None, "", "   "):
            out = mark_edited(served, generated)
            self.assertEqual(out, served)
            self.assertNotIn("edited", out[0])
