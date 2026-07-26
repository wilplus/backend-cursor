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
from datetime import date, datetime, timezone
from functools import wraps

from flask import Blueprint, jsonify, request

from auth import require_auth
from config import Config as config
from services import life_chat as chat
from services import life_engine as engine
from services import life_panel as lp
from services import life_store as store

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

    return jsonify({
        "consented": consented,
        "consent_version": version,
        "setup_started": bool(setup),
        "setup_complete": complete,
        # The one field to gate on. consented + setup_complete are the reason,
        # this is the answer — so the FE never has to re-derive the rule.
        "active": active,
        "menu": menu,
        # The `#` picker is only useful once the engine will actually run.
        "tags": lp.tag_suggestions() if active else [],
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
    return jsonify({"consented": True, "version": required}), 200


@life_bp.route("/v2/life/setup", methods=["GET"])
@life_route()
def life_setup_get():
    """Partial answers, for save-and-resume."""
    row = store.get_setup(_uid()) or {}
    return jsonify({
        "answers": row.get("answers") or {},
        "complete": bool(row.get("completed_at")),
    }), 200


@life_bp.route("/v2/life/setup", methods=["PUT"])
@life_route()
def life_setup_put():
    """Upsert partial answers. Called on every step, not only at the end —
    eight horizons is long enough that people get interrupted, and without
    resume an interruption is an abandonment."""
    answers = _body().get("answers")
    if not isinstance(answers, dict):
        return _invalid("answers: must be an object")
    row = store.upsert_setup(_uid(), answers)
    if not row:
        return jsonify({"code": "V2_ERROR",
                        "error": "Could not save"}), 500
    return jsonify({"answers": row.get("answers") or {}}), 200


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
    latest = store.latest_strategy(_uid())
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

    warrants = {}
    for row in surfaced + batch:
        wid = row.get("warrant_principle_id")
        if wid and wid not in warrants:
            warrants[wid] = store.get_item(user_id, str(wid))

    def _ser(row):
        return lp.serialize_proposal(
            row, warrant=warrants.get(row.get("warrant_principle_id")))

    return jsonify({
        "surfaced": [_ser(r) for r in surfaced],
        "weekly_batch": [_ser(r) for r in batch],
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
    if body.get("approve") is True:
        fields["status"] = "active"
        if "category" not in fields and existing.get("category_proposed"):
            fields["category"] = lp.normalize_categories(
                existing["category_proposed"])
        for item in store.items_for_case(user_id, case_id):
            if item.get("status") == "proposed":
                store.update_item(user_id, str(item["id"]),
                                  {"status": "active"})
    row = store.update_case(user_id, case_id, fields)
    return jsonify({"case": lp.serialize_case(row or existing)}), 200


# ═════════════════════════════════════════════════════════════════════════
# Items · timeline
# ═════════════════════════════════════════════════════════════════════════

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
        "proposals": [lp.serialize_proposal(p) for p in lp.weekly_batch(queued)],
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
    body = _body()
    text = body.get("body")
    if not isinstance(text, str) or not text.strip():
        return _invalid("body: must be a non-empty string")
    result = chat.handle_note(_uid(), text, source="form")
    if result is None:
        # Untagged from the panel: capture only, no action (§5).
        row = store.insert_note(_uid(), text, source="form")
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
# BE-10 — export + hard delete (launch blockers)
# ═════════════════════════════════════════════════════════════════════════

@life_bp.route("/v2/life/export", methods=["POST"])
@life_route()
def life_export():
    """Everything the user owns, one JSON. Raw rows on purpose — an export
    exists so they can LEAVE, and a shape tuned for this FE is a shape only
    this FE can read."""
    payload = store.export_all(_uid())
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
