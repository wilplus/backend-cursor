"""Rings: the one rollout mechanism (founder 2026-09-29, rings design note).

A person has one ring (an integer; a missing row is the default ring with no
attributes). A feature carries the lowest ring that gets it, an optional
attribute rule, an optional consent purpose and a kill switch. The rule the
database implements (migration 0394, ``feature_is_on_v1``) and this module
mirrors for the panel's previews:

    A feature is on for a person when the row is not killed, the person's
    ring is >= the feature's ring, the row's attribute rule matches them
    (AND of "key is in list"), and, for a feature with a consent purpose,
    that consent is current for that person.

RINGS DECIDE REACH, NEVER PROVENANCE (L3). Nothing here creates, reads into
or infers consent: the consent half of the check is asked of the two doors
that already exist, in SQL, by the check function. A ring change never
creates consent and a consent never moves a ring.

READ SIDE. ``feature_is_on`` asks the database function and caches the
answer for the length of the Flask request (``flask.g``), so a route that
asks twice costs one round trip. Every failure is a closed door: an
unreachable database, an unknown feature and a person with no principal all
answer False. Nothing in the F1 loop (record → transcript → Ideal Text →
Feedback → next Take) is behind a ring, so a closed door here never stops a
speaker's Take.

WRITE SIDE. Every write goes through a SECURITY DEFINER RPC; the service key
holds SELECT and nothing else on the ring tables (R-1, as 0389). The admin
routes under /v2/admin/rings/* call the functions below and nothing else.

THE ONE-WAY ROWS. A learning pipe's row is ``one_way``: killing it is
permanent (the RPC refuses the unkill) and it invokes the pipe's own kill.
For the confidence chain that pipe kill is ``confidence_writer_killed``:
the cutover module's ``configured_confidence_cutover`` reads it and reports
``killed`` whatever the constant says. The constant
``MLC2_CONFIDENCE_CUTOVER_MODE`` remains the writer state (``founder_canary``
since the flip of 2026-09-29); this module can only close it, never open it.

THE THREE CANARY VARIABLES ARE GONE. ``DATA_FOUNDATION_CANARY_ENABLED``,
``MLC2_CONFIDENCE_CANARY_FOUNDER_EMAIL`` and
``MLC2_CONFIDENCE_CANARY_PRINCIPAL_ID`` were kept readable and unread for
one release after 0394 and retired on 2026-09-29. Who a feature reaches is a
row; a Railway panel that still carries them sets nothing.
"""
from __future__ import annotations

import hashlib
import logging
import threading
import time
from typing import Any, Mapping, Optional
from uuid import UUID

logger = logging.getLogger(__name__)

# The rows the code reads. A name not listed here is still a valid row (the
# panel can create one for a frontend-only switch); these are the ones a
# decorator or a gate in this repository asks about.
CANONICAL_TAKE_ROWS = "canonical_take_rows"
CONFIDENCE_LEARNING_WRITES = "confidence_learning_writes"
EXERCISE_SERVICE = "exercise_service"
EXERCISE_SERVICE_UI = "exercise_service_ui"
COACH_INLINE_AUTHORING = "coach_inline_authoring"
CONFIDENT_MOMENT_BUNDLES = "confident_moment_bundles"
ROOTING_COVERAGE = "rooting_coverage"
GATED_FEATURES: tuple[str, ...] = (
    CANONICAL_TAKE_ROWS, CONFIDENCE_LEARNING_WRITES, EXERCISE_SERVICE,
    EXERCISE_SERVICE_UI, COACH_INLINE_AUTHORING, CONFIDENT_MOMENT_BUNDLES,
    ROOTING_COVERAGE,
)

CONSENT_PURPOSES: tuple[str, ...] = (
    "personalised_practice", "pooled_model_improvement",
)
DECISIONS: tuple[str, ...] = ("accepted", "not_now")
ATTRIBUTE_KEYS: tuple[str, ...] = ("region", "plan", "language", "role", "bucket")
FALLBACK_DEFAULT_RING = 2

#: How long a process without a request (the worker, a cron) trusts a
#: writer-kill read before asking again. A kill lands within this many
#: seconds on every service, with no deploy.
WRITER_KILL_TTL_SECONDS = 15.0
_writer_kill_lock = threading.Lock()
_writer_kill_cache: dict[str, tuple[float, bool]] = {}


