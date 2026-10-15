"""A Lounge clip gets a fresh link only from the reader's own recording."""
from services.lounge_clips import refresh_walk_clips


class _Db:
    def get_snippets_by_sessions(self, sids, **_):
        return {sid: [{"id": "s1", "user_id": "me", "start_offset_ms": 10,
                       "duration_ms": 20},
                      {"id": "s2", "user_id": "other"}] for sid in sids}


def _msg(snippet):
    return {"kind": "walk_step", "metadata": {
        "take_session_id": "t1", "clip": {"src": "old", "snippet_id": snippet}}}


def test_own_clip_is_resigned_and_another_users_is_not():
    mine, theirs = _msg("s1"), _msg("s2")
    refresh_walk_clips([mine, theirs], "me", _Db(), lambda row: f"fresh-{row['id']}")
    assert mine["metadata"]["clip"] == {"src": "fresh-s1", "snippet_id": "s1",
                                        "start_ms": 10, "duration_ms": 20}
    assert theirs["metadata"]["clip"]["src"] == "old"
