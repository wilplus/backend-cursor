"""Ranking eval set (services/ranking_eval.py). Pure — no DB, no LLM, no
network; runs in the lean env (no numpy/flask).

The two properties that matter most here:
  • DRIFT-PROOFING — machine picks come from the REAL select_best_per_slide
    / power_score, so a production ranking change moves the eval with it.
  • THE BLIND FENCE — the rater's sheet carries no machine read of any
    kind (allowlist-constructed; asserted here as a hard test).

Run: python3 -m unittest test_ranking_eval
"""
from __future__ import annotations

import csv
import io
import unittest

from services.ranking_eval import (
    BLIND_COLUMNS, KEY_COLUMNS, agreement_report, attach_bands,
    attach_machine_picks, band_for_case, blind_rows, build_cases,
    build_session_candidates, draw_sample, key_rows, parse_key_rows,
    parse_labels,
)


def _metrics(overall=None, slide=None, topic=None):
    m: dict = {}
    if overall is not None:
        m["overall_score"] = overall
    if slide is not None:
        m["slide_stickiness"] = {"composite": slide}
    if topic is not None:
        m["stickiness"] = {"composite": topic}
    return m


def _snip(sid, offset_ms, transcript, **mk):
    return {
        "id": sid,
        "start_offset_ms": offset_ms,
        "duration_ms": 3000,
        "transcript": transcript,
        "audio_ref": f"audio/{sid}.mp3",
        "metrics": _metrics(**mk),
    }


_SESSION = {
    "id": "sess-alpha-0001",
    "take_index": 1,
    "intake_context": {
        "slides": [
            {"title": "Vision", "body": "Where we are going"},
            {"title": "Numbers", "body": "The quarter in figures"},
        ],
        "slide_advances": [
            {"index": 0, "t_ms": 0},
            {"index": 1, "t_ms": 10000},
        ],
    },
}


def _cand(sid, slide, transcript, *, overall=None, stick=None, topic=None,
          session="sess-alpha-0001"):
    """A pre-built candidate (bypasses build_session_candidates) for the
    case/report tests."""
    return {
        "slide_index": slide,
        "snippet_id": sid,
        "session_id": session,
        "transcript": transcript,
        "transcript_source": "raw",
        "audio_ref": f"audio/{sid}.mp3",
        "start_offset_ms": 1000,
        "duration_ms": 2000,
        "take_index": 1,
        "direction": None,
        "coach_direction": None,
        "breakthrough": False,
        "activation": overall,
        "slide_stickiness": stick,
        "topic_stickiness": topic,
        "voice_confidence": None,
        "tag": None,
    }


COMPLETE_LO = "This is a complete sentence about the plan."     # score ↓
INCOMPLETE_HI = "and this is the key point about growth"        # score ↑


class CandidateConstructionTests(unittest.TestCase):
    def test_fields_mirror_production_inputs(self):
        snips = [
            _snip("a1", 2000, COMPLETE_LO, overall=0.5, slide=0.4, topic=0.6),
            _snip("a2", 12000, "Numbers went up a lot this quarter.",
                  overall=0.8, slide=0.7, topic=0.9),
        ]
        cands = build_session_candidates(_SESSION, snips, {}, {})
        self.assertEqual(len(cands), 2)
        c1, c2 = cands
        self.assertEqual(c1["slide_index"], 0)   # 2000ms → slide 0
        self.assertEqual(c2["slide_index"], 1)   # 12000ms → slide 1
        self.assertEqual(c1["activation"], 0.5)
        self.assertEqual(c1["slide_stickiness"], 0.4)
        self.assertEqual(c1["topic_stickiness"], 0.6)
        self.assertIsNone(c1["tag"])             # labels live in drafts
        self.assertIsNone(c1["voice_confidence"])  # flag off → no-op term
        self.assertFalse(c1["breakthrough"])     # no coach challenge label
        self.assertEqual(c1["transcript_source"], "raw")

    def test_coach_correction_is_the_verbatim(self):
        snips = [_snip("a1", 2000, "raw whisper words", overall=0.5)]
        cands = build_session_candidates(
            _SESSION, snips, {}, {"a1": "The coach corrected line."})
        self.assertEqual(cands[0]["transcript"], "The coach corrected line.")
        self.assertEqual(cands[0]["transcript_source"], "corrected")

    def test_deckless_session_yields_slide_index_none(self):
        sess = {"id": "s2", "take_index": 1, "intake_context": {}}
        cands = build_session_candidates(
            sess, [_snip("b1", 2000, "Some spoken words here.")], {}, {})
        self.assertIsNone(cands[0]["slide_index"])


