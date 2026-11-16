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
