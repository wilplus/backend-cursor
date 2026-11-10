"""A host's model gathers its examples from the Takes people send them
(MOD-02; N563 item 4, N575, N582 item 4, N528 item 10, N566 items 5 and 6).

Which Takes: those a speaker sent to the model's owner in their chat (a
message of kind ``take``, services/take_sends.py), so a model learns only
from what reaches its host's chat (N582 item 4). Which moments: each
moment of the Take (its snippets), as its words; its clip is played to a
teacher by a short-lived signed link when it is served
(``model_launchpad_store.with_clips``). No recording is copied, and
recordings never leave WillpowerLab (N528 item 10).

THE CONSENT AND PROCESSING-AUTHORIZATION PATH, checked for every speaker on
every run, before anything is written:
  1. the speaker's training yes ("Help improve WillpowerLab") is on
     (``get_mlc2_training_consent_status_v2``, migration 0373), and only
     Takes recorded after they gave it are taken (``takes_offered_to_teachers``);
  2. no deletion or termination has stopped their learning
     (``services.account_deletion.learning_stopped``);
  3. their processing authorization is current
     (``ProcessingAuthorizationService.require_current``, when the gate is
     enforced).
A speaker who fails any of them gives nothing; a speaker whose training yes
is off ("Turn off training?") has every example from their Takes taken out
of every model on the next run, with the answers given on them.

No provider call: the Takes were transcribed through the
processing-authorization path when they were recorded, and this job only
reads their words.

The sealed exam (N566 items 5 and 6): whole speakers at a time go to a
model's exam until it holds 100 cases, so no speaker is on both sides.

Runs from the periodic sweep (``services/pipeline_jobs.py``): a withdrawn
yes is let go in every model each run, however many models there are
(N615 item 2); the gathering is a bounded number of models a run. It is
safe to run twice: a moment goes into a
model once (0520's ``ai_model_examples_take_moment_once``).
"""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

from services import model_launchpad as rules
from services import model_setup as S
from services.chats import MEMBERS, MESSAGES, _rows, _table

logger = logging.getLogger(__name__)

MODELS, EXAMPLES = "ai_models", "ai_model_examples"
#: Moments read from one Take, at most; a Take has a few dozen.
MAX_MOMENTS = 60


def _received_takes(database: Any, owner: str) -> list[dict]:
    """[{"speaker_id", "take_id"}] the Takes others sent the owner."""
    mine = _rows(_table(database, MEMBERS).select("id,thread_id").eq("user_id", owner))
    if not mine:
        return []
    my_ids = {str(m["id"]) for m in mine}
    threads = [str(m["thread_id"]) for m in mine]
    members = {str(m["id"]): m for m in _rows(_table(database, MEMBERS).select("id,thread_id,user_id")
                                               .in_("thread_id", threads))}
    out, seen = [], set()
    for msg in _rows(_table(database, MESSAGES).select("author_member_id,meta,kind")
                     .in_("thread_id", threads).eq("kind", "take")):
        author = members.get(str(msg.get("author_member_id") or ""))
        take = (msg.get("meta") or {}).get("take_session_id")
        if not author or str(author["id"]) in my_ids or not author.get("user_id") or not take:
            continue
        key = (str(author["user_id"]), str(take))
        if key not in seen:
            seen.add(key)
            out.append({"speaker_id": key[0], "take_id": key[1]})
    return out


