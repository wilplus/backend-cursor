"""Which signed line to say next (D-FW-3; docs/SIGNED-line-bank-2026-10-06.md
"Rotation"; the Feedback walk lock, "Line bank").

Pins: pick() never repeats an index twice in a row within a bank for one
speaker; a later line only from Take 2 on, naming the real earlier Take,
and only when its cue was measurably weaker then; never the later line
twice in a row; no memory, no line; nothing but signed words; the table is
purged with the account."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from services import line_rotation as rotation
from services.line_bank import BANKS, LATER

ROOT = Path(__file__).resolve().parents[1]


class _Memory:
    """The SQL function's rule, in memory (the PG suite runs the real one)."""

    def __init__(self):
        self.rows: dict = {}
        self.calls: list = []

    def pick_line_bank_line(self, *, user_id, bank, size, later_true):
        self.calls.append((user_id, bank, size, later_true))
        last, plain = self.rows.get((user_id, bank), (None, None))
        if later_true and last != -1:
            nxt = -1
        else:
            nxt = ((plain if plain is not None else -1) + 1) % size
            plain = nxt
        self.rows[(user_id, bank)] = (nxt, plain)
        return nxt


WEAKER_THEN = {"pitch_range": -0.4}
STRONGER_NOW = {"pitch_range": 0.4}      # +0.8 z: B02's cue (wide_range)


@pytest.mark.parametrize("bank", sorted(BANKS))
def test_pick_never_repeats_an_index_twice_in_a_row(bank):
    memory = _Memory()
    shown = [rotation.pick(memory, user_id="u", bank=bank)["index"] for _ in range(20)]
    assert all(a != b for a, b in zip(shown, shown[1:]))
    assert set(shown) == set(range(len(BANKS[bank])))
    assert memory.calls[0][2] == len(BANKS[bank])


def test_each_speaker_and_each_bank_rotates_on_its_own():
    memory = _Memory()
    assert rotation.pick(memory, user_id="a", bank="B02")["index"] == 0
    assert rotation.pick(memory, user_id="b", bank="B02")["index"] == 0
    assert rotation.pick(memory, user_id="a", bank="B03")["index"] == 0
    assert rotation.pick(memory, user_id="a", bank="B02")["index"] == 1


def test_a_later_line_needs_take_two_a_real_earlier_take_and_a_weaker_cue():
    ok = dict(take_index=2, earlier_take_index=1,
              reads_now=STRONGER_NOW, reads_then=WEAKER_THEN)
    assert rotation.later_is_true("B02", **ok) is True
    # Take 1 has no earlier Take.
    assert rotation.later_is_true("B02", **{**ok, "take_index": 1}) is False
    # The earlier Take must be earlier, and a real Take number.
    assert rotation.later_is_true("B02", **{**ok, "earlier_take_index": 2}) is False
    assert rotation.later_is_true("B02", **{**ok, "earlier_take_index": 0}) is False
    assert rotation.later_is_true("B02", **{**ok, "earlier_take_index": None}) is False
    assert rotation.later_is_true("B02", **{**ok, "take_index": True}) is False
    # Not measurably weaker then: a gain below the bar, none, or no read.
    assert rotation.later_is_true(
        "B02", **{**ok, "reads_now": {"pitch_range": -0.1}}) is False
    assert rotation.later_is_true("B02", **{**ok, "reads_now": WEAKER_THEN}) is False
    assert rotation.later_is_true("B02", **{**ok, "reads_then": None}) is False
    # Another cue moving is not this bank's truth.
    assert rotation.later_is_true("B03", **ok) is False
    # The general lines need some cue that moved that far.
    assert rotation.later_is_true("B01", **ok) is True
    assert rotation.later_is_true("B09", **ok) is True
    # The clearer and practise banks have no later line.
    assert rotation.later_is_true("B13", **ok) is False


