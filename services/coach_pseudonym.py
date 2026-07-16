"""Deterministic coach-facing pseudonym for a user_id.

REPLICA of ``routes/v2_routes.py::_coach_pseudonym`` (§B.4 — friendly,
stable, non-reversible handle: salted-hash pick of adjective + animal).
It lives here so SERVICES (e.g. the coach homework-complete email
subject) can pseudonymize without importing the routes module — that
would be a circular import (routes import services, never the reverse).

The logic, salt and wordlists MUST stay byte-identical to the routes
copy: the coach recognises a returning student because the SAME handle
shows up in the review queue, the overlay AND the mailbox thread.
``test_email_threading.py::PseudonymParityTests`` pins the two
implementations against each other in CI (it imports the routes module,
so it skips locally without Flask). If you change one copy, change both.

No stored map, never reversible to identity. Wordlists sized for beta;
expand per §B.4 (≈10x user count) at scale — in BOTH copies at once.
"""
from __future__ import annotations

import hashlib

_COACH_PSEUDONYM_SALT = "willab-coach-pseudonym-v1"

_COACH_PSEUDONYM_ADJ = (
    "Playful", "Quiet", "Bright", "Curious", "Bold", "Gentle", "Swift",
    "Calm", "Clever", "Brave", "Sunny", "Steady", "Witty", "Warm", "Keen",
    "Nimble", "Mellow", "Lively", "Patient", "Earnest", "Cheery", "Frank",
    "Spry", "Wry",
)
_COACH_PSEUDONYM_ANIMAL = (
    "Octopus", "Otter", "Falcon", "Badger", "Heron", "Lynx", "Marten",
    "Sparrow", "Dolphin", "Ibex", "Magpie", "Beaver", "Finch", "Hare",
    "Stork", "Vole", "Wren", "Crane", "Mole", "Newt", "Quail", "Robin",
    "Seal", "Tern",
)


def coach_pseudonym(user_id) -> str:
    """Stable friendly handle for a user_id (e.g. "Playful Octopus"). Never
    reversible to identity; no stored map. Empty user_id → 'Anonymous'."""
    if not user_id:
        return "Anonymous"
    h = int(hashlib.sha256(
        (_COACH_PSEUDONYM_SALT + str(user_id)).encode("utf-8")
    ).hexdigest(), 16)
    adj = _COACH_PSEUDONYM_ADJ[(h // len(_COACH_PSEUDONYM_ANIMAL)) % len(_COACH_PSEUDONYM_ADJ)]
    animal = _COACH_PSEUDONYM_ANIMAL[h % len(_COACH_PSEUDONYM_ANIMAL)]
    return f"{adj} {animal}"
