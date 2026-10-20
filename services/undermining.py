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
Pure.
"""
from __future__ import annotations

import re
from typing import Optional

RULE_VERSION = "undermining-words-v1"

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
PHRASES = _APOLOGY_PERMISSION + _PLAYING_DOWN + _SELF_DOUBT
_LEAVE_OUT = _APOLOGY_PERMISSION + _SELF_DOUBT + _LEAVE_OUT_HEDGES
_MIN_WORDS = 5
_WORD = re.compile(r"[^\W_]+(?:['’-][^\W_]+)*", re.UNICODE)


def _norm(text: str) -> str:
    return " ".join(str(text or "").replace("’", "'").lower().split())


def _pattern(phrase: str) -> re.Pattern:
    words = [re.escape(w).replace("'", "['’]") for w in phrase.split()]
    return re.compile(r"(?<![\w'’])" + r"\s+".join(words) + r"(?![\w'’])", re.IGNORECASE)


_FOUND = [(p, _pattern(p)) for p in sorted(PHRASES, key=len, reverse=True)]
_GONE = [_pattern(p) for p in sorted(_LEAVE_OUT, key=len, reverse=True)]


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
    out = _tidy(out)
    if not out or any(p in _norm(out) for p in _PLAYING_DOWN):
        return None
    out = out[0].upper() + out[1:]
    end = sentence.rstrip()[-1:] if sentence.rstrip()[-1:] in ".!?" else "."
    out = out.rstrip(",;: ") if out[-1] not in ".!?" else out
    if out[-1] not in ".!?":
        out += end
    if len(_WORD.findall(out)) < _MIN_WORDS or out == sentence.strip():
        return None
    return out
