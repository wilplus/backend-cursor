"""The coach's own words in doors 2, 3 and 4 (Privacy/Terms 3.5, signed by
the founder 2026-10-08, decisions log N68; migration 0459).

Pins:
  * every door knows both coach-word surfaces, and each still opens for one
    only when its switch is on AND the founder named it: named vs not named,
    door by door (release, training, promotion), fail closed;
  * the speaker's yes governs: both surfaces need it at the stamp, at the
    weekly refresh and at release; a pair with no yes, or a yes withdrawn
    since it was stamped, never leaves, whatever the door says;
  * a coach-word pair carries the prompt its drafter kept; a training
    example and a golden evaluation rebuild the drafter's prompt from it
    verbatim, and a pair without it is never an example or a golden moment;
  * the config sets name neither coach-word surface today (the switch is a
    separate reviewed change);
  * the migration widens the four door tables and the promote RPC to the
    two surfaces, and adds the drafter's snapshot columns, idempotently.
"""
from __future__ import annotations

import json
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest import mock

from services import coach_word_pairs as cwp
from services import feedback_pairs as fp
from services import golden_evaluation as ge
from services import golden_set as gs
from services import learning_ledger as ll
from services import model_promotion as mp
from services import model_training as mt
from services import pair_consent as pc
from services import pair_release as pr
from tests.test_doors_three_and_four import (
    _Config as _Config34, _Db as _Db34, _open3, _open4, _Provider,
)
from tests.test_pair_release import (
    _Config as _Config2, _Db as _Db2, _Storage, _open as _open2, _pair as _pair2,
)

ROOT = Path(__file__).resolve().parents[1]
COACH_WORDS = ("coach_moment_line", "coach_take_word")
NOW = datetime(2026, 10, 8, 9, 0, tzinfo=timezone.utc)
WEEK = date(2026, 10, 5)


def _snapshot(passage="so the figure was about nine million and we held it there",
              notes="liked the pause"):
    return cwp.prompt_snapshot(transcript=passage, coach_text=notes)


def _word_pair(i, surface="coach_take_word", owner="o-1", snapshot=True, **over):
    snap = _snapshot(passage=f"so the figure was about {i} million and we held it there") \
        if snapshot else {"passage_text": None, "prompt_context": None}
    row = {"id": f"pair-{i}", "surface": surface, "draft_text": f"draft {i}",
           "final_text": f"you held the pause before the number {i}", "final_kind": "final",
           **snap, "owner_principal_id": owner, "releasable": True, "release_id": "rel-1",
           "trained_run_id": None, "created_at": "2026-10-01T00:00:00+00:00"}
    row.update(over)
    return row


class TheDoorsKnowBothSurfaces(unittest.TestCase):
    def test_every_door_surface_needs_the_speakers_yes(self):
        self.assertEqual(set(fp.DOOR_SURFACES), set(fp.SURFACES))
        for surface in COACH_WORDS:
            self.assertIn(surface, fp.DOOR_SURFACES)
            self.assertIn(surface, pc.CONSENT_REQUIRED_SURFACES)
        self.assertLessEqual(set(fp.DOOR_SURFACES), set(pc.CONSENT_REQUIRED_SURFACES))
        self.assertLessEqual(set(fp.DOOR_SURFACES), set(gs.PAIR_SURFACES))

    def test_the_config_sets_name_both_surfaces(self):
        # Named 2026-10-08 (founder: "turn it all ON"; 3.5 signed, N68).
        from config import Config
        for name in ("PAIR_RELEASE_SURFACES", "TRAINING_SURFACES", "PROMOTION_SURFACES"):
            self.assertLessEqual(set(COACH_WORDS), set(getattr(Config, name)), name)

    def test_the_comments_cite_the_signature_not_a_lawyer(self):
        for path in ("services/feedback_pairs.py", "services/coach_word_pairs.py",
                     "services/ml_surface_contracts.py", "services/pair_consent.py"):
            text = (ROOT / path).read_text(encoding="utf-8")
            self.assertNotIn("qualified lawyer", text, path)
            self.assertIn("N68", text, path)