class RingsError(RuntimeError):
    """A write the database refused, carrying its code."""

    def __init__(self, code: str, status: int = 400):
        super().__init__(code)
        self.code = code
        self.status = status


# Codes the RPCs raise, and the HTTP status each deserves.
_RPC_CODES: dict[str, int] = {
    "RING_FEATURE_INVALID": 400,
    "RING_VALUE_INVALID": 400,
    "RING_RULE_INVALID": 400,
    "RING_CONSENT_PURPOSE_INVALID": 400,
    "RING_ATTRIBUTES_INVALID": 400,
    "RING_PRINCIPAL_INVALID": 400,
    "RING_BULK_SIZE_INVALID": 400,
    "RING_DECISION_INVALID": 400,
    "RING_ANNOUNCEMENT_INVALID": 400,
    "RING_FEATURE_UNKNOWN": 404,
    "RING_ANNOUNCEMENT_UNKNOWN": 404,
    "RING_ONE_WAY_KILLED": 409,
}


# ── plumbing ───────────────────────────────────────────────────────────────

def _database(database: Any = None) -> Any:
    if database is not None:
        return database
    from services.db import db
    return db


def _rows(data: Any) -> list[dict]:
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    if isinstance(data, dict):
        return [data]
    return []


def _scalar(data: Any) -> Any:
    if isinstance(data, list):
        return data[0] if data else None
    return data


def _raise_for(error: Exception) -> None:
    text = str(error)
    for code, status in _RPC_CODES.items():
        if code in text:
            raise RingsError(code, status) from error
    raise RingsError("RINGS_UNAVAILABLE", 503) from error


def _rpc(name: str, params: dict, *, database: Any = None) -> Any:
    """One RPC call; a refusal becomes a RingsError with the RPC's code."""
    try:
        return _database(database).client.rpc(name, params).execute().data
    except RingsError:
        raise
    except Exception as error:  # the client raises its own families
        _raise_for(error)
        return None  # unreachable; keeps type checkers quiet


def _request_cache() -> Optional[dict]:
    try:
        from flask import g, has_request_context
        if not has_request_context():
            return None
        cache = getattr(g, "_rings_cache", None)
        if cache is None:
            cache = {}
            g._rings_cache = cache
        return cache
    except Exception:
        return None


def _valid_uuid(value: Any) -> Optional[str]:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError, AttributeError):
        return None


# ── the rule, in Python, for the panel's previews ─────────────────────────
# The database is the check every gate uses; this mirror is what the People
# tab shows before a person's next request, and the released-lane rehearsal
# asserts the two agree on every clause.

def rule_reaches(
    feature_row: Optional[Mapping[str, Any]],
    person_row: Optional[Mapping[str, Any]],
    default_ring: int,
) -> bool:
    """Not killed, ring >= min_ring, attribute rule matches. No consent."""
    if not feature_row or bool(feature_row.get("killed")):
        return False
    try:
        min_ring = int(feature_row.get("min_ring"))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False
    if person_row and person_row.get("ring") is not None:
        ring = int(person_row["ring"])
        attributes = person_row.get("attributes") or {}
    else:
        ring, attributes = int(default_ring), {}
    if ring < min_ring:
        return False
    rule = feature_row.get("attribute_rule")
    if rule is None:
        return True
    if not isinstance(rule, Mapping) or not isinstance(attributes, Mapping):
        return False
    for key, allowed in rule.items():
        if not isinstance(allowed, list):
            return False
        mine = attributes.get(key)
        if mine is None:
            return False
        if str(mine) not in {str(item) for item in allowed}:
            return False
    return True


def rule_is_on(
    feature_row: Optional[Mapping[str, Any]],
    person_row: Optional[Mapping[str, Any]],
    default_ring: int,
    consent_current: bool,
) -> bool:
    """The whole rule. ``consent_current`` is what the consent door said for
    this person and this row's purpose; it is ignored when the row names no
    purpose, and it is never derived from a ring."""
    if not rule_reaches(feature_row, person_row, default_ring):
        return False
    if feature_row is None or feature_row.get("consent_purpose") is None:
        return True
    return bool(consent_current)


# ── read side ──────────────────────────────────────────────────────────────

