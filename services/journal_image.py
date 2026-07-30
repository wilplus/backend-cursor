"""Journal cover images, generated (founder 2026-07-28).

One button in the CMS next to a post: read the post, write an image brief,
draw it, land the file in the same R2 journal bucket an uploaded cover would.
A notes box steers the next attempt, and "Regenerate" re-runs the brief with
that note PLUS the previous brief — so "darker, no hands" refines the image
the founder is looking at instead of drawing an unrelated one.

Two model calls, on purpose:

  1. THE BRIEF (a text model).  A journal body runs to 200k characters and an
     image model takes a few thousand — something has to distil the post into
     one scene. Doing that in a text model is also what makes the notes box
     work: "less literal" is an instruction about a brief, not a pixel op. The
     brief is returned to the CMS so the founder sees what was asked for.
  2. THE DRAW (an image model).  Bytes come back base64, are PUT to R2
     server-side, and the PUBLIC R2 url is what we store. The image model's own
     url is never persisted — DALL·E's expires in about an hour, which would
     blank every cover on the site shortly after publishing.

Degrades rather than fails: with no text model available the brief falls back
to a deterministic one built from the title, excerpt and notes. The image is
worse; the button still works.

FENCES
------
* PUBLIC COPY — ``alt_text`` is rendered on the public post, so it goes
  through the same construct guard as the community drafts: the retired score
  vocabulary comes back FLAGGED, never silently rewritten, on a row the
  founder is already looking at. Posts default to draft, so no generated copy
  reaches the site without a human publish.
* NO TEXT IN THE IMAGE — briefed hard, and not for taste: image models render
  lettering as garbage, and a cover with garbled words sits directly under a
  real headline. Also no recognizable people and no brand marks, which is a
  rights question, not a style one.
* L1 / LIVE LOOP — a marketing surface. No F1 assembly module may import it,
  and it reads no arc, session or piece row. Grep-fenced both ways in
  test_journal_image.py.

Synchronous by design (like the community studio): the founder is watching a
spinner, and an image takes ten to thirty seconds.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ── caps ───────────────────────────────────────────────────────────────────

# The brief only needs the shape of the piece, not the whole essay.
_MAX_SOURCE_CHARS = 6_000
_MAX_NOTES_CHARS = 500
# DALL·E 3 hard-rejects a prompt over 4000 characters; stay clear of the edge.
_MAX_PROMPT_CHARS = 3_800
# Matches the cover_alt cap in services/journal.py, so a generated alt can
# always be written to the post without the validator trimming it.
_MAX_ALT_LEN = 500
# What /image/list returns. Attempts are ~1KB rows; this is a UI cap, not a
# retention policy.
MAX_HISTORY = 24

# ── model defaults (env-overridable, no deploy needed) ─────────────────────
#
# gpt-image-1: what the live /images/generations endpoint is built around
# today. It always returns base64 — which is what we need, since the bytes go
# straight to R2 — and at medium it is about half the price of DALL·E 3 for a
# better cover.
#
# The pinned SDK (openai==1.59.2) predates this model and types only DALL·E's
# vocabulary, but it forwards `model`, `size` and `quality` as plain strings
# and does not enforce its Literal hints at runtime, so the call goes through.
# Verified live 2026-07-28.
_DEFAULT_MODEL = "gpt-image-1"
_DEFAULT_SIZE = "1536x1024"       # landscape — the journal card is a wide crop
_DEFAULT_QUALITY = "medium"       # "high" is ~3x the cost for a blog cover

_SIZES = {
    "dall-e-3": ("1024x1024", "1792x1024", "1024x1792"),
    "dall-e-2": ("256x256", "512x512", "1024x1024"),
    "gpt-image-1": ("1024x1024", "1536x1024", "1024x1536", "auto"),
}
_QUALITIES = {
    "dall-e-3": ("standard", "hd"),
    "dall-e-2": ("standard",),
    "gpt-image-1": ("low", "medium", "high", "auto"),
}
_FALLBACK_SIZE = {"dall-e-3": "1792x1024", "dall-e-2": "1024x1024",
                  "gpt-image-1": "1536x1024"}
_FALLBACK_QUALITY = {"dall-e-3": "standard", "dall-e-2": "standard",
                     "gpt-image-1": "medium"}

# Both families return PNG.
IMAGE_CONTENT_TYPE = "image/png"

# The house look. Env-overridable (JOURNAL_IMAGE_STYLE) so the founder can pin
# his own look without a deploy — it is prepended to every brief.
_DEFAULT_STYLE = (
    "Editorial photography for a personal-growth journal: one quiet, physical "
    "scene, natural light, muted and slightly desaturated palette, generous "
    "empty space for a headline to sit over. Restrained and adult — never "
    "stock-photo triumphant, never neon, never a 3D render."
)

# AC-9 output guard. Local copy of the community-studio pattern so this
# marketing module imports nothing from the loop.
_GUARD_CONSTRUCT_RE = re.compile(
    r"\bthreat[\s:\-]*challenge\b"
    r"|\bt\s*:\s*c\b"
    r"|\bcharisma\s+(?:score|profile|classifier|ratio)\b"
    r"|\bstress\s+(?:score|classifier)\b"
    r"|\bkpi\b",
    re.IGNORECASE,
)

_BOLD_RE = re.compile(r"(\*\*|__)")
_HEADING_RE = re.compile(r"^#{1,6}\s*", re.MULTILINE)

# OpenAI's refusal for a brief its safety system won't draw. Distinguished
# from a transient failure because the founder can act on it (reword the
# note) and cannot act on the other.
_REJECT_TOKENS = ("content_policy", "safety system", "content policy",
                  "rejected as a result of our safety")


class JournalImageError(RuntimeError):
    """Generation failed. Message is safe to show the CMS author."""


class ImageRejected(JournalImageError):
    """The image model refused the brief (content policy). The author's 400 —
    rewording the note is the fix, retrying the same brief is not."""


# ── config ─────────────────────────────────────────────────────────────────

def _config():
    from config import Config
    return Config


def image_enabled() -> bool:
    return bool(getattr(_config(), "JOURNAL_IMAGE_ENABLED", True))


def image_model() -> str:
    return (getattr(_config(), "JOURNAL_IMAGE_MODEL", "")
            or _DEFAULT_MODEL).strip() or _DEFAULT_MODEL


def _family(model: Any = None) -> str:
    """The key into the per-model vocabularies, or "" for an unknown model.

    Unknown is not an error: a model released after this file was written
    should still be callable, it just gets no local validation.
    """
    m = (model or image_model()).strip().lower()
    return m if m in _SIZES else ""


def image_size(model: Any = None) -> str:
    """The configured size, or the family default when it is not one this
    model accepts — a typo'd env var should not 400 every draw."""
    fam = _family(model)
    want = (getattr(_config(), "JOURNAL_IMAGE_SIZE", "") or "").strip().lower()
    if not fam:
        return want or _DEFAULT_SIZE
    if want in _SIZES[fam]:
        return want
    if want:
        logger.warning("journal_image: JOURNAL_IMAGE_SIZE=%r invalid for %s — "
                       "using %s", want, fam, _FALLBACK_SIZE[fam])
    return _FALLBACK_SIZE[fam]


