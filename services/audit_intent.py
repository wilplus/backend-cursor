"""Audit chat intercept (willab Prompt C §5).

A signed-in user asking for "their audit" (any language) gets a short bubble +
a button (suggested_action="audit") that opens the audits page — WITHOUT
routing through the Lounge librarian (§0: never add rules to master_doc_rag,
at its attention ceiling). The /chat/query route calls handle_audit_intent
BEFORE the librarian and short-circuits the turn when it fires.

Deterministic: a cheap multilingual keyword pre-gate (no LLM) decides IF this
is an audit request; only then does it look up the user's audits. The bubble
line is one short in-language pointer (LLM-rendered, with the audit name as a
hard fallback) — it NEVER explains what an audit is (founder rule). The button
+ the page do the rest.
"""
from __future__ import annotations

import logging
import re
from typing import Optional

logger = logging.getLogger(__name__)

_SURFACE = "audit_intent"

# "audit" is a specific noun; the prefix covers en/de/fr/it/es/pt
# (audit/audits/auditor/auditoría/auditoria) + pl (audyt/audytu). A rare false
# positive ("audition") is harmless — the gate ALSO requires the user to have
# an audit, else it falls through to the librarian.
_AUDIT_HINT = re.compile(r"\baudit|\baudyt", re.IGNORECASE)


def _looks_like_audit_request(message: str) -> bool:
    if not message:
        return False
    return bool(_AUDIT_HINT.search(message))


def _render_pointer(audit_name: str, message: str) -> Optional[str]:
    """One short in-language line that frames the audit button. None on any
    failure (caller falls back to the audit name)."""
    try:
        import json as _json

        from services.llm import chat_complete
        from services.llm_config import SPEC_AUDIT_POINTER
        from services.will_voice import with_voice_rules
    except Exception as e:  # pragma: no cover - import guard
        logger.warning("audit_intent: llm import failed: %s", e)
        return None

    system = with_voice_rules("\n".join(f"- {r}" for r in [
        "Write ONE short line (max ~12 words) in the USER'S LANGUAGE that "
        "points them to their audit, which opens via the button below your "
        "message.",
        "Do NOT explain what an audit is. No preamble, no marketing, no "
        "score/verdict. Just a brief, warm hand-off to the button.",
        "You MAY reference the audit by its name if it reads naturally.",
        'Output strict JSON: {"line": "<the line>"}.',
    ]))
    user_prompt = (
        f"Audit name: {audit_name}\n\nUser message:\n{message.strip()}"
    )
    schema = {
        "name": "audit_pointer",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["line"],
            "properties": {"line": {"type": "string", "maxLength": 200}},
        },
        "strict": True,
    }
    try:
        result = chat_complete(
            spec=SPEC_AUDIT_POINTER, system=system, user=user_prompt,
            surface=_SURFACE,
            response_format_override={"type": "json_schema", "json_schema": schema},
        )
    except Exception as e:
        logger.warning("audit_intent: render failed: %s", e)
        return None
    if not result:
        return None
    parsed = result.parsed
    if not isinstance(parsed, dict):
        try:
            parsed = _json.loads((result.text or "").strip())
        except Exception:
            return None
        if not isinstance(parsed, dict):
            return None
    line = str(parsed.get("line") or "").strip()
    return line or None


def _get_db(database):
    if database is not None:
        return database
    from services.db import db as _db
    return _db


def handle_audit_intent(
    user_id: Optional[str], message: str, *, database=None,
) -> Optional[dict]:
    """If ``message`` asks for the user's audit AND they have one, return
    ``{"answer": <short in-language line>, "suggested_action": "audit"}``.
    Otherwise None (the route falls through to the librarian). Never raises."""
    if not user_id or not isinstance(message, str) or not message.strip():
        return None
    if not _looks_like_audit_request(message):
        return None
    db = _get_db(database)
    try:
        audits = db.list_user_audits(user_id)
    except Exception:
        audits = []
    if not audits:
        # Asked for an audit but has none — let the librarian handle it (it
        # won't invent one; this avoids a confusing dead-end button).
        return None
    name = str(audits[0].get("name") or "").strip()
    answer = _render_pointer(name, message) or name or "Here's your audit."
    logger.info("audit_intent: surfaced audit for user=%s", user_id)
    return {"answer": answer, "suggested_action": "audit"}
