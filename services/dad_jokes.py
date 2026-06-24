"""Founder-supplied dad jokes for the Lounge bot (BE-owned; NOT in the FE repo).

Returned on request (a joke on request is on-mission — founder re-lock) or when
the user accepts the pre-recording "want a bad joke?" offer (FE F7). Verbatim
set, rotated so two consecutive asks never return the same one.

House rule: no em-dashes in copy — the founder's WORDS are verbatim; the
setup/punchline separator is a sentence break, not an em-dash.
"""
from __future__ import annotations

import threading

DAD_JOKES = [
    "How do cows stay up to date? They read the moos-paper. 🐄",
    "What do you call a bear with no teeth? A gummy bear. 🐻",
    "Did you hear about the accident at the shoe factory? Many soles were lost. 👞",
    "Who won the neck decorating contest? It was a tie. 👔",
    "Why did the bicycle fall over? Because it was two-tired. 🚲",
    "What do you call a dog magician? A Labracadabrador Retriever. 🐕",
    "Well-dressed man on a unicycle vs poorly-dressed man on a bicycle? Attire. 🎩",
    "Difference between Batman and a shoplifter? Batman can go into a store "
    "without Robin. 🦇",
    "Difference between a greedy person and a crayfish? One is selfish, the "
    "other is shellfish. 🦞",
    "Italian barber vs angry circus ringmaster? One's a shaving Roman, the "
    "other's a raving showman. 🎪",
]

_lock = threading.Lock()
_last = -1


def next_dad_joke() -> str:
    """Return a joke, rotating so the same one never comes back-to-back —
    cycles through all of DAD_JOKES before repeating. Thread-safe."""
    global _last
    with _lock:
        _last = (_last + 1) % len(DAD_JOKES)
        return DAD_JOKES[_last]