def feature_is_on(
    feature: str, principal_id: Any, *, database: Any = None,
) -> bool:
    """The check every gated route calls. Fail closed, cached per request."""
    principal = _valid_uuid(principal_id)
    if not feature or not principal:
        return False
    cache = _request_cache()
    key = ("on", feature, principal)
    if cache is not None and key in cache:
        return bool(cache[key])
    try:
        answer = bool(_scalar(_rpc(
            "feature_is_on_v1",
            {"p_feature": feature, "p_principal": principal},
            database=database,
        )))
    except Exception as error:  # any failure is a closed door
        logger.warning("rings: feature_is_on(%s) unavailable: %s",
                       feature, getattr(error, "code", error))
        answer = False
    if cache is not None:
        cache[key] = answer
    return answer


def feature_reaches(
    feature: str, principal_id: Any, *, database: Any = None,
) -> bool:
    """The reach half only (ring, rule, not killed). For the consent route,
    which is the door that creates the consent the full check would ask for."""
    principal = _valid_uuid(principal_id)
    if not feature or not principal:
        return False
    cache = _request_cache()
    key = ("reach", feature, principal)
    if cache is not None and key in cache:
        return bool(cache[key])
    try:
        answer = bool(_scalar(_rpc(
            "feature_reaches_v1",
            {"p_feature": feature, "p_principal": principal},
            database=database,
        )))
    except Exception as error:  # any failure is a closed door
        logger.warning("rings: feature_reaches(%s) unavailable: %s",
                       feature, getattr(error, "code", error))
        answer = False
    if cache is not None:
        cache[key] = answer
    return answer


def principal_for_user(user_id: Any, *, database: Any = None) -> Optional[str]:
    """The owner principal behind a signed-in user, or None."""
    if not user_id:
        return None
    try:
        row = _database(database).get_owner_principal_for_user(str(user_id))
    except Exception:
        return None
    return _valid_uuid((row or {}).get("id"))


def feature_is_on_for_user(
    feature: str, user_id: Any, *, database: Any = None,
) -> bool:
    principal = principal_for_user(user_id, database=database)
    return bool(principal) and feature_is_on(feature, principal, database=database)


def features_on_for(principal_id: Any, *, database: Any = None) -> dict:
    """What a login needs: ring, attributes, features on, pending
    announcements. An unreachable database answers an empty, marked payload
    rather than raising: the app must load without this."""
    principal = _valid_uuid(principal_id)
    empty: dict[str, Any] = {
        "principal_id": principal,
        "ring": None,
        "has_ring_row": False,
        "default_ring": None,
        "attributes": {},
        "features_on": [],
        "pending_announcements": [],
        "unavailable": True,
    }
    if not principal:
        return empty
    try:
        payload = _scalar(_rpc(
            "features_on_for_v1", {"p_principal": principal},
            database=database,
        ))
    except Exception as error:
        logger.warning("rings: features_on_for unavailable: %s",
                       getattr(error, "code", error))
        return empty
    if not isinstance(payload, dict):
        return empty
    payload.setdefault("features_on", [])
    payload.setdefault("pending_announcements", [])
    payload["unavailable"] = False
    return payload


def features_on_for_user(user_id: Any, *, database: Any = None) -> dict:
    principal = principal_for_user(user_id, database=database)
    if not principal:
        return features_on_for(None, database=database)
    return features_on_for(principal, database=database)


def feature_ring_row(feature: str, *, database: Any = None) -> Optional[dict]:
    """One feature row (a direct read; the service key holds SELECT)."""
    try:
        result = (_database(database).client.table("feature_rings")
                  .select("*").eq("feature", feature).limit(1).execute())
        rows = _rows(result.data)
        return rows[0] if rows else None
    except Exception as error:
        logger.warning("rings: feature row %s unreadable: %s", feature, error)
        return None


def confidence_writer_killed(*, database: Any = None, now: Optional[float] = None) -> bool:
    """The confidence chain's pipe kill, read from its one-way row.

    True only when the ``confidence_learning_writes`` row exists and is
    killed. Cached for WRITER_KILL_TTL_SECONDS per process, so the worker
    and every cron see a kill within that window with no deploy. A read
    that fails leaves the constant's state standing (False here): this
    function can close the pipe, never open it, and a database blip must
    not flip the writer state either way.
    """
    moment = time.monotonic() if now is None else now
    with _writer_kill_lock:
        cached = _writer_kill_cache.get(CONFIDENCE_LEARNING_WRITES)
        if cached and moment - cached[0] < WRITER_KILL_TTL_SECONDS:
            return cached[1]
    row = feature_ring_row(CONFIDENCE_LEARNING_WRITES, database=database)
    killed = bool(row and row.get("killed"))
    with _writer_kill_lock:
        _writer_kill_cache[CONFIDENCE_LEARNING_WRITES] = (moment, killed)
    return killed


