"""willab — provenance hashing, the boot check, and the row stamps.

SPEC-immutable-provenance, Phase A. services/provenance.py (pure),
services/provenance_check.py (runtime), and the two db.py write paths that
carry the result.

WHAT THIS PINS DOWN:
  * CANONICAL FORM — the hash must not depend on dict key order, list order,
    or how the process happened to start. Every definition here is a set, so
    a cosmetic reorder of the lexicon must NOT read as a behaviour change —
    a checker that cries wolf gets muted, which is worse than no checker;
  * THE HASH MOVES WHEN BEHAVIOUR MOVES — adding one word ("actually") must
    change it. That is the founder's exact danger: "if fillers are corrupted
    all my data goes nuts";
  * THE SEED CONTRACT — the live DEFAULT_FILLERS must hash to a seed some
    detector_version migration actually records. This makes CI itself a
    provenance check: edit the lexicon without minting a version row and
    this file goes red BEFORE prod boots into a CRITICAL log;
  * UNKNOWN IS SUSPECT — no recorded hash, or a detector the module cannot
    describe, reports SUSPECT, never a clean bill of health issued without
    an examination;
  * TABLE-MISSING IS *NOT* SUSPECT — pre-migration (or DB down) the row
    stays UNSTAMPED, the same honest NULL as pre-provenance history, and
    the miss is NOT cached so the first read after 0257 lands picks it up;
  * THE STAMP NEVER BREAKS THE WRITE IT RIDES — a database without the 0257
    columns gets the measurements unstamped rather than not at all, and a
    missing label_revision table never un-succeeds the rating write.

Run: python3 -m unittest test_provenance
"""
from __future__ import annotations

import pathlib
import re
import unittest

from services import provenance, provenance_check
from tests.fakes import FakeSupabaseClient, swap_attr
from utils.metrics import DEFAULT_FILLERS

MIGRATIONS = pathlib.Path(__file__).parent / "migrations"


class TestCanonicalForm(unittest.TestCase):
    def test_dict_key_order_is_irrelevant(self):
        a = {"lexicon": ["um", "uh"], "match": "whole_word_ci"}
        b = {"match": "whole_word_ci", "lexicon": ["um", "uh"]}
        self.assertEqual(provenance.definition_hash(a),
                         provenance.definition_hash(b))

    def test_list_order_is_irrelevant(self):
        """The lexicon is a SET — reordering cannot change one output."""
        a = {"lexicon": ["um", "uh", "like"]}
        b = {"lexicon": ["like", "um", "uh"]}
        self.assertEqual(provenance.definition_hash(a),
                         provenance.definition_hash(b))

    def test_adding_a_word_changes_the_hash(self):
        """The founder's exact scenario: add 'actually' and the eras split."""
        today = {"lexicon": list(DEFAULT_FILLERS), "match": "whole_word_ci"}
        tomorrow = {"lexicon": list(DEFAULT_FILLERS) + ["actually"],
                    "match": "whole_word_ci"}
        self.assertNotEqual(provenance.definition_hash(today),
                            provenance.definition_hash(tomorrow))

    def test_removing_so_changes_the_hash(self):
        """The named live prospect: tightening 'so' out of the list."""
        today = {"lexicon": list(DEFAULT_FILLERS), "match": "whole_word_ci"}
        tightened = {"lexicon": [w for w in DEFAULT_FILLERS if w != "so"],
                     "match": "whole_word_ci"}
        self.assertNotEqual(provenance.definition_hash(today),
                            provenance.definition_hash(tightened))

    def test_nested_structures_normalise(self):
        a = {"a": [{"y": 2, "x": 1}, {"b": [3, 1, 2]}]}
        b = {"a": [{"b": [1, 2, 3]}, {"x": 1, "y": 2}]}
        self.assertEqual(provenance.canonical(a), provenance.canonical(b))


class TestSeedContract(unittest.TestCase):
    """The live code must hash to a version some migration actually seeds.

    THIS TEST IS THE CI HALF OF THE BOOT CHECK. When it fails, the fix is
    NEVER to edit an existing seed row — mint the next version: a new
    migration inserting fillers-v2 with the new lexicon and its hash, and
    a retire of the v1 row. Editing v1's hash to make this pass would
    rewrite what the historical rows mean, which is the corruption this
    whole spec exists to prevent.
    """

    def _seeded_hashes(self) -> set:
        out = set()
        for path in MIGRATIONS.glob("*.sql"):
            sql = path.read_text(encoding="utf-8")
            for block in re.findall(
                    r"INSERT\s+INTO\s+public\.detector_version[\s\S]{0,2000}?;",
                    sql, re.IGNORECASE):
                out.update(re.findall(r"'([0-9a-f]{64})'", block))
        return out

    def test_live_fillers_hash_is_seeded(self):
        live = provenance.live_definition(provenance.FILLERS)
        self.assertIsNotNone(live)
        self.assertIn(provenance.definition_hash(live), self._seeded_hashes())

    def test_live_lexicon_is_default_fillers(self):
        live = provenance.live_definition(provenance.FILLERS)
        self.assertEqual(live["lexicon"], list(DEFAULT_FILLERS))


