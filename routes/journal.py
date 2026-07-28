"""Journal (blog) API — public reads + password-gated CMS (2026-07-25).

A self-contained blueprint (full paths baked in, like routes/dev_bugs.py) for
the public Journal on www.willpowerlab.com plus its in-house CMS. Nothing here
touches the record → transcribe → coach → read loop; the only table involved
is journal_post.

PUBLIC — no auth, no session, no token. The FE server-renders these with ISR,
so they must answer an anonymous request. Drafts are invisible on every public
path (an unknown slug and a draft slug both 404 — no existence leak).

  GET  /v2/journal/posts            ?category&q&sort&limit&offset
  GET  /v2/journal/posts/<slug>
  GET  /v2/journal/categories

ADMIN — the CMS. Password in the BODY (not a header) so the browser page can
send it from a form field; that is why every admin endpoint, including the
reads, is a POST. Mirrors the credits-admin pair in routes/internal_webhooks.py
(_credit_admin_ok): blank config ⇒ 503 DISABLED, mismatch ⇒ 401 Wrong password.
The password is compared with hmac.compare_digest and is never logged.

  POST /v2/internal/journal/posts/list | get | create | update | delete
  POST /v2/internal/journal/posts/publish | unpublish
  POST /v2/internal/journal/reorder
  POST /v2/internal/journal/media/presign

Auth note: this app has no blanket before_request — auth is per-route via
decorators — so "public" here simply means no decorator, and admin means the
explicit _journal_admin_ok() gate on the first line of the handler.
"""
from __future__ import annotations

import hmac
import logging
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

from config import Config as config
from services import journal as jr
from services.db import db

logger = logging.getLogger(__name__)

journal_bp = Blueprint("journal", __name__)


# ── admin gate ─────────────────────────────────────────────────────────────

def _journal_admin_ok():
    """(authorized, error_response). error_response is None when authorized.

    Same contract as internal_webhooks._credit_admin_ok — 503 when the
    password is unconfigured (the feature is off, not "wrong password"), 401
    on a mismatch — but compared in constant time.
    """
    pw = (getattr(config, "JOURNAL_ADMIN_PASSWORD", None) or "").strip()
    if not pw:
        return False, (jsonify({
            "code": "DISABLED",
            "error": "JOURNAL_ADMIN_PASSWORD not configured",
        }), 503)
    body = request.get_json(silent=True) or {}
    supplied = body.get("password")
    supplied = supplied.strip() if isinstance(supplied, str) else ""
    # Compare BYTES, not str: hmac.compare_digest raises TypeError on a str
    # containing any non-ASCII character, so an accented admin password — or a
    # probe sending one — would 500 instead of answering 401.
    if not hmac.compare_digest(supplied.encode("utf-8"), pw.encode("utf-8")):
        return False, (jsonify({
            "code": "UNAUTHORIZED", "error": "Wrong password",
        }), 401)
    return True, None


def _body() -> dict:
    return request.get_json(silent=True) or {}


def _post_id(body: dict) -> str:
    """The `id` field as a trimmed string, "" when absent or not a string.

    Explicitly type-guarded: `(body.get("id") or "").strip()` raises
    AttributeError on a numeric or list id, which would surface as a 500 where
    the contract promises 400.
    """
    raw = (body or {}).get("id")
    return raw.strip() if isinstance(raw, str) else ""


def _invalid(message: str, code: str = "INVALID_INPUT", status: int = 400):
    return jsonify({"code": code, "error": message}), status


# ── PUBLIC reads (no auth) ─────────────────────────────────────────────────

@journal_bp.route("/v2/journal/posts", methods=["GET"])
def journal_list_posts():
    """Published posts for the index. NO AUTH.

    200 { posts: [card...], total } — `total` counts every match, so the FE
    can page even though it filters in memory today.
    """
    try:
        category = (request.args.get("category") or "").strip().lower()
        if category in ("", "all"):
            category = None
        elif category not in jr.CATEGORIES:
            return _invalid(
                f"category: must be one of {', '.join(jr.CATEGORIES)}")
        search = (request.args.get("q") or "").strip() or None
        column, descending = jr.sort_key_for(request.args.get("sort"))
        limit = jr.clamp_limit(request.args.get("limit"))
        offset = jr.clamp_offset(request.args.get("offset"))

        rows = db.list_journal_posts(
            published_only=True, category=category, search=search,
            order_column=column, descending=descending,
            limit=limit, offset=offset,
        )
        total = db.count_journal_posts(
            published_only=True, category=category, search=search)
        return jsonify({
            "posts": [jr.serialize_card(r) for r in rows],
            "total": total,
        }), 200
    except Exception as e:
        logger.error("journal_list_posts failed: %s", e, exc_info=True)
        # Never 500 a public marketing page over a content query.
        return jsonify({"posts": [], "total": 0}), 200


