"""The walk's line bank routes (D-FW-3 wired; 0438): the walk reads which
line each signed bank says next, shows it, and records it as shown.

Pins: ``upcoming`` names exactly the index the next ``pick`` records, for
every bank, before and after lines were said, and records nothing; after a
later line the ordinary rotation goes on where it was; a line recorded with
``shown`` is never the one shown just before; an unknown bank is refused
before any write; a memory that cannot answer degrades to "keep your own
turn" (GET) or an error (POST), never a repeat; the routes are
authenticated, wired and carry indexes only."""
from __future__ import annotations

from pathlib import Path

import pytest

from services import line_rotation as rotation
from services.line_bank import BANKS

ROOT = Path(__file__).resolve().parents[1]


class _Memory:
    """The SQL function's rule and the table, in memory (the PG suite runs
    the real function)."""

    def __init__(self, raises: Exception | None = None):
        self.rows: dict = {}
        self.raises = raises

    def pick_line_bank_line(self, *, user_id, bank, size, later_true):
        if self.raises:
            raise self.raises
        last, plain = self.rows.get((user_id, bank), (None, None))
        if later_true and last != -1:
            nxt = -1
        else:
            nxt = ((plain if plain is not None else -1) + 1) % size
            plain = nxt
        self.rows[(user_id, bank)] = (nxt, plain)
        return nxt

    def read_line_bank_memory(self, *, user_id):
        if self.raises:
            raise self.raises
        return [{"bank": bank, "last_index": last, "last_plain_index": plain}
                for (user, bank), (last, plain) in self.rows.items() if user == user_id]


def test_upcoming_names_the_first_line_of_every_bank_before_any_was_said():
    assert rotation.upcoming(_Memory(), user_id="u") == {bank: 0 for bank in BANKS}


@pytest.mark.parametrize("bank", sorted(BANKS))
def test_upcoming_is_exactly_what_the_next_pick_records(bank):
    memory = _Memory()
    said = []
    for _ in range(len(BANKS[bank]) * 2 + 1):
        expected = rotation.upcoming(memory, user_id="u")[bank]
        status, body = rotation.shown(memory, user_id="u", body={"bank": bank})
        assert status == 200 and body == {"bank": bank, "index": expected}
        said.append(expected)
    assert all(a != b for a, b in zip(said, said[1:]))


def test_upcoming_records_nothing_and_is_per_speaker():
    memory = _Memory()
    rotation.shown(memory, user_id="u", body={"bank": "B13"})
    before = dict(memory.rows)
    assert rotation.upcoming(memory, user_id="u")["B13"] == 1
    assert rotation.upcoming(memory, user_id="u")["B13"] == 1
    assert memory.rows == before
    assert rotation.upcoming(memory, user_id="someone else")["B13"] == 0


def test_after_a_later_line_the_rotation_goes_on_where_it_was():
    memory = _Memory()
    rotation.shown(memory, user_id="u", body={"bank": "B02"})        # 0
    memory.pick_line_bank_line(user_id="u", bank="B02", size=len(BANKS["B02"]),
                               later_true=True)                       # -1
    assert rotation.upcoming(memory, user_id="u")["B02"] == 1


def test_a_stale_or_odd_row_starts_the_bank_again():
    class _Odd(_Memory):
        def read_line_bank_memory(self, *, user_id):
            return [{"bank": "B13", "last_plain_index": 99},
                    {"bank": "B14", "last_plain_index": True},
                    {"bank": "ZZ99", "last_plain_index": 0}, "junk"]
    out = rotation.upcoming(_Odd(), user_id="u")
    assert out["B13"] == 0 and out["B14"] == 0 and "ZZ99" not in out


@pytest.mark.parametrize("body", [None, {}, {"bank": "B99"}, {"bank": 13}, {"bank": ""}])
def test_an_unknown_bank_is_refused_before_any_write(body):
    memory = _Memory()
    assert rotation.shown(memory, user_id="u", body=body) == (
        400, {"code": "INVALID_INPUT", "error": "bank must be a signed bank"})
    assert memory.rows == {}


def test_a_memory_that_cannot_answer_never_risks_a_repeat():
    down = _Memory(raises=RuntimeError("connection reset"))
    assert rotation.upcoming(down, user_id="u") == {}
    assert rotation.shown(down, user_id="u", body={"bank": "B13"})[0] == 503
    assert rotation.upcoming(_Memory(), user_id="") == {}


def test_the_routes_are_authenticated_wired_and_carry_indexes_only():
    source = (ROOT / "routes/v2/line_bank.py").read_text()
    for route, method in (('"/user/line-bank"', "GET"), ('"/user/line-bank/shown"', "POST")):
        head = source[source.index(f"@v2_bp.route({route}"):]
        head = head[:head.index("def ")]
        assert f'methods=["{method}"]' in head and "@require_auth" in head
    from routes.v2 import DOMAIN_MODULES
    assert "line_bank" in DOMAIN_MODULES
    # No signed text leaves through these routes: only bank names and indexes.
    assert "line(" not in source and "say(" not in source


def test_the_routes_reach_the_service():
    from unittest.mock import patch

    from flask import Flask, request

    from routes.v2 import line_bank

    memory = _Memory()
    app = Flask(__name__)
    with patch.object(line_bank, "db", memory):
        with app.test_request_context("/v2/user/line-bank/shown", method="POST",
                                      json={"bank": "B13"}):
            request.user_id = "u"
            response, status = line_bank.v2_user_line_bank_shown.__wrapped__()
        assert (status, response.get_json()) == (200, {"bank": "B13", "index": 0})
        with app.test_request_context("/v2/user/line-bank"):
            request.user_id = "u"
            response, status = line_bank.v2_user_line_bank.__wrapped__()
        assert status == 200 and response.get_json()["next"]["B13"] == 1
