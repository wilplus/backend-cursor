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
