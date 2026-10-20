"""The coach's blind lines (founder 2026-10-01; migration 0411): the error
audit (6a, F6) and the block pick (8, C5-b), and V4's two sheets (0453).
Each lists this coach's pending items and takes one answer per item, once.
Nothing here says what the detector or the Manager chose. The work is
``services.error_presence_audit``, ``services.coach_block_pick`` and
``services.v4_coach_sheets``.

A LINE IS FILLED ONLY WHEN IT IS EMPTY (2026-10-14, the coach panel's 504s).
The panel reads all four lines each time the queue opens and again for fresh
audio links, and a fill walks up to 200 recent frames with a consent read
per Take: 25 to 77 database calls, four times over, on every open. A fill
already tops the line up to the week's cap, and answering an item does not
make room under it, so a line with items pending is served as it stands.
An empty line looks for new items at most once per `FILL_EVERY_SECONDS`
per coach (per worker: a second worker may look once more).
"""
from __future__ import annotations

import logging
from time import monotonic

import sentry_sdk
from flask import jsonify, request

from routes.admin import require_admin_or_coach, require_founder
from routes.v2.blueprint import v2_bp
from services.db import db

logger = logging.getLogger(__name__)


def _run(name: str, call):
    try:
        status, payload = call()
    except Exception as e:
        logger.error("%s failed: %s", name, e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Could not do that."}), 500
    return jsonify(payload), status


def _coach_id() -> str:
    return str(getattr(request, "user_id", "") or "")


#: How often one coach's empty line may look for new items.
FILL_EVERY_SECONDS = 15 * 60
_filled_at: dict[tuple[str, str], float] = {}


def _served(line: str, read, fill):
    """The line as it stands; filled first only when it is empty and has
    not looked for new items within `FILL_EVERY_SECONDS`."""
    status, payload = read()
    if status != 200 or payload.get("items"):
        return status, payload
    key = (line, _coach_id())
    now = monotonic()
    last = _filled_at.get(key)
    if last is not None and now - last < FILL_EVERY_SECONDS:
        return status, payload
    _filled_at[key] = now
    fill()
    return read()


@v2_bp.route("/coach/error-audit", methods=["GET"])
@require_admin_or_coach
def v2_coach_error_audit_queue():
    """This coach's pending blind error checks; an empty line is sampled
    up to the cap."""
    from services.error_presence_audit import queue, sample_for_coach
    return _run("error audit queue", lambda: _served(
        "error_audit",
        lambda: queue(db, coach_id=_coach_id()),
        lambda: sample_for_coach(db, coach_id=_coach_id())))


@v2_bp.route("/coach/error-audit/<audit_id>/answer", methods=["POST"])
@require_admin_or_coach
def v2_coach_error_audit_answer(audit_id):
    """Body {answer: yes | no | cant_tell}: one answer, once."""
    from services.error_presence_audit import answer
    return _run("error audit answer", lambda: answer(
        db, coach_id=_coach_id(), audit_id=str(audit_id),
        body=request.get_json(silent=True)))


@v2_bp.route("/coach/block-picks", methods=["GET"])
@require_admin_or_coach
def v2_coach_block_picks_queue():
    """This coach's pending block picks; an empty line is sampled up to
    the shared cap."""
    from services.coach_block_pick import queue, sample_for_coach
    from services.error_presence_audit import week_key
    return _run("block pick queue", lambda: _served(
        "block_pick",
        lambda: queue(db, coach_id=_coach_id()),
        lambda: sample_for_coach(db, coach_id=_coach_id(), week=week_key())))


@v2_bp.route("/coach/block-picks/<pick_id>/answer", methods=["POST"])
@require_admin_or_coach
def v2_coach_block_pick_answer(pick_id):
    """Body {pick_clip_id} or {cant_tell: true}: one pick, once."""
    from services.coach_block_pick import answer
    return _run("block pick answer", lambda: answer(
        db, coach_id=_coach_id(), pick_id=str(pick_id),
        body=request.get_json(silent=True)))


# ── The founder's ⋯ on a line (2026-10-20; migration 0482) ─────────────────

@v2_bp.route("/coach/blind/<line>/clear", methods=["POST"])
@require_founder
def v2_coach_clear_blind_line(line):
    """"Clear what's waiting": every item waiting on the founder's own line
    is cleared for the week (never shown again, never an answer); answers
    already given stay, and the line refills next week. ``line`` is one of
    error_audit, block_pick, v4_moment_pick, v4_surer. 200 {cleared: n} · 404."""
    from services.error_presence_audit import week_key
    if line not in db.BLIND_LINES:
        return jsonify({"code": "NOT_FOUND", "error": "No such line."}), 404
    return _run("clear blind line", lambda: (
        200, {"cleared": db.clear_blind_line(line, _coach_id(), week_key())}))


# ── V4's two blind sheets (B1.8, B1.9; S-B8 A; migration 0453) ────────────

@v2_bp.route("/coach/v4-moment-picks", methods=["GET"])
@require_admin_or_coach
def v2_coach_v4_moment_picks_queue():
    """"Pick the moment for feedback": this rater's pending blocks; an
    empty line is filled up to the week's cap. Words, audio, letters;
    nothing the machine chose."""
    from services.error_presence_audit import week_key
    from services.v4_coach_sheets import fill_pick_sheets, pick_queue
    return _run("v4 moment pick queue", lambda: _served(
        "v4_moment_pick",
        lambda: pick_queue(db, rater_id=_coach_id()),
        lambda: fill_pick_sheets(db, rater_id=_coach_id(), week=week_key())))


@v2_bp.route("/coach/v4-moment-picks/<sheet_id>/answer", methods=["POST"])
@require_admin_or_coach
def v2_coach_v4_moment_pick_answer(sheet_id):
    """Body {clip_id} or {none_needs_it: true}: one answer, once."""
    from services.v4_coach_sheets import pick_answer
    return _run("v4 moment pick answer", lambda: pick_answer(
        db, rater_id=_coach_id(), sheet_id=str(sheet_id),
        body=request.get_json(silent=True)))


@v2_bp.route("/coach/v4-surer-pairs", methods=["GET"])
@require_admin_or_coach
def v2_coach_v4_surer_pairs_queue():
    """"Which sounds surer": this rater's pending pairs; an empty line is
    filled up to the week's cap. Two texts only; never the slice or the
    level."""
    from services.error_presence_audit import week_key
    from services.v4_coach_sheets import fill_surer_sheets, surer_queue
    return _run("v4 surer queue", lambda: _served(
        "v4_surer",
        lambda: surer_queue(db, rater_id=_coach_id()),
        lambda: fill_surer_sheets(db, rater_id=_coach_id(), week=week_key())))


@v2_bp.route("/coach/v4-surer-pairs/<sheet_id>/answer", methods=["POST"])
@require_admin_or_coach
def v2_coach_v4_surer_pair_answer(sheet_id):
    """Body {answer: yes | no | cant_tell}: one answer, once."""
    from services.v4_coach_sheets import surer_answer
    return _run("v4 surer answer", lambda: surer_answer(
        db, rater_id=_coach_id(), sheet_id=str(sheet_id),
        body=request.get_json(silent=True)))