class DoorTwo(unittest.TestCase):
    def test_named_vs_not_named(self):
        for surface in COACH_WORDS:
            self.assertIn("door 2 closed", pr.why_not(_Config2(), surface))
            self.assertIn("no founder sentence", pr.why_not(_open2("praise_line"), surface))
            self.assertIsNone(pr.why_not(_open2(surface), surface))
            self.assertEqual(pr.authorised_surfaces(_open2(surface)), frozenset({surface}))
        # An unknown name is never authorised, whatever the set says.
        self.assertEqual(pr.authorised_surfaces(_open2("coach_note_v9")), frozenset())

    def _coach_pairs(self, surface):
        return [{**_pair2(i, owner=owner), "surface": surface}
                for i, owner in ((1, "p-1"), (2, "p-2"))]

    def test_a_named_coach_word_surface_leaves_with_the_yes(self):
        for surface in COACH_WORDS:
            db = _Db2(pairs=self._coach_pairs(surface))
            storage = _Storage()
            out = pr.export_surface(db, storage, surface=surface, week_start=WEEK,
                                    config=_open2(surface), now=NOW)
            self.assertEqual(out["exported"], 2, out)
            self.assertEqual(db.releases[0]["surface"], surface)
            body = next(v for (b, k), v in storage.objects.items() if k.endswith("pairs.jsonl"))
            lines = [json.loads(line) for line in body.decode().splitlines()]
            self.assertEqual({line["surface"] for line in lines}, {surface})
            self.assertTrue(all(line["consent_state"] == "yes" for line in lines))

    def test_not_named_nothing_is_written(self):
        for surface in COACH_WORDS:
            db = _Db2(pairs=self._coach_pairs(surface))
            storage = _Storage()
            out = pr.export_surface(db, storage, surface=surface, week_start=WEEK,
                                    config=_open2("praise_line"), now=NOW)
            self.assertEqual(out["exported"], 0)
            self.assertIn("no founder sentence", out["why"])
            self.assertEqual((db.releases, storage.puts), ([], []))

    def test_never_released_without_the_speakers_yes(self):
        """No yes at all, and a yes withdrawn since the pair was stamped
        (the stamp said yes; the grant in force now is gone)."""
        for surface in COACH_WORDS:
            db = _Db2(pairs=self._coach_pairs(surface), grants={})
            storage = _Storage()
            out = pr.export_surface(db, storage, surface=surface, week_start=WEEK,
                                    config=_open2(surface), now=NOW)
            self.assertEqual(out["exported"], 0)
            self.assertEqual(out["eligibility"]["excluded"], {"no_current_yes": 2})
            self.assertEqual((db.releases, storage.puts), ([], []))
            # p-2 withdrew: only p-1's pair leaves.
            db = _Db2(pairs=self._coach_pairs(surface), grants={"p-1": "training-v1"})
            out = pr.export_surface(db, _Storage(), surface=surface, week_start=WEEK,
                                    config=_open2(surface), now=NOW)
            self.assertEqual(out["exported"], 1)
            self.assertEqual(db.marked[0][1], ["pair-1"])

    def test_the_refresh_names_both_surfaces(self):
        db = _Db2()
        pc.refresh(db)
        self.assertTrue(set(COACH_WORDS) <= set(db.refreshed_with))


class TheStamp(unittest.TestCase):
    def _db(self, active):
        db = mock.Mock()
        db.get_owner_principal_for_user.return_value = {"id": "p-1"}
        db.get_mlc2_training_consent_status.return_value = (
            {"active": True, "grant_event_id": "g1", "consent_policy_version": "training-only-v2"}
            if active else {"active": False})
        return db

    def test_yes_and_no(self):
        for surface in COACH_WORDS:
            with mock.patch("services.account_deletion.learning_stopped", return_value=False):
                yes = pc.stamp(self._db(True), surface=surface, owner_user_id="u1")
            self.assertEqual((yes["consent_state"], yes["releasable"]), ("yes", True))
            no = pc.stamp(self._db(False), surface=surface, owner_user_id="u1")
            self.assertEqual((no["consent_state"], no["releasable"]), ("no", False))
            nobody = pc.stamp(mock.Mock(**{"get_owner_principal_for_user.return_value": None}),
                              surface=surface, owner_user_id="u1")
            self.assertEqual((nobody["consent_state"], nobody["releasable"]), ("unknown", False))