@journal_bp.route("/v2/journal/posts/<slug>", methods=["GET"])
def journal_get_post(slug):
    """One published post by slug. NO AUTH.

    404 when the slug is unknown OR the post is a draft — identical answers,
    so a scraper cannot enumerate unpublished work.

    503 (not 404) when the DB itself is unreachable: the FE caches these
    responses with ISR, so answering "post not found" during a Supabase blip
    would take a live post off the site until the cache window expired.
    """
    try:
        row = db.get_journal_post_by_slug(slug, published_only=True,
                                          strict=True)
    except Exception as e:
        logger.error("journal_get_post failed slug=%s: %s", slug, e,
                     exc_info=True)
        return jsonify({"code": "UNAVAILABLE",
                        "error": "Failed to load the post"}), 503
    if not row:
        return jsonify({"code": "NOT_FOUND",
                        "error": "post not found"}), 404
    return jsonify(jr.serialize_post(row)), 200


@journal_bp.route("/v2/journal/categories", methods=["GET"])
def journal_categories():
    """Category keys + published counts. NO AUTH. Every category is listed
    (count 0 included) so the FE can render a stable chip row."""
    try:
        counts = db.journal_category_counts()
    except Exception as e:
        logger.warning("journal_categories failed: %s", e)
        counts = {}
    return jsonify({"categories": [
        {"key": key, "count": int(counts.get(key, 0))}
        for key in jr.CATEGORIES
    ]}), 200


# ── ADMIN (password in body; every route POST) ─────────────────────────────

@journal_bp.route("/v2/internal/journal/posts/list", methods=["POST"])
def journal_admin_list():
    """CMS list — ALL posts including drafts. Body { password, limit?, offset? }.

    Paged: this endpoint is the only way to learn a post's id, so without
    paging the 101st post would be permanently uneditable. `total` lets the
    CMS render the pager.
    200 { posts: [admin...], total } · 401 · 503"""
    ok, err = _journal_admin_ok()
    if not ok:
        return err
    body = _body()
    rows = db.list_journal_posts(
        published_only=False, order_column="sort_order", descending=False,
        # sort_order ASC, created_at DESC (FE amendment 2026-07-25). NOT
        # published_at: this list includes drafts, whose published_at is NULL,
        # and Postgres orders DESC as NULLS FIRST — undated drafts would float
        # above dated posts and the list would reshuffle as dates got set.
        # Every new post starts at sort_order=0, so this tiebreak IS the
        # visible order until the coach reorders.
        tiebreak_column="created_at",
        limit=jr.clamp_limit(body.get("limit")),
        offset=jr.clamp_offset(body.get("offset")),
    )
    return jsonify({
        "posts": [jr.serialize_admin(r) for r in rows],
        "total": db.count_journal_posts(published_only=False),
    }), 200


@journal_bp.route("/v2/internal/journal/posts/get", methods=["POST"])
def journal_admin_get():
    """One post for the editor. Body { password, id }.
    200 { post } · 400 · 401 · 404 · 503"""
    ok, err = _journal_admin_ok()
    if not ok:
        return err
    post_id = _post_id(_body())
    if not post_id:
        return _invalid("id: required")
    row = db.get_journal_post_by_id(post_id)
    if not row:
        return jsonify({"code": "NOT_FOUND", "error": "post not found"}), 404
    return jsonify({"post": jr.serialize_admin(row)}), 200


@journal_bp.route("/v2/internal/journal/posts/create", methods=["POST"])
def journal_admin_create():
    """Create a draft. Body { password, ...fields }.
    201 { post } · 400 · 401 · 409 · 500 · 503"""
    ok, err = _journal_admin_ok()
    if not ok:
        return err
    try:
        fields = jr.validate_post_body(_body(), partial=False)
    except jr.JournalError as ve:
        return _invalid(str(ve))
    row = db.create_journal_post(fields)
    if row == "DUPLICATE_SLUG":
        return _invalid(
            f"slug: \"{fields.get('slug')}\" is already taken",
            code="DUPLICATE_SLUG", status=409)
    if not row:
        return jsonify({"code": "V2_ERROR",
                        "error": "Could not create the post"}), 500
    return jsonify({"post": jr.serialize_admin(row)}), 201


