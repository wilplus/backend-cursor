"""Every live dimension must be readable off a REAL production snippet row.

THE BUG THIS PINS. `wpm` and `fillers` came back NULL on every drift row while
the other four flowed normally. Not a short recording, not the 30 s gate — the
four that worked had a JSONB `metrics` fallback key and those two had `None`.

In production the six denormalized columns are never written:
`db.update_snippet_metrics` is reached only from
`snippet_extraction.recompute_snippet_metrics_for_window`, which has no callers
(orphaned, like compute_session_global_metrics before it). `process_lab_recording`
inserts the `metrics` blob and nothing else. So a dimension with no blob key had
no source at all, and reported `insufficient_data` forever while looking healthy.

The fixture below is the shape a lab-recording snippet ACTUALLY has — blob
populated, columns absent — which is the shape the old code could not read.

Run: python3 -m unittest test_snippet_value_resolution
"""
from __future__ import annotations

import ast
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).parent

# services.snippet_values is PURE — no db, no supabase — so this suite imports
# it directly. It lives apart from session_metrics for exactly that reason.
from services.snippet_values import SNIPPET_FIELDS as _FIELDS  # noqa: E402
from services.snippet_values import display_hz, resolve, weights_of  # noqa: E402

_SESSION_METRICS_SRC = (ROOT / "services" / "session_metrics.py").read_text()


# A lab-recording snippet as process_lab_recording actually writes it: the
# `metrics` blob from audio_metrics._analyze_pcm, no metric columns. Note there
# is no filler key — audio_metrics computes none.
LAB_SNIPPET = {
    "id": "snip-1",
    "duration_ms": 15000,
    "transcript": "so um I think we should uh ship it you know right now",
    "metrics": {
        "wpm": 128.4,
        "pause_ms": 410.0,
        "dynamic_db": 18.2,
        "pitch_center_st": -2.5,
        "energy_ratio": 0.71,
    },
}


def _resolve_all(snippet):
    return {d: resolve(snippet, d) for d in _FIELDS}


class TestTheFixtureIsFaithful(unittest.TestCase):
    """`test_no_dimension_is_unreadable_on_a_real_row` only means something if
    LAB_SNIPPET is the shape production actually produces. Soften the fixture —
    add the columns, add a filler key — and that test goes green while the bug
    is still there. These guard it."""

    def test_the_row_carries_no_metric_columns(self):
        """Nothing on the live loop writes them; a fixture that has them is
        testing a row that does not exist."""
        for column in ("wpm", "fillers", "pause_ms", "dynamic_db",
                       "pitch_center", "energy"):
            self.assertNotIn(column, LAB_SNIPPET)

    def test_the_blob_carries_no_filler_key(self):
        """audio_metrics computes no filler field — which is why fillers needs
        a derivation rather than a blob key."""
        for key in LAB_SNIPPET["metrics"]:
            self.assertNotIn("filler", key.lower())

    def test_the_columns_really_are_unwritten_on_the_live_path(self):
        """The claim the whole diagnosis rests on: update_snippet_metrics is
        reached only from recompute_snippet_metrics_for_window, and that has no
        callers. If someone wires it up, this fails and the fixture above stops
        being the production shape — re-read the diagnosis then."""
        # AST, not a text search: prose mentions of the name in docstrings and
        # comments are not callers, and the first draft of this test failed on
        # its own explanation of the bug.
        target = "recompute_snippet_metrics_for_window"
        callers = []
        for path in ROOT.rglob("*.py"):
            if path.name == "snippet_extraction.py" or path.name.startswith("test_"):
                continue
            if ".mypy_cache" in path.parts or "node_modules" in path.parts:
                continue
            try:
                tree = ast.parse(path.read_text())
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                called = (isinstance(node, ast.Call)
                          and (getattr(node.func, "id", None) == target
                               or getattr(node.func, "attr", None) == target))
                imported = (isinstance(node, ast.ImportFrom)
                            and any(a.name == target for a in node.names))
                if called or imported:
                    callers.append(str(path.relative_to(ROOT)))
                    break
        self.assertEqual(callers, [],
                         f"the orphan now has callers: {callers}")


