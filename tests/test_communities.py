"""
STORY    As a speaker, I want to share a Take only with communities I belong
         to, revocably, with listeners hearing audio only, so that sharing is
         my choice and listeners judge blind.
OUTCOME
  O1  Clips the listener answered or labelled, clips the quorum settled,
      and clips that can no longer settle (unresolved, quarantined for
      unclear audio) are not queued again.
  O2  The listener's answers list shows each answer with its clip's sound,
      newest first, only their own.
  O3  Stop sharing (Data & consent) lists each shared Take once, with where.
  O4  "None" withdraws a Take from every community at once, and its clips
      leave the queue; "None" with a community is refused.
  O5  A listener hears audio only (no words, no speaker, no Take), never
      their own clip, and answering their own clip is refused.
  O6  Every walk serves three clips, one per level (high, middle, low),
      from three different speakers, community clips first in their level,
      never mine or one I answered, in a blind order fixed for the Take;
      fewer only when fewer speakers are left.
  O7  An imported corpus clip plays through a short-lived signed link,
      audio only, never a name, transcript or level.
  O8  My answer on an imported clip is kept once (a second answer is
      refused) and never becomes a label.
  O9  The judging reopened from the Lounge lists imported clips too.
  O10 An empty queue is logged with its reason, and so is a short one.
PROVES   O1 -> test_answered_self_labelled_and_settled_clips_are_not_queued
         O2 -> test_the_judging_reopened_shows_the_latest_answers_with_their_clips
         O3 -> test_data_and_consent_lists_each_shared_take_once_with_where
         O4 -> test_none_withdraws_a_take_from_every_community
         O5 -> test_a_listener_hears_audio_only_and_never_their_own_clip
         O6 -> test_three_clips_one_per_level_three_speakers_fixed_per_take
         O7 -> test_an_imported_clip_plays_by_a_signed_link_audio_only
         O8 -> test_an_answer_on_an_imported_clip_is_kept_once_and_never_a_label
         O9 -> test_the_replay_lists_imported_clips
         O10 -> test_an_empty_queue_is_logged_with_why
WHY      Founder 2026-10-06 (N52.4, migration 0432; CM2). The consent and
         words versions on a share are pinned on the database in
         test_a_share_records_the_words_the_speaker_saw_postgres.py.
         O6 to O10: founder 2026-10-23 (N119, migration
         a_speaker_may_judge_an_imported_clip.sql): the imported corpus the
         coaches judge is played to speakers, three levels, three speakers;
         this amends CM1 A and replaces N97's one moment per try.
"""
from __future__ import annotations

import json
import logging
from types import SimpleNamespace
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
        # The imported training corpus (N119): ownerless import sessions,
        # each with its frozen cohort, and the speakers' answers on them.
        self.imports: dict = {}
        self.import_answers: list = []
        self.takes = SimpleNamespace(list_training_import_cohorts=lambda: list(self.imports.values()))
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
        if sid in self.imports:
            return self.imports[sid]
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
        self.answers.append({**row, "created_at": f"2026-10-18T10:00:{len(self.answers):02d}Z"})
        return self.answers[-1]

    def list_community_answers(self, listener, *, limit=50):
        mine = [a for a in self.answers if a["listener_user_id"] == listener]
        return list(reversed(mine))[:limit]

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

    def get_snippet_scores_by_ids(self, ids):
        return {i: {"session_id": self.snippets[i]["session_id"],
                    "score": ((self.snippets[i].get("metrics") or {})
                              .get("voice_confidence") or {}).get("score")}
                for i in ids if i in self.snippets}

    # the imported corpus's answers (N119)
    def list_import_clip_answered_ids(self, listener):
        return [a["snippet_id"] for a in self.import_answers if a["listener_user_id"] == listener]

    def insert_import_clip_answer(self, row):
        if any(a["listener_user_id"] == row["listener_user_id"]
               and a["snippet_id"] == row["snippet_id"] for a in self.import_answers):
            return None
        n = len(self.answers) + len(self.import_answers)
        self.import_answers.append({**row, "created_at": f"2026-10-18T10:00:{n:02d}Z"})
        return self.import_answers[-1]

    def list_import_clip_answers(self, listener, *, limit=50):
        mine = [a for a in self.import_answers if a["listener_user_id"] == listener]
        return list(reversed(mine))[:limit]