@journal_bp.route("/v2/internal/journal/posts/update", methods=["POST"])
def journal_admin_update():
    """Update a post. Body { password, id, ...fields }. Only the keys present
    are written, so a save never blanks an untouched field.
    200 { post } · 400 · 401 · 404 · 409 · 500 · 503"""
    ok, err = _journal_admin_ok()
    if not ok:
        return err
    body = _body()
    post_id = _post_id(body)
    if not post_id:
        return _invalid("id: required")
    existing = db.get_journal_post_by_id(post_id)
    if not existing:
        return jsonify({"code": "NOT_FOUND", "error": "post not found"}), 404
    try:
        changes = jr.validate_post_body(body, partial=True, existing=existing)
        if not changes:
            return _invalid("no fields to update")
        # Check the invariant against the POST-SAVE view, so setting the kind
        # in one save and the media URL in another is allowed.
        jr.check_media_consistency({**existing, **changes})
    except jr.JournalError as ve:
        return _invalid(str(ve))
    row = db.update_journal_post(post_id, changes)
    if row == "DUPLICATE_SLUG":
        return _invalid(
            f"slug: \"{changes.get('slug')}\" is already taken",
            code="DUPLICATE_SLUG", status=409)
    if not row:
        return jsonify({"code": "V2_ERROR",
                        "error": "Could not save the post"}), 500
    return jsonify({"post": jr.serialize_admin(row)}), 200


@journal_bp.route("/v2/internal/journal/posts/delete", methods=["POST"])
def journal_admin_delete():
    """Delete a post. Body { password, id }. 200 { deleted } · 400 · 401 · 503"""
    ok, err = _journal_admin_ok()
    if not ok:
        return err
    post_id = _post_id(_body())
    if not post_id:
        return _invalid("id: required")
    return jsonify({"deleted": bool(db.delete_journal_post(post_id))}), 200


@journal_bp.route("/v2/internal/journal/posts/publish", methods=["POST"])
def journal_admin_publish():
    """Make a post public. Body { password, id }.

    Sets status=published, and stamps published_at ONLY when it is still null
    — the author-set display date is never overwritten (that is the whole
    point of keeping date and visibility independent).
    200 { post } · 400 · 401 · 404 · 503"""
    ok, err = _journal_admin_ok()
    if not ok:
        return err
    post_id = _post_id(_body())
    if not post_id:
        return _invalid("id: required")
    existing = db.get_journal_post_by_id(post_id)
    if not existing:
        return jsonify({"code": "NOT_FOUND", "error": "post not found"}), 404
    changes = {"status": "published"}
    if not existing.get("published_at"):
        changes["published_at"] = datetime.now(timezone.utc).isoformat()
    row = db.update_journal_post(post_id, changes)
    if not row or row == "DUPLICATE_SLUG":
        return jsonify({"code": "V2_ERROR",
                        "error": "Could not publish the post"}), 500
    return jsonify({"post": jr.serialize_admin(row)}), 200


@journal_bp.route("/v2/internal/journal/posts/unpublish", methods=["POST"])
def journal_admin_unpublish():
    """Hide a post. Body { password, id }. status=draft; published_at is KEPT
    so re-publishing restores the same display date.
    200 { post } · 400 · 401 · 404 · 503"""
    ok, err = _journal_admin_ok()
    if not ok:
        return err
    post_id = _post_id(_body())
    if not post_id:
        return _invalid("id: required")
    if not db.get_journal_post_by_id(post_id):
        return jsonify({"code": "NOT_FOUND", "error": "post not found"}), 404
    row = db.update_journal_post(post_id, {"status": "draft"})
    if not row or row == "DUPLICATE_SLUG":
        return jsonify({"code": "V2_ERROR",
                        "error": "Could not unpublish the post"}), 500
    return jsonify({"post": jr.serialize_admin(row)}), 200


