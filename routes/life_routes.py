"""The Life Panel API — /v2/life/* (founder-directed, 2026-07-26).

Spec of record: PROMPT-life-panel.md · build prompt: PROMPT-BE-life-panel.md

Its own blueprint with full paths baked in (the house pattern from
routes/journal.py and routes/dev_bugs.py). The ONLY edit outside this file is
the blueprint registration in app.py — v2_routes.py is not touched by this
module.

The three-tier gate (§1.4), and why each answer is the code it is
──────────────────────────────────────────────────────────────────
  flag off              → 404 on every route. Not 503, not "coming soon": with
                          LIFE_PANEL_ENABLED=0 the feature does not exist, and
                          the menu payload is unchanged from today.
  not consented         → 409 + a pointer to the Principles tab, on everything
                          except /state, /consent and the setup endpoints —
                          those are how you BECOME consented, so gating them
                          would be a locked door with the key inside.
  not on the allowlist  → 404, never 403. A 403 confirms the surface exists;
                          the founder-only entries are absent from the payload
                          and their endpoints deny that they were ever there.

The allowlist covers the prayer link and founder-only surfaces ONLY. The
principles engine is PUBLIC behind consent (L-6).

BE-10's launch blockers are in this file and not in a follow-up: consent
recording, self-serve export, and a hard delete that reports what it actually
removed. The founder chose no staged rollout, so there is no soft launch in
which to add them later.
"""
from __future__ import annotations

import difflib
import logging
import os
from datetime import date, datetime, timezone
from functools import wraps
from typing import Optional

from flask import Blueprint, jsonify, make_response, request

from auth import require_auth
from config import Config as config
from services import life_chat as chat
from services import life_engine as engine
from services import life_import as importer
from services import life_panel as lp
# Delivery is fenced into services/life_reminders (the ONE sanctioned sender,
# founder 2026-07-30). This module exposes the user-initiated SETTINGS only —
# it never imports the push library and never sends; test_life_panel.py
# asserts both.
from services import life_reminders as reminders
from services import life_store as store
from services.context_document import (SUPPORTED_UPLOAD_EXTENSIONS,
                                       extract_document_text)

logger = logging.getLogger(__name__)

life_bp = Blueprint("life", __name__)


# ═════════════════════════════════════════════════════════════════════════
# Gates
# ═════════════════════════════════════════════════════════════════════════

def _not_found():
    """The answer for "this does not exist" AND for "this exists but is not
    yours". Identical on purpose — see the module docstring."""
    return jsonify({"code": "NOT_FOUND", "error": "Not found"}), 404


def _needs_consent():
    return jsonify({
        "code": "CONSENT_REQUIRED",
        "error": "Open the Principles tab and read the consent screen first.",
        "pointer": "/panel/principles",
    }), 409


def _invalid(message: str, code: str = "INVALID_INPUT", status: int = 400):
    return jsonify({"code": code, "error": message}), status


def life_route(*, consent: bool = True, allowlist: bool = False):
    """Auth + the three-tier gate, in that order.

    ``consent=False`` is for the endpoints that exist to GET consent.
    ``allowlist=True`` marks a founder-only surface — 404 to everyone else.
    """
    def decorator(fn):
        @wraps(fn)
        @require_auth
        def wrapper(*args, **kwargs):
            if not chat.is_enabled():
                return _not_found()
            user_id = str(request.user_id)
            if allowlist and not chat.is_allowlisted(user_id):
                return _not_found()
            if consent and not chat.has_consented(user_id):
                return _needs_consent()
            try:
                return fn(*args, **kwargs)
            except lp.LifeError as ve:
                return _invalid(str(ve))
            except Exception as e:
                logger.error("life route %s failed: %s", fn.__name__, e,
                             exc_info=True)
                return jsonify({"code": "V2_ERROR",
                                "error": "Request failed"}), 500
        return wrapper
    return decorator


def _body() -> dict:
    return request.get_json(silent=True) or {}


def _uid() -> str:
    return str(request.user_id)


def _with_warrants(user_id: str, rows: list) -> list:
    """Serialize proposals WITH the principle that warrants each one.

    The single place proposals become JSON, and it exists because there were
    two and only one of them remembered. L-2 requires every proposed change to
    display one of the user's own principles as its justification, and the FE
    DROPS a proposal that arrives without one — correctly, since there is no
    compliant way to render a bare proposal. So a serializer that forgets the
    warrant does not look like a bug: the proposal simply never appears.

    That is what had happened to the weekly review, which is the entire
    delivery mechanism for the L-2b queue — the ranked batch of three arrived
    warrant-less and would have been discarded on sight.

    Warrants are looked up once per call and shared, so a batch citing the
    same principle three times costs one read."""
    warrants: dict = {}
    for row in rows:
        wid = row.get("warrant_principle_id")
        if wid and wid not in warrants:
            warrants[wid] = store.get_item(user_id, str(wid))
    return [
        lp.serialize_proposal(
            row, warrant=warrants.get(row.get("warrant_principle_id")))
        for row in rows
    ]


def _clamp(value, default: int, hi: int) -> int:
    """A page size. At least 1 — a limit of 0 is a request for nothing, which
    is never what the caller meant."""
    try:
        return max(1, min(hi, int(value)))
    except (TypeError, ValueError):
        return default


def _offset(value) -> int:
    """A row offset. Zero-based and clamped at 0 — deliberately NOT run
    through _clamp, whose floor of 1 would silently skip the first row of
    every unpaged list."""
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


# ═════════════════════════════════════════════════════════════════════════
# State + consent + setup
# ═════════════════════════════════════════════════════════════════════════

@life_bp.route("/v2/life/state", methods=["GET"])
@life_route(consent=False)
def life_state():
    """What the panel shell needs to render itself.

    Consent is NOT required here — this is the call that tells the FE to show
    the consent screen. Founder-only entries are ABSENT from `menu` for
    everyone else rather than present-and-disabled: a disabled entry is a
    discovery.

    ── The activation model (founder 2026-07-26) ────────────────────────────
    Completing the onboarding IS the membership test. There is no separate
    roster: the hamburger shows ONE entry — Principles — to everyone, and
    finishing consent + goal-setting is what opens the rest.

    That is not a policy choice dressed as a gate. It is a precondition:
    `compare_to_strategy` answers `no_strategy` without the documents setup
    generates, retrieval has nothing to retrieve without principles, and the
    daily card has no goals to rank. A user let in early would meet a feature
    that silently does nothing and conclude it is broken.

    The order is fixed and cannot be rearranged: explainer → CONSENT → form.
    The form itself collects life data (the anchor, eight horizons of personal
    goals), so consent has to precede it. "Activate by finishing onboarding"
    must never become "collect first, ask after".

    `active` is the single field the FE gates the menu on."""
    user_id = _uid()
    version = getattr(config, "LIFE_PANEL_CONSENT_VERSION", "1.0")
    consented = chat.has_consented(user_id)
    setup = store.get_setup(user_id) if consented else None
    complete = bool((setup or {}).get("completed_at"))
    active = bool(consented and complete)

    # Before activation the panel is one door, not nine empty rooms.
    menu = ["principles"]
    if active:
        menu = ["principles", "wins", "phrases", "today", "goals", "timeline",
                "distractions", "strategy", "notes"]
        # Prayer stays OFF (founder 2026-07-26). The allowlist is empty by
        # default, so this appends nothing until someone is explicitly added —
        # and pompeiana.willpowerlab.com keeps working signed-out regardless,
        # which is the whole point of it staying a separate app.
        if chat.is_allowlisted(user_id):
            menu.append("prayer")

    answers = (setup or {}).get("answers") or {}
    return jsonify({
        # ── the onboarding state machine (FE contract) ───────────────────
        # Nested because these two drive WHICH SCREEN to show, and the flat
        # fields below drive what to render once you are through. Keeping the
        # two jobs apart is what stops the FE deriving the menu from consent
        # state and getting the allowlist wrong.
        #
        # `required_version` is an OPAQUE TOKEN, not a date. It is whatever
        # LIFE_PANEL_CONSENT_VERSION says — "1.0" by default. Compare it for
        # equality; never parse it. A copy change that ships as "1.1" or
        # "2026-08-02" must not break the comparison.
        "consent": {
            "required_version": version,
            "accepted_version": version if consented else None,
        },
        "setup": {
            "complete": complete,
            "started": bool(setup),
            "resume_step": answers.get("_step"),
        },
        # ── what to render ───────────────────────────────────────────────
        # `menu` stays SERVER-OWNED and is the authority. The eight standard
        # tabs are derivable from `active`, but an allowlisted entry is not:
        # deriving it FE-side would mean shipping allowlist membership as a
        # boolean the client could flip, and a 404-not-403 surface must not
        # announce itself in a payload.
        "active": active,
        "menu": menu,
        # The `#` picker is only useful once the engine will actually run.
        "tags": lp.tag_suggestions() if active else [],

        # Flat aliases, kept for the callers already on them. Same values,
        # never computed twice — read from the same locals as the objects
        # above, so the two shapes cannot drift.
        "consented": consented,
        "consent_version": version,
        "setup_started": bool(setup),
        "setup_complete": complete,
    }), 200


