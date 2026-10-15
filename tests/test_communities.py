"""Communities (founder 2026-10-06, decisions log N52.4; migration 0432),
on (their switch was deleted 2026-10-11), sharing gated on
COMMUNITY_SHARE_POLICY_VERSION (CM2).

Pins: pass codes are normalised, at least six
characters and kept only as a keyed digest (no secret, 503); joining is by
pass code alone; "None" stands alone and revokes every share; a speaker
shares only with communities they belong to (general is open) and each share
carries the consent version; a revocation leaves the queue; the listener's
own clips, answered or self-labelled clips and settled clips are never
queued; private communities' clips come first, then the general one's, then
training clips; the payload is audio only; a community answer is a peer
label (lane game_peer) under the quorum's access rule, a training answer
takes no label; the listener's own clip is refused.
"""
from __future__ import annotations

import random
from unittest.mock import patch

import pytest

from config import Config
from services import communities as cm

GENERAL_ID = "00000000-0000-4000-8000-000000000001"
SECRET = "s" * 40


def _uuid(n: int) -> str:
    return f"00000000-0000-4000-8000-{n:012d}"


class _Db:
    """The tables 0432 adds, and the reads the queue and the answer make."""

    def __init__(self):
        self.communities = {GENERAL_ID: {"id": GENERAL_ID, "kind": "general", "name": None,
                                         "pass_code_digest": None, "created_by": None,
                                         "closed_at": None}}
        self.members: list = []
        self.shares: list = []
        self.answers: list = []
        self.snippets: dict = {}
        self.labels: dict = {}
        self.ratings: list = []
        self.corpus: list = []
        self.sessions = {_uuid(901): "owner-1", _uuid(902): "owner-2"}
        self.next = 100

    # communities
    def get_general_community(self):
        return self.communities[GENERAL_ID]

    def insert_community(self, row):
        if any(c.get("pass_code_digest") == row["pass_code_digest"]
               for c in self.communities.values()):
            return None
        self.next += 1
        cid = _uuid(self.next)
        self.communities[cid] = {"id": cid, "closed_at": None, **row}
        return self.communities[cid]

    def get_community_by_pass_code_digest(self, digest):
        return next((c for c in self.communities.values()
                     if c.get("pass_code_digest") == digest and not c.get("closed_at")), None)

    def get_communities_by_ids(self, ids):
        return [self.communities[i] for i in ids if i in self.communities]

    def add_community_member(self, *, community_id, user_id, role):
        if not any(m["community_id"] == community_id and m["user_id"] == user_id
                   for m in self.members):
            self.members.append({"community_id": community_id, "user_id": user_id, "role": role})
        return True

    def list_community_memberships(self, user_id):
        return [m for m in self.members if m["user_id"] == user_id]

    # shares
    def v2_get_session_by_id(self, sid):
        return {"id": sid, "user_id": self.sessions[sid]} if sid in self.sessions else None

    def upsert_take_share(self, *, take_session_id, owner_user_id, community_id,
                          consent_version, share_words_version):
        row = next((s for s in self.shares if s["take_session_id"] == take_session_id
                    and s["community_id"] == community_id), None)
        if row is None:
            row = {"take_session_id": take_session_id, "community_id": community_id}
            self.shares.append(row)
        row.update(owner_user_id=owner_user_id, consent_version=consent_version,
                   share_words_version=share_words_version, revoked_at=None)
        return row

    def revoke_take_shares(self, take_session_id, *, keep_community_ids):
        n = 0
        for s in self.shares:
            if (s["take_session_id"] == take_session_id and s["revoked_at"] is None
                    and s["community_id"] not in keep_community_ids):
                s["revoked_at"] = "now"
                n += 1
        return n

    def _live(self):
        out = []
        for s in self.shares:
            community = self.communities.get(s["community_id"]) or {}
            if s["revoked_at"] is not None or community.get("closed_at"):
                continue
            for sn in self.snippets.values():
                if sn["session_id"] == s["take_session_id"]:
                    out.append({"snippet_id": sn["id"], "take_session_id": s["take_session_id"],
                                "community_id": s["community_id"],
                                "community_kind": community.get("kind"),
                                "owner_user_id": s["owner_user_id"]})
        return out

    def list_community_clips_live(self, ids):
        return [r for r in self._live() if r["community_id"] in ids]

    def list_community_clips_for_snippet(self, sid):
        return [r for r in self._live() if r["snippet_id"] == sid]

    # the queue and the answer
    def list_community_answered_clip_ids(self, listener):
        return [a.get("snippet_id") or a.get("corpus_clip_id") for a in self.answers
                if a["listener_user_id"] == listener]

    def insert_community_answer(self, row):
        key = row.get("snippet_id") or row.get("corpus_clip_id")
        if any(a["listener_user_id"] == row["listener_user_id"]
               and (a.get("snippet_id") or a.get("corpus_clip_id")) == key for a in self.answers):
            return None
        self.answers.append(dict(row))
        return self.answers[-1]

    def get_snippet_by_id(self, sid):
        return self.snippets.get(sid)

    def get_confidence_labels_by_snippet_ids(self, ids):
        return {i: self.labels.get(i, []) for i in ids}

    def upsert_state_rating(self, **kwargs):
        self.ratings.append(kwargs)
        return True

    def list_corpus_clips_active(self):
        return [c for c in self.corpus if c.get("active", True)]

    def get_corpus_clip(self, cid):
        return next((c for c in self.corpus if c["id"] == cid), None)


