"""One AI clip per practice, made only in the voice Exercise lane
(founder lock 2026-10-12, docs/FOUNDER-LOCK-ai-voice-practice-2026-10-12.md).

  prewarm    the bake's job (founder 2026-10-15, B: "start it the moment you
             know it will be needed"): at the end of the bake the exercise
             moment is known, so the practice row is opened server-side,
             exactly as the walk would open it, and the clip is started
             then. The walk's own ask (below) finds the row and the clip
             already there.
  ensure     the walk asks for the clip when it enters the lane: when the
             Exercise screen opens (no video fits) or when Practise is
             tapped (a video fits), or when a clearer version is
             practised (founder 2026-10-18: the clip says the accepted
             words, shown only after a try that is not yet). Praise never
             gets here.
             One cycle row per practice (UNIQUE), so a repeated request never
             makes a second clip. Since the prewarm this is the fallback.
  generate   the background job: choose the exercise, build the request,
             check the limits, call ElevenLabs through the permit, check the
             clip (words re-heard through the existing Whisper permit), store
             it. A failed check is never shown. A voice still on its way
             from Take 1 is waited for: a bounded, delayed retry.
  state      what the walk may know: video or AI clip, and the clip's state
             and short-lived link when it passed, with the one signed
             sentence on what the clip does differently and why it sounds
             better (WIL-82, founder 2026-10-16). No id, setting, score or
             check result ever leaves.
  note_*     a play, and the next try's outcome on the one problem.

Job states (cycle ``status``): pending → analyzing → choosing_exercise →
generating → validating → completed | failed | skipped.
"""
from __future__ import annotations

import hashlib
import logging
import time
import uuid
from typing import Any, Optional

from config import Config
from services import ai_voice_store as store

_log = logging.getLogger(__name__)

#: At most this many AI clips per exercise (the walk counts appearances).
MAX_APPEARANCES = 3
LINK_SECONDS = 900
#: The library's problem names a video must target to be "the same
#: problem" (confident_voice_practice._SIGNAL_PROBLEM_TAGS). Stress has no
#: library name yet, so stress always takes the AI clip.
PROBLEM_TAGS = {"pace": {"rushing"}, "pause": {"rushing"}, "stress": set(), "fillers": set()}
#: A voice not ready at generate time (the clone still on its way from
#: Take 1) is asked for again after this many seconds, at most this many
#: times; the count rides the cycle row's ``generation_metadata`` (no
#: migration). After that the next walk ask retries, as before.
NO_VOICE_RETRY_SECONDS = 30
NO_VOICE_MAX_WAITS = 5
#: The guards the walk's routes put before a practice and before a clip
#: (routes/v2/user_sessions.py, routes/v2/ai_voice.py); the prewarm, which
#: reaches neither route, asks the same questions itself.
PRACTICE_PURPOSE = "personalized_exercise_recommendation"
PRACTICE_CHOICE = "personalised_practice"


def principal_for(database: Any, take_id: Any, user_id: Any) -> str:
    """The acquisition principal the permits run under (as the practice
    transcription resolves it); "" while the gate is off."""
    from services.processing_authorization import ProcessingAuthorizationService
    authorization = ProcessingAuthorizationService(database)
    if not authorization.enforced:
        return ""
    session = (database.v2_get_session_by_id(str(take_id)) or {}) if take_id else {}
    return authorization.resolve_acquisition_principal(
        str(session.get("owner_principal_id") or ""),
        user_id=str(user_id or "") or None)


# ── the lane and the video rule ──────────────────────────────────────────

def in_voice_lane(practice: dict) -> bool:
    """A practice the AI clip may follow: a library exercise, the moment's
    own words (stored as ``plain``), or the Clearer version (a ``rewrite``,
    founder 2026-10-18: its words first, then the voice). A row without a
    kind is an exercise, as practice_adoption reads it."""
    return str((practice or {}).get("kind") or "exercise") in ("exercise", "plain", "rewrite")


def _coach_picked(practice: dict) -> bool:
    from services.confident_voice_practice import COACH_REQUEST_POLICY_VERSION
    assessment = practice.get("machine_assessment") or {}
    return assessment.get("matching_policy_version") == COACH_REQUEST_POLICY_VERSION


def demo_for(database: Any, practice: dict, selection: Optional[dict]) -> str:
    """``video`` · ``ai_voice`` · ``none`` for the Exercise screen.

    The video stays when a coach chose it, or when it fits EXACTLY and its
    main target is the problem picked; otherwise the AI clip takes its place.
    """
    if not in_voice_lane(practice):
        return "none"
    has_video = (str(practice.get("kind")) == "exercise"
                 and bool((practice.get("exercise_snapshot") or {}).get("explanation_video_url")))
    if has_video and _coach_picked(practice):
        return "video"
    if selection is None:
        return "video" if has_video else "none"
    if has_video and (practice.get("machine_assessment") or {}).get("exercise_fit") == "exact":
        from services.confident_voice_practice import exercise_targets
        exercise = database.get_active_diagnostic_exercise(str(practice.get("exercise_id")))
        main, _secondary = exercise_targets(exercise)
        if main & PROBLEM_TAGS.get(str(selection.get("exercise")), set()):
            return "video"
    return "ai_voice"


