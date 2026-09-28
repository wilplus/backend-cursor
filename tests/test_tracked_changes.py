"""The served change list — anchors, grain, and lane precedence.

Run: python3 -m unittest tests.test_tracked_changes
"""
from __future__ import annotations

import unittest

from services import tracked_changes as tc


class AcousticSwapServeTests(unittest.TestCase):
    """Stage 5 — the swap lane's serve contract (founder 2026-08-13)."""

    DOC = "First part words here.\n\nSecond part words here."

    def _piece(self, grain):
        return {"snippet_id": "s1", "start": 24, "end": 47,
                "text": "Second part words here.", "anchor_grain": grain}

    def _sug(self, trigger):
        return {"s1": {"kind": "replace", "trigger": trigger,
                       "replacement_text": "Second part words, better said."}}

    def test_it_gets_its_OWN_source_not_wording(self):
        """The FE labels it 'Delivery' and the anchoring exemption keys on it;
        both need it distinguishable from an ordinary replace, and the internal
        trigger never rides the payload."""
        out = tc.build_tracked_changes(
            self.DOC, [self._piece("word")], self._sug("acoustic_swap"))
        self.assertEqual(out[0]["source"], "acoustic_swap")

    def test_it_SURVIVES_paragraph_grain_where_a_plain_replace_declines(self):
        """THE EXEMPTION, and the one comparison that shows why it is not a
        weakening. A locked chunk is exactly what gets a coarse anchor, so the
        decline would mute this lane precisely where it applies — and unlike an
        ordinary replace, whole-paragraph IS this lane's claim rather than a
        silently widened one."""
        piece = self._piece("paragraph")
        swap = tc.build_tracked_changes(
            self.DOC, [piece], self._sug("acoustic_swap"))
        plain = tc.build_tracked_changes(
            self.DOC, [piece], self._sug(None))
        self.assertEqual(len(swap), 1)
        self.assertEqual(swap[0]["quote"], "Second part words here.")
        self.assertEqual(plain, [])          # the rule still holds elsewhere

    def test_the_internal_trigger_never_rides_the_payload(self):
        out = tc.build_tracked_changes(
            self.DOC, [self._piece("word")], self._sug("acoustic_swap"))
        self.assertNotIn("acoustic_swap", str(out[0].get("why") or ""))
        self.assertNotIn("trigger", out[0])


class LanePrecedenceTests(unittest.TestCase):
    """Corrections > Swap > Style when two lanes want the same words."""

    def _c(self, source, start, end, kind="replace"):
        return {"source": source, "kind": kind,
                "span": {"start": start, "end": end}, "quote": "x"}

    def test_a_correction_beats_a_swap_on_the_same_span(self):
        kept = tc.drop_overlaps([self._c("acoustic_swap", 0, 40),
                                 self._c("wording", 0, 40)])
        self.assertEqual([c["source"] for c in kept], ["wording"])

    def test_a_swap_beats_a_STYLE_bold_it_contains(self):
        """Width alone got this backwards: the swap's span is a whole
        paragraph by construction, so the narrower-wins tie-break handed every
        collision to a 'make this word orange' suggestion."""
        kept = tc.drop_overlaps([self._c("acoustic_swap", 0, 40),
                                 self._c("wording", 0, 8, kind="bold")])
        self.assertEqual([c["source"] for c in kept], ["acoustic_swap"])

    def test_non_overlapping_lanes_all_survive(self):
        kept = tc.drop_overlaps([self._c("acoustic_swap", 0, 20),
                                 self._c("wording", 30, 40)])
        self.assertEqual(len(kept), 2)


