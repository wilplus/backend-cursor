"""THE F1 LOOP CONTRACT — what the pipeline work may not break.

FOUNDER, 2026-09-22, before releasing five parallel agent sessions onto the
provenance audit: "how can we do it so that the two things collaborate and
step by step sort of talk to each other and check if nothing got broken?"

This file is that mechanism, and it is deliberately a TEST and not a
document. Five parallel sessions will not read a document. They will run
the gate, because the gate is what stops their pull request merging. So the
protection lives inside the gate.

WHAT EACH LINE IS. One assertion, named in the words the founder used, over
the behaviour this week established. Every line is either

  GREEN  — true today, and a pipeline change that breaks it turns this file
           red and cannot merge; or
  XFAIL  — false today because the audit found a real defect, marked strict
           and tagged with its finding id.

STRICT IS THE WHOLE TRICK. `xfail(strict=True)` fails the suite when the
test starts PASSING. So the workstream that closes a finding is mechanically
forced to come here and flip its line, and cannot quietly close a finding
the contract still believes is open. Neither side has to remember the other
exists: one writes the fix, the gate notices.

WHAT THIS FILE IS NOT. It is not the audit, and it does not restate it. It
holds only the handful of behaviours a speaker would FEEL — bookmarks that
arrive and stay answered, a document that is never rebuilt, a wait that
never lies, no number on a user's screen. The audit's ninety-eight findings
have their own regression tests, named per finding, in their own files.

Unit tier on purpose: no database, no network, so it runs on every pull
request in this repository rather than only on the ones that touch
migrations. The database-bound half of the same contract lives in
`test_ideal_text_feedback_bake_postgres.py` (the stored bookmark set and
its freshness rule) and runs in the rehearsal tier.

Its ledger — which workstream flipped which line, and when — is
`docs/PIPELINE_WORK_LEDGER.md`.
"""
from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import Mock

import pytest

for _module in ("supabase", "sentry_sdk"):
    if _module not in sys.modules:
        sys.modules[_module] = types.ModuleType(_module)
if not hasattr(sys.modules["supabase"], "create_client"):
    sys.modules["supabase"].create_client = lambda *a, **k: None
    sys.modules["supabase"].Client = object
if not hasattr(sys.modules["sentry_sdk"], "capture_exception"):
    sys.modules["sentry_sdk"].capture_exception = lambda *a, **k: None

from services.degradation import DegradationLog  # noqa: E402
from services.ideal_text_changes import ChangesDeps  # noqa: E402

ARC = "arc-contract"
TAKE = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
SNIPPET = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
DOC = "We started small. And then we shipped it fast."


# ══════════════════════════════════════════════════════════════════════════
#  1. THE BOOKMARKS ARRIVE, AND THEY ARE THE ONES THAT WERE FROZEN
# ══════════════════════════════════════════════════════════════════════════


def _v3_row(snippet_id: str = SNIPPET) -> dict:
    """One served V3 Confident Voice row, in the shape the service emits."""
    return {
        "id": f"cand:{snippet_id}",
        "kind": "moment",
        "source": "mlc3_service",
        "feedback_family": "confident_voice",
        "snippet_id": snippet_id,
    }


def _v2_frozen_set() -> dict:
    """A set frozen under V2's exactly-three rule, before the V3 cutover.

    Every document opened before 2026-09-18 carries one of these, and the
    claim is insert-once, so they keep it forever.
    """
    return {
        "selected_keys": [
            {"id": "v2-cv", "feedback_family": "confident_voice"},
            {"id": "v2-rw", "feedback_family": "rewrite_clarity"},
            {"id": "v2-gf", "feedback_family": "great_formulation"},
        ],
    }


class _ContractDb:
    """The reads `_claim_or_filter` makes, and nothing else."""

    def __init__(self, session=None):
        self.session = session or {"id": TAKE, "take_index": 1}
        self.exposures: list[dict] = []

    def v2_get_session_by_id(self, sid):
        return dict(self.session) if sid == TAKE else {}

    def insert_take_feedback_exposure(self, **kwargs):
        self.exposures.append(kwargs)
        return True

    def __getattr__(self, name):
        def _missing(*a, **k):
            raise AttributeError(f"_ContractDb has no {name}")
        return _missing


def _run(db):
    from services.ideal_text_changes import _ChangesRun
    return _ChangesRun(
        ARC, DOC, "user-1", TAKE, 1,
        ChangesDeps(
            database=db,
            first_client_repository=None,
            applied_map=lambda ids: {},
            playback_map=lambda ids: {},
            previous_spoken_session=lambda arc_id, sid: None,
            locked_parts=lambda arc_id, user_id, text: [],
            with_evidence_coordinates=lambda rows, **k: rows,
            record_arms=lambda result, sid, uid: None,
        ),
        DegradationLog("ideal_text"),
    )