# ── ensure / generate ────────────────────────────────────────────────────

def ensure(database: Any, practice: dict, *, user_id: str, principal_id: str,
           run=None, sign=None, queue: Optional[str] = None) -> dict:
    """Start (once) the clip for this practice and return ``state``.

    ``queue`` is the lane the job rides (the pipeline's unless told other);
    a job already started by the prewarm is found, never started again."""
    from services.ai_voice_clone import available_to
    if not available_to(user_id) or not in_voice_lane(practice) \
            or _voice_turned_off(database, str(user_id)):
        return {"demo": "video" if _has_video(practice) else "none", "clip": None}
    cycle, created = store.create_cycle(database, {
        "practice_id": str(practice["id"]), "owner_user_id": str(user_id),
        "take_session_id": practice.get("take_session_id"),
        "snippet_id": practice.get("snippet_id"), "status": "pending"})
    if cycle is None:
        return {"demo": "video" if _has_video(practice) else "none", "clip": None}
    retry_waiting = cycle.get("failure_kind") == "no_voice" and (
        cycle.get("status") == "pending"
        or (cycle.get("status") == "skipped" and _voice_on_its_way(database, str(user_id))))
    if retry_waiting and cycle.get("status") == "skipped":
        # It stopped waiting; a voice is now ready or being made.
        store.update_cycle(database, str(cycle["id"]), {"status": "pending"})
    if created or retry_waiting:
        args = (str(cycle["id"]), principal_id, queue)
        if run is not None:
            run(*args[:2])
        else:
            _start(args, cycle_id=str(cycle["id"]), queue=queue)
        cycle = store.get_cycle(database, str(practice["id"])) or cycle
    return state(database, practice, cycle, sign=sign)


def _has_video(practice: dict) -> bool:
    return (str((practice or {}).get("kind")) == "exercise"
            and bool(((practice or {}).get("exercise_snapshot") or {}).get("explanation_video_url")))


def _start(args: tuple, *, cycle_id: str, queue: Optional[str] = None,
           delay_seconds: int = 0, attempt: int = 0) -> bool:
    """Queue ``generate`` (a delayed one for a voice still on its way);
    without a queue it runs on a thread, as the walk's ask always has."""
    from services.job_queue import enqueue
    job_id = f"ai-voice-clip-{cycle_id}" + (f"-wait{attempt}" if attempt else "")
    if enqueue("services.ai_voice_clip.generate", *args, rq_job_id=job_id,
               queue=queue, delay_seconds=delay_seconds):
        return True
    import threading
    if delay_seconds > 0:
        timer = threading.Timer(delay_seconds, generate, args=args)
        timer.daemon = True
        timer.name = "ai-voice-clip-wait"
        timer.start()
        return True
    threading.Thread(target=generate, args=args, daemon=True,
                     name="ai-voice-clip").start()
    return True


# ── the prewarm: the clip starts when the exercise moment is known ───────

def exercise_moments_of(block: Any) -> list[dict]:
    """The voice-exercise moments in a stored feedback block, read exactly as
    the walk reads them (frontend `lockedMoments` and `practiseOpening`, lock
    2026-10-12): a moment that is not praised and carries `practice_prompt`
    is practised as a clearer version when a rewrite rides it (its clip is
    asked when the speaker accepts it, never prewarmed: until then the
    words are not chosen), else on its exercise, else said again. One or
    two per Take (founder 2026-10-20: both shown moments are corrected when
    both are weak). The stored rows are the client's rows
    (`strip_internal_evidence`), so this reads the same keys.

    Each is ``{snippet_id, take_session_id, kind, exercise_id, evidence,
    feedback_id}``; [] when the Take has no voice exercise.
    """
    found: list[dict] = []
    for group in _moment_groups(block):
        green = any(r.get("bookmark_tier") == "confident" for r in group)
        marked = any(r.get("practice_prompt") is True for r in group)
        if green or not marked:
            continue
        moment = _practise_of(group)
        if moment:
            found.append(moment)
    return found


def practised_moments_of(block: Any) -> list[dict]:
    """Every moment the walk practises with the AI clip, in page order: the
    voice-exercise moments (:func:`exercise_moments_of`) and each praised
    moment the server marked `confident_practice` (founder 2026-10-23,
    N122: "do we practice the confident moments? I think yes we should!"),
    practised as the moment said again (`plain`)."""
    found = list(exercise_moments_of(block))
    for group in _moment_groups(block):
        if not any(r.get("bookmark_tier") == "confident" and r.get("confident_practice") is True
                   for r in group):
            continue
        source = next((r for r in group if _practisable(r)), None)
        if source is None:
            continue
        found.append({
            "snippet_id": str(source["snippet_id"]),
            "take_session_id": str(source["evidence"]["take_session_id"]),
            "kind": "plain", "exercise_id": None,
            "evidence": dict(source["evidence"]),
            "feedback_id": str(source.get("id") or "") or None,
        })
    return found