POLICY = patch.object(Config, "COMMUNITY_SHARE_POLICY_VERSION", "phase1-2026-11-01")
ACCEPTED = patch("services.lend_your_ear.accepted_policy_at_least", return_value=True)
KEY = patch.object(Config, "SUPABASE_JWT_SECRET", SECRET)
AUDIO = patch.object(cm, "_clip_audio", lambda _db, s: f"https://a/{s['id']}.webm")


@pytest.fixture(autouse=True)
def _switches():
    with KEY, AUDIO:
        yield


HIGH, MIDDLE, LOW = 0.8, 0.0, -0.8


def _snippet(sid, take, user="owner-1", score=HIGH, **extra):
    return {"id": sid, "session_id": take, "user_id": user, "start_offset_ms": 1200,
            "duration_ms": 3000, "transcript": "the words they said",
            "metrics": {"voice_confidence": {"score": score}}, **extra}


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





# ── the queue ─────────────────────────────────────────────────────────────

def _world():
    """owner-1 shares Take 901 with the general community; owner-2 shares
    Take 902 with a private community the listener belongs to and with the
    general one; the listener shares their own Take too."""
    db = _Db()
    db.sessions[_uuid(903)] = "listener"
    db.snippets = {
        _uuid(11): _snippet(_uuid(11), _uuid(901)),
        _uuid(21): _snippet(_uuid(21), _uuid(902), user="owner-2", score=LOW),
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


TAKE = _uuid(990)


def _queue(db, listener="listener", take=TAKE):
    status, payload = cm.queue_for(db, listener_id=listener, take=take)
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
    db3, _ = _world()
    db3.labels[_uuid(11)] = [{"value": v, "lane": "coach", "rater_id": f"c{i}"}
                             for i, v in enumerate(("yes", "no", "in_between"))]
    assert _uuid(11) not in {c["clip_id"] for c in _queue(db3)}
    db4, _ = _world()
    db4.labels[_uuid(11)] = [{"value": "audio_unclear", "lane": "coach", "rater_id": f"c{i}"}
                             for i in range(2)]
    assert _uuid(11) not in {c["clip_id"] for c in _queue(db4)}
    db5, _ = _world()
    db5.labels[_uuid(11)] = [{"value": "yes", "lane": "coach", "rater_id": "c1"}]
    assert _uuid(11) in {c["clip_id"] for c in _queue(db5)}


def test_the_judging_reopened_shows_the_latest_answers_with_their_clips():
    """The walk reopened from the Lounge: the moments the listener already
    judged, newest first, each with its sound and the answer given; a clip
    whose sound is gone is left out, and nothing of another listener's."""
    db, _ = _world()
    assert cm.answer(db, listener_id="listener", body={"clip_id": _uuid(21), "value": "yes"})[0] == 200
    assert cm.answer(db, listener_id="listener", body={"clip_id": _uuid(51), "value": "no"})[0] == 200
    assert cm.answer(db, listener_id="someone-else", body={"clip_id": _uuid(11), "value": "yes"})[0] == 200
    status, payload = cm.my_answers(db, listener_id="listener")
    assert status == 200
    assert [(a["clip_id"], a["value"]) for a in payload["answers"]] == [(_uuid(51), "no"), (_uuid(21), "yes")]
    assert payload["answers"][0]["audio_ref"] == "https://c/51.mp3"
    assert payload["answers"][1]["audio_ref"] == f"https://a/{_uuid(21)}.webm"
    assert payload["answers"][1]["community"] == "Friends"
    assert all(a["answered_at"] for a in payload["answers"])
    db.corpus[0]["audio_url"] = None
    assert [a["clip_id"] for a in cm.my_answers(db, listener_id="listener")[1]["answers"]] == [_uuid(21)]





def test_none_withdraws_a_take_from_every_community():
    db, _ = _world()
    assert _uuid(21) in {c["clip_id"] for c in _queue(db)}
    status, _ = _share(db, _uuid(901), none=True, general=True)
    assert status == 400
    status, body = _share(db, _uuid(902), owner="owner-2", none=True)
    assert (status, body["community_ids"]) == (200, [])
    assert all(s["revoked_at"] for s in db.shares if s["take_session_id"] == _uuid(902))
    queued = {c["clip_id"] for c in _queue(db)}
    assert _uuid(21) not in queued and _uuid(11) in queued


def test_a_listener_hears_audio_only_and_never_their_own_clip():
    db, _ = _world()
    clips = _queue(db)
    community = [c for c in clips if c["clip_id"] in (_uuid(11), _uuid(21))]
    assert len(community) == 2
    assert all(c["audio_ref"] == f"https://a/{c['clip_id']}.webm" for c in community)
    served = json.dumps(clips)
    for private in ("the words they said", "owner-1", "owner-2", _uuid(901), _uuid(902)):
        assert private not in served
    assert _uuid(31) not in {c["clip_id"] for c in clips}
    assert cm.answer(db, listener_id="listener",
                     body={"clip_id": _uuid(31), "value": "yes"}) == (403, {"code": "OWN_CLIP"})


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



# ── three levels, three speakers, and the imported corpus (N119) ─────────

IMPORT_A, IMPORT_B, IMPORT_C = _uuid(801), _uuid(802), _uuid(803)


def _import(db, sid, speaker, clips, *, set_up=True, archived=False):
    """One training import the coaches judge: ownerless, its cohort frozen
    on its context, each clip a snippet of it with the machine's read."""
    ctx = {"topic": "Board pitch", "speaker_label": speaker,
           "label_queue_selection": [{"snippet_id": c} for c, _ in clips]}
    if set_up:
        ctx["language"] = "en"
    if archived:
        ctx["archived_at"] = "2026-10-20T00:00:00Z"
    db.imports[sid] = {"id": sid, "source": "training_import", "recording_id": None,
                       "intake_context": ctx}
    for clip_id, score in clips:
        db.snippets[clip_id] = {
            "id": clip_id, "session_id": sid, "user_id": None, "start_offset_ms": 4000,
            "duration_ms": 2500, "transcript": "an imported speaker's words",
            "audio_segment_path": f"corpus/{clip_id}.webm",
            "metrics": {"voice_confidence": {"score": score}}}


def _signed(ref, expires_in=None, **_):
    return f"https://signed.example/{ref}?ttl={expires_in}"


SIGNED = patch("services.audio_ref_resolver.resolve_playable_ref", _signed)


def _imported_world():
    """The queue world, the licensed corpus emptied (it is, on main), and
    two coaches' imports: Ada (three levels) and Bo (middle and low); a
    third import not set up and a fourth archived are never served."""
    db, club = _world()
    db.corpus = []
    _import(db, IMPORT_A, "Ada", [(_uuid(61), HIGH), (_uuid(62), MIDDLE), (_uuid(63), LOW)])
    _import(db, IMPORT_B, "Bo", [(_uuid(71), MIDDLE), (_uuid(72), LOW)])
    _import(db, IMPORT_C, "Cy", [(_uuid(81), MIDDLE)], set_up=False)
    _import(db, _uuid(804), "Di", [(_uuid(91), MIDDLE)], archived=True)
    return db, club


def _level(db, clip):
    score = db.snippets.get(clip["clip_id"], {}).get("metrics", {}).get("voice_confidence", {}).get("score")
    return {HIGH: "high", MIDDLE: "middle", LOW: "low"}[score]


def _speaker(db, clip):
    snippet = db.snippets[clip["clip_id"]]
    if snippet["session_id"] in db.imports:
        return db.imports[snippet["session_id"]]["intake_context"]["speaker_label"]
    return snippet["user_id"]


def test_three_clips_one_per_level_three_speakers_fixed_per_take():
    with SIGNED:
        db, _ = _imported_world()
        clips = _queue(db)
        # Community clips first in their level: owner-1's high, owner-2's
        # low; the imported corpus fills the middle (Ada's or Bo's).
        assert sorted(_level(db, c) for c in clips) == ["high", "low", "middle"]
        assert len({_speaker(db, c) for c in clips}) == 3
        assert {_uuid(11), _uuid(21)} <= {c["clip_id"] for c in clips}
        assert {c["source"] for c in clips} == {"community", "training"}
        never = {_uuid(31), _uuid(81), _uuid(91)}   # mine, not set up, archived
        assert not never & {c["clip_id"] for c in clips}
        # Fixed for the Take: asked again, the same three in the same order.
        assert _queue(db) == clips
        # A blind order: the place never tells the level.
        places = {[_level(db, c) for c in _queue(db, take=_uuid(990 + n))].index("high")
                  for n in range(12)}
        assert len(places) > 1
        # Never one I answered: with both imported middles answered, the
        # middle is left out, never filled from another level.
        for clip_id in (_uuid(62), _uuid(71)):
            assert cm.answer(db, listener_id="listener",
                             body={"clip_id": clip_id, "value": "yes"})[0] == 200
        clips = _queue(db, take=_uuid(991))
        assert sorted(_level(db, c) for c in clips) == ["high", "low"]
        # Fewer only with fewer speakers: Ada alone gives one clip, never two.
        lone = _Db()
        _import(lone, IMPORT_A, "Ada", [(_uuid(61), HIGH), (_uuid(62), MIDDLE), (_uuid(63), LOW)])
        assert len(_queue(lone)) == 1
        # Three speakers whose clips crowd one level still fill all three.
        crowd = _Db()
        _import(crowd, IMPORT_A, "Ada", [(_uuid(61), HIGH), (_uuid(62), MIDDLE)])
        _import(crowd, IMPORT_B, "Bo", [(_uuid(71), HIGH), (_uuid(72), LOW)])
        _import(crowd, IMPORT_C, "Cy", [(_uuid(81), HIGH)])
        clips = _queue(crowd)
        assert sorted(_level(crowd, c) for c in clips) == ["high", "low", "middle"]
        assert len({_speaker(crowd, c) for c in clips}) == 3


def test_an_imported_clip_plays_by_a_signed_link_audio_only():
    with SIGNED:
        db = _Db()
        _import(db, IMPORT_A, "Ada", [(_uuid(61), HIGH)])
        [clip] = _queue(db)
    assert clip == {"clip_id": _uuid(61), "source": "training",
                    "audio_ref": f"https://signed.example/corpus/{_uuid(61)}.webm?ttl=900",
                    "start_offset_ms": 4000, "duration_ms": 2500, "community": None}
    served = json.dumps(clip)
    for private in ("Ada", "Board pitch", "an imported speaker's words", IMPORT_A,
                    "0.8", "delivery_signal"):
        assert private not in served
    # A clip whose sound cannot be signed is never served.
    with patch("services.audio_ref_resolver.resolve_playable_ref", lambda *_a, **_k: None):
        assert _queue(db) == []


def test_an_answer_on_an_imported_clip_is_kept_once_and_never_a_label():
    db, _ = _imported_world()
    body = {"clip_id": _uuid(61), "value": "in_between"}
    assert cm.answer(db, listener_id="listener", body=body) == (200, {"recorded": True})
    assert cm.answer(db, listener_id="listener", body=body) == (409, {"code": "ALREADY_ANSWERED"})
    assert db.import_answers == [{"listener_user_id": "listener", "snippet_id": _uuid(61),
                                  "import_session_id": IMPORT_A, "value": "in_between",
                                  "created_at": db.import_answers[0]["created_at"]}]
    # Never a label, never a community answer: the coaches' ledger and the
    # peer rows are untouched.
    assert db.ratings == [] and db.answers == []
    # A clip of an import not set up, or archived, is not one to answer.
    for clip_id in (_uuid(81), _uuid(91)):
        assert cm.answer(db, listener_id="listener",
                         body={"clip_id": clip_id, "value": "yes"}) == (404, {"code": "CLIP_NOT_FOUND"})
    with SIGNED:
        assert _uuid(61) not in {c["clip_id"] for c in _queue(db)}


def test_the_replay_lists_imported_clips():
    db, _ = _imported_world()
    assert cm.answer(db, listener_id="listener", body={"clip_id": _uuid(21), "value": "no"})[0] == 200
    assert cm.answer(db, listener_id="listener", body={"clip_id": _uuid(61), "value": "yes"})[0] == 200
    with SIGNED:
        status, payload = cm.my_answers(db, listener_id="listener")
    assert status == 200
    assert [(a["clip_id"], a["value"]) for a in payload["answers"]] == [(_uuid(61), "yes"), (_uuid(21), "no")]
    imported = payload["answers"][0]
    assert imported["audio_ref"] == f"https://signed.example/corpus/{_uuid(61)}.webm?ttl=900"
    assert (imported["source"], imported["community"]) == ("training", None)
    assert "Ada" not in json.dumps(payload)


def test_an_empty_queue_is_logged_with_why(caplog):
    with caplog.at_level(logging.INFO, logger="services.lend_your_ear"):
        assert _queue(_Db()) == []
    empty = [r for r in caplog.records if "no other speakers" in r.getMessage()]
    assert empty and empty[0].levelno == logging.WARNING
    assert "high: no clip" in empty[0].getMessage()
    caplog.clear()
    lone = _Db()
    with SIGNED, caplog.at_level(logging.INFO, logger="services.lend_your_ear"):
        _import(lone, IMPORT_A, "Ada", [(_uuid(61), HIGH), (_uuid(62), MIDDLE)])
        assert len(_queue(lone)) == 1
    short = [r for r in caplog.records if "fewer than three" in r.getMessage()]
    assert short and "speaker already in the set" in short[0].getMessage()
