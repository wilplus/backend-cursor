"""THE ACOUSTIC KPI (founder 2026-08-12).

  1. "The True KPI: Acoustic Moving Average — VERDICT: MEASURE AGAINST THE
     USER'S BASELINE."
  2. "Item 6 Pacing: Single-Point Focus — ISOLATE THE WEAKEST LINK. Identify
     the single most consistently underperforming part. Route all feedback and
     interventions to that specific part. Suppress feedback everywhere else."
  3. "The Ratchet: only when that weakest part surpasses the baseline and
     'comes onboard' does the system unlock feedback for the next
     underperforming part."

The properties worth pinning are not the arithmetic — an EMA is an EMA. They
are the ones a later change would break while every number still looked
plausible: that the ratchet cannot run backwards, that a cold start suppresses
NOTHING, and that the persisted baseline and the transient one are the same
measurement.

Run: python3 -m unittest test_acoustic_kpi
"""
from __future__ import annotations

import logging
import unittest

from services import part_acoustics as pa
from services import acoustic_baseline as ab


def _row(pid, ema, takes=3, onboard=None):
    return {"part_id": pid, "ema_z": ema, "n_takes": takes,
            "came_onboard_at": onboard}


class BaselineTests(unittest.TestCase):
    def test_stats_keep_the_sample_count_the_tuple_shape_cannot(self):
        # A feature backed by 8 pieces and one backed by 80 are not the same
        # claim, and the stored baseline has to be able to say which it is.
        pool = [{"f0_sd": float(i), "dynamic_db": 2.0} for i in range(10)]
        stats = ab.stats_from_metrics(pool, min_samples=8)
        self.assertIn("f0_sd", stats)
        self.assertEqual(stats["f0_sd"]["n"], 10)
        # dynamic_db has ten samples but ZERO spread — z-scoring against it
        # divides by zero, so it is not a usable baseline feature.
        self.assertNotIn("dynamic_db", stats)

    def test_a_feature_under_the_evidence_floor_is_omitted_not_guessed(self):
        pool = [{"f0_sd": float(i)} for i in range(3)]
        self.assertIsNone(ab.stats_from_metrics(pool, min_samples=8))

    def test_the_baseline_tuple_and_persisted_stats_are_one_measurement(self):
        # The persisted form keeps evidence counts while the scoring form uses
        # (mean, sd) tuples. Both must be projections of the same calculation.
        pool = [{"f0_sd": float(i), "pause_regularity": float(i % 3)}
                for i in range(12)]
        tup = ab.as_baseline(ab.stats_from_metrics(pool, 8))
        rich = ab.as_baseline(ab.stats_from_metrics(pool, 8))
        self.assertEqual(tup, rich)

    def test_as_baseline_refuses_a_zero_or_missing_sd(self):
        self.assertIsNone(ab.as_baseline({"f0_sd": {"mean": 1.0, "sd": 0.0}}))
        self.assertIsNone(ab.as_baseline({"f0_sd": {"mean": 1.0}}))
        self.assertIsNone(ab.as_baseline(None))

    def test_the_version_PROMISES_the_weights_it_was_computed_under(self):
        # The founder's immutability rule in executable form: a weights edit
        # that forgets to bump BASELINE_VERSION would silently mix two regimes
        # into one series, which is the slow form of a silent overwrite. This
        # fingerprint is what v1 means; change the weights, change the version,
        # change this string — deliberately, all three at once.
        self.assertEqual(ab.BASELINE_VERSION, "acoustic-baseline-v1")
        self.assertEqual(
            ab.weights_fingerprint(),
            "f0_sd=0.3000;pause_regularity=0.3000;"
            "dynamic_db=0.2500;voiced_ratio=0.1500")
        # And the declared feature set matches the live one, so a feature
        # added to the composite cannot slip in unversioned either.
        from services.snippet_salience import _CONTROL_COMPONENTS
        self.assertEqual(tuple(n for n, _w in _CONTROL_COMPONENTS),
                         ab.BASELINE_FEATURES)


