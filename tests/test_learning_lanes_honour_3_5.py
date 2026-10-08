"""The learning lanes keep what Privacy 3.5 promises (3.5 pack, file 22,
items E4 and E5; signed by the founder 2026-10-08).

Anything that learns across people uses a speaker's data only while that
speaker holds the training yes. The V4 coach sheets, the blind block pick
and the learned exercise order read it through ``services.pair_consent``,
the pairs' own consent read (the ledger's status under the active training
policy, and no learning for a person whose service is ending), never a rule
of their own. Each lane is pinned for a speaker who said yes, one who never
did, and one who withdrew; unreadable answers fail closed.

(E1/D1, the corpus copy copies no audio, is pinned in
tests/test_training_corpus.py.)
"""
from __future__ import annotations

import random
from datetime import datetime, timezone
from unittest import mock

import pytest

from services import coach_block_pick as bp
from services import pair_consent as pc
from services import v4_coach_sheets as cs

NOW = datetime(2026, 10, 8, tzinfo=timezone.utc)

#: take -> speaker principal; speaker -> the ledger's status today.
TAKES = {"t-yes": "p-yes", "t-no": "p-no", "t-gone": "p-gone"}


class _Ledger:
    """The ledger as the status RPC reads it: a withdrawal reads as not
    active, exactly like a speaker who never said yes."""

    def __init__(self):
        self.status = {"p-yes": {"active": True, "grant_event_id": "g1",
                                 "consent_policy_version": "training-only-v2"},
                       "p-no": {"active": False},
                       "p-gone": {"active": True, "grant_event_id": "g2",
                                  "consent_policy_version": "training-only-v2"}}

    def withdraw(self, principal):
        self.status[principal] = {"active": False}

    # the readers pair_consent uses
    def v2_get_session_by_id(self, take):
        if take not in TAKES:
            return None
        return {"id": take, "owner_principal_id": None, "project_id": f"proj-{take}",
                "user_id": f"u-{take}"}

    def get_project_owner_principal(self, project):
        return TAKES.get(project.removeprefix("proj-"), "")

    def get_owner_principal_for_user(self, user_id):
        return {"id": {"u-yes": "p-yes", "u-no": "p-no", "u-gone": "p-gone"}[user_id]} \
            if user_id in ("u-yes", "u-no", "u-gone") else None

    def get_mlc2_training_consent_status(self, principal):
        return self.status.get(principal, {"active": False})


@pytest.fixture(autouse=True)
def no_objection(monkeypatch):
    # 0454's reader needs a live client; here nobody objected unless a test says so.
    monkeypatch.setattr("services.error_presence_audit._objected", lambda db, take: False)


# ── the shared read ──────────────────────────────────────────────────────

def test_yes_no_and_withdrawn_through_the_one_read():
    db = _Ledger()
    assert pc.take_holds_training_yes(db, "t-yes") is True
    assert pc.take_holds_training_yes(db, "t-no") is False
    assert pc.take_holds_training_yes(db, "t-gone") is True
    db.withdraw("p-gone")
    assert pc.take_holds_training_yes(db, "t-gone") is False
    assert pc.user_holds_training_yes(db, "u-yes") is True
    assert pc.user_holds_training_yes(db, "u-no") is False
    assert pc.user_holds_training_yes(db, "u-gone") is False


def test_every_doubt_reads_as_no():
    db = _Ledger()
    assert pc.take_holds_training_yes(db, "unknown-take") is False
    assert pc.take_holds_training_yes(db, "") is False
    assert pc.user_holds_training_yes(db, None) is False
    db.get_mlc2_training_consent_status = mock.Mock(side_effect=RuntimeError("down"))
    assert pc.take_holds_training_yes(db, "t-yes") is False
    db = _Ledger()
    db.v2_get_session_by_id = mock.Mock(side_effect=RuntimeError("down"))
    assert pc.take_holds_training_yes(db, "t-yes") is False


def test_a_person_whose_service_is_ending_has_no_yes():
    db = _Ledger()
    with mock.patch("services.account_deletion.learning_stopped", return_value=True):
        assert pc.take_holds_training_yes(db, "t-yes") is False


def test_the_takes_own_principal_comes_first_then_the_project():
    db = _Ledger()
    db.v2_get_session_by_id = lambda take: {"owner_principal_id": "p-yes",
                                            "project_id": "proj-t-no"}
    assert pc.take_principal(db, "anything") == "p-yes"


def test_an_objection_to_the_blind_check_keeps_a_yes_speaker_off_a_sheet(monkeypatch):
    db = _Ledger()
    assert pc.take_may_reach_a_coach_sheet(db, "t-yes") is True
    monkeypatch.setattr("services.error_presence_audit._objected", lambda db, take: True)
    assert pc.take_may_reach_a_coach_sheet(db, "t-yes") is False