def forget_writer_kill_cache() -> None:
    with _writer_kill_lock:
        _writer_kill_cache.clear()


def ring_eligible_principals(feature: str, *, database: Any = None) -> tuple[str, ...]:
    """The principals with a ring row that a feature reaches (no consent)."""
    try:
        data = _rpc("ring_eligible_principals_v1", {"p_feature": feature},
                    database=database)
    except RingsError:
        return ()
    out: list[str] = []
    for item in data if isinstance(data, list) else []:
        value = item.get("ring_eligible_principals_v1") if isinstance(item, dict) else item
        principal = _valid_uuid(value)
        if principal:
            out.append(principal)
    return tuple(out)


# ── write side (the admin routes call these) ───────────────────────────────

def get_default_ring(*, database: Any = None) -> int:
    try:
        value = _scalar(_rpc("ring_default_v1", {}, database=database))
        return int(value)
    except (RingsError, TypeError, ValueError):
        return FALLBACK_DEFAULT_RING


def set_default_ring(ring: Any, *, changed_by: str, database: Any = None) -> dict:
    return _scalar(_rpc("set_ring_default_v1", {
        "p_ring": _int_or_raise(ring, "RING_VALUE_INVALID"),
        "p_changed_by": changed_by,
    }, database=database)) or {}


def list_features(*, database: Any = None) -> dict:
    """Every feature row with its counts and announcement, for the panel."""
    db = _database(database)
    rows = _rows(db.client.table("feature_rings").select("*")
                 .order("min_ring").order("feature").execute().data)
    announcements = {
        row.get("feature"): row for row in _rows(
            db.client.table("ring_announcements").select("*").execute().data)
    }
    try:
        counts = _scalar(_rpc("feature_ring_counts_v1", {}, database=db)) or {}
    except RingsError:
        counts = {}
    for row in rows:
        row["counts"] = counts.get(row.get("feature")) if isinstance(counts, dict) else None
        row["announcement"] = announcements.get(row.get("feature"))
    return {"features": rows, "default_ring": get_default_ring(database=db)}


def set_feature_ring(
    feature: str, body: Mapping[str, Any], *, changed_by: str,
    database: Any = None,
) -> dict:
    rule = body.get("attribute_rule")
    if rule is not None and not isinstance(rule, Mapping):
        raise RingsError("RING_RULE_INVALID", 400)
    purpose = body.get("consent_purpose")
    if purpose is not None and purpose not in CONSENT_PURPOSES:
        raise RingsError("RING_CONSENT_PURPOSE_INVALID", 400)
    note = body.get("note")
    if note is not None and (not isinstance(note, str) or len(note) > 2000):
        raise RingsError("RING_VALUE_INVALID", 400)
    return _scalar(_rpc("set_feature_ring_v1", {
        "p_feature": feature,
        "p_min_ring": _int_or_raise(body.get("min_ring"), "RING_VALUE_INVALID"),
        "p_attribute_rule": dict(rule) if rule is not None else None,
        "p_consent_purpose": purpose,
        "p_note": note or "",
        "p_one_way": bool(body.get("one_way", False)),
        "p_changed_by": changed_by,
    }, database=database)) or {}


def kill_feature(
    feature: str, killed: Any, *, changed_by: str, database: Any = None,
) -> dict:
    """The kill switch. On a one-way row this also invokes the pipe's own
    kill; the RPC has already refused an unkill of one."""
    if not isinstance(killed, bool):
        raise RingsError("RING_VALUE_INVALID", 400)
    row = _scalar(_rpc("kill_feature_v1", {
        "p_feature": feature, "p_killed": killed, "p_changed_by": changed_by,
    }, database=database)) or {}
    if killed and row.get("one_way"):
        _apply_pipe_kill(str(row.get("feature") or feature))
    return row


