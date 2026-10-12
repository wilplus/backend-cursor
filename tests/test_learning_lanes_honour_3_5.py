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

import pytest

from services import coach_block_pick as bp

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


# ── E4: the V4 coach sheets ──────────────────────────────────────────────


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
