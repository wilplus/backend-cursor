"""Resolve a speaking question against the speaker's Take index before reading text."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, replace


_WORDS = re.compile(r"[^\W_]+", re.UNICODE)
_TALK = re.compile(
    r"\b(?:takes?|recordings?|talks?|presentations?|pitch(?:es)?|speech(?:es)?|projects?|"
    r"proba|proby|probie|nagranie|nagraniu|prezentacj\w*|wystapieni\w*|projekt\w*)\b"
    r"|\b(?:my|the|this|that|moj\w*|moim|tej|tym) (?:opening|ending|closing|poczatek|poczatku|zakonczeni\w*)\b"
    r"|\b(?:at the end|na (?:samym )?koncu)\b"
)
_ACROSS_PROJECTS = re.compile(r"\b(?:across (?:all )?(?:my )?(?:projects|talks|presentations)|overall|"
                              r"all my (?:projects|talks|presentations)|ogolnie|wszystk\w* moj\w*)\b")
_LATEST = re.compile(r"\b(?:latest|last|newest|most recent|ostatni\w*|najnowsz\w*)\b")
_RECENT_PAIR = re.compile(
    r"\b(?:last|latest|most recent) (?:two|2) (?:takes?|recordings?)\b"
    r"|\bostatni(?:e|ch) (?:dwa|dwoch|2) nagrani\w*\b"
)
_FIRST = re.compile(r"\b(?:first|earliest|pierwsz\w*) (?:takes?|recordings?|prob\w*|nagrani\w*)\b")
_COMPARE = re.compile(
    r"\b(?:compare|changed|improved|clearer|better|different|versus|vs|"
    r"porown\w*|zmienil\w*|poprawil\w*|lepiej|jasniej)\b|\blast time\b"
)
_FOLLOW_UP = re.compile(r"^(?:and|what about|how about|why|what else|tell me more|a co|dlaczego)\b")
_TAKE_NUMBER = re.compile(
    r"\b(?:takes?|recordings?|prob[aye]|probie|nagrani[aeu]) (?:number |nr )?(\d{1,3})"
    r"(?: (?:and|to|with|i|vs|versus|oraz) (\d{1,3}))?\b"
)
_SLIDE_NUMBER = re.compile(r"\b(?:slide|slajd\w*) (?:number |nr )?(\d{1,3})\b")
_OPENING = re.compile(r"\b(?:opening|intro|introduction|beginning|poczat\w*|wstep\w*)\b")
_ENDING = re.compile(r"\b(?:ending|closing|conclusion|at the end|call to action|zakoncz\w*|koncow\w*|na (?:samym )?koncu)\b")


def normalize(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text.casefold().replace("ł", "l"))
    return " ".join(_WORDS.findall("".join(c for c in folded if not unicodedata.combining(c))))


@dataclass(frozen=True)
class TalkScope:
    requested: bool = False
    arc_id: str = ""
    take_numbers: tuple[int, ...] = ()
    first: bool = False
    latest: bool = False
    compare: bool = False
    recent_pair: bool = False


def requested_passage(question: str) -> tuple[int | None, str]:
    text = normalize(question)
    slide = _SLIDE_NUMBER.search(text)
    if slide and int(slide[1]) > 0:
        return int(slide[1]) - 1, ""
    if _ENDING.search(text):
        return None, "ending"
    return None, "opening" if _OPENING.search(text) else ""


def _topics(rows: list[dict]) -> dict[str, set[str]]:
    projects: dict[str, set[str]] = {}
    for row in rows:
        arc = str(row.get("arc_id") or "")
        if not arc:
            continue
        titles = projects.setdefault(arc, set())
        setup = row.get("intake_context")
        topic = setup.get("topic") if isinstance(setup, dict) else None
        if isinstance(topic, str) and (name := normalize(topic)):
            titles.add(name)
    return projects


def _named_projects(text: str, projects: dict[str, set[str]]) -> set[str]:
    padded = f" {text} "
    matches = [(arc, match.start(), match.end()) for arc, titles in projects.items()
               for title in titles
               for match in re.finditer(rf"(?<= ){re.escape(title)}(?= )", padded)]
    # A mention of "Board Update Europe" alone does not also name "Board Update".
    return {arc for arc, start, end in matches if not any(
        other_start <= start and other_end >= end and (other_start, other_end) != (start, end)
        for _, other_start, other_end in matches
    )}


def _prior_question(history: list[dict]) -> str:
    return next((row["content"] for row in reversed(history)
                 if isinstance(row, dict) and row.get("role") == "user"
                 and isinstance(row.get("content"), str) and row["content"].strip()), "")


def _request_for(arc: str, text: str) -> TalkScope:
    numbers = tuple(dict.fromkeys(int(value) for match in _TAKE_NUMBER.finditer(text)
                                  for value in match.groups() if value))
    first = bool(_FIRST.search(text))
    comparison = bool(_COMPARE.search(text)) or len(numbers) > 1
    latest = bool(_LATEST.search(text)) and (not numbers or comparison)
    compare = comparison or (first and latest)
    recent_pair = bool(_RECENT_PAIR.search(text))
    return TalkScope(True, arc, numbers[:2], first, latest, compare or recent_pair, recent_pair)


def resolve_scope(rows: list[dict], question: str, history: list[dict]) -> tuple[TalkScope, str]:
    """Use explicit names, the newest Take when requested, or a clear follow-up."""
    text = normalize(question)
    projects = _topics(rows)
    named = _named_projects(text, projects)
    prior = _prior_question(history)
    prior_text = normalize(prior)
    if len(named) == 1:
        arc = next(iter(named))
        # A title alone can answer the preceding request to identify the talk.
        query = f"{prior} {question}" if text in projects[arc] and _TALK.search(prior_text) else question
        return _request_for(arc, normalize(query)), query
    if named:
        return TalkScope(requested=True), question
    if _RECENT_PAIR.search(text):
        return _request_for("", text), question
    if _ACROSS_PROJECTS.search(text):
        return TalkScope(), question

    talk = bool(_TALK.search(text) or _SLIDE_NUMBER.search(text))
    if not talk and not _FOLLOW_UP.search(text):
        return TalkScope(), question
    if talk and _LATEST.search(text):
        latest = max(rows, key=lambda row: str(row.get("created_at") or ""), default={})
        return _request_for(str(latest.get("arc_id") or ""), text), question
    prior_names = _named_projects(prior_text, projects)
    if len(prior_names) == 1:
        arc = next(iter(prior_names))
        query = f"{prior} {question}" if _FOLLOW_UP.search(text) else question
        scope = _request_for(arc, text)
        if not (scope.take_numbers or scope.first or scope.latest):
            previous = _request_for(arc, prior_text)
            scope = replace(scope, take_numbers=previous.take_numbers, first=previous.first,
                            latest=previous.latest, compare=previous.compare, recent_pair=previous.recent_pair)
        return scope, query
    if not talk:
        return TalkScope(), question
    arc = next(iter(projects)) if len(projects) == 1 else ""
    return _request_for(arc, text), question


def select_takes(rows: list[dict], scope: TalkScope) -> list[dict]:
    """Input is newest first and owner/permission checked. No substitute for a missing Take."""
    if not rows:
        return []
    by_number: dict[int, dict] = {}
    for row in rows:
        number = row.get("take_index")
        if isinstance(number, int):
            by_number.setdefault(number, row)
    if any(number not in by_number for number in scope.take_numbers):
        return []
    chosen = [by_number[number] for number in scope.take_numbers]
    if scope.first:
        chosen.append(rows[-1])
    if scope.latest or not chosen:
        chosen.append(rows[0])
    take_ids = {row["id"] for row in chosen}
    if scope.compare and len(take_ids) == 1:
        primary = next(row for row in rows if row["id"] in take_ids)
        earlier = next((row for row in rows if row["id"] != primary["id"]
                        and str(row.get("created_at") or "") < str(primary.get("created_at") or "")), None)
        if earlier:
            take_ids.add(earlier["id"])
    return [row for row in rows if row["id"] in take_ids][:2]
