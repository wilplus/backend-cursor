"""Ranking eval set (services/ranking_eval.py). Pure — no DB, no LLM, no
network; runs in the lean env (no numpy/flask).

The properties that matter most:
  • DRIFT-PROOFING — machine picks come from the REAL select_best_per_slide
    / power_score, so a production ranking change moves the eval with it.
  • THE BLIND FENCE — the rater surface (sheet + page) carries no machine
    read of any kind, and repeats are indistinguishable from fresh cases.
  • THE RATIFIED RULES — R0 ceiling gating, R1-R3 duel verdicts with the
    2-of-3-on-≥6 standard, none-fit exclusion, R5 floor.

Run: python3 -m unittest test_ranking_eval
"""
from __future__ import annotations

import csv
import io
import unittest

from services.ranking_eval import (
    BLIND_COLUMNS, KEY_COLUMNS, agreement_report, attach_bands,
    attach_machine_picks, band_for_case, blind_rows, build_cases,
    build_session_candidates, draw_sample, key_rows, page_payload,
    parse_answers, parse_key_rows, render_labeling_page, run_id_for,
)


def _metrics(overall=None, slide=None, topic=None, vc_score=None):
    m: dict = {}
    if overall is not None:
        m["overall_score"] = overall
    if slide is not None:
        m["slide_stickiness"] = {"composite": slide}
    if topic is not None:
        m["stickiness"] = {"composite": topic}
    if vc_score is not None:
        m["voice_confidence"] = {"score": vc_score, "band": "x", "cues": []}
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
          vc_stamped=None, session="sess-alpha-0001"):
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
        "voice_confidence": None,          # served term: flag OFF
        "voice_confidence_stamped": vc_stamped,
        "tag": None,
    }


COMPLETE_LO = "This is a complete sentence about the plan."     # score ↓
INCOMPLETE_HI = "and this is the key point about growth"        # score ↑


def _built(cands, *, per_band=2, seed=7, repeats=0):
    cases, _ = build_cases(cands)
    attach_machine_picks(cases, {"sess-alpha-0001": cands})
    attach_bands(cases)
    return draw_sample(cases, per_band=per_band, seed=seed, repeats=repeats)


class CandidateConstructionTests(unittest.TestCase):
    def test_fields_mirror_production_inputs(self):
        snips = [
            _snip("a1", 2000, COMPLETE_LO, overall=0.5, slide=0.4,
                  topic=0.6, vc_score=0.42),
            _snip("a2", 12000, "Numbers went up a lot this quarter.",
                  overall=0.8, slide=0.7, topic=0.9),
        ]
        cands = build_session_candidates(_SESSION, snips, {}, {})
        c1, c2 = cands
        self.assertEqual(c1["slide_index"], 0)
        self.assertEqual(c2["slide_index"], 1)
        self.assertEqual(c1["activation"], 0.5)
        self.assertEqual(c1["slide_stickiness"], 0.4)
        self.assertEqual(c1["topic_stickiness"], 0.6)
        self.assertIsNone(c1["tag"])
        self.assertIsNone(c1["voice_confidence"])   # serving flag off
        self.assertEqual(c1["voice_confidence_stamped"], 0.42)  # stamp read
        self.assertIsNone(c2["voice_confidence_stamped"])       # unstamped
        self.assertFalse(c1["breakthrough"])

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
            _cand("a", 0, COMPLETE_LO, overall=0.5, stick=0.5),
            _cand("b", 0, INCOMPLETE_HI, overall=0.9, stick=0.5),
            _cand("c", None, "Deckless words spoken aloud."),
            _cand("d", 1, "Only line on this slide here."),
            _cand("e", 0, "   "),
        ]
        cases, stats = build_cases(cands)
        self.assertEqual(len(cases), 1)
        self.assertEqual(stats["deckless_skipped"], 1)
        self.assertEqual(stats["singleton_skipped"], 1)
        self.assertEqual(stats["empty_transcript_skipped"], 1)

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
    def test_sentence_gate_decides_and_band_says_so(self):
        cands = [
            _cand("lo", 0, COMPLETE_LO, overall=0.5, stick=0.5),
            _cand("hi", 0, INCOMPLETE_HI, overall=0.9, stick=0.5),
        ]
        cases, _ = build_cases(cands)
        attach_machine_picks(cases, {"sess-alpha-0001": cands})
        attach_bands(cases)
        picks = {c["snippet_id"]: c["shipped_local_pick"]
                 for c in cases[0]["candidates"]}
        self.assertTrue(picks["lo"])    # the REAL selector's choice
        self.assertFalse(picks["hi"])
        self.assertEqual(cases[0]["band"], "gate_decided")

    def test_close_and_clear_bands(self):
        close = [
            _cand("a", 0, "First complete sentence about this.",
                  overall=0.50, stick=0.5),
            _cand("b", 0, "Second complete sentence about this.",
                  overall=0.55, stick=0.5),
        ]
        cases, _ = build_cases(close)
        self.assertEqual(band_for_case(cases[0]), "close")

        clear = [
            _cand("a", 0, "First complete sentence about this.",
                  overall=0.2, stick=0.2),
            _cand("b", 0, "Second complete sentence about this.",
                  overall=0.9, stick=0.9),
        ]
        cases, _ = build_cases(clear)
        self.assertEqual(band_for_case(cases[0]), "clear")

    def test_assembly_pick_diverges_under_cross_slide_dedupe(self):
        dup_text = "Great line one indeed works everywhere."
        session = [
            _cand("s0", 0, dup_text, overall=0.9, stick=0.9),
            _cand("s1a", 1, dup_text, overall=0.9, stick=0.9),
            _cand("s1b", 1, "Another decent complete sentence here.",
                  overall=0.4, stick=0.4),
        ]
        cases, _ = build_cases(session)
        attach_machine_picks(cases, {"sess-alpha-0001": session})
        by_id = {c["snippet_id"]: c for c in cases[0]["candidates"]}
        self.assertTrue(by_id["s1a"]["shipped_local_pick"])
        self.assertFalse(by_id["s1a"]["shipped_assembly_pick"])
        self.assertTrue(by_id["s1b"]["shipped_assembly_pick"])