def image_quality(model: Any = None) -> str:
    fam = _family(model)
    want = (getattr(_config(), "JOURNAL_IMAGE_QUALITY", "")
            or "").strip().lower()
    if not fam:
        return want or _DEFAULT_QUALITY
    if want in _QUALITIES[fam]:
        return want
    if want:
        logger.warning("journal_image: JOURNAL_IMAGE_QUALITY=%r invalid for "
                       "%s — using %s", want, fam, _FALLBACK_QUALITY[fam])
    return _FALLBACK_QUALITY[fam]


def image_style() -> str:
    return (os.getenv("JOURNAL_IMAGE_STYLE") or "").strip() or _DEFAULT_STYLE


# ── the brief ──────────────────────────────────────────────────────────────

_BRIEF_SYSTEM = (
    "You are the art director for the Willpower Lab journal. You are given one "
    "essay and you write the brief for its cover image — a single scene, "
    "described for an image model.\n\n"
    "HARD RULES — every one of these is load-bearing:\n"
    "1. NO TEXT ANYWHERE IN THE IMAGE. No words, letters, numbers, captions, "
    "signage, handwriting, logos, watermarks, charts, diagrams or user "
    "interface. Image models render lettering as garbage and this cover sits "
    "directly under a real headline. State this constraint inside the prompt "
    "you write.\n"
    "2. No real, named, famous or recognizable people, and no brand marks. If "
    "a person appears they are anonymous — turned away, cropped, or distant.\n"
    "3. Describe ONE scene, physically: subject, setting, light, distance, "
    "palette. Do not illustrate the essay's argument as a diagram or a "
    "metaphor spelled out in objects. A cover sets a mood; it does not "
    "summarize.\n"
    "4. Obey the house style block you are given.\n"
    "5. Write the prompt in ENGLISH regardless of the essay's language — "
    "image models are weakest outside it.\n"
    "6. alt_text is accessibility copy on a public page: one plain sentence "
    "for what a sighted reader would see, in the SAME LANGUAGE as the essay. "
    "Not the essay's summary, not marketing, no 'image of'.\n"
    "7. Never use the words: charisma score, stress score, threat, ratio, "
    "classifier, KPI.\n"
    "8. When you are given a PREVIOUS BRIEF and a STEER, return that previous "
    "brief CHANGED BY the steer — keep every element the steer does not "
    "mention. This is a revision, not a new idea.\n\n"
    "Return ONLY valid JSON matching the provided schema."
)