class _PairDb:
    def __init__(self):
        self.pairs: list[dict] = []

    def insert_feedback_pair(self, **fields):
        self.pairs.append(fields)
        return {"id": f"fp-{len(self.pairs)}", **fields}

    def v2_get_session_by_id(self, take):
        return {"user_id": "owner-1"}


class TheKeptPrompt(unittest.TestCase):
    def test_the_pair_carries_the_drafters_snapshot_and_nothing_else(self):
        db = _PairDb()
        snap = _snapshot()
        word = {"id": "w-1", "take_session_id": "t", "draft_text": "Keep that pace.",
                "draft_model_version": "m1", "draft_prompt": snap}
        with mock.patch("services.pair_consent.stamp", return_value={}):
            cwp.record_take_word_pair(db, word_row=word, coach_id="c", final_text="Keep the pace.")
            # A draft from before 0459 kept nothing: no passage, so it never
            # leaves (list_releasable_pairs needs one), is never judged and
            # never trains.
            cwp.record_take_word_pair(db, word_row={**word, "id": "w-2", "draft_prompt": None},
                                      coach_id="c", final_text="Keep the pace.")
            # The moment line never borrows the clip's transcript either.
            db.get_snippets_by_session = lambda take: [{"id": "s1", "transcript": "the clip"}]
            cwp.record_moment_line_pair(
                db, request_row={"id": "r-1", "draft_surface": "coach_moment_line",
                                 "draft_text": "A warm line.", "snippet_id": "s1",
                                 "take_session_id": "t", "owner_user_id": "owner-1"},
                coach_id="c", final_text="A warmer line.")
        self.assertEqual(db.pairs[0]["passage_text"], snap["passage_text"])
        self.assertEqual(db.pairs[0]["prompt_context"],
                         {"prompt": "coach_word_drafts", "coach_text": "liked the pause"})
        self.assertIsNone(db.pairs[1]["passage_text"])
        self.assertIsNone(db.pairs[2]["passage_text"])

    def test_the_drafter_keeps_what_its_prompt_was_given(self):
        class _Db:
            word = None

            def list_bookmarked_snippet_ids(self, take):
                return ["s1"]

            def get_own_state_ratings_for_session(self, take, coach):
                return {"s1": "yes"}

            def get_snippets_by_session(self, take):
                return [{"transcript": "  so   we held it "}]

            def set_coach_take_word_draft(self, **kw):
                self.word = kw
        db = _Db()
        with mock.patch.object(cwp, "word_pairs_enabled", return_value=True), \
             mock.patch.object(cwp, "compose", return_value={"text": "Keep it.", "model_version": "m"}) as composed:
            status, _ = cwp.draft_take_word(db, take_session_id="t", coach_id="c",
                                            body={"notes": " the pause "})
        self.assertEqual(status, 200)
        self.assertEqual(db.word["prompt"], {"passage_text": "so we held it",
                                             "prompt_context": {"prompt": "coach_word_drafts",
                                                                "coach_text": "the pause"}})
        kept = cwp.prompt_from("coach_take_word", db.word["prompt"]["passage_text"],
                               db.word["prompt"]["prompt_context"])
        from services.prompts.coach_word_drafts import SYSTEM, user
        self.assertEqual(kept, (SYSTEM["coach_take_word"],
                                user(surface="coach_take_word",
                                     transcript=cwp.passage_for(composed.call_args.kwargs["transcript"]),
                                     coach_text=composed.call_args.kwargs["coach_text"])))

    def test_a_long_passage_rebuilds_to_itself(self):
        snap = cwp.prompt_snapshot(transcript="word " * 400, coach_text=None)
        self.assertFalse(snap["passage_text"].endswith(" "))
        self.assertEqual(" ".join(snap["passage_text"].split()), snap["passage_text"])


