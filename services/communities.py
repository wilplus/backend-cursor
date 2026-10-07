"""Communities: a Take shared with the people who judge it (founder
2026-10-06, decisions log N52.4; docs/FOUNDER-LOCK-feedback-walk-2026-10-06.md;
migration 0432), dark behind ``Config.COMMUNITIES_ENABLED``; sharing also
requires ``Config.COMMUNITY_SHARE_POLICY_VERSION``, the CURRENT Privacy/Terms
(CM2 B, N53.2; Q-B6 A, N62: sharing goes live with the sharing screen under
the founder's own signed words, without waiting for counsel), and each share
records the version of the sharing screen's words the speaker saw
(``take_shares.share_words_version``, migration 0443), sent by the screen.

THE LOCK (N52.4): "After every finished review the speaker is asked whether
to share that Take; several choices may be ticked: the general community,
only my community (with a pass code), or a community of their own (a name
and a pass code); 'None' stands alone. A shared Take is judged by the
community chosen; with 'None' only the coach judges it. When judging, the
speaker hears their community's Takes first, then their own mixed with
training clips. Consent is per Take, and taking it back removes the Take
from every community queue. Community answers are peer ratings, a
provenance of their own (L3), never coach labels, owner routing or training
labels by themselves."

THE PASS CODE is normalised (Unicode NFKC, stripped, casefolded), at least
six characters, and stored only as an HMAC-SHA256 digest keyed from a server
secret already in config; with no secret set, creating and joining refuse
(503) rather than keep a code in the clear. Joining is by pass code alone.

THE SHARE is per Take, one row per community, stamped with the policy
version the speaker accepted (Privacy/Terms) and with the version of the
sharing screen's words they saw (``share_words_version``, which the screen
sends and the route requires on every share); "None" cannot be combined
with any other choice and revokes every live row of the Take. A community
the speaker does not belong to cannot be chosen; the general community is
open to everyone. Withdrawal (fewer communities, or "None") never waits for
the policy version and carries no words version: taking consent back is
always possible.

THE QUEUE is the walk's other voices, served by the Lend your ear engine
(``lend_your_ear.other_voices``; founder 2026-10-07, Q-B11 A, N62): at most
three per walk, the community clips first (the speaker's private
communities, then the general one), never the listener's own, never one
they answered, never one the coach + peer quorum already settled
(``label_quorum``), then training clips from the licensed corpus for the
places left, machine-picked by stratum (``lend_your_ear.build_set``). The
per-Take share above is the ONE consent path that admits a speaker's
moment to this queue: ``community_clips`` reads ``community_clips_live``
and nothing else (the Album share switch is retired). The speaker's own
moments are judged in the existing owner judgement flow, which this
module does not touch. Audio only (AC-9): the clip id, the sound, where it
starts, how long it is and which kind it is. No names, no words, no
machine read, no numbers about anyone's voice.

THE ANSWER is one per person per clip, the same five answers
(``state_ratings.validate_rating``). A community clip's answer is a PEER
rating: it is kept in ``community_answers`` and becomes a peer label
(lane ``game_peer``) only under the quorum's access rule, exactly as
``lend_your_ear._peer_label`` writes one; it is never a coach label, never
owner routing and never a training label by itself (L3). A training clip is
not a snippet and takes no label: its answer stays in ``community_answers``
alone, beside but apart from the community rows (clip_source 'corpus').
The listener's own clip is never accepted.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import re
import unicodedata
import uuid
from typing import Any, Optional

_log = logging.getLogger(__name__)

GENERAL = "general"
PRIVATE = "private"
PASS_CODE_MIN = 6
PASS_CODE_MAX = 128
NAME_MAX = 80
#: Domain separation for the pass-code key derived from the server secret.
_KEY_LABEL = b"willab/community-pass-code/v1"
#: The shape of a sharing-screen words version the screen may send (0443):
#: a short id, nothing a person wrote.
_WORDS_VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")



def _not_found() -> tuple[int, dict]:
    """Every answer while the switch is off: nothing is read or written."""
    return 404, {"code": "NOT_FOUND"}


def communities_enabled() -> bool:
    from config import Config
    return bool(getattr(Config, "COMMUNITIES_ENABLED", False))


def share_policy_version() -> Optional[str]:
    from config import Config
    version = getattr(Config, "COMMUNITY_SHARE_POLICY_VERSION", None)
    return str(version) if version else None


# ── the pass code ─────────────────────────────────────────────────────────

def normalise_pass_code(raw: Any) -> Optional[str]:
    """The code as compared: NFKC, stripped, casefolded; None when it is
    not a string, shorter than six characters or longer than 128. Pure."""
    if not isinstance(raw, str):
        return None
    code = unicodedata.normalize("NFKC", raw).strip().casefold()
    if len(code) < PASS_CODE_MIN or len(code) > PASS_CODE_MAX:
        return None
    return code


def _pass_code_key() -> Optional[bytes]:
    """A key derived from the server secret, never the secret itself; None
    when the secret is not set (the routes then refuse with 503)."""
    from config import Config
    secret = str(getattr(Config, "SUPABASE_JWT_SECRET", "") or "").strip()
    if not secret:
        return None
    return hmac.new(secret.encode("utf-8"), _KEY_LABEL, hashlib.sha256).digest()


def pass_code_digest(code: str, key: bytes) -> str:
    """HMAC-SHA256 of the normalised code. Pure."""
    return hmac.new(key, code.encode("utf-8"), hashlib.sha256).hexdigest()


def _digest_or_error(raw: Any) -> tuple[Optional[str], Optional[tuple[int, dict]]]:
    code = normalise_pass_code(raw)
    if code is None:
        return None, (400, {"code": "PASS_CODE_INVALID"})
    key = _pass_code_key()
    if key is None:
        return None, (503, {"code": "PASS_CODES_UNAVAILABLE"})
    return pass_code_digest(code, key), None


def _is_uuid(value: Any) -> bool:
    try:
        uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return False
    return True


def _community_payload(row: dict, role: Optional[str]) -> dict:
    """What a member sees of a community: its id, kind, the name its owner
    gave it and their own role. Never the digest, never who else is in it."""
    return {"id": str(row.get("id")), "kind": row.get("kind"),
            "name": row.get("name") if row.get("kind") == PRIVATE else None,
            "role": role}


# ── create, join, list ────────────────────────────────────────────────────

def create_community(database: Any, *, owner_user_id: str, body: Any) -> tuple[int, dict]:
    """Set up a private community with a name and a pass code; its creator
    is its owner and first member. 409 when the code is already in use."""
    if not communities_enabled():
        return _not_found()
    fields: dict = body if isinstance(body, dict) else {}
    raw_name = fields.get("name")
    name = " ".join(raw_name.split()) if isinstance(raw_name, str) else ""
    if not name or len(name) > NAME_MAX:
        return 400, {"code": "NAME_INVALID"}
    digest, error = _digest_or_error(fields.get("pass_code"))
    if error:
        return error
    row = database.insert_community({
        "kind": PRIVATE, "name": name, "pass_code_digest": digest,
        "created_by": str(owner_user_id)})
    if row is None:
        return 409, {"code": "PASS_CODE_TAKEN"}
    if not isinstance(row, dict) or not row.get("id"):
        return 500, {"code": "V2_ERROR"}
    database.add_community_member(community_id=str(row["id"]),
                                  user_id=str(owner_user_id), role="owner")
    return 201, {"community": _community_payload(row, "owner")}


def join_community(database: Any, *, user_id: str, body: Any) -> tuple[int, dict]:
    """Join a private community by its pass code alone. Joining again is a
    no-op; an owner stays owner."""
    if not communities_enabled():
        return _not_found()
    fields: dict = body if isinstance(body, dict) else {}
    digest, error = _digest_or_error(fields.get("pass_code"))
    if error:
        return error
    row = database.get_community_by_pass_code_digest(str(digest))
    if not isinstance(row, dict) or row.get("kind") != PRIVATE or row.get("closed_at"):
        return 404, {"code": "COMMUNITY_NOT_FOUND"}
    database.add_community_member(community_id=str(row["id"]), user_id=str(user_id),
                                  role="member")
    role = _roles(database, user_id).get(str(row["id"]), "member")
    return 200, {"community": _community_payload(row, role)}


def _roles(database: Any, user_id: str) -> dict[str, str]:
    """{community_id: role} for one person's memberships."""
    return {str(m.get("community_id")): str(m.get("role") or "member")
            for m in database.list_community_memberships(str(user_id)) or []
            if isinstance(m, dict) and m.get("community_id")}