def _apply_pipe_kill(feature: str) -> None:
    """The pipe's own kill for a one-way row.

    confidence_learning_writes: the writer state is read through
    ``confidence_writer_killed`` by ``configured_confidence_cutover``, so the
    row IS the kill; forgetting the cache makes this process see it now.
    The constant stays where it is. Any other one-way row has no pipe hook
    yet and is logged so the gap is visible.
    """
    forget_writer_kill_cache()
    if feature == CONFIDENCE_LEARNING_WRITES:
        logger.warning(
            "rings: %s killed; the confidence writer state now reads killed "
            "on every service within %ss (constant untouched)",
            feature, int(WRITER_KILL_TTL_SECONDS),
        )
        return
    logger.warning("rings: one-way row %s killed; no pipe hook registered",
                   feature)


def set_principal_ring(
    principal_id: Any, body: Mapping[str, Any], *, changed_by: str,
    database: Any = None,
) -> dict:
    principal = _valid_uuid(principal_id)
    if not principal:
        raise RingsError("RING_PRINCIPAL_INVALID", 400)
    ring = body.get("ring")
    attributes = body.get("attributes")
    if attributes is not None:
        attributes = _clean_attributes(attributes)
    return _scalar(_rpc("set_principal_ring_v1", {
        "p_principal": principal,
        "p_ring": None if ring is None else _int_or_raise(ring, "RING_VALUE_INVALID"),
        "p_attributes": attributes,
        "p_changed_by": changed_by,
    }, database=database)) or {}


def set_principal_rings_bulk(
    principal_ids: Any, ring: Any, *, changed_by: str, database: Any = None,
) -> dict:
    if not isinstance(principal_ids, list) or not principal_ids:
        raise RingsError("RING_BULK_SIZE_INVALID", 400)
    principals = [_valid_uuid(value) for value in principal_ids]
    if any(value is None for value in principals) or len(principals) > 500:
        raise RingsError("RING_PRINCIPAL_INVALID", 400)
    return _scalar(_rpc("set_principal_rings_bulk_v1", {
        "p_principals": principals,
        "p_ring": _int_or_raise(ring, "RING_VALUE_INVALID"),
        "p_changed_by": changed_by,
    }, database=database)) or {}


def list_people(
    *, search: str = "", filters: Optional[Mapping[str, str]] = None,
    ring: Optional[int] = None, limit: int = 50, offset: int = 0,
    database: Any = None,
) -> dict:
    """A page of accounts with their ring, attributes and what reaches them.

    Accounts come from the admin user directory (the same page the /admin
    users list shows); their ring rows are joined on the owner principal.
    Attribute filters are applied to the page in Python. What each person
    "gets" is the Python mirror of the rule over the loaded feature rows: it
    says which rows REACH them; a row with a consent purpose is marked as
    asking for that consent rather than asserted on.
    """
    from services import admin_user_directory

    db = _database(database)
    directory = admin_user_directory.list_users(
        limit=limit, offset=offset, search=search)
    users = [dict(row) for row in directory.get("users") or []]
    user_ids = [str(row.get("user_id")) for row in users if row.get("user_id")]
    principals: dict[str, str] = {}
    if user_ids:
        for row in _rows(db.client.table("owner_principals")
                         .select("id,user_id").in_("user_id", user_ids)
                         .execute().data):
            if row.get("user_id") and row.get("id"):
                principals[str(row["user_id"])] = str(row["id"])
    ring_rows: dict[str, dict] = {}
    if principals:
        for row in _rows(db.client.table("principal_rings").select("*")
                         .in_("principal_id", list(principals.values()))
                         .execute().data):
            ring_rows[str(row.get("principal_id"))] = row
    features = _rows(db.client.table("feature_rings").select("*")
                     .order("min_ring").execute().data)
    default_ring = get_default_ring(database=db)

    people: list[dict] = []
    for user in users:
        principal = principals.get(str(user.get("user_id")))
        ring_row: Optional[dict] = ring_rows.get(principal or "")
        person_ring = int(default_ring)
        if ring_row and ring_row.get("ring") is not None:
            person_ring = int(ring_row["ring"])
        attributes: dict = dict((ring_row or {}).get("attributes") or {})
        person: dict[str, Any] = {
            "user_id": user.get("user_id"),
            "email": user.get("email"),
            "name": user.get("name"),
            "principal_id": principal,
            "ring": person_ring,
            "has_ring_row": bool(ring_row),
            "attributes": attributes,
        }
        if ring is not None and person_ring != int(ring):
            continue
        if not _matches_filters(attributes, filters or {}):
            continue
        person["reaches"] = [
            {"feature": f.get("feature"),
             "consent_purpose": f.get("consent_purpose")}
            for f in features if rule_reaches(f, ring_row, default_ring)
        ]
        people.append(person)
    return {
        "people": people,
        "default_ring": default_ring,
        "has_more": bool(directory.get("has_more")),
        "limit": limit,
        "offset": offset,
    }