@life_bp.route("/v2/life/consent", methods=["POST"])
@life_route(consent=False)
def life_consent():
    """Record acceptance of the consent screen (L-6). Body ``{version}``.

    The version must match the one currently in force: accepting "1.0" when
    the copy has moved to "2.0" would record agreement to text the user was
    never shown."""
    required = getattr(config, "LIFE_PANEL_CONSENT_VERSION", "1.0")
    supplied = (_body().get("version") or "").strip()
    if supplied and supplied != required:
        return _invalid(f"version: must be {required}", code="STALE_CONSENT")
    row = store.record_consent(
        _uid(), version=required,
        # The acceptance record, and nothing else. Never used for analytics,
        # geolocation, or anything a second feature might want it for.
        ip=(request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
            or request.remote_addr or None),
    )
    if not row:
        return jsonify({"code": "V2_ERROR",
                        "error": "Could not record consent"}), 500
    # Without this the user who just accepted keeps being treated as a
    # non-participant until the cache expires — they would finish the consent
    # screen and find the feature still inert.
    chat.invalidate_consent(_uid())
    return jsonify({"consented": True, "version": required}), 200


@life_bp.route("/v2/life/setup", methods=["GET"])
@life_route()
def life_setup_get():
    """Partial answers, for save-and-resume."""
    row = store.get_setup(_uid()) or {}
    answers = row.get("answers") or {}
    return jsonify({
        "answers": answers,
        "complete": bool(row.get("completed_at")),
        # Which step to reopen on. Stored rather than inferred from which
        # answers exist: the founder can skip a horizon and come back to it,
        # so "the first unanswered one" is not the same as "where they were".
        "resume_step": answers.get("_step"),
    }), 200


@life_bp.route("/v2/life/setup", methods=["PUT"])
@life_route()
def life_setup_put():
    """Upsert partial answers. Called on every step, not only at the end —
    eight horizons is long enough that people get interrupted, and without
    resume an interruption is an abandonment."""
    body = _body()
    answers = body.get("answers")
    if not isinstance(answers, dict):
        return _invalid("answers: must be an object")
    # `step` rides inside the answers blob rather than getting its own column:
    # it is FE-owned form state, and the FE owns what a step IS. A column
    # would freeze that shape into the schema and need a migration the first
    # time a horizon is split in two.
    if "step" in body:
        step = body.get("step")
        if step is not None and not isinstance(step, (str, int)):
            return _invalid("step: must be a string, a number, or null")
        answers = {**answers, "_step": step}
    row = store.upsert_setup(_uid(), answers)
    if not row:
        return jsonify({"code": "V2_ERROR",
                        "error": "Could not save"}), 500
    saved = row.get("answers") or {}
    return jsonify({"answers": saved,
                    "resume_step": saved.get("_step")}), 200


@life_bp.route("/v2/life/setup/complete", methods=["POST"])
@life_route()
def life_setup_complete():
    """Generate the document set from the user's own answers, then replay any
    notes they typed before the gate let them in."""
    user_id = _uid()
    if not (store.get_setup(user_id) or {}).get("answers"):
        return _invalid("setup: answer the form before completing it")
    result = engine.complete_setup_and_generate(user_id)
    return jsonify({
        "horizons": result.get("horizons") or [],
        "replayed": len(result.get("replayed") or []),
        "replayed_notes": result.get("replayed") or [],
    }), 200


# ═════════════════════════════════════════════════════════════════════════
# Setup strategy-document upload (founder-approved item 9, 2026-07-30)
# ═════════════════════════════════════════════════════════════════════════

_SETUP_DOCUMENT_MAX_MB = 15
_SETUP_DOCUMENT_MAX_BYTES = _SETUP_DOCUMENT_MAX_MB * 1024 * 1024


def _serialize_setup_document(row: dict) -> dict:
    """Metadata only. extracted_text NEVER rides a response — it re-enters
    the product only as generation context and as the user's own export."""
    return {
        "id": str(row.get("id") or ""),
        "file_name": row.get("file_name"),
        "status": row.get("status"),
        "char_count": int(row.get("char_count") or 0),
        "created_at": row.get("created_at"),
    }


@life_bp.route("/v2/life/setup/document", methods=["POST"])
@life_route()
def life_setup_document_upload():
    """Multipart ``file`` → extracted text stored, binary discarded.

    OPTIONAL by design (founder 2026-07-30): setup completes identically with
    zero uploads, and an upload alone changes nothing the user sees until
    they ask to draft from it. Extraction is best-effort and never raises
    (services/context_document.py); a document nothing could be read from is
    kept as ``extraction_failed`` so the FE can SAY so instead of silently
    behaving as if nothing was uploaded."""
    file = request.files.get("file")
    if file is None:
        return _invalid("file: multipart field required")
    filename = (file.filename or "").strip()
    ext = os.path.splitext(filename.lower())[1]
    if ext not in SUPPORTED_UPLOAD_EXTENSIONS:
        return _invalid(
            "file: must be one of " + ", ".join(SUPPORTED_UPLOAD_EXTENSIONS))
    # Same two-step size check as the lab audio upload: refuse on the declared
    # length, then refuse again on the actual bytes — a Content-Length is a
    # claim, not a fact.
    if (request.content_length or 0) > _SETUP_DOCUMENT_MAX_BYTES:
        return jsonify({"code": "PAYLOAD_TOO_LARGE",
                        "error": f"exceeds {_SETUP_DOCUMENT_MAX_MB}MB"}), 413
    data = file.read(_SETUP_DOCUMENT_MAX_BYTES + 1)
    if len(data) > _SETUP_DOCUMENT_MAX_BYTES:
        return jsonify({"code": "PAYLOAD_TOO_LARGE",
                        "error": f"exceeds {_SETUP_DOCUMENT_MAX_MB}MB"}), 413
    if not data:
        return _invalid("file: is empty")

    extracted = extract_document_text(data, content_type=file.mimetype,
                                      filename=filename)
    text = extracted.get("text") or ""
    row = importer.insert_setup_document(
        _uid(),
        file_name=filename,
        mime_type=file.mimetype or "",
        extracted_text=text,
        char_count=len(text),
        status="processed" if text else "extraction_failed",
    )
    if not row:
        return jsonify({"code": "V2_ERROR",
                        "error": "Could not save the document"}), 500
    return jsonify({"document": _serialize_setup_document(row)}), 201