def test_the_later_line_carries_the_real_take_number_and_is_never_shown_twice_in_a_row():
    memory = _Memory()
    ok = dict(take_index=3, earlier_take_index=2,
              reads_now=STRONGER_NOW, reads_then=WEAKER_THEN)
    first = rotation.pick(memory, user_id="u", bank="B02", **ok)
    assert first == {"bank": "B02", "later_take": 2}
    assert rotation.say(first) == "Your voice moved more here than on Take 2."
    # True again on the next pick: an ordinary line instead, never the same
    # later line twice in a row.
    second = rotation.pick(memory, user_id="u", bank="B02", **ok)
    assert second == {"bank": "B02", "index": 0}
    third = rotation.pick(memory, user_id="u", bank="B02", **ok)
    assert third == {"bank": "B02", "later_take": 2}


def test_take_one_never_gets_a_later_line():
    memory = _Memory()
    choice = rotation.pick(memory, user_id="u", bank="B02", take_index=1,
                           earlier_take_index=None, reads_now=STRONGER_NOW,
                           reads_then=WEAKER_THEN)
    assert choice == {"bank": "B02", "index": 0}
    assert memory.calls[-1][3] is False


def test_no_memory_no_line_and_an_unknown_bank_is_refused():
    class _Down:
        def pick_line_bank_line(self, **_kwargs):
            raise RuntimeError("database down")
    assert rotation.pick(_Down(), user_id="u", bank="B02") is None
    assert rotation.pick(_Memory(), user_id="u", bank="B99") is None
    assert rotation.pick(_Memory(), user_id="", bank="B02") is None

    class _Odd:
        def pick_line_bank_line(self, **_kwargs):
            return 99
    assert rotation.pick(_Odd(), user_id="u", bank="B02") is None


def test_say_renders_only_signed_words():
    for bank, lines in BANKS.items():
        for index, text in enumerate(lines):
            assert rotation.say({"bank": bank, "index": index}) == text
    for bank in LATER:
        said = rotation.say({"bank": bank, "later_take": 4})
        assert said == LATER[bank].replace("{n}", "4")
        # The Take number is the only number a line carries (AC-9).
        assert re.sub(r"Take 4", "", said) == re.sub(r"\d", "", re.sub(r"Take 4", "", said))
    assert rotation.say({"bank": "B13", "later_take": 2}) is None
    assert rotation.say({"bank": "B02", "index": 9}) is None
    assert rotation.say({"bank": "B02", "later_take": 0}) is None
    assert rotation.say({"bank": "nope", "index": 0}) is None
    assert rotation.say("B02") is None


def test_the_migration_is_listed_and_the_purge_knows_the_table():
    from services import data_purge_project_scope as scope
    from services.data_purge_registry import DEPENDENCIES

    manifest = (ROOT / "migrations" / "manifest.txt").read_text()
    assert "0438\ta_line_is_never_said_twice_in_a_row.sql" in manifest
    sql = (ROOT / "migrations" / "a_line_is_never_said_twice_in_a_row.sql").read_text()
    assert "CREATE TABLE IF NOT EXISTS public.line_bank_memory" in sql
    assert "CREATE OR REPLACE FUNCTION public.pick_line_bank_line_v1" in sql
    assert "ENABLE ROW LEVEL SECURITY" in sql
    assert "DROP " not in re.sub(r"--.*", "", sql).upper()
    dependency = {d.relation: d for d in DEPENDENCIES}["line_bank_memory"]
    assert (dependency.selector_column, dependency.locator_kind,
            dependency.disposition) == ("user_id", "user", "delete")
    assert "line_bank_memory" in scope.ACCOUNT_LEVEL


def test_the_database_call_reads_the_index_whatever_shape_it_comes_in():
    from types import SimpleNamespace

    from services.db import DatabaseService

    class _Rpc:
        def __init__(self, data):
            self.data = data
            self.args = None

        def rpc(self, name, args):
            self.args = (name, args)
            return self

        def execute(self):
            return self

    def call(client):
        return DatabaseService.pick_line_bank_line(
            SimpleNamespace(client=client),  # type: ignore[arg-type]
            user_id="u", bank="B02", size=4, later_true=False)

    for data, want in ((2, 2), ([3], 3), ([{"pick_line_bank_line_v1": -1}], -1)):
        client = _Rpc(data)
        assert call(client) == want
        assert client.args == ("pick_line_bank_line_v1", {
            "p_user_id": "u", "p_bank": "B02", "p_size": 4, "p_later_true": False})
    with pytest.raises(ValueError):
        call(_Rpc([]))