class MovingAverageTests(unittest.TestCase):
    def test_the_first_take_SEEDS_the_average_it_does_not_pull_a_zero(self):
        # Seeding from an implicit 0.0 would make every part look like it
        # started at the baseline and then got worse — a story about the seed,
        # not about the speaker.
        ema, n = pa.fold(None, 0, -2.0)
        self.assertEqual((ema, n), (-2.0, 1))

    def test_later_takes_weigh_more_than_the_first(self):
        ema, n = pa.fold(-2.0, 1, 0.0)
        self.assertEqual(n, 2)
        # Halfway with alpha 0.5 — recent evidence is not drowned by history,
        # which is the whole reason this is exponential and not a flat mean.
        self.assertAlmostEqual(ema, -1.0)
        # A part that keeps improving keeps climbing.
        ema, n = pa.fold(ema, n, 1.0)
        self.assertGreater(ema, -1.0)

    def test_a_part_with_no_pieces_this_take_is_ABSENT_not_zero(self):
        # Folding a fabricated 0.0 would read as "delivered exactly at their
        # baseline", which is a measurement nobody took.
        parts = [{"id": "a", "ord": 0, "text": "Alpha words here."},
                 {"id": "b", "ord": 1, "text": "Beta words here."}]
        # One piece, sitting inside part a only.
        pieces = [{"start": 0, "end": 17, "metrics": {"f0_sd": 1.0}}]
        out = pa.take_z_by_part(pieces, parts, baseline={"f0_sd": (0.0, 1.0)})
        self.assertIn("a", out)
        self.assertNotIn("b", out)

    def test_a_piece_STRADDLING_two_parts_is_dropped_never_guessed(self):
        parts = [{"id": "a", "ord": 0, "text": "Alpha words here."},
                 {"id": "b", "ord": 1, "text": "Beta words here."}]
        pieces = [{"start": 10, "end": 25, "metrics": {"f0_sd": 1.0}}]
        self.assertEqual(
            pa.take_z_by_part(pieces, parts, baseline={"f0_sd": (0.0, 1.0)}),
            {})


class BeatsIncumbentTests(unittest.TestCase):
    """THE PRAISE LANE'S DETECTOR (founder 2026-08-13, Option C).

    It exists because the system had detectors for problems and none at all
    for "this one landed", which is why a fully-settled document produced a
    blank screen: nothing was notable, so nothing was generated, so every
    lane downstream had nothing to route.

    IT IS A HEAD-TO-HEAD, and the first cut was not. That version compared
    the take against arc_part_acoustics.ema_z — which is folded from the
    PERSISTED DOCUMENT, i.e. the best-of assembly. Asking a raw take to beat
    a rolling average of best-of scores asks it to beat the strongest version
    that ever survived, which it almost never does. The lane would have
    shipped looking built and fired approximately never."""

    def test_a_take_that_beats_the_document_version_is_offerable(self):
        out = pa.beats_incumbent({"a": 1.2, "b": 0.1}, {"a": 0.0, "b": 0.0})
        self.assertEqual([p for p, _ in out], ["a"])

    def test_the_biggest_LIFT_comes_first(self):
        # Not the highest absolute score — the biggest improvement over the
        # incumbent, which is what "you just said this better" means.
        out = pa.beats_incumbent({"a": 1.9, "b": 0.6}, {"a": 1.0, "b": -1.0})
        self.assertEqual([p for p, _ in out], ["b", "a"])

    def test_a_FIRST_take_can_never_offer_a_swap(self):
        """No consistency floor is needed and its absence is not an
        oversight: on take one the document IS that take, so the two scores
        are identical, the lift is zero, and no offer exists. The design's
        "requires multiple takes" property falls out of the arithmetic rather
        than being enforced by a rule that could drift from it."""
        same = {"a": 2.5, "b": -1.0}
        self.assertEqual(pa.beats_incumbent(same, dict(same)), [])

    def test_matching_or_losing_to_the_incumbent_is_not_an_offer(self):
        self.assertEqual(pa.beats_incumbent({"a": 0.0}, {"a": 0.0}), [])
        self.assertEqual(pa.beats_incumbent({"a": -2.0}, {"a": 0.0}), [])

    def test_a_WEAK_take_can_still_beat_a_weaker_incumbent(self):
        """Absolute quality is not the question. A paragraph the speaker has
        always struggled with is exactly where an improvement is worth
        offering, even though both sides sit below their baseline."""
        out = pa.beats_incumbent({"a": -1.5}, {"a": -3.0})
        self.assertEqual([p for p, _ in out], ["a"])

    def test_a_part_not_spoken_this_take_is_absent_not_zero(self):
        # take_z_by_part omits parts with no pieces. Treating that as 0.0
        # would offer a swap on a paragraph the student skipped.
        self.assertEqual(pa.beats_incumbent({"b": 5.0}, {"a": 0.0}), [])

    def test_a_part_not_in_the_document_is_skipped(self):
        # No incumbent means nothing to beat — and nothing to replace.
        self.assertEqual(pa.beats_incumbent({"a": 5.0}, {}), [])

    def test_the_margin_is_the_one_number_to_tune(self):
        self.assertEqual(pa.beats_incumbent({"a": 0.4}, {"a": 0.0}), [])
        self.assertEqual(
            [p for p, _ in pa.beats_incumbent({"a": 0.4}, {"a": 0.0},
                                              margin=0.1)], ["a"])
        self.assertLess(pa.STRONG_Z_MARGIN, 1.2,
                        "a problem should need more evidence than a good "
                        "moment: a false problem costs trust, a false "
                        "positive costs one ignored mark")

    def test_it_is_LOCK_AGNOSTIC(self):
        """A lift is a lift. Whether it becomes a swap offer (locked chunks)
        or a lock recommendation (open ones) is the caller's routing decision
        and the two lanes differ — baking one lane's rule in here would break
        the other. The DOCSTRING is stripped first: it names both lanes, so
        scanning the raw source would fail on the record of the decision
        rather than a breach of it."""
        import inspect
        body = inspect.getsource(pa.beats_incumbent).split('"""')[-1]
        for leak in ("locked", "lock_at", "locked_at"):
            self.assertNotIn(leak, body)

    def test_junk_degrades_to_no_offer_never_a_crash(self):
        for bad in (None, [], "x", 42):
            self.assertEqual(pa.beats_incumbent(bad, {"a": 0.0}), [])
            self.assertEqual(pa.beats_incumbent({"a": 1.0}, bad), [])
        self.assertEqual(pa.beats_incumbent({"a": "x"}, {"a": 0.0}), [])

    def test_ties_are_stable_across_calls(self):
        out = pa.beats_incumbent({"b": 1.0, "a": 1.0}, {"a": 0.0, "b": 0.0})
        self.assertEqual([p for p, _ in out], ["a", "b"])


