"""V4's one batched call per Take: each moment's role and whether it holds
together (founder H6 "one batched LLM call per Take"; S-B1 A "Holding
together"; S-B1b A "the moment roles and their weights"; V4 B1.3, B1.6).

The roles and their weights are version 1 as the founder signed them. A
later change is version 2, and older reads and picks keep the version they
used. The weights stay inside the machine (AC-9); this module only tags.

The call goes through the shared language-model wrapper, so inside a
protected provider scope it takes its own per-call permit (PLF1). A failed,
refused or malformed answer returns None: the read then stores no role and
no holding-together signal, and nothing waits for it (LIVE LOOP).
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

ROLES_VERSION = "v4-moment-roles-v1"
HOLDING_TOGETHER_VERSION = "v4-holding-together-v1"

#: S-B1b A, version 1 (decisions log N65). Internal only.
ROLE_WEIGHTS: dict[str, float] = {
    "opening": 1.0,
    "main_point": 1.0,
    "close": 1.0,
    "evidence": 0.7,
    "transition": 0.4,
    "aside": 0.2,
}
ROLES = tuple(ROLE_WEIGHTS)

#: S-B1 A "Holding together": 1 yes, 0.5 partly, 0 no.
HOLDS_TOGETHER = {"yes": 1.0, "partly": 0.5, "no": 0.0}

SURFACE = "v4_take_tags"
#: Words per moment sent to the call; a moment is about 75 words, so this
#: only trims a runaway block.
_MAX_CHARS = 1500

_SCHEMA = {
    "name": "v4_take_tags",
    "schema": {
        "type": "object", "additionalProperties": False,
        "required": ["moments"],
        "properties": {"moments": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["ref", "role", "holds_together"],
            "properties": {
                "ref": {"type": "string"},
                "role": {"type": "string", "enum": list(ROLES)},
                "holds_together": {"type": "string",
                                   "enum": list(HOLDS_TOGETHER)},
            },
        }}},
    },
    "strict": True,
}


def parse(data: Any, refs: list[str]) -> Optional[dict[str, dict]]:
    """{ref: {"role", "holding_together"}} for the refs asked, or None.

    An answer naming an unknown ref, a ref twice, an unknown role or an
    unknown holding-together answer is dropped for that ref only; a ref the
    answer leaves out simply has no tag. None when nothing usable came back.
    """
    if not isinstance(data, dict) or not isinstance(data.get("moments"), list):
        return None
    wanted = set(refs)
    seen: dict[str, int] = {}
    out: dict[str, dict] = {}
    for row in data["moments"]:
        if not isinstance(row, dict):
            continue
        ref = str(row.get("ref") or "")
        if ref not in wanted:
            continue
        seen[ref] = seen.get(ref, 0) + 1
        role = row.get("role")
        holds = row.get("holds_together")
        out[ref] = {
            "role": role if role in ROLE_WEIGHTS else None,
            "holding_together": HOLDS_TOGETHER.get(str(holds))
            if holds in HOLDS_TOGETHER else None,
        }
    for ref, count in seen.items():
        if count > 1:
            out.pop(ref, None)
    return out or None


def tag_take(moments: list[dict], *, session_id: Optional[str] = None,
             arc_id: Optional[str] = None) -> Optional[dict[str, dict]]:
    """One call for the whole Take. ``moments``: [{"ref", "text"}] in
    spoken order. Never raises."""
    rows = [
        {"ref": str(m.get("ref") or ""),
         "text": str(m.get("text") or "")[:_MAX_CHARS]}
        for m in moments or [] if isinstance(m, dict) and m.get("ref")
    ]
    if not rows:
        return None
    try:
        from services.llm import chat_complete
        from services.llm_config import SPEC_V4_TAKE_TAGS
        from services.prompts.v4_take_tags import SYSTEM
        result = chat_complete(
            spec=SPEC_V4_TAKE_TAGS, system=SYSTEM,
            user=json.dumps({"moments": rows}, ensure_ascii=False),
            surface=SURFACE, session_id=session_id, arc_id=arc_id,
            response_format_override={"type": "json_schema",
                                      "json_schema": _SCHEMA},
        )
        return parse(result.parsed if result else None,
                     [row["ref"] for row in rows])
    except Exception as error:  # noqa: BLE001 -- the read stores no tag
        logger.warning("v4 take tags failed take=%s: %s", session_id, error)
        return None