def test_the_lanes_add_no_consent_logic_of_their_own():
    """One boundary (CLAUDE.md): the lanes call pair_consent, never the
    ledger or a policy version directly."""
    import inspect

    from services import exercise_learned_order as lo
    for module in (cs, bp, lo):
        source = inspect.getsource(module)
        for direct in ("get_mlc2_training_consent_status", "consent_policy_version",
                       "training-only-v"):
            assert direct not in source, (module.__name__, direct)


# ── E4: the V4 coach sheets ──────────────────────────────────────────────

class _SheetDb(_Ledger):
    def __init__(self):
        super().__init__()
        self.sheets: list[dict] = []
        self.surer: list[dict] = []

    def list_takes_coach_is_walking(self, rater):
        return []

    def list_recent_v3_frames(self, limit=200):
        return [{"take_session_id": take, "frame": {"blocks": [
            {"block_id": "b1", "snippet_ids": [f"{take}-a", f"{take}-b"]}]}}
            for take in TAKES]

    def list_v4_picks(self, take):
        return [{"block_id": "b1", "sureness": 0.1, "v4_snippet_id": f"{take}-a",
                 "v3_snippet_id": f"{take}-b"}]

    def list_v4_pick_sheets(self, rater):
        return [s for s in self.sheets if s["rater_id"] == rater]

    def insert_v4_pick_sheet(self, row):
        row = {**row, "id": f"s{len(self.sheets)}"}
        self.sheets.append(row)
        return row

    def get_v4_pick_sheet(self, sheet_id, rater):
        return next((s for s in self.sheets if s["id"] == sheet_id), None)

    def answer_v4_pick_sheet(self, sheet_id, rater, clip, none):
        row = self.get_v4_pick_sheet(sheet_id, rater)
        row.update(answered_at="x")
        return row

    def list_v4_surer_sheets(self, rater):
        return [s for s in self.surer if s["rater_id"] == rater]

    def list_v4_surer_answers(self, limit=20000):
        return []

    def list_v4_willfidence_reads(self, take):
        return []

    def get_snippets_by_session(self, take):
        return [{"id": f"{take}-a", "transcript": "Um, I think we should, um, start."}]

    def insert_v4_surer_sheet(self, row):
        row = {**row, "id": f"r{len(self.surer)}"}
        self.surer.append(row)
        return row

    def get_v4_surer_sheet(self, sheet_id, rater):
        return next((s for s in self.surer if s["id"] == sheet_id), None)

    def answer_v4_surer_sheet(self, sheet_id, rater, answer, chosen, rejected):
        row = self.get_v4_surer_sheet(sheet_id, rater)
        row.update(answered_at="x")
        return row

    def list_coach_clip_exposures(self, *a, **k):
        return []

    def record_coach_clip_exposure(self, *a, **k):
        return True

    def get_snippet_by_id(self, clip):
        return {"transcript": f"words of {clip}", "audio_segment_path": None}


@pytest.fixture
def sheets_on(monkeypatch):
    from config import Config
    monkeypatch.setattr(Config, "V4_COACH_SHEETS_ENABLED", True, raising=False)
    monkeypatch.setattr(cs, "rater_role", lambda uid: "coach")


def test_only_yes_speakers_reach_a_pick_sheet_and_a_withdrawal_empties_it(sheets_on):
    db = _SheetDb()
    written = cs.fill_pick_sheets(db, rater_id="c1", week="w", rng=random.Random(1), now=NOW)
    assert sorted(w["take_session_id"] for w in written) == ["t-gone", "t-yes"]
    db.withdraw("p-gone")
    status, body = cs.pick_queue(db, rater_id="c1")
    assert status == 200
    served = {m["clip_id"].rsplit("-", 1)[0] for item in body["items"] for m in item["moments"]}
    assert served == {"t-yes"}
    gone = next(w for w in written if w["take_session_id"] == "t-gone")
    assert cs.pick_answer(db, rater_id="c1", sheet_id=gone["id"],
                          body={"none_needs_it": True})[0] == 404
    kept = next(w for w in written if w["take_session_id"] == "t-yes")
    assert cs.pick_answer(db, rater_id="c1", sheet_id=kept["id"],
                          body={"none_needs_it": True})[0] == 200


def test_a_due_repick_of_a_withdrawn_speaker_is_not_asked(sheets_on):
    db = _SheetDb()
    db.withdraw("p-gone")
    db.status["p-yes"] = {"active": False}
    old = {"id": "old", "rater_id": "c1", "take_session_id": "t-gone", "block_id": "b1",
           "clip_ids": ["t-gone-a", "t-gone-b"], "slice": "unsure", "week": "w0",
           "answered_at": "2026-09-22T00:00:00+00:00"}
    for seed in range(20):
        db.sheets = [old]
        assert cs.fill_pick_sheets(db, rater_id="c1", week="w", rng=random.Random(seed),
                                   now=NOW) == []