class TestCheck(unittest.TestCase):
    def test_matching_hash_is_ok(self):
        live = provenance.live_definition(provenance.FILLERS)
        marker, live_hash = provenance.check(
            provenance.FILLERS, provenance.definition_hash(live))
        self.assertEqual(marker, provenance.OK)
        self.assertEqual(live_hash, provenance.definition_hash(live))

    def test_mismatch_is_suspect(self):
        marker, _ = provenance.check(provenance.FILLERS, "0" * 64)
        self.assertEqual(marker, provenance.SUSPECT)

    def test_missing_recorded_hash_is_suspect(self):
        """No recorded hash = nobody can say what produced the number."""
        for bad in (None, "", 42):
            marker, _ = provenance.check(provenance.FILLERS, bad)
            self.assertEqual(marker, provenance.SUSPECT, bad)

    def test_unknown_detector_is_suspect(self):
        marker, live_hash = provenance.check("no_such_detector", "0" * 64)
        self.assertEqual(marker, provenance.SUSPECT)
        self.assertIsNone(live_hash)

    def test_recorded_hash_is_case_and_space_tolerant(self):
        """A hand-pasted hash with whitespace must not read as corruption."""
        live = provenance.live_definition(provenance.FILLERS)
        h = provenance.definition_hash(live)
        marker, _ = provenance.check(provenance.FILLERS,
                                     "  " + h.upper() + "\n")
        self.assertEqual(marker, provenance.OK)


class TestStatus(unittest.TestCase):
    """provenance_check.status — the three outcomes and the cache rule."""

    def setUp(self):
        provenance_check.reset_cache()

    def tearDown(self):
        provenance_check.reset_cache()

    def _with_row(self, row):
        return swap_attr(provenance_check, "_read_current_row", lambda d: row)

    def _good_row(self):
        live = provenance.live_definition(provenance.FILLERS)
        return {"version": "fillers-v1",
                "definition_hash": provenance.definition_hash(live)}

    def test_matching_row_is_ok(self):
        with self._with_row(self._good_row()):
            self.assertEqual(provenance_check.status(provenance.FILLERS),
                             (provenance.OK, "fillers-v1"))

    def test_mismatching_row_is_suspect_and_logs_critical(self):
        row = {"version": "fillers-v1", "definition_hash": "0" * 64}
        with self._with_row(row):
            with self.assertLogs("services.provenance_check",
                                 level="CRITICAL"):
                marker, version = provenance_check.status(provenance.FILLERS)
        self.assertEqual(marker, provenance.SUSPECT)
        self.assertEqual(version, "fillers-v1")

    def test_table_answered_but_no_row_is_suspect(self):
        """The table exists and says 'no current version' — that IS a look,
        and what it found is that nobody registered the detector."""
        with self._with_row({}):
            with self.assertLogs("services.provenance_check",
                                 level="CRITICAL"):
                marker, _ = provenance_check.status(provenance.FILLERS)
        self.assertEqual(marker, provenance.SUSPECT)

    def test_unreadable_table_is_unstamped_and_not_cached(self):
        """Pre-migration is NOT suspicion, and the miss must stay retryable:
        after 0257 lands the very next read should pick it up, no restart."""
        with self._with_row(None):
            self.assertEqual(provenance_check.status(provenance.FILLERS),
                             (None, None))
        with self._with_row(self._good_row()):
            self.assertEqual(provenance_check.status(provenance.FILLERS),
                             (provenance.OK, "fillers-v1"))

    def test_definite_answer_is_cached(self):
        calls = []

        def read(detector_id):
            calls.append(detector_id)
            return self._good_row()

        with swap_attr(provenance_check, "_read_current_row", read):
            provenance_check.status(provenance.FILLERS)
            provenance_check.status(provenance.FILLERS)
        self.assertEqual(len(calls), 1)

    def test_stamp_for_unmapped_dimension_is_empty(self):
        """A dimension with no registered detector gets NOTHING — an honest
        absence, never a neighbour's version."""
        with self._with_row(self._good_row()):
            self.assertEqual(provenance_check.stamp("wpm"), {})

    def test_stamp_for_fillers_carries_both_fields(self):
        with self._with_row(self._good_row()):
            self.assertEqual(provenance_check.stamp("fillers"),
                             {"provenance": provenance.OK,
                              "detector_version": "fillers-v1"})

    def test_check_at_boot_never_raises(self):
        def boom(detector_id):
            raise RuntimeError("db down")
        with swap_attr(provenance_check, "_read_current_row", boom):
            provenance_check.check_at_boot()   # must not raise


