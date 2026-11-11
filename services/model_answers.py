"""A model's answers come from its question (N646 items 1 and 2).

A question that names the things to tell apart gives those things as its
answers: "Is the wood cracked or broken?" gives "Cracked", "Broken" and
"Not sure"; "Is this a quote, a paraphrase or neither?" gives "Quote",
"Paraphrase", "Neither". A question that is itself yes or no gives "Yes",
"No", "Not sure". Never more than three, the unsure one included.

Rules only, no provider call: the setup's suggestions (one call,
``chat_suggestions.suggest``) are asked for the same and then put through
``fix``, so a reply that still says yes or no to a question naming two
things is corrected.
"""
from __future__ import annotations

import re
from typing import Any

#: At most three answers, the unsure one included (N646 item 2).
MOST = 3
#: Each answer as a card holds it (``chat_recipes._model``).
LONGEST = 22
UNSURE = "Not sure"
YES_NO = ["Yes", "No", UNSURE]
_ARTICLES = {"a", "an", "the", "some", "any"}
_PLAIN = {"not", "no", "yes", "otherwise", "something else"}


def _words(text: str) -> list[str]:
    return [w for w in re.split(r"\s+", text.strip()) if w]


def _option(text: str, words: int) -> str:
    """The last ``words`` words of a piece, without an article, capitalised."""
    found = [w.strip(" ,.;:!?\"'()") for w in _words(text)]
    found = [w for w in found if w]
    picked = found[-words:] if words else found
    while picked and picked[0].lower() in _ARTICLES:
        picked = picked[1:]
    said = " ".join(picked)
    return said[:1].upper() + said[1:] if said else ""


def named(question: Any) -> list[str]:
    """The things a question names to tell apart, in its order; [] for a
    question that names none (it is yes or no)."""
    text = " ".join(str(question or "").split()).rstrip(" ?.!")
    if " or " not in text.lower():
        return []
    head, _, last = _split_last(text)
    last_words = [w for w in _words(last) if w.lower() not in _ARTICLES]
    if not last_words or last.strip().lower() in _PLAIN:
        return []
    pieces = re.split(r",|\s+or\s+", head, flags=re.I)
    # The first piece holds the question's own words before the first thing
    # ("Is the wood cracked"): as many of its last words as the last thing has.
    return ([_option(pieces[0], len(last_words))] + [_option(p, 0) for p in pieces[1:] if p.strip()]
            + [_option(last, 0)])


def _split_last(text: str) -> tuple[str, str, str]:
    """``text`` split at its last " or "."""
    match = None
    for match in re.finditer(r"\s+or\s+", text, re.I):
        pass
    if match is None:
        return text, "", ""
    return text[:match.start()], match.group(0), text[match.end():]


def answers_for(question: Any) -> list[str]:
    """The answers a model with this question starts with: what it names,
    then "Not sure" while there is room; else "Yes", "No", "Not sure"."""
    things = named(question)
    seen = {t.lower() for t in things}
    if len(things) < 2 or len(seen) != len(things) or any(not t or len(t) > LONGEST for t in things):
        return list(YES_NO)
    if len(things) >= MOST:
        return things[:MOST]
    return [*things, UNSURE]


def fix(question: Any, answers: Any) -> list[str]:
    """Suggested answers kept, unless the question names the things to tell
    apart: then those (N646 item 1)."""
    if named(question) and answers_for(question) != YES_NO:
        return answers_for(question)
    given = [str(a) for a in answers or [] if str(a).strip()] if isinstance(answers, list) else []
    return given[:MOST] if len(given) >= 2 else list(YES_NO)
