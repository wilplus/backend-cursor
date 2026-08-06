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
import unittest

ROOT = pathlib.Path(__file__).parent

# services.session_metrics imports services.db → supabase, which this pure-unit
# suite must not require. Lift the resolver and its table by AST instead.
_SRC = (ROOT / "services" / "session_metrics.py").read_text()


def _load_resolver():
    """Execute only the pieces this test needs, with a stub logger."""
    tree = ast.parse(_SRC)
    wanted = {"_derive_wpm", "_derive_fillers", "_SNIPPET_FIELDS",
              "_resolve_snippet_value"}
    keep = [n for n in tree.body
            if (isinstance(n, ast.FunctionDef) and n.name in wanted)
            or (isinstance(n, ast.Assign)
                and getattr(n.targets[0], "id", "") in wanted)]
    module = ast.Module(body=keep, type_ignores=[])
    ns: dict = {"logger": _SilentLogger()}
    exec(compile(module, "<session_metrics-subset>", "exec"), ns)
    return ns


class _SilentLogger:
    def warning(self, *a, **k):
        pass


_NS = _load_resolver()
_resolve = _NS["_resolve_snippet_value"]
_FIELDS = _NS["_SNIPPET_FIELDS"]

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
    seconds = float(snippet["duration_ms"]) / 1000.0
    return {
        d: _resolve(snippet, d, snippet.get("metrics") or {},
                    (snippet.get("transcript") or "").strip(), seconds)
        for d in _FIELDS
    }


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
        self.assertNotIn("_SNIPPET_FIELDS[", _SRC,
                         "a call site is indexing the table directly instead "
                         "of going through _resolve_snippet_value")


if __name__ == "__main__":
    unittest.main()
