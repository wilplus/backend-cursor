"""Every Take rewrites the Slides it spoke (contract 8-9, founder 2026-09-25)."""
from __future__ import annotations

from services.take_rebuild import merge_by_slide, reidentify_parts


def _doc(blocks, slides, *, take=None):
    text = "\n\n".join(blocks)
    paragraphs, pieces, at = [], [], 0
    for block, slide in zip(blocks, slides):
        paragraphs.append({"slide_index": slide, "start": at,
                           "end": at + len(block), "take_index": take})
        pieces.append({"snippet_id": f"s{at}", "start": at,
                       "end": at + len(block), "text": block,
                       "slide_index": slide})
        at += len(block) + 2
    return text, {"paragraphs": paragraphs, "pieces": pieces,
                  "take_session_id": f"t{take}", "take_index": take}


def test_spoken_slides_are_replaced_and_unspoken_ones_kept():
    old_text, old = _doc(["A one.", "B one.", "C one."], [0, 1, 2], take=1)
    new_text, new = _doc(["B two, longer.", "B two again."], [1, 1], take=2)
    r = merge_by_slide(old_text, old, new_text, new)
    assert r is not None
    assert r.text.split("\n\n") == [
        "A one.", "B two, longer.", "B two again.", "C one."]
    assert r.sources == [("old", 0), ("new", 0), ("new", 1), ("old", 2)]
    assert r.slides == [0, 1, 1, 2]
    assert r.rebuilt_slides == {1}
    # Every piece still proves its own words at its new position.
    for piece in r.document["pieces"]:
        assert r.text[piece["start"]:piece["end"]] == piece["text"]
    for para, block in zip(r.document["paragraphs"], r.text.split("\n\n")):
        assert r.text[para["start"]:para["end"]] == block


def test_a_revisited_slide_is_grouped_under_its_slide():
    old_text, old = _doc(["A.", "B."], [0, 1], take=1)
    new_text, new = _doc(["B first.", "A now.", "B again."], [1, 0, 1], take=2)
    r = merge_by_slide(old_text, old, new_text, new)
    assert r.text.split("\n\n") == ["A now.", "B first.", "B again."]


def test_a_new_slide_appears_in_slide_order():
    old_text, old = _doc(["A.", "C."], [0, 2], take=1)
    new_text, new = _doc(["B said at last."], [1], take=2)
    r = merge_by_slide(old_text, old, new_text, new)
    assert r.text.split("\n\n") == ["A.", "B said at last.", "C."]


def test_unprovable_slides_are_never_guessed():
    old_text, old = _doc(["A.", "B."], [0, None], take=1)
    new_text, new = _doc(["B."], [1], take=2)
    assert merge_by_slide(old_text, old, new_text, new) is None
    # Paragraph rows that do not tile the text.
    old["paragraphs"] = old["paragraphs"][:1]
    assert merge_by_slide(old_text, old, new_text, new) is None


def test_no_slide_lineage_anywhere_rebuilds_the_whole_text():
    old_text, old = _doc(["Old."], [None], take=1)
    new_text, new = _doc(["New one.", "New two."], [None, None], take=2)
    r = merge_by_slide(old_text, old, new_text, new)
    assert r.text == new_text


def test_identity_is_kept_for_untouched_and_reused_within_a_slide():
    old_text, old = _doc(["A one.", "B one.", "B two."], [0, 1, 1], take=1)
    rows = [{"id": "a", "ord": 0, "text": "A one.",
             "locked_at": "2026-09-25T10:00:00Z"},
            {"id": "b1", "ord": 1, "text": "B one."},
            {"id": "b2", "ord": 2, "text": "B two."}]
    new_text, new = _doc(["B only now."], [1], take=2)
    parts = reidentify_parts(rows, old_text,
                             merge_by_slide(old_text, old, new_text, new))
    assert [(p["id"], p["text"]) for p in parts] == [
        ("a", "A one."), ("b1", "B only now.")]
    assert parts[0]["locked_at"] == "2026-09-25T10:00:00Z"
    assert [p["ord"] for p in parts] == [0, 1]


def test_rows_that_do_not_tile_the_old_text_get_fresh_ids():
    old_text, old = _doc(["A.", "B."], [0, 1], take=1)
    rows = [{"id": "x", "ord": 0, "text": "Something else."}]
    new_text, new = _doc(["B new."], [1], take=2)
    parts = reidentify_parts(rows, old_text,
                             merge_by_slide(old_text, old, new_text, new))
    assert len(parts) == 2 and "x" not in {p["id"] for p in parts}


def test_edited_rows_keep_their_identity_when_they_count_the_paragraphs():
    """Founder lock 2026-09-30, B1. An owner edit between Takes rewrites the
    stored rows' words, not the machine text. The rows still count the old
    Paragraphs one for one, so every id, lock and helper word follows its
    Paragraph into the rebuild. Until this, the mismatch cost every
    Paragraph a fresh id. The unspoken Slide keeps the edited words, its
    last version (N29), when the rebuild is given the served text."""
    old_text, old = _doc(["A one.", "B one."], [0, 1], take=1)
    rows = [{"id": "a", "ord": 0, "text": "A one, edited by hand.",
             "locked_at": "2026-09-30T10:00:00Z", "root_phrase": "A one"},
            {"id": "b", "ord": 1, "text": "B one, also edited."}]
    served = "\n\n".join(r["text"] for r in rows)
    new_text, new = _doc(["B two."], [1], take=2)
    parts = reidentify_parts(rows, old_text, merge_by_slide(
        old_text, old, new_text, new, current_text=served))
    assert [(p["id"], p["text"]) for p in parts] == [
        ("a", "A one, edited by hand."), ("b", "B two.")]
    assert parts[0]["locked_at"] == "2026-09-30T10:00:00Z"


