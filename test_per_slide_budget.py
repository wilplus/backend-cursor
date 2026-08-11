"""THE BUDGET IS COUNTED PER SLIDE, UP TO 2 (founder 2026-08-11).

It was ≤3 per TAKE, set when a whole talk arrived as one chunk — three marks
in one wall of text. The document now carries one paragraph per slide, and
the paragraph IS the chunk the student decides on, so a per-take cap counted
in a unit the surface no longer has: three notes spread over a ten-slide deck
leaves seven slides visibly empty, and the reader meets that emptiness slide
by slide.

What these tests hold is that EVERY counting rule moved to the same unit. A
budget counted per slide beside a mix cap counted per document is not a
smaller version of the old system — it is two rules disagreeing about what
"the mix" is, and the disagreement shows up as slides that silently get
nothing.

Run: python3 -m unittest test_per_slide_budget
"""
from __future__ import annotations

import unittest

from services import intervention_candidates as ic
from services import manager_engine as me
from services.intervention_spend import (
    paragraph_index_at, spent_by_paragraph,
)

# Three paragraphs of ~250 chars — one per slide, which is what the document
# builder now emits. Each paragraph uses its OWN vocabulary, because spent
# slots are placed by matching their quote and a phrase shared between two
# slides would land on the first (QuoteAmbiguityTests pins that).
_P0 = "alpha bravo charlie delta echo foxtrot golf hotel india juliet " * 4
_P1 = "kilo lima mike november oscar papa quebec romeo sierra tango " * 4
_P2 = "uniform victor whiskey xray yankee zulu zero one two three " * 4
PARAS = [_P0.strip(), _P1.strip(), _P2.strip()]
DOC = "\n\n".join(PARAS)


def _at(para: int, within: int = 0) -> int:
    """Char offset inside paragraph `para` of DOC."""
    base = sum(len(p) + 2 for p in PARAS[:para])
    return base + within


def _change(cid, start, *, kind="replace", end=None):
    end = start + 10 if end is None else end
    return {"id": cid, "snippet_id": f"s{cid}", "take_session_id": "t1",
            "kind": kind, "source": "polish",
            "span": {"start": start, "end": end},
            "quote": DOC[start:end], "proposed_text": "y"}


class ParagraphIndexTests(unittest.TestCase):
    def test_offsets_land_in_the_right_paragraph(self):
        self.assertEqual(paragraph_index_at(DOC, 0), 0)
        self.assertEqual(paragraph_index_at(DOC, _at(1, 5)), 1)
        self.assertEqual(paragraph_index_at(DOC, _at(2, 5)), 2)

    def test_a_document_with_no_breaks_is_ONE_group(self):
        # The old flat cap, reached by the same code path — a take with no
        # provable slide structure must not be chopped into invented units.
        self.assertEqual(paragraph_index_at("no breaks here at all", 12), 0)

    def test_junk_reads_as_the_first_paragraph_rather_than_raising(self):
        for bad in (None, "", "x"):
            self.assertEqual(paragraph_index_at(bad, 5), 0)
        self.assertEqual(paragraph_index_at(DOC, None), 0)


class PerSlideBudgetTests(unittest.TestCase):
    def test_each_slide_gets_its_OWN_two(self):
        # Six candidates, two slides. Per take this served 2 in total and the
        # second slide showed nothing; per slide it serves 2 + 2.
        pool = [_change(f"a{i}", _at(0, i * 20)) for i in range(3)]
        pool += [_change(f"b{i}", _at(1, i * 20)) for i in range(3)]
        out = ic.select(pool, served_text=DOC)["changes"]
        paras = [paragraph_index_at(DOC, c["span"]["start"]) for c in out]
        self.assertEqual(len(out), 4)
        self.assertEqual(paras.count(0), 2)
        self.assertEqual(paras.count(1), 2)

    def test_a_slide_never_takes_more_than_two(self):
        pool = [_change(f"a{i}", _at(0, i * 20)) for i in range(5)]
        out = ic.select(pool, served_text=DOC)["changes"]
        self.assertEqual(len(out), 2)

    def test_WITHOUT_the_document_the_flat_cap_is_unchanged(self):
        # Guests and any caller with no served text keep today's behaviour.
        pool = [_change(f"a{i}", _at(0, i * 20)) for i in range(3)]
        pool += [_change(f"b{i}", _at(1, i * 20)) for i in range(3)]
        self.assertEqual(len(ic.select(pool)["changes"]), me.BUDGET_CEILING)

    def test_spend_on_one_slide_does_not_touch_another(self):
        pool = [_change(f"a{i}", _at(0, i * 20)) for i in range(3)]
        pool += [_change(f"b{i}", _at(1, i * 20)) for i in range(3)]
        out = ic.select(pool, served_text=DOC,
                        spent_by_paragraph={0: 2})["changes"]
        paras = [paragraph_index_at(DOC, c["span"]["start"]) for c in out]
        self.assertEqual(paras, [1, 1])          # slide 0 is spent; 1 is not

    def test_a_fully_spent_slide_serves_nothing_there(self):
        pool = [_change(f"a{i}", _at(0, i * 20)) for i in range(3)]
        out = ic.select(pool, served_text=DOC,
                        spent_by_paragraph={0: 9})["changes"]
        self.assertEqual(out, [])