class ConfidentVoiceSourceTests(unittest.TestCase):
    """§17 acoustic-confidence-v1: the Confident Voice card gets its OWN
    served source, so the FE can title it and key its signed body."""

    def test_confident_trigger_routes_to_its_own_source(self):
        from services.tracked_changes import _kind_and_source
        self.assertEqual(
            _kind_and_source({"kind": "emphasize", "trigger": "confident"}),
            ("bold", "confident_voice"))
        # Historical charisma-era rows stay interpretable (corpus rule).
        self.assertEqual(
            _kind_and_source({"kind": "emphasize", "trigger": "charisma"}),
            ("bold", "confident_voice"))
        # An ordinary emphasize is untouched.
        self.assertEqual(
            _kind_and_source({"kind": "emphasize", "trigger": None}),
            ("bold", "wording"))

    def test_confident_voice_is_a_served_source(self):
        from services.tracked_changes import SOURCES
        self.assertIn("confident_voice", SOURCES)


class BuildTrackedChangesPinTests(unittest.TestCase):
    """What build_tracked_changes serves, pinned before its split into named
    stages (audit W1, 2026-09-28): the refusals, one exact entry per lane,
    the cue filter, the fallbacks and the order."""

    DOC = "We ship fast.\n\nThen we listen closely."
    FIRST = {"snippet_id": "s1", "take_session_id": "t1", "start": 0,
             "end": 13, "text": "We ship fast."}
    SECOND = {"snippet_id": "s2", "take_session_id": "t1", "start": 15,
              "end": 38, "text": "Then we listen closely."}

    def _build(self, suggestions, pieces=None, **kwargs):
        return tc.build_tracked_changes(
            self.DOC, [self.FIRST, self.SECOND] if pieces is None else pieces,
            suggestions, **kwargs)

    def test_refusals(self):
        wording = {"kind": "replace", "replacement_text": "We move fast."}
        self.assertEqual(tc.build_tracked_changes(None, [self.FIRST],
                                                  {"s1": wording}), [])
        self.assertEqual(tc.build_tracked_changes("", [self.FIRST],
                                                  {"s1": wording}), [])
        self.assertEqual(self._build({"s1": wording}, pieces=[
            "not a piece",
            dict(self.FIRST, snippet_id=""),
            dict(self.FIRST, start="x"),
            {k: v for k, v in self.FIRST.items() if k != "end"},
            dict(self.FIRST, start=None),
            dict(self.FIRST, text="Other words."),
        ]), [])
        self.assertEqual(self._build({"s1": "not a row"}), [])
        self.assertEqual(self._build({"s1": {"kind": "mystery"}}), [])
        self.assertEqual(self._build({"s1": wording}, applied=["s1"]), [])
        self.assertEqual(self._build(None), [])
        self.assertEqual(self._build(
            {"s1": {"kind": "replace", "replacement_text": "   "}}), [])

    def test_a_wording_replace_entry(self):
        out = self._build({"s1": {"kind": "replace", "why": "free text",
                                  "replacement_text": " We move fast. "}})
        self.assertEqual(out, [{
            "id": "s1", "snippet_id": "s1", "take_session_id": "t1",
            "kind": "replace", "source": "wording",
            "span": {"start": 0, "end": 13}, "quote": "We ship fast.",
            "why_key": "clarity", "proposed_text": "We move fast.",
            "why": "free text",
        }])

    def test_a_profanity_replace_has_no_why_key(self):
        out = self._build({"s2": {"kind": "replace", "trigger": "profanity",
                                  "replacement_text": "Then we listen."}})
        self.assertEqual(out[0]["source"], "profanity")
        self.assertNotIn("why_key", out[0])

    def test_an_emphasis_bold_narrows_to_the_picked_phrase(self):
        out = self._build({"s2": {"kind": "emphasize", "trigger": "clarity",
                                  "emphasis_quote": "LISTEN", "why": "w",
                                  "cue_keys": ["full_volume"]}})
        self.assertEqual(out, [{
            "id": "s2", "snippet_id": "s2", "take_session_id": "t1",
            "kind": "bold", "source": "wording",
            "span": {"start": 23, "end": 29}, "quote": "listen",
            "why_key": "emphasis", "why": "w",
        }])

    def test_key_phrases_narrow_a_bold_and_nothing_else(self):
        phrases = {"s2": ["we listen"], "s1": ["ship"]}
        out = self._build({"s2": {"kind": "emphasize"},
                           "s1": {"kind": "replace",
                                  "replacement_text": "We go."}},
                          key_phrases_by_snippet=phrases)
        self.assertEqual([(c["quote"], c["kind"]) for c in out],
                         [("We ship fast.", "replace"),
                          ("we listen", "bold")])

    def test_confident_voice_keeps_only_known_cues(self):
        sug = {"kind": "emphasize", "trigger": "confident", "why": "w",
               "emphasis_quote": "we listen",
               "cue_keys": ["full_volume", "made-up", 3, "kept_moving"]}
        out = self._build({"s2": sug})
        self.assertEqual(out, [{
            "id": "s2", "snippet_id": "s2", "take_session_id": "t1",
            "kind": "bold", "source": "confident_voice",
            "span": {"start": 20, "end": 29}, "quote": "we listen",
            "why_key": "confident_voice", "why": "w",
            "cue_keys": ["full_volume", "kept_moving"],
        }])
        for cues in (["made-up"], "full_volume", None):
            out = self._build({"s2": dict(sug, cue_keys=cues)})
            self.assertNotIn("cue_keys", out[0])

    def test_advice_names_its_device_and_keeps_only_known_cues(self):
        out = self._build({
            "s1": {"kind": "delivery", "trigger": "pause", "why": "dropped",
                   "cue_keys": ("landed_ending", "nope")},
            "s2": {"kind": "structure", "trigger": "signpost"},
        })
        self.assertEqual(out, [
            {"id": "s1", "snippet_id": "s1", "take_session_id": "t1",
             "kind": "advice", "source": "delivery",
             "span": {"start": 0, "end": 13}, "quote": "We ship fast.",
             "device": "pause", "why": None, "cue_keys": ["landed_ending"]},
            {"id": "s2", "snippet_id": "s2", "take_session_id": "t1",
             "kind": "advice", "source": "structural",
             "span": {"start": 15, "end": 38},
             "quote": "Then we listen closely.",
             "device": "signpost", "why": None},
        ])

    def test_a_wide_bold_with_no_phrase_is_declined_at_any_grain(self):
        doc = "One sentence here. Another sentence there."
        piece = {"snippet_id": "s1", "start": 0, "end": len(doc),
                 "text": doc}
        self.assertEqual(tc.build_tracked_changes(
            doc, [piece], {"s1": {"kind": "emphasize"}}), [])
        # One sentence is accent width and is bolded whole.
        self.assertEqual(self._build({"s1": {"kind": "emphasize"}})[0]["quote"],
                         "We ship fast.")

    def test_paragraph_grain_declines_replace_and_bold_but_keeps_advice(self):
        piece = dict(self.FIRST, anchor_grain="paragraph")
        for sug in ({"kind": "replace", "replacement_text": "x"},
                    {"kind": "emphasize"}):
            self.assertEqual(self._build({"s1": sug}, pieces=[piece]), [])
        out = self._build({"s1": {"kind": "delivery"}}, pieces=[piece])
        self.assertEqual(out[0]["quote"], "We ship fast.")

    def test_a_narrowed_quote_outside_the_window_falls_back_to_the_window(self):
        from unittest import mock

        with mock.patch.object(tc, "_narrow", return_value="not in there"):
            out = self._build({"s1": {"kind": "replace",
                                      "replacement_text": "We go."}})
        self.assertEqual((out[0]["quote"], out[0]["span"]),
                         ("We ship fast.", {"start": 0, "end": 13}))

    def test_ordered_by_span_start_then_end(self):
        doc = "Alpha beta gamma."
        pieces = [
            {"snippet_id": "late", "start": 6, "end": 17,
             "text": "beta gamma."},
            {"snippet_id": "long", "start": 0, "end": 17, "text": doc},
            {"snippet_id": "short", "start": 0, "end": 5, "text": "Alpha"},
        ]
        advice = {"kind": "delivery"}
        out = tc.build_tracked_changes(
            doc, pieces, {"late": advice, "long": advice, "short": advice})
        self.assertEqual([c["id"] for c in out], ["short", "long", "late"])
