"""
STORY    As a speaker, I want the walk to know who my talk is for and what I
         want them to do, from what I already told Will or my plan, so that
         the moment it praises and the one it fixes are the ones my talk
         needs, and nothing changes when it knows nothing.
OUTCOME
  O1  What I told Will (the talk's setup) comes first, then my plan's
      answers, then a guess read from my Take; a guess never replaces
      something I said.
  O2  A sentence that carries my key line or my call to action counts in
      full when I said it, at half weight when it was only a guess, and not
      at all when nothing is known.
  O3  The walk picks that sentence as my strongest when it is close to the
      top, and its fix lands there first; with no context the pick is as
      before.
PROVES   O1 -> test_what_i_said_comes_before_the_plan_and_a_guess
         O2 -> test_my_key_line_counts_in_full_and_a_guess_at_half
         O3 -> test_the_strongest_and_the_fix_follow_what_my_talk_needs
WHY      Founder 2026-10-31 (N293: "ok, it is good", "ok, build it"; N290:
         "spot the correct moments that yield the most for the user
         confidence and serve the intervention that is the most relevant").
"""
from services.moment_pick import pick
from services.take_context import assemble, relevance


def test_what_i_said_comes_before_the_plan_and_a_guess():
    setup = {"audience": "The board", "heard": {"audience": "investors", "ask": "fund us"},
             "strategic_context": "Desired call to action: approve the budget"}
    facts = {"audience": "Investors", "success": "A second meeting", "key_line": "We pay back in a year"}
    ctx = assemble(setup, facts)
    assert (ctx["who"]["value"], ctx["who"]["state"], ctx["who"]["source"]) == ("The board", "sure", "setup")
    assert (ctx["success"]["value"], ctx["success"]["source"]) == ("approve the budget", "setup")
    assert ctx["key_line"]["state"] == "sure"
    # Without what I said: the plan's answers, then the guess.
    ctx = assemble({"heard": setup["heard"]}, facts)
    assert (ctx["who"]["value"], ctx["who"]["source"]) == ("Investors", "plan")
    ctx = assemble({"heard": setup["heard"]}, {})
    assert (ctx["who"]["value"], ctx["who"]["state"]) == ("investors", "guess")
    assert (ctx["success"]["value"], ctx["success"]["state"]) == ("fund us", "guess")
    # Nothing at all: every slot missing.
    assert {k: v["state"] for k, v in assemble(None, None).items()} == {
        "who": "missing", "what": "missing", "success": "missing", "key_line": "missing"}


def test_my_key_line_counts_in_full_and_a_guess_at_half():
    said = assemble({}, {"key_line": "We pay back every euro within a year"})
    assert relevance("And we pay back every euro within a year, guaranteed.", said) == 1.0
    assert relevance("Our team is small but sharp.", said) == 0.0
    guessed = assemble({"heard": {"ask": "sign the pilot this quarter"}}, {})
    assert relevance("So please sign the pilot this quarter.", guessed) == 0.5
    assert relevance("So please sign the pilot this quarter.", None) == 0.0


def _row(block, s, *, w=1.0, words=12, rel=0.0, help=None):
    return {"block_id": block, "slide_index": 0, "word_count": words, "candidate_id": f"{block}-clip",
            "read": {"s": s, "w": w, "value": s * w, "sound": True, "words_help": help, "relevance": rel}}


def test_the_strongest_and_the_fix_follow_what_my_talk_needs():
    plain = [_row("a", 0.80), _row("key", 0.75), _row("c", 0.40), _row("d", 0.42)]
    assert pick(plain)["shown"][0]["block_id"] == "a"
    # The key line, close to the top, is the strongest when I said it.
    lifted = [_row("a", 0.80), _row("key", 0.75, rel=1.0), _row("c", 0.40), _row("d", 0.42)]
    assert pick(lifted)["shown"][0]["block_id"] == "key"
    # A key line far below stays where its voice and words put it.
    low = [_row("a", 0.80), _row("key", 0.30, rel=1.0), _row("c", 0.70)]
    assert pick(low)["shown"][0]["block_id"] == "a"
    # Two near-equal sentences to fix: the one carrying my call to action.
    fix = [_row("a", 0.90), _row("ask", 0.42, rel=1.0), _row("other", 0.40)]
    assert [m["block_id"] for m in pick(fix)["shown"] if m["slot"] == "weakest"] == ["ask"]
    assert [m["block_id"] for m in pick([_row("a", 0.90), _row("ask", 0.42), _row("other", 0.40)])["shown"]
            if m["slot"] == "weakest"] == ["other"]
