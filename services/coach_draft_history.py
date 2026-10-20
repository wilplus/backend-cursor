"""Every draft keeps its prompt (0480; founder 2026-10-19, decisions log N79).

A model draft shown to a coach lives on the row it is shown from (the
moment's request, the coach's Take word), and a re-draft replaces it. This
module keeps each one in ``coach_draft_history`` as it was drafted: the
draft, the model, what its prompt was given, the sha256 of the exact
system and user text sent, and the surface's locked prompt hash at that
moment. When the coach saves an answer, the draft the row then carries is
settled: whether the saved words are that draft as written.

CAPTURE ONLY. No training, release, golden or promotion reader reads the
history, and it is in no payload. The row's own ``draft_prompt`` names the
draft (``draft_id``, beside the snapshot, never inside ``prompt_context``),
so what the pairs and their readers take from the snapshot is unchanged.
Every write here is best effort: the coach's draft shows and the answer
saves whether or not the history could be written. No provider call.
"""
from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

_log = logging.getLogger(__name__)


def new_draft_id() -> str:
    """The id a draft is kept under, named before its row is written so the
    row's snapshot and the history agree."""
    return str(uuid.uuid4())


def prompt_sha256(system: Any, user: Any) -> str:
    """sha256 of the exact text sent: the UTF-8 of the JSON array
    [system, user], no spaces, no ASCII escaping."""
    sent = json.dumps([str(system or ""), str(user or "")], ensure_ascii=False,
                      separators=(",", ":"))
    return hashlib.sha256(sent.encode("utf-8")).hexdigest()


def _lock_for(surface: str) -> Optional[str]:
    """The surface's locked prompt hash now, the value runs, evaluations and
    promotions record; None when it cannot be read (a record, not a gate)."""
    try:
        from services.ml_surface_contracts import locked_prompt_hash
        return locked_prompt_hash(surface)
    except Exception as e:  # noqa: BLE001 -- a record, not a gate
        _log.info("prompt lock unavailable for %s: %s", surface, e)
        return None


def keep(database: Any, *, draft_id: str, surface: str, prompt_family: str,
         coach_id: Any, draft: dict, inputs: dict, take_session_id: Any,
         owner_user_id: Any = None, snippet_id: Any = None,
         request_id: Any = None, take_word_id: Any = None) -> bool:
    """One draft as it was shown. ``draft`` is the composer's output: its
    text, model version, and the system and user text it sent. True when
    the row was written; never raises."""
    writer = getattr(database, "insert_coach_draft", None)
    if writer is None or not isinstance(draft, dict) or not draft.get("text"):
        return False
    try:
        writer(id=str(draft_id), surface=str(surface), prompt_family=str(prompt_family),
               coach_id=str(coach_id or ""), owner_user_id=str(owner_user_id or "") or None,
               take_session_id=str(take_session_id or ""),
               snippet_id=str(snippet_id or "") or None,
               request_id=str(request_id or "") or None,
               take_word_id=str(take_word_id or "") or None,
               draft_text=str(draft["text"]),
               model_version=str(draft.get("model_version") or "") or None,
               prompt_sha256=prompt_sha256(draft.get("system"), draft.get("user")),
               prompt_lock_sha256=_lock_for(surface),
               prompt_inputs=dict(inputs or {}))
        return True
    except Exception as e:  # noqa: BLE001 -- the draft still shows
        _log.warning("coach draft not kept surface=%s take=%s: %s", surface,
                     take_session_id, e, exc_info=True)
        return False


def settle(database: Any, row: Any, *, final: Any) -> None:
    """The coach saved an answer while ``row`` (a request or a Take word, as
    it was when they saved) carried a kept draft: record whether the saved
    words are that draft as written. No draft, or none kept: nothing.
    Never raises."""
    if not isinstance(row, dict) or not row.get("draft_text"):
        return
    snapshot = row.get("draft_prompt")
    draft_id = snapshot.get("draft_id") if isinstance(snapshot, dict) else None
    writer = getattr(database, "settle_coach_draft", None)
    if not draft_id or writer is None:
        return
    from services.feedback_pairs import normalised
    unchanged = bool(normalised(final)) and normalised(final) == normalised(row["draft_text"])
    try:
        writer(draft_id=str(draft_id), final_unchanged=unchanged,
               settled_at=datetime.now(timezone.utc).isoformat())
    except Exception as e:  # noqa: BLE001 -- the answer is saved either way
        _log.warning("coach draft not settled id=%s: %s", draft_id, e, exc_info=True)
