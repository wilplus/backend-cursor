"""
STORY    As a speaker, I want my data used for cross-person learning only while
         I hold the training yes, so that withdrawing consent really stops it.
         (Consent, beside the loop: coach sheets and exercise order learn
         from speakers; the record -> feedback loop never waits on them.)
OUTCOME
  O1  The shared read (services.pair_consent) says yes only for a speaker
      with an active yes; never-said-yes and withdrawn both read as no.
  O2  Fails closed: an unreadable ledger, an unreadable Take or an
      unreadable blind-check objection reads as no.
  O3  E4 V4 coach sheets: only yes-speakers' Takes are written; after a
      withdrawal the sheet leaves the queue and cannot be answered.
  O4  E4 blind block pick: the same, for the coach's block pick.
  O5  E5 learned exercise order: only yes-speakers' tries are learned from;
      a withdrawal drops them at the next read.
PROVES   O1 -> test_the_shared_read_says_yes_only_while_the_yes_is_held
         O2 -> test_every_unreadable_answer_reads_as_no
         O3 -> test_only_yes_speakers_reach_the_coach_sheets_and_a_withdrawal_empties_them
         O4 -> test_only_yes_speakers_reach_the_block_pick_and_a_withdrawal_empties_it
         O5 -> test_only_yes_speakers_teach_the_exercise_order
WHY      Privacy 3.5 section 4a, items E4 and E5 (founder signed 2026-10-08).
         The ledger here is a Python double: this file covers the Python
         lanes, not the SQL status function.
"""
from __future__ import annotations

import random

import pytest

from services import coach_block_pick as bp
from services import error_presence_audit as epa
from services import exercise_learned_order as elo
from services import pair_consent as pc
from services import v4_coach_sheets as cs

REAL_OBJECTED = epa._objected

#: take -> speaker principal; user -> principal.
TAKES = {"t-yes": "p-yes", "t-no": "p-no", "t-gone": "p-gone"}
USERS = {"u-yes": "p-yes", "u-no": "p-no", "u-gone": "p-gone"}


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
                "user_id": f"u-{take.removeprefix('t-')}"}

    def get_project_owner_principal(self, project):
        return TAKES.get(project.removeprefix("proj-"), "")

    def get_owner_principal_for_user(self, user_id):
        return {"id": USERS[user_id]} if user_id in USERS else None

    def get_mlc2_training_consent_status(self, principal):
        return self.status.get(principal, {"active": False})


@pytest.fixture(autouse=True)
def no_objection(monkeypatch):
    # 0454's reader needs a live client; here nobody objected unless a test says so.
    monkeypatch.setattr("services.error_presence_audit._objected", lambda db, take: False)
    monkeypatch.setattr("services.snippet_audio_url.snippet_clip_playback",
                        lambda snippet, db: {"audio_ref": None, "start_offset_ms": None,
                                             "duration_ms": None})


# ── the shared read ──────────────────────────────────────────────────────

def test_the_shared_read_says_yes_only_while_the_yes_is_held():
    db = _Ledger()
    assert [pc.take_holds_training_yes(db, t) for t in TAKES] == [True, False, True]
    assert [pc.user_holds_training_yes(db, u) for u in USERS] == [True, False, True]
    assert pc.take_may_reach_a_coach_sheet(db, "t-yes") is True
    db.withdraw("p-yes")
    assert pc.take_holds_training_yes(db, "t-yes") is False
    assert pc.user_holds_training_yes(db, "u-yes") is False
    assert pc.take_may_reach_a_coach_sheet(db, "t-yes") is False


def test_every_unreadable_answer_reads_as_no(monkeypatch):
    db = _Ledger()
    assert pc.take_holds_training_yes(db, "t-yes") is True  # the yes is there to lose

    def broken(*_a, **_k):
        raise RuntimeError("database fault")

    ledger_down = _Ledger()
    ledger_down.get_mlc2_training_consent_status = broken
    assert pc.take_holds_training_yes(ledger_down, "t-yes") is False

    take_down = _Ledger()
    take_down.v2_get_session_by_id = broken
    assert pc.take_holds_training_yes(take_down, "t-yes") is False
    assert pc.take_holds_training_yes(db, "t-unknown") is False

    # The objection reader cannot reach the database on this double: that
    # counts as an objection, so the Take never reaches a sheet.
    monkeypatch.setattr("services.error_presence_audit._objected", REAL_OBJECTED)
    assert pc.take_may_reach_a_coach_sheet(db, "t-yes") is False


