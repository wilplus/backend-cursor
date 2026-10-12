"""Which Ideal Text heads the repair script republishes.

Founder 2026-09-18: "after a lock the text skipped the slides and got
concatenated again."  A head whose pieces all carry ``slide_index`` NULL makes
``groupChunksBySlide`` fail on the first paragraph (``missing_parent_slide``),
and the deck collapses into one unlinked "Your talk" section with no slide
kickers and no slide preview.

The script has to be exactly as strict as the client's reader: too loose and
it rewrites healthy documents, too tight and the broken ones stay broken. One
contract test through ``main()`` (founder 2026-10-12, "How to test"), in place
of sixteen tests of its private helpers.
"""
import sys

import scripts.backfill_piece_slide_lineage as backfill


def piece(slide):
    return {"piece_key": 0, "text": "words", "slide_index": slide}


# arc -> the head's payload. Only the two marked POISONED render flat.
HEADS = {
    "all-null": {"pieces": [piece(None), piece(None), piece(None)]},  # POISONED
    "healthy": {"pieces": [piece(0), piece(1), piece(2)]},
    # The first slide is index 0; a falsy check would call this unlinked.
    "zero-only": {"pieces": [piece(0), piece(0)]},
    # A NULL that FOLLOWS a real index is legitimate: the client inherits it.
    "trailing-null": {"pieces": [piece(0), piece(None), piece(1)]},
    # Renders flat, but the lineage is partly provable: left out on purpose.
    "leading-null": {"pieces": [piece(None), piece(1)]},
    # One paragraph is one section either way: nothing to buy.
    "single": {"pieces": [piece(None)]},
    # Non-mapping rows are not paragraphs, so this is still one.
    "single-with-junk": {"pieces": [piece(None), "junk", None]},
    "empty": {"pieces": []},
    "no-block": {},
    "non-list": {"pieces": "nope"},
    # The client's reader rejects bool, negative and non-int indexes, and
    # drops non-mapping rows, so this document has no link at all.
    "junk-indexes": {"pieces": [piece(True), piece(-1), piece("0"),    # POISONED
                                piece(1.5), "junk", None]},
}


class _Query:
    def __init__(self, rows):
        self.rows = rows

    def select(self, *_a):
        return self

    def eq(self, column, value):
        return _Query([r for r in self.rows if r[column] == value])

    def limit(self, _n):
        return self

    def execute(self):
        return type("R", (), {"data": self.rows})()


class _Db:
    def __init__(self):
        self.heads = dict(HEADS)
        self.client = type("C", (), {"table": lambda _s, _name: _Query(
            [{"arc_id": arc, "actor_id": "u1", "snapshot_id": "s"}
             for arc in HEADS])})()

    def get_ideal_text_document_snapshot(self, arc_id, _actor_id):
        return {"payload": self.heads[arc_id]}


def test_only_heads_that_lost_every_slide_link_are_republished(
        monkeypatch, capsys):
    published = []
    database = _Db()

    def publish(_db, arc, _actor, **_kw):
        # The publisher re-derives the lineage where provenance proves it
        # (here: slide 0 is index 0) and fails closed to NULL where not.
        published.append(arc)
        if arc == "all-null":
            database.heads[arc] = {"pieces": [piece(0), piece(0), piece(1)]}
        return {"snapshot_id": "new"}

    monkeypatch.setattr(backfill, "db", database)
    monkeypatch.setattr(backfill, "publish_for_arc", publish)

    # Preview is the default: it names the poisoned heads and writes nothing.
    monkeypatch.setattr(sys, "argv", ["backfill"])
    assert backfill.main() == 0
    out = capsys.readouterr().out
    named = {line.split("arc=")[1].split()[0]
             for line in out.splitlines() if "paragraphs=" in line}
    assert named == {"all-null", "junk-indexes"}
    assert published == []

    # --apply republishes exactly those, and a head that is still unlinked
    # after the publish is reported UNRECOVERED, never counted as repaired.
    monkeypatch.setattr(sys, "argv", ["backfill", "--apply"])
    assert backfill.main() == 0
    out = capsys.readouterr().out
    assert sorted(published) == ["all-null", "junk-indexes"]
    assert "repaired arc=all-null (3/3 paragraphs linked)" in out
    assert "UNRECOVERED arc=junk-indexes" in out
    assert "repaired 1, unrecovered 1" in out
