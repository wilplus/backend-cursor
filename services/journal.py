"""Journal (blog) content — validation + serialization (founder 2026-07-25).

The pure layer under the Journal API: it owns the field contract so the
routes stay thin and the FE gets one stable JSON shape. No DB, no Flask, no
network — everything here is a pure function over dicts, which is why it is
also where the tests live.

Two structural decisions from the founder, enforced here:

  * `body` is PLAIN TEXT with blank-line-separated paragraphs. It is NOT
    HTML and NOT Markdown; the FE splits on /\\n\\s*\\n/ and renders <p>
    elements, never dangerouslySetInnerHTML. Because no HTML is stored there
    is no XSS surface to sanitize — but ``normalize_body`` still strips the
    control characters that would corrupt the paragraph split, and if the
    body format ever changes to allow markup THIS is the function that has
    to start sanitizing.
  * `published_at` is the author-supplied DISPLAY DATE; `status` is
    visibility. They are independent (a published post may be backdated) and
    neither is ever derived. `read_time_min` is likewise author-supplied —
    we do not count words.

Public surface:
  CATEGORIES / COVER_KINDS / STATUSES  — the allowed values (also the CHECK
      constraint values in migrations/add_journal_posts.sql).
  JournalError                         — validation failure, message is
      FE-renderable (routes 400 with it verbatim).
  slugify(text)                        — url-safe slug from a title.
  validate_post_body(body, partial)    — the CMS write contract.
  serialize_card(row) / serialize_post(row) — the two public read shapes.
  sort_key_for(sort)                   — maps the public `sort` param.
"""
from __future__ import annotations

import datetime as _datetime
import logging
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)


# Allowed values — kept in lockstep with the CHECK constraints in
# migrations/add_journal_posts.sql. The FE renders the category chips from
# this same list (All + these six).
CATEGORIES = (
    "physiology", "physical_exercise", "philosophy",
    "voice", "language", "others",
)
COVER_KINDS = ("image", "video", "audio")
STATUSES = ("draft", "published")
SORTS = ("newest", "oldest", "curated")

# Bounds. Generous compared with the intake-context tag fields — this is
# long-form editorial copy, not a label — but bounded so a paste accident
# can't write an unbounded row.
_MAX_SLUG_LEN = 200
_MAX_TITLE_LEN = 300
_MAX_EXCERPT_LEN = 1000
_MAX_BODY_LEN = 200_000
_MAX_URL_LEN = 2000
_MAX_ALT_LEN = 500
_MAX_AUTHOR_LEN = 200
_MAX_META_TITLE_LEN = 300
_MAX_META_DESC_LEN = 1000
_MIN_READ_TIME = 1
_MAX_READ_TIME = 600
_MAX_DURATION_SEC = 24 * 3600

# Public list paging.
DEFAULT_LIMIT = 50
MAX_LIMIT = 100

# Slug shape: lowercase alphanumerics + single dashes. Anchored, so this is
# also the validator for an author-typed slug.
_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

# Control characters that would corrupt the blank-line paragraph split (or
# smuggle a bidi/zero-width trick into rendered copy). \n and \t are kept.
_CONTROL_RE = re.compile(
    "["
    "\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f"   # C0 controls (\t \n kept)
    "\u200b-\u200f"                              # zero-width + LTR/RTL marks
    "\u2028\u2029"                              # line / paragraph separators
    "\u202a-\u202e"                              # bidi embedding + override
    "\ufeff"                                    # BOM / zero-width no-break space
    "]"
)


class JournalError(ValueError):
    """Validation error whose message is safe to show the CMS author.

    The route catches it and returns 400 INVALID_INPUT with the message
    verbatim — matching the IntakeContextError pattern used elsewhere.
    """


# ── field normalizers ──────────────────────────────────────────────────────

def _norm_text(value: Any, field: str, max_len: int,
               *, allow_empty: bool = True) -> Optional[str]:
    """Trim a string; empty-after-trim collapses to None. Bounded."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise JournalError(f"{field}: must be a string")
    cleaned = _CONTROL_RE.sub("", value).strip()
    if not cleaned:
        if allow_empty:
            return None
        raise JournalError(f"{field}: required")
    if len(cleaned) > max_len:
        raise JournalError(f"{field}: must be {max_len} characters or fewer")
    return cleaned


def _norm_int(value: Any, field: str, lo: int, hi: int) -> Optional[int]:
    """Integer in [lo, hi] or None. Bool rejected (bool-is-int in Python).
    A numeric string is accepted — the CMS sends form values as strings."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise JournalError(f"{field}: must be an integer")
    if isinstance(value, str):
        try:
            value = int(value.strip())
        except (TypeError, ValueError):
            raise JournalError(f"{field}: must be an integer") from None
    if not isinstance(value, int):
        raise JournalError(f"{field}: must be an integer")
    if not (lo <= value <= hi):
        raise JournalError(f"{field}: must be between {lo} and {hi}")
    return value