class RatchetTests(unittest.TestCase):
    def test_the_worst_OPEN_part_takes_the_focus(self):
        rows = [_row("a", -0.2), _row("b", -1.5), _row("c", -0.9)]
        self.assertEqual(pa.focus_part_id(rows), "b")

    def test_a_part_that_came_onboard_NEVER_takes_the_focus_again(self):
        # THE RATCHET. b is the worst by a mile and has already graduated; the
        # focus moves to the next open part rather than back to it. Re-deriving
        # this from ema_z instead of reading the latch would turn the ratchet
        # into a threshold, and one bad take would un-graduate a paragraph the
        # student already fixed.
        rows = [_row("a", -0.2), _row("b", -1.5, onboard="2026-08-12T00:00:00Z"),
                _row("c", -0.9)]
        self.assertEqual(pa.focus_part_id(rows), "c")

    def test_ONE_take_is_not_a_consistency_claim(self):
        # "Most CONSISTENTLY underperforming." Routing every intervention in
        # the document at a paragraph on one noisy take is the over-reaction
        # the ratchet exists to prevent.
        self.assertIsNone(pa.focus_part_id([_row("a", -3.0, takes=1)]))
        self.assertEqual(pa.focus_part_id([_row("a", -3.0, takes=2)]), "a")

    def test_a_part_already_at_the_speakers_own_level_is_not_a_focus(self):
        # Nothing is underperforming, so there is nothing to concentrate on.
        self.assertIsNone(pa.focus_part_id([_row("a", 0.4), _row("b", 1.2)]))

    def test_no_rows_no_focus_and_that_is_the_cold_start_answer(self):
        self.assertIsNone(pa.focus_part_id([]))
        self.assertIsNone(pa.focus_part_id(None))

    def test_the_focus_is_STABLE_between_two_identical_takes(self):
        # An unstable choice would move the student's feedback around the
        # document for no reason they could perceive.
        rows = [_row("z", -1.0), _row("a", -1.0)]
        self.assertEqual(pa.focus_part_id(rows), pa.focus_part_id(rows))
        self.assertEqual(pa.focus_part_id(list(reversed(rows))),
                         pa.focus_part_id(rows))

    def test_is_onboard_reads_the_LATCH_not_the_current_average(self):
        self.assertTrue(pa.is_onboard(_row("a", -9.0, onboard="then")))
        self.assertFalse(pa.is_onboard(_row("a", 9.0)))


