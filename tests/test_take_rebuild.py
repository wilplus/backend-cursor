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
