"""An accepted clearer version is practised, not written (rule 5, founder
lock 2026-10-12, moment and feedback chat).

The Ideal Text is only what the speaker said in their latest Take. When the
speaker taps "Accept and practise", their `apply_suggestion` answer is
recorded and the clearer version is what they practise; the Paragraph takes
the words only once they are said in the next Take. No Paragraph version is
written here any more. Earlier 'accepted_rewrite' revisions stay in each
Paragraph's history (services/paragraph_history.py reads them).
"""
from __future__ import annotations

from typing import Any


def text_update_for_answer(database: Any, row: dict, arc_id: str,
                           owner_user_id: str, take_session_id: str) -> dict:
    """For the answer route: nothing to write. Kept as the route's hook so
    the answer path stays one shape."""
    return {}
