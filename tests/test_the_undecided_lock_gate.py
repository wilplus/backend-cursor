"""The old "undecided" lock gate is gone (founder 2026-10-05, "i guess
yes"; F1 Repair Plan Phase 5 question).

`PUT /explore/arc/<arc>/parts/<part>/lock` used to refuse with 409 UNDECIDED
while any served row on the paragraph was neither approved nor dismissed -- a
V3 rewrite or praise note included -- and the page read that refusal as final,
so helper words saved while their lock did not. The route no longer asks.
`undecided` stays the page-colour rule it also was.
"""
from pathlib import Path

from services.ideal_text_changes import undecided

ROOT = Path(__file__).resolve().parents[1]


def test_an_open_note_is_still_undecided_for_the_page():
    rows = [
        {"id": "cv", "feedback_family": "confident_voice", "status": "approved"},
        {"id": "rw", "feedback_family": "rewrite_clarity", "status": "pending"},
        {"id": "pr", "feedback_family": "great_formulation"},
        {"id": "kept", "feedback_family": "rewrite_clarity", "status": "dismissed"},
    ]
    assert [r["id"] for r in undecided(rows)] == ["rw", "pr"]


def test_the_lock_route_no_longer_refuses_on_open_feedback():
    source = (ROOT / "routes/v2/explore_ideal_text.py").read_text()
    start = source.index("def v2_explore_set_part_lock(")
    body = source[start:source.index("@v2_bp.route", start)]
    assert "undecided(" not in body
    assert '"code": "UNDECIDED"' not in body
    assert "_tracked_changes_block(" not in body