class TestEvaluationStamping(unittest.TestCase):
    """db.record_dimension_evaluations carries the stamp — and survives a
    database that does not have the 0257 columns yet."""

    def setUp(self):
        provenance_check.reset_cache()
        from services.db import db
        self.db = db

    def tearDown(self):
        provenance_check.reset_cache()

    def _rows(self):
        return [
            {"dimension_id": "fillers", "snippet_id": "s1", "raw_value": 3.0},
            {"dimension_id": "wpm", "snippet_id": "s1", "raw_value": 140.0},
        ]

    def _good_row(self):
        live = provenance.live_definition(provenance.FILLERS)
        return {"version": "fillers-v1",
                "definition_hash": provenance.definition_hash(live)}

    def test_fillers_row_is_stamped_others_are_not(self):
        client = FakeSupabaseClient({"dimension_evaluations": []})
        with swap_attr(self.db, "client", client), \
                swap_attr(provenance_check, "_read_current_row",
                          lambda d: self._good_row()):
            n = self.db.record_dimension_evaluations(self._rows())
        self.assertEqual(n, 2)
        payload = client.tables["dimension_evaluations"].payload
        by_dim = {p["dimension_id"]: p for p in payload}
        self.assertEqual(by_dim["fillers"].get("provenance"), provenance.OK)
        self.assertEqual(by_dim["fillers"].get("detector_version"),
                         "fillers-v1")
        self.assertNotIn("provenance", by_dim["wpm"])
        self.assertNotIn("detector_version", by_dim["wpm"])

    def test_missing_columns_retries_unstamped(self):
        """0257 not applied: the measurements land WITHOUT the stamp rather
        than not at all. Provenance protects the data; it never gates it."""
        attempts = []

        def run(q):
            # dict-copy: the retry strips the SAME payload dicts in place,
            # so a by-reference capture would show attempt 1 already clean.
            attempts.append([dict(p) for p in q.payload])
            if len(attempts) == 1:
                raise Exception(
                    'column "provenance" of relation '
                    '"dimension_evaluations" does not exist')
            return []

        client = FakeSupabaseClient({"dimension_evaluations": run})
        with swap_attr(self.db, "client", client), \
                swap_attr(provenance_check, "_read_current_row",
                          lambda d: self._good_row()):
            n = self.db.record_dimension_evaluations(self._rows())
        self.assertEqual(n, 2)
        self.assertEqual(len(attempts), 2)
        self.assertTrue(any("provenance" in p for p in attempts[0]))
        self.assertFalse(any("provenance" in p for p in attempts[1]))
        self.assertFalse(any("detector_version" in p for p in attempts[1]))

    def test_stamp_failure_never_breaks_the_write(self):
        def boom(dimension_id):
            raise RuntimeError("anything")
        client = FakeSupabaseClient({"dimension_evaluations": []})
        with swap_attr(self.db, "client", client), \
                swap_attr(provenance_check, "stamp", boom):
            n = self.db.record_dimension_evaluations(self._rows())
        self.assertEqual(n, 2)