class MixCapUnitTests(unittest.TestCase):
    """The cap has to be counted in the budget's unit or it starves slides."""

    def test_a_rewrite_heavy_slide_does_not_starve_another_slide(self):
        # Document-wide, the REWRITE cap would keep one rewrite for the WHOLE
        # deck and slide 1 would serve nothing at all.
        pool = [_change(f"a{i}", _at(0, i * 20)) for i in range(3)]
        pool += [_change("a-bold", _at(0, 80), kind="bold")]
        pool += [_change(f"b{i}", _at(1, i * 20)) for i in range(3)]
        out = ic.select(pool, served_text=DOC)["changes"]
        paras = [paragraph_index_at(DOC, c["span"]["start"]) for c in out]
        self.assertEqual(paras.count(1), 2)
        self.assertGreater(paras.count(0), 0)

    def test_the_cap_still_reserves_the_last_slot_for_a_mix(self):
        # Appendix C's rule, at the new ceiling: an accent proposing beside
        # rewrites still lands. Written against BUDGET_CEILING so the two
        # cannot drift apart again.
        pool = [_change(f"a{i}", _at(0, i * 20)) for i in range(4)]
        accent = _change("a-bold", _at(0, 90), kind="bold")
        accent["quote"] = "land these words"
        out = ic.select(pool + [accent], served_text=DOC)["changes"]
        self.assertIn("bold", [c["kind"] for c in out])
        self.assertEqual(
            ic.TYPE_ROWS["REWRITE"]["serve_cap"], me.BUDGET_CEILING - 1)


class SpentByParagraphTests(unittest.TestCase):
    class _Db:
        def __init__(self, rows):
            self._rows = rows

        def list_spent_intervention_decisions(self, arc, take):
            return self._rows

    def test_a_spent_slot_is_placed_by_its_own_words(self):
        quote = DOC[_at(1, 10):_at(1, 24)]
        db = self._Db([{"quote": quote}])
        self.assertEqual(spent_by_paragraph(db, "arc", "t1", DOC), {1: 1})

    def test_a_quote_no_longer_in_the_document_counts_against_NOTHING(self):
        # Baked, coach-corrected or retyped. Drop-never-guess, and the error
        # runs toward offering feedback rather than silently withholding it.
        db = self._Db([{"quote": "words that are not in this document"}])
        self.assertEqual(spent_by_paragraph(db, "arc", "t1", DOC), {})

    def test_rows_predating_the_texts_migration_are_skipped(self):
        db = self._Db([{"quote": None}, {"quote": "   "}])
        self.assertEqual(spent_by_paragraph(db, "arc", "t1", DOC), {})

    def test_a_read_failure_degrades_to_an_empty_map_not_a_dark_serve(self):
        class _Boom:
            def list_spent_intervention_decisions(self, *a, **k):
                raise RuntimeError("no table")
        self.assertEqual(spent_by_paragraph(_Boom(), "arc", "t1", DOC), {})


class QuoteAmbiguityTests(unittest.TestCase):
    """THE KNOWN LIMIT of placing a spent slot by its words.

    The ledger has no slide column, so the quote is what puts a spent slot on
    a slide. `find` takes the FIRST occurrence — so a phrase the speaker used
    on two slides charges the earlier one. Pinned rather than hidden: the
    effect is bounded (one slide under-serves by one, its twin over-serves by
    one, both inside the ≤2) and the alternative is a migration plus a
    backfill of history that was never recorded. If it ever stops being
    acceptable, the fix is a `slide_index` column written at decide time —
    not a cleverer matcher, which would guess."""

    class _Db:
        def __init__(self, rows):
            self._rows = rows

        def list_spent_intervention_decisions(self, arc, take):
            return self._rows

    def test_a_phrase_on_two_slides_charges_the_EARLIER_one(self):
        shared = "the very same phrase"
        doc = f"{_P0.strip()} {shared}\n\n{_P1.strip()} {shared}"
        db = self._Db([{"quote": shared}])
        self.assertEqual(spent_by_paragraph(db, "arc", "t1", doc), {0: 1})


class ArmRowsTests(unittest.TestCase):
    def test_a_candidate_BEATEN_BY_THE_BUDGET_still_gets_an_arm_row(self):
        # It had none: arm_rows walked selected / withheld / control /
        # rejected, and a budget loser is in none of those — so "one row per
        # CONSIDERED dimension" quietly did not hold. Invisible at a cap of
        # 3; routine at 2 per slide.
        dims = ("d0", "d1", "d2", "d3")
        state = {d: me.APPRENTICE for d in dims}
        user = me.UserState(user_id="u0", state_by_dimension=state)
        cands = [me.Candidate(ref=str(i), dimension=d, grade="A",
                              deviation=4.0 - i * 0.1, ppv=0.9,
                              anchor=(i * 10.0, i * 10.0 + 1))
                 for i, d in enumerate(dims)]
        out = me.arbitrate(cands, user, session_id="s1")
        rows = me.arm_rows(out, session_id="s1", user_id="u0")
        self.assertEqual(sorted(r["dimension_id"] for r in rows),
                         sorted(dims))


if __name__ == "__main__":
    unittest.main()