@life_bp.route("/v2/life/setup/documents", methods=["GET"])
@life_route()
def life_setup_documents_list():
    rows = importer.list_setup_documents(_uid())
    return jsonify({"documents":
                    [_serialize_setup_document(r) for r in rows]}), 200


@life_bp.route("/v2/life/setup/propose-from-document", methods=["POST"])
@life_route()
def life_setup_propose_from_document():
    """DRAFT rows from the uploaded document. WRITES NOTHING.

    The founder's line: drafting from the document is offered, never
    forced-automatic. This endpoint returns rows for the review UI and stops;
    creation happens only in /setup/apply-proposed with exactly the rows the
    user ticked (N5).

    ``kind`` (optional) is the panel view the user was standing on when they
    handed the document over — one of the closed nine. It scopes a second
    read of the same text; it does NOT filter what comes back, and omitting
    it is the original call, not a degraded one. Absent a document id, the
    newest PROCESSED upload is the one read: a later upload nothing could be
    extracted from never shadows a good one."""
    body = _body()
    document_id = body.get("document_id")
    if document_id is not None and not isinstance(document_id, str):
        return _invalid("document_id: must be an id string or null")
    kind = body.get("kind")
    if kind is not None and not isinstance(kind, str):
        return _invalid(f"kind: must be one of {', '.join(lp.ITEM_KINDS)}")
    kind = (kind or "").strip() or None
    # Validated against the SAME closed nine the panel renders. An unknown
    # kind is refused rather than ignored: a tenth kind is an FE change, so a
    # backend that quietly accepted one would be drafting rows nothing on the
    # other side can display.
    if kind and kind not in lp.ITEM_KINDS:
        return _invalid(f"kind: must be one of {', '.join(lp.ITEM_KINDS)}")
    doc = importer.get_setup_document(_uid(), (document_id or "").strip()
                                      or None)
    if not doc or doc.get("status") != "processed" \
            or not (doc.get("extracted_text") or "").strip():
        return _invalid("document: nothing readable to draft from",
                        code="NO_DOCUMENT")
    items, outcome = engine.draft_items_from_document_ex(
        _uid(), doc["extracted_text"], kind=kind)
    return jsonify({
        "document": _serialize_setup_document(doc),
        "items": items,
        # Echoed so the caller can see the hint arrived and was honoured —
        # null when none was sent.
        "kind": kind,
        # Stated on the wire so no reader can mistake a draft for a write.
        "written": False,
        # Whether the READ worked, which is not the same question as whether
        # the document held anything. False means we fell over — ran out of
        # room, could not reach the model, could not parse it — and the short
        # `items` list is OUR failure, not a fact about what the person wrote.
        #
        # Without this the FE cannot tell the two apart and has to pick one
        # message for both, which is how a 19,787-character goals document got
        # answered with "nothing that reads as a goal came out of that
        # document". That copy is NOT changed here: user-facing wording is
        # held for founder sign-off. This is the signal it needs when it is.
        "extraction_ok": outcome not in engine.FAILED_OUTCOMES,
    }), 200


def _insert_ticked_item(user_id: str, fields: dict) -> Optional[dict]:
    """Create ONE ticked row, degrading rather than losing it.

    THE ROW IS THE JOB. Two of the fields written here arrive with their own
    migration, and "on main" is not "run in prod":

      * ``origin_document_id`` — migrations/add_life_items_origin_document.sql
      * ``horizon = "week"``   — migrations/add_life_items_week_horizon.sql

    Against a database where either has not run, the insert is REJECTED, and
    ``store.insert_item`` swallows the error and returns None — so a row the
    person read on a screen and individually ticked would simply vanish, with
    a 201 and a shorter ``created`` list as the only trace. The "week" case is
    the sharper one: it is a CHECK constraint, so it fails the whole write
    rather than one field.

    So each rung drops the newest, least essential thing and tries again,
    most-complete first, and the first row that lands wins:

      1. everything
      2. without the provenance stamp    (stamp column not migrated)
      3. week downgraded to NULL horizon (week constraint not migrated)
      4. both                            (neither migrated)

    A downgraded horizon costs the weekly screen its pre-fill — the row lands
    in the FE's remainder review, which is exactly where it landed before
    "week" existed. Never a DIFFERENT horizon: putting a weekly goal on the
    daily screen would be the system inventing a due date the person did not
    write, and a wrong screen is worse than an un-filled one.

    ``insert_item`` cannot tell us WHY it failed, so the ladder is best-effort
    by construction. A genuine outage fails all four rungs and the row is
    skipped, exactly as it is today."""
    row = store.insert_item(user_id, fields)
    if row is not None:
        return row

    stamped = "origin_document_id" in fields
    weekly = fields.get("horizon") == "week"

    if stamped:
        row = store.insert_item(
            user_id, {k: v for k, v in fields.items()
                      if k != "origin_document_id"})
        if row is not None:
            logger.warning("life: apply-proposed created a row without its "
                           "provenance stamp; run "
                           "migrations/add_life_items_origin_document.sql")
            return row

    if weekly:
        downgraded = {**fields, "horizon": None}
        row = store.insert_item(user_id, downgraded)
        if row is None and stamped:
            downgraded.pop("origin_document_id")
            row = store.insert_item(user_id, downgraded)
        if row is not None:
            logger.warning("life: apply-proposed downgraded a week horizon to "
                           "the remainder review; run "
                           "migrations/add_life_items_week_horizon.sql")
    return row


@life_bp.route("/v2/life/setup/apply-proposed", methods=["POST"])
@life_route()
def life_setup_apply_proposed():
    """Create ONLY the rows the user ticked in the review UI.

    N5 as restated by the founder for this flow: the tick is the explicit
    approve, made on a fully displayed row — so a ticked row is created
    ACTIVE, an unticked row is never sent and never created, and nothing
    lands as a silent 'proposed'. ``sanitize_confirmed_item`` forces the
    status and keeps a bet's rank LOCKED (L-2a) regardless of what the
    client sent. It accepts exactly the kinds ``propose`` can emit
    (``importer.DOC_DRAFT_KINDS``) — the two disagreeing would be a dead end
    the user cannot act on.

    PROVENANCE. A row created here came out of a document the person wrote
    and then ticked on a screen: it has no ``origin_case_id`` (no `#mistake`
    case derived it) and no ``origin_note_id`` (nobody typed it into the
    chat). Send the ``document_id`` that was drafted from and every created
    row carries it in ``origin_document_id``, so a principle read out of a
    file stays tellable-apart from one the engine derived. It is OPTIONAL and
    resolved, never guessed — an id we cannot resolve costs the stamp and
    nothing else, because the rows are the job and the provenance is not."""
    body = _body()
    raw_items = body.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        return _invalid("items: must be a non-empty list")
    if len(raw_items) > 200:
        return _invalid("items: at most 200 per request")
    document_id = body.get("document_id")
    if document_id is not None and not isinstance(document_id, str):
        return _invalid("document_id: must be an id string or null")
    document_id = (document_id or "").strip() or None
    origin_document_id = None
    if document_id:
        doc = importer.get_setup_document(_uid(), document_id)
        if doc:
            origin_document_id = str(doc.get("id") or "") or None
        else:
            # Deleted between drafting and ticking, or never theirs. Losing
            # the rows over a provenance field would be the wrong trade.
            logger.warning("life: apply-proposed could not resolve the "
                           "document it was told to stamp")
    created = []
    for raw in raw_items:
        fields = importer.sanitize_confirmed_item(raw)
        if not fields:
            continue
        if origin_document_id:
            fields["origin_document_id"] = origin_document_id
        row = _insert_ticked_item(_uid(), fields)
        if row:
            created.append(lp.serialize_item(row))
    return jsonify({"created": created, "count": len(created)}), 201