# ── E4: the V4 coach sheets ──────────────────────────────────────────────

class _SheetDb(_Ledger):
    def __init__(self):
        super().__init__()
        self.sheets: list[dict] = []

    def list_v4_pick_sheets(self, rater):
        return [s for s in self.sheets if s["rater_id"] == rater]

    def list_takes_coach_is_walking(self, rater):
        return []

    def list_recent_v3_frames(self, limit=200):
        return [{"take_session_id": t, "frame": {"blocks": [
            {"block_id": f"{t}-b1", "snippet_ids": [f"{t}-a", f"{t}-b"]}]}} for t in TAKES]

    def list_v4_picks(self, take):
        return [{"block_id": f"{take}-b1", "sureness": 0.1,
                 "v4_snippet_id": f"{take}-a", "v3_snippet_id": f"{take}-b"}]

    def insert_v4_pick_sheet(self, row):
        row = {**row, "id": f"s-{row['take_session_id']}"}
        self.sheets.append(row)
        return row

    def list_coach_clip_exposures(self, *a, **k):
        return []

    def record_coach_clip_exposure(self, *a, **k):
        return True

    def get_v4_pick_sheet(self, sheet_id, rater):
        return next((s for s in self.sheets if s["id"] == sheet_id), None)

    def answer_v4_pick_sheet(self, sheet_id, rater, clip, none):
        row = self.get_v4_pick_sheet(sheet_id, rater)
        row.update(answered_at="x")
        return row

    def get_snippet_by_id(self, clip):
        return {"transcript": f"words of {clip}", "audio_segment_path": None}


def test_only_yes_speakers_reach_the_coach_sheets_and_a_withdrawal_empties_them(monkeypatch):
    monkeypatch.setattr(cs, "rater_role", lambda uid: "coach")
    db = _SheetDb()
    written = cs.fill_pick_sheets(db, rater_id="c", week="w", rng=random.Random(2))
    assert sorted(w["take_session_id"] for w in written) == ["t-gone", "t-yes"]
    db.withdraw("p-gone")
    status, body = cs.pick_queue(db, rater_id="c")
    assert status == 200 and [i["sheet_id"] for i in body["items"]] == ["s-t-yes"]
    assert cs.pick_answer(db, rater_id="c", sheet_id="s-t-gone",
                          body={"none_needs_it": True})[0] == 404
    assert cs.pick_answer(db, rater_id="c", sheet_id="s-t-yes",
                          body={"none_needs_it": True})[0] == 200


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


def test_only_yes_speakers_reach_the_block_pick_and_a_withdrawal_empties_it():
    db = _PickDb()
    written = bp.sample_for_coach(db, coach_id="c", week="w", rng=random.Random(2))
    assert sorted(w["take_session_id"] for w in written) == ["t-gone", "t-yes"]
    db.withdraw("p-gone")
    status, body = bp.queue(db, coach_id="c")
    assert status == 200 and len(body["items"]) == 1
    gone = next(w for w in written if w["take_session_id"] == "t-gone")
    kept = next(w for w in written if w["take_session_id"] == "t-yes")
    assert bp.answer(db, coach_id="c", pick_id=gone["id"], body={"cant_tell": True})[0] == 404
    assert bp.answer(db, coach_id="c", pick_id=kept["id"], body={"cant_tell": True})[0] == 200


# ── E5: the learned exercise order ───────────────────────────────────────

def test_only_yes_speakers_teach_the_exercise_order(monkeypatch):
    """The jar's own grading is exercise_evaluation's; here it stands in as
    "each kept speaker's tries teach their one exercise", so what is pinned
    is the consent filter the order hands it."""
    tries = {"u-yes": "ex-yes", "u-no": "ex-no", "u-gone": "ex-gone"}

    def jar(database, gate=None, *, keep_owner=None):
        kept = [u for u in tries if keep_owner is None or keep_owner(u)]
        return {"sealed": False, "machine_only": {
            "fair_test": {"meets_bar": True},
            "preferences": [{"exercise_id": tries[u], "trusted": True, "helped_rate": 0.5,
                             "counted": 10_000} for u in kept]}}

    monkeypatch.setattr("services.exercise_evaluation.evaluate_jar", jar)
    db = _Ledger()
    rates, why = elo.learned_rates(db)
    assert why == "learned" and sorted(rates) == ["ex-gone", "ex-yes"]
    db.withdraw("p-gone")
    rates, _ = elo.learned_rates(db)
    assert sorted(rates) == ["ex-yes"]