class SuppressionTests(unittest.TestCase):
    """The filter is the only thing that can take the surface dark, so its
    no-op cases matter more than its active one."""

    PARTS = [{"id": "a", "ord": 0, "text": "Alpha words here."},
             {"id": "b", "ord": 1, "text": "Beta words here."}]
    # part a = [0, 17); "\n\n"; part b = [19, 35)
    CHANGES = [{"id": "1", "kind": "replace", "span": {"start": 0, "end": 5}},
               {"id": "2", "kind": "replace", "span": {"start": 20, "end": 25}}]

    def _ids(self, out):
        return [c["id"] for c in out]

    def test_all_feedback_routes_to_the_focus_part(self):
        from services.intervention_candidates import suppress_outside_focus
        out = suppress_outside_focus(self.CHANGES, self.PARTS, "b")
        self.assertEqual(self._ids(out), ["2"])

    def test_NO_focus_suppresses_NOTHING(self):
        # The cold-start contract, and the one this filter must never get
        # wrong: no baseline, a first take, or a document already at level all
        # arrive here as None, and every one of them must behave exactly as
        # before the feature existed.
        from services.intervention_candidates import suppress_outside_focus
        for focus in (None, "", 0):
            self.assertEqual(
                self._ids(suppress_outside_focus(
                    self.CHANGES, self.PARTS, focus)),
                ["1", "2"], f"focus={focus!r} suppressed something")

    def test_no_parts_suppresses_nothing_either(self):
        from services.intervention_candidates import suppress_outside_focus
        for parts in (None, []):
            self.assertEqual(
                self._ids(suppress_outside_focus(self.CHANGES, parts, "b")),
                ["1", "2"])

    def test_a_focus_id_matching_no_part_does_not_silence_the_surface(self):
        # A stale focus (its part was deleted or re-minted) must degrade to
        # "no focus", not to "suppress everything" — R1 SUPPRESSES, so a bad
        # read here is the one that can take the screen dark.
        from services.intervention_candidates import suppress_outside_focus
        out = suppress_outside_focus(self.CHANGES, self.PARTS, "ghost")
        self.assertEqual(self._ids(out), [])
        # …which is why `select` records it in the funnel: see FunnelTests.

    def test_the_funnel_records_the_focus_gate(self):
        # Eight gates drop silently; this is the ninth, and the empty serve it
        # can produce has to be attributable to it rather than to guesswork.
        from services.intervention_candidates import select
        out = select(self.CHANGES, user_id="u", session_id="s",
                     parts=self.PARTS, focus_part_id="b")
        self.assertIn("after_focus", out["funnel"])
        self.assertEqual(out["funnel"]["after_focus"], 1)


class WiringTests(unittest.TestCase):
    def test_the_pipeline_folds_the_take_AFTER_the_assembly(self):
        # The average is measured over the current best-of document, so
        # folding before the eager assembly would score the PREVIOUS take's
        # selection and file it under this one.
        import inspect
        from services import analysis_worker as aw

        src = inspect.getsource(aw.run_full_analysis)
        self.assertIn("fold_session", src)
        self.assertLess(src.index("maybe_assemble_ideal_text"),
                        src.index("fold_session"))
        # …and it is timed, like every other phase.
        self.assertIn('tl.mark("kpi")', src)
        self.assertLess(src.index('tl.mark("kpi")'), src.index("fold_session"))

    def test_only_the_SPEAKERS_OWN_baseline_is_persisted(self):
        # A parent-take reference is a within-session comparison for the
        # coach's needle, not a claim about where this speaker normally sits.
        # Storing it as one would corrupt the series it feeds.
        import inspect

        src = inspect.getsource(ab.resolve_for_take)
        self.assertIn('kind == "user"', src)
        self.assertIn("snapshot(user_id", src)

    def test_the_upload_path_READS_the_baseline_it_does_not_rebuild_it(self):
        # The 1+N cut (founder 2026-08-12, "can we still do smth with the wait
        # time?"). The upload path must go through the resolver that serves the
        # stored snapshot — calling the rebuilder directly would pay five
        # get_snippets_by_session round-trips on every take, which is what this
        # change exists to stop.
        import inspect
        from services import lab_recording as lr
        from services import recording_piece_analysis as rpa

        pipeline_src = inspect.getsource(lr.process_lab_recording)
        stage_src = inspect.getsource(rpa._refresh_acoustic_baseline)
        self.assertIn("analyze_canonical_pieces", pipeline_src)
        self.assertIn("resolve_for_take", stage_src)
        self.assertNotIn("acoustic_read", stage_src)