# ═════════════════════════════════════════════════════════════════════════
# Strategy + proposals
# ═════════════════════════════════════════════════════════════════════════

@life_bp.route("/v2/life/strategy", methods=["GET"])
@life_route()
def life_strategy():
    """Every horizon at its current version."""
    latest = store.latest_strategy(_uid())
    return jsonify({
        "documents": {h: lp.serialize_strategy(r) for h, r in latest.items()},
        "horizons": list(lp.STRATEGY_HORIZONS),
    }), 200


def _assemble(latest: dict) -> str:
    """The document set as ONE document, in horizon order."""
    parts = []
    for horizon in lp.STRATEGY_HORIZONS:
        row = latest.get(horizon)
        if row:
            parts.append(f"# {horizon}\n\n{(row.get('body') or '').strip()}")
    return "\n\n".join(parts)


@life_bp.route("/v2/life/strategy/download", methods=["GET"])
@life_route()
def life_strategy_download():
    """The strategy as a document (story #11, founder 2026-07-27).

    ?format=json (DEFAULT — the original payload, so existing callers are
    untouched) · md · pdf · docx. A file format returns the bytes as an
    attachment; a renderer whose dependency is missing degrades to markdown
    with a 200, so the download button can never 500 (same contract as
    services/dev_tasks.py::export_pdf). Read the response Content-Type — do
    not assume the requested one.
    """
    latest = store.latest_strategy(_uid())
    fmt = (request.args.get("format") or "json").strip().lower()
    if fmt in ("md", "pdf", "docx"):
        from services.strategy_export import export
        payload, mimetype, filename = export(
            latest, lp.STRATEGY_HORIZONS, fmt)
        resp = make_response(payload)
        resp.headers["Content-Type"] = mimetype
        resp.headers["Content-Disposition"] = \
            f'attachment; filename="{filename}"'
        return resp, 200
    return jsonify({
        "body": _assemble(latest),
        "versions": {h: int(r.get("version") or 1) for h, r in latest.items()},
    }), 200


@life_bp.route("/v2/life/strategy/upload", methods=["POST"])
@life_route()
def life_strategy_upload():
    """Returns a DIFF. Never writes — not one row, not one field.

    §6.2: a re-upload produces a diff you approve, never a silent overwrite.
    Arbitrary Word formatting reconciled back into structured sections will
    not round-trip cleanly, and the diff is the safety net for exactly that:
    a mangled section shows up as a visible deletion instead of quietly
    replacing four years of work."""
    body = _body()
    documents = body.get("documents")
    if not isinstance(documents, dict):
        raw = body.get("body")
        if not isinstance(raw, str) or not raw.strip():
            return _invalid("documents: object of {horizon: text}, or body: text")
        documents = _split_uploaded(raw)

    latest = store.latest_strategy(_uid())
    diffs: dict[str, list[str]] = {}
    for horizon, text in documents.items():
        key = str(horizon).strip().lower()
        if key not in lp.STRATEGY_HORIZONS or not isinstance(text, str):
            continue
        current = (latest.get(key) or {}).get("body") or ""
        if current.strip() == text.strip():
            continue
        diffs[key] = list(difflib.unified_diff(
            current.splitlines(), text.splitlines(),
            fromfile=f"{key} (current)", tofile=f"{key} (uploaded)",
            lineterm="", n=2,
        ))
    return jsonify({"diffs": diffs, "written": False}), 200


def _split_uploaded(raw: str) -> dict:
    """One assembled document → per-horizon bodies, on the ``# <horizon>``
    headings /download writes. Anything before the first heading is dropped
    rather than guessed at — an unlabelled block has no home."""
    out: dict[str, list[str]] = {}
    current = None
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            candidate = stripped[2:].strip().lower()
            if candidate in lp.STRATEGY_HORIZONS:
                current = candidate
                out.setdefault(current, [])
                continue
        if current:
            out[current].append(line)
    return {h: "\n".join(lines).strip() for h, lines in out.items()}


@life_bp.route("/v2/life/proposals", methods=["GET"])
@life_route()
def life_proposals():
    """Today's surfaced proposal + the weekly batch of three.

    Not in the BE-2 endpoint list, but the L-2b budget is meaningless without
    a read: something has to show the founder the one surfaced change and the
    ranked three. `queued_total` is reported rather than hidden — "here are
    your three" reads as "that was everything" when the remainder is
    invisible, and silent truncation is how a backlog becomes a surprise."""
    user_id = _uid()
    store.expire_stale_proposals(user_id)
    surfaced = store.list_proposals(user_id, status="surfaced",
                                    kind="strategy")
    queued = store.list_proposals(user_id, status="queued", kind="strategy")
    batch = lp.weekly_batch(queued)

    return jsonify({
        "surfaced": _with_warrants(user_id, surfaced),
        "weekly_batch": _with_warrants(user_id, batch),
        "queued_total": len(queued),
        "queued_held_back": max(0, len(queued) - len(batch)),
    }), 200


@life_bp.route("/v2/life/proposals/<proposal_id>/approve", methods=["POST"])
@life_route()
def life_proposal_approve(proposal_id):
    """Apply a proposed change and bump the horizon's version.

    Refuses the immutable core here as well as at creation: "never proposed
    against" has to hold on the WRITE path too, not only on the path that
    happens to be in front of it (L-2a)."""
    user_id = _uid()
    row = store.get_proposal(user_id, proposal_id)
    if not row:
        return _not_found()
    if row.get("status") in ("approved", "dismissed", "expired"):
        return _invalid(f"proposal is already {row.get('status')}",
                        code="ALREADY_DECIDED", status=409)
    if row.get("kind") == "retire":
        return _invalid("use /principles/<id>/retire for a retire decision")
    if lp.is_immutable_target(row.get("target")):
        return _invalid(
            "That section is hand-edited only — nothing is applied here.",
            code="IMMUTABLE_CORE", status=409)
    written = engine.apply_proposal(user_id, row)
    if not written:
        return jsonify({"code": "V2_ERROR",
                        "error": "Could not apply the change"}), 500
    return jsonify({"applied": True,
                    "strategy": lp.serialize_strategy(written)}), 200


@life_bp.route("/v2/life/proposals/<proposal_id>/dismiss", methods=["POST"])
@life_route()
def life_proposal_dismiss(proposal_id):
    """Dismissed proposals are REMEMBERED, not deleted — so the same change is
    not proposed again next week from the same evidence."""
    user_id = _uid()
    row = store.get_proposal(user_id, proposal_id)
    if not row:
        return _not_found()
    store.update_proposal(user_id, proposal_id, {
        "status": "dismissed",
        "decided_at": datetime.now(timezone.utc).isoformat(),
    })
    return jsonify({"dismissed": True}), 200