@journal_bp.route("/v2/internal/journal/reorder", methods=["POST"])
def journal_admin_reorder():
    """Manual ordering for the `curated` sort. Body { password, ids: [...] }
    — sort_order becomes the array index. 200 { updated } · 400 · 401 · 503"""
    ok, err = _journal_admin_ok()
    if not ok:
        return err
    ids = _body().get("ids")
    if not isinstance(ids, list) or not ids:
        return _invalid("ids: must be a non-empty array of post ids")
    if len(ids) > 1000:
        return _invalid("ids: at most 1000 entries")
    if not all(isinstance(i, str) and i.strip() for i in ids):
        return _invalid("ids: every entry must be a post id string")
    return jsonify({"updated": db.reorder_journal_posts(ids)}), 200


@journal_bp.route("/v2/internal/journal/media/presign", methods=["POST"])
def journal_admin_presign():
    """Presigned direct-to-storage PUT for a cover file.
    Body { password, filename, content_type, kind }.

    The browser PUTs the bytes straight to R2 with the returned headers, then
    saves `public_url` on the post — the file never transits Flask or the
    Next BFF (Vercel's ~4.5MB body limit would 413 a video).
    200 { upload_url, public_url, key, headers, expires_in, max_bytes }
    400 · 401 · 503"""
    ok, err = _journal_admin_ok()
    if not ok:
        return err
    body = _body()
    kind = body.get("kind")
    content_type = body.get("content_type")
    try:
        from services.journal_media import presign_put, JournalMediaError
    except Exception as e:   # pragma: no cover - import guard
        logger.error("journal presign import failed: %s", e)
        return jsonify({"code": "DISABLED",
                        "error": "Media uploads are unavailable"}), 503
    try:
        out = presign_put(kind=kind, content_type=content_type,
                          filename=body.get("filename"))
    except JournalMediaError as me:
        # A misconfigured bucket is 503 (the feature is off); a bad kind or
        # content type is the author's 400.
        text = str(me)
        if "not configured" in text or "no public base URL" in text:
            return jsonify({"code": "DISABLED", "error": text}), 503
        return _invalid(text)
    except Exception as e:
        logger.error("journal presign failed: %s", e, exc_info=True)
        return jsonify({"code": "V2_ERROR",
                        "error": "Could not create the upload URL"}), 500
    return jsonify(out), 200


# ── COMMUNITY CONTENT STUDIO (founder 2026-07-26) ──────────────────────────
#
# One button in the CMS, under a post's body: derive the three OTHER community
# formats from this post. The journal post itself is format ① Technique; these
# routes own ② Myth-bust, ③ Fear, ④ Win.
#
# Same auth as every other CMS route — password in the body, POST only. These
# drafts are COMMUNITY-ONLY: nothing above in the PUBLIC section reads
# journal_community_post, and the rows carry no slug/status so they cannot be
# published to the site. The founder copies them into Skool by hand.

def _item_id(body: dict) -> str:
    """The `id` field as a trimmed string — same type-guard as _post_id."""
    raw = (body or {}).get("id")
    return raw.strip() if isinstance(raw, str) else ""


@journal_bp.route("/v2/internal/journal/community/generate", methods=["POST"])
def journal_community_generate():
    """Derive the community formats from one journal post.

    Body { password, post_id, formats?: [myth_bust|fear|win], notes? }.
    `formats` narrows the run to a single card's "Regenerate" — the siblings
    are left alone AND their batch-level fields (pillar, theme, the two app
    lines) are inherited, so a one-post reroll never re-themes the week.

    200 { items: [...] } — the FULL current set for the post, not just what
    was regenerated, so the CMS can render from one response.
    400 · 401 · 404 · 503 (flag off / no model output) · 500
    """
    ok, err = _journal_admin_ok()
    if not ok:
        return err
    if not getattr(config, "COMMUNITY_CONTENT_ENABLED", True):
        return jsonify({"code": "DISABLED",
                        "error": "The content studio is switched off"}), 503

    body = _body()
    post_id = (body.get("post_id") or "").strip() \
        if isinstance(body.get("post_id"), str) else ""
    if not post_id:
        return _invalid("post_id: required")

    from services import community_content as cc

    formats = body.get("formats")
    if formats is None:
        wanted = cc.FORMATS
    elif (isinstance(formats, list) and formats
            and all(f in cc.FORMATS for f in formats)):
        wanted = tuple(dict.fromkeys(formats))
    else:
        return _invalid(
            f"formats: must be a non-empty subset of {', '.join(cc.FORMATS)}")

    notes = body.get("notes")
    if notes is not None and not isinstance(notes, str):
        return _invalid("notes: must be a string")

    post = db.get_journal_post_by_id(post_id)
    if not post:
        return jsonify({"code": "NOT_FOUND", "error": "post not found"}), 404
    if not (post.get("body") or "").strip():
        return _invalid("This post has no body yet — there is nothing to "
                        "derive from.")

    try:
        payload = cc.generate_community_posts(post, formats=wanted,
                                              notes=notes)
    except Exception as e:  # pragma: no cover - the service swallows its own
        logger.error("journal_community_generate failed post=%s: %s",
                     post_id, e, exc_info=True)
        payload = None
    if not payload:
        return jsonify({
            "code": "V2_ERROR",
            "error": "Could not write the posts right now. Try again.",
        }), 503

    # Single-format reroll: inherit the week's framing from a surviving
    # sibling rather than letting one call re-theme the other two.
    inherit = None
    existing = db.list_journal_community_posts(post_id)
    if len(wanted) < len(cc.FORMATS):
        inherit = next((r for r in existing if r.get("kind") not in wanted),
                       None)

    rows = cc.rows_for_upsert(post_id, payload, inherit=inherit)
    written = db.upsert_journal_community_posts(post_id, rows)
    if not written:
        return jsonify({
            "code": "V2_ERROR",
            "error": "Generated the posts but could not save them.",
        }), 500

    items = db.list_journal_community_posts(post_id) or written
    return jsonify({
        "items": [cc.serialize_community_item(r) for r in items],
    }), 200