class TestSnippetGrainDoesNotClaimTheRecordingGrain(unittest.TestCase):
    """23505, found in production 2026-08-12::

        Key (recording_id, dimension_id, benchmark_version)
          = (97d982ea…, wpm, measure-v1) already exists.
        violates unique constraint "uq_dimension_evaluations_rec_dim_ver"

    `_windowed_rate_rows` sets snippet_id AND recording_id, so seven windows
    of one recording produce seven rows sharing a (recording_id,
    dimension_id, benchmark_version). The upsert's arbiter names the SNIPPET
    index, so Postgres never treats the recording-grain violation as a
    conflict to resolve — it raises, and a best-effort writer swallows it.
    That is why this table kept staying empty.

    0249 designed the way out: storage is snippet grain and the
    recording-grain index is PARTIAL (`WHERE recording_id IS NOT NULL`), which
    only works if snippet rows leave the column NULL.
    """

    def setUp(self):
        from services.db import db
        self.db = db

    def _write(self, rows):
        client = FakeSupabaseClient({"dimension_evaluations": []})
        with swap_attr(self.db, "client", client):
            n = self.db.record_dimension_evaluations(rows)
        return n, client.tables["dimension_evaluations"].payload

    def test_a_snippet_row_writes_a_NULL_recording_id(self):
        n, payload = self._write([
            {"dimension_id": "wpm", "snippet_id": "s1",
             "recording_id": "rec-1", "session_id": "sess-1",
             "raw_value": 140.0},
        ])
        self.assertEqual(n, 1)
        self.assertIsNone(payload[0]["recording_id"])
        # The anchor and the analysis grain both survive: has_anchor is
        # satisfied by snippet_id, and session_id is what every reader uses.
        self.assertEqual(payload[0]["snippet_id"], "s1")
        self.assertEqual(payload[0]["session_id"], "sess-1")

    def test_many_windows_of_ONE_recording_no_longer_collide(self):
        # The exact production shape: several rows, one recording, one
        # dimension. Before the fix every one of them carried the same
        # recording_id and the second insert raised 23505.
        rows = [{"dimension_id": "wpm", "snippet_id": f"s{i}",
                 "recording_id": "rec-1", "session_id": "sess-1",
                 "raw_value": 100.0 + i} for i in range(7)]
        n, payload = self._write(rows)
        self.assertEqual(n, 7)
        self.assertTrue(all(p["recording_id"] is None for p in payload))
        # …and they remain distinct on the arbiter the upsert actually names.
        keys = {(p["snippet_id"], p["dimension_id"], p["benchmark_version"])
                for p in payload}
        self.assertEqual(len(keys), 7)

    def test_a_RECORDING_grain_row_keeps_its_recording_id(self):
        # Nulling is scoped to rows that have a finer anchor. A row whose only
        # anchor IS the recording must keep it, or it loses its anchor
        # entirely and ck_dimension_evaluations_has_anchor rejects it.
        n, payload = self._write([
            {"dimension_id": "wpm", "recording_id": "rec-1",
             "raw_value": 140.0},
        ])
        self.assertEqual(n, 1)
        self.assertEqual(payload[0]["recording_id"], "rec-1")
        self.assertIsNone(payload[0]["snippet_id"])


class TestLabelRevision(unittest.TestCase):
    """The append-only shadow of upsert_state_rating."""

    def setUp(self):
        from services.db import db
        self.db = db

    def _rate(self, client, **kw):
        with swap_attr(self.db, "client", client):
            return self.db.upsert_state_rating(
                snippet_id="11111111-1111-1111-1111-111111111111",
                row={"state_id": "confidence", "value": "yes",
                     "unrateable": False, "saw_model_output": False},
                rater_id="22222222-2222-2222-2222-222222222222",
                lane="coach", **kw)

    def test_revision_appended_alongside_the_upsert(self):
        def revision_table(q):
            last = q.calls[-1][0]
            if last == "insert":
                return []
            return [{"id": 7}]        # the newest prior revision

        client = FakeSupabaseClient({"confidence_labels": [],
                                     "label_revision": revision_table})
        self.assertTrue(self._rate(client))
        row = client.tables["label_revision"].payload
        self.assertIsNotNone(row, "no revision row was inserted")
        self.assertEqual(row["value"], "yes")
        self.assertEqual(row["origin"], "live")
        self.assertEqual(row["supersedes_id"], 7)
        self.assertEqual(row["state_id"], "confidence")
        self.assertFalse(row["saw_model_output"])
        # The judgment's own timestamp rides along; created_at is the DB's.
        self.assertTrue(row["rated_at"])

    def test_missing_table_never_unsucceeds_the_rating(self):
        """0258 not applied: the rating write is the load-bearing one."""
        def missing(q):
            raise Exception('relation "public.label_revision" does not exist')

        client = FakeSupabaseClient({"confidence_labels": [],
                                     "label_revision": missing})
        self.assertTrue(self._rate(client))

    def test_first_revision_has_no_supersedes(self):
        client = FakeSupabaseClient({"confidence_labels": [],
                                     "label_revision": []})
        self.assertTrue(self._rate(client))
        row = client.tables["label_revision"].payload
        self.assertIsNone(row["supersedes_id"])


if __name__ == "__main__":
    unittest.main()