class CaseBuildingTests(unittest.TestCase):
    def test_grouping_and_counted_exclusions(self):
        cands = [
            # rankable pair on slide 0
            _cand("a", 0, COMPLETE_LO, overall=0.5, stick=0.5),
            _cand("b", 0, INCOMPLETE_HI, overall=0.9, stick=0.5),
            # deckless
            _cand("c", None, "Deckless words spoken aloud."),
            # singleton slide
            _cand("d", 1, "Only line on this slide here."),
            # empty transcript
            _cand("e", 0, "   "),
        ]
        cases, stats = build_cases(cands)
        self.assertEqual(len(cases), 1)
        self.assertEqual(stats["deckless_skipped"], 1)
        self.assertEqual(stats["singleton_skipped"], 1)
        self.assertEqual(stats["empty_transcript_skipped"], 1)
        self.assertEqual(stats["oversize_skipped"], 0)

    def test_oversize_case_excluded_whole_never_truncated(self):
        cands = [
            _cand(f"s{i}", 0, f"Line number {i} is fully complete.",
                  overall=0.5, stick=0.5)
            for i in range(3)
        ]
        cases, stats = build_cases(cands, max_candidates=2)
        self.assertEqual(cases, [])
        self.assertEqual(stats["oversize_skipped"], 1)


class MachinePickAndBandTests(unittest.TestCase):
    def _gate_case(self):
        cands = [
            _cand("lo", 0, COMPLETE_LO, overall=0.5, stick=0.5),
            _cand("hi", 0, INCOMPLETE_HI, overall=0.9, stick=0.5),
        ]
        cases, _ = build_cases(cands)
        attach_machine_picks(
            cases, {"sess-alpha-0001": cands})
        attach_bands(cases)
        return cases[0]

    def test_sentence_gate_decides_and_band_says_so(self):
        case = self._gate_case()
        # Production picks the COMPLETE lower-scored line — via the real
        # select_best_per_slide, not a reimplementation.
        picks = {c["snippet_id"]: c["shipped_local_pick"]
                 for c in case["candidates"]}
        self.assertTrue(picks["lo"])
        self.assertFalse(picks["hi"])
        self.assertEqual(case["band"], "gate_decided")

    def test_close_and_clear_bands(self):
        close = [
            _cand("a", 0, "First complete sentence about this.",
                  overall=0.50, stick=0.5),
            _cand("b", 0, "Second complete sentence about this.",
                  overall=0.55, stick=0.5),
        ]
        cases, _ = build_cases(close)
        attach_machine_picks(cases, {"sess-alpha-0001": close})
        self.assertEqual(band_for_case(cases[0]), "close")

        clear = [
            _cand("a", 0, "First complete sentence about this.",
                  overall=0.2, stick=0.2),
            _cand("b", 0, "Second complete sentence about this.",
                  overall=0.9, stick=0.9),
        ]
        cases, _ = build_cases(clear)
        attach_machine_picks(cases, {"sess-alpha-0001": clear})
        self.assertEqual(band_for_case(cases[0]), "clear")

    def test_assembly_pick_diverges_under_cross_slide_dedupe(self):
        dup_text = "Great line one indeed works everywhere."
        session = [
            _cand("s0", 0, dup_text, overall=0.9, stick=0.9),
            _cand("s1a", 1, dup_text, overall=0.9, stick=0.9),
            _cand("s1b", 1, "Another decent complete sentence here.",
                  overall=0.4, stick=0.4),
        ]
        cases, _ = build_cases(session)  # slide 1 is the only 2+ case
        self.assertEqual(len(cases), 1)
        attach_machine_picks(cases, {"sess-alpha-0001": session})
        by_id = {c["snippet_id"]: c for c in cases[0]["candidates"]}
        # Local: the dup wins slide 1. Assembly: slide 0 took the text
        # first, so slide 1 falls to its runner-up.
        self.assertTrue(by_id["s1a"]["shipped_local_pick"])
        self.assertFalse(by_id["s1a"]["shipped_assembly_pick"])
        self.assertTrue(by_id["s1b"]["shipped_assembly_pick"])