def exercise_moment_of(block: Any) -> Optional[dict]:
    """The first of :func:`exercise_moments_of`, or None."""
    return next(iter(exercise_moments_of(block)), None)


def _moment_groups(block: Any) -> list[list[dict]]:
    """The walk's moments: rows by block, else by where they start."""
    rows = [r for r in ((block or {}).get("changes") or []) if isinstance(r, dict)]
    groups: dict[str, list[dict]] = {}
    for row in sorted(rows, key=lambda r: int((r.get("span") or {}).get("start") or 0)):
        start = (row.get("span") or {}).get("start")
        key = f"b:{row['block_id']}" if row.get("block_id") else f"s:{start}"
        groups.setdefault(key, []).append(row)
    return list(groups.values())


def _practise_of(group: list[dict]) -> Optional[dict]:
    """What the walk opens on the exercise moment: nothing when a clearer
    version rides it, else its exercise, else the moment said again."""
    if any(_rides_rewrite(r) for r in group):
        return None
    exercise = next((r for r in group if _carries_exercise(r)), None)
    marked = [r for r in group if r.get("practice_prompt") is True and _practisable(r)]
    source = exercise or next(iter(marked), None) \
        or next((r for r in group if _practisable(r)), None)
    if source is None:
        return None
    offer = (exercise or {}).get("practice_exercise") or {}
    return {
        "snippet_id": str(source["snippet_id"]),
        "take_session_id": str(source["evidence"]["take_session_id"]),
        "kind": "exercise" if exercise else "plain",
        "exercise_id": str(offer.get("exercise_id")) if exercise else None,
        "evidence": dict(source["evidence"]),
        "feedback_id": str(source.get("id") or "") or None,
    }


def _practisable(row: dict) -> bool:
    evidence = row.get("evidence")
    return bool(row.get("snippet_id")) and isinstance(evidence, dict) \
        and bool(evidence.get("take_session_id"))


def _rides_rewrite(row: dict) -> bool:
    return (row.get("kind") == "replace" and bool(str(row.get("proposed_text") or "").strip())
            and (row.get("feedback_family") == "rewrite_clarity" or row.get("open_card") == "rewrite"))


def _carries_exercise(row: dict) -> bool:
    offer = row.get("practice_exercise")
    if not isinstance(offer, dict) or not offer.get("exercise_id") or not _practisable(row):
        return False
    if (row.get("open_card") != "exercise" and offer.get("chosen_by_coach") is not True
            and row.get("practice_prompt") is not True):
        return False
    return bool(str(offer.get("passage") or row.get("quote") or "").strip())


def _voice_on_its_way(database: Any, user_id: str) -> bool:
    """A voice that is ready, or one being made (the retry in ``generate``
    waits for it). None, failed, off or deleted: no clip is coming."""
    row = store.get_clone(database, user_id)
    return bool(row and row.get("enabled", True)
                and row.get("status") in ("creating", "ready"))


def _practice_allowed(database: Any, principal_id: str) -> Optional[str]:
    """The reason the walk's routes would refuse, or None."""
    from services.processing_authorization import ProcessingAuthorizationService
    from services.processing_purposes import purpose_is_operational
    if not purpose_is_operational(PRACTICE_PURPOSE):
        return "purpose_not_operational"
    service = ProcessingAuthorizationService(database)
    allowed = (service.choice_permitted(principal_id, PRACTICE_CHOICE)
               if principal_id else not service.enforced)
    return None if allowed else "consent_choice_off"


