"""What someone knows of what a Take needs, for the matching after a Take
(N477, N481 item 2), as a number the founder can follow: shared words, each
weighed by how rare it is among the people who could be suggested.

A word every profile has ("presentation", "speak", "confidence" in a
speaking app; "dla" or "und" in another language) says little about who
knows this Take's subject, so it weighs nearly nothing; a word only one
person has weighs 1 (an inverse document frequency, normalised). A long
profile counts a little less per word (the length normalisation of BM25),
so listing many words does not buy matches. Function words of Polish and
German join the English ones, since the shared word lists know English only.

    knowledge = Σ w(t) over the Take's words they know       ÷ L(know)
              + ½ Σ w(t) over the Take's words they practise ÷ L(practise)
              + ½ Σ w(t) over what you know that they practise

    rare(t) = ln((N + 1) / (n_t + 0.5)) ÷ ln((N + 1) / 1.5), between 0 and 1
    w(t)    = 1 − min(1, N ÷ N0) × (1 − rare(t))
    L(d)    = 1 − B + B × |d| ÷ average |d|

N is how many people share a community with the speaker, n_t how many of
them have the word. How rare a word is can only be told among enough people:
with few, every shared word counts nearly 1; from ``N0`` people on, fully by
its rarity.
Reads nothing and writes nothing: pure functions of the texts given.
"""
from __future__ import annotations

import math
from collections import Counter
from typing import Any, Iterable

from services.speaker_lookup import _STOPWORDS, _WORD, _stem

#: How many of a Take's words are looked for (as ``speaker_lookup``).
TAKE_WORDS = 24
#: How much a long profile counts less per word (BM25's b; 0 is none).
B = 0.5
#: From how many people a word's rarity is trusted fully.
N0 = 20
#: Function words of the two other languages speakers here use, so a
#: Polish or German Take is not matched on "dla" or "und" (audit, 4 November
#: 2026). Lowercase, as the words are read.
OTHER_STOPWORDS = frozenset("""
a aby ale ani bo by być był była było będzie co czy dla do gdy go i ich jak
jaki jakie jako je jego jej jest jestem już każdy kiedy kto która które
który którzy lub ma mam mi mnie mną mój moja moje mu na nad nam nas nasz
nasza nasze nie nim niż o od oraz po pod przez przy się sobie są ta tak
także te tego tej ten też to tu tym u w we więc wszystko z za ze że żeby
aber als am an auch auf aus bei bin bis da das dass dem den der des die
dies doch du ein eine einem einen einer eines er es für hat ich ihr im in
ist ja kein mit nach nicht noch nur oder sich sie sind so über um und uns
vom von vor war wenn wie wir wird zu zum zur
""".split())


def counts(text: Any) -> Counter:
    """The text's content words, lowercased and stemmed, with how often each
    comes; the stopwords of every language here out. Pure."""
    words = (w.replace("'", "") for w in _WORD.findall(str(text or "").lower()))
    return Counter(_stem(w) for w in words
                   if len(w) > 1 and w not in _STOPWORDS and w not in OTHER_STOPWORDS)


def take_words(topic: str, said: str) -> set[str]:
    """The Take's most used words, its topic written in three times so its
    words always count. Pure."""
    return {w for w, _n in counts(f"{topic} {topic} {topic} {said}").most_common(TAKE_WORDS)}


def weights(docs: Iterable[set[str]]) -> tuple[dict[str, float], int]:
    """Each word's weight among ``docs`` (one set of words per person), and
    how many people there are. Pure."""
    docs = list(docs)
    n = len(docs)
    have: Counter = Counter(w for d in docs for w in d)
    top = math.log((n + 1) / 1.5) if n else 0.0
    trust = min(1.0, n / N0)

    def weight(k: int) -> float:
        rare = max(0.0, min(1.0, math.log((n + 1) / (k + 0.5)) / top)) if top > 0 else 1.0
        return 1.0 - trust * (1.0 - rare)
    return {w: round(weight(k), 4) for w, k in have.items()}, n


def _length(size: int, average: float) -> float:
    return 1 - B + B * (size / average) if average > 0 else 1.0


def score(wanted: set[str], knows: Counter, practises: Counter, speaker_knows: set[str],
          weight: dict[str, float], average_know: float, average_practise: float
          ) -> tuple[float, list[str]]:
    """One person's knowledge of this Take, and the words that made it. A
    word nobody else has weighs 1. Pure."""
    def w(words: set[str]) -> float:
        return sum(weight.get(t, 1.0) for t in words)
    know = wanted & set(knows)
    practise = wanted & set(practises)
    back = speaker_knows & set(practises)
    total = (w(know) / _length(sum(knows.values()), average_know)
             + 0.5 * w(practise) / _length(sum(practises.values()), average_practise)
             + 0.5 * w(back))
    return round(total, 4), sorted(know | practise | back)