def test_a_take_frozen_under_the_old_policy_still_shows_its_bookmarks():
    """THE ONE THE FOUNDER HAS FELT ALL WEEK.

    "bookmarks are gone again ... sometimes they do appear but then a while
    later they are gone." Every document opened before the V3 cutover holds
    a V2 frozen set, and the rows V3 now serves share no identity with it.

    Serving those Takes no marks at all is strictly worse than serving marks
    whose answers cannot be validated: they were already in the second
    situation, and the first is a blank page.

    Closed by WS2 (ws2-lineage-or-nothing). `_claim_or_filter` decides the
    superseded branch by whether the frozen set ADDRESSES the served rows —
    `take_feedback_set.frozen_set_addresses`, the same identity rule
    `filter_to_selected` uses — instead of by the `v3_replaced_changes`
    flag. A set that names none of them predates them, so the rows serve
    whole and nothing re-claims the insert-once row. Was xfail(strict) from
    2026-09-22 until then.
    """
    db = _ContractDb()
    run = _run(db)
    run.arm_sid = TAKE          # the live path always sets this
    run.take_contract_on = True
    run.feedback_set = _v2_frozen_set()
    run.changes = [_v3_row()]
    run.v3_replaced_changes = True

    run._claim_or_filter()

    assert [row["id"] for row in run.changes] == [f"cand:{SNIPPET}"], (
        "a Take frozen under the old policy served no bookmarks at all"
    )


def test_a_take_frozen_under_its_own_policy_is_still_filtered_to_it():
    """The guard the branch above exists for, and it must not be lost.

    When the served rows ARE the frozen ones, accepting item one may never
    reveal item four. Any fix for the line above has to keep this true.
    """
    from services.ideal_text_changes import _ChangesRun  # noqa: F401
    db = _ContractDb()
    run = _run(db)
    run.arm_sid = TAKE
    run.take_contract_on = True
    kept = {"id": "cand:kept", "kind": "moment", "source": "acoustic",
            "feedback_family": "confident_voice"}
    hidden = {"id": "cand:hidden", "kind": "moment", "source": "acoustic",
              "feedback_family": "confident_voice"}
    run.feedback_set = {"selected_keys": [kept]}
    run.changes = [kept, hidden]
    run.v3_replaced_changes = False

    run._claim_or_filter()

    assert [row["id"] for row in run.changes] == ["cand:kept"]


# ══════════════════════════════════════════════════════════════════════════
#  2. AN ANSWERED BOOKMARK STAYS ANSWERED
# ══════════════════════════════════════════════════════════════════════════


class TheAnswerSurvivesTheRead(unittest.TestCase):
    """Founder, 2026-09-21: "I have locked in a text I have judged as no
    confident; and then the state of the text didn't change and the bookmark
    state there; I would need to reload and wait."

    One rule decides whether an item is still open, and the page and the
    lock gate must ask the same one — otherwise the page shows a decided
    bookmark as open, or the lock refuses over an item the speaker settled.
    """

    def test_every_answer_decides_an_item_one_way_or_the_other(self):
        from services.ideal_text_changes import decided_status

        for answer in ("yes", "in_between", "no", "not_sure",
                       "audio_unclear"):
            with self.subTest(answer=answer):
                self.assertIn(decided_status(answer),
                              ("approved", "dismissed"))

    def test_an_unanswered_item_is_the_only_undecided_one(self):
        from services.ideal_text_changes import undecided

        rows = [
            {"id": "answered", "status": "approved"},
            {"id": "dismissed", "status": "dismissed"},
            {"id": "open"},
        ]
        self.assertEqual([row["id"] for row in undecided(rows)], ["open"])

    def test_the_lock_gate_asks_the_page_s_own_question(self):
        """Not "is there a rule" but "is it the SAME rule". Two copies
        drifting apart is how the lock started refusing over items the
        speaker had already judged."""
        import routes.v2.explore_ideal_text as route
        from services.ideal_text_changes import undecided

        self.assertIs(route.undecided, undecided)


# ══════════════════════════════════════════════════════════════════════════
#  3. THE DOCUMENT IS CREATED ONCE AND NEVER REBUILT
# ══════════════════════════════════════════════════════════════════════════