class DoorThree(unittest.TestCase):
    def test_example_is_the_drafters_prompt_verbatim(self):
        from services.prompts.coach_word_drafts import SYSTEM, user
        for surface in COACH_WORDS:
            pair = _word_pair(1, surface=surface)
            example = mt.example_for(pair)
            self.assertEqual(example["messages"][0]["content"], SYSTEM[surface])
            self.assertEqual(example["messages"][1]["content"],
                             user(surface=surface, transcript=pair["passage_text"],
                                  coach_text="liked the pause"))
            self.assertEqual(example["messages"][2]["content"], pair["final_text"])

    def test_no_kept_prompt_no_example(self):
        for surface in COACH_WORDS:
            self.assertIsNone(mt.example_for(_word_pair(1, surface=surface, snapshot=False)))
            # A clip-derived context (an answer surface's) is not this prompt.
            self.assertIsNone(mt.example_for(_word_pair(
                1, surface=surface, prompt_context={"kind": "error", "pattern_key": None})))

    def test_named_vs_not_named(self):
        for surface in COACH_WORDS:
            self.assertIn("door 3 closed", mt.why_not(_Config34(), surface))
            self.assertIn("no founder sentence", mt.why_not(_open3("praise_line"), surface))
            self.assertIsNone(mt.why_not(_open3(surface), surface))
            db = _Db34(pairs=[_word_pair(i, surface=surface) for i in range(300)])
            out = mt.start_run(db, _Provider(), surface=surface, config=_open3("praise_line"), now=NOW)
            self.assertFalse(out["started"])
            self.assertIn("no founder sentence", out["why"])

    def test_a_named_surface_trains_on_the_kept_prompts(self):
        surface = "coach_moment_line"
        db = _Db34(pairs=[_word_pair(i, surface=surface, owner=f"o-{i % 9}") for i in range(260)])
        for i in range(50):
            gs.record(db, surface=surface, judge="founder@w.com",
                      body={"snippet_id": f"pair-{i}", "value": "yes" if i < 25 else "no"})
        gs.seal(db, surface=surface, judge="founder@w.com")
        provider = _Provider()
        out = mt.start_run(db, provider, surface=surface, config=_open3(surface), now=NOW)
        self.assertTrue(out["started"], out)
        self.assertEqual(db.runs[0]["surface"], surface)
        first = json.loads(provider.uploads[0][1].decode().splitlines()[0])
        from services.prompts.coach_word_drafts import SYSTEM
        self.assertEqual(first["messages"][0]["content"], SYSTEM[surface])


class TheGoldenSet(unittest.TestCase):
    def test_only_pairs_with_a_kept_prompt_are_judged(self):
        for surface in COACH_WORDS:
            db = _Db34(pairs=[_word_pair(1, surface=surface, snapshot=False),
                              _word_pair(2, surface=surface)])
            moment = gs.next_moment(db, surface=surface, judge="f")
            self.assertEqual(moment["snippet_id"], "pair-2")
            self.assertNotIn("draft 2", json.dumps(moment))
            with self.assertRaises(gs.GoldenRefusal):
                gs.record(db, surface=surface, judge="f",
                          body={"snippet_id": "pair-1", "value": "yes"})
            gs.record(db, surface=surface, judge="f", body={"snippet_id": "pair-2", "value": "yes"})
            self.assertEqual(db.judgements[-1]["prompt_context"]["prompt"], "coach_word_drafts")
            self.assertEqual(gs.counts(db, surface=surface)["kind"], "pair")

    def test_the_evaluation_runs_the_coach_word_drafter(self):
        surface = "coach_take_word"
        db = _Db34(pairs=[_word_pair(i, surface=surface) for i in range(50)])
        for i in range(50):
            gs.record(db, surface=surface, judge="founder@w.com",
                      body={"snippet_id": f"pair-{i}", "value": "yes" if i < 25 else "no"})
        gs.seal(db, surface=surface, judge="founder@w.com")
        seen = []

        def compose_words(*, surface, transcript, coach_text, user_id=None):
            from services.ml_surface_contracts import active_evaluation_override
            seen.append(coach_text)
            if active_evaluation_override(surface):
                i = transcript.split()[5]
                return {"text": f"you held the pause before the number {i}"}
            return {"text": "nice"}
        with mock.patch.object(cwp, "compose", side_effect=compose_words):
            out = ge.evaluate(db, surface=surface, candidate_model="ft:w",
                              baseline_model="stock", now=NOW)
        self.assertTrue(out["passed"], out["report"])
        self.assertEqual(set(seen), {"liked the pause"})
        self.assertEqual(db.reports[0]["surface"], surface)