def prewarm(user_id: str, take_session_id: str, snippet_id: str, principal_id: str,
            start: dict, queue: Optional[str] = None, *, database: Any = None,
            run=None) -> str:
    """The bake's job: open the exercise moment's practice as the walk
    would and start its clip. Never raises; returns what it did.

    ``start`` is ``exercise_moment_of``'s answer: the kind the walk would
    open (``plain``, or ``exercise`` with the offered exercise id), the
    exact evidence and the feedback item. A refusal the practice route
    would give is a quiet skip, so the walk later opens exactly what it
    always has."""
    from services.ai_voice_clone import available_to
    from services.practice_start import start_practice
    from services.refusal import Refusal
    if database is None:
        from services.db import db as database
    try:
        if not available_to(user_id):
            return "skipped:off"
        if not _voice_on_its_way(database, str(user_id)):
            _log.info("ai voice: prewarm skipped, no voice take=%s", take_session_id)
            return "skipped:no_voice"
        refused = _practice_allowed(database, principal_id)
        if refused:
            _log.info("ai voice: prewarm skipped take=%s: %s", take_session_id, refused)
            return f"skipped:{refused}"
        body: dict[str, Any] = {"kind": str(start.get("kind") or "plain"),
                                "evidence": dict(start.get("evidence") or {})}
        if body["kind"] == "exercise":
            body["exercise_id"] = start.get("exercise_id")
        elif start.get("feedback_id"):
            body["feedback_id"] = start["feedback_id"]
        try:
            practice, created = start_practice(
                database, snippet_id=str(snippet_id), body=body,
                user_id=str(user_id), answer=None)
        except Refusal as refusal:
            _log.info("ai voice: prewarm skipped take=%s: practice refused %s",
                      take_session_id, refusal.body.get("code"))
            return f"skipped:{refusal.body.get('code')}"
        if str(practice.get("take_session_id")) != str(take_session_id):
            return "skipped:other_take"
        # No link is issued here: nobody receives this answer, the walk
        # signs its own when it asks. The clip's state is all that is read.
        out = ensure(database, practice, user_id=str(user_id), principal_id=principal_id,
                     run=run or (lambda cid, p: generate(cid, p, queue, database=database)),
                     queue=queue, sign=lambda _bucket, _key: "stored")
        clip = out.get("clip") or {}
        _log.info("ai voice: prewarm take=%s practice=%s %s clip=%s",
                  take_session_id, practice.get("id"),
                  "opened" if created else "resumed", clip.get("state") or "none")
        return str(clip.get("state") or "none")
    except Exception as error:  # noqa: BLE001 — the walk's own ask is the fallback
        _log.warning("ai voice: prewarm failed take=%s: %s", take_session_id,
                     type(error).__name__, exc_info=True)
        return "failed"


def _choose(database: Any, practice: dict, cycle: dict) -> tuple[Optional[dict], dict]:
    from services.ai_voice_severity import own_medians, select
    snippet = database.get_snippet_by_id(str(practice.get("snippet_id"))) or {}
    take = database.get_snippets_by_session(str(practice.get("take_session_id"))) or []
    medians = own_medians(take)
    history = [row for row in store.owner_cycles(database, str(cycle["owner_user_id"]))
               if str(row.get("id")) != str(cycle["id"])]
    sentence = str(practice.get("exact_passage") or snippet.get("transcript") or "")
    # On a plan, the level's own problem where the clip shows it (G7, N209).
    from services.plan_walk import AI_PROBLEM, level_of_practice
    selection = select(snippet, medians, sentence=sentence,
                       seed=str(practice["id"]), history=history,
                       prefer=AI_PROBLEM.get(level_of_practice(database, practice) or ""))
    before = {k: (snippet.get("metrics") or {}).get(k)
              for k in ("wpm", "pause_ratio", "dynamic_db")}
    from services.ai_voice_severity import fillers_per_100
    before["fillers_per_100"] = fillers_per_100(sentence)
    return selection, {"before": before, "medians": medians,
                       "sentence": sentence, "snippet": snippet}


class _Job:
    """One clip job's context: what it reads, what it may call, its clock."""

    def __init__(self, database: Any, cycle: dict, practice: dict, principal_id: str,
                 tools: dict):
        self.db, self.cycle, self.practice = database, cycle, practice
        self.cycle_id, self.owner = str(cycle["id"]), str(cycle["owner_user_id"])
        self.principal_id, self.tools = principal_id, tools
        self.clock: dict[str, int] = {}
        self.t0 = self.mark = time.monotonic()

    def lap(self, name: str) -> None:
        now = time.monotonic()
        self.clock[name] = int((now - self.mark) * 1000)
        self.mark = now

    def update(self, fields: dict) -> None:
        store.update_cycle(self.db, self.cycle_id, fields)

    def end_clock(self) -> dict[str, int]:
        """Each stage, the job's total, and end to end: since the walk asked
        for the clip (the cycle's creation) and since the Take was saved."""
        self.clock["total"] = int((time.monotonic() - self.t0) * 1000)
        for name, since in (("since_request", self.cycle.get("created_at")),
                            ("since_take_saved", _take_saved_at(self.db, self.practice))):
            waited = _ms_since(since)
            if waited is not None:
                self.clock[name] = waited
        return self.clock

    def fail(self, kind: str, code: str) -> str:
        self.update({"status": "failed", "failure_kind": kind,
                     "failure_code": code[:80], "latency_ms": self.end_clock()})
        _log.info("ai voice: clip not shown cycle=%s kind=%s code=%s",
                  self.cycle_id, kind, code)
        return "failed"


