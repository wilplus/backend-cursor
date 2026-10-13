"""One AI clip per practice, made only in the voice Exercise lane
(founder lock 2026-10-12, docs/FOUNDER-LOCK-ai-voice-practice-2026-10-12.md).

  ensure     the walk asks for the clip when it enters the lane: when the
             Exercise screen opens (no video fits) or when Practise is
             tapped (a video fits). The rewrite lane and praise never get
             here; a rewrite practice is refused before anything is read.
             One cycle row per practice (UNIQUE), so a repeated request never
             makes a second clip.
  generate   the background job: choose the exercise, build the request,
             check the limits, call ElevenLabs through the permit, check the
             clip (words re-heard through the existing Whisper permit), store
             it. A failed check is never shown.
  state      what the walk may know: video or AI clip, and the clip's state
             and short-lived link when it passed. No id, setting, score or
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
PROBLEM_TAGS = {"pace": {"rushing"}, "pause": {"rushing"}, "stress": set()}


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
    """Only the voice Exercise: never the Clearer version (a rewrite)."""
    return str((practice or {}).get("kind") or "") in ("exercise", "moment")


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
           run=None, sign=None) -> dict:
    """Start (once) the clip for this practice and return ``state``."""
    from services.ai_voice_clone import available_to
    if not available_to(user_id) or not in_voice_lane(practice):
        return {"demo": "video" if _has_video(practice) else "none", "clip": None}
    cycle, created = store.create_cycle(database, {
        "practice_id": str(practice["id"]), "owner_user_id": str(user_id),
        "take_session_id": practice.get("take_session_id"),
        "snippet_id": practice.get("snippet_id"), "status": "pending"})
    if cycle is None:
        return {"demo": "video" if _has_video(practice) else "none", "clip": None}
    retry_waiting = (cycle.get("status") == "pending"
                     and cycle.get("failure_kind") == "no_voice")
    if created or retry_waiting:
        args = (str(cycle["id"]), principal_id)
        if run is not None:
            run(*args)
        else:
            _start(args, cycle_id=str(cycle["id"]))
        cycle = store.get_cycle(database, str(practice["id"])) or cycle
    return state(database, practice, cycle, sign=sign)


def _has_video(practice: dict) -> bool:
    return (str((practice or {}).get("kind")) == "exercise"
            and bool(((practice or {}).get("exercise_snapshot") or {}).get("explanation_video_url")))


def _start(args: tuple, *, cycle_id: str) -> None:
    from services.job_queue import enqueue
    if enqueue("services.ai_voice_clip.generate", *args,
               rq_job_id=f"ai-voice-clip-{cycle_id}"):
        return
    import threading
    threading.Thread(target=generate, args=args, daemon=True,
                     name="ai-voice-clip").start()


def _choose(database: Any, practice: dict, cycle: dict) -> tuple[Optional[dict], dict]:
    from services.ai_voice_severity import own_medians, select
    snippet = database.get_snippet_by_id(str(practice.get("snippet_id"))) or {}
    take = database.get_snippets_by_session(str(practice.get("take_session_id"))) or []
    medians = own_medians(take)
    history = [row for row in store.owner_cycles(database, str(cycle["owner_user_id"]))
               if str(row.get("id")) != str(cycle["id"])]
    sentence = str(practice.get("exact_passage") or snippet.get("transcript") or "")
    selection = select(snippet, medians, sentence=sentence,
                       seed=str(practice["id"]), history=history)
    before = {k: (snippet.get("metrics") or {}).get(k)
              for k in ("wpm", "pause_ratio", "dynamic_db")}
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


def generate(cycle_id: str, principal_id: str, *, database: Any = None,
             provider: Any = None, transcribe=None, put_object=None,
             decode=None, provider_usage=None) -> str:
    """The clip job; returns the cycle's end status."""
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
        "decode": decode, "provider_usage": provider_usage})
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
    if not voice_id:
        # The clone may still be on its way from Take 1: the next ensure retries.
        job.update({"status": "pending", "failure_kind": "no_voice",
                    "exercise": selection["exercise"]})
        return "pending"
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


def _speak_until_checked(job: _Job, voice_id: str, request: dict, selection: dict,
                         context: dict) -> tuple[bytes, Optional[dict], Optional[str]]:
    """(audio, last check, provider failure). At most 1 + RETRIES clips are
    made (founder 2026-10-12: one, so RETRIES is 0). A provider refusal that
    made nothing (429, 5xx) is asked once more and costs no generation."""
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
            if getattr(error, "transient", False) and not asked_again:
                asked_again = True
                time.sleep(1.5)
                continue
            failure = str(getattr(error, "kind", "") or type(error).__name__)
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
    if status == "completed" and cycle.get("storage_key"):
        url = (sign or _sign)(str(cycle.get("bucket") or ""), str(cycle["storage_key"]))
        clip = {"state": "ready" if url else "unavailable", "url": url,
                "duration_ms": cycle.get("duration_ms"),
                "max_appearances": MAX_APPEARANCES}
    elif status in ("pending", "analyzing", "choosing_exercise", "generating", "validating"):
        clip = {"state": "pending", "url": None, "max_appearances": MAX_APPEARANCES}
    else:
        clip = {"state": "unavailable", "url": None, "max_appearances": MAX_APPEARANCES}
    if clip["state"] == "unavailable" and demo == "ai_voice":
        # No clip to put in the video's place: the locked Exercise as it was.
        demo = "video" if _has_video(practice) else "none"
    return {"demo": demo, "clip": clip}


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
    longer than the practice limit (45 s) is not measured."""
    cycle = store.get_cycle(database, str(practice.get("id")))
    if not cycle or not cycle.get("exercise") or not attempts:
        return
    latest = max(attempts, key=lambda row: int(row.get("attempt_index") or 0))
    after = latest.get("acoustic_metrics") or {}
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
        "metrics_after": {k: after.get(k) for k in ("wpm", "pause_ratio", "dynamic_db")}})


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