def test_only_yes_speakers_reach_a_surer_sheet_and_a_withdrawal_empties_it(sheets_on):
    db = _SheetDb()
    written = cs.fill_surer_sheets(db, rater_id="c1", week="w", rng=random.Random(1))
    assert sorted(w["take_session_id"] for w in written) == ["t-gone", "t-yes"]
    db.withdraw("p-gone")
    status, body = cs.surer_queue(db, rater_id="c1")
    assert status == 200 and len(body["items"]) == 1
    gone = next(w for w in written if w["take_session_id"] == "t-gone")
    assert cs.surer_answer(db, rater_id="c1", sheet_id=gone["id"],
                           body={"answer": "yes"})[0] == 404


# ── E4: the blind block pick ─────────────────────────────────────────────

class _PickDb(_Ledger):
    def __init__(self):
        super().__init__()
        self.picks: list[dict] = []

    def count_coach_blind_answers(self, coach, week):
        return 0

    def list_coach_block_picks_pending(self, coach):
        return [p for p in self.picks if not p.get("answered_at")]

    def list_coach_block_picks_by_coach(self, coach):
        return list(self.picks)

    def list_takes_coach_is_walking(self, coach):
        return []

    def list_recent_v3_frames(self, limit=200):
        def block(take):
            return {"block_id": f"{take}-b1", "selected_candidate_id": "c2",
                    "confidence_candidates": [
                        {"candidate_id": f"c{i}", "snippet_id": f"{take}-s{i}",
                         "eligibility": "eligible"} for i in (1, 2, 3)]}
        return [{"take_session_id": t, "policy_version": "v3", "frame": {"blocks": [block(t)]}}
                for t in TAKES]

    def list_coach_clip_exposures(self, *a, **k):
        return []

    def record_coach_clip_exposure(self, *a, **k):
        return True

    def insert_coach_block_pick(self, row):
        row = {**row, "id": f"pick-{len(self.picks)}"}
        self.picks.append(row)
        return row

    def get_coach_block_pick(self, pick_id, coach):
        return next((p for p in self.picks if p["id"] == pick_id), None)

    def answer_coach_block_pick(self, *, pick_id, coach_id, pick_snippet_id, cant_tell):
        row = self.get_coach_block_pick(pick_id, coach_id)
        row.update(answered_at="x")
        return row

    def get_snippet_by_id(self, clip):
        return {"id": clip, "audio_segment_path": None}


def test_only_yes_speakers_reach_the_block_pick_and_a_withdrawal_empties_it(monkeypatch):
    monkeypatch.setattr("config.Config.COACH_BLOCK_PICK_ENABLED", True, raising=False)
    monkeypatch.setattr("services.snippet_audio_url.snippet_clip_playback",
                        lambda snippet, db: {"audio_ref": None, "start_offset_ms": None,
                                             "duration_ms": None})
    db = _PickDb()
    written = bp.sample_for_coach(db, coach_id="c", week="w", rng=random.Random(2))
    assert sorted(w["take_session_id"] for w in written) == ["t-gone", "t-yes"]
    db.withdraw("p-gone")
    status, body = bp.queue(db, coach_id="c")
    assert status == 200 and len(body["items"]) == 1
    gone = next(w for w in written if w["take_session_id"] == "t-gone")
    assert bp.answer(db, coach_id="c", pick_id=gone["id"], body={"cant_tell": True})[0] == 404


# ── E5: the learned exercise order ───────────────────────────────────────

def test_the_learned_order_counts_only_yes_speakers(monkeypatch):
    from services import exercise_evaluation as ev
    from services import exercise_learned_order as lo

    records = [{"exposure": {"owner_user_id": u}, "excluded": None}
               for u in ("u-yes", "u-no", "u-gone", "")]
    seen: list[list[str]] = []

    def build(recs, prefs=None):
        seen.append([ev.record_owner(r) for r in recs])
        return {"machine_only": {"fair_test": {"meets_bar": True}, "preferences": []}}

    monkeypatch.setattr(ev, "readiness", lambda db: {"ready": True})
    monkeypatch.setattr(ev, "read_sources", lambda db: ({}, []))
    monkeypatch.setattr(ev, "cohort_records", lambda **kw: list(records))
    monkeypatch.setattr(ev, "build_evaluation", build)

    db = _Ledger()
    lo.learned_rates(db)
    assert seen[-1] == ["u-yes", "u-gone"]
    db.withdraw("p-gone")
    lo.learned_rates(db)
    assert seen[-1] == ["u-yes"]
    # The founder's own jar page reads the unfiltered counter, as before.
    ev.evaluate_jar(db)
    assert seen[-1] == ["u-yes", "u-no", "u-gone", ""]