class RepeatAndPageTests(unittest.TestCase):
    def _two_case_pool(self):
        return [
            _cand("lo", 0, COMPLETE_LO, overall=0.5, stick=0.5),
            _cand("hi", 0, INCOMPLETE_HI, overall=0.9, stick=0.5),
            _cand("x1", 1, "First complete sentence about numbers.",
                  overall=0.3, stick=0.3),
            _cand("x2", 1, "Second complete sentence about numbers.",
                  overall=0.9, stick=0.9),
        ]

    def test_repeats_are_cloned_to_the_end_and_marked_key_side_only(self):
        sample = _built(self._two_case_pool(), repeats=2)
        base = [c for c in sample if not c.get("repeat_of")]
        reps = [c for c in sample if c.get("repeat_of")]
        self.assertEqual(len(base), 2)
        self.assertEqual(len(reps), 2)
        # Appended AFTER every base case, ids suffixed, pointing at a base id.
        self.assertTrue(all(sample.index(r) >= len(base) for r in reps))
        for r in reps:
            self.assertTrue(r["case_id"].endswith("-r"))
            self.assertIn(r["repeat_of"], {b["case_id"] for b in base})
        # key.csv carries the marker; the page payload does NOT.
        krows = key_rows(sample)
        self.assertTrue(any(k["repeat_of"] for k in krows))
        payload = page_payload(sample, {}, {})
        for case in payload:
            self.assertEqual(set(case),
                             {"id", "slide_no", "title", "body", "cands"})

    def test_blind_sheet_is_allowlist_only(self):
        rows = blind_rows(
            _built(self._two_case_pool()),
            {"sess-alpha-0001": _SESSION["intake_context"]["slides"]},
            {"lo": "https://signed/lo.mp3"})
        self.assertTrue(rows)
        for r in rows:
            self.assertEqual(set(r), set(BLIND_COLUMNS))
            for leak in ("score", "band", "take_index", "direction",
                         "activation", "snippet_id", "shipped_local_pick",
                         "repeat_of"):
                self.assertNotIn(leak, r)

    def test_page_html_is_blind_and_self_contained(self):
        sample = _built(self._two_case_pool(), repeats=1)
        payload = page_payload(
            sample,
            {"sess-alpha-0001": _SESSION["intake_context"]["slides"]},
            {"lo": "https://signed/lo.mp3"})
        html = render_labeling_page(payload, run_id_for(sample))
        self.assertIn("https://signed/lo.mp3", html)
        self.assertIn(run_id_for(sample), html)
        # The disguise + the fence: no machine-side field name reaches HTML.
        for leak in ("repeat_of", "power_score", "shipped_local",
                     "gate_decided", '"band"', "snippet_id"):
            self.assertNotIn(leak, html)
        # No external resources — self-contained page.
        self.assertNotIn("<link", html.lower())
        self.assertNotIn("src=\"http", html.lower())

    def test_draw_is_deterministic_per_seed(self):
        a = [(c["case_id"], [x["candidate"] for x in c["candidates"]])
             for c in _built(self._two_case_pool(), seed=42, repeats=2)]
        b = [(c["case_id"], [x["candidate"] for x in c["candidates"]])
             for c in _built(self._two_case_pool(), seed=42, repeats=2)]
        self.assertEqual(a, b)