def speaker_may_teach(database: Any, speaker_id: str) -> dict:
    """The consent and processing-authorization path for one speaker:
    {"ok": bool, "granted_at": iso | None}."""
    no = {"ok": False, "granted_at": None}
    try:
        from services.rings import principal_for_user
        principal = principal_for_user(speaker_id, database=database)
    except Exception:
        logger.warning("model examples: no principal speaker=%s", speaker_id, exc_info=True)
        return no
    if not principal:
        return no
    consent = rules.take_consent(database, principal)
    if not consent.get("active"):
        return no
    try:
        from services.account_deletion import learning_stopped
        if learning_stopped(database, principal):
            return no
        from services.processing_authorization import (
            ProcessingAuthorizationError, ProcessingAuthorizationService)
        authorization = ProcessingAuthorizationService(database)
        if authorization.enforced:
            acquisition = authorization.resolve_acquisition_principal(principal, user_id=speaker_id)
            authorization.require_current(acquisition, operation="ai_conversation")
    except ProcessingAuthorizationError:
        return no
    except Exception:
        logger.warning("model examples: the path could not be checked speaker=%s", speaker_id,
                       exc_info=True)
        return no
    return {"ok": True, "granted_at": consent.get("granted_at")}


def _moments(database: Any, take_id: str) -> list[dict]:
    try:
        clips = database.get_snippets_by_session(take_id) or []
    except Exception:
        logger.warning("model examples: the Take's moments could not be read take=%s", take_id,
                       exc_info=True)
        return []
    return [c for c in clips if isinstance(c, dict) and c.get("id")
            and str(c.get("transcript") or "").strip()][:MAX_MOMENTS]


def _recorded_at(database: Any, take_id: str) -> str:
    try:
        session = database.v2_get_session_by_id(take_id) or {}
    except Exception:
        logger.warning("model examples: the Take could not be read take=%s", take_id, exc_info=True)
        session = {}
    return str(session.get("created_at") or "")


def _let_go(database: Any, model: dict, have: list[dict], path: dict[str, dict]) -> int:
    """Every example of a speaker who no longer may teach leaves the model,
    with the answers given on it."""
    removed = 0
    for speaker, ok in path.items():
        theirs = [e for e in have if str(e.get("speaker_id")) == speaker]
        if not ok["ok"] and theirs:
            _table(database, EXAMPLES).delete().eq("model_id", model["id"]).eq("source", "takes") \
                .eq("speaker_id", speaker).execute()
            removed += len(theirs)
    return removed


def _example(model: dict, speaker: str, take_id: str, clip: dict) -> dict:
    return {"model_id": model["id"], "source": "takes", "private": False, "speaker_id": speaker,
            "take_id": take_id, "snippet_id": str(clip["id"]), "kind": None,
            # What a teacher's screen reads: the words, and (added when it is
            # served, signed and short-lived) the clip. Never the Take, the
            # snippet or the speaker: those are columns no teacher receives.
            "content": {"text": str(clip.get("transcript") or "").strip()[:4000]}}


def _new_moments(database: Any, model: dict, takes: list[dict], path: dict[str, dict],
                 known: set[str]) -> list[dict]:
    """The moments not yet in the model, of Takes recorded after the
    speaker's training yes."""
    offered: dict[str, list[dict]] = defaultdict(list)
    for t in takes:
        if path.get(t["speaker_id"], {}).get("ok"):
            offered[t["speaker_id"]].append({**t, "recorded_at": _recorded_at(database, t["take_id"])})
    new: list[dict] = []
    for speaker, ts in offered.items():
        yes = {"active": True, "granted_at": path[speaker]["granted_at"]}
        for t in rules.takes_offered_to_teachers(ts, yes):
            for clip in _moments(database, t["take_id"]):
                if str(clip["id"]) not in known:
                    known.add(str(clip["id"]))
                    new.append(_example(model, speaker, t["take_id"], clip))
    return new


def _insert(database: Any, model: dict, have: list[dict], new: list[dict]) -> int:
    """The new moments in, whole speakers to the sealed exam until it holds
    100 (a speaker already on one side stays there)."""
    exam_speakers = {str(e["speaker_id"]) for e in have if e.get("in_exam")}
    seen_speakers = {str(e["speaker_id"]) for e in have}
    fresh = [{**e, "id": e["snippet_id"]} for e in new if e["speaker_id"] not in seen_speakers]
    to_exam = S.exam_split(fresh, sum(1 for e in have if e.get("in_exam")))
    added = 0
    for e in new:
        row = {**e, "in_exam": e["snippet_id"] in to_exam or e["speaker_id"] in exam_speakers}
        try:
            _table(database, EXAMPLES).insert(row).execute()
            added += 1
        except Exception:  # noqa: BLE001 -- the once-index refuses a repeat
            logger.warning("model examples: a moment not added model=%s", model["id"], exc_info=True)
    return added