POLICY = patch.object(Config, "COMMUNITY_SHARE_POLICY_VERSION", "phase1-2026-11-01")
ACCEPTED = patch("services.lend_your_ear.accepted_policy_at_least", return_value=True)
KEY = patch.object(Config, "SUPABASE_JWT_SECRET", SECRET)
AUDIO = patch.object(cm, "_clip_audio", lambda _db, s: f"https://a/{s['id']}.webm")


@pytest.fixture(autouse=True)
def _switches():
    with KEY, AUDIO:
        yield


def _snippet(sid, take, user="owner-1", **extra):
    return {"id": sid, "session_id": take, "user_id": user, "start_offset_ms": 1200,
            "duration_ms": 3000, "transcript": "the words they said", **extra}


def _private(db, owner="owner-1", code="friends-of-mine"):
    _, payload = cm.create_community(db, owner_user_id=owner,
                                     body={"name": "Friends", "pass_code": code})
    return payload["community"]["id"]


WORDS = "sharing-screen-2026-10-06"


def _share(db, take, owner="owner-1", **body):
    if not body.get("none") and "share_words_version" not in body:
        body["share_words_version"] = WORDS
    with POLICY, ACCEPTED:
        return cm.share_take(db, owner_user_id=owner, take_session_id=take, body=body)


# ── the switches ──────────────────────────────────────────────────────────


# ── the pass code ─────────────────────────────────────────────────────────


# ── the share ─────────────────────────────────────────────────────────────


# ── the queue ─────────────────────────────────────────────────────────────

def _world():
    """owner-1 shares Take 901 with the general community; owner-2 shares
    Take 902 with a private community the listener belongs to and with the
    general one; the listener shares their own Take too."""
    db = _Db()
    db.sessions[_uuid(903)] = "listener"
    db.snippets = {
        _uuid(11): _snippet(_uuid(11), _uuid(901)),
        _uuid(21): _snippet(_uuid(21), _uuid(902), user="owner-2"),
        _uuid(31): _snippet(_uuid(31), _uuid(903), user="listener"),
    }
    club = _private(db, owner="owner-2", code="the-club-code")
    cm.join_community(db, user_id="listener", body={"pass_code": "the-club-code"})
    _share(db, _uuid(901), general=True)
    _share(db, _uuid(902), owner="owner-2", general=True, community_ids=[club])
    _share(db, _uuid(903), owner="listener", general=True, community_ids=[club])
    db.corpus = [{"id": _uuid(51), "audio_url": "https://c/51.mp3", "duration_ms": 4000,
                  "machine_stratum": "confident", "passage": "a licensed line",
                  "licence": "CC BY", "active": True},
                 {"id": _uuid(52), "audio_url": "https://c/52.mp3", "duration_ms": 4000,
                  "machine_stratum": "weak", "passage": "another line",
                  "licence": "CC BY", "active": True}]
    return db, club


def _queue(db, listener="listener"):
    status, payload = cm.queue_for(db, listener_id=listener, rng=random.Random(4))
    assert status == 200
    return payload["clips"]


def test_answered_self_labelled_and_settled_clips_are_not_queued():
    db, _ = _world()
    assert cm.answer(db, listener_id="listener", body={"clip_id": _uuid(21), "value": "yes"})[0] == 200
    db.labels[_uuid(11)] = [{"value": "yes", "lane": "coach", "rater_id": "c1"},
                            {"value": "yes", "lane": "game_peer", "rater_id": "p1"}]
    assert {c["source"] for c in _queue(db)} == {"training"}
    db2, _ = _world()
    db2.labels[_uuid(11)] = [{"value": "no", "lane": "game_peer", "rater_id": "listener"}]
    assert _uuid(11) not in {c["clip_id"] for c in _queue(db2)}
    assert cm.answer(db2, listener_id="listener", body={"clip_id": _uuid(51), "value": "no"})[0] == 200
    assert _uuid(51) not in {c["clip_id"] for c in _queue(db2)}


# ── the answer ────────────────────────────────────────────────────────────


# ── provenance and fences ─────────────────────────────────────────────────


# ── the words the speaker saw (CM2 B, N53.2; Q-B6 A, N62; 0443) ───────────


def test_data_and_consent_lists_each_shared_take_once_with_where():
    """Fix 3 (founder 2026-10-15): Stop sharing lists every live share,
    one row per Take, with the communities it is heard in."""
    class Shares:
        def list_live_take_shares(self, owner):
            assert owner == "owner-1"
            return [
                {"take_session_id": _uuid(901), "community_id": GENERAL_ID,
                 "community_name": None, "community_kind": "general",
                 "take_index": 2, "project": "Pitch"},
                {"take_session_id": _uuid(901), "community_id": _uuid(7),
                 "community_name": "Friends", "community_kind": "private",
                 "take_index": 2, "project": "Pitch"},
            ]
    status, body = cm.my_live_shares(Shares(), owner_user_id="owner-1")
    assert status == 200
    assert body == {"takes": [{
        "take_session_id": _uuid(901), "take_index": 2, "project": "Pitch",
        "communities": [{"id": GENERAL_ID, "name": None, "kind": "general"},
                        {"id": _uuid(7), "name": "Friends", "kind": "private"}]}]}

