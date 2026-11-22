"""Verbatim speaking evidence, matched passages, and links to the original sources."""
from __future__ import annotations

import math
import re
import textwrap
from collections import Counter
from dataclasses import dataclass
from urllib.parse import quote, urlencode

from services.speaking_coach_scope import normalize, requested_passage


MAX_EVIDENCE_CHARS = 760
MAX_SEMANTIC_PASSAGES = 48
SOURCE_KINDS = {"progression", "coach_shared", "take_transcript", "ideal_text", "delivery_cues"}
_STOP_WORDS = set("a an the to my i me for is on in of was with about how what did can"
                  " do this that does take slide take's moj moja moim w z na czy co jak".split())
_WEIGHTS = {"progression": 2.4, "coach_shared": 2.2, "take_transcript": 2.0,
            "ideal_text": 1.8, "delivery_cues": 1.7, "project_context": 1.6, "profile": 1.4}
_PRACTICE_TAGS = {
    "ending_compression": re.compile(r"\b(?:rush\w*|compress\w*|spiesz\w*)\b.{0,30}\b(?:end\w*|clos\w*|kon\w*|zakoncz\w*)\b"),
    "rushing": re.compile(r"\b(?:rush\w*|too fast|pace|pacing|paus\w*|tempo|za szybko|pauz\w*)\b"),
    "word_compression": re.compile(r"\b(?:mumbl\w*|enunciat\w*|word separation|articulat\w*|artykul\w*|niewyrazn\w*)\b"),
}


@dataclass(frozen=True)
class Source:
    kind: str
    arc_id: str
    take_id: str
    slide: int | None = None
    take_number: int | None = None

    def url(self, base: str) -> str:
        if self.kind == "transcript":
            query = "?" + urlencode({"slide": self.slide}) if self.slide is not None else ""
            return f"{base}/chat/take/{quote(self.take_id, safe='')}{query}"
        if self.kind == "feedback":
            from services.coach_feedback_email import feedback_url
            return feedback_url(self.arc_id, self.take_id)
        return f"{base}/chat?" + urlencode({"idealArc": self.arc_id})


@dataclass(frozen=True)
class Evidence:
    source_type: str
    project: str
    recency: str
    observation_kind: str
    text: str
    sources: tuple[Source, ...] = ()
    section: str = ""
    slide: int | None = None


def excerpts(text: str) -> list[str]:
    """Keep word boundaries and the original wording, including later slides."""
    return textwrap.wrap(text, width=MAX_EVIDENCE_CHARS, expand_tabs=False,
                         replace_whitespace=False, break_on_hyphens=False)


def _transcripts(take: dict) -> dict[int, str]:
    rows = take.get("slide_transcripts") or []
    rows = [rows] if isinstance(rows, dict) else rows
    out = {}
    for position, slide in enumerate(rows):
        if not isinstance(slide, dict):
            continue
        index = slide.get("index", position)
        text = slide.get("transcript") or slide.get("text")
        if isinstance(index, int) and isinstance(text, str) and text.strip():
            out[index] = text.strip()
    return out


def _deck(take: dict) -> list:
    intake = take.get("intake_context")
    slides = intake.get("slides") if isinstance(intake, dict) else None
    return slides if isinstance(slides, list) else []


def _transcript_source(take: dict, slide: int) -> Source:
    return Source("transcript", str(take["arc_id"]), str(take["id"]), slide, take.get("take_index"))


def transcript_evidence(label: str, takes: list[dict]) -> list[Evidence]:
    out = []
    for take_position, take in enumerate(takes):
        slides = sorted(_transcripts(take).items())
        for position, (index, transcript) in enumerate(slides):
            chunks = excerpts(transcript)
            for chunk_position, chunk in enumerate(chunks):
                section = ""
                if position == 0 and chunk_position == 0:
                    section = "opening"
                if position == len(slides) - 1 and chunk_position == len(chunks) - 1:
                    section = "opening and ending" if section else "ending"
                out.append(Evidence(
                    "take_transcript", label, "recent" if take_position == 0 else "earlier",
                    "speaker_words", chunk, (_transcript_source(take, index),),
                    section, index if _deck(take) else None,
                ))
    return out


def _slide_key(slide: dict) -> tuple[str, ...]:
    if identifier := slide.get("slide_id") or slide.get("id"):
        return ("id", str(identifier))
    return tuple(normalize(str(slide.get(key) or "")) for key in ("title", "body", "text"))


def _unique_slides(deck: list) -> dict[tuple[str, ...], int]:
    keys = [_slide_key(slide) if isinstance(slide, dict) else () for slide in deck]
    counts = Counter(keys)
    return {key: index for index, key in enumerate(keys) if any(key) and counts[key] == 1}