class TestEveryDimensionResolves(unittest.TestCase):

    def test_no_dimension_is_unreadable_on_a_real_row(self):
        """The whole defect in one assertion. Before the fix, wpm and fillers
        were None here and nothing failed."""
        got = _resolve_all(LAB_SNIPPET)
        missing = sorted(k for k, v in got.items() if v is None)
        self.assertEqual(missing, [],
                         f"unreadable on a live snippet row: {missing}")

    def test_wpm_matches_what_the_pipeline_stored(self):
        """The blob key is 'wpm' and always was — reading it is the fix, not
        recomputing it."""
        self.assertAlmostEqual(_resolve_all(LAB_SNIPPET)["wpm"], 128.4)

    def test_fillers_is_a_count_not_a_rate(self):
        """rate_windows aggregates fillers per_minute and therefore needs a
        COUNT. Handing it a rate would divide by minutes twice."""
        # "um", "uh", "you know" → 3 by DEFAULT_FILLERS.
        value = _resolve_all(LAB_SNIPPET)["fillers"]
        self.assertGreaterEqual(value, 1)
        self.assertEqual(value, float(int(value)), "filler value is not a count")

    def test_a_stored_column_beats_the_blob_and_the_derivation(self):
        """Precedence must not invert: a real measurement always wins."""
        row = dict(LAB_SNIPPET, wpm=99.0)
        self.assertAlmostEqual(_resolve_all(row)["wpm"], 99.0)

    def test_the_blob_beats_the_derivation(self):
        row = dict(LAB_SNIPPET)
        row["metrics"] = dict(row["metrics"], wpm=77.0)
        self.assertAlmostEqual(_resolve_all(row)["wpm"], 77.0)


class TestAbsenceIsNotZero(unittest.TestCase):

    def test_no_transcript_yields_none_not_zero(self):
        """compute_wpm returns 0.0 for an empty string and count_fillers
        returns 0 — writing either would be a FABRICATED measurement of a
        snippet we know nothing about. F.5: missing must stay missing."""
        row = dict(LAB_SNIPPET, transcript="", metrics={})
        got = _resolve_all(row)
        self.assertIsNone(got["wpm"])
        self.assertIsNone(got["fillers"])

    def test_zero_fillers_on_real_speech_is_a_real_measurement(self):
        """The mirror of the above: clean speech genuinely scores 0, and that
        must NOT be suppressed as missing."""
        row = dict(LAB_SNIPPET,
                   transcript="we shipped the thing on Tuesday", metrics={})
        self.assertEqual(_resolve_all(row)["fillers"], 0.0)

    def test_zero_duration_yields_none_for_wpm(self):
        """Guards the divide. compute_wpm returns 0.0 rather than raising."""
        row = dict(LAB_SNIPPET, duration_ms=0, metrics={})
        self.assertIsNone(_resolve_all(row)["wpm"])

    def test_a_boolean_is_not_a_measurement(self):
        """bool subclasses int; True must not silently become 1.0."""
        row = dict(LAB_SNIPPET, energy=True)
        self.assertNotEqual(_resolve_all(row)["energy"], 1.0)


