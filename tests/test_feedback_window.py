"""
STORY    As a speaker, I want my page to show only the moments that matter, so
         that it stays focused.
OUTCOME
  O1  Confident moments, the exercise and items I already answered are shown;
      other open moments are not; a paragraph I saved in this Take shows
      nothing new, except a moment picked for me there, which stays until I
      walk it; and no score fields reach the page.
  O2  A Take with nothing picked still shows two moments; one whose picked
      moments I answered shows no others in their place.
  O3  A paragraph I saved in an earlier Take gets its moments again in later
      Takes.
PROVES   O1 -> test_green_moments_and_the_exercise_show_nothing_else_open_does
         O2 -> test_a_take_with_nothing_picked_still_shows_two_moments,
               test_answered_moments_leave_no_place_for_others
         O3 -> test_a_paragraph_saved_in_an_earlier_take_gets_its_moments_again
         O1 -> test_the_second_best_moment_stays_after_helper_words_on_its_paragraph
WHY      Founder lock 2026-10-12; project "S" 2026-10-13; Never-rule 1;
         2026-10-28 (N246 item 5, "Second stays").
"""
from services.feedback_window import window_rows


def _m(id_, para, tier="standard", *, practise=False, status=None):
    return {"id": id_, "source": "confident_voice",
            "feedback_family": "confident_voice",
            "span": {"start": para * 100}, "bookmark_tier": tier,
            "practice_prompt": practise, "status": status}


def _para(row):
    return row["span"]["start"] // 100


def test_green_moments_and_the_exercise_show_nothing_else_open_does():
    rows = [_m("g1", 0, "confident"), _m("plain", 1), _m("g2", 2, "confident"),
            _m("ex", 3, practise=True), _m("done", 4, status="approved"),
            _m("other", 5)]
    out = window_rows(rows, paragraph_of=_para, saved_paragraphs={5})
    assert [r["id"] for r in out] == ["g1", "g2", "ex", "done"]
    assert all("candidate_score" not in r and "delivery_band" not in r for r in out)


def test_a_take_with_nothing_picked_still_shows_two_moments():
    rows = [_m("a", 0), _m("b", 1), _m("c", 2)]
    out = window_rows(rows, paragraph_of=_para, saved_paragraphs=set())
    assert [r["id"] for r in out] == ["a", "b"]


def test_answered_moments_leave_no_place_for_others():
    """Founder 2026-10-21: walked through, the black lines stayed. Answered,
    the picked moments stand; the other moments stay unshown, also on a
    paragraph saved in this Take."""
    rows = [_m("g1", 0, "confident", status="dismissed"), _m("plain", 1),
            _m("ex", 2, practise=True, status="approved"), _m("other", 3),
            _m("g2", 4, "confident", status="approved"), _m("after", 4)]
    out = window_rows(rows, paragraph_of=_para, saved_paragraphs={4})
    assert [r["id"] for r in out] == ["g1", "ex", "g2"]


def test_a_paragraph_saved_in_an_earlier_take_gets_its_moments_again():
    """Founder 2026-10-13, project "S": helper words saved in Take 1 must not
    withhold every moment on that paragraph in Take 2 and after."""
    from services.ideal_text_changes import saved_paragraphs
    take_2_started = "2026-10-13T19:01:22.244848"
    parts = [
        # Saved in Take 1 (words on the paragraph, locked before Take 2).
        {"id": "p0", "locked_at": "2026-10-13T18:31:59+00:00",
         "root_phrase": "I think you should"},
        # Saved in Take 1 on its Slide only (the caller passes no Take-1 rows).
        {"id": "p1", "locked_at": "2026-10-10T09:18:21+00:00"},
        # Saved during Take 2's own review.
        {"id": "p2", "locked_at": "2026-10-13T19:05:00+00:00",
         "root_phrase": "You can actually use"},
        # Saved on its Slide during Take 2's review.
        {"id": "P3", "locked_at": "2026-10-13T19:06:00+00:00"},
    ]
    saved = saved_paragraphs(parts, {"p3"}, take_2_started)
    assert saved == {2, 3}
    rows = [_m("a", 0, "confident"), _m("b", 1, "confident"),
            _m("c", 2, "confident", status="approved"), _m("d", 2)]
    out = window_rows(rows, paragraph_of=_para, saved_paragraphs=saved)
    assert [r["id"] for r in out] == ["a", "b", "c"]


def test_the_second_best_moment_stays_after_helper_words_on_its_paragraph():
    """Founder 2026-10-28 (N246 item 5): both best moments on one slide's
    paragraph; the helper words saved at the first took the second, and its
    clearer version, off the walk."""
    note = {"id": "note", "feedback_family": "rewrite_clarity",
            "span": {"start": 150}, "status": None}
    rows = [_m("first", 1, "confident", status="approved"),
            _m("second", 1, practise=True), note, _m("plain", 1)]
    out = window_rows(rows, paragraph_of=_para, saved_paragraphs={1})
    assert [r["id"] for r in out] == ["first", "second", "note"]
    # Once it is answered, the paragraph is done: its other notes leave.
    rows[1] = _m("second", 1, practise=True, status="dismissed")
    out = window_rows(rows, paragraph_of=_para, saved_paragraphs={1})
    assert [r["id"] for r in out] == ["first", "second"]
