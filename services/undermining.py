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

Two more undermine the speaker (founder 2026-10-23, N124, "Let's do 1-4"),
each found by where it stands, since the words alone are innocent:

  an ask for approval              ", okay?", ", right?", ", you know?",
                                   ", yeah?" ending a sentence; it goes and
                                   the sentence ends on a full stop
  a playing-down "just"            "is just a job", "if you could just",
                                   "I just wanted to"; a "just" of time or
                                   measure ("just now", "just in time",
                                   "just before", "just as") stays
Pure.
"""
from __future__ import annotations

import functools
import re
from typing import Optional

RULE_VERSION = "undermining-words-v3"
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

#: An ask for approval ending a sentence (N124).
_APPROVAL_TAG = re.compile(r",\s*(?:okay|ok|right|you know|yeah)\s*\?+(?=\s|$)",
                           re.IGNORECASE)
_JUST = re.compile(r"(?<![\w'’])just(?![\w'’])(?P<comma>,)?", re.IGNORECASE)
#: A "just" before one of these is one of time or measure, or opens a
#: meaning of its own ("just the beginning"): it stays.
_JUST_STAYS = frozenset("""
now then in before after as about like so because enough right that when
while once the
""".split())
#: "if you could just", "can you just": an ask played down.
_ASKS = frozenset("could can would will should".split())
#: "I just wanted to", "we just need": the speaker's own wish played down.
_WANTING = frozenset("""
want wanted wanna need needed wonder wondered wondering think thought hope
hoped hoping try tried trying mean meant feel felt
""".split())
#: After "is", "I'm" ...: these "-ing" words are played down ("I'm just
#: trying to"); any other ("was just leaving") is time and stays.
_PLAYED_DOWN_ING = frozenset("trying wondering saying asking hoping checking thinking".split())
_BE = frozenset("is are was were am be".split())


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
    """The undermining phrases this text says, longest first, each once;
    then an ask for approval and a playing-down "just" (N124)."""
    said = _norm(text)
    hits: list[str] = []
    for phrase, pattern in _FOUND:
        if pattern.search(said) and not any(phrase in longer for longer in hits):
            hits.append(phrase)
    raw = str(text or "")
    if _APPROVAL_TAG.search(raw):
        hits.append("approval tag")
    if _just_spans(raw):
        hits.append("just")
    return hits


def count(text: str) -> int:
    """How many times this text undermines the speaker."""
    said = _norm(text)
    raw = str(text or "")
    return (sum(len(pattern.findall(said)) for _, pattern in _FOUND)
            + len(_APPROVAL_TAG.findall(raw)) + len(_just_spans(raw)))


def _just_spans(text: str) -> list[tuple[int, int]]:
    """Where a playing-down "just" stands, each span with the space before
    it (and its comma after an ask: "could just, help"), to leave out."""
    spans: list[tuple[int, int]] = []
    for match in _JUST.finditer(text):
        base = max(0, match.start() - 80)
        lead = re.search(r"([\w'’]+)\s+$", text[base:match.start()])
        after = re.match(r"\s+([\w'’-]+)", text[match.end():])
        if not lead or not after:
            continue
        head = text[base:base + lead.end()]
        before = [w.lower().replace("’", "'") for w in _WORD.findall(head)[-2:]]
        prev, nxt = before[-1], after.group(1).lower()
        if nxt in _JUST_STAYS:
            continue
        ask = prev in _ASKS or (prev in ("you", "we", "i") and len(before) > 1
                                and before[-2] in _ASKS)
        wanting = prev in ("i", "we") and nxt in _WANTING
        be = prev in _BE or prev.endswith(("'s", "'m", "'re"))
        if match.group("comma") and not ask:
            continue
        if ask or wanting or (be and _played_down_after_be(nxt)):
            spans.append((base + lead.end(1), match.end()))
    return spans


def _played_down_after_be(nxt: str) -> bool:
    if nxt.endswith("ing"):
        return nxt in _PLAYED_DOWN_ING
    return not nxt.endswith("ed")


def _without_just(text: str) -> str:
    for start, end in reversed(_just_spans(text)):
        text = text[:start] + text[end:]
    return text


def _tidy(text: str) -> str:
    out = re.sub(r"\s+", " ", text)
    out = re.sub(r"\s+([,.;:!?])", r"\1", out)
    out = re.sub(r",(\s*[,.;:!?])", r"\1", out)
    out = re.sub(r"^[\s,;:.?!]+", "", out)
    out = re.sub(r"^(?:but|and|so)\b(?!\s+(?:that|far)\b)[\s,]*", "", out,
                 flags=re.IGNORECASE)
    return out.strip()


def without(sentence: str) -> Optional[str]:
    """The sentence said with conviction: its apologies, asks for
    permission or approval, self-doubt, playing-down "just" and softening
    hedges left out, nothing added; None when it does not undermine, when a
    playing-down phrase would have to be rewritten rather than left out, or
    when too little is left."""
    if not found(sentence) or any(p in _norm(sentence) for p in _PLAYING_DOWN):
        return None
    out = _APPROVAL_TAG.sub(".", sentence)
    for pattern in _GONE:
        out = pattern.sub(" ", out)
    out = _tidy(_hedges_out(_without_just(out)))
    if not out:
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