def generate(cycle_id: str, principal_id: str, queue: Optional[str] = None, *,
             database: Any = None, provider: Any = None, transcribe=None,
             put_object=None, decode=None, provider_usage=None) -> str:
    """The clip job; returns the cycle's end status. ``queue`` is the lane
    it rode, so a wait for the voice is queued in the same lane."""
    if database is None:
        from services.db import db as database
    cycle = _cycle_by_id(database, cycle_id)
    if not cycle or cycle.get("status") in ("completed", "failed", "skipped", "deleted"):
        return str((cycle or {}).get("status") or "missing")
    if not store.claim_cycle(database, cycle_id):
        return "already_running"
    practice = database.get_confident_voice_practice(
        str(cycle["practice_id"]), str(cycle["owner_user_id"])) or {}
    job = _Job(database, cycle, practice, principal_id, {
        "provider": provider, "transcribe": transcribe, "put_object": put_object,
        "decode": decode, "provider_usage": provider_usage, "queue": queue})
    try:
        selection, context = _choose(database, practice, cycle)
    except Exception as error:  # noqa: BLE001 — recorded as the cycle's failure
        _log.warning("ai voice: choosing failed cycle=%s", cycle_id, exc_info=True)
        return job.fail("internal", type(error).__name__)
    job.lap("choose_exercise")
    job.update({"status": "choosing_exercise",
                "demo": demo_for(database, practice, selection),
                "selection": selection, "metrics_before": context["before"]})
    if selection is None:
        job.update({"status": "skipped", "failure_kind": "no_exercise",
                    "latency_ms": job.end_clock()})
        return "skipped"
    return _make(job, selection, context)


def _make(job: _Job, selection: dict, context: dict) -> str:
    from services.ai_voice_clone import voice_for
    from services.ai_voice_limits import clip_refusal
    from services.ai_voice_prompt import PromptRejected, build
    voice_id = voice_for(job.db, job.owner)
    if not voice_id and _no_voice_coming(job.db, job.owner):
        # Off, failed, or the Take could not make one (too short, too
        # noisy): no clip is coming, so the walk is not left on the dots.
        return _no_voice(job)
    if not voice_id:
        # The clone may still be on its way from Take 1: ask again in a
        # little while, a bounded number of times; the walk's next ask
        # also retries, as it always has.
        return _wait_for_voice(job, selection)
    try:
        request = build(sentence=context["sentence"], exercise=selection,
                        practice_id=str(job.practice["id"]))
    except PromptRejected as error:
        return job.fail("internal", str(error))
    refused = clip_refusal(job.db, job.owner,
                           characters=request["metadata"]["characters"],
                           provider_usage=job.tools["provider_usage"])
    if refused:
        return job.fail("limits", refused)
    job.update({"status": "generating", "exercise": selection["exercise"],
                "failure_kind": None, "prepared_text": request["prepared_text"],
                "generation_metadata": request["metadata"]})
    audio, result, failure = _speak_until_checked(job, voice_id, request, selection, context)
    if failure:
        return job.fail("provider", failure)
    if not result or not result["passed"]:
        return job.fail("validation", str((result or {}).get("reason") or "unchecked"))
    return _keep(job, audio, result, selection)


def _wait_for_voice(job: _Job, selection: dict) -> str:
    """Back to ``pending`` with ``no_voice``; the wait count rides
    ``generation_metadata`` (written over by the request's own metadata
    once a voice is there). Within the bound, one delayed retry is queued
    in the lane the job rode."""
    waited = int(((job.cycle.get("generation_metadata") or {}).get("no_voice_waits") or 0))
    waits = waited + 1 if waited < NO_VOICE_MAX_WAITS else waited
    job.update({"status": "pending", "failure_kind": "no_voice",
                "exercise": selection["exercise"],
                "generation_metadata": {"no_voice_waits": waits}})
    if waited < NO_VOICE_MAX_WAITS:
        _start((job.cycle_id, job.principal_id, job.tools.get("queue")),
               cycle_id=job.cycle_id, queue=job.tools.get("queue"),
               delay_seconds=NO_VOICE_RETRY_SECONDS, attempt=waits)
        _log.info("ai voice: no voice yet cycle=%s wait=%d/%d retry_in=%ds",
                  job.cycle_id, waits, NO_VOICE_MAX_WAITS, NO_VOICE_RETRY_SECONDS)
        return "pending"
    _log.info("ai voice: no voice after %d waits cycle=%s; the next ask retries",
              waited, job.cycle_id)
    return _no_voice(job)


def _voice_turned_off(database: Any, user_id: str) -> bool:
    """The speaker's own off (the card's Delete, or ``enabled`` false on
    their row): no clip is asked for, so the walk never shows its place."""
    row = store.get_clone(database, user_id)
    return row is not None and not row.get("enabled", True)


def _no_voice_coming(database: Any, user_id: str) -> bool:
    """A clone row that says no voice will come. No row yet is a clone job
    still queued from the Take, so it is waited for."""
    row = store.get_clone(database, user_id)
    return bool(row) and not _voice_on_its_way(database, user_id)


def _no_voice(job: _Job) -> str:
    """Stopped waiting: the clip reads ``unavailable`` and the walk shows its
    locked Exercise. A later ask with a voice on its way starts it again."""
    job.update({"status": "skipped", "failure_kind": "no_voice",
                "latency_ms": job.end_clock()})
    return "skipped"


