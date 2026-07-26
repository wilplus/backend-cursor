"""F1 — the MEASURED audio-vs-UI clock offset (2026-07-26).

Pause-snap guesses the recorder warm-up by hunting a silence near each tap.
The FE can measure it instead. This pins that correction.

  C-1  the shift is exact, order/shape preserving, and clamps at 0;
  C-2  a missing / malformed / absurd offset degrades to TODAY's behaviour —
       an unusable measurement must never corrupt the timeline;
  C-3  validation rejects an out-of-range value loudly (seconds-sent-as-ms is
       the classic bug) instead of clamping it into something plausible;
  C-4  the whole pipeline inherits the correction from one place;
  C-5  a take with no offset is byte-identical to before this shipped.

Run: ./venv/bin/python -m unittest test_slide_clock_offset
"""
from __future__ import annotations

import unittest

from services.slide_word_split import (
    apply_clock_offset, context_with_clock_offset,
)


def _adv(*t_ms):
    return [{"index": i, "t_ms": t} for i, t in enumerate(t_ms)]


class ApplyOffsetTests(unittest.TestCase):
    """C-1 — the arithmetic."""

    def test_subtracts_the_offset_from_every_tap(self):
        out = apply_clock_offset(_adv(0, 5000, 9000), 300)
        self.assertEqual([a["t_ms"] for a in out], [0, 4700, 8700])

    def test_clamps_at_zero_a_tap_cannot_precede_the_recording(self):
        out = apply_clock_offset(_adv(0, 100), 400)
        self.assertEqual([a["t_ms"] for a in out], [0, 0])

    def test_index_and_shape_are_preserved(self):
        out = apply_clock_offset([{"index": 7, "t_ms": 5000, "extra": "x"}], 300)
        self.assertEqual(out[0]["index"], 7)
        self.assertEqual(out[0]["extra"], "x")

    def test_a_negative_offset_shifts_the_other_way(self):
        out = apply_clock_offset(_adv(5000), -200)
        self.assertEqual(out[0]["t_ms"], 5200)

    def test_input_is_not_mutated(self):
        src = _adv(0, 5000)
        apply_clock_offset(src, 300)
        self.assertEqual(src[1]["t_ms"], 5000)


class DegradeTests(unittest.TestCase):
    """C-2 — an unusable measurement must fall back, never corrupt."""

    def test_missing_zero_and_malformed_are_all_no_ops(self):
        src = _adv(0, 5000)
        for bad in (None, 0, "300", True, False, [], {}, float("nan")):
            self.assertIs(apply_clock_offset(src, bad), src, repr(bad))

    def test_absurd_offsets_are_ignored_not_clamped(self):
        # 300000ms = seconds mistaken for milliseconds. Refusing beats
        # "helpfully" clamping to 30s and silently wrecking the timeline.
        src = _adv(0, 5000)
        self.assertIs(apply_clock_offset(src, 300000), src)
        self.assertIs(apply_clock_offset(src, -60000), src)

    def test_empty_or_non_list_advances(self):
        self.assertEqual(apply_clock_offset([], 300), [])
        self.assertIsNone(apply_clock_offset(None, 300))

    def test_a_malformed_entry_passes_through_untouched(self):
        out = apply_clock_offset([{"index": 0, "t_ms": True},
                                  {"index": 1, "t_ms": 5000}], 300)
        self.assertIs(out[0]["t_ms"], True)      # bool never treated as 1ms
        self.assertEqual(out[1]["t_ms"], 4700)


class ContextTests(unittest.TestCase):
    """C-4/C-5 — one place corrects it; no offset means no change at all."""

    def test_context_advances_are_shifted(self):
        ctx = {"topic": "t", "slide_advances": _adv(0, 5000),
               "slide_clock_offset_ms": 300}
        out = context_with_clock_offset(ctx)
        self.assertEqual([a["t_ms"] for a in out["slide_advances"]], [0, 4700])
        self.assertEqual(out["topic"], "t")          # everything else intact

    def test_no_offset_returns_the_very_same_object(self):
        # C-5: identity, not just equality — proves nothing was rebuilt and a
        # legacy take takes a byte-identical path.
        for ctx in ({"slide_advances": _adv(0, 5000)},
                    {"slide_advances": _adv(0, 5000),
                     "slide_clock_offset_ms": None},
                    {"slide_advances": _adv(0, 5000),
                     "slide_clock_offset_ms": 0},
                    {"slide_clock_offset_ms": 300},          # no advances
                    {}):
            self.assertIs(context_with_clock_offset(ctx), ctx)

    def test_out_of_range_offset_leaves_the_context_alone(self):
        ctx = {"slide_advances": _adv(0, 5000),
               "slide_clock_offset_ms": 999999}
        self.assertIs(context_with_clock_offset(ctx), ctx)

    def test_non_dict_context(self):
        self.assertIsNone(context_with_clock_offset(None))

    def test_the_original_context_is_never_mutated(self):
        ctx = {"slide_advances": _adv(0, 5000), "slide_clock_offset_ms": 300}
        context_with_clock_offset(ctx)
        self.assertEqual(ctx["slide_advances"][1]["t_ms"], 5000)


class ValidatorTests(unittest.TestCase):
    """C-3 — the field on the intake contract."""

    def _v(self, body):
        from services.intake_context import validate_intake_context_body
        return validate_intake_context_body(body)

    def test_accepted_and_carried(self):
        self.assertEqual(self._v({"slide_clock_offset_ms": 275})
                         ["slide_clock_offset_ms"], 275)

    def test_absent_is_none(self):
        self.assertIsNone(self._v({"topic": "t"})["slide_clock_offset_ms"])

    def test_negative_within_range_is_allowed(self):
        # The UI clock can start marginally AFTER the audio.
        self.assertEqual(self._v({"slide_clock_offset_ms": -120})
                         ["slide_clock_offset_ms"], -120)

    def test_out_of_range_rejected_loudly(self):
        from services.intake_context import IntakeContextError
        for bad in (300000, -60000):
            with self.assertRaises(IntakeContextError, msg=str(bad)):
                self._v({"slide_clock_offset_ms": bad})

    def test_non_int_and_bool_rejected(self):
        from services.intake_context import IntakeContextError
        for bad in ("300", 3.5, True):
            with self.assertRaises(IntakeContextError, msg=repr(bad)):
                self._v({"slide_clock_offset_ms": bad})

    def test_key_is_canonical_so_it_survives_the_validator(self):
        # The validator STRIPS unknown keys — the #221 lesson. If this field
        # were not in _FIELDS it would be silently dropped and the whole
        # feature would run inert in prod.
        from services.intake_context import _FIELDS
        self.assertIn("slide_clock_offset_ms", _FIELDS)


class PipelineWiringTests(unittest.TestCase):
    """C-4 — the correction is actually applied by the pipeline, not just
    available. Guards the exact failure mode where a helper exists but nothing
    calls it."""

    def test_process_lab_recording_applies_it(self):
        import inspect
        from services import lab_recording as mod
        src = inspect.getsource(mod.process_lab_recording)
        self.assertIn("context_with_clock_offset", src)

    def test_correction_precedes_any_slide_advances_read(self):
        import inspect
        from services import lab_recording as mod
        src = inspect.getsource(mod.process_lab_recording)
        applied = src.index("context_with_clock_offset")
        first_read = src.index('get("slide_advances")')
        self.assertLess(applied, first_read,
                        "taps must be corrected BEFORE anything reads them")


if __name__ == "__main__":
    unittest.main()
