"""A Lounge clip gets a fresh link only from the reader's own recording,
and a coach's video only while it is their word's current one."""
from services.lounge_clips import refresh_walk_clips


class _Db:
    def get_snippets_by_session(self, sid):
        return [{"id": "s1", "user_id": "me", "start_offset_ms": 10, "duration_ms": 20},
                {"id": "s2", "user_id": "other"}]


def _msg(snippet):
    return {"kind": "walk_step", "metadata": {
        "take_session_id": "t1", "clip": {"src": "old", "snippet_id": snippet}}}


def test_own_clip_is_resigned_and_another_users_is_not():
    mine, theirs = _msg("s1"), _msg("s2")
    refresh_walk_clips([mine, theirs], "me", _Db(), lambda row: f"fresh-{row['id']}")
    assert mine["metadata"]["clip"] == {"src": "fresh-s1", "snippet_id": "s1",
                                        "start_ms": 10, "duration_ms": 20}
    assert theirs["metadata"]["clip"]["src"] == "old"


class _Takes:
    def __init__(self, fail=False):
        self.fail = fail

    def get_arc_sessions_many(self, arcs):
        if self.fail:
            raise RuntimeError("decks down")
        return {"arc1": [{"id": "t1", "user_id": "me", "arc_id": "arc1",
                          "take_index": 1,
                          "intake_context": {"presentation_ref": "s3://b/deck.pdf"}}]}


class _PageDb(_Db):
    """One read of every Take's recordings, one of every project's Takes,
    one of the coach flags — what one Lounge page costs now."""

    def __init__(self, fail_decks=False):
        self.takes = _Takes(fail=fail_decks)
        self.calls = []

    def get_snippet_audio_rows_by_sessions(self, sids):
        self.calls.append(("snippets", tuple(sids)))
        return {"t1": [{"id": "s1", "user_id": "me", "session_id": "t1",
                        "start_offset_ms": 10, "duration_ms": 20,
                        "audio_segment_path": "s3://b/take.webm"}]}

    def get_snippets_by_session(self, sid):
        raise AssertionError("the batch read serves every Take on the page")

    def new_coach_feedback_by_project(self, user_id):
        return {"arc1": True, "arc2": False}


def _page(*messages):
    return {"messages": list(messages), "has_more": False, "oldest_cursor": None}


def test_one_page_gets_fresh_links_decks_and_flags_from_batched_reads(monkeypatch):
    from services import lounge_clips
    monkeypatch.setattr("services.coach_video_storage.refreshed_media_url",
                        lambda ref: f"deck-{ref}")
    clip = _msg("s1")
    take = {"kind": "recording_summary", "metadata": {"session_id": "t1"}}
    card = {"kind": "ideal_text", "metadata": {"arc_id": "arc1"}}
    page = _page(clip, take, card)
    db = _PageDb()
    lounge_clips.enrich_page(
        page, "me", db,
        resolve_snippet=lambda row: f"fresh-{row['id']}",
        resolve_ref=lambda ref: f"signed-{ref}", with_flags=True)
    assert clip["metadata"]["clip"]["src"] == "fresh-s1"
    assert take["metadata"]["audio"] == {"src": "signed-s3://b/take.webm"}
    assert card["metadata"]["deck"] == {"presentation_ref": "deck-s3://b/deck.pdf"}
    assert page["new_coach_feedback"] == {"arc1": True, "arc2": False}
    assert db.calls == [("snippets", ("t1",))]


MINE = "11111111-1111-4111-8111-111111111111"
THEIRS = "22222222-2222-4222-8222-222222222222"
K1 = f"coach-feedback/{MINE}/k1.webm"
K2 = f"coach-feedback/{MINE}/k2.webm"


def _signed(key):
    return f"https://acct.r2.example/coach-videos/{key}?X-Amz-Signature=old"


class _CoachDb:
    """The coach's word for my Take: words W2 with video K2, shared at 10:00
    and last changed at 12:00."""

    def __init__(self, seen_at=None):
        self.seen_at = seen_at

    def list_owned_take_ids(self, user_id, takes):
        assert sorted(takes) == sorted([MINE, THEIRS])
        return {MINE}

    def list_shared_coach_take_words(self, takes):
        assert takes == [MINE]
        return [{"take_session_id": MINE, "text": "Breathe before the price.",
                 "video_ref": f"s3://coach-videos/{K2}",
                 "shared_at": "2026-10-19T10:00:00+00:00",
                 "updated_at": "2026-10-19T12:00:00+00:00"}]

    def list_coach_take_word_seen(self, user_id, takes):
        return {MINE: self.seen_at} if self.seen_at else {}


def _coach(client_id, take, words, video, *, update=True):
    meta = {"step": "coachnote", "author": "coach", "take_session_id": take,
            "video": video}
    if update:
        meta.update(coach_update=True, heading="Later · from your coach")
    return {"client_id": client_id, "kind": "walk_step",
            "body": f"Your coach\n{words}", "metadata": meta}


def test_a_coach_video_plays_only_while_it_is_the_word_s_current_one(monkeypatch):
    """N80 (founder 2026-10-19): one "Later · from your coach" bubble per
    word, a removed or replaced coach video never plays again in the chat,
    and the bubble is "new" until the word is watched."""
    from services import lounge_clips
    signed = []
    monkeypatch.setattr("services.coach_video_storage.r2_bucket_name", lambda: "coach-videos")
    monkeypatch.setattr("services.coach_video_storage.refreshed_media_url",
                        lambda ref: signed.append(ref) or f"fresh-{ref}")

    def read(db):
        page = _page(
            _coach("older", MINE, "Slow the opening.", _signed(K1)),
            _coach("walk", MINE, "Slow the opening.", _signed(K1), update=False),
            _coach("current", MINE, "Breathe before the price.", _signed(K2)),
            _coach("theirs", THEIRS, "Not yours.", "https://elsewhere/v.webm"))
        lounge_clips.enrich_page(page, "me", db, resolve_snippet=lambda row: None,
                                 resolve_ref=lambda ref: None, with_flags=False)
        return {m["client_id"]: m["metadata"] for m in page["messages"]}

    shown = read(_CoachDb())
    assert list(shown) == ["walk", "current", "theirs"]
    assert shown["current"]["video"] == f"fresh-s3://coach-videos/{K2}"
    assert shown["current"]["unseen"] is True
    assert shown["walk"]["video"] is None and shown["walk"]["unseen"] is True
    assert shown["theirs"]["video"] == "https://elsewhere/v.webm"
    assert "unseen" not in shown["theirs"]
    assert signed == [f"s3://coach-videos/{K2}"]

    watched = read(_CoachDb(seen_at="2026-10-19T13:00:00+00:00"))
    assert watched["current"]["unseen"] is False and watched["walk"]["unseen"] is False


def test_an_older_page_carries_no_flags_and_a_failed_step_costs_only_itself(monkeypatch):
    from services import lounge_clips
    clip = _msg("s1")
    card = {"kind": "ideal_text", "metadata": {"arc_id": "arc1"}}
    page = _page(clip, card)
    lounge_clips.enrich_page(
        page, "me", _PageDb(fail_decks=True),
        resolve_snippet=lambda row: f"fresh-{row['id']}",
        resolve_ref=lambda ref: None, with_flags=False)
    assert clip["metadata"]["clip"]["src"] == "fresh-s1"
    assert "deck" not in card["metadata"]
    assert "new_coach_feedback" not in page