class TheOneCanonicalDocument(unittest.TestCase):
    """L1, and the founder's Option A of 2026-09-22 stated as behaviour."""

    @staticmethod
    def _db(existing):
        database = Mock()
        database.ideal_text.get_coach_arc_ideal_text.return_value = existing
        return database

    def test_a_project_with_no_document_gets_one_from_its_next_take(self):
        from services.ideal_text_confirmation import take_creates_ideal_text

        self.assertTrue(
            take_creates_ideal_text(self._db(None), ARC, 1))
        self.assertTrue(
            take_creates_ideal_text(self._db(None), ARC, 4))

    def test_a_project_WITH_a_document_never_has_it_rebuilt(self):
        """THE L1 PROOF. However the words got there — machine, speaker or
        coach — no later Take may touch them."""
        for existing in ({"auto_text": "Machine words"},
                         {"text": "Coach words"},
                         {"auto_text": "", "text": "The speaker's own"}):
            with self.subTest(existing=existing):
                from services.ideal_text_confirmation import (
                    take_creates_ideal_text,
                )
                self.assertFalse(
                    take_creates_ideal_text(self._db(existing), ARC, 2))

    def test_a_document_that_cannot_be_read_is_never_overwritten(self):
        from services.ideal_text_confirmation import take_creates_ideal_text

        database = Mock()
        database.ideal_text.get_coach_arc_ideal_text.side_effect = (
            RuntimeError("database is down"))
        self.assertFalse(take_creates_ideal_text(database, ARC, 2))


# ══════════════════════════════════════════════════════════════════════════
#  4. THE STORED BOOKMARK SET NEVER OUTLIVES AN ANSWER
# ══════════════════════════════════════════════════════════════════════════


class TheStoredSetKnowsAboutAnswers(unittest.TestCase):
    """The database half of this runs in the rehearsal tier
    (`test_ideal_text_feedback_bake_postgres.py`). What is asserted here is
    the rule's SOURCE: every route a speaker can answer through must be
    named in the freshness function, because a writer nobody enumerated is
    exactly how the first two were missed."""

    ANSWER_ROUTES = (
        "take_feedback_self_report",        # the legacy answer route
        "feedback_v3_owner_responses",      # the service answer route
        "intervention_decisions",           # a paragraph decision
        "user_suggestion_feedback",         # a tap on a suggestion
    )

    def test_the_freshness_rule_names_every_route_an_answer_takes(self):
        import pathlib

        root = pathlib.Path(__file__).resolve().parent.parent
        rule = (root / "migrations"
                / "the_bake_knows_about_answers_and_its_own_start.sql")
        body = rule.read_text(encoding="utf-8")
        for table in self.ANSWER_ROUTES:
            with self.subTest(table=table):
                self.assertIn(table, body)

    def test_the_computation_window_reaches_the_writer(self):
        """An answer committed while the Manager ran was never seen by it.
        The row is dated from when the computation STARTED, and the caller
        is the only thing that knows how long that was."""
        import inspect

        from services.db import DatabaseService

        signature = inspect.signature(
            DatabaseService.write_ideal_text_feedback_bake)
        self.assertIn("computed_over_ms", signature.parameters)


# ══════════════════════════════════════════════════════════════════════════
#  5. THE FIVE OWNER STATES SURVIVE THE WRITE
# ══════════════════════════════════════════════════════════════════════════


ANSWER_STATES = ("yes", "in_between", "no", "not_sure", "audio_unclear")


def test_the_page_offers_exactly_the_five_owner_states():
    """The Confident Voice question asks one thing and offers five answers.
    Anything that narrows this list narrows what a speaker can say."""
    from services.take_feedback_responses import RESPONSES

    assert RESPONSES["confident_voice"] == set(ANSWER_STATES)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "F-4 (audit, 2026-09-22): the routing derived from a Confident "
        "Voice answer collapses in_between and not_sure into one value on "
        "the way to the Voice Album route, so two different things a "
        "speaker said become the same record. The derivation is also "
        "inline in `routes/v2/user_sessions.py`, which is why no unit test "
        "could state it — the same reason `waitProgress`, `deckScroll` and "
        "`bookmarkMotion` each live in their own module. Closing F-4 means "
        "naming it (`album_routing_for` in `take_feedback_responses`) and "
        "keeping the five apart. Owner: the workstream that closes F-4."
    ),
)
def test_each_of_the_five_states_routes_as_itself():
    """A distinction the speaker can make and the record cannot keep is a
    distinction the product does not really offer."""
    from services.take_feedback_responses import album_routing_for

    routed = {album_routing_for(state) for state in ANSWER_STATES}
    assert len(routed) == len(ANSWER_STATES), (
        f"five answers routed into {len(routed)} stored values"
    )


# ══════════════════════════════════════════════════════════════════════════
#  6. NOTHING CHANGES THE SPEAKER'S WORDS WITHOUT A DECISION
# ══════════════════════════════════════════════════════════════════════════