def _matches_filters(attributes: Mapping[str, Any], filters: Mapping[str, str]) -> bool:
    for key, wanted in filters.items():
        if wanted in (None, ""):
            continue
        if str(attributes.get(key)) != str(wanted):
            return False
    return True


def list_announcements(*, database: Any = None) -> list[dict]:
    return _rows(_database(database).client.table("ring_announcements")
                 .select("*").order("feature").execute().data)


def set_announcement(
    feature: str, body: Mapping[str, Any], *, changed_by: str,
    database: Any = None,
) -> dict:
    title = body.get("title")
    text = body.get("body")
    if not isinstance(title, str) or not isinstance(text, str):
        raise RingsError("RING_ANNOUNCEMENT_INVALID", 400)
    return _scalar(_rpc("set_ring_announcement_v1", {
        "p_feature": feature,
        "p_title": title,
        "p_body": text,
        "p_requires_consent": bool(body.get("requires_consent", False)),
        "p_retired": bool(body.get("retired", False)),
        "p_changed_by": changed_by,
    }, database=database)) or {}


def record_announcement_decision(
    principal_id: Any, feature: str, decision: Any, *, database: Any = None,
) -> dict:
    """The person's answer to an announcement. Creates no consent."""
    principal = _valid_uuid(principal_id)
    if not principal:
        raise RingsError("RING_PRINCIPAL_INVALID", 400)
    if decision not in DECISIONS:
        raise RingsError("RING_DECISION_INVALID", 400)
    return _scalar(_rpc("record_ring_announcement_decision_v1", {
        "p_principal": principal, "p_feature": feature, "p_decision": decision,
    }, database=database)) or {}


def list_changes(*, limit: int = 100, database: Any = None) -> list[dict]:
    """The audit list: the three append-only tables, newest first."""
    db = _database(database)
    limit = max(1, min(int(limit), 500))
    out: list[dict] = []
    for table, kind in (("feature_ring_changes", "feature"),
                        ("principal_ring_changes", "principal"),
                        ("ring_setting_changes", "setting")):
        try:
            rows = _rows(db.client.table(table).select("*")
                         .order("id", desc=True).limit(limit).execute().data)
        except Exception as error:
            logger.warning("rings: %s unreadable: %s", table, error)
            rows = []
        for row in rows:
            out.append({"kind": kind, **row})
    out.sort(key=lambda row: str(row.get("changed_at") or ""), reverse=True)
    return out[:limit]


def _int_or_raise(value: Any, code: str) -> int:
    if isinstance(value, bool) or value is None:
        raise RingsError(code, 400)
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise RingsError(code, 400) from None
    if number < 0:
        raise RingsError(code, 400)
    return number


def _clean_attributes(value: Any) -> dict:
    if not isinstance(value, Mapping):
        raise RingsError("RING_ATTRIBUTES_INVALID", 400)
    cleaned: dict[str, Any] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not key.islower() or len(key) > 40:
            raise RingsError("RING_ATTRIBUTES_INVALID", 400)
        if isinstance(item, (dict, list)):
            raise RingsError("RING_ATTRIBUTES_INVALID", 400)
        if item is None:
            continue
        cleaned[key] = item
    return cleaned


# ── attributes at sign-up ──────────────────────────────────────────────────

def bucket_for(principal_id: Any) -> int:
    """0–99, a stable sha256 of the principal id, for percentage rules."""
    digest = hashlib.sha256(str(principal_id).encode("utf-8")).hexdigest()
    return int(digest, 16) % 100