def _open_private(database: Any, user_id: str) -> tuple[list[dict], dict[str, str]]:
    """The private communities this person belongs to that are not closed,
    and their roles."""
    roles = _roles(database, user_id)
    rows = [r for r in database.get_communities_by_ids(list(roles)) or []
            if isinstance(r, dict) and r.get("kind") == PRIVATE and not r.get("closed_at")]
    return rows, roles


def list_my_communities(database: Any, *, user_id: str) -> tuple[int, dict]:
    """The general community (open to everyone) and the private ones this
    person belongs to."""
    if not communities_enabled():
        return _not_found()
    out: list[dict] = []
    general = database.get_general_community()
    if isinstance(general, dict) and general.get("id"):
        out.append(_community_payload(general, None))
    rows, roles = _open_private(database, user_id)
    out.extend(_community_payload(r, roles.get(str(r.get("id")))) for r in rows)
    return 200, {"communities": out}


# ── the share ─────────────────────────────────────────────────────────────

def _share_choice(body: Any) -> tuple[Optional[dict], Optional[tuple[int, dict]]]:
    """{general, community_ids, none} from the body, strictly typed. Pure."""
    fields: dict = body if isinstance(body, dict) else {}
    general = fields.get("general", False)
    none = fields.get("none", False)
    ids = fields.get("community_ids", [])
    if not isinstance(general, bool) or not isinstance(none, bool) or not isinstance(ids, list):
        return None, (400, {"code": "INVALID_INPUT"})
    if any(not isinstance(i, str) or not _is_uuid(i) for i in ids):
        return None, (400, {"code": "INVALID_INPUT"})
    if none and (general or ids):
        return None, (400, {"code": "NONE_IS_EXCLUSIVE"})
    if not none and not general and not ids:
        return None, (400, {"code": "NOTHING_CHOSEN"})
    return {"general": general, "none": none,
            "community_ids": list(dict.fromkeys(str(i).lower() for i in ids))}, None


