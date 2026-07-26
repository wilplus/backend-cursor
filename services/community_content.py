"""Community Content Studio — one journal post → the three derived community
formats (founder 2026-07-26).

The founder writes the week's essay into the Journal CMS as an ordinary post.
That post IS format ① Technique. One button sends it here, and this module
derives the other three formats prescribed by the content model in
``services/prompts/community_content_strategy.md``:

  ② myth_bust — the same idea inverted   (Thu)
  ③ fear      — the same idea confessed  (Tue)
  ④ win       — the same idea as a member-fill prompt (Sat)

The founder copies the results into Skool by hand. Nothing here posts anywhere.

FENCES
------
* PUBLIC ISOLATION — the output lives in ``journal_community_post`` and is
  reachable ONLY through the password-gated ``/v2/internal/journal/community/*``
  routes. No public ``/v2/journal/*`` handler may read that table: a "Win" post
  is a Skool thread ("share yours below"), not an article on the site. The rows
  carry no slug, no status and no published_at, so they are unpublishable by
  construction.
* L1 — this is a marketing surface. No F1 assembly module (the best-slide
  selection, the ideal-text assembly, the cross-take selection) may import
  it, and it never reads or writes an arc, session or piece row. Grep-fenced
  BOTH ways in ``test_community_content``: this module names none of them,
  and none of them names this module.
* AC-9 / CONSTRUCT — the derived copy is guarded in code (``_guard_flags``):
  a body carrying the retired construct vocabulary comes back FLAGGED, not
  silently dropped. These are drafts a human reads before posting, so a visible
  warning beats a deletion that hides the problem.
* FABRICATION — the model is told never to introduce a fact, statistic or study
  absent from the source essay, and ``_guard_flags`` raises a soft "verify"
  flag when a derived body cites something the essay does not. Posting an
  invented citation under the founder's own name is the real risk on this
  surface, so the check is belt-and-braces rather than prompt-only.

Synchronous by design (unlike the fire-and-forget suggestion surfaces): the
founder is watching a spinner.
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

# The three DERIVED formats. ① Technique is the input and is never generated.
FORMATS = ("myth_bust", "fear", "win")

# Human labels + the posting day each format lands on (content model cadence).
FORMAT_LABELS = {
    "myth_bust": ("Myth-bust", "Thu"),
    "fear": ("Fear", "Tue"),
    "win": ("Win", "Sat"),
}

_STRATEGY_FILENAME = "community_content_strategy.md"

# The journal allows a 200k body; a book-length essay would blow the context
# window and the bill, so the prompt sees at most this much.
_MAX_SOURCE_CHARS = 20_000
_MAX_NOTES_CHARS = 500

_MAX_TITLE_LEN = 120
_MAX_BODY_LEN = 2200
_MAX_LINE_LEN = 300
_PAYLOAD_VERSION = 1

# AC-9 output guard — the retired construct family must never reach copy the
# founder pastes in public. Same pattern as the per-snippet suggestion surface;
# kept as a local copy so this marketing module imports nothing from the loop.
_GUARD_CONSTRUCT_RE = re.compile(
    r"\bthreat[\s:\-]*challenge\b"
    r"|\bt\s*:\s*c\b"
    r"|\bcharisma\s+(?:score|profile|classifier|ratio)\b"
    r"|\bstress\s+(?:score|classifier)\b"
    r"|\bkpi\b",
    re.IGNORECASE,
)

# Tokens that read as a sourced claim. Their presence is only interesting when
# the SOURCE essay does not contain them — see _guard_flags.
_CLAIM_TOKENS = ("study", "studies", "research", "researcher", "scientist",
                 "percent", "%", "professor", "university", "trial")
_DIGIT_RE = re.compile(r"\d")

# Markdown the model sometimes emits despite the plain-text rule.
_BOLD_RE = re.compile(r"(\*\*|__)")
_HEADING_RE = re.compile(r"^#{1,6}\s*", re.MULTILINE)

_strategy_cache: Optional[str] = None


# ── the content model ──────────────────────────────────────────────────────

def load_strategy() -> str:
    """The content model text, module-cached.

    Returns "" when the file is unreadable — the caller then refuses to
    generate rather than calling the model with no content model at all,
    which would produce generic LinkedIn slop under the founder's name.
    """
    global _strategy_cache
    if _strategy_cache is not None:
        return _strategy_cache
    path = os.path.join(os.path.dirname(__file__), "prompts",
                        _STRATEGY_FILENAME)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            _strategy_cache = fh.read().strip()
    except Exception as e:
        logger.warning("community_content: strategy doc unreadable at %s: %s",
                       path, e)
        _strategy_cache = ""
    return _strategy_cache


# ── prompts ────────────────────────────────────────────────────────────────

_PREAMBLE = (
    "You are the content editor for WillLab, a free personal-growth community "
    "run by one person. You are given ONE finished essay — the week's "
    "\"Technique\" post, which the founder already wrote by talking it into "
    "his own app. Your job is to rotate that single idea into the community's "
    "other post formats, exactly as the content model below prescribes. You "
    "are not writing new ideas. You are turning one idea to a different "
    "angle.\n\n"
    "HARD RULES — every one of these is load-bearing:\n"
    "1. Never introduce a fact, statistic, study, researcher, or claim that "
    "is not in the source essay. If the essay cites research you may refer to "
    "it in the essay's own terms; you may never add, sharpen, or name a new "
    "one. Inventing a source here means the founder posts a fabricated "
    "citation under his own name.\n"
    "2. Write in the founder's first-person voice, matched to the source "
    "essay's register. He is the \"I\" in every post.\n"
    "3. Write in the SAME LANGUAGE as the source essay. A Polish essay gets "
    "Polish posts.\n"
    "4. Plain text only. No markdown, no headings, no bold, no hashtags, no "
    "links. Line breaks and blank lines are the only formatting. At most one "
    "emoji, and only leading the Win post.\n"
    "5. Never use the words: charisma score, stress score, threat, ratio, "
    "classifier, KPI. Never quote a number as a measure of the reader's "
    "performance.\n"
    "6. Never mention the app inside a post body. App mentions belong in the "
    "two separate lines you return (soft_cta_line, app_proof_line), which the "
    "founder appends himself.\n"
    "7. If the essay is too thin to derive a format honestly, keep that "
    "format short and true to the essay — never pad it with generic advice.\n\n"
    "THE CONTENT MODEL (authoritative — follow it over your own instincts):\n"
)


def build_system_prompt() -> str:
    """Preamble + the content model. "" when the model file is missing."""
    strategy = load_strategy()
    if not strategy:
        return ""
    return (
        f"{_PREAMBLE}\n{strategy}\n\n"
        "Return ONLY valid JSON matching the provided schema."
    )


def build_user_prompt(post: Any, *, formats: Any = FORMATS,
                      notes: Any = None) -> str:
    """The source essay + what to derive from it. Pure."""
    p = post if isinstance(post, dict) else {}
    title = (p.get("title") or "").strip()
    excerpt = (p.get("excerpt") or "").strip()
    body = (p.get("body") or "").strip()
    if len(body) > _MAX_SOURCE_CHARS:
        body = body[:_MAX_SOURCE_CHARS].rstrip() + "…"

    wanted = [f for f in (formats or FORMATS) if f in FORMATS] or list(FORMATS)
    names = ", ".join(FORMAT_LABELS[f][0] for f in wanted)

    lines = [
        "Here is this week's Technique essay — the anchor post. Derive the "
        f"following format(s) from it: {names}.",
        "",
        f"Title: {title or '(untitled)'}",
    ]
    if excerpt:
        lines.append(f"Excerpt: {excerpt}")
    lines += ["", "Essay:", body, ""]

    note = notes.strip() if isinstance(notes, str) else ""
    if note:
        lines.append(f"The founder's steer for this week: {note[:_MAX_NOTES_CHARS]}")
    lines += [
        "",
        "Also identify which of the six pillars this essay belongs to, and "
        "name the week's theme in a few words.",
        f"Return exactly {len(wanted)} post(s), one per requested format: "
        f"{', '.join(wanted)}.",
    ]
    return "\n".join(lines)


# ── response schema ────────────────────────────────────────────────────────

_RESPONSE_SCHEMA = {
    "name": "community_posts",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["pillar_id", "pillar_name", "theme", "posts",
                     "soft_cta_line", "app_proof_line"],
        "properties": {
            "pillar_id": {"type": "integer"},
            "pillar_name": {"type": "string", "maxLength": 80},
            "theme": {"type": "string", "maxLength": 120},
            "posts": {"type": "array", "maxItems": 3, "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["format", "title", "body"],
                "properties": {
                    "format": {"type": "string",
                               "enum": ["myth_bust", "fear", "win"]},
                    "title": {"type": "string", "maxLength": _MAX_TITLE_LEN},
                    "body": {"type": "string", "maxLength": _MAX_BODY_LEN},
                },
            }},
            "soft_cta_line": {"type": "string", "maxLength": _MAX_LINE_LEN},
            "app_proof_line": {"type": "string", "maxLength": _MAX_LINE_LEN},
        },
    },
    "strict": True,
}


# ── cleaning + guards ──────────────────────────────────────────────────────

def _strip_markup(text: Any) -> str:
    """Plain text, per the content model's Skool rule. Pure."""
    if not isinstance(text, str):
        return ""
    out = _BOLD_RE.sub("", text)
    out = _HEADING_RE.sub("", out)
    return out.strip()