# ═════════════════════════════════════════════════════════════════════════
# Principles + cases
# ═════════════════════════════════════════════════════════════════════════

@life_bp.route("/v2/life/principles", methods=["GET"])
@life_route()
def life_principles():
    """``?q=`` retrieves the ~10 relevant ones; no q lists the archive.

    A `q` NEVER returns the whole corpus — that is the retrieval contract the
    privacy fence rests on, and it is also what makes the answer useful."""
    user_id = _uid()
    q = (request.args.get("q") or "").strip()
    limit = _clamp(request.args.get("limit"), engine.RETRIEVAL_LIMIT, 500)
    if q:
        rows = engine.retrieve_principles(user_id, q, limit=limit)
    else:
        rows = store.principles(user_id, limit=limit)
    counts = store.application_counts(user_id)
    out = []
    for row in rows:
        item = lp.serialize_item(row)
        # L-5's payoff, and the one number in the payload: how many times the
        # founder's own archive cited this principle. It is a count of their
        # own actions, not a score anything assigned them.
        item["applications"] = int(counts.get(str(row.get("id")), 0))
        out.append(item)
    return jsonify({"principles": out, "total": len(out)}), 200


@life_bp.route("/v2/life/principles/<item_id>", methods=["GET"])
@life_route()
def life_principle_detail(item_id):
    """The principle + the case it came from + its application log."""
    user_id = _uid()
    row = store.get_item(user_id, item_id)
    if not row or row.get("kind") != "principle":
        return _not_found()
    case = None
    if row.get("origin_case_id"):
        case_row = store.get_case(user_id, str(row["origin_case_id"]))
        case = lp.serialize_case(case_row) if case_row else None
    applications = store.applications_for(user_id, item_id)
    return jsonify({
        "principle": lp.serialize_item(row),
        "case": case,
        "applications": [
            {"context": a.get("context"), "at": a.get("created_at")}
            for a in applications
        ],
    }), 200


@life_bp.route("/v2/life/principles/<item_id>/retire", methods=["POST"])
@life_route()
def life_principle_retire(item_id):
    """``{retires_id, decision}`` — the veto is absolute.

    ``decision`` is "yes" or "no". On "no" BOTH stay active and the decision is
    PERSISTED, so the question is never asked again (L-3 / BE-7). Re-asking a
    settled veto is how a system wears someone down into an answer they
    already declined to give."""
    user_id = _uid()
    body = _body()
    new_principle = store.get_item(user_id, item_id)
    old_id = (body.get("retires_id") or "").strip() \
        if isinstance(body.get("retires_id"), str) else ""
    decision = (body.get("decision") or "").strip().lower()
    if not new_principle or new_principle.get("kind") != "principle":
        return _not_found()
    if not old_id:
        return _invalid("retires_id: required")
    if decision not in ("yes", "no"):
        return _invalid("decision: must be 'yes' or 'no'")
    old = store.get_item(user_id, old_id)
    if not old or old.get("kind") != "principle":
        return _not_found()

    store.insert_proposal(user_id, {
        "kind": "retire",
        "target": old_id,
        "proposed": item_id,
        "current": old.get("title") or "",
        "status": "approved" if decision == "yes" else "dismissed",
        "decided_at": datetime.now(timezone.utc).isoformat(),
    })
    if decision == "yes":
        store.update_item(user_id, old_id, {"status": "retired"})
    return jsonify({
        "retired": decision == "yes",
        # Both stay active on "no" — said explicitly so the FE cannot render
        # a half-state that implies the old one is on its way out.
        "both_active": decision == "no",
    }), 200


@life_bp.route("/v2/life/cases", methods=["GET"])
@life_route()
def life_cases_list():
    user_id = _uid()
    rows = store.list_cases(
        user_id,
        limit=_clamp(request.args.get("limit"), 100, 500),
        offset=_offset(request.args.get("offset")),
        needs_review=(request.args.get("needs_review") or "").lower()
        in ("1", "true", "yes"),
    )
    return jsonify({"cases": [lp.serialize_case(r) for r in rows]}), 200


@life_bp.route("/v2/life/cases", methods=["POST"])
@life_route()
def life_case_create():
    """Create a case from the founder's own text.

    N5 / L-1: ``reflections`` comes from THIS request body and from nowhere
    else. ``validate_case_input`` is the only writer of that field in the
    codebase — no model output reaches it, on this path or any other."""
    user_id = _uid()
    fields = lp.validate_case_input(_body(), partial=False)
    derived = engine.derive_case(
        user_id, fields.get("case_at_hand") or "",
        reflections=fields.get("reflections") or "")
    row = store.insert_case(user_id, {
        **fields,
        # The model's categories are a PROPOSAL and land in the proposal
        # column. `category` stays whatever the founder supplied.
        "category_proposed": derived.get("category") or [],
        "status": "draft",
    })
    if not row:
        return jsonify({"code": "V2_ERROR",
                        "error": "Could not save the case"}), 500

    engine.log_case_applications(user_id, str(row.get("id")),
                                 derived.get("principles") or [])

    proposed_principle = None
    if derived.get("new_principle"):
        proposed_principle = store.insert_item(user_id, {
            "kind": "principle",
            "title": derived["new_principle"],
            "body": derived["new_principle"],
            # Propose, never commit. It is not part of the archive — and is
            # not retrievable as one — until it is approved.
            "status": "proposed",
            "origin_case_id": row.get("id"),
            "order_key": lp.next_order_key(store.principles(user_id)),
        })

    return jsonify({
        "case": lp.serialize_case(row),
        "proposed_principle": (lp.serialize_item(proposed_principle)
                               if proposed_principle else None),
        "applied_principles": [lp.serialize_item(p)
                               for p in (derived.get("principles") or [])],
        "conflicts": [
            [lp.serialize_item(a), lp.serialize_item(b)]
            for a, b in (derived.get("conflicts") or [])
        ],
    }), 201


@life_bp.route("/v2/life/cases/<case_id>", methods=["GET"])
@life_route()
def life_case_detail(case_id):
    user_id = _uid()
    row = store.get_case(user_id, case_id)
    if not row:
        return _not_found()
    return jsonify({"case": lp.serialize_case(
        row, principles=store.items_for_case(user_id, case_id))}), 200


@life_bp.route("/v2/life/cases/<case_id>", methods=["PATCH"])
@life_route()
def life_case_update(case_id):
    """Approve the derivation, or correct the case.

    Approving is what moves a proposed category onto ``category`` and a
    proposed principle into the archive: nothing crosses that line without
    this call."""
    user_id = _uid()
    existing = store.get_case(user_id, case_id)
    if not existing:
        return _not_found()
    body = _body()
    # `approve` alone is a complete request — it is the whole point of this
    # endpoint. Running it through validate_case_input would raise "no fields
    # to update" and make the approve button 400.
    editable = {k: v for k, v in body.items() if k != "approve"}
    fields = lp.validate_case_input(editable, partial=True) if editable else {}
    retire_prompt = None
    if body.get("approve") is True:
        fields["status"] = "active"
        if "category" not in fields and existing.get("category_proposed"):
            fields["category"] = lp.normalize_categories(
                existing["category_proposed"])
        for item in store.items_for_case(user_id, case_id):
            if item.get("status") != "proposed":
                continue
            activated = store.update_item(user_id, str(item["id"]),
                                          {"status": "active"}) or item
            # BE-7's retire question, asked at the only moment it makes sense:
            # a principle has just ENTERED the archive, so "does this replace
            # one already in it?" is answerable. Asked once — a pair the
            # founder already answered `no` on is never raised again, and
            # retire_candidate skips those.
            if retire_prompt is None:
                retire_prompt = _retire_prompt(user_id, activated)
    row = store.update_case(user_id, case_id, fields)
    return jsonify({
        "case": lp.serialize_case(row or existing),
        # null on almost every approval. A prompt here is the system ASKING,
        # never announcing — the veto is absolute and nothing is retired until
        # POST /principles/<id>/retire says so.
        "retire_prompt": retire_prompt,
    }), 200


