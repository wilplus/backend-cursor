"""Rows keyed by a signed-in user's id are found by the `user` locator.

coach_id, listener_user_id and rater_id on the 0409-0411 tables hold
request.user_id, never an owner principal's id. Under the `principal`
locator they matched nothing and outlived a deleted account (found
2026-10-06 while building 0432). This pins them to `user`, and checks
that an account's purge graph reaches them through its user ids.
"""
from __future__ import annotations

from services.data_purge import SubjectGraph
from services.data_purge_registry import DEPENDENCIES

USER_KEYED = {
    "coach_readings": ("coach_readings", "coach_id"),
    "lend_your_ear_answers": ("lend_your_ear_answers", "listener_user_id"),
    "delayed_measure_votes": ("delayed_measure_votes", "rater_id"),
    "coach_exercise_preference_by_coach": ("coach_exercise_preference", "coach_id"),
    "error_presence_audit_by_coach": ("error_presence_audit", "coach_id"),
    "coach_block_pick_by_coach": ("coach_block_pick", "coach_id"),
    "coach_clip_exposures": ("coach_clip_exposures", "coach_id"),
}


def _by_code():
    return {d.code: d for d in DEPENDENCIES}


def test_user_keyed_rows_use_the_user_locator():
    by = _by_code()
    for code, (relation, column) in USER_KEYED.items():
        dep = by[code]
        assert (dep.relation, dep.selector_column, dep.locator_kind) == (
            relation, column, "user"), code
        assert dep.disposition == "delete", code


def test_an_account_graph_reaches_them_by_user_id():
    graph = SubjectGraph(principal_ids=("p-1",), user_ids=("u-1",))
    by = _by_code()
    for code in USER_KEYED:
        assert graph.values(by[code].locator_kind) == ("u-1",), code