def _norm_choice(value: Any, field: str, allowed: tuple) -> Optional[str]:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise JournalError(f"{field}: must be a string")
    v = value.strip().lower()
    if v not in allowed:
        raise JournalError(f"{field}: must be one of {', '.join(allowed)}")
    return v


def _norm_url(value: Any, field: str) -> Optional[str]:
    """An https:// URL, or None.

    https-only on purpose: these URLs are rendered into <img>/<video>/<audio>
    src attributes on a public page, so http would be mixed content and a
    `javascript:`/`data:` scheme would be an injection vector even though the
    body itself carries no markup.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise JournalError(f"{field}: must be a string")
    # Same control/zero-width/bidi strip as every other stored string: these
    # land in a public page's src/href/meta attributes, so an embedded newline
    # or bidi override has no legitimate use here.
    v = _CONTROL_RE.sub("", value).strip()
    if not v:
        return None
    if len(v) > _MAX_URL_LEN:
        raise JournalError(f"{field}: too long")
    if not v.lower().startswith("https://"):
        raise JournalError(f"{field}: must be an https:// URL")
    # Whitespace anywhere inside a URL is either a typo or an attempt to hide
    # a second scheme; there is no valid unencoded space in a stored URL.
    if re.search(r"\s", v):
        raise JournalError(f"{field}: must not contain whitespace")
    return v


def _norm_timestamp(value: Any, field: str) -> Optional[str]:
    """Pass an ISO-8601 date/datetime through as a string, or None.

    Permissive about the TIME half (the CMS sends a plain `YYYY-MM-DD` from a
    date input; an edit round-trip sends back the full timestamptz), but the
    DATE half is really parsed — a shape-only check would accept `2026-13-45`,
    which Postgres then rejects on write, surfacing as an opaque 500 instead of
    telling the author their month is wrong.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise JournalError(f"{field}: must be an ISO-8601 date string")
    v = value.strip()
    if not v:
        return None
    if not re.match(r"^\d{4}-\d{2}-\d{2}([T ].*)?$", v):
        raise JournalError(
            f"{field}: must be an ISO-8601 date (YYYY-MM-DD)"
        )
    try:
        _datetime.date.fromisoformat(v[:10])
    except ValueError:
        raise JournalError(
            f"{field}: {v[:10]} is not a real calendar date"
        ) from None
    return v


def slugify(text: Any) -> str:
    """URL-safe slug from a title. ASCII-folds accents, lowercases, and
    collapses every run of non-alphanumerics to a single dash.

    Returns "" when nothing usable survives (e.g. a CJK-only or emoji-only
    title) — the caller decides what to do, because silently inventing a
    slug would produce an unguessable URL. The CMS defaults new drafts to
    `draft-<random>`, so "" surfaces as a validation error instead.
    """
    if not isinstance(text, str):
        return ""
    folded = unicodedata.normalize("NFKD", text)
    ascii_only = folded.encode("ascii", "ignore").decode("ascii")
    dashed = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_only).strip("-").lower()
    return dashed[:_MAX_SLUG_LEN].strip("-")