_BRIEF_SCHEMA = {
    "name": "cover_image_brief",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["prompt", "alt_text"],
        "properties": {
            "prompt": {"type": "string", "maxLength": _MAX_PROMPT_CHARS},
            "alt_text": {"type": "string", "maxLength": 300},
        },
    },
    "strict": True,
}


def build_brief_user(post: Any, *, notes: Any = None,
                     previous: Any = None) -> str:
    """The essay + the house style + any steer. Pure."""
    p = post if isinstance(post, dict) else {}
    title = (p.get("title") or "").strip()
    excerpt = (p.get("excerpt") or "").strip()
    category = (p.get("category") or "").strip()
    body = (p.get("body") or "").strip()
    if len(body) > _MAX_SOURCE_CHARS:
        body = body[:_MAX_SOURCE_CHARS].rstrip() + "…"

    lines = ["HOUSE STYLE:", image_style(), "",
             f"Title: {title or '(untitled)'}"]
    if excerpt:
        lines.append(f"Excerpt: {excerpt}")
    if category:
        lines.append(f"Category: {category}")
    if body:
        lines += ["", "Essay:", body]

    prev = previous if isinstance(previous, dict) else {}
    prev_prompt = (prev.get("prompt") or "").strip()
    note = notes.strip()[:_MAX_NOTES_CHARS] if isinstance(notes, str) else ""

    if prev_prompt:
        lines += ["", "PREVIOUS BRIEF (the image on screen):",
                  prev_prompt[:_MAX_PROMPT_CHARS]]
    if note:
        lines += ["", f"STEER from the author: {note}"]
        if prev_prompt:
            lines.append("Apply the steer to the previous brief. Keep "
                         "everything it does not mention.")
    elif prev_prompt:
        # Regenerate with no note: the founder wants a different take on the
        # same essay, so say so explicitly — otherwise the model reads the
        # previous brief as something to reproduce.
        lines += ["", "No steer was given. Draw a DIFFERENT scene for the "
                  "same essay — do not repeat the previous brief."]

    lines += ["", "Write the cover brief."]
    return "\n".join(lines)


def _strip_markup(text: Any) -> str:
    if not isinstance(text, str):
        return ""
    return _HEADING_RE.sub("", _BOLD_RE.sub("", text)).strip()


def guard_flags(*parts: Any) -> list:
    """["construct"] when the retired score vocabulary reached generated copy.

    A flag, never a drop — the CMS renders a warning on a draft the founder is
    already looking at, and he edits or rerolls it. Pure.
    """
    blob = " ".join(p for p in parts if isinstance(p, str))
    return ["construct"] if _GUARD_CONSTRUCT_RE.search(blob) else []


def fallback_brief(post: Any, *, notes: Any = None,
                   previous: Any = None) -> dict:
    """A deterministic brief for when no text model is reachable.

    Deliberately blunt: house style, the title, the excerpt, the steer. Worse
    images than the model-written brief, but the button still draws something
    rather than 503ing on a dependency the founder cannot see. Pure.
    """
    p = post if isinstance(post, dict) else {}
    title = (p.get("title") or "").strip()
    excerpt = (p.get("excerpt") or "").strip()
    prev = previous if isinstance(previous, dict) else {}
    note = notes.strip()[:_MAX_NOTES_CHARS] if isinstance(notes, str) else ""

    base = (prev.get("prompt") or "").strip()
    if not base:
        subject = title or excerpt or "a quiet moment before speaking"
        base = (f"{image_style()} The scene evokes, without illustrating it "
                f"literally: {subject}.")
    parts = [base]
    if note:
        parts.append(f"Revision requested: {note}")
    parts.append("Absolutely no text, letters, numbers, logos, watermarks or "
                 "user interface anywhere in the image. No recognizable "
                 "people.")
    prompt = " ".join(parts)[:_MAX_PROMPT_CHARS]
    return {
        "prompt": prompt,
        "alt_text": (title or "Journal cover image")[:_MAX_ALT_LEN],
        "brief_source": "fallback",
    }