@journal_bp.route("/v2/internal/journal/community/list", methods=["POST"])
def journal_community_list():
    """Derived posts. Body { password, post_id? } — omit post_id for ALL of
    them (the CMS loads once and groups client-side). 200 { items } · 401 · 503"""
    ok, err = _journal_admin_ok()
    if not ok:
        return err
    from services import community_content as cc
    raw = _body().get("post_id")
    post_id = raw.strip() if isinstance(raw, str) else None
    rows = db.list_journal_community_posts(post_id or None)
    return jsonify({
        "items": [cc.serialize_community_item(r) for r in rows],
    }), 200


@journal_bp.route("/v2/internal/journal/community/update", methods=["POST"])
def journal_community_update():
    """The founder's manual edit. Body { password, id, title?, body? }.

    Editing CLEARS the flags: they exist to make him look at the draft, and
    he just has. Only title/body are writable — nothing here can turn a
    community draft into a journal post.
    200 { item } · 400 · 401 · 404 · 500 · 503"""
    ok, err = _journal_admin_ok()
    if not ok:
        return err
    from services import community_content as cc
    payload = _body()
    item_id = _item_id(payload)
    if not item_id:
        return _invalid("id: required")

    changes = {}
    if "title" in payload:
        if not isinstance(payload["title"], str):
            return _invalid("title: must be a string")
        changes["title"] = payload["title"].strip()[:120]
    if "body" in payload:
        if not isinstance(payload["body"], str):
            return _invalid("body: must be a string")
        changes["body"] = payload["body"].strip()[:2200]
    if not changes:
        return _invalid("no fields to update")

    if not db.get_journal_community_post(item_id):
        return jsonify({"code": "NOT_FOUND", "error": "post not found"}), 404
    changes["flags"] = []
    row = db.update_journal_community_post(item_id, changes)
    if not row:
        return jsonify({"code": "V2_ERROR",
                        "error": "Could not save the post"}), 500
    return jsonify({"item": cc.serialize_community_item(row)}), 200


@journal_bp.route("/v2/internal/journal/community/delete", methods=["POST"])
def journal_community_delete():
    """Delete one derived post. Body { password, id }.
    200 { deleted } · 400 · 401 · 503"""
    ok, err = _journal_admin_ok()
    if not ok:
        return err
    item_id = _item_id(_body())
    if not item_id:
        return _invalid("id: required")
    return jsonify(
        {"deleted": bool(db.delete_journal_community_post(item_id))}), 200


# ── GENERATED COVERS (founder 2026-07-28) ──────────────────────────────────
#
# "Draw a cover" next to a post, a notes box to steer it, and Regenerate. The
# model writes a brief from the post, draws it, and the file lands in the same
# R2 bucket an uploaded cover would (services/journal_image.py).
#
# Every attempt is KEPT (journal_post_image) so Regenerate is non-destructive
# and /image/select can promote an earlier one. cover_image_url on the post
# stays the single source of truth for what the site shows — a row here is a
# candidate until something attaches it.
#
# Same auth as every other CMS route. Nothing public reads these.

