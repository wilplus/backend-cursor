"""A Lounge clip gets a fresh link only from the reader's own recording."""
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
    lounge_clips.enrich_lounge_page(
        page, "me", db,
        resolve_snippet=lambda row: f"fresh-{row['id']}",
        resolve_ref=lambda ref: f"signed-{ref}", with_flags=True)
    assert clip["metadata"]["clip"]["src"] == "fresh-s1"
    assert take["metadata"]["audio"] == {"src": "signed-s3://b/take.webm"}
    assert card["metadata"]["deck"] == {"presentation_ref": "deck-s3://b/deck.pdf"}
    assert page["new_coach_feedback"] == {"arc1": True, "arc2": False}
    assert db.calls == [("snippets", ("t1",))]


def test_an_older_page_carries_no_flags_and_a_failed_step_costs_only_itself(monkeypatch):
    from services import lounge_clips
    clip = _msg("s1")
    card = {"kind": "ideal_text", "metadata": {"arc_id": "arc1"}}
    page = _page(clip, card)
    lounge_clips.enrich_lounge_page(
        page, "me", _PageDb(fail_decks=True),
        resolve_snippet=lambda row: f"fresh-{row['id']}",
        resolve_ref=lambda ref: None, with_flags=False)
    assert clip["metadata"]["clip"]["src"] == "fresh-s1"
    assert "deck" not in card["metadata"]
    assert "new_coach_feedback" not in page
