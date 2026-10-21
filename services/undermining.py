"""Words that undermine the speaker (founder 2026-10-20, N85: the walk "spots
my negative thinking patterns"; undermining or poorly formulated words get
the clearer version, "try it and see if it gives you confidence").

Three patterns the founder named, closed English lists like the hedge
lexicon (``verbal_markers``); a word with an innocent common use ("just",
"hope", "might") is left out by construction:

  apologising or asking permission   "sorry", "if that's okay", "does that
                                     make sense"
  playing the idea down              "just a small thing", "it's not much"
  self-doubt beyond the hedges       "I'm not sure", "I might be wrong"

One is enough for the words check (``rewrite_gate.words_need_help``) to
open the practise moment on the clearer version. ``without`` is that
version as a rule writes it: the same sentence with the apologies, the
asks for permission, the self-doubt and the hedges that can simply go left
out (never a word added), tidied. A playing-down phrase that cannot just be
left out makes no rule rewrite; the gate then keeps the voice exercise.

``without_hedges`` is the same rule for a sentence that hedges and does not
undermine (founder 2026-10-21, N112: a Take whose words needed help for its
hedges had no rule to write their clearer version, so it showed none): the
sentence with its softening hedges left out. A hedge's words that are not a
hedge where they stand ("I think about it", "this kind of problem") stay.
Pure.
"""
from __future__ import annotations

import functools
import re
from typing import Optional

RULE_VERSION = "undermining-words-v2"
HEDGE_RULE_VERSION = "hedge-words-v1"

_APOLOGY_PERMISSION = (
    "sorry", "i'm sorry", "i am sorry", "so sorry", "apologies", "excuse me",
    "forgive me", "if that's okay", "if that's ok", "if that is okay",
    "if that's alright", "if you don't mind", "if i may", "does that make sense",
    "is that okay", "bear with me", "hope that's okay", "hope that makes sense",
)
_PLAYING_DOWN = (
    "just a small thing", "just a quick", "just a little", "it's not much",
    "it is not much", "not a big deal", "nothing special", "only a small thing",
    "this might be stupid", "this may sound silly", "this might sound silly",
    "i'm not an expert", "i am not an expert", "i'm no expert",
)
_SELF_DOUBT = (
    "i'm not sure", "i am not sure", "i might be wrong", "i could be wrong",
    "i may be wrong", "i'm probably wrong", "i don't know if", "i don't know whether",
)
#: Hedges that can simply go: a softener, never a verb or a measure the
#: sentence needs ("seems", "roughly" stay).
_LEAVE_OUT_HEDGES = (
    "i think", "i guess", "i suppose", "i believe", "maybe", "perhaps",
    "possibly", "probably", "sort of", "kind of", "a little bit", "to be honest",
    "in a way", "or something", "or whatever", "more or less",
)
#: Where a hedge's words go on into a meaning of their own, they stay: "I
#: think about it", "I believe in us", "a little bit of time", "or something
#: else" (N112).
_GOES_ON = {
    "i think": "about|of|through|over|back|ahead|twice|so|not",
    "i believe": "in|so|you|him|her|them|me|us",
    "i guess": "so", "i suppose": "so", "a little bit": "of",
    "or something": "else|like", "or whatever": "else|like|you",
}
#: "in a way" goes only when set off ("In a way, ...", "..., in a way."):
#: "built in a way that scales" needs it.
_SET_OFF_ONLY = ("in a way",)
#: "kind of" and "sort of" after one of these are a noun: "this kind of
#: problem", "what sort of team".
_NOUN_AFTER = frozenset("""
a an the this that these those what which any some every each no one another
other same different new right wrong first my our your their his her its
""".split())
#: "I think that we ..." loses its "that" with the hedge; "I think that is
#: right" keeps it, as the subject.
_THAT_CLAUSE = (r"(?:\s+that(?=\s+(?:i|we|you|they|he|she|it|the|a|an|our|my|"
                r"your|their|his|her|this|these|those|there|people|everyone|"
                r"everybody|nobody|no|all|most|some|many)\b))?")
PHRASES = _APOLOGY_PERMISSION + _PLAYING_DOWN + _SELF_DOUBT
_LEAVE_OUT = _APOLOGY_PERMISSION + _SELF_DOUBT
_MIN_WORDS = 5
_WORD = re.compile(r"[^\W_]+(?:['’-][^\W_]+)*", re.UNICODE)


def _norm(text: str) -> str:
    return " ".join(str(text or "").replace("’", "'").lower().split())