class SheetTests(unittest.TestCase):
    def _sampled(self, seed=7):
        cands = [
            _cand("lo", 0, COMPLETE_LO, overall=0.5, stick=0.5),
            _cand("hi", 0, INCOMPLETE_HI, overall=0.9, stick=0.5),
        ]
        cases, _ = build_cases(cands)
        attach_machine_picks(cases, {"sess-alpha-0001": cands})
        attach_bands(cases)
        return draw_sample(cases, per_band=2, seed=seed)

    def test_blind_sheet_is_allowlist_only(self):
        rows = blind_rows(
            self._sampled(),
            {"sess-alpha-0001": _SESSION["intake_context"]["slides"]})
        self.assertTrue(rows)
        for r in rows:
            self.assertEqual(set(r), set(BLIND_COLUMNS))
            for leak in ("score", "band", "take_index", "direction",
                         "activation", "snippet_id", "shipped_local_pick"):
                self.assertNotIn(leak, r)
        self.assertEqual(rows[0]["slide_title"], "Vision")

    def test_key_carries_the_machine_side(self):
        rows = key_rows(self._sampled())
        for r in rows:
            self.assertEqual(set(r), set(KEY_COLUMNS))
        self.assertEqual(
            sum(1 for r in rows if r["shipped_local_pick"]), 1)

    def test_draw_is_deterministic_per_seed(self):
        a = [(c["case_id"], [x["candidate"] for x in c["candidates"]])
             for c in self._sampled(seed=42)]
        b = [(c["case_id"], [x["candidate"] for x in c["candidates"]])
             for c in self._sampled(seed=42)]
        self.assertEqual(a, b)

    def test_sheet_and_key_join_on_case_and_letter(self):
        sample = self._sampled()
        sheet = {(r["case_id"], r["candidate"]): r["transcript"]
                 for r in blind_rows(sample, {})}
        key = {(r["case_id"], r["candidate"]): r["snippet_id"]
               for r in key_rows(sample)}
        self.assertEqual(set(sheet), set(key))


class ScoringTests(unittest.TestCase):
    def _label_and_key(self, human_picks_incomplete=True):
        sample = SheetTests()._sampled()
        krows = key_rows(sample)
        # Human disagrees with the sentence gate: picks the higher-scored
        # incomplete line.
        target = "hi" if human_picks_incomplete else "lo"
        letter = next(r["candidate"] for r in krows
                      if r["snippet_id"] == target)
        labels = {krows[0]["case_id"]: letter}
        return labels, krows

    def test_parse_labels_validates_exactly_one(self):
        rows = [
            {"case_id": "c1", "candidate": "A", "is_best": "1"},
            {"case_id": "c1", "candidate": "B", "is_best": ""},
            {"case_id": "c2", "candidate": "A", "is_best": "1"},
            {"case_id": "c2", "candidate": "B", "is_best": "x"},
            {"case_id": "c3", "candidate": "A", "is_best": ""},
        ]
        labels, problems = parse_labels(rows)
        self.assertEqual(labels, {"c1": "A"})
        self.assertEqual(len(problems), 2)  # c2 double, c3 none

    def test_gate_disagreement_splits_shipped_and_variant(self):
        labels, krows = self._label_and_key(human_picks_incomplete=True)
        report = agreement_report(labels, krows)
        self.assertEqual(
            report["variants"]["shipped_local"]["overall"]["agree"], 0)
        self.assertEqual(
            report["variants"]["no_sentence_gate"]["overall"]["agree"], 1)
        self.assertEqual(len(report["disagreements"]), 1)
        self.assertEqual(report["disagreements"][0]["band"], "gate_decided")

    def test_debiased_coverage_flips_the_double_counted_winner(self):
        # A wins shipped on slide coverage entering twice; B carries the
        # topic. Debiased (topic = 2·overall − slide) prefers B.
        cands = [
            _cand("A", 0, "Slide heavy complete sentence right here.",
                  overall=0.7, stick=1.0),   # topic 0.4
            _cand("B", 0, "Topic heavy complete sentence right here also.",
                  overall=0.6, stick=0.2),   # topic 1.0
        ]
        cases, _ = build_cases(cands)
        attach_machine_picks(cases, {"sess-alpha-0001": cands})
        attach_bands(cases)
        sample = draw_sample(cases, per_band=1, seed=1)
        krows = key_rows(sample)
        letter_b = next(r["candidate"] for r in krows
                        if r["snippet_id"] == "B")
        report = agreement_report({krows[0]["case_id"]: letter_b}, krows)
        self.assertEqual(
            report["variants"]["shipped_local"]["overall"]["agree"], 0)
        self.assertEqual(
            report["variants"]["debiased_coverage"]["overall"]["agree"], 1)

    def test_key_csv_roundtrip_scores_identically(self):
        labels, krows = self._label_and_key()
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=list(KEY_COLUMNS))
        w.writeheader()
        w.writerows(krows)
        buf.seek(0)
        reparsed = parse_key_rows(list(csv.DictReader(buf)))
        self.assertEqual(agreement_report(labels, krows),
                         agreement_report(labels, reparsed))

    def test_labeled_case_missing_from_key_is_counted(self):
        _, krows = self._label_and_key()
        report = agreement_report({"nope-s00": "A"}, krows)
        self.assertEqual(report["cases_unmatched"], 1)
        self.assertEqual(report["cases_labeled"], 0)


if __name__ == "__main__":
    unittest.main()