def _speak_until_checked(job: _Job, voice_id: str, request: dict, selection: dict,
                         context: dict) -> tuple[bytes, Optional[dict], Optional[str]]:
    """(audio, last check, provider failure). At most 1 + RETRIES clips are
    made: a clip that fails its check is made once more with a new seed
    (founder 2026-10-21, N93; RETRIES is 1). A provider refusal that made
    nothing (429, 5xx) is asked once more and costs no generation."""
    from services.ai_voice_limits import estimated_credits
    from services.ai_voice_validator import validate
    voices = job.tools["provider"] or _voices(job.db, job.principal_id, job.practice)
    budget = 1 + max(0, int(Config.AI_VOICE_GENERATION_RETRIES))
    attempts, characters, audio, result, failure = 0, 0, b"", None, None
    asked_again = False
    snippet = context["snippet"]
    while attempts < budget and failure is None:
        try:
            speech = voices.speak(owner_key=job.owner, voice_id=voice_id, body=request["body"])
        except Exception as error:  # noqa: BLE001 — named; asked once more only if transient
            _log.warning("ai voice: provider refused cycle=%s", job.cycle_id, exc_info=True)
            # A permit the service could not read right now is transient too
            # (PROVIDER_PERMIT_UNAVAILABLE); and a refusal's code, not its
            # class name, is what the cycle keeps, so the row in
            # `ai_voice_cycles` says which check refused (founder 2026-10-20,
            # the clip that never came).
            code = str(getattr(error, "code", "") or "")
            transient = bool(getattr(error, "transient", False)) or code == "PROVIDER_PERMIT_UNAVAILABLE"
            if transient and not asked_again:
                asked_again = True
                time.sleep(1.5)
                continue
            failure = str(getattr(error, "kind", "") or code or type(error).__name__)
            break
        attempts += 1
        characters += int(speech.character_cost or request["metadata"]["characters"])
        audio = speech.audio
        job.lap("generation")
        job.update({"status": "validating"})
        result = validate(
            audio=audio, spoken_words=request["spoken_words"], exercise=selection,
            transcription=_hear(job.db, job.principal_id, job.practice, audio,
                                job.tools["transcribe"]),
            decode=job.tools["decode"],
            original_wpm=(snippet.get("metrics") or {}).get("wpm"),
            original_duration_s=(snippet.get("duration_ms") or 0) / 1000.0 or None)
        job.lap("validation")
        if result["passed"]:
            break
        # One fresh take may land the pause or the pace; a seed change is safe.
        request["body"]["seed"] = (int(request["body"]["seed"]) + 1) % 4294967295
    job.update({"generation_attempts": attempts, "characters": characters,
                "credits_estimated": estimated_credits(characters), "validation": result,
                "generation_metadata": {**request["metadata"],
                                        "provider_retries": int(asked_again)}})
    return audio, result, failure


def _keep(job: _Job, audio: bytes, result: dict, selection: dict) -> str:
    key = f"ai-voice/{job.owner}/{job.practice['id']}/{uuid.uuid4().hex}.mp3"
    try:
        bucket = (job.tools["put_object"] or _put)(key, audio)
    except Exception as error:  # noqa: BLE001 — a clip not stored is not shown
        _log.warning("ai voice: clip not stored cycle=%s", job.cycle_id, exc_info=True)
        return job.fail("internal", type(error).__name__)
    job.lap("store")
    job.end_clock()
    job.update({
        "status": "completed", "storage_provider": "r2", "bucket": bucket,
        "storage_key": key, "content_sha256": hashlib.sha256(audio).hexdigest(),
        "duration_ms": int(float(result["measurements"].get("duration_s") or 0) * 1000),
        "latency_ms": job.clock, "ready_at": store._now()})
    _log.info("ai voice: clip ready cycle=%s exercise=%s total=%dms",
              job.cycle_id, selection["exercise"], job.clock["total"])
    return "completed"


def _ms_since(stamp: Any) -> Optional[int]:
    """Milliseconds from an ISO timestamp to now; None when unreadable."""
    from datetime import datetime, timezone
    try:
        then = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    waited = int((datetime.now(timezone.utc) - then).total_seconds() * 1000)
    return waited if waited >= 0 else None


def _take_saved_at(database: Any, practice: dict) -> Any:
    """When the practised Take finished processing (end of recording to
    saved Take), or None."""
    try:
        session = database.v2_get_session_by_id(str(practice.get("take_session_id"))) or {}
        return session.get("completed_at")
    except Exception:  # noqa: BLE001 — an unread time is simply not reported
        return None


def _cycle_by_id(database: Any, cycle_id: str) -> Optional[dict]:
    try:
        res = (database.client.table(store.CYCLES).select("*")
               .eq("id", str(cycle_id)).limit(1).execute())
        rows = list(res.data or [])
        return rows[0] if rows else None
    except Exception:  # noqa: BLE001 — an unreadable job does nothing
        _log.warning("ai voice: cycle unreadable id=%s", cycle_id, exc_info=True)
        return None


def _coordinates(principal_id: str, practice: dict):
    from services.authorized_provider import ProviderCoordinates
    return ProviderCoordinates(principal_id, str(practice.get("take_session_id") or "") or None, None)