class AnswerParsingTests(unittest.TestCase):
    def test_parse_answers_validates(self):
        rows = [
            {"case_id": "c1", "picked": "a", "none_fit": "0", "why": ""},
            {"case_id": "c2", "picked": "B", "none_fit": "1",
             "why": "flat delivery everywhere"},
            {"case_id": "c2", "picked": "C", "none_fit": "", "why": ""},
            {"case_id": "c3", "picked": "", "none_fit": "", "why": ""},
        ]
        labels, none_fit, why, problems = parse_answers(rows)
        self.assertEqual(labels, {"c1": "A", "c2": "B"})
        self.assertEqual(none_fit, {"c2"})
        self.assertEqual(why, {"c2": "flat delivery everywhere"})
        self.assertEqual(len(problems), 2)  # dup c2 + pickless c3


class ScoringTests(unittest.TestCase):
    def _gate_run(self, repeats=0):
        sample = _built([
            _cand("lo", 0, COMPLETE_LO, overall=0.5, stick=0.5),
            _cand("hi", 0, INCOMPLETE_HI, overall=0.9, stick=0.5),
        ], repeats=repeats)
        return sample, key_rows(sample)

    def _letter(self, krows, cid, sid):
        return next(r["candidate"] for r in krows
                    if r["case_id"] == cid and r["snippet_id"] == sid)

    def test_gate_disagreement_splits_shipped_and_variant(self):
        sample, krows = self._gate_run()
        cid = sample[0]["case_id"]
        labels = {cid: self._letter(krows, cid, "hi")}
        report = agreement_report(labels, krows)
        clean = report["clean"]["variants"]
        self.assertEqual(clean["shipped_local"]["overall"]["agree"], 0)
        self.assertEqual(clean["no_sentence_gate"]["overall"]["agree"], 1)
        self.assertEqual(len(report["clean"]["disagreements"]), 1)
        d = report["duels"]["R1_no_sentence_gate"]
        self.assertEqual((d["differing"], d["wins"]), (1, 1))
        self.assertEqual(d["verdict"], "insufficient_data")  # < 6 decided

    def test_duel_clear_win_at_the_ratified_standard(self):
        # 6 gate-decided cases, human sides with the challenger every time.
        pool = []
        for i in range(6):
            pool += [
                _cand(f"lo{i}", i, f"Complete sentence number {i} here.",
                      overall=0.5, stick=0.5),
                _cand(f"hi{i}", i, f"and the incomplete point {i}",
                      overall=0.9, stick=0.5),
            ]
        cases, _ = build_cases(pool)
        attach_machine_picks(cases, {"sess-alpha-0001": pool})
        attach_bands(cases)
        sample = draw_sample(cases, per_band=6, seed=3, repeats=0)
        krows = key_rows(sample)
        labels = {c["case_id"]: self._letter(
            krows, c["case_id"],
            next(x["snippet_id"] for x in c["candidates"]
                 if x["snippet_id"].startswith("hi")))
            for c in sample}
        report = agreement_report(labels, krows)
        self.assertEqual(report["duels"]["R1_no_sentence_gate"]["verdict"],
                         "clear_win")

    def test_confidence_on_variant_flips_with_the_stamp(self):
        # Same content scores; B carries a strong stamped confidence read.
        cands = [
            _cand("A", 0, "Confidently flat complete sentence here.",
                  overall=0.6, stick=0.5, vc_stamped=-0.5),
            _cand("B", 0, "Confidently strong complete sentence here.",
                  overall=0.55, stick=0.5, vc_stamped=0.8),
        ]
        sample = _built(cands)
        krows = key_rows(sample)
        cid = sample[0]["case_id"]
        labels = {cid: self._letter(krows, cid, "B")}
        report = agreement_report(labels, krows)
        clean = report["clean"]["variants"]
        self.assertEqual(clean["shipped_local"]["overall"]["agree"], 0)
        self.assertEqual(clean["confidence_on"]["overall"]["agree"], 1)

    def test_debiased_coverage_flips_the_double_counted_winner(self):
        cands = [
            _cand("A", 0, "Slide heavy complete sentence right here.",
                  overall=0.7, stick=1.0),   # topic 0.4
            _cand("B", 0, "Topic heavy complete sentence right here also.",
                  overall=0.6, stick=0.2),   # topic 1.0
        ]
        sample = _built(cands)
        krows = key_rows(sample)
        cid = sample[0]["case_id"]
        labels = {cid: self._letter(krows, cid, "B")}
        report = agreement_report(labels, krows)
        clean = report["clean"]["variants"]
        self.assertEqual(clean["shipped_local"]["overall"]["agree"], 0)
        self.assertEqual(clean["debiased_coverage"]["overall"]["agree"], 1)

    def test_ceiling_from_disguised_repeats_and_r0_gate(self):
        sample, krows = self._gate_run(repeats=1)
        base = sample[0]
        rep = sample[1]
        self.assertEqual(rep["repeat_of"], base["case_id"])
        # Consistent rater: picks the same SNIPPET both times (letters
        # differ — matching is by snippet, exactly what the ceiling tests).
        labels = {
            base["case_id"]: self._letter(krows, base["case_id"], "hi"),
            rep["case_id"]: self._letter(krows, rep["case_id"], "hi"),
        }
        report = agreement_report(labels, krows)
        self.assertEqual(report["ceiling"],
                         {"pairs": 1, "agree": 1, "rate": 1.0})
        self.assertFalse(report["r0_gated"])
        # Machine rates count the BASE case only — repeats never inflate n.
        self.assertEqual(
            report["clean"]["variants"]["shipped_local"]["overall"]["n"], 1)

        # Inconsistent rater → ceiling 0 → R0 gates the duels.
        labels[rep["case_id"]] = self._letter(krows, rep["case_id"], "lo")
        gated = agreement_report(labels, krows)
        self.assertEqual(gated["ceiling"]["rate"], 0.0)
        self.assertTrue(gated["r0_gated"])
        self.assertTrue(all(d["verdict"].startswith("GATED_BY_R0")
                            for d in gated["duels"].values()))

    def test_none_fit_cases_excluded_from_clean_pass_only(self):
        sample, krows = self._gate_run()
        cid = sample[0]["case_id"]
        labels = {cid: self._letter(krows, cid, "hi")}
        report = agreement_report(labels, krows, none_fit={cid})
        self.assertEqual(
            report["all_cases"]["variants"]["shipped_local"]["overall"]["n"], 1)
        self.assertEqual(
            report["clean"]["variants"]["shipped_local"]["overall"]["n"], 0)
        self.assertEqual(report["none_fit_flagged"], 1)

    def test_key_csv_roundtrip_scores_identically(self):
        sample, krows = self._gate_run(repeats=1)
        cid = sample[0]["case_id"]
        labels = {cid: self._letter(krows, cid, "hi")}
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=list(KEY_COLUMNS))
        w.writeheader()
        w.writerows(krows)
        buf.seek(0)
        reparsed = parse_key_rows(list(csv.DictReader(buf)))
        self.assertEqual(agreement_report(labels, krows),
                         agreement_report(labels, reparsed))

    def test_labeled_case_missing_from_key_is_counted(self):
        _, krows = self._gate_run()
        report = agreement_report({"nope-s00": "A"}, krows)
        self.assertEqual(report["cases_unmatched"], 1)
        self.assertEqual(report["cases_labeled"], 0)


if __name__ == "__main__":
    unittest.main()
