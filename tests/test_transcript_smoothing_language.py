"""
STORY    As a Polish speaker, I want spoken fillers removed without deleting
         meaningful grammar, so that my raw transcript remains faithful.
OUTCOME
  O1  Fixed Polish hesitations are removed only when Polish is known.
  O2  Contextual discourse fillers are removed only at paused sentence starts.
  O3  Meaningful Polish constructions and conjunctions remain unchanged.
PROVES   O1 -> test_polish_fixed_fillers_are_removed_but_unknown_language_stays_safe
         O2 -> test_polish_discourse_fillers_are_removed_only_at_a_paused_sentence_start
         O3 -> test_polish_meaningful_grammar_and_conjunctions_are_preserved
WHY      Founder decision N652: Polish filler handling is meaning-preserving.
"""

from services.transcript_smoothing import count_fillers, strip_fillers, without_fillers


def test_polish_fixed_fillers_are_removed_but_unknown_language_stays_safe():
    text = "yyy eee em hm hmm zaczynamy"
    assert "zaczynamy" in strip_fillers(text, "pl")
    assert count_fillers(text, "pl") == 5
    assert "em" in strip_fillers(text, None)


def test_polish_discourse_fillers_are_removed_only_at_a_paused_sentence_start():
    text = "Jakby, zaczynam. Wiesz, przejdźmy dalej. No, kończymy."
    assert strip_fillers(text, "pl") == " zaczynam.  przejdźmy dalej.  kończymy."
    assert without_fillers(text, "pl") == "zaczynam. przejdźmy dalej. kończymy."


def test_polish_meaningful_grammar_and_conjunctions_are_preserved():
    text = "To znaczy, że jakby działa, więc idziemy."
    assert strip_fillers(text, "pl") == text