def _voices(database: Any, principal_id: str, practice: dict):
    from services.authorized_voice_provider import AuthorizedVoiceProvider
    return AuthorizedVoiceProvider(database, _coordinates(principal_id, practice))


def _hear(database: Any, principal_id: str, practice: dict, audio: bytes,
          transcribe=None) -> Optional[dict]:
    """The clip re-heard by the existing Whisper, through its permit."""
    try:
        if transcribe is not None:
            return transcribe(audio)
        from services.authorized_provider import AuthorizedProviderAdapter
        adapter = AuthorizedProviderAdapter(database, _coordinates(principal_id, practice))
        return adapter.transcribe_snippet(audio, "ai-voice-check.mp3", language_hint="en")
    except Exception:  # noqa: BLE001 — unheard means unchecked, never shown
        _log.info("ai voice: clip not re-heard", exc_info=True)
        return None


def _put(key: str, audio: bytes) -> str:
    from services.lab_audio_storage import put_lab_audio_bytes
    return put_lab_audio_bytes(key, audio, "audio/mpeg")


# ── what the walk may know ───────────────────────────────────────────────

def state(database: Any, practice: dict, cycle: Optional[dict], *, sign=None) -> dict:
    if not cycle:
        return {"demo": "video" if _has_video(practice) else "none", "clip": None}
    status = str(cycle.get("status") or "")
    demo = cycle.get("demo") or ("video" if _has_video(practice) else "none")
    if not cycle.get("demo") and status in ("pending", "analyzing") \
            and not (_has_video(practice) and _coach_picked(practice)):
        # The job has not chosen yet (queued by the bake, or waiting for
        # the voice): the walk shows the clip's place, the breathing mark,
        # rather than the locked screen and then a swap. A coach's video
        # is never displaced. `unavailable` below still falls back.
        demo = "ai_voice"
    if status == "completed" and cycle.get("storage_key"):
        url = (sign or _sign)(str(cycle.get("bucket") or ""), str(cycle["storage_key"]))
        clip = {"state": "ready" if url else "unavailable", "url": url,
                "duration_ms": cycle.get("duration_ms"),
                "max_appearances": MAX_APPEARANCES, "why": why_of(cycle),
                **problem_of(cycle)}
    elif status in ("pending", "analyzing", "choosing_exercise", "generating", "validating"):
        clip = {"state": "pending", "url": None, "max_appearances": MAX_APPEARANCES}
        if (cycle.get("selection") or {}).get("exercise"):
            # Chosen, still being made: the walk can word its bubble now and
            # the chat says the same (N120).
            clip.update(problem_of(cycle))
    else:
        clip = {"state": "unavailable", "url": None, "max_appearances": MAX_APPEARANCES}
    if clip["state"] == "unavailable" and demo == "ai_voice":
        # No clip to put in the video's place: the locked Exercise as it was.
        demo = "video" if _has_video(practice) else "none"
    return {"demo": demo, "clip": clip}


#: What the speaker's own numbers showed, what the clip does differently
#: and why it sounds better: one signed sentence per change (WIL-82, founder
#: 2026-10-16, L14-L17). The opening clause is only ever said when the
#: picker measured that change against the speaker's own usual delivery;
#: when nothing reached the line the clip is the default (stress on the
#: main point) and ``default`` says so instead. ``{phrase}`` is the
#: speaker's own target words, cut from their transcript, the only words the
#: bubble ever shows (an amendment to the lock's "never the words"). No
#: model writes this and no number is in it (AC-9).
WHY = {
    "pace": ("You said this faster than you usually do. This version is a little "
             "slower. Slower gives the listener time to take each thought in, so "
             "it is easier to follow."),
    "pause": ("You ran straight into \u201c{phrase}\u201d. This version stops for a "
              "moment before it. The pause makes the listener wait for what comes "
              "next, so it lands."),
    "stress": ("You said this flatter than you usually do. This version makes "
               "\u201c{phrase}\u201d stand out, said a little stronger. One point that "
               "stands out gives the sentence a shape, so it is less flat and keeps "
               "the listener with you."),
    "default": ("Nothing was off here. This version just makes \u201c{phrase}\u201d stand "
                "out a little more, so the point lands and the sentence has a shape."),
    # L18 (founder 2026-10-18): the fillers clip names no words and no number.
    "fillers": ("You said this with a few ums and uhs. This version says it without "
                "them. Without them each thought comes out whole, so it sounds sure "
                "and is easier to follow."),
}


def problem_of(cycle: dict) -> dict:
    """What the clip fixes, in words, for the walk's short bubble (founder
    2026-10-23, N120): ``problem`` (pace, pause, stress, fillers, or default
    when nothing was off) and ``phrase``, the speaker's own target words, or
    None when its problem has none. The app picks the signed tip
    (docs/SIGNED-line-bank-2026-10-06.md, the AI clip's bubble). No severity,
    score or check crosses (AC-9)."""
    selection = cycle.get("selection") or {}
    exercise = str(cycle.get("exercise") or selection.get("exercise") or "") or None
    phrase = " ".join(str(selection.get("target_phrase") or "").split()) or None
    return {"problem": "default" if selection.get("default") else exercise, "phrase": phrase}