class TestTheHzTrap(unittest.TestCase):
    """`pitch_center` is SEMITONES (audio_metrics._pitch_center_st_from_series)
    while the registry declares the dimension's unit as "Hz". Consistent
    everywhere, so comparisons are valid — but any surface rendering a "Hz"
    label must read f0_mean instead, and two of them format exactly that way.
    """

    def test_display_hz_is_not_the_pitch_center_dimension(self):
        row = dict(LAB_SNIPPET)
        row["metrics"] = dict(row["metrics"], f0_mean=138.0)
        self.assertEqual(display_hz(row), 138.0)
        self.assertEqual(resolve(row, "pitch_center"), -2.5)

    def test_display_hz_is_none_rather_than_semitones(self):
        """The failure that matters: no f0_mean must yield nothing, NOT a
        silent fall back to the semitone figure under an Hz label."""
        self.assertIsNone(display_hz(LAB_SNIPPET))

    def test_no_hz_labelled_surface_reads_pitch_center(self):
        """Guards the two formatters that print "Hz"."""
        for name in ("routes/v2/coaching.py", "routes/v2/user_sessions.py"):
            source = (ROOT / name).read_text()
            for raw in source.splitlines():
                # Comments explaining the trap are not the trap. (This test's
                # first draft failed on the comment warning about it.)
                line = raw.split("#", 1)[0]
                if "Hz" in line and "pitch_center" in line:
                    self.assertIn(
                        "display_hz", line,
                        f"{name}: Hz label reading the semitone dimension: "
                        f"{line.strip()}")


class TestNothingReadsTheDeadColumns(unittest.TestCase):
    """PM-9. The columns exist, look canonical, and are never written. Reading
    one off a snippet row yields None in production 100% of the time, and every
    such site was silently blank rather than broken — which is why four of them
    survived for months.

    Anything that needs these values goes through snippet_values.
    """

    # Where a snippet's values legitimately come from: the freshly computed
    # audio_metrics dict (not a DB row) and the resolver itself.
    ALLOWED = {
        "services/snippet_values.py",       # defines the precedence
        "services/snippet_extraction.py",   # writes them from a live analysis
        "services/audio_metrics.py",        # produces the blob
        "services/session_metrics.py",      # delegates to the resolver
    }

    def test_no_row_read_of_a_dead_column(self):
        dead = set(_FIELDS)
        offenders = []
        for path in (ROOT / "routes").rglob("*.py"):
            rel = str(path.relative_to(ROOT))
            if rel in self.ALLOWED:
                continue
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                # s.get("wpm") / row.get("fillers") — a dict read of a column
                # name off something that is not the metrics blob.
                if not (isinstance(node, ast.Call)
                        and getattr(node.func, "attr", None) == "get"
                        and len(node.args) == 1
                        and isinstance(node.args[0], ast.Constant)
                        and node.args[0].value in dead):
                    continue
                receiver = getattr(node.func.value, "id", "")
                # `metrics.get("wpm")` reads the BLOB and `resolved.get("wpm")`
                # reads resolve_all's OUTPUT — both correct. The defect is
                # reading the name off a raw DB ROW.
                if receiver in ("metrics", "metrics_src", "m", "blob",
                                "resolved"):
                    continue
                offenders.append(
                    f"{rel}:{node.lineno} {receiver}.get"
                    f"({node.args[0].value!r})")
        self.assertEqual(offenders, [],
                         "these read the dead columns instead of "
                         f"snippet_values.resolve_all: {offenders}")