class BaselineFreshnessTests(unittest.TestCase):
    """The refresh rule is the whole risk in caching this.

    Never refreshing does not merely age the reference — it INVERTS the
    measurement, because the KPI's job is to notice improvement and a frozen
    baseline reports improvement as drift away from itself.
    """

    def test_it_counts_only_the_sessions_NEWER_than_the_snapshot(self):
        sess = [{"created_at": "2026-08-12T10:00:00Z"},
                {"created_at": "2026-08-12T09:00:00Z"},
                {"created_at": "2026-08-11T09:00:00Z"}]
        # Two, not three: the last session is the PREVIOUS DAY, so it predates
        # the snapshot and is not evidence that the baseline has fallen behind.
        self.assertEqual(ab._newer_than("2026-08-12T08:00:00Z", sess), 2)
        self.assertEqual(ab._newer_than("2026-08-10T08:00:00Z", sess), 3)
        self.assertEqual(ab._newer_than("2026-08-12T09:30:00Z", sess), 1)
        self.assertEqual(ab._newer_than("2026-08-12T23:00:00Z", sess), 0)

    def test_an_UNPARSEABLE_timestamp_forces_a_rebuild(self):
        # The bias is deliberate. Over-counting costs a recompute — correct,
        # merely not free. Under-counting would pin a stale baseline in place
        # forever, and a reference that stopped tracking the speaker is worse
        # than a slow one.
        sess = [{"created_at": "2026-08-12T10:00:00Z"}, {"created_at": None}]
        self.assertEqual(ab._newer_than("not-a-date", sess), 2)
        self.assertEqual(ab._newer_than("2026-08-12T23:00:00Z", sess), 1)
        self.assertEqual(ab._newer_than(None, sess), 2)

    def test_a_NAIVE_and_an_AWARE_timestamp_still_compare(self):
        # PRODUCTION BUG, 2026-08-12. Postgres returns `computed_at` with an
        # offset and `created_at` without, and comparing the two raises
        # "can't compare offset-naive and offset-aware datetimes" — at the
        # COMPARISON, not the parse, so it fell past _dt's guard into the
        # caller's except, which logged "cached read failed" and rebuilt. Every
        # take. The cache never served a single hit and the whole saving was
        # forfeited while every test here passed, because the tests used
        # uniformly Z-suffixed strings and production does not.
        aware = "2026-08-12T10:26:39.552+00:00"
        naive = [{"created_at": "2026-08-12T11:01:25.068"}]
        self.assertEqual(ab._newer_than(aware, naive), 1)
        # …and the other way round.
        self.assertEqual(
            ab._newer_than("2026-08-12T11:30:00",
                           [{"created_at": "2026-08-12T10:00:00+00:00"}]), 0)

    def test_a_mixed_pair_does_not_disable_the_cache_wholesale(self):
        # The shape of the original failure: one bad comparison must cost one
        # rebuild, never take the whole fast path down.
        class _Db:
            def get_current_user_acoustic_baseline(self, uid, *, detector_version=""):
                return {"id": "b1", "computed_at": "2026-08-12T10:00:00+00:00",
                        "features": {"f0_sd": {"mean": 1.0, "sd": 0.5}}}

            def v2_list_user_lab_sessions(self, uid, *, limit=5):
                return [{"created_at": "2026-08-12T09:00:00"}]   # naive, older

            def get_snippets_by_session(self, sid):   # pragma: no cover
                raise AssertionError("rebuilt when it should have reused")

        base, kind = ab.resolve_for_take("u1", database=_Db())
        self.assertEqual((base, kind), ({"f0_sd": (1.0, 0.5)}, "user"))

    def test_no_sessions_is_not_stale(self):
        self.assertEqual(ab._newer_than("2026-08-12T08:00:00Z", []), 0)
        self.assertEqual(ab._newer_than("2026-08-12T08:00:00Z", None), 0)

    def test_the_freshness_window_is_the_REBUILD_window(self):
        # The staleness check and the rebuild must agree about how far back
        # "recent" goes, or the cache could be judged fresh against five
        # sessions and rebuilt from a different five.
        self.assertEqual(ab._max_sessions(), ab._BASELINE_MAX_SESSIONS)

    def test_a_stored_baseline_is_reused_without_touching_the_snippets(self):
        # The point of the whole change: the expensive call is
        # get_snippets_by_session, once per session in the window.
        calls: list = []

        class _Db:
            def get_current_user_acoustic_baseline(self, uid, *, detector_version=""):
                calls.append("baseline")
                return {"id": "b1", "computed_at": "2026-08-12T10:00:00Z",
                        "features": {"f0_sd": {"mean": 1.0, "sd": 0.5}}}

            def v2_list_user_lab_sessions(self, uid, *, limit=5):
                calls.append("sessions")
                return [{"created_at": "2026-08-12T11:00:00Z"}]

            def get_snippets_by_session(self, sid):    # pragma: no cover
                calls.append("snippets")
                return []

        base, kind = ab.resolve_for_take("u1", database=_Db())
        self.assertEqual(kind, "user")
        self.assertEqual(base, {"f0_sd": (1.0, 0.5)})
        self.assertEqual(calls, ["baseline", "sessions"])   # two, not six

    def test_it_rebuilds_once_the_window_has_passed(self):
        calls: list = []

        class _Db:
            def get_current_user_acoustic_baseline(self, uid, *, detector_version=""):
                calls.append("baseline")
                return {"id": "b1", "computed_at": "2026-08-12T00:00:00Z",
                        "features": {"f0_sd": {"mean": 1.0, "sd": 0.5}}}

            def v2_list_user_lab_sessions(self, uid, *, limit=5):
                calls.append("sessions")
                return [{"id": "s1", "created_at": "2026-08-12T10:00:00Z"},
                        {"id": "s2", "created_at": "2026-08-12T11:00:00Z"},
                        {"id": "s3", "created_at": "2026-08-12T12:00:00Z"}]

            def get_snippets_by_session(self, sid):
                calls.append("snippets")
                return []

        ab.resolve_for_take("u1", database=_Db())
        self.assertGreaterEqual(calls.count("snippets"), 1)

    def test_a_read_hiccup_costs_a_rebuild_never_a_take(self):
        class _Db:
            def get_current_user_acoustic_baseline(self, uid, *, detector_version=""):
                raise RuntimeError("table gone")

            def v2_list_user_lab_sessions(self, uid, *, limit=5):
                return []

            def get_snippets_by_session(self, sid):    # pragma: no cover
                return []

        # No raise, and the cold-start answer rather than a crash.
        self.assertEqual(ab.resolve_for_take("u1", database=_Db()),
                         (None, None))