def _pattern(phrase: str) -> re.Pattern:
    words = [re.escape(w).replace("'", "['’]") for w in phrase.split()]
    return re.compile(r"(?<![\w'’])" + r"\s+".join(words) + r"(?![\w'’])", re.IGNORECASE)


def _hedge_pattern(phrase: str) -> re.Pattern:
    """The hedge with a comma beside it, unless its words go on into a
    meaning of their own."""
    body = r"\s+".join(re.escape(w).replace("'", "['’]") for w in phrase.split())
    if phrase.startswith("i "):
        body += _THAT_CLAUSE
    tail = r"(?![\w'’])"
    if phrase in _GOES_ON:
        tail += rf"(?!\s+(?:{_GOES_ON[phrase]})\b)"
    if phrase in _SET_OFF_ONLY:
        tail += r"(?=\s*(?:[,.;:!?]|$))"
    return re.compile(rf"(?P<lead>,\s*)?(?<![\w'’]){body}{tail}(?P<trail>\s*,)?",
                      re.IGNORECASE)


_FOUND = [(p, _pattern(p)) for p in sorted(PHRASES, key=len, reverse=True)]
_GONE = [_pattern(p) for p in sorted(_LEAVE_OUT, key=len, reverse=True)]
_HEDGES = [(p, _hedge_pattern(p)) for p in sorted(_LEAVE_OUT_HEDGES, key=len, reverse=True)]


def found(text: str) -> list[str]:
    """The undermining phrases this text says, longest first, each once."""
    said = _norm(text)
    hits: list[str] = []
    for phrase, pattern in _FOUND:
        if pattern.search(said) and not any(phrase in longer for longer in hits):
            hits.append(phrase)
    return hits


def count(text: str) -> int:
    """How many times this text undermines the speaker."""
    said = _norm(text)
    return sum(len(pattern.findall(said)) for _, pattern in _FOUND)


def _tidy(text: str) -> str:
    out = re.sub(r"\s+", " ", text)
    out = re.sub(r"\s+([,.;:!?])", r"\1", out)
    out = re.sub(r",(\s*[,.;:!?])", r"\1", out)
    out = re.sub(r"^[\s,;:.?!]+", "", out)
    out = re.sub(r"^(?:but|and|so)\b[\s,]*", "", out, flags=re.IGNORECASE)
    return out.strip()


def without(sentence: str) -> Optional[str]:
    """The sentence said with conviction: its apologies, asks for
    permission, self-doubt and softening hedges left out, nothing added;
    None when it does not undermine, when a playing-down phrase would have
    to be rewritten rather than left out, or when too little is left."""
    if not found(sentence):
        return None
    out = sentence
    for pattern in _GONE:
        out = pattern.sub(" ", out)
    out = _tidy(_hedges_out(out))
    if not out or any(p in _norm(out) for p in _PLAYING_DOWN):
        return None
    return _finished(sentence, out)


def without_hedges(sentence: str) -> Optional[str]:
    """The sentence with its softening hedges left out, nothing added
    (N112); None when it undermines the speaker (``without`` writes that
    one), says no hedge that can simply go, or too little is left."""
    if found(sentence):
        return None
    left = _hedges_out(sentence)
    out = _tidy(left) if left != sentence else ""
    return _finished(sentence, out) if out else None


def _hedges_out(text: str) -> str:
    for phrase, pattern in _HEDGES:
        text = pattern.sub(functools.partial(_drop, phrase), text)
    return text


def _drop(phrase: str, match: re.Match) -> str:
    """A hedge left out with its commas, unless it is a noun where it
    stands; the comma before it stays when it opened a clause of its own
    ("First, maybe we ..." -> "First, we ...")."""
    before = match.string[:match.start()].split()
    if (phrase in ("kind of", "sort of") and not match.group("lead") and before
            and before[-1].lower() in _NOUN_AFTER):
        return match.group(0)
    closes = re.match(r"\s*(?:[.!?;:]|$)", match.string[match.end():])
    lead = match.group("lead")
    return (lead if lead and not (match.group("trail") or closes) else "") + " "


def _finished(sentence: str, out: str) -> Optional[str]:
    out = out[0].upper() + out[1:]
    end = sentence.rstrip()[-1:] if sentence.rstrip()[-1:] in ".!?" else "."
    out = out.rstrip(",;: ") if out[-1] not in ".!?" else out
    if out[-1] not in ".!?":
        out += end
    if len(_WORD.findall(out)) < _MIN_WORDS or out == sentence.strip():
        return None
    return out