def normalize_body(value: Any) -> str:
    """The plain-text body, with the paragraph contract normalized.

    * CRLF/CR → LF, so the blank-line split behaves the same whatever the
      author's editor sent.
    * Control characters stripped (they would survive JSON and corrupt the
      split or smuggle bidi overrides into rendered copy).
    * Runs of 3+ newlines collapsed to exactly 2 — one blank line IS the
      paragraph separator, so more only creates empty <p> elements.

    No HTML is permitted or expected; nothing here escapes markup because
    nothing downstream interprets markup.
    """
    if value is None:
        return ""
    if not isinstance(value, str):
        raise JournalError("body: must be a string")
    text = value.replace("\r\n", "\n").replace("\r", "\n")
    text = _CONTROL_RE.sub("", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = text.strip()
    if len(text) > _MAX_BODY_LEN:
        raise JournalError(
            f"body: must be {_MAX_BODY_LEN} characters or fewer"
        )
    return text


def paragraphs(body: Any) -> list[str]:
    """The body split into paragraphs — the same split the FE performs.

    Not used by the API (the FE renders), but it is the executable
    definition of the paragraph contract and keeps the two sides honest.
    """
    if not isinstance(body, str) or not body.strip():
        return []
    return [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]


# ── the CMS write contract ────────────────────────────────────────────────

def validate_post_body(body: Any, *, partial: bool = False,
                       existing: Any = None) -> dict:
    """Validate a CMS create/update payload → the cleaned column dict.

    ``partial=True`` (update): only the keys actually present AND non-null are
    validated and returned, so a PATCH-style save never blanks a field the
    author did not touch. ``partial=False`` (create): `title` and `slug` are
    required and every column gets its default.

    ``existing`` (the stored row, update path) is consulted for one thing
    only: whether the post already has a `published_at`, so flipping status to
    published does not re-stamp a date the author set.

    Raises JournalError with an author-facing message. The `password` key is
    stripped here rather than at the route so it can never reach a column.
    """
    if not isinstance(body, dict):
        raise JournalError("Body must be a JSON object")

    src = {k: v for k, v in body.items()
           if k not in ("password", "id", "created_at", "updated_at")}

    # On a PARTIAL update, an explicit JSON null means "I am not touching this
    # field", NOT "reset it to the default". Dropping null keys here is what
    # makes that true for every field uniformly: without it, a CMS form object
    # that serializes untouched optional inputs as null would send
    # {"status": null} and silently unpublish a live post (and {"body": null}
    # would wipe it). On CREATE, null still resolves to the column default.
    if partial:
        src = {k: v for k, v in src.items() if v is not None}

    out: dict[str, Any] = {}

    def present(key: str) -> bool:
        return key in src

    # title FIRST: the slug can fall back to it, and validating title first
    # means a create that forgot the title says so, instead of blaming the
    # slug it could not derive.
    if present("title") or not partial:
        title = _norm_text(src.get("title"), "title", _MAX_TITLE_LEN,
                           allow_empty=partial)
        if not partial and not title:
            raise JournalError("title: required")
        if title is not None:
            out["title"] = title

    # slug — required on create; validated whenever supplied.
    if present("slug") or not partial:
        slug = _norm_text(src.get("slug"), "slug", _MAX_SLUG_LEN)
        if slug is None and not partial:
            # Fall back to the title so a create can omit the slug.
            slug = slugify(out.get("title")) or None
        if slug is None:
            raise JournalError("slug: required")
        slug = slug.lower()
        if not _SLUG_RE.match(slug):
            raise JournalError(
                "slug: use lowercase letters, numbers and single dashes"
            )
        out["slug"] = slug

    if present("excerpt") or not partial:
        out["excerpt"] = _norm_text(
            src.get("excerpt"), "excerpt", _MAX_EXCERPT_LEN) or ""

    if present("category") or not partial:
        out["category"] = _norm_choice(
            src.get("category"), "category", CATEGORIES) or "others"

    if present("read_time_min") or not partial:
        out["read_time_min"] = _norm_int(
            src.get("read_time_min"), "read_time_min",
            _MIN_READ_TIME, _MAX_READ_TIME) or _MIN_READ_TIME

    if present("cover_kind") or not partial:
        out["cover_kind"] = _norm_choice(
            src.get("cover_kind"), "cover_kind", COVER_KINDS) or "image"

    for key in ("cover_image_url", "media_url", "author_avatar_url",
                "og_image_url"):
        if present(key) or not partial:
            out[key] = _norm_url(src.get(key), key)

    if present("cover_alt") or not partial:
        out["cover_alt"] = _norm_text(
            src.get("cover_alt"), "cover_alt", _MAX_ALT_LEN)

    if present("media_duration_sec") or not partial:
        out["media_duration_sec"] = _norm_int(
            src.get("media_duration_sec"), "media_duration_sec",
            0, _MAX_DURATION_SEC)

    if present("body") or not partial:
        out["body"] = normalize_body(src.get("body"))

    if present("author_name") or not partial:
        out["author_name"] = _norm_text(
            src.get("author_name"), "author_name",
            _MAX_AUTHOR_LEN) or "Willpower Lab"

    if present("status") or not partial:
        out["status"] = _norm_choice(
            src.get("status"), "status", STATUSES) or "draft"

    if present("published_at"):
        out["published_at"] = _norm_timestamp(
            src.get("published_at"), "published_at")

    # A post that becomes published MUST carry a display date. The dedicated
    # publish route stamps one, but `status` is writable here too (the editor's
    # own status control), and a published row with published_at = NULL sorts
    # FIRST under Postgres's default NULLS FIRST on DESC — it would pin itself
    # to the top of the public index permanently. Stamp only when nothing else
    # supplies a date; an author-set date is never overwritten.
    if out.get("status") == "published" and not out.get("published_at"):
        if not (existing or {}).get("published_at"):
            out["published_at"] = datetime.now(timezone.utc).isoformat()

    if present("sort_order") or not partial:
        out["sort_order"] = _norm_int(
            src.get("sort_order"), "sort_order", -100_000, 100_000) or 0

    if present("meta_title") or not partial:
        out["meta_title"] = _norm_text(
            src.get("meta_title"), "meta_title", _MAX_META_TITLE_LEN)

    if present("meta_description") or not partial:
        out["meta_description"] = _norm_text(
            src.get("meta_description"), "meta_description",
            _MAX_META_DESC_LEN)

    # A video/audio cover with no media file has nothing to play. Checked
    # against the MERGED view on a partial update (the caller passes the
    # stored row via `existing`) — here we only catch the self-contained case.
    kind = out.get("cover_kind")
    if kind in ("video", "audio") and not partial and not out.get("media_url"):
        raise JournalError(
            f"media_url: required when cover_kind is {kind}"
        )

    return out


def check_media_consistency(merged: dict) -> None:
    """Post-merge invariant: a video/audio cover needs a media_url.

    Called by the update path with {**stored_row, **changes} so setting the
    kind in one save and the URL in another is allowed, while *saving* a row
    that ends up video-without-media is not.
    """
    kind = (merged or {}).get("cover_kind")
    if kind in ("video", "audio") and not (merged or {}).get("media_url"):
        raise JournalError(
            f"media_url: required when cover_kind is {kind}"
        )


# ── public read shapes ────────────────────────────────────────────────────

_CARD_FIELDS = (
    "slug", "title", "excerpt", "category", "read_time_min",
    "cover_kind", "cover_image_url", "cover_alt", "media_duration_sec",
    "published_at", "sort_order",
)

# The full post adds the body + the media file + author + SEO overrides.
_POST_EXTRA_FIELDS = (
    "body", "media_url", "author_name", "author_avatar_url",
    "meta_title", "meta_description", "og_image_url",
)


def serialize_card(row: Any) -> dict:
    """The index-card shape. Never leaks `body`, `status`, or internal ids."""
    r = row if isinstance(row, dict) else {}
    return {key: r.get(key) for key in _CARD_FIELDS}


def serialize_post(row: Any) -> dict:
    """The full public post shape (card fields + body/media/author/SEO).

    Still omits `id` and `status` — a public reader has no use for either,
    and `status` leaking would tell a scraper that drafts exist.
    """
    r = row if isinstance(row, dict) else {}
    out = serialize_card(r)
    out.update({key: r.get(key) for key in _POST_EXTRA_FIELDS})
    return out


def serialize_admin(row: Any) -> dict:
    """The CMS shape — everything, including `id` and `status`."""
    r = row if isinstance(row, dict) else {}
    out = serialize_post(r)
    out.update({
        "id": r.get("id"),
        "status": r.get("status"),
        "created_at": r.get("created_at"),
        "updated_at": r.get("updated_at"),
    })
    return out


def sort_key_for(sort: Any) -> tuple[str, bool]:
    """Map the public `sort` param → (column, descending).

    newest (default) → published_at desc · oldest → published_at asc ·
    curated → sort_order asc (the CMS's manual order; the DB layer applies
    published_at desc as the tiebreak).
    """
    s = (sort or "").strip().lower() if isinstance(sort, str) else ""
    if s == "oldest":
        return ("published_at", False)
    if s == "curated":
        return ("sort_order", False)
    return ("published_at", True)


def clamp_limit(value: Any) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return DEFAULT_LIMIT
    return max(1, min(n, MAX_LIMIT))


def clamp_offset(value: Any) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, n)