def why_of(cycle: dict) -> Optional[str]:
    """The signed sentence for the change this clip was made with, from the
    stored selection: the measured problem, or the default when none reached
    the line. None when the cycle does not say (an old row) or the change
    needs a phrase it lacks."""
    selection = cycle.get("selection") or {}
    exercise = str(cycle.get("exercise") or selection.get("exercise") or "")
    line = WHY.get("default" if selection.get("default") else exercise)
    if not line:
        return None
    phrase = " ".join(str(selection.get("target_phrase") or "").split())
    if "{phrase}" in line and not phrase:
        return None
    return line.format(phrase=phrase)


def _sign(bucket: str, key: str) -> Optional[str]:
    try:
        from services.coach_video_storage import presigned_get_coach_object
        return presigned_get_coach_object(bucket, key, LINK_SECONDS)
    except Exception:  # noqa: BLE001 — no link means "unavailable", never a broken player
        _log.warning("ai voice: link not signed", exc_info=True)
        return None


def note_play(database: Any, practice_id: str) -> None:
    cycle = store.get_cycle(database, practice_id)
    if cycle and cycle.get("status") == "completed":
        store.update_cycle(database, str(cycle["id"]), {
            "plays": int(cycle.get("plays") or 0) + 1, "listened": True})


def note_attempts(database: Any, practice: dict, attempts: list[dict]) -> None:
    """The next try, measured on the one problem only, in the same units.

    Stored for the future picker; it changes nothing on screen. A try
    longer than the practice limit (45 s) is not measured, and neither is
    a try after a clip that was never made (failed its check, skipped):
    the speaker never heard one to follow."""
    cycle = store.get_cycle(database, str(practice.get("id")))
    if not cycle or cycle.get("status") != "completed" \
            or not cycle.get("exercise") or not attempts:
        return
    latest = max(attempts, key=lambda row: int(row.get("attempt_index") or 0))
    after = dict(latest.get("acoustic_metrics") or {})
    # Fillers are read from the try's own transcript, the same way the
    # practised sentence was read.
    from services.ai_voice_severity import fillers_per_100
    after["fillers_per_100"] = fillers_per_100(latest.get("transcript"))
    too_long = int(latest.get("duration_ms") or 0) > 1000 * int(Config.AI_VOICE_MAX_PRACTICE_SECONDS)
    from services.ai_voice_severity import outcome
    medians = {}
    try:
        from services.ai_voice_severity import own_medians
        medians = own_medians(database.get_snippets_by_session(
            str(practice.get("take_session_id"))) or [])
    except Exception:  # noqa: BLE001 — unmeasured is inconclusive
        _log.info("ai voice: own usual unreadable", exc_info=True)
        medians = {}
    result = "inconclusive" if too_long else outcome(
        str(cycle["exercise"]), cycle.get("metrics_before") or {}, after, medians)
    store.update_cycle(database, str(cycle["id"]), {
        "retried": True, "outcome": result,
        "metrics_after": {k: after.get(k)
                          for k in ("wpm", "pause_ratio", "dynamic_db", "fillers_per_100")}})


def erase_clips(database: Any, owner_user_id: str, *, delete_object=None) -> int:
    """Every clip of this speaker: the stored audio first, then the row's
    clip fields. Safe to repeat. Returns how many clips could NOT be
    removed: their rows keep their coordinates, so the next Delete finds
    them again (a failure is never turned into "gone")."""
    left = 0
    for cycle in store.owner_cycles(database, owner_user_id, limit=1000):
        key, bucket, sha = cycle.get("storage_key"), cycle.get("bucket"), cycle.get("content_sha256")
        if key and bucket and sha:
            try:
                (delete_object or _delete_object)(str(key), str(bucket), str(sha))
            except FileNotFoundError:
                pass
            except Exception as error:  # noqa: BLE001 — kept for the next Delete
                _log.warning("ai voice: clip object not deleted cycle=%s: %s",
                             cycle.get("id"), type(error).__name__, exc_info=True)
                left += 1
                continue
        # The clip and everything describing it: its words, the request
        # and the check. What stays is about the speaker's own tries
        # (metrics before and after, the pick, the outcome), for the picker.
        store.update_cycle(database, str(cycle["id"]), {
            "status": "deleted", "storage_key": None, "bucket": None,
            "content_sha256": None, "prepared_text": None,
            "generation_metadata": None, "validation": None, "duration_ms": None})
    return left


def _delete_object(key: str, bucket: str, sha: str) -> None:
    from services.lab_audio_storage import delete_verified_lab_audio_object
    delete_verified_lab_audio_object(key, bucket=bucket, storage_provider="r2",
                                     expected_sha256=sha)