class DoorFour(unittest.TestCase):
    def _db(self, surface):
        from services.ml_surface_contracts import locked_prompt_hash
        db = _Db34()
        db.runs.append({"id": "run-1", "surface": surface, "status": "succeeded",
                        "candidate_model": "ft:w"})
        db.reports.append({"id": "rep-1", "surface": surface, "candidate_model": "ft:w",
                           "passed": True, "run_id": "run-1",
                           "prompt_lock_sha256": locked_prompt_hash(surface)})
        return db

    def test_named_vs_not_named(self):
        for surface in COACH_WORDS:
            self.assertIn("door 4 closed", mp.why_not(_Config34(), surface))
            db = self._db(surface)
            with self.assertRaises(mp.PromotionRefusal) as refused:
                mp.promote(db, surface=surface, candidate_model="ft:w",
                           evaluation_report_id="rep-1", by="founder",
                           config=_open4("praise_line"))
            self.assertIn("no founder sentence", refused.exception.message)
            self.assertEqual(db.runtime, {})
            out = mp.promote(db, surface=surface, candidate_model="ft:w",
                             evaluation_report_id="rep-1", by="founder",
                             config=_open4(surface), now=NOW)
            self.assertEqual(db.runtime, {f"openai_surface_model_{surface}": "ft:w"})
            self.assertEqual(out["model"], "ft:w")
            mp.kill(db, surface=surface, by="founder", reason="tone", now=NOW)
            self.assertEqual(db.runtime[f"openai_surface_model_{surface}"], mp.stock_model())

    def test_an_unknown_surface_is_refused(self):
        self.assertIn("not a pair surface", mp.why_not(_open4("coach_note_v9"), "coach_note_v9"))

    def test_the_runtime_keys_are_allowlisted(self):
        from services.runtime_model_gate import MODEL_CONFIG_KEYS
        sql = (ROOT / "migrations/the_coach_s_words_reach_the_doors.sql").read_text(encoding="utf-8")
        for surface in COACH_WORDS:
            key = f"openai_surface_model_{surface}"
            self.assertIn(key, MODEL_CONFIG_KEYS)
            self.assertIn(f"'{key}'", sql)


class TheLedger(unittest.TestCase):
    def test_doors_three_and_four_list_their_named_surfaces(self):
        c = _open3("coach_take_word")
        c.PROMOTION_SURFACES = frozenset({"coach_moment_line"})
        doors = ll.doors(c)
        self.assertEqual(doors["training"]["surfaces"], ["coach_take_word"])
        self.assertEqual(doors["promotion"]["surfaces"], ["coach_moment_line"])

    def test_the_pace_panel_has_a_jar_per_coach_word_surface(self):
        from services.learning_pace import JARS
        ids = {jar[0] for jar in JARS}
        for surface in COACH_WORDS:
            self.assertIn(f"pairs.{surface}", ids)


class TheMigration(unittest.TestCase):
    SQL = (ROOT / "migrations/the_coach_s_words_reach_the_doors.sql").read_text(encoding="utf-8")

    def test_it_is_in_the_manifest(self):
        manifest = (ROOT / "migrations/manifest.txt").read_text(encoding="utf-8")
        self.assertIn("0459\tthe_coach_s_words_reach_the_doors.sql", manifest)

    def test_the_four_door_tables_widen_idempotently(self):
        for table in ("pair_releases", "fine_tune_runs", "evaluation_reports", "model_promotions"):
            self.assertIn(f"DROP CONSTRAINT IF EXISTS {table}_surface_check", self.SQL)
            self.assertIn(f"ADD CONSTRAINT {table}_surface_check", self.SQL)
        self.assertEqual(self.SQL.count("'coach_moment_line', 'coach_take_word'));"), 4)

    def test_the_snapshot_columns_and_aliases(self):
        for table in ("exercise_coach_requests", "coach_take_words"):
            self.assertIn(f"ALTER TABLE public.{table}\n    ADD COLUMN IF NOT EXISTS draft_prompt jsonb NULL",
                          self.SQL)
        self.assertIn("ON CONFLICT (alias) DO NOTHING", self.SQL)
        self.assertNotIn("DROP TABLE", self.SQL.upper())
        self.assertNotIn("DELETE FROM", self.SQL.upper())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