def _retire_prompt(user_id: str, new_principle: dict):
    """``{question, retires: {...}, number}`` when a newly approved principle
    looks like it supersedes an existing one — otherwise None.

    `number` is the candidate's 1-based position in the founder's own ordered
    list, because the copy asks "does this retire #12?" and #12 has to mean
    the twelfth thing they see."""
    candidate = engine.retire_candidate(user_id, new_principle)
    if not candidate:
        return None
    ordered = store.principles(user_id)
    number = next(
        (i + 1 for i, p in enumerate(ordered)
         if str(p.get("id")) == str(candidate.get("id"))), None)
    return {
        "question": chat.COPY["retire_question"].format(
            n=number if number is not None else "?"),
        "retires": lp.serialize_item(candidate),
        "number": number,
    }


# ═════════════════════════════════════════════════════════════════════════
# Items · goals · timeline
# ═════════════════════════════════════════════════════════════════════════

@life_bp.route("/v2/life/goals", methods=["GET"])
@life_route()
def life_goals():
    """FE-9 — the three bets in LOCKED rank order, each with its goals.

    The FE has called this since the Goals view shipped: it is in that file's
    own contract header ("GET /v2/life/goals — bets in rank order, goals
    beneath"). Nothing on this side ever answered it, so the view 404'd and
    rendered its error state — which read as "the panel lost my goals" the
    moment apply-proposed had visibly created them (2026-08-01 screenshot:
    "Added. They are in your panel now." over "That did not load.").

    The groups come from ``lp.BETS``, not from the seeded bet rows: the rank
    is immutable core (L-2a), so the response's ORDER must not depend on what
    is in the table. All three groups are always present, empty or not — the
    three bets are the screen's skeleton ("Three bets, in order. The order is
    the point."), not a search result.

    A goal whose ``collection`` names no bet rides in ``ungrouped`` rather
    than being dropped server-side: the wire must not lose rows the user
    ticked, even while today's FE renders only the three groups. The label is
    echoed for completeness, but the FE deliberately prefers its own name for
    a key it knows — a rename must not show the new word in setup and an old
    one here."""
    user_id = _uid()
    grouped: dict[str, list[dict]] = {}
    ungrouped: list[dict] = []
    bet_keys = {bet["key"] for bet in lp.BETS}
    # One read, already in order_key order — the draft order the rows were
    # created in, which is the document's own order for applied drafts.
    for row in store.list_items(user_id, kind="goal", status="active"):
        key = (row.get("collection") or "").strip().lower()
        target = grouped.setdefault(key, []) if key in bet_keys else ungrouped
        target.append(lp.serialize_item(row))
    return jsonify({
        "bets": [{
            "key": bet["key"],
            "rank": bet["rank"],
            "label": f"{bet['emoji']} {bet['title']}",
            "goals": grouped.get(bet["key"], []),
        } for bet in lp.BETS],
        "ungrouped": ungrouped,
    }), 200


@life_bp.route("/v2/life/items", methods=["GET"])
@life_route()
def life_items_list():
    kind = (request.args.get("kind") or "").strip() or None
    if kind and kind not in lp.ITEM_KINDS:
        return _invalid(f"kind: must be one of {', '.join(lp.ITEM_KINDS)}")
    rows = store.list_items(
        _uid(), kind=kind,
        status=(request.args.get("status") or "").strip() or None,
        collection=(request.args.get("collection") or "").strip() or None,
        limit=_clamp(request.args.get("limit"), 500, 2000),
    )
    return jsonify({"items": [lp.serialize_item(r) for r in rows]}), 200


@life_bp.route("/v2/life/items", methods=["POST"])
@life_route()
def life_item_create():
    user_id = _uid()
    fields = lp.validate_item_input(_body(), partial=False)
    if "order_key" not in fields:
        fields["order_key"] = lp.next_order_key(
            store.list_items(user_id, kind=fields.get("kind")))
    # DELIBERATELY NOT _insert_ticked_item. That helper degrades a "week"
    # horizon to NULL when the migration has not run, which is the right trade
    # for apply-proposed — there the horizon was inferred by a model reading a
    # document, and the row is what the person actually ticked. Here the person
    # CHOSE "week" on a form. Quietly saving it with no horizon would be the
    # panel overruling an explicit choice and not saying so; failing the save
    # tells them, and their input is still on the screen.
    row = store.insert_item(user_id, fields)
    if not row:
        return jsonify({"code": "V2_ERROR",
                        "error": "Could not save"}), 500
    return jsonify({"item": lp.serialize_item(row)}), 201


@life_bp.route("/v2/life/items/<item_id>", methods=["PATCH"])
@life_route()
def life_item_update(item_id):
    user_id = _uid()
    if not store.get_item(user_id, item_id):
        return _not_found()
    row = store.update_item(user_id, item_id,
                            lp.validate_item_input(_body(), partial=True))
    if not row:
        return jsonify({"code": "V2_ERROR", "error": "Could not save"}), 500
    return jsonify({"item": lp.serialize_item(row)}), 200


@life_bp.route("/v2/life/items/<item_id>", methods=["DELETE"])
@life_route()
def life_item_delete(item_id):
    if not store.get_item(_uid(), item_id):
        return _not_found()
    return jsonify({"deleted": store.delete_item(_uid(), item_id)}), 200


@life_bp.route("/v2/life/timeline", methods=["GET"])
@life_route()
def life_timeline():
    """Events + goals that carry a parsed date, plus the bets as colour bands.

    A goal whose ``due_label`` did not parse is returned in `undated` rather
    than being dropped or given a made-up date: the label is the source of
    truth, and a marker in the wrong year reads as a fact."""
    user_id = _uid()
    events = store.list_items(user_id, kind="event", status="active")
    goals = store.list_items(user_id, kind="goal", status="active")
    bets = store.list_items(user_id, kind="bet", status="active")
    dated = [g for g in goals if g.get("due_at")]
    undated = [g for g in goals if not g.get("due_at")]
    return jsonify({
        "events": [lp.serialize_item(e) for e in events],
        "goals": [lp.serialize_item(g) for g in dated],
        "undated": [lp.serialize_item(g) for g in undated],
        "bets": [lp.serialize_item(b) for b in bets],
    }), 200


# ═════════════════════════════════════════════════════════════════════════
# Day + week
# ═════════════════════════════════════════════════════════════════════════

@life_bp.route("/v2/life/day", methods=["GET"])
@life_route()
def life_day():
    """The daily card. Generated on first read if the 05:00 cron has not run.

    Generation on read is what makes the cron an OPTIMISATION rather than a
    dependency: if it never fires, the card exists the moment the panel is
    opened. Nothing is sent either way — generation is scheduled, delivery is
    not (L-4)."""
    user_id = _uid()
    raw = (request.args.get("date") or "").strip()
    if raw:
        try:
            target = date.fromisoformat(raw[:10])
        except ValueError:
            return _invalid("date: must be YYYY-MM-DD")
        row = store.get_day(user_id, target.isoformat())
    else:
        row = engine.ensure_daily_card(user_id)
    if not row:
        return jsonify({"day": None}), 200
    # The evening pass, if it is late enough. Same generate-on-read fallback
    # as the morning card, so the 23:00 cron is an optimisation rather than a
    # dependency — but gated on the hour, because stamping evening.generated_at
    # early would open the evening section on a card the founder opened at
    # breakfast.
    row = engine.ensure_evening_pass(
        user_id, date.fromisoformat(str(row.get("day"))[:10])) or row
    return jsonify({"day": lp.serialize_day(row)}), 200