def _attach_to_post(post: dict, image_url: str, alt_text: str):
    """Promote one candidate onto its post. (updated_post, error_message).

    Runs through the ordinary CMS validator, so a generated cover is held to
    the same https-only, length-capped contract as a pasted one — the R2
    public base is configuration, and configuration can be wrong.

    ``cover_alt`` is OVERWRITTEN, not preserved: alt text describes the image,
    and the image just changed. Keeping the old sentence would leave the
    public page describing a cover that is no longer there.

    ``cover_kind`` is left alone on purpose — on a video post the image is the
    poster frame, and flipping the kind would drop the video.

    Returns the error as a message rather than raising: the image is already
    drawn, paid for and stored, so a failed attach must not discard it.
    """
    changes = {"cover_image_url": image_url}
    if (alt_text or "").strip():
        changes["cover_alt"] = alt_text
    try:
        validated = jr.validate_post_body(changes, partial=True,
                                          existing=post)
    except jr.JournalError as ve:
        return None, str(ve)
    if not validated:
        return None, "nothing to attach"
    row = db.update_journal_post(post.get("id"), validated)
    if not row or row == "DUPLICATE_SLUG":
        return None, "Could not save the cover on the post."
    return row, None


@journal_bp.route("/v2/internal/journal/image/generate", methods=["POST"])
def journal_image_generate():
    """Draw a cover image for one post.

    Body { password, post_id, notes?, parent_id?, fresh?, attach? }.

      notes      the steer for THIS attempt ("darker, no hands"). Applied to
                 the previous brief, so a note refines the cover on screen
                 rather than starting an unrelated one.
      parent_id  refine a specific earlier attempt. Defaults to the most
                 recent one for this post — which is what Regenerate wants.
      fresh      true ⇒ ignore the history and brief from the essay alone.
      attach     default TRUE — write the result onto the post's cover so the
                 button does the obvious thing. false ⇒ candidate only.

    200 { image, items, post, attached, attach_error? }
    400 (bad input, or the model refused the brief) · 401 · 404
    · 503 (switched off / storage unconfigured / draw failed — retryable)
    """
    ok, err = _journal_admin_ok()
    if not ok:
        return err

    from services import journal_image as ji

    if not ji.image_enabled():
        return jsonify({"code": "DISABLED",
                        "error": "Cover generation is switched off"}), 503

    body = _body()
    raw_post_id = body.get("post_id")
    post_id = raw_post_id.strip() if isinstance(raw_post_id, str) else ""
    if not post_id:
        return _invalid("post_id: required")

    notes = body.get("notes")
    if notes is not None and not isinstance(notes, str):
        return _invalid("notes: must be a string")
    parent_id = _item_id({"id": body.get("parent_id")})

    post = db.get_journal_post_by_id(post_id)
    if not post:
        return jsonify({"code": "NOT_FOUND", "error": "post not found"}), 404
    if not (post.get("title") or "").strip() \
            and not (post.get("body") or "").strip():
        return _invalid("This post has no title or body yet — there is "
                        "nothing to draw from.")

    # What this attempt refines. An explicit parent must belong to THIS post:
    # briefing from another post's cover would silently cross the two.
    previous = None
    if parent_id:
        previous = db.get_journal_post_image(parent_id)
        if not previous:
            return jsonify({"code": "NOT_FOUND",
                            "error": "that image was not found"}), 404
        if str(previous.get("journal_post_id")) != str(post_id):
            return _invalid("parent_id: belongs to a different post")
    elif not body.get("fresh"):
        history = db.list_journal_post_images(post_id, limit=1)
        previous = history[0] if history else None

    try:
        result = ji.generate_cover_image(post, notes=notes, previous=previous)
    except ji.ImageRejected as re_:
        # The safety system refused the brief — the author can act on this,
        # so it is a 400 with the reason, not an opaque retry.
        return jsonify({"code": "IMAGE_REJECTED", "error": str(re_)}), 400
    except ji.JournalImageError as ge:
        return jsonify({"code": "V2_ERROR", "error": str(ge)}), 503
    except Exception as e:  # pragma: no cover - defensive
        logger.error("journal_image_generate failed post=%s: %s", post_id, e,
                     exc_info=True)
        return jsonify({"code": "V2_ERROR",
                        "error": "Could not draw the image right now."}), 503

    try:
        from services.journal_media import put_bytes, JournalMediaError
        stored = put_bytes(data=result["image_bytes"],
                           content_type=result["content_type"])
    except JournalMediaError as me:
        # The image exists but we have nowhere to keep it. 503, and say which
        # half failed — "try again" is wrong advice for a missing bucket.
        logger.error("journal_image_generate: storage failed post=%s: %s",
                     post_id, me)
        return jsonify({"code": "DISABLED", "error": str(me)}), 503
    except Exception as e:
        logger.error("journal_image_generate: storage failed post=%s: %s",
                     post_id, e, exc_info=True)
        return jsonify({"code": "V2_ERROR",
                        "error": "Could not store the image."}), 500

    row = db.insert_journal_post_image(ji.row_for_insert(
        post_id, result, image_url=stored["public_url"],
        storage_key=stored.get("key"), notes=notes,
        parent_id=(previous or {}).get("id"),
    ))
    # A missing history table (migration pending) must not lose the cover the
    # founder just paid for: serve the in-memory shape and carry on.
    image = ji.serialize_image(row) if row else ji.serialize_image({
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

    # null == absent == default TRUE. A FE that serializes untouched optional
    # inputs as null would otherwise draw a cover and never attach it — the
    # same null-vs-absent trap validate_post_body already guards against.
    attach = body.get("attach")
    attached, attach_error, updated = False, None, None
    if attach is None or attach:
        updated, attach_error = _attach_to_post(
            post, image["image_url"], image["alt_text"])
        attached = updated is not None

    payload = {
        "image": image,
        "items": [ji.serialize_image(r)
                  for r in db.list_journal_post_images(post_id,
                                                       limit=ji.MAX_HISTORY)],
        "post": jr.serialize_admin(updated) if updated else None,
        "attached": attached,
        "brief_source": result.get("brief_source"),
    }
    if attach_error:
        payload["attach_error"] = attach_error
    return jsonify(payload), 200


@journal_bp.route("/v2/internal/journal/image/list", methods=["POST"])
def journal_image_list():
    """Cover attempts for one post, newest first.
    Body { password, post_id }. 200 { items } · 400 · 401 · 503"""
    ok, err = _journal_admin_ok()
    if not ok:
        return err
    from services import journal_image as ji
    raw = _body().get("post_id")
    post_id = raw.strip() if isinstance(raw, str) else ""
    if not post_id:
        return _invalid("post_id: required")
    rows = db.list_journal_post_images(post_id, limit=ji.MAX_HISTORY)
    return jsonify({"items": [ji.serialize_image(r) for r in rows]}), 200


@journal_bp.route("/v2/internal/journal/image/select", methods=["POST"])
def journal_image_select():
    """Promote one attempt to the post's cover — the undo for Regenerate.
    Body { password, id }.
    200 { post, image } · 400 · 401 · 404 · 500 · 503"""
    ok, err = _journal_admin_ok()
    if not ok:
        return err
    from services import journal_image as ji
    image_id = _item_id(_body())
    if not image_id:
        return _invalid("id: required")
    row = db.get_journal_post_image(image_id)
    if not row:
        return jsonify({"code": "NOT_FOUND",
                        "error": "that image was not found"}), 404
    post = db.get_journal_post_by_id(row.get("journal_post_id"))
    if not post:
        return jsonify({"code": "NOT_FOUND", "error": "post not found"}), 404

    updated, attach_error = _attach_to_post(
        post, row.get("image_url") or "", row.get("alt_text") or "")
    if attach_error:
        return jsonify({"code": "V2_ERROR", "error": attach_error}), 500
    return jsonify({"post": jr.serialize_admin(updated),
                    "image": ji.serialize_image(row)}), 200


@journal_bp.route("/v2/internal/journal/image/delete", methods=["POST"])
def journal_image_delete():
    """Drop one attempt from the strip. Body { password, id }.

    The stored file is left in R2 — the post may still point at it. This only
    clears the candidate from the CMS.
    200 { deleted } · 400 · 401 · 503"""
    ok, err = _journal_admin_ok()
    if not ok:
        return err
    image_id = _item_id(_body())
    if not image_id:
        return _invalid("id: required")
    return jsonify({"deleted": bool(db.delete_journal_post_image(image_id))}), 200
