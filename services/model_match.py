"""Matching a person to a model: "For you" on the models page (founder,
5 November 2026, N518 items 7 and 8; N520 item 7), the second matching
beside the matching of a person to a Take (``services/take_match.py``).

A person's profile words (their job, their About) are scored against each
model's own words, its specification, by the same knowledge score the
matching of a Take uses (``take_match_knowledge.score``: shared words, rare
words weighing most, a long text counting a little less per word), with
the same threshold, ``take_match.MIN_FIT`` (2.0), until the founder sets
one of its own (N518 item 10).

  * ``for_you``  the models "For you" shows: those whose words match the
                 person's profile at ``MIN_FIT`` or more, best first, and
                 the ones they teach, whatever their score.
  * ``feeds``    the one model a person's answer feeds as a data pair
                 (N518 item 7): the highest at or over ``MIN_FIT``, or None,
                 and then the answer stays their own Take.

Pure: the caller gives the profile and the models ({"id", "words"}); the
models' catalogue is the launchpad's. Never a score on screen (Never 1):
only which models, in which order.
"""
from __future__ import annotations

from typing import Any, Iterable, Optional

from services import take_match_knowledge as knowledge


def _scores(profile: str, models: list[dict]) -> list[tuple[float, str]]:
    """Each model's fit to the profile: the profile's words are what the
    person knows, each model's words what it needs."""
    knows = knowledge.counts(profile)
    if not knows or not models:
        return []
    needs = {str(m["id"]): set(knowledge.counts(m.get("words") or "")) for m in models}
    weight, _n = knowledge.weights(needs.values())
    out = []
    for model_id, wanted in needs.items():
        fit, _terms = knowledge.score(wanted, knows, knowledge.counts(""), set(), weight,
                                      float(sum(knows.values())), 1.0)
        out.append((fit, model_id))
    return sorted(out, key=lambda x: (-x[0], x[1]))


def for_you(profile: Any, models: list[dict], teaches: Iterable[str] = ()) -> list[str]:
    """The ids of the models "For you" shows: the ones they teach first, then
    those at ``MIN_FIT`` or more, best first."""
    from services.take_match import MIN_FIT
    taught = [str(t) for t in teaches]
    fitting = [m for fit, m in _scores(str(profile or ""), models) if fit >= MIN_FIT]
    return taught + [m for m in fitting if m not in taught]


def feeds(profile: Any, models: list[dict]) -> Optional[str]:
    """The model a person's answer feeds, or None below ``MIN_FIT``."""
    from services.take_match import MIN_FIT
    scored = _scores(str(profile or ""), models)
    return scored[0][1] if scored and scored[0][0] >= MIN_FIT else None