def _guard_flags(body: str, source: str) -> list:
    """The two soft warnings the CMS renders above a derived body.

    ``construct`` — the retired score vocabulary reached user-visible copy.
    ``verify``    — the body carries a number or a sourced-sounding claim that
                    the SOURCE essay does not, i.e. the model may have
                    invented it.

    Neither drops the post: a founder reviewing a flagged draft is strictly
    better than a draft that silently vanished. Pure.
    """
    flags = []
    if _GUARD_CONSTRUCT_RE.search(body or ""):
        flags.append("construct")
    src = (source or "").lower()
    low = (body or "").lower()
    invented = False
    for token in _CLAIM_TOKENS:
        if token in low and token not in src:
            invented = True
            break
    if not invented and _DIGIT_RE.search(body or ""):
        # A digit the essay never used is the cheapest fabrication tell.
        digits_in_body = set(re.findall(r"\d+", body or ""))
        digits_in_source = set(re.findall(r"\d+", source or ""))
        invented = bool(digits_in_body - digits_in_source)
    if invented:
        flags.append("verify")
    return flags


def _clean_payload(parsed: Any, source_text: str,
                   wanted: Any = FORMATS) -> Optional[dict]:
    """Validate + guard the model output into the persisted shape.

    Assumes the model misbehaves: every cap in the schema is re-enforced here,
    unknown/duplicate formats are dropped, and an out-of-range pillar becomes
    None rather than a guess. Returns None when nothing usable survives. Pure.
    """
    if not isinstance(parsed, dict):
        return None
    allowed = {f for f in (wanted or FORMATS) if f in FORMATS} or set(FORMATS)

    posts: list = []
    seen: set = set()
    for raw in (parsed.get("posts") or []):
        if not isinstance(raw, dict):
            continue
        fmt = raw.get("format")
        if fmt not in allowed or fmt in seen:
            continue
        body = _strip_markup(raw.get("body"))[:_MAX_BODY_LEN]
        if not body:
            continue
        seen.add(fmt)
        posts.append({
            "format": fmt,
            "title": _strip_markup(raw.get("title"))[:_MAX_TITLE_LEN],
            "body": body,
            "flags": _guard_flags(body, source_text),
            "char_count": len(body),
        })
    if not posts:
        return None

    pillar_id = parsed.get("pillar_id")
    if not isinstance(pillar_id, int) or isinstance(pillar_id, bool) \
            or not 1 <= pillar_id <= 6:
        pillar_id, pillar_name = None, ""
    else:
        pillar_name = _strip_markup(parsed.get("pillar_name"))[:80]

    return {
        "pillar_id": pillar_id,
        "pillar_name": pillar_name,
        "theme": _strip_markup(parsed.get("theme"))[:120],
        "posts": posts,
        "soft_cta_line": _strip_markup(
            parsed.get("soft_cta_line"))[:_MAX_LINE_LEN],
        "app_proof_line": _strip_markup(
            parsed.get("app_proof_line"))[:_MAX_LINE_LEN],
        "version": _PAYLOAD_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


# ── the call ───────────────────────────────────────────────────────────────

def generate_community_posts(post: Any, *, formats: Any = FORMATS,
                             notes: Any = None) -> Optional[dict]:
    """One LLM call → the cleaned payload, or None.

    None on: an empty source body, a missing content model, no LLM available,
    a failed/garbled call, or output with nothing usable in it. Never raises —
    the route maps None to a 503 the founder can retry.
    """
    p = post if isinstance(post, dict) else {}
    source_text = (p.get("body") or "").strip()
    if not source_text:
        return None

    system = build_system_prompt()
    if not system:
        logger.warning("community_content: no content model — refusing to "
                       "generate")
        return None

    wanted = tuple(f for f in (formats or FORMATS) if f in FORMATS) or FORMATS

    try:
        from services.llm import chat_complete
        from services.llm_config import SPEC_COMMUNITY_CONTENT as spec
    except Exception as e:
        logger.warning("community_content: llm import failed: %s", e)
        return None

    try:
        result = chat_complete(
            spec=spec,
            system=system,
            user=build_user_prompt(p, formats=wanted, notes=notes),
            surface="community_content",
            response_format_override={
                "type": "json_schema", "json_schema": _RESPONSE_SCHEMA,
            },
        )
    except Exception as e:
        logger.warning("community_content: llm call failed: %s", e)
        return None

    parsed = getattr(result, "parsed", None) if result else None
    if parsed is None and result is not None:
        try:
            parsed = json.loads(getattr(result, "text", "") or "")
        except (ValueError, TypeError):
            parsed = None

    cleaned = _clean_payload(parsed, source_text, wanted)
    if cleaned is None:
        logger.warning("community_content: unusable model output")
        return None
    cleaned["model"] = spec.model
    return cleaned


# ── persistence shapes ─────────────────────────────────────────────────────

def rows_for_upsert(journal_post_id: str, payload: dict,
                    inherit: Any = None) -> list:
    """The payload → journal_community_post rows.

    ``inherit`` is an existing sibling row on a SINGLE-FORMAT regenerate. The
    batch-level fields (pillar, theme, and the two app lines) are then taken
    from it rather than from this call, so rerolling one post cannot silently
    re-theme the week under the other two. Pure.
    """
    src = inherit if isinstance(inherit, dict) else {}
    use_inherited = bool(src)

    def pick(key, default=None):
        return src.get(key) if use_inherited else payload.get(key, default)

    now = datetime.now(timezone.utc).isoformat()
    rows = []
    for item in (payload.get("posts") or []):
        rows.append({
            "journal_post_id": str(journal_post_id),
            "kind": item["format"],
            "title": item.get("title") or "",
            "body": item.get("body") or "",
            "flags": item.get("flags") or [],
            "pillar_id": pick("pillar_id"),
            "pillar_name": pick("pillar_name") or "",
            "theme": pick("theme") or "",
            "soft_cta_line": pick("soft_cta_line") or "",
            "app_proof_line": pick("app_proof_line") or "",
            "model": payload.get("model"),
            "generated_at": payload.get("generated_at") or now,
            "updated_at": now,
        })
    return rows


def serialize_community_item(row: Any) -> dict:
    """The CMS shape for one derived post. Pure."""
    r = row if isinstance(row, dict) else {}
    kind = r.get("kind")
    label, day = FORMAT_LABELS.get(kind, (kind or "", ""))
    body = r.get("body") or ""
    flags = r.get("flags")
    if isinstance(flags, str):
        try:
            flags = json.loads(flags)
        except (ValueError, TypeError):
            flags = []
    return {
        "id": r.get("id"),
        "journal_post_id": r.get("journal_post_id"),
        "kind": kind,
        "label": label,
        "day": day,
        "title": r.get("title") or "",
        "body": body,
        "char_count": len(body),
        "flags": flags if isinstance(flags, list) else [],
        "pillar_id": r.get("pillar_id"),
        "pillar_name": r.get("pillar_name") or "",
        "theme": r.get("theme") or "",
        "soft_cta_line": r.get("soft_cta_line") or "",
        "app_proof_line": r.get("app_proof_line") or "",
        "generated_at": r.get("generated_at"),
        "updated_at": r.get("updated_at"),
    }