@life_bp.route("/v2/life/day/<day_id>", methods=["PATCH"])
@life_route()
def life_day_update(day_id):
    """Checkbox ticks and the editable content of the card.

    The FRAME is fixed: ``one_thing`` can be changed, but it cannot be removed
    — there is always a one thing for the day, and blanking it is how the card
    quietly becomes optional."""
    user_id = _uid()
    body = _body()
    allowed = ("morning_checks", "one_thing", "focus_blocks",
               "distraction_flagged", "evening_habits_ran",
               "evening_one_thing", "evening_distraction", "evening_line",
               "edit_why")
    fields = {k: body[k] for k in allowed if k in body}
    if not fields:
        return _invalid("no fields to update")
    if "one_thing" in fields and not str(fields["one_thing"] or "").strip():
        return _invalid("one_thing: cannot be blank — change it, don't remove it")
    row = store.update_day(user_id, day_id, fields)
    if not row:
        return _not_found()
    return jsonify({"day": lp.serialize_day(row)}), 200


@life_bp.route("/v2/life/week", methods=["GET"])
@life_route()
def life_week_get():
    user_id = _uid()
    raw = (request.args.get("week_start") or "").strip()
    try:
        target = (date.fromisoformat(raw[:10]) if raw
                  else lp.week_start_for(datetime.now(timezone.utc).date()))
    except ValueError:
        return _invalid("week_start: must be YYYY-MM-DD")
    week_start = lp.week_start_for(target)
    row = store.get_week(user_id, week_start.isoformat())
    queued = store.list_proposals(user_id, status="queued", kind="strategy")
    return jsonify({
        "week": lp.serialize_week(row) if row else
        {"week_start": week_start.isoformat()},
        # The weekly review is where the queued proposals arrive as a ranked
        # batch of three (L-2b).
        "proposals": _with_warrants(user_id, lp.weekly_batch(queued)),
        "queued_held_back": max(0, len(queued) - lp.WEEKLY_BATCH_SIZE),
        "untagged_notes": [lp.serialize_note(n) for n in
                           store.list_notes(user_id, limit=20,
                                            untagged_only=True)],
    }), 200


@life_bp.route("/v2/life/week", methods=["POST"])
@life_route()
def life_week_post():
    user_id = _uid()
    body = _body()
    raw = (body.get("week_start") or "").strip()
    try:
        target = (date.fromisoformat(raw[:10]) if raw
                  else lp.week_start_for(datetime.now(timezone.utc).date()))
    except (ValueError, AttributeError):
        return _invalid("week_start: must be YYYY-MM-DD")
    allowed = ("habits_failed", "goals_moved", "main_distraction",
               "environmental_change", "becoming_sentence", "reviewed_on")
    fields = {k: body[k] for k in allowed if k in body}
    row = store.upsert_week(user_id, lp.week_start_for(target).isoformat(),
                            fields)
    if not row:
        return jsonify({"code": "V2_ERROR", "error": "Could not save"}), 500
    return jsonify({"week": lp.serialize_week(row)}), 200


# ═════════════════════════════════════════════════════════════════════════
# Notes (the router's HTTP entrance) + board + lookup
# ═════════════════════════════════════════════════════════════════════════

@life_bp.route("/v2/life/notes", methods=["GET"])
@life_route()
def life_notes_list():
    rows = store.list_notes(
        _uid(), limit=_clamp(request.args.get("limit"), 100, 500),
        untagged_only=(request.args.get("untagged") or "").lower()
        in ("1", "true", "yes"))
    return jsonify({"notes": [lp.serialize_note(r) for r in rows]}), 200


@life_bp.route("/v2/life/notes", methods=["POST"])
@life_route()
def life_note_create():
    """The same router the chat surface uses, over HTTP.

    Both entrances call services.life_chat.handle_note, so a `#mistake` typed
    in the panel and one typed in chat cannot drift apart."""
    user_id = _uid()
    body = _body()
    text = body.get("body")
    if not isinstance(text, str) or not text.strip():
        return _invalid("body: must be a non-empty string")
    # The same gate the chat router applies (founder: "no try outs"). The
    # panel is unreachable before onboarding anyway, so this is the second
    # door being locked rather than the first — but a second door nobody
    # checks is how a rule becomes advisory.
    if not store.setup_completed(user_id):
        return jsonify({
            "code": "SETUP_REQUIRED",
            "error": "Finish the Principles setup first.",
            "pointer": "/panel/principles",
        }), 409
    result = chat.handle_note(user_id, text, source="form")
    if result is None:
        # Untagged from the panel: capture only, no action (§5).
        row = store.insert_note(user_id, text, source="form")
        return jsonify({"note": lp.serialize_note(row) if row else None,
                        "route": "capture"}), 201
    return jsonify(result), 201


@life_bp.route("/v2/life/board", methods=["POST"])
@life_route()
def life_board():
    """"I'm stuck on X" → one of the five advisors, in that lens."""
    question = _body().get("question")
    if not isinstance(question, str) or not question.strip():
        return _invalid("question: must be a non-empty string")
    return jsonify(engine.board_answer(_uid(), question.strip())), 200


@life_bp.route("/v2/life/lookup", methods=["GET"])
@life_route()
def life_lookup():
    """"what do I have on money?" — the ~10 relevant rows, never a dump."""
    q = (request.args.get("q") or "").strip()
    if not q:
        return _invalid("q: required")
    user_id = _uid()
    found = engine.lookup(user_id, q)
    return jsonify({
        "principles": [lp.serialize_item(p) for p in found["principles"]],
        "phrases": [lp.serialize_item(p) for p in found["phrases"]],
        # L-3 — pairs, never a resolution.
        "conflicts": [[lp.serialize_item(a), lp.serialize_item(b)]
                      for a, b in found["conflicts"]],
    }), 200


# ═════════════════════════════════════════════════════════════════════════
# Item 12 — OPT-IN reminder settings (founder decision 2026-07-30)
# ═════════════════════════════════════════════════════════════════════════
# User-initiated settings, allowed under the amended L-4: the user flips the
# switches; nothing here sends. Delivery is fenced into
# services/life_reminders and fires only from the internal cron webhook
# (routes/life_reminders_webhook.py). Every default is OFF.


@life_bp.route("/v2/life/reminders", methods=["GET"])
@life_route()
def life_reminders_get():
    """The switches (all False until the user says otherwise), the VAPID
    public key (null ⇒ the FE hides the section behind a hint), and whether
    this account holds any push subscription."""
    user_id = _uid()
    return jsonify({
        "settings": reminders.get_settings(user_id),
        "public_key": reminders.public_key(),
        "subscribed": bool(reminders.list_subscriptions(user_id)),
    }), 200


@life_bp.route("/v2/life/reminders", methods=["PUT"])
@life_route()
def life_reminders_put():
    """Flip the user's own switches. Unknown fields are dropped, tz is
    clamped; the write is the user's explicit choice and nothing else."""
    fields = reminders.sanitize_settings(_body())
    if not fields:
        return _invalid("no reminder fields to update")
    settings = reminders.upsert_settings(_uid(), fields)
    if settings is None:
        return jsonify({"code": "V2_ERROR", "error": "Could not save"}), 500
    return jsonify({"settings": settings}), 200