def share_words_version_from(body: Any) -> Optional[str]:
    """The version of the sharing screen's words the speaker saw, as the
    screen sends it (``share_words_version``); None when missing or not a
    short id. Pure."""
    fields: dict = body if isinstance(body, dict) else {}
    value = fields.get("share_words_version")
    if not isinstance(value, str) or not _WORDS_VERSION_RE.match(value):
        return None
    return value


def share_take(database: Any, *, owner_user_id: str, take_session_id: str,
               body: Any) -> tuple[int, dict]:
    """Share one Take with the communities chosen and withdraw it from the
    rest; "None" withdraws it from every community. A share names the
    current Privacy/Terms (Q-B6 A) and records the words the speaker saw
    (CM2 B, 0443); "None" needs neither."""
    if not communities_enabled():
        return _not_found()
    session = database.v2_get_session_by_id(str(take_session_id))
    if not isinstance(session, dict) or str(session.get("user_id")) != str(owner_user_id):
        return 404, {"code": "TAKE_NOT_FOUND"}
    choice, error = _share_choice(body)
    if error or choice is None:
        return error or (400, {"code": "INVALID_INPUT"})
    take = str(take_session_id)
    if choice["none"]:
        database.revoke_take_shares(take, keep_community_ids=[])
        return 200, {"take_session_id": take, "community_ids": [], "none": True}
    words_version = share_words_version_from(body)
    if words_version is None:
        return 400, {"code": "SHARE_WORDS_VERSION_REQUIRED"}
    version = share_policy_version()
    from services.lend_your_ear import accepted_policy_at_least
    if not version or not accepted_policy_at_least(database, owner_user_id, version):
        return 409, {"code": "TERMS_REACCEPT_REQUIRED"}
    general = database.get_general_community()
    if not isinstance(general, dict) or not general.get("id"):
        return 500, {"code": "V2_ERROR"}
    general_id = str(general["id"]).lower()
    wanted_private = [i for i in choice["community_ids"] if i != general_id]
    want_general = choice["general"] or general_id in choice["community_ids"]
    rows, _ = _open_private(database, owner_user_id)
    mine = {str(r.get("id")).lower() for r in rows}
    if any(i not in mine for i in wanted_private):
        return 403, {"code": "NOT_A_MEMBER"}
    chosen = ([general_id] if want_general else []) + wanted_private
    for community_id in chosen:
        database.upsert_take_share(take_session_id=take, owner_user_id=str(owner_user_id),
                                   community_id=community_id, consent_version=version,
                                   share_words_version=words_version)
    database.revoke_take_shares(take, keep_community_ids=chosen)
    return 200, {"take_session_id": take, "community_ids": chosen, "none": False,
                 "share_words_version": words_version}


