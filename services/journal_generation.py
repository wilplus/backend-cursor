"""The journal CMS's two generators: a post's cover image (POST
/v2/internal/journal/image/generate) and its community formats (POST
/v2/internal/journal/community/generate).

Moved out of ``routes.journal`` unchanged (founder 2026-10-12). The routes
keep the admin-password gate and their feature switches; everything here
answers with a ``Refusal`` or the response body.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from services import journal as jr
from services.refusal import Refusal

logger = logging.getLogger(__name__)


def _invalid(error: str) -> Refusal:
    return Refusal("INVALID_INPUT", error, 400)


def _trimmed_id(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def attach_to_post(database, post: dict, image_url: str, alt_text: str):
    """Promote one candidate onto its post. (updated_post, error_message).

    Runs through the ordinary CMS validator, so a generated cover is held to
    the same https-only, length-capped contract as a pasted one. ``cover_alt``
    is OVERWRITTEN (alt text describes the image, and the image changed);
    ``cover_kind`` is left alone (on a video post the image is the poster).
    Returns the error as a message rather than raising: the image is already
    drawn, paid for and stored, so a failed attach must not discard it."""
    changes = {"cover_image_url": image_url}
    if (alt_text or "").strip():
        changes["cover_alt"] = alt_text
    try:
        validated = jr.validate_post_body(changes, partial=True, existing=post)
    except jr.JournalError as ve:
        return None, str(ve)
    if not validated:
        return None, "nothing to attach"
    row = database.update_journal_post(post.get("id"), validated)
    if not row or row == "DUPLICATE_SLUG":
        return None, "Could not save the cover on the post."
    return row, None


# ── the cover ───────────────────────────────────────────────────────────────

def _drawable_post(database, post_id: str) -> dict:
    post = database.get_journal_post_by_id(post_id)
    if not post:
        raise Refusal("NOT_FOUND", "post not found", 404)
    if not (post.get("title") or "").strip() \
            and not (post.get("body") or "").strip():
        raise _invalid("This post has no title or body yet — there is "
                       "nothing to draw from.")
    return post


def _previous_attempt(database, post_id: str, parent_id: str,
                      fresh: Any) -> Optional[dict]:
    """What this attempt refines. An explicit parent must belong to THIS
    post: briefing from another post's cover would cross the two."""
    if parent_id:
        previous = database.get_journal_post_image(parent_id)
        if not previous:
            raise Refusal("NOT_FOUND", "that image was not found", 404)
        if str(previous.get("journal_post_id")) != str(post_id):
            raise _invalid("parent_id: belongs to a different post")
        return previous
    if fresh:
        return None
    history = database.list_journal_post_images(post_id, limit=1)
    return history[0] if history else None


def _draw(ji, post, notes, previous, post_id) -> dict:
    try:
        return ji.generate_cover_image(post, notes=notes, previous=previous)
    except ji.ImageRejected as rejected:
        # The safety system refused the brief — the author can act on this.
        raise Refusal("IMAGE_REJECTED", str(rejected), 400) from rejected
    except ji.JournalImageError as ge:
        raise Refusal("V2_ERROR", str(ge), 503) from ge
    except Exception as e:  # pragma: no cover - defensive
        logger.error("journal_image_generate failed post=%s: %s", post_id, e,
                     exc_info=True)
        raise Refusal("V2_ERROR", "Could not draw the image right now.", 503) from e


def _store(result: dict, post_id: str) -> dict:
    try:
        from services.journal_media import JournalMediaError, put_bytes
        return put_bytes(data=result["image_bytes"],
                         content_type=result["content_type"])
    except JournalMediaError as me:
        # The image exists but there is nowhere to keep it; say which half
        # failed — "try again" is wrong advice for a missing bucket.
        logger.error("journal_image_generate: storage failed post=%s: %s",
                     post_id, me)
        raise Refusal("DISABLED", str(me), 503) from me
    except Exception as e:
        logger.error("journal_image_generate: storage failed post=%s: %s",
                     post_id, e, exc_info=True)
        raise Refusal("V2_ERROR", "Could not store the image.", 500) from e