def compose_brief(post: Any, *, notes: Any = None,
                  previous: Any = None) -> dict:
    """The image brief: {prompt, alt_text, brief_source}.

    Never raises and never returns empty — a failed or garbled text call falls
    through to ``fallback_brief``. ``brief_source`` is "model" or "fallback"
    so the CMS (and a bug report) can tell which one drew the image.
    """
    try:
        from services.llm import chat_complete
        from services.llm_config import SPEC_JOURNAL_IMAGE_BRIEF as spec
    except Exception as e:
        logger.warning("journal_image: llm import failed: %s", e)
        return fallback_brief(post, notes=notes, previous=previous)

    try:
        result = chat_complete(
            spec=spec,
            system=_BRIEF_SYSTEM,
            user=build_brief_user(post, notes=notes, previous=previous),
            surface="journal_image_brief",
            response_format_override={
                "type": "json_schema", "json_schema": _BRIEF_SCHEMA,
            },
        )
    except Exception as e:
        logger.warning("journal_image: brief call failed: %s", e)
        result = None

    parsed = getattr(result, "parsed", None) if result else None
    if parsed is None and result is not None:
        try:
            parsed = json.loads(getattr(result, "text", "") or "")
        except (ValueError, TypeError):
            parsed = None

    prompt = _strip_markup((parsed or {}).get("prompt") if
                           isinstance(parsed, dict) else "")[:_MAX_PROMPT_CHARS]
    if not prompt:
        logger.warning("journal_image: unusable brief — using the fallback")
        return fallback_brief(post, notes=notes, previous=previous)

    alt = _strip_markup((parsed or {}).get("alt_text"))[:_MAX_ALT_LEN]
    p = post if isinstance(post, dict) else {}
    return {
        "prompt": prompt,
        "alt_text": alt or (p.get("title") or "").strip()[:_MAX_ALT_LEN],
        "brief_source": "model",
    }


# ── the draw ───────────────────────────────────────────────────────────────

def _looks_rejected(error: Exception) -> bool:
    text = str(error).lower()
    return any(token in text for token in _REJECT_TOKENS)


def _bytes_from_url(url: str) -> bytes:
    """Fetch a model-hosted image URL into bytes.

    Only reached on a legacy DALL·E model, which returns a link rather than
    base64. The link expires in about an hour, so it is resolved here and the
    bytes go to our own storage — a stored link would blank the cover on its
    own schedule.

    httpx, not requests: it is already a dependency (the Supabase client
    pulls it) and requests is not.
    """
    try:
        import httpx
        response = httpx.get(url, timeout=60.0, follow_redirects=True)
        response.raise_for_status()
        return response.content
    except Exception as e:
        logger.warning("journal_image: could not fetch the drawn image: %s", e)
        raise JournalImageError(
            "Could not download the image the model drew. Try again.") from e