class TestTheOrphanIsGone(unittest.TestCase):
    """PM-9 follow-up: the dead writer is DELETED, not merely uncalled.

    The earlier version of this suite asserted only that
    recompute_snippet_metrics_for_window had no callers. An uncalled function
    that looks like the source of truth is what hid the bug; these assert the
    whole cluster is gone."""

    def test_the_orphaned_writer_and_its_helpers_are_deleted(self):
        source = (ROOT / "services" / "snippet_extraction.py").read_text()
        for symbol in ("def recompute_snippet_metrics_for_window(",
                       "def _load_parent_audio(",
                       "def _retranscribe_window("):
            self.assertNotIn(symbol, source, f"{symbol} is back")

    def test_the_db_writer_is_deleted(self):
        source = (ROOT / "services" / "db.py").read_text()
        self.assertNotIn("def update_snippet_metrics(", source)
        # The narrow blob-only writer SURVIVES — different function, live use.
        self.assertIn("def update_snippet_metrics_blob(", source)

    def test_no_charisma_snippets_query_names_a_dropped_column(self):
        """Migration 0254 drops them; a SELECT naming one would then error.

        SCOPED TO charisma_snippets, and matched as whole tokens. Other tables
        have their OWN wpm/pause_ms columns that this migration does not touch
        — session_sniper_metrics is one — and a substring check flags those
        plus `pitch_center_st`, which is a different column again.
        """
        source = (ROOT / "services" / "db.py").read_text()
        dropped = set(_FIELDS)
        offenders = []
        for match in re.finditer(r'table\("charisma_snippets"\)', source):
            window = source[match.end():match.end() + 600]
            select = re.search(r"\.select\(\s*((?:[^()]|\([^()]*\))*?)\)",
                               window, re.DOTALL)
            if not select:
                continue
            named = set(re.findall(r"[A-Za-z_][A-Za-z_0-9]*", select.group(1)))
            hit = named & dropped
            if hit:
                line = source[:match.start()].count("\n") + 1
                offenders.append(f"db.py:{line} selects {sorted(hit)}")
        self.assertEqual(offenders, [],
                         f"these break once 0254 runs: {offenders}")

    def test_the_column_drop_is_parked_not_manifested(self):
        """A destructive migration in manifest.txt that has NOT been applied
        blocks EVERY deploy: the Railway migrate step hits the DROP COLUMN
        guard and aborts. This one is blocked on a data question (four of the
        six columns hold rows), so it lives in migrations/pending/, which
        migrate.py does not glob. It moves up in the same commit that applies
        it."""
        manifest = (ROOT / "migrations" / "manifest.txt").read_text()
        self.assertNotIn("drop_dead_snippet_metric_columns.sql", manifest)
        self.assertTrue((ROOT / "migrations" / "pending"
                         / "drop_dead_snippet_metric_columns.sql").exists())

    def test_pending_migrations_are_invisible_to_the_runner(self):
        """The parking only works because the glob is non-recursive. If that
        ever changes, every parked file silently re-enters the manifest check
        and deploys break again."""
        source = (ROOT / "scripts" / "migrate.py").read_text()
        self.assertIn('MIGRATIONS_DIR.glob("*.sql")', source)
        self.assertNotIn('MIGRATIONS_DIR.rglob("*.sql")', source)


class TestPauseCountWeights(unittest.TestCase):

    def test_the_pause_count_becomes_a_weight(self):
        row = dict(LAB_SNIPPET)
        row["metrics"] = dict(row["metrics"], pause_count=3)
        self.assertEqual(weights_of(row), {"pause_ms": 3.0})

    def test_wpm_never_gets_a_weight(self):
        """wpm is already a rate — duration-weighting it is exact, and a count
        weight would corrupt it."""
        row = dict(LAB_SNIPPET)
        row["metrics"] = dict(row["metrics"], pause_count=3, wpm=120.0)
        self.assertNotIn("wpm", weights_of(row))

    def test_an_old_snippet_has_no_weights(self):
        self.assertEqual(weights_of(LAB_SNIPPET), {})

    def test_zero_and_bool_are_not_weights(self):
        for bogus in (0, False, True):
            row = dict(LAB_SNIPPET)
            row["metrics"] = dict(row["metrics"], pause_count=bogus)
            self.assertNotIn("pause_ms", weights_of(row), f"count={bogus!r}")


class TestPlumbingCoversTheRegistry(unittest.TestCase):

    def test_every_wired_dimension_has_a_reachable_source(self):
        """A future dimension added with (column, None, None) would repeat this
        bug exactly: silent, permanent insufficient_data."""
        for dim, (column, blob_key, derive) in _FIELDS.items():
            with self.subTest(dim=dim):
                self.assertTrue(
                    blob_key or derive,
                    f"{dim} can only be read from the `{column}` column, and "
                    "nothing on the live loop writes those columns",
                )

    def test_the_resolver_is_the_only_reader(self):
        """Two copies of the precedence chain is how the snippet grain and the
        window grain start disagreeing about the same row."""
        self.assertNotIn("_SNIPPET_FIELDS[", _SESSION_METRICS_SRC,
                         "a call site is indexing the table directly instead "
                         "of going through _resolve_snippet_value")


if __name__ == "__main__":
    unittest.main()