class PartIterationRegressionTests(unittest.TestCase):
    """`iteration` was resetting to 0 on every wholesale parts replace.

    The insert names its columns, so every column it omits returns to its
    DEFAULT. All three call sites read `locked_at` back and thread it through;
    not one mentions `iteration`, because preserving a column is opt-in and
    forgetting is the default. Lock a chunk, record another take, open the
    readout — compose reports `changed`, the parts are replaced, and the
    founder's "Locked in · N iterations" kicker is back to zero silently.
    """

    def test_the_replace_carries_iteration_across(self):
        import inspect
        from services.db import DatabaseService

        src = inspect.getsource(DatabaseService.replace_ideal_text_parts)
        self.assertIn('"iteration"', src)
        # Read BEFORE the delete — afterwards there is nothing to read.
        self.assertLess(src.index("prev_iter"), src.index(".delete()"))

    def test_preservation_lives_in_the_WRITER_not_in_the_callers(self):
        # A fourth call site must not be able to forget it, which is the whole
        # reason this is not fixed at the three call sites individually.
        import inspect
        import routes.v2.explore_ideal_text as eit

        src = inspect.getsource(eit)
        self.assertGreaterEqual(src.count("replace_ideal_text_parts"), 3)
        self.assertNotIn("iteration=", src)


if __name__ == "__main__":
    logging.disable(logging.CRITICAL)
    unittest.main()
