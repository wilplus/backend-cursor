"""The old "undecided" lock gate, pinned as it stands (F1 Repair Plan Phase 5).

`PUT /explore/arc/<arc>/parts/<part>/lock` refuses with 409 UNDECIDED while
any served row on the paragraph is neither approved nor dismissed -- a V3
rewrite or praise note included. The page reads that refusal as final
(`saveBehind`), so the helper words can save while the lock that should
follow them does not. Whether the gate stays is the founder's call; this
test only makes its rule visible so that call is made on the code.
"""
from pathlib import Path

from services.ideal_text_changes import undecided

ROOT = Path(__file__).resolve().parents[1]


def test_an_open_note_is_undecided():
    rows = [
        {"id": "cv", "feedback_family": "confident_voice", "status": "approved"},
        {"id": "rw", "feedback_family": "rewrite_clarity", "status": "pending"},
        {"id": "pr", "feedback_family": "great_formulation"},
        {"id": "kept", "feedback_family": "rewrite_clarity", "status": "dismissed"},
    ]
    assert [r["id"] for r in undecided(rows)] == ["rw", "pr"]


def test_the_lock_route_refuses_while_any_is_open():
    source = (ROOT / "routes/v2/explore_ideal_text.py").read_text()
    start = source.index("def v2_explore_set_part_lock(")
    body = source[start:source.index("@v2_bp.route", start)]
    assert "undecided(_served)" in body
    assert '"code": "UNDECIDED"' in body