def _matching_moments(before: dict, after: dict) -> list[tuple[int, int, str]]:
    earlier, later = sorted(_transcripts(before)), sorted(_transcripts(after))
    if not earlier or not later:
        return []
    old_deck, new_deck = _deck(before), _deck(after)
    if not old_deck and not new_deck:
        return [(earlier[0], later[0], "opening"), (earlier[-1], later[-1], "ending")]
    old_keys, new_keys = _unique_slides(old_deck), _unique_slides(new_deck)
    return [(old_index, new_index, _section_of(new_index, later))
            for key, new_index in new_keys.items()
            if (old_index := old_keys.get(key)) in earlier and new_index in later]


def _section_of(index: int, indices: list[int]) -> str:
    if index == indices[-1]:
        return "ending"
    return "opening" if index == indices[0] else ""


def comparison_evidence(label: str, takes: list[dict]) -> list[Evidence]:
    if len(takes) < 2:
        return []
    after, before = takes[0], takes[-1]
    old_text, new_text = _transcripts(before), _transcripts(after)
    out = []
    for previous, current, section in _matching_moments(before, after):
        old_chunks = textwrap.wrap(old_text[previous], width=315, break_on_hyphens=False)
        new_chunks = textwrap.wrap(new_text[current], width=315, break_on_hyphens=False)
        old = old_chunks[-1] if section == "ending" else old_chunks[0]
        new = new_chunks[-1] if section == "ending" else new_chunks[0]
        out.append(Evidence(
            "progression", label, "longitudinal", "speaker_words",
            f"earlier spoken passage: {old}\nmore recent spoken passage: {new}",
            (_transcript_source(before, previous), _transcript_source(after, current)),
            section, current if _deck(after) else None,
        ))
    return out


def _terms(text: str) -> set[str]:
    return {word for word in normalize(text).split() if len(word) > 1} - _STOP_WORDS


def _lexical(item: Evidence, terms: set[str], section: str) -> float:
    relevance = len(terms & _terms(item.text))
    recency = 0.3 if item.recency in ("recent", "current") else 0.0
    focus = 2.0 if section and section in item.section else 0.0
    return _WEIGHTS.get(item.source_type, 1.0) + relevance + recency + focus


def _cosine(a: list[float], b: list[float]) -> float:
    if len(a) != len(b):
        return 0.0
    lengths = math.sqrt(math.fsum(value * value for value in a) * math.fsum(value * value for value in b))
    if not lengths or not math.isfinite(lengths):
        return 0.0
    return math.fsum(x * y for x, y in zip(a, b)) / lengths


def rank_evidence(evidence: tuple[Evidence, ...], question: str, limit: int, *,
                  scoped: bool, user_id: str | None) -> tuple[tuple[Evidence, ...], bool]:
    slide, section = requested_passage(question)
    terms = _terms(question)
    sources = _sources_for_slide(evidence, slide)
    ranked = sorted(sources, key=lambda item: _lexical(item, terms, section), reverse=True)
    scoped_setup = [item for item in evidence if item.source_type == "project_context"] if scoped else []
    supplemental = [item for item in evidence if item.source_type not in SOURCE_KINDS and item not in scoped_setup]
    if not scoped:
        ranking = sorted(ranked + supplemental, key=lambda item: _lexical(item, terms, section), reverse=True)
        return tuple(ranking[:limit]), False
    first_by_source: dict[str, Evidence] = {}
    for item in ranked:
        first_by_source.setdefault(item.source_type, item)
    shortlisted = list(dict.fromkeys([*first_by_source.values(), *ranked]))[:MAX_SEMANTIC_PASSAGES]
    vectors = _embeddings(question, shortlisted, user_id)
    if vectors and len(vectors) == len(shortlisted) + 1:
        scored = [(item, _lexical(item, terms, section) + 7 * _cosine(vectors[0], vector))
                  for item, vector in zip(shortlisted, vectors[1:])]
        ranked = [item for item, _ in sorted(scored, key=lambda pair: pair[1], reverse=True)]
        return tuple((scoped_setup + ranked + supplemental)[:limit]), True
    return tuple((scoped_setup + ranked + supplemental)[:limit]), False


def _sources_for_slide(evidence: tuple[Evidence, ...], slide: int | None) -> list[Evidence]:
    sources = [item for item in evidence if item.source_type in SOURCE_KINDS]
    if slide is None:
        return sources
    aligned = {source for item in sources if item.source_type == "progression" and item.slide == slide
               for source in item.sources}
    return [item for item in sources
            if item.source_type not in ("take_transcript", "progression")
            or (item.source_type == "progression" and item.slide == slide)
            or (item.source_type == "take_transcript" and (
                any(source in aligned for source in item.sources) if aligned else item.slide == slide
            ))]


def _embeddings(question: str, evidence: list[Evidence], user_id: str | None) -> list[list[float]] | None:
    if len(evidence) < 2:
        return None
    from services.llm import embed
    return embed([question[:900], *(f"{item.section} {item.text}" for item in evidence)],
                 surface="speaking_coach_retrieval", user_id=user_id, timeout_seconds=2.0)


def practice_tags(text: str) -> set[str]:
    normalized = normalize(text)
    return {tag for tag, pattern in _PRACTICE_TAGS.items() if pattern.search(normalized)}
