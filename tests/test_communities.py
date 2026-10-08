"""Communities (founder 2026-10-06, decisions log N52.4; migration 0432),
dark behind COMMUNITIES_ENABLED, sharing gated on
COMMUNITY_SHARE_POLICY_VERSION (CM2: counsel approves the words first).

Pins: both switches default off; off, every route and every service call
answers 404 before any read; pass codes are normalised, at least six
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

import hashlib
import hmac
import json
import random
from pathlib import Path
from unittest.mock import patch

import pytest
from flask import Flask, request

from config import Config
from services import communities as cm

ROOT = Path(__file__).resolve().parents[1]
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


class _Refuses:
    """A database that fails the test on any read or write."""

    def __getattr__(self, name):
        raise AssertionError(f"read {name} while the switch is off")


ON = patch.object(Config, "COMMUNITIES_ENABLED", True)
POLICY = patch.object(Config, "COMMUNITY_SHARE_POLICY_VERSION", "phase1-2026-11-01")
ACCEPTED = patch("services.lend_your_ear.accepted_policy_at_least", return_value=True)
KEY = patch.object(Config, "SUPABASE_JWT_SECRET", SECRET)
AUDIO = patch.object(cm, "_clip_audio", lambda _db, s: f"https://a/{s['id']}.webm")


@pytest.fixture(autouse=True)
def _switches():
    with ON, KEY, AUDIO:
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

def test_the_switch_is_on_and_sharing_names_the_current_privacy_terms():
    """COMMUNITIES_ENABLED is on from 2026-10-08 (founder, D-FW-20, N66;
    counsel's review not obtained). CM2 B / Q-B6 A: the share policy version
    names the current Privacy/Terms, the same version the peer share and the
    blind check are on; a share records the signed words' version."""
    source = (ROOT / "config.py").read_text()
    assert "    COMMUNITIES_ENABLED = True\n" in source
    assert Config.SHARE_WORDS_VERSIONS == ("sharing-screen-2026-10-06",)
    assert ('    COMMUNITY_SHARE_POLICY_VERSION: str | None = "phase1-2026-10-02"\n'
            in source)
    assert Config.COMMUNITY_SHARE_POLICY_VERSION == Config.PEER_SHARE_POLICY_VERSION
    assert "N52.4" in source and "CM2 B" in source and "Q-B6 A" in source
    assert "share_words_version" in source


def test_off_every_call_is_404_before_any_read():
    with patch.object(Config, "COMMUNITIES_ENABLED", False):
        db = _Refuses()
        calls = [
            lambda: cm.create_community(db, owner_user_id="u", body={"name": "x", "pass_code": "abcdefg"}),
            lambda: cm.join_community(db, user_id="u", body={"pass_code": "abcdefg"}),
            lambda: cm.list_my_communities(db, user_id="u"),
            lambda: cm.share_take(db, owner_user_id="u", take_session_id=_uuid(901), body={"none": True}),
            lambda: cm.queue_for(db, listener_id="u"),
            lambda: cm.answer(db, listener_id="u", body={"clip_id": _uuid(1), "value": "yes"}),
        ]
        for call in calls:
            assert call() == (404, {"code": "NOT_FOUND"})


ROUTES = {
    "v2_community_create": ("/user/communities", "POST", ()),
    "v2_community_join": ("/user/communities/join", "POST", ()),
    "v2_communities_list": ("/user/communities", "GET", ()),
    "v2_take_share": ("/user/takes/<take_id>/share", "PUT", ("not-a-uuid",)),
    "v2_community_queue": ("/user/communities/queue", "GET", ()),
    "v2_community_answer": ("/user/communities/answers", "POST", ()),
}


def test_the_routes_are_registered_authenticated_and_fenced():
    from routes.v2 import DOMAIN_MODULES
    assert "communities" in DOMAIN_MODULES
    source = (ROOT / "routes/v2/communities.py").read_text()
    assert source.count("@v2_bp.route(") == len(ROUTES)
    assert source.count("@require_auth") == len(ROUTES)
    for name, (path, method, _) in ROUTES.items():
        assert f'@v2_bp.route("{path}", methods=["{method}"])' in source
        body = source[source.index(f"def {name}("):]
        body = body[:body.index("@v2_bp.route") if "@v2_bp.route" in body else len(body)]
        # The switch is read before anything else in the handler.
        assert body.index("off = _off()") < min(
            i for i in (body.find("db,"), body.find("_is_valid_uuid")) if i >= 0)
    # The pass-code routes carry the rate limit against guessing.
    for name in ("v2_community_create", "v2_community_join"):
        head = source[:source.index(f"def {name}(")]
        assert head.rstrip().endswith("@require_auth")
        assert head[head.rindex("@v2_bp.route"):].count("@heavy_limit") == 1


def test_off_every_route_answers_404_before_any_read():
    import routes.v2.communities as route
    app = Flask(__name__)
    with patch.object(Config, "COMMUNITIES_ENABLED", False), \
            patch.object(route, "db", _Refuses()):
        for name, (_path, method, args) in ROUTES.items():
            with app.test_request_context("/v2/x", method=method, json={"none": True}):
                request.user_id = "u"
                response, status = getattr(route, name).__wrapped__(*args)
            assert status == 404, name
            assert response.get_json() == {"code": "NOT_FOUND"}, name


def test_on_the_routes_reach_the_service():
    import routes.v2.communities as route
    app = Flask(__name__)
    db = _Db()
    with patch.object(route, "db", db):
        with app.test_request_context("/v2/x", method="POST",
                                      json={"name": "Friends", "pass_code": "friends-of-mine"}):
            request.user_id = "owner-1"
            response, status = route.v2_community_create.__wrapped__()
        assert status == 201
        with app.test_request_context("/v2/x", method="PUT", json={"none": True}):
            request.user_id = "owner-1"
            assert route.v2_take_share.__wrapped__("not-a-uuid")[1] == 400
            assert route.v2_take_share.__wrapped__(_uuid(901))[1] == 200
        with app.test_request_context("/v2/x", method="GET"):
            request.user_id = "owner-1"
            response, status = route.v2_communities_list.__wrapped__()
        assert status == 200 and len(response.get_json()["communities"]) == 2


# ── the pass code ─────────────────────────────────────────────────────────

def test_pass_code_rules():
    assert cm.normalise_pass_code("  OurClub  ") == "ourclub"
    assert cm.normalise_pass_code("OURCLUB") == cm.normalise_pass_code("ourclub")
    assert cm.normalise_pass_code("Straße1") == "strasse1"
    assert cm.normalise_pass_code("abcde") is None
    assert cm.normalise_pass_code("   abcde   ") is None
    assert cm.normalise_pass_code("x" * 129) is None
    assert cm.normalise_pass_code(123456) is None
    assert cm.normalise_pass_code(None) is None


def test_the_digest_is_a_keyed_hmac_never_the_code():
    key = cm._pass_code_key()
    assert key is not None and key != SECRET.encode()
    digest = cm.pass_code_digest("ourclub", key)
    assert digest == hmac.new(key, b"ourclub", hashlib.sha256).hexdigest()
    assert digest != hashlib.sha256(b"ourclub").hexdigest()
    assert cm.pass_code_digest("ourclub", b"another key") != digest
    db = _Db()
    _private(db, code="OurClub-2026")
    stored = json.dumps(list(db.communities.values()))
    assert "ourclub-2026" not in stored.lower()


def test_no_secret_refuses_rather_than_keep_a_plain_code():
    db = _Db()
    with patch.object(Config, "SUPABASE_JWT_SECRET", ""):
        assert cm.create_community(db, owner_user_id="o", body={"name": "x", "pass_code": "abcdefg"}) \
            == (503, {"code": "PASS_CODES_UNAVAILABLE"})
        assert cm.join_community(db, user_id="o", body={"pass_code": "abcdefg"})[0] == 503
    assert len(db.communities) == 1


def test_create_and_join_by_pass_code_alone():
    db = _Db()
    assert cm.create_community(db, owner_user_id="o", body={"name": " ", "pass_code": "abcdefg"})[0] == 400
    assert cm.create_community(db, owner_user_id="o", body={"name": "x" * 81, "pass_code": "abcdefg"})[0] == 400
    assert cm.create_community(db, owner_user_id="o", body={"name": "x", "pass_code": "short"}) \
        == (400, {"code": "PASS_CODE_INVALID"})
    status, payload = cm.create_community(db, owner_user_id="owner-1",
                                          body={"name": "  Friends   of mine ", "pass_code": "Friends-Club"})
    assert status == 201
    assert payload["community"] == {"id": payload["community"]["id"], "kind": "private",
                                    "name": "Friends of mine", "role": "owner"}
    assert cm.create_community(db, owner_user_id="owner-2",
                               body={"name": "Other", "pass_code": " friends-club "}) \
        == (409, {"code": "PASS_CODE_TAKEN"})
    assert cm.join_community(db, user_id="owner-2", body={"pass_code": "nobody-knows"}) \
        == (404, {"code": "COMMUNITY_NOT_FOUND"})
    status, joined = cm.join_community(db, user_id="owner-2", body={"pass_code": "  FRIENDS-CLUB"})
    assert status == 200 and joined["community"]["role"] == "member"
    # Joining again changes nothing; the owner stays owner.
    assert cm.join_community(db, user_id="owner-1", body={"pass_code": "friends-club"})[1]["community"]["role"] == "owner"
    assert len(db.members) == 2
    listed = cm.list_my_communities(db, user_id="owner-2")[1]["communities"]
    assert [c["kind"] for c in listed] == ["general", "private"]
    assert all(set(c) == {"id", "kind", "name", "role"} for c in listed)


# ── the share ─────────────────────────────────────────────────────────────

def test_none_stands_alone():
    db = _Db()
    for body in ({"none": True, "general": True}, {"none": True, "community_ids": [GENERAL_ID]}):
        assert _share(db, _uuid(901), **body) == (400, {"code": "NONE_IS_EXCLUSIVE"})
    assert _share(db, _uuid(901)) == (400, {"code": "NOTHING_CHOSEN"})
    assert _share(db, _uuid(901), general="yes")[0] == 400
    assert _share(db, _uuid(901), community_ids=["not-a-uuid"])[0] == 400
    assert db.shares == []


def test_only_the_owner_shares_and_only_with_their_communities():
    db = _Db()
    theirs = _private(db, owner="owner-2", code="someone-else")
    assert _share(db, _uuid(901), owner="owner-2", general=True) == (404, {"code": "TAKE_NOT_FOUND"})
    assert _share(db, _uuid(901), community_ids=[theirs]) == (403, {"code": "NOT_A_MEMBER"})
    assert db.shares == []


def test_sharing_waits_for_the_policy_version_and_none_never_waits():
    db = _Db()
    with patch.object(Config, "COMMUNITY_SHARE_POLICY_VERSION", None):
        assert cm.share_take(db, owner_user_id="owner-1", take_session_id=_uuid(901),
                             body={"general": True, "share_words_version": WORDS}
                             ) == (409, {"code": "TERMS_REACCEPT_REQUIRED"})
        assert db.shares == []
        assert cm.share_take(db, owner_user_id="owner-1", take_session_id=_uuid(901),
                             body={"none": True})[0] == 200


def test_the_policy_check_reads_the_community_version_not_the_peer_one():
    seen = []

    def _accepted(database, owner, version):
        seen.append(version)
        return False
    db = _Db()
    with POLICY, patch("services.lend_your_ear.accepted_policy_at_least", _accepted):
        status, _ = cm.share_take(db, owner_user_id="owner-1", take_session_id=_uuid(901),
                                  body={"general": True, "share_words_version": WORDS})
    assert status == 409 and seen == ["phase1-2026-11-01"]


def test_a_share_is_per_take_stamped_and_revocable():
    db = _Db()
    mine = _private(db)
    status, payload = _share(db, _uuid(901), general=True, community_ids=[mine])
    assert status == 200
    assert payload == {"take_session_id": _uuid(901), "community_ids": [GENERAL_ID, mine],
                       "none": False, "share_words_version": WORDS}
    assert {s["consent_version"] for s in db.shares} == {"phase1-2026-11-01"}
    # CM2 B / Q-B6 A (0443): each share records the words the speaker saw.
    assert {s["share_words_version"] for s in db.shares} == {WORDS}
    # Fewer choices withdraw the Take from the rest.
    _share(db, _uuid(901), community_ids=[mine])
    live = {s["community_id"] for s in db.shares if s["revoked_at"] is None}
    assert live == {mine}
    # "None" withdraws it from every community.
    assert _share(db, _uuid(901), none=True)[1]["none"] is True
    assert all(s["revoked_at"] for s in db.shares)
    # The general community named by id is the general choice.
    _share(db, _uuid(901), community_ids=[GENERAL_ID])
    assert {s["community_id"] for s in db.shares if s["revoked_at"] is None} == {GENERAL_ID}


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


def test_community_first_then_training_at_most_three_and_never_own():
    # Q-B11 A (N62): at most 3 other voices per walk, community first, then
    # training clips for the places left, served by the Lend your ear engine.
    db, _ = _world()
    clips = _queue(db)
    assert [c["clip_id"] for c in clips[:2]] == [_uuid(21), _uuid(11)]
    assert [c["source"] for c in clips] == ["community", "community", "training"]
    assert _uuid(31) not in {c["clip_id"] for c in clips}
    # A moment shared with two communities is heard once.
    assert len({c["clip_id"] for c in clips}) == len(clips)
    # Enough community clips fill the three; no training clip then.
    for n in (4, 5, 6):
        db.sessions[_uuid(900 + n)] = f"owner-{n}"
        db.snippets[_uuid(10 * n)] = _snippet(_uuid(10 * n), _uuid(900 + n), user=f"owner-{n}")
        _share(db, _uuid(900 + n), owner=f"owner-{n}", general=True)
    clips = _queue(db)
    assert len(clips) == 3
    assert [c["source"] for c in clips] == ["community"] * 3


def test_the_per_take_share_is_the_one_door_into_the_queue():
    # Q-B11 A: the Album share switch is retired. A moment lent through it
    # (the 0410 view) and never shared per Take is not served; the engine
    # and this module read community_clips_live and nothing else.
    db, _ = _world()
    db.snippets[_uuid(41)] = _snippet(_uuid(41), _uuid(904), user="owner-4")
    db.list_shared_clips_live = lambda: [{"snippet_id": _uuid(41), "owner_user_id": "owner-4"}]
    assert _uuid(41) not in {c["clip_id"] for c in _queue(db)}
    from services import lend_your_ear as lye
    assert cm.queue_for(db, listener_id="listener", rng=random.Random(4))[1]["clips"] == \
        lye.other_voices(db, listener_id="listener", rng=random.Random(4))
    for name in ("services/communities.py", "services/lend_your_ear.py"):
        source = (ROOT / name).read_text()
        assert "list_shared_clips_live" not in source
    assert "community_clips_live" in (ROOT / "services/db.py").read_text()


def test_the_payload_is_audio_only():
    db, _ = _world()
    db.labels = {_uuid(11): []}
    db.snippets[_uuid(11)]["metrics"] = {"voice_confidence": {"band": "delivery_signal_high"}}
    for clip in _queue(db):
        assert set(clip) == {"clip_id", "source", "audio_ref", "start_offset_ms", "duration_ms"}
    flat = json.dumps(_queue(db))
    for leak in ("owner-1", "owner-2", "Friends", "words they said", "licensed line",
                 "CC BY", "confident", "weak", "delivery_signal", "stratum", "community_id"):
        assert leak not in flat


def test_a_revocation_leaves_the_queue():
    db, club = _world()
    assert _uuid(21) in {c["clip_id"] for c in _queue(db)}
    _share(db, _uuid(902), owner="owner-2", none=True)
    assert _uuid(21) not in {c["clip_id"] for c in _queue(db)}
    _share(db, _uuid(901), none=True)
    assert [c["source"] for c in _queue(db)] == ["training", "training"]


def test_a_closed_community_or_a_stranger_hears_only_the_general_clips():
    db, club = _world()
    heard = [c for c in _queue(db, listener="stranger") if c["source"] == "community"]
    assert {c["clip_id"] for c in heard} == {_uuid(11), _uuid(21), _uuid(31)}
    db.shares = [s for s in db.shares if s["community_id"] != GENERAL_ID]
    assert {c["source"] for c in _queue(db, listener="stranger")} == {"training"}
    assert _uuid(21) in {c["clip_id"] for c in _queue(db)}
    db.communities[club]["closed_at"] = "now"
    assert {c["source"] for c in _queue(db)} == {"training"}


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

def test_a_community_answer_is_a_peer_label_under_the_quorum_rule():
    db, club = _world()
    status, payload = cm.answer(db, listener_id="listener",
                                body={"clip_id": _uuid(21), "value": "in_between"})
    assert (status, payload) == (200, {"recorded": True})
    assert len(db.ratings) == 1
    assert db.ratings[0]["lane"] == "game_peer"
    assert db.ratings[0]["self_report"] is False
    assert db.ratings[0]["rater_id"] == "listener"
    assert db.ratings[0]["row"]["value"] == "in_between"
    saved = db.answers[0]
    assert saved["clip_source"] == "community" and saved["community_id"] == club
    assert saved["take_session_id"] == _uuid(902) and saved["label_outcome"] == "new"
    assert cm.answer(db, listener_id="listener", body={"clip_id": _uuid(21), "value": "no"}) \
        == (409, {"code": "ALREADY_ANSWERED"})


def test_a_settled_clip_keeps_the_answer_but_takes_no_label():
    db, _ = _world()
    db.labels[_uuid(11)] = [{"value": "yes", "lane": "coach", "rater_id": "c1"},
                            {"value": "yes", "lane": "game_peer", "rater_id": "p1"}]
    assert cm.answer(db, listener_id="listener", body={"clip_id": _uuid(11), "value": "yes"})[0] == 200
    assert db.ratings == []
    assert db.answers[0]["label_id"] is None and db.answers[0]["label_outcome"] != "new"


def test_a_training_answer_takes_no_label():
    db, _ = _world()
    assert cm.answer(db, listener_id="listener", body={"clip_id": _uuid(51), "value": "no"})[0] == 200
    assert db.ratings == []
    assert db.answers[0] == {"clip_source": "corpus", "listener_user_id": "listener",
                             "corpus_clip_id": _uuid(51), "value": "no", "label_id": None,
                             "label_outcome": None}


def test_the_listener_s_own_clip_and_bad_input_are_refused():
    db, _ = _world()
    assert cm.answer(db, listener_id="listener", body={"clip_id": _uuid(31), "value": "yes"}) \
        == (403, {"code": "OWN_CLIP"})
    assert cm.answer(db, listener_id="listener", body={"clip_id": _uuid(21), "value": "maybe"})[0] == 400
    assert cm.answer(db, listener_id="listener", body={"clip_id": "nope", "value": "yes"})[0] == 400
    assert cm.answer(db, listener_id="listener", body={"clip_id": _uuid(77), "value": "yes"}) \
        == (404, {"code": "CLIP_NOT_FOUND"})
    assert db.ratings == [] and db.answers == []


def test_a_clip_outside_the_listener_s_communities_is_not_answerable():
    db, club = _world()
    db.shares = [s for s in db.shares if s["community_id"] != GENERAL_ID]
    assert cm.answer(db, listener_id="stranger", body={"clip_id": _uuid(21), "value": "yes"}) \
        == (404, {"code": "CLIP_NOT_FOUND"})
    assert db.ratings == []


# ── provenance and fences ─────────────────────────────────────────────────

def test_the_module_keeps_provenance_and_shows_no_number():
    source = (ROOT / "services/communities.py").read_text()
    for forbidden in ("fine_tune", "training_corpus", "training_labels", "is_owner=True",
                      "is_coach=True", "score"):
        assert forbidden not in source
    routes = (ROOT / "routes/v2/communities.py").read_text()
    assert '"error"' not in routes  # error codes only, no copy


def test_the_migration_and_the_purge_know_the_tables():
    from services import data_purge_project_scope as scope
    from services.data_purge_registry import DEPENDENCIES, NON_SUBJECT_RELATIONS
    manifest = (ROOT / "migrations/manifest.txt").read_text()
    assert "\ta_take_may_be_shared_with_a_community.sql" in manifest
    relations = {d.relation for d in DEPENDENCIES}
    assert {"communities", "community_members", "take_shares", "community_answers"} <= relations
    assert "community_clips_live" in NON_SUBJECT_RELATIONS
    assert {"community_answers_by_listener", "community_members",
            "communities_created"} <= scope.ACCOUNT_LEVEL
    assert scope.PROJECT_SELECTORS["take_shares_by_owner"] == ("take_session_id", "take")


# ── the words the speaker saw (CM2 B, N53.2; Q-B6 A, N62; 0443) ───────────

def test_a_share_records_the_words_the_speaker_saw_and_none_needs_none():
    db = _Db()
    # A share without the words version is refused before any write; the
    # policy check comes after it, so the refusal is the same on or off it.
    with POLICY, ACCEPTED:
        for body in ({"general": True}, {"general": True, "share_words_version": ""},
                     {"general": True, "share_words_version": 7},
                     {"general": True, "share_words_version": "has a space"},
                     {"general": True, "share_words_version": "x" * 65}):
            assert cm.share_take(db, owner_user_id="owner-1", take_session_id=_uuid(901),
                                 body=body) == (400, {"code": "SHARE_WORDS_VERSION_REQUIRED"})
    assert db.shares == []
    # The version the screen sends is what is recorded, as sent.
    status, payload = _share(db, _uuid(901), general=True,
                             share_words_version="sharing-screen-2026-10-06")
    assert status == 200 and payload["share_words_version"] == "sharing-screen-2026-10-06"
    assert db.shares[0]["share_words_version"] == "sharing-screen-2026-10-06"
    # A later share under newer words (once the server lists them)
    # re-stamps the live row.
    with patch.object(Config, "SHARE_WORDS_VERSIONS",
                      ("sharing-screen-2026-10-06", "sharing-screen-v2")):
        _share(db, _uuid(901), general=True, share_words_version="sharing-screen-v2")
    assert db.shares[0]["share_words_version"] == "sharing-screen-v2"
    # "None" revokes with no version, and reads none.
    status, payload = cm.share_take(db, owner_user_id="owner-1", take_session_id=_uuid(901),
                                    body={"none": True})
    assert (status, payload) == (200, {"take_session_id": _uuid(901), "community_ids": [],
                                       "none": True})
    assert db.shares[0]["revoked_at"] is not None
    assert db.shares[0]["share_words_version"] == "sharing-screen-v2"  # history keeps it


def test_the_words_version_is_a_short_id():
    assert cm.share_words_version_from({"share_words_version": "sharing-screen-2026-10-06"}) \
        == "sharing-screen-2026-10-06"
    with patch.object(Config, "SHARE_WORDS_VERSIONS", ("v1.2_a-b",)):
        assert cm.share_words_version_from({"share_words_version": "v1.2_a-b"}) == "v1.2_a-b"
    for bad in (None, "", " ", "-x", "a b", "x" * 65, 1, ["v1"], {"v": 1}):
        assert cm.share_words_version_from({"share_words_version": bad}) is None
    assert cm.share_words_version_from(None) is None
    assert cm.share_words_version_from({}) is None


def test_a_words_version_the_server_does_not_list_is_refused_before_any_write():
    """The words version is checked against the server's own list
    (Config.SHARE_WORDS_VERSIONS): a well-formed id the screen never showed
    is refused cleanly, with its own code, and nothing is written."""
    assert Config.SHARE_WORDS_VERSIONS == ("sharing-screen-2026-10-06",)
    assert WORDS in Config.SHARE_WORDS_VERSIONS
    db = _Db()
    with POLICY, ACCEPTED:
        for unknown in ("sharing-screen-v2", "sharing-screen-2099-01-01", "anything"):
            assert cm.share_take(db, owner_user_id="owner-1", take_session_id=_uuid(901),
                                 body={"general": True, "share_words_version": unknown}
                                 ) == (400, {"code": "SHARE_WORDS_VERSION_UNKNOWN"})
    assert db.shares == []
    assert cm.share_words_version_from({"share_words_version": "anything"}) is None
    assert cm.share_words_version_from({"share_words_version": WORDS}) == WORDS
    # An empty list refuses every share; "None" still revokes.
    with patch.object(Config, "SHARE_WORDS_VERSIONS", ()), POLICY, ACCEPTED:
        assert cm.share_take(db, owner_user_id="owner-1", take_session_id=_uuid(901),
                             body={"general": True, "share_words_version": WORDS}
                             ) == (400, {"code": "SHARE_WORDS_VERSION_UNKNOWN"})
        status, _ = cm.share_take(db, owner_user_id="owner-1", take_session_id=_uuid(901),
                                  body={"none": True})
        assert status == 200
