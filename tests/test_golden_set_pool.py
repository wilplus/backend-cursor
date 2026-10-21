"""
STORY      As the founder, I want the golden set I judge to be drawn only from
           moments that real, blind, independent listeners labelled, so that
           the evaluation is measured against the same labels the app learns
           from (N111, B2).
OUTCOME    The confidence pool offers a moment labelled blind by a coach or
           another speaker inside practice, and skips a speaker's own answer,
           an answer from any other lane, and an answer given after seeing
           the clip's other side.
PROVES     test_the_confidence_pool_takes_only_blind_independent_labels
WHY        walk I1 (labels come only from blind answers); LEARNING-AND-QUORUM
           §3 B2: the pool used to read every row.
"""
from __future__ import annotations

from unittest.mock import patch

from services import golden_set as gs


class _Db:
    def __init__(self, rows):
        self.rows = rows

    def list_golden_judgements(self, *, surface, judge=None):
        return []

    def get_confidence_label_corpus(self, *, source=None, limit=5000):
        return self.rows

    def get_snippet_by_id(self, snippet_id, _user):
        return {"id": snippet_id, "session_id": "t1", "transcript": snippet_id}


def _offered(rows):
    with patch("services.snippet_audio_url.resolve_snippet_audio_url", return_value="u"):
        moment = gs.next_moment(_Db(rows), surface="confidence", judge="founder")
    return moment and moment["snippet_id"]


def test_the_confidence_pool_takes_only_blind_independent_labels():
    skipped = [
        {"snippet_id": "own", "lane": "coach", "self_report": True},
        {"snippet_id": "owner-lane", "lane": "game_owner"},
        {"snippet_id": "no-lane"},
        {"snippet_id": "seen", "lane": "coach", "blind": False},
    ]
    assert _offered(skipped) is None
    assert _offered(skipped + [{"snippet_id": "blind", "lane": "coach", "blind": True}]) == "blind"
    assert _offered([{"snippet_id": "peer", "lane": "game_peer"}]) == "peer"