# ── the queue ─────────────────────────────────────────────────────────────

def _hearable(database: Any, listener_id: str) -> tuple[Optional[str], set[str]]:
    """(the general community's id, the private ones the listener belongs
    to and that are open)."""
    general = database.get_general_community()
    general_id = str(general["id"]) if isinstance(general, dict) and general.get("id") else None
    rows, _ = _open_private(database, listener_id)
    return general_id, {str(r.get("id")) for r in rows}


def order_community_clips(rows: list[dict], *, listener_id: str, answered: set[str],
                          labels: dict, private_ids: set[str]) -> list[dict]:
    """The community clips a listener may hear, in order: their private
    communities' first, then the general one's; one entry per moment (a
    moment shared with two communities is heard once, under the private
    one); never their own, never one they answered or already labelled,
    never one the quorum settled. Pure."""
    from services.label_quorum import SETTLED_STATUSES, resolve
    me = str(listener_id)
    seen: set[str] = set()
    picked: list[tuple[int, int, dict]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or not row.get("snippet_id"):
            continue
        sid = str(row["snippet_id"])
        if str(row.get("owner_user_id")) == me or sid in answered:
            continue
        rows_for = labels.get(sid, []) or []
        if any(isinstance(r, dict) and str(r.get("rater_id") or "") == me for r in rows_for):
            continue
        if resolve(rows_for).get("status") in SETTLED_STATUSES:
            continue
        rank = 0 if str(row.get("community_id")) in private_ids else 1
        picked.append((rank, index, row))
    out: list[dict] = []
    for _, _, row in sorted(picked, key=lambda p: (p[0], p[1])):
        sid = str(row["snippet_id"])
        if sid not in seen:
            seen.add(sid)
            out.append(row)
    return out


def _clip_audio(database: Any, snippet: dict) -> Optional[str]:
    from services.lend_your_ear import _audio
    return _audio(database, {"source": "community", "snippet": snippet})


def answered_clip_ids(database: Any, listener_id: str) -> set[str]:
    """Every clip this listener answered in the queue: the snippet of a
    community clip, the corpus id of a training clip."""
    return {str(c) for c in database.list_community_answered_clip_ids(str(listener_id)) or []}


def community_clips(database: Any, *, listener_id: str, answered: set[str],
                    limit: int) -> list[dict]:
    """Up to `limit` community clips the listener may hear, in the queue's
    order. THE ONE DOOR for another speaker's moment into a peer queue:
    only a Take shared under the per-Take consent (``community_clips_live``)
    is read here. Audio only (AC-9)."""
    me = str(listener_id)
    general_id, private_ids = _hearable(database, me)
    hearable = ([general_id] if general_id else []) + sorted(private_ids)
    rows = [r for r in database.list_community_clips_live(hearable) or [] if isinstance(r, dict)]
    ids = list(dict.fromkeys(str(r["snippet_id"]) for r in rows if r.get("snippet_id")))
    labels = (database.get_confidence_labels_by_snippet_ids(ids) or {}) if ids else {}
    clips: list[dict] = []
    for row in order_community_clips(rows, listener_id=me, answered=answered,
                                     labels=labels, private_ids=private_ids):
        if len(clips) >= limit:
            break
        snippet = database.get_snippet_by_id(str(row["snippet_id"]))
        if not isinstance(snippet, dict) or snippet.get("is_skipped"):
            continue
        if snippet.get("user_id") and str(snippet.get("user_id")) == me:
            continue
        audio = _clip_audio(database, snippet)
        if not audio:
            continue
        clips.append({"clip_id": str(row["snippet_id"]), "source": "community",
                      "audio_ref": audio,
                      "start_offset_ms": snippet.get("start_offset_ms"),
                      "duration_ms": snippet.get("duration_ms")})
    return clips


def queue_for(database: Any, *, listener_id: str, rng: Any = None) -> tuple[int, dict]:
    """The listener's queue: the walk's other voices, at most three,
    community clips first, then training clips (Q-B11 A), served by the
    Lend your ear engine. Audio only (AC-9)."""
    if not communities_enabled():
        return _not_found()
    from services.lend_your_ear import other_voices
    return 200, {"clips": other_voices(database, listener_id=str(listener_id), rng=rng)}


# ── the answer ────────────────────────────────────────────────────────────

def answer(database: Any, *, listener_id: str, body: Any) -> tuple[int, dict]:
    """One answer per person per clip. A community clip's answer is a peer
    rating and a peer label where the quorum still takes raters; a training
    clip's answer stays here alone. Never the listener's own clip."""
    from services.state_ratings import validate_rating
    if not communities_enabled():
        return _not_found()
    fields: dict = body if isinstance(body, dict) else {}
    clip_id = fields.get("clip_id")
    if not isinstance(clip_id, str) or not _is_uuid(clip_id):
        return 400, {"code": "INVALID_INPUT"}
    row, err = validate_rating({"state_id": "confidence", "value": fields.get("value")})
    if err or row is None:
        return 400, {"code": "INVALID_INPUT"}
    me = str(listener_id)
    answered = answered_clip_ids(database, me)
    shared = [r for r in database.list_community_clips_for_snippet(clip_id) or []
              if isinstance(r, dict)]
    if shared:
        return _answer_community(database, listener_id=me, clip_id=clip_id, rows=shared,
                                 answered=answered, row=row)
    corpus = database.get_corpus_clip(clip_id)
    if not isinstance(corpus, dict) or not corpus.get("active", True):
        return 404, {"code": "CLIP_NOT_FOUND"}
    if clip_id in answered:
        return 409, {"code": "ALREADY_ANSWERED"}
    # A training clip is a licensed corpus clip, not a snippet: no quorum,
    # no label, no Take. Its answer is kept beside the community answers
    # (clip_source 'corpus', no community, no snippet, no label; the table's
    # checks hold that shape), so a listener's queue history is one table and
    # nothing about it can be mistaken for a peer label on a speaker's Take.
    saved = database.insert_community_answer({
        "clip_source": "corpus", "listener_user_id": me, "corpus_clip_id": clip_id,
        "value": row["value"], "label_id": None, "label_outcome": None})
    if saved is None:
        return 409, {"code": "ALREADY_ANSWERED"}
    if not isinstance(saved, dict):
        return 500, {"code": "V2_ERROR"}
    return 200, {"recorded": True}


def _answer_community(database: Any, *, listener_id: str, clip_id: str, rows: list[dict],
                      answered: set[str], row: dict) -> tuple[int, dict]:
    from services.lend_your_ear import _peer_label
    if any(str(r.get("owner_user_id")) == listener_id for r in rows):
        return 403, {"code": "OWN_CLIP"}
    general_id, private_ids = _hearable(database, listener_id)
    mine = [r for r in rows if str(r.get("community_id")) in private_ids]
    general = [r for r in rows if general_id and str(r.get("community_id")) == general_id]
    if not mine and not general:
        return 404, {"code": "CLIP_NOT_FOUND"}
    heard = (mine or general)[0]
    if clip_id in answered:
        return 409, {"code": "ALREADY_ANSWERED"}
    label_id, outcome = _peer_label(database, listener_id=listener_id,
                                    snippet_id=clip_id, row=row)
    saved = database.insert_community_answer({
        "clip_source": "community", "community_id": str(heard.get("community_id")),
        "listener_user_id": listener_id, "snippet_id": clip_id,
        "take_session_id": str(heard.get("take_session_id")),
        "value": row["value"], "label_id": label_id, "label_outcome": outcome})
    if saved is None:
        return 409, {"code": "ALREADY_ANSWERED"}
    if not isinstance(saved, dict):
        return 500, {"code": "V2_ERROR"}
    return 200, {"recorded": True}