def _recorded_image(database, ji, post_id, result, stored, notes, previous) -> dict:
    """The attempt as recorded; a missing history table (migration pending)
    must not lose the cover, so the in-memory shape serves instead."""
    row = database.insert_journal_post_image(ji.row_for_insert(
        post_id, result, image_url=stored["public_url"],
        storage_key=stored.get("key"), notes=notes,
        parent_id=(previous or {}).get("id"),
    ))
    if row:
        return ji.serialize_image(row)
    return ji.serialize_image({
        "journal_post_id": post_id,
        "image_url": stored["public_url"],
        "alt_text": result.get("alt_text"),
        "prompt": result.get("prompt"),
        "revised_prompt": result.get("revised_prompt"),
        "notes": notes if isinstance(notes, str) else "",
        "flags": result.get("flags"),
        "model": result.get("model"), "size": result.get("size"),
        "quality": result.get("quality"),
    })


def generate_cover(database, body: dict) -> dict:
    """Draw, store and record one cover attempt, attaching it unless asked
    not to; the response body. Raises ``Refusal``."""
    from services import journal_image as ji
    post_id = _trimmed_id(body.get("post_id"))
    if not post_id:
        raise _invalid("post_id: required")
    notes = body.get("notes")
    if notes is not None and not isinstance(notes, str):
        raise _invalid("notes: must be a string")
    parent_id = _trimmed_id(body.get("parent_id"))
    post = _drawable_post(database, post_id)
    previous = _previous_attempt(database, post_id, parent_id, body.get("fresh"))
    result = _draw(ji, post, notes, previous, post_id)
    stored = _store(result, post_id)
    image = _recorded_image(database, ji, post_id, result, stored, notes, previous)
    # null == absent == default TRUE (the null-vs-absent trap).
    attach = body.get("attach")
    attached, attach_error, updated = False, None, None
    if attach is None or attach:
        updated, attach_error = attach_to_post(
            database, post, image["image_url"], image["alt_text"])
        attached = updated is not None
    payload = {
        "image": image,
        "items": [ji.serialize_image(r) for r in
                  database.list_journal_post_images(post_id, limit=ji.MAX_HISTORY)],
        "post": jr.serialize_admin(updated) if updated else None,
        "attached": attached,
        "brief_source": result.get("brief_source"),
    }
    if attach_error:
        payload["attach_error"] = attach_error
    return payload


# ── the community formats ───────────────────────────────────────────────────

def _wanted_formats(cc, formats: Any) -> tuple:
    if formats is None:
        return cc.FORMATS
    if (isinstance(formats, list) and formats
            and all(f in cc.FORMATS for f in formats)):
        return tuple(dict.fromkeys(formats))
    raise _invalid(
        f"formats: must be a non-empty subset of {', '.join(cc.FORMATS)}")


def _derivable_post(database, post_id: str) -> dict:
    post = database.get_journal_post_by_id(post_id)
    if not post:
        raise Refusal("NOT_FOUND", "post not found", 404)
    if not (post.get("body") or "").strip():
        raise _invalid("This post has no body yet — there is nothing to "
                       "derive from.")
    return post


def generate_community(database, body: dict) -> dict:
    """Derive the community formats from one post; the FULL current set.
    A single-format reroll inherits the week's framing from a surviving
    sibling rather than re-theming the other two. Raises ``Refusal``."""
    post_id = _trimmed_id(body.get("post_id"))
    if not post_id:
        raise _invalid("post_id: required")
    from services import community_content as cc
    wanted = _wanted_formats(cc, body.get("formats"))
    notes = body.get("notes")
    if notes is not None and not isinstance(notes, str):
        raise _invalid("notes: must be a string")
    post = _derivable_post(database, post_id)
    try:
        payload = cc.generate_community_posts(post, formats=wanted, notes=notes)
    except Exception as e:  # pragma: no cover - the service swallows its own
        logger.error("journal_community_generate failed post=%s: %s",
                     post_id, e, exc_info=True)
        payload = None
    if not payload:
        raise Refusal("V2_ERROR", "Could not write the posts right now. Try again.", 503)
    existing = database.list_journal_community_posts(post_id)
    inherit = None
    if len(wanted) < len(cc.FORMATS):
        inherit = next((r for r in existing if r.get("kind") not in wanted), None)
    rows = cc.rows_for_upsert(post_id, payload, inherit=inherit)
    written = database.upsert_journal_community_posts(post_id, rows)
    if not written:
        raise Refusal("V2_ERROR", "Generated the posts but could not save them.", 500)
    items = database.list_journal_community_posts(post_id) or written
    return {"items": [cc.serialize_community_item(r) for r in items]}