def gather_for_model(database: Any, model: dict) -> dict:
    """One model's run: take out what a withdrawn yes no longer allows, then
    add the new moments of the Takes its owner received."""
    owner = str(model.get("owner_id") or "")
    kind = (model.get("recipe") or {}).get("input") or "voice"
    if not owner or kind not in ("voice", "text"):
        return {"added": 0, "removed": 0}
    have = _rows(_table(database, EXAMPLES).select("id,snippet_id,speaker_id,in_exam,source")
                 .eq("model_id", model["id"]).eq("source", "takes"))
    takes = _received_takes(database, owner)
    speakers = sorted({t["speaker_id"] for t in takes} | {str(e["speaker_id"]) for e in have if e.get("speaker_id")})
    path = {s: speaker_may_teach(database, s) for s in speakers}
    removed = _let_go(database, model, have, path)
    kept = [e for e in have if path.get(str(e.get("speaker_id")), {}).get("ok")]
    new = _new_moments(database, model, takes, path, {str(e["snippet_id"]) for e in kept if e.get("snippet_id")})
    return {"added": _insert(database, model, kept, new) if new else 0, "removed": removed}


#: Rows read a request: PostgREST answers at most a thousand without a range.
PAGE = 500


def _all(make_query: Any) -> list[dict]:
    """Every row a query matches, a page at a time (``make_query`` builds a
    fresh query for each page), so nothing is past the server's cap."""
    out: list[dict] = []
    start = 0
    while True:
        rows = _rows(make_query().range(start, start + PAGE - 1))
        out.extend(rows)
        if len(rows) < PAGE:
            return out
        start += PAGE


def _every_take_speaker(database: Any) -> list[str]:
    """Every speaker with an example from their Takes in any model."""
    rows = _all(lambda: _table(database, EXAMPLES).select("speaker_id").eq("source", "takes"))
    return sorted({str(r["speaker_id"]) for r in rows if r.get("speaker_id")})


def let_go_everywhere(database: Any) -> int:
    """A speaker who no longer may teach leaves every model at once, however
    many models hold their Takes (N575, N615 item 2): each speaker is checked
    once a run, and their examples are taken out of all models together.
    The gathering below is bounded; this is not."""
    removed = 0
    for speaker in _every_take_speaker(database):
        if speaker_may_teach(database, speaker)["ok"]:
            continue
        gone = _rows(_table(database, EXAMPLES).delete().eq("source", "takes").eq("speaker_id", speaker))
        removed += len(gone)
    return removed


def sweep(*, database: Any = None, limit: int = 20) -> dict:
    """First every withdrawn yes, in every model; then every model that
    learns gathers, up to ``limit`` a run. Never raises."""
    if database is None:
        from services.db import db as database
    out = {"models": 0, "added": 0, "removed": 0}
    try:
        out["removed"] += let_go_everywhere(database)
    except Exception:
        logger.warning("model examples: a withdrawn yes could not be let go everywhere", exc_info=True)
    try:
        models = [m for m in _all(lambda: _table(database, MODELS).select("id,owner_id,status,recipe"))
                  if m.get("status") in ("learning", "ready")][:limit]
    except Exception:
        logger.warning("model examples: the models could not be read", exc_info=True)
        return out
    for m in models:
        try:
            got = gather_for_model(database, m)
        except Exception:
            logger.warning("model examples: a run failed model=%s", m.get("id"), exc_info=True)
            continue
        out["models"] += 1
        out["added"] += got["added"]
        out["removed"] += got["removed"]
    return out