def test_a_different_count_still_means_fresh_ids():
    """The count is the proof: rows from some other document shape get no
    identity, as before."""
    old_text, old = _doc(["A.", "B."], [0, 1], take=1)
    rows = [{"id": "x", "ord": 0, "text": "A, edited."},
            {"id": "y", "ord": 1, "text": "B, edited."},
            {"id": "z", "ord": 2, "text": "A third that is not there."}]
    new_text, new = _doc(["B new."], [1], take=2)
    parts = reidentify_parts(rows, old_text,
                             merge_by_slide(old_text, old, new_text, new))
    assert {p["id"] for p in parts}.isdisjoint({"x", "y", "z"})


# --------------------------------------------------------------------------- #
#  An unspoken Slide keeps its last version (L1, contract 8, N29)             #
# --------------------------------------------------------------------------- #
def _pieces_prove_their_words(r):
    for piece in r.document["pieces"]:
        assert r.text[piece["start"]:piece["end"]] == piece["text"]
    for para, block in zip(r.document["paragraphs"], r.text.split("\n\n")):
        assert r.text[para["start"]:para["end"]] == block


def test_an_owner_edit_on_an_unspoken_slide_is_kept():
    """The owner edited Slide 2 after Take 1; Take 2 spoke only Slide 1.
    Slide 2 keeps the edited words, not Take 1's machine words; Slide 1 is
    what Take 2 said, though the owner had edited it too (Q5 A)."""
    old_text, old = _doc(["A one.", "B one.", "C one.", "D one."],
                         [0, 1, 2, 3], take=1)
    served = ("A one, edited.\n\nB one.\n\nC one. And more."
              "\n\nD one, reworded.")
    new_text, new = _doc(["A two, said at more length."], [0], take=2)
    r = merge_by_slide(old_text, old, new_text, new, current_text=served)
    assert r is not None
    assert r.text.split("\n\n") == [
        "A two, said at more length.", "B one.", "C one. And more.",
        "D one, reworded."]
    assert r.sources == [("new", 0), ("old", 1), ("old", 2), ("old", 3)]
    assert r.rebuilt_slides == {0}
    _pieces_prove_their_words(r)
    # The untouched Paragraph keeps its piece; the edited ones keep a piece
    # only where it still spells its own words in place ("C one." still
    # opens its Paragraph; "D one." no longer stands in "D one, reworded.").
    assert [(p["text"], p["slide_index"]) for p in r.document["pieces"]] == [
        ("A two, said at more length.", 0), ("B one.", 1), ("C one.", 2)]


def test_an_accepted_rewrite_on_an_unspoken_slide_is_kept():
    """N35.4 / N40: an accepted rewrite is written through the owner-edit
    writer, so it is in the served text. Take 2 did not speak its Slide, so
    the Paragraph keeps the accepted words; the machine piece that no
    longer spells them is not carried (it stays in the version history)."""
    old_text, old = _doc(["We grew a bit.", "Then we stopped."], [0, 1],
                         take=1)
    served = "We grew fast.\n\nThen we stopped."
    new_text, new = _doc(["Then we paused, briefly."], [1], take=2)
    r = merge_by_slide(old_text, old, new_text, new, current_text=served)
    assert r.text == "We grew fast.\n\nThen we paused, briefly."
    assert r.slides == [0, 1]
    _pieces_prove_their_words(r)
    assert [p["text"] for p in r.document["pieces"]] == [
        "Then we paused, briefly."]


def test_identity_lock_and_words_follow_an_accepted_rewrite_kept_unspoken():
    """The Paragraph that kept its accepted words keeps its id and lock (no
    Take rewrite touched it), and the spoken Slide reuses its own id."""
    old_text, old = _doc(["We grew a bit.", "Then we stopped."], [0, 1],
                         take=1)
    rows = [{"id": "a", "ord": 0, "text": "We grew fast.",
             "locked_at": "2026-10-05T10:00:00Z"},
            {"id": "b", "ord": 1, "text": "Then we stopped."}]
    new_text, new = _doc(["Then we paused."], [1], take=2)
    parts = reidentify_parts(rows, old_text, merge_by_slide(
        old_text, old, new_text, new,
        current_text="We grew fast.\n\nThen we stopped."))
    assert [(p["id"], p["text"], p["locked_at"]) for p in parts] == [
        ("a", "We grew fast.", "2026-10-05T10:00:00Z"),
        ("b", "Then we paused.", None)]


def test_served_text_that_does_not_tile_keeps_the_machine_words(caplog):
    """No proof that slot N is Paragraph N: the machine words stay, as
    before, and it is counted under one fixed name."""
    old_text, old = _doc(["A one.", "B one."], [0, 1], take=1)
    new_text, new = _doc(["B two."], [1], take=2)
    with caplog.at_level("WARNING", logger="services.take_rebuild"):
        r = merge_by_slide(old_text, old, new_text, new,
                           current_text="One free-form edit, no slots.")
    assert r.text.split("\n\n") == ["A one.", "B two."]
    assert "take_rebuild_unspoken_kept_machine_words" in caplog.text


def test_no_served_text_is_the_machine_text():
    old_text, old = _doc(["A one.", "B one."], [0, 1], take=1)
    new_text, new = _doc(["B two."], [1], take=2)
    assert (merge_by_slide(old_text, old, new_text, new).text
            == merge_by_slide(old_text, old, new_text, new,
                              current_text=old_text).text
            == "A one.\n\nB two.")
