"""The catalogue of signed lines (founder 2026-09-30, E3 and C4; P1-4).

One signed sentence per pattern, read by the Manager before its fallback:

  * a PRAISE row (family great_formulation) gets `praise_line`: the line
    for its device first (an exact-quote structural device, or the
    impeccable read), else the first of its delivery cues that has a line,
    else the line for the confident read itself;
  * a REWRITE row (family rewrite_clarity) gets `rewrite_move`: the line
    for its why_key ("clarity", "clarity_tentative", ...).

A row with no matching line is left as it is: the sheet keeps its constant
and the fallback stays honest (contract 24f). Nothing here invents a line,
scores anything, or reads a recording (AC-9, L3). Pure except `decorate`'s
one catalogue read, which the caller passes in.
"""
from __future__ import annotations

from typing import Any, Optional

LANES = ("praise", "rewrite")
PATTERN_KINDS = {
    "praise": ("read", "cue", "device"),
    "rewrite": ("move",),
}
#: The read a praise line falls back to when neither device nor cue has one.
CONFIDENT_READ = "confident_read"
MAX_TEXT = 400
_KEY_MAX = 64


class CatalogueRefusal(Exception):
    def __init__(self, message: str, *, code: str = "INVALID_INPUT",
                 status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status


def _clean(value: Any, limit: int) -> str:
    text = value.strip() if isinstance(value, str) else ""
    return text if 0 < len(text) <= limit else ""


def validate_line(body: Any) -> dict:
    """The one row an author may write, or a CatalogueRefusal naming why.

    `signed_by` is taken by the ROUTE from the authenticated caller, never
    from the body (L3)."""
    if not isinstance(body, dict):
        raise CatalogueRefusal("body must be an object")
    lane = _clean(body.get("lane"), _KEY_MAX)
    if lane not in LANES:
        raise CatalogueRefusal("lane must be praise or rewrite")
    kind = _clean(body.get("pattern_kind"), _KEY_MAX)
    if kind not in PATTERN_KINDS[lane]:
        raise CatalogueRefusal(
            f"pattern_kind for {lane} must be one of "
            f"{', '.join(PATTERN_KINDS[lane])}")
    key = _clean(body.get("pattern_key"), _KEY_MAX)
    if not key or any(ch.isspace() for ch in key):
        raise CatalogueRefusal("pattern_key is required and carries no spaces")
    text = _clean(body.get("text"), MAX_TEXT)
    if not text:
        raise CatalogueRefusal(f"text is required, at most {MAX_TEXT} characters")
    if any(ch.isdigit() for ch in text) and "%" in text:
        # A percentage in a user-facing line is a number about the speaker
        # (AC-9). Digits alone are allowed: "the last four words" is words.
        raise CatalogueRefusal("a line may not carry a percentage")
    return {"lane": lane, "pattern_kind": kind, "pattern_key": key,
            "text": text}


def newest_lines(rows: Any) -> dict[tuple[str, str, str], str]:
    """The newest ACTIVE line per (lane, kind, key). Rows in any order."""
    best: dict[tuple[str, str, str], tuple[int, str]] = {}
    for row in rows or []:
        if not isinstance(row, dict) or row.get("active") is False:
            continue
        key = (str(row.get("lane") or ""), str(row.get("pattern_kind") or ""),
               str(row.get("pattern_key") or ""))
        text = row.get("text")
        version = row.get("version")
        if not all(key) or not isinstance(text, str) or not text.strip():
            continue
        if isinstance(version, bool) or not isinstance(version, int):
            version = 1
        if key not in best or version > best[key][0]:
            best[key] = (version, text.strip())
    return {key: text for key, (_, text) in best.items()}


def praise_line_for(row: Any, lines: dict) -> Optional[str]:
    """The signed line behind a praise row, by its evidence."""
    if not isinstance(row, dict) or not lines:
        return None
    device = row.get("device")
    if isinstance(device, str) and device:
        line = lines.get(("praise", "device", device))
        if line:
            return line
    for cue in row.get("cue_keys") or []:
        if isinstance(cue, str):
            line = lines.get(("praise", "cue", cue))
            if line:
                return line
    return lines.get(("praise", "read", CONFIDENT_READ))


def rewrite_move_for(row: Any, lines: dict) -> Optional[str]:
    """The signed move behind a rewrite row, by its why_key."""
    if not isinstance(row, dict) or not lines:
        return None
    why = row.get("why_key")
    if not isinstance(why, str) or not why:
        return None
    return lines.get(("rewrite", "move", why))


def decorate(changes: Any, catalogue_rows: Any) -> list:
    """The served rows with `praise_line` / `rewrite_move` where the
    catalogue has one. Rows are copied; nothing else on them changes."""
    lines = newest_lines(catalogue_rows)
    out: list = []
    for row in changes or []:
        if not isinstance(row, dict) or not lines:
            out.append(row)
            continue
        if is_praise(row):
            line = praise_line_for(row, lines)
            out.append({**row, "praise_line": line} if line else row)
        elif is_rewrite(row):
            move = rewrite_move_for(row, lines)
            out.append({**row, "rewrite_move": move} if move else row)
        else:
            out.append(row)
    return out


def is_praise(row: dict) -> bool:
    """The sheet's own rule (chunkSteps.isPraiseFeedback): the praise family,
    or the impeccable read."""
    return (row.get("feedback_family") == "great_formulation"
            or row.get("device") == "impeccable")


def is_rewrite(row: dict) -> bool:
    """The sheet's own rule (paragraphOverlay.rewriteOf): the rewrite family,
    or any replace with words to propose (a legacy-lane row carries no
    family)."""
    proposed = row.get("proposed_text")
    return (row.get("feedback_family") == "rewrite_clarity"
            or (row.get("kind") == "replace"
                and isinstance(proposed, str) and bool(proposed.strip())))