def attributes_for_account(
    *, principal_id: str, region: Optional[str], language: Optional[str],
    plan: Optional[str], role: Optional[str],
) -> dict:
    """The attributes a new account starts with. Absent facts are absent
    keys, never guessed: a rule on ``region`` does not match a person whose
    region is unknown."""
    attributes: dict[str, Any] = {"bucket": bucket_for(principal_id)}
    if region:
        attributes["region"] = str(region).strip().upper()[:8]
    if language:
        attributes["language"] = str(language).strip().lower()[:16]
    if plan:
        attributes["plan"] = str(plan).strip().lower()[:32]
    if role:
        attributes["role"] = str(role).strip().lower()[:32]
    return attributes


def _language_from_accept(header: Optional[str]) -> Optional[str]:
    first = str(header or "").split(",")[0].split(";")[0].strip()
    return first.split("-")[0].lower() if first else None


def record_account_attributes(
    user_id: Any, *, email: Optional[str] = None, region: Optional[str] = None,
    language: Optional[str] = None, plan: Optional[str] = None,
    database: Any = None,
) -> Optional[dict]:
    """The sign-up hook. Creates the owner principal if it does not exist,
    then writes the person's starting row at the default ring with their
    attributes. Best effort: it never raises into a sign-up."""
    try:
        db = _database(database)
        row = db.get_owner_principal_for_user(str(user_id)) or \
            db.create_user_owner_principal(str(user_id))
        principal = _valid_uuid((row or {}).get("id"))
        if not principal:
            return None
        role = "coach" if _is_coach_email(email, database=db) else "speaker"
        attributes = attributes_for_account(
            principal_id=principal, region=region, language=language,
            plan=plan or "free", role=role,
        )
        existing = _rows(db.client.table("principal_rings").select("*")
                         .eq("principal_id", principal).limit(1).execute().data)
        if existing:
            # A person who already has a row (a seeded cohort member who
            # signs in again) keeps their ring and gains only missing keys.
            merged = {**attributes, **(existing[0].get("attributes") or {})}
            if merged == (existing[0].get("attributes") or {}):
                return existing[0]
            return set_principal_ring(
                principal, {"attributes": merged}, changed_by="signup",
                database=db)
        return set_principal_ring(
            principal, {"attributes": attributes}, changed_by="signup",
            database=db)
    except Exception as error:
        logger.warning("rings: sign-up attributes not recorded user=%s: %s",
                       user_id, error)
        return None


def record_signup_from_request(user_id: Any, email: Optional[str], request: Any) -> Optional[dict]:
    """Region and language from what the request carries (the edge's
    country header when present, the browser's Accept-Language); the
    account country recorded at Phase-1 acceptance refines region later
    through ``record_account_country``."""
    headers = getattr(request, "headers", None) or {}
    region = (headers.get("CF-IPCountry") or headers.get("X-Vercel-IP-Country")
              or headers.get("X-Country") or "")
    region = None if not region or region.upper() in ("XX", "T1") else region
    return record_account_attributes(
        user_id, email=email, region=region,
        language=_language_from_accept(headers.get("Accept-Language")),
    )


def record_account_country(
    principal_id: Any, *, country: Optional[str], locale: Optional[str] = None,
    database: Any = None,
) -> None:
    """Phase-1 acceptance records the account country; the region attribute
    follows it. Best effort, never raises into the acceptance."""
    principal = _valid_uuid(principal_id)
    if not principal or not country:
        return
    try:
        db = _database(database)
        existing = _rows(db.client.table("principal_rings").select("*")
                         .eq("principal_id", principal).limit(1).execute().data)
        attributes = dict((existing[0].get("attributes") or {}) if existing else {})
        attributes.setdefault("bucket", bucket_for(principal))
        attributes["region"] = str(country).strip().upper()[:8]
        if locale and "language" not in attributes:
            attributes["language"] = _language_from_accept(locale)
        set_principal_ring(principal, {"attributes": attributes},
                           changed_by="phase1_acceptance", database=db)
    except Exception as error:
        logger.warning("rings: account country not recorded: %s", error)


def _is_coach_email(email: Optional[str], *, database: Any) -> bool:
    if not email:
        return False
    try:
        rows = _rows(database.client.table("coach_users").select("id")
                     .eq("email", str(email).strip().lower())
                     .eq("is_active", True).execute().data)
        return bool(rows)
    except Exception:
        return False