@life_bp.route("/v2/life/reminders/subscription", methods=["POST"])
@life_route()
def life_reminders_subscribe():
    """Store this browser's push subscription. Body is the serialized
    PushSubscription: ``{endpoint, keys: {p256dh, auth}}``."""
    body = _body()
    endpoint = body.get("endpoint")
    keys = body.get("keys") if isinstance(body.get("keys"), dict) else {}
    p256dh = keys.get("p256dh")
    auth_key = keys.get("auth")
    for name, value in (("endpoint", endpoint), ("keys.p256dh", p256dh),
                        ("keys.auth", auth_key)):
        if not isinstance(value, str) or not value.strip():
            return _invalid(f"{name}: must be a non-empty string")
    row = reminders.save_subscription(
        _uid(), endpoint=endpoint.strip(), p256dh=p256dh.strip(),
        auth=auth_key.strip(),
        user_agent=request.headers.get("User-Agent"))
    if not row:
        return jsonify({"code": "V2_ERROR", "error": "Could not save"}), 500
    return jsonify({"subscribed": True}), 201


@life_bp.route("/v2/life/reminders/subscription", methods=["DELETE"])
@life_route()
def life_reminders_unsubscribe():
    """Drop one endpoint (body ``{endpoint}``) or, with no body, every
    subscription this account holds."""
    endpoint = (_body().get("endpoint") or "").strip() or None
    removed = reminders.delete_subscription(_uid(), endpoint)
    if removed is None:
        return jsonify({"code": "V2_ERROR", "error": "Could not delete"}), 500
    return jsonify({"deleted": removed}), 200


@life_bp.route("/v2/life/reminders/public-key", methods=["GET"])
@life_route()
def life_reminders_public_key():
    return jsonify({"public_key": reminders.public_key()}), 200


# ═════════════════════════════════════════════════════════════════════════
# User copy — the founder's check-in lines, per-user editable
# (founder decision 2026-07-30: "my copy as default, editable")
# ═════════════════════════════════════════════════════════════════════════

@life_bp.route("/v2/life/copy", methods=["GET"])
@life_route()
def life_copy_get():
    """The user's overrides for the mantra header and the distraction
    question. Every field present; NULL means the FE renders the founder's
    default line."""
    return jsonify({"copy": engine.get_user_copy(_uid())}), 200


@life_bp.route("/v2/life/copy", methods=["PUT"])
@life_route()
def life_copy_put():
    """Reword a line, or clear a field to get the founder's line back.

    The user's OWN words on their OWN card — no model touches this, and the
    write happens only because they typed it (the same reasoning as the
    evening review's fields)."""
    fields = engine.sanitize_user_copy(_body())
    if not fields:
        return _invalid("no copy fields to update")
    saved = engine.upsert_user_copy(_uid(), fields)
    if saved is None:
        return jsonify({"code": "V2_ERROR", "error": "Could not save"}), 500
    return jsonify({"copy": saved}), 200


# ═════════════════════════════════════════════════════════════════════════
# BE-10 — export + hard delete (launch blockers)
# ═════════════════════════════════════════════════════════════════════════

@life_bp.route("/v2/life/export", methods=["POST"])
@life_route()
def life_export():
    """Everything the user owns, one JSON. Raw rows on purpose — an export
    exists so they can LEAVE, and a shape tuned for this FE is a shape only
    this FE can read."""
    user_id = _uid()
    payload = store.export_all(user_id)
    # The two 2026-07-30 additions live outside life_store (setup documents in
    # the importer, reminders in the sanctioned delivery module), so they are
    # merged here rather than silently missing from "everything".
    documents = importer.export_setup_documents(user_id)
    if documents is None:
        payload.setdefault("errors", []).append("life_setup_documents")
    else:
        payload["tables"]["life_setup_documents"] = documents
    reminder_rows = reminders.export_user(user_id)
    if reminder_rows is None:
        payload.setdefault("errors", []).append("life_reminder_settings")
    else:
        payload["tables"].update(reminder_rows)
    user_copy = engine.export_user_copy(user_id)
    if user_copy is None:
        payload.setdefault("errors", []).append("life_user_copy")
    else:
        payload["tables"]["life_user_copy"] = user_copy
    if payload.get("errors"):
        # An export missing a table looks exactly like an empty table. Saying
        # so is the difference between "you have it all" and "you think you
        # have it all".
        return jsonify({**payload, "complete": False}), 200
    return jsonify({**payload, "complete": True}), 200


@life_bp.route("/v2/life/data", methods=["DELETE"])
@life_route(consent=False)
def life_delete():
    """Hard delete. Irreversible, and it requires an explicit confirmation.

    ``consent=False`` deliberately: someone who withdrew consent — or whose
    consent version lapsed — must still be able to delete their data. Gating
    the exit behind the gate they are leaving through would be the worst
    possible reading of a consent screen.

    Body ``{"confirm": "DELETE"}``. Reports what was actually removed and
    refuses to claim success on a partial failure."""
    if (_body().get("confirm") or "") != "DELETE":
        return _invalid('confirm: send {"confirm": "DELETE"} to proceed',
                        code="CONFIRMATION_REQUIRED")
    result = store.hard_delete(_uid())
    # The 2026-07-30 tables die with everything else. Same promise, same
    # honesty: a failure is reported, never papered over.
    removed_docs = importer.delete_setup_documents(_uid())
    if removed_docs is None:
        result.setdefault("failed", []).append("life_setup_documents")
    else:
        result.setdefault("deleted", {})["life_setup_documents"] = removed_docs
    reminder_result = reminders.hard_delete_user(_uid())
    result.setdefault("deleted", {}).update(reminder_result.get("deleted")
                                            or {})
    result.setdefault("failed", []).extend(reminder_result.get("failed")
                                           or [])
    removed_copy = engine.delete_user_copy(_uid())
    if removed_copy is None:
        result.setdefault("failed", []).append("life_user_copy")
    else:
        result.setdefault("deleted", {})["life_user_copy"] = removed_copy
    # The consent row is gone, so the cached "yes" must go with it. Otherwise
    # a just-wiped account keeps passing the gate and can write fresh rows
    # into the account it emptied a second ago.
    chat.invalidate_consent(_uid())
    if result.get("failed"):
        return jsonify({
            "code": "PARTIAL_DELETE",
            "error": "Some data could not be deleted. Nothing is claimed gone "
                     "that is not gone — try again.",
            **result,
        }), 500
    return jsonify({"deleted": True, **result}), 200


# ═════════════════════════════════════════════════════════════════════════
# Founder-only surfaces — 404 to everyone else
# ═════════════════════════════════════════════════════════════════════════

@life_bp.route("/v2/life/prayer", methods=["GET"])
@life_route(allowlist=True)
def life_prayer():
    """The link out to pompeiana.willpowerlab.com. Coach-only for now (§3.4).

    A LINK, not a port. Pompeiana is zero-network by design, offline-first,
    and its scripture text is deliberately not in its repo — absorbing it
    would break the rule the app was built around. The daily card's
    ``☐ Pompeiana`` checkbox stays a local habit tick in life_days and does
    NOT read the prayer app's state: coupling stays at zero."""
    return jsonify({
        "url": "https://pompeiana.willpowerlab.com",
        "opens": "external",
    }), 200