@pytest.mark.xfail(
    strict=True,
    reason=(
        "LEGACY-1 (audit, blocker): the promotion script writes a model name "
        "into runtime_config and `llm.py` serves it on the very next request "
        "for Take 1 Ideal Text and Say It Stronger, with a 60-second cache "
        "and no gate reading MLC2_PROMOTION_ENABLED. A script can therefore "
        "change the words in a speaker's document with nobody deciding. "
        "Owner: the workstream that closes LEGACY-1. Flip this to a plain "
        "test when it does."
    ),
)
def test_a_promoted_model_cannot_reach_the_document_without_a_gate():
    """The only finding in the audit that can silently alter F1 output."""
    import inspect

    from services import llm

    source = inspect.getsource(llm)
    assert "MLC2_PROMOTION_ENABLED" in source, (
        "the serving path never consults the promotion gate"
    )


class TheDocumentIsTheSpeakersOwn(unittest.TestCase):
    def test_a_later_take_proposes_and_never_applies(self):
        """L1 again, at the other end: a later Take's review advances the
        version, and an owner edit at the previous version must come back
        byte for byte."""
        import inspect

        from services import take_review

        source = inspect.getsource(take_review.finalize_later_take_review)
        self.assertIn("get_user_ideal_edit", source)
        self.assertIn("owner_edit_before", source)


# ══════════════════════════════════════════════════════════════════════════
#  7. NO NUMBER REACHES A SPEAKER (AC-9)
# ══════════════════════════════════════════════════════════════════════════


class NoScoreReachesTheSpeaker(unittest.TestCase):
    """The fence that cannot be traded for anything. The read is
    qualitative; a score, ratio, verdict or classifier output never is."""

    BANNED = ("score", "ratio", "percentile", "confidence_value",
              "classifier", "probability", "z_score")

    def test_the_words_a_speaker_waits_on_name_work_not_judgement(self):
        """Every stage label the wait screen renders comes from here. They
        say what the machine is doing, never what it has concluded."""
        import inspect
        import re

        import services.analysis_worker as worker

        source = inspect.getsource(worker.run_full_analysis)
        emitted = re.findall(r'_emit\(progress,\s*"[a-z_]+",\s*\d+,\s*\n?\s*"([^"]+)"', source)
        self.assertTrue(emitted, "no stage labels found to check")
        for label in emitted:
            for banned in self.BANNED:
                with self.subTest(label=label, banned=banned):
                    self.assertNotIn(banned, label.lower())

    def test_the_stage_labels_a_speaker_reads_carry_no_verdict(self):
        """The wait screen's own words, checked here because the backend
        emits the stage names the screen renders."""
        import services.analysis_worker as worker
        import inspect

        source = inspect.getsource(worker.run_full_analysis)
        for banned in ("charisma", "stress score", "power_score ="):
            with self.subTest(banned=banned):
                self.assertNotIn(f'"{banned}"', source)


# ══════════════════════════════════════════════════════════════════════════
#  8. EVERY SERVICE THAT CAN DROP A WRITE SAYS WHAT IT READ
# ══════════════════════════════════════════════════════════════════════════


class EveryServiceReportsItsOwnConfig(unittest.TestCase):
    """CONFIG-FIRST, as a test rather than a habit.

    Railway variables are per service, and the worst case is a WRITER
    service missing one: the app looks healthy while background work
    silently drops what it should be saving. The rule says verify from each
    service's boot log rather than the panel, which only works if each
    service actually prints it.

    It did not. The founder searched the worker's log for the line on
    2026-09-22 and found nothing, because the line lived in `app.py` and the
    worker runs `worker.py`. The one service whose setting is invisible from
    outside was the one that could not report it.
    """

    ENTRYPOINTS = ("app.py", "worker.py")

    def test_both_entrypoints_report_the_stored_bookmark_set(self):
        import pathlib

        root = pathlib.Path(__file__).resolve().parent.parent
        for name in self.ENTRYPOINTS:
            with self.subTest(entrypoint=name):
                body = (root / name).read_text(encoding="utf-8")
                self.assertIn("stored bookmark set is", body)
                self.assertIn("_bake_enabled", body)

    def test_they_say_it_in_the_same_words(self):
        """One search across both services, or the check is two checks and
        somebody runs only the easy one."""
        import pathlib
        import re

        root = pathlib.Path(__file__).resolve().parent.parent
        phrasings = set()
        for name in self.ENTRYPOINTS:
            body = (root / name).read_text(encoding="utf-8")
            # Line-scoped: a comment two paragraphs away must not be read
            # as one enormous string literal.
            phrasings.update(re.findall(
                r'"([^"\n]*stored bookmark set[^"\n]*)"', body))
        self.assertEqual(len(phrasings), 2, phrasings)  # the ON/OFF line
                                                        # and the unreadable
                                                        # one, once each