def _draw(prompt: str) -> dict:
    """One image call → {image_bytes, revised_prompt, model, size, quality}.

    Raises ImageRejected on a content-policy refusal (the author's 400) and
    JournalImageError on everything else (a retryable 503).
    """
    try:
        from services.openai_service import openai_service
        client = openai_service.client
    except Exception as e:
        logger.warning("journal_image: openai import failed: %s", e)
        client = None
    if not client:
        raise JournalImageError(
            "The image model is not available (no OpenAI client).")

    model = image_model()
    size = image_size(model)
    quality = image_quality(model)

    # NO response_format. The live endpoint rejects it outright — "Unknown
    # parameter: 'response_format'" — for every model, not just gpt-image-1
    # (verified against the API 2026-07-28; the parameter belongs to an older
    # shape of this endpoint that the SDK still types). gpt-image-1 therefore
    # always returns base64, and a legacy DALL·E model returns a temporary
    # URL, which _bytes_from_url below resolves before it can expire.
    kwargs: dict = {"model": model, "prompt": prompt, "n": 1, "size": size,
                    "quality": quality,
                    # Measured live: 23s for a first draw, 98s for a steered
                    # one. 120 was close enough to that to cut off a slow but
                    # perfectly good image, so the ceiling is generous — it
                    # exists to stop a HUNG call holding the worker, not to
                    # bound a normal one.
                    "timeout": 180.0}

    try:
        response = client.images.generate(**kwargs)
    except Exception as e:
        if _looks_rejected(e):
            logger.info("journal_image: brief refused by the safety system")
            raise ImageRejected(
                "The image model refused this brief. Reword the note and try "
                "again.") from e
        logger.warning("journal_image: draw failed model=%s: %s", model, e)
        raise JournalImageError(
            "Could not draw the image right now. Try again.") from e

    data = list(getattr(response, "data", None) or [])
    first = data[0] if data else None
    b64 = getattr(first, "b64_json", None) if first is not None else None
    url = getattr(first, "url", None) if first is not None else None

    if b64:
        try:
            image_bytes = base64.b64decode(b64)
        except Exception as e:
            raise JournalImageError(
                "The image model returned something unreadable.") from e
    elif url:
        # A legacy DALL·E model hands back a temporary URL instead of bytes,
        # and that URL expires in about an hour. Fetch it NOW: storing the
        # link would blank every cover on the site shortly after publishing.
        image_bytes = _bytes_from_url(url)
    else:
        logger.warning("journal_image: no image in the response model=%s",
                       model)
        raise JournalImageError(
            "The image model returned no image. Try again.")

    return {
        "image_bytes": image_bytes,
        "revised_prompt": getattr(first, "revised_prompt", None),
        "model": model,
        "size": size,
        "quality": quality,
    }


def generate_cover_image(post: Any, *, notes: Any = None,
                         previous: Any = None) -> dict:
    """Brief → draw → the payload the route stores.

    Returns {image_bytes, content_type, prompt, alt_text, revised_prompt,
    brief_source, model, size, quality, flags}. Raises ImageRejected (400) or
    JournalImageError (503); never returns a half-usable result.
    """
    brief = compose_brief(post, notes=notes, previous=previous)
    drawn = _draw(brief["prompt"])
    return {
        "content_type": IMAGE_CONTENT_TYPE,
        "prompt": brief["prompt"],
        "alt_text": brief["alt_text"],
        "brief_source": brief["brief_source"],
        "flags": guard_flags(brief["alt_text"], brief["prompt"]),
        **drawn,
    }


# ── persistence shapes ─────────────────────────────────────────────────────

def row_for_insert(journal_post_id: str, result: dict, *, image_url: str,
                   storage_key: Any = None, notes: Any = None,
                   parent_id: Any = None) -> dict:
    """The generated attempt → a journal_post_image row. Pure."""
    r = result if isinstance(result, dict) else {}
    revised = r.get("revised_prompt")
    return {
        "journal_post_id": str(journal_post_id),
        "image_url": image_url,
        "storage_key": storage_key or None,
        "alt_text": (r.get("alt_text") or "")[:_MAX_ALT_LEN],
        "prompt": (r.get("prompt") or "")[:_MAX_PROMPT_CHARS],
        # DALL·E's rewrite runs long; the column is text but the CMS renders
        # it, so keep it bounded.
        "revised_prompt": revised[:4_000] if isinstance(revised, str) else None,
        "notes": (notes.strip()[:_MAX_NOTES_CHARS]
                  if isinstance(notes, str) else ""),
        "parent_image_id": str(parent_id) if parent_id else None,
        "flags": r.get("flags") or [],
        "model": r.get("model"),
        "size": r.get("size"),
        "quality": r.get("quality"),
    }


def serialize_image(row: Any) -> dict:
    """The CMS shape for one attempt. Pure."""
    r = row if isinstance(row, dict) else {}
    flags = r.get("flags")
    if isinstance(flags, str):
        try:
            flags = json.loads(flags)
        except (ValueError, TypeError):
            flags = []
    return {
        "id": r.get("id"),
        "journal_post_id": r.get("journal_post_id"),
        "image_url": r.get("image_url") or "",
        "alt_text": r.get("alt_text") or "",
        "prompt": r.get("prompt") or "",
        "revised_prompt": r.get("revised_prompt") or "",
        "notes": r.get("notes") or "",
        "parent_image_id": r.get("parent_image_id"),
        "flags": flags if isinstance(flags, list) else [],
        "model": r.get("model"),
        "size": r.get("size"),
        "quality": r.get("quality"),
        "created_at": r.get("created_at"),
    }
