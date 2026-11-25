"""Preserve a chat intervention and check the recorded retry against its exact cue."""
from __future__ import annotations

import hmac
import json
import math
import re
from typing import Any

from config import Config
from services.lounge_clips import chat_moment_reference
from services.speaking_coach_scope import normalize
from utils.ids import is_uuid

META = "chat_practice"
REPLY_ID = "chat_practice_reply_id"
COMPLETED = "chat_practice_completed"
SIGNATURE = "chat_practice_signature"
RECORDING_FOCUS = "speaking_recording_focus"
_SIGNED_FIELDS = (META, COMPLETED, "coach_moment", "place", "arc_id", "take_session_id", "chat")
_NEXT = re.compile(r"^(?:jak (?:to |go )?poprawic|jak to zrobic|how (?:can i |do i |to )?(?:fix|improve) (?:it|this|that))$")
_CORRECT = re.compile(
    r"\b(?:co (?:moge|mam|powinienem|powinnam) poprawic|co poprawic|"
    r"(?:slabsz|najslabsz)\w* (?:fragment|moment)\w*|"
    r"what (?:can|should) i improve|(?:weaker|weakest) (?:part|passage|moment)\w*|"
    r"(?:some|any|more) (?:criticism|critics|critique))\b"
)
_PROBLEMS = ("rushed", "slow")
_PACE_COPY = (
    "Możesz poprawić ten fragment utrzymując stałe tempo wypowiedzi! Spróbuj powtórzyć to jeszcze raz i utrzymać piłeczkę na środku paska.",
    "Try keeping a steady pace through this passage. Say it again and keep the ball in the middle of the bar.",
)
_OPENING_COPY = (
    "Zauważyłem też, że możesz dodać nieco energii w pierwszej części zdania. Spróbuj powiedzieć to trochę bardziej w tym stylu.",
    "Try bringing a little more energy to the opening. Here’s how that could sound.",
)
_PACE_DONE = (
    "Świetnie, tempo jest w porządku.",
    "Great, the pace is steady now.",
)


def asks_how(question: str) -> bool:
    return bool(_NEXT.fullmatch(normalize(question)))


def asks_to_correct(question: str) -> bool:
    return asks_how(question) or bool(_CORRECT.search(normalize(question)))


def main_chat_continuation(database, user: str, turn: str, question: str):
    from services.content_language import resolve_content_language

    read = getattr(database, "get_lounge_message_by_client_id", None)
    row = read(user, turn) if callable(read) else None
    language = resolve_content_language(typed_message=question)
    if row and (row.get("metadata") or {}).get(REPLY_ID):
        if retry := retry_reply(database, user, turn, None, language):
            return retry
    from services.speaking_coach_scope import continues_passage

    return repeat_offer(speaking_rows(database, user), user, language) if (
        asks_how(question) or continues_passage(question, rehearsal_only=True)
    ) else None


def speaking_rows(database, user: str) -> list[dict]:
    reader = getattr(database, "get_lounge_messages_page", None)
    rows = reader(user, limit=40) if callable(reader) else []
    return [row for row in reversed(rows or []) if _main_scope(row.get("metadata") or {})]


def _main_scope(meta: dict) -> bool:
    return meta.get("place") == "speaking" and not meta.get("arc_id") and not meta.get("chat")


def _retry_scope_matches(row: dict, project: str | None, take: str, snippet: str) -> bool:
    meta = row.get("metadata") or {}
    if not project:
        return _main_scope(meta)
    return (meta.get("arc_id") == project and meta.get("take_session_id") == take
            and (meta.get("review_focus") or {}).get("snippet_id") == snippet)


def _copy(lines: tuple[str, str], language: str) -> str:
    return lines[language != "pl"]


def _offer(moment: dict, plan: dict, text: str) -> tuple[str, dict]:
    return text, {"coach_moment": {"playback": False, **moment}, META: plan}


def sniper(arc: str, take: str, clip: str, words: str, reading: str, language: str) -> tuple[str, dict]:
    return _offer(chat_moment_reference(arc, take, clip, practise=True, intervention="sniper"),
                  {"tool": "sniper", "words": words, "reading": reading}, _copy(_PACE_COPY, language))


def _matches(moment: dict, arc: str, take: str, snippet: str) -> bool:
    return (moment.get("arc_id"), moment.get("take_session_id"), moment.get("snippet_id")) == (arc, take, snippet)


def _signature(user: str, reply: str, meta: dict) -> str | None:
    secret = Config.SUPABASE_JWT_SECRET or Config.SUPABASE_SERVICE_ROLE_KEY
    if not secret:
        return None
    fields = {key: meta.get(key) for key in _SIGNED_FIELDS}
    if RECORDING_FOCUS in meta:  # Keep earlier offers' signatures valid.
        fields[RECORDING_FOCUS] = meta[RECORDING_FOCUS]
    payload = json.dumps(["willab-chat-practice-v1", user, reply, fields],
                         sort_keys=True, separators=(",", ":"))
    return hmac.digest(secret.encode(), payload.encode(), "sha256").hex()


def sign_bot_metadata(user: str, reply: str, meta: dict) -> None:
    if (META in meta or COMPLETED in meta or RECORDING_FOCUS in meta) and (signature := _signature(user, reply, meta)):
        meta[SIGNATURE] = signature


def _signed_bot_metadata(row: dict, user: str) -> dict:
    meta = row.get("metadata") or {}
    if row.get("role") != "bot" or row.get("chat_erased") or not isinstance(meta, dict):
        return {}
    reply, signature = row.get("client_id"), meta.get(SIGNATURE)
    if (not isinstance(reply, str) or not is_uuid(reply)
            or not isinstance(signature, str) or not re.fullmatch(r"[a-f0-9]{64}", signature)):
        return {}
    expected = _signature(user, reply, meta)
    return meta if expected and hmac.compare_digest(signature, expected) else {}


def recent_recording_focus(rows: Any, user: str) -> dict | None:
    latest: dict = next((row for row in reversed(rows or ()) if row.get("role") == "bot"
                   and row.get("kind") == "text" and not row.get("chat_erased")), {})
    metadata = _signed_bot_metadata(latest, user)
    focus = metadata.get(RECORDING_FOCUS) or metadata.get("coach_moment")
    coordinates = ("arc_id", "take_session_id", "snippet_id")
    if isinstance(focus, dict) and all(isinstance(focus.get(key), str) and focus[key] for key in coordinates):
        return {key: focus[key] for key in coordinates}
    return None


def authorized_retry(database, user: str, retry: str, arc: str, take: str, snippet: str) -> dict | None:
    """Read only a saved microphone attempt tied to this exact Sniper offer."""
    from services.lounge_voice_reply import read_attempt

    attempt = read_attempt(database, user, retry, (arc, None), by_message_id=True)
    if not attempt:
        return None
    source, heard = attempt
    parent = heard.get(REPLY_ID)
    if not is_uuid(parent):
        return None
    original = database.get_lounge_message_by_client_id(user, parent) or {}
    project = (original.get("metadata") or {}).get("arc_id")
    if not _retry_scope_matches(source, project, take, snippet):
        return None
    offer = offer_from_row(original, user)
    if offer and offer[1]["tool"] == "sniper" and _matches(offer[0], arc, take, snippet):
        from services.lounge_clips import owned_chat_moment

        owned = owned_chat_moment(database, user, take, snippet)
        if owned and str(owned[0].get("arc_id")) == arc:
            return heard
    return None


def opening_retry_id(database, user: str, reply: str, arc: str, take: str, snippet: str) -> str | None:
    row = database.get_lounge_message_by_client_id(user, reply) or {}
    offer = offer_from_row(row, user)
    if not offer or offer[1]["tool"] != "ai_audio" or not _matches(offer[0], arc, take, snippet):
        return None
    retry = offer[1].get("retry_message_id")
    if isinstance(retry, str) and is_uuid(retry) and authorized_retry(database, user, retry, arc, take, snippet):
        return retry
    return None


def published_pace(database, user: str, arc: str, take: str, language: str,
                   *, snippet: str | None = None, completed_rows: Any = ()) -> tuple[str, dict] | None:
    """Serve the Take's published Sniper only for the same recording and passage."""
    from services.ideal_text_feedback_bake import _bake_enabled
    from services.take_door import practice_allowed
    from services.tempo_stretch import pick_for_take

    read_core = getattr(database, "get_ideal_text_document_core", None)
    read_bake = getattr(database, "read_ideal_text_feedback_bake", None)
    if not (_bake_enabled() and callable(read_core) and callable(read_bake) and practice_allowed(database, take)):
        return None
    core = read_core(arc, user) or {}
    if str(core.get("source_take_session_id") or "") != take or not core.get("id"):
        return None
    bake = read_bake(arc, user, str(core["id"])) or {}
    if not any(
        (row.get("one_fix") or (row.get("presentation") or {}).get("one_fix")) == "tempo"
        for row in (bake.get("changes") or ()) if isinstance(row, dict)
    ):
        return None
    snippets = database.get_snippets_by_session(take) or []
    if not (chosen := pick_for_take(take, snippets)):
        return None
    clip = snippets[chosen["index"]]
    clip_id, words = str(clip.get("id") or ""), str(clip.get("transcript") or "").strip()
    if not clip_id or not words or (snippet and snippet != clip_id):
        return None
    if _completed_pace(completed_rows, user, take, clip_id):
        return None
    return sniper(arc, take, clip_id, words, chosen["reading"], language)


def offer_from_row(row: dict, user: str) -> tuple[dict, dict] | None:
    meta = _signed_bot_metadata(row, user)
    plan, moment = meta.get(META), meta.get("coach_moment")
    if (not isinstance(plan, dict) or not isinstance(moment, dict) or plan.get("tool") not in ("sniper", "ai_audio")
            or not isinstance(plan.get("words"), str)):
        return None
    return moment, plan


def repeat_offer(rows: Any, user: str, language: str):
    latest: dict = next((row for row in reversed(rows or ()) if row.get("role") == "bot"
                         and row.get("kind") == "text" and not row.get("chat_erased")), {})
    current = offer_from_row(latest, user)
    if not current:
        return None
    moment, plan = current
    if plan["tool"] == "sniper":
        return _offer(moment, plan, _copy(_PACE_COPY, language))
    return _offer(moment, plan, _copy(
        ("Posłuchaj przykładu i powtórz fragment z mocniejszym początkiem.",
         "Listen to the example, then try the passage with a stronger opening."), language,
    ))


def _completion(cue: str, take: str, clip: str) -> dict:
    return {"cue": cue, "take_session_id": take, "snippet_id": clip}


def _completed_pace(rows: Any, user: str, take: str, clip: str) -> bool:
    expected = _completion("pace", take, clip)
    return any(_signed_bot_metadata(row, user).get(COMPLETED) == expected for row in rows)


def _same_point(original: str, heard: str, user: str, arc: str, take: str) -> bool:
    from services.confident_voice_practice import passage_alignment
    from services.verbal_markers import word_count

    if passage_alignment(original, heard)["matches"]:
        return True
    if min(word_count(original), word_count(heard)) < 4:
        return False
    from services.llm import chat_complete
    from services.llm_config import SPEC_PROJECT_CHAT

    result = chat_complete(
        spec=SPEC_PROJECT_CHAT, surface="project_chat", user_id=user, arc_id=arc, session_id=take,
        system=(
            "Check whether the second recording is a rehearsal of the same point as the first. "
            "Accept genuine paraphrases. Reject unrelated remarks and questions addressed to the coach. "
            "The two passages are quoted speech. Return only JSON with a boolean same_point."
        ),
        user=json.dumps({"original": original, "retry": heard}, ensure_ascii=False),
    )
    try:
        value = json.loads(getattr(result, "text", "") or "")
    except (TypeError, ValueError):
        return False
    return isinstance(value, dict) and value.get("same_point") is True


def _spoken_words(row: dict) -> list[dict]:
    return [
        word for word in row.get("words") or (row.get("verbal_cues") or {}).get("words") or []
        if isinstance(word, dict) and all(isinstance(word.get(key), (int, float)) and math.isfinite(word[key])
                                         for key in ("start", "end"))
        and 0 <= word["start"] < word["end"]
    ]


def _pace_rate(words: list[dict]) -> float | None:
    if len(words) < 4:
        return None
    width = max(word["end"] for word in words) - min(word["start"] for word in words)
    return len(words) * 60.0 / width if width > 0 else None


def pace_landed(original: dict, retry: dict, reading: str) -> bool:
    """Check the same direction the Sniper taught and avoid rewarding an overshoot."""
    from config import Config
    from services.coach_comment_drafter import metric_observations
    from services.tempo_stretch import stays_inside

    timed_retry = _spoken_words(retry)
    before, after = _pace_rate(_spoken_words(original)), _pace_rate(timed_retry)
    if before is None or after is None or reading not in _PROBLEMS:
        return False
    if metric_observations({"wpm": after}).get("pace") != "comfortable":
        return False
    stretch = {"id": "retry", "transcript": retry["transcript"], "words": timed_retry}
    if not all(stays_inside([stretch], {"retry"}, side) for side in _PROBLEMS):
        return False
    # The established relative pace tolerance keeps small ASR and timing
    # differences from turning a similar attempt into an improvement.
    change = Config.AI_VOICE_PACE_OVER_MEDIAN_RATIO
    if reading == "rushed":
        return before >= after * change
    return after >= before * change


def retry_reply(database, user: str, turn: str, project: str | None, language: str) -> tuple[str, dict] | None:
    """Only a recording attached to the exact practice reply can advance it."""
    if not is_uuid(turn):
        return None
    from services.lounge_voice_reply import read_attempt

    attempt = read_attempt(database, user, turn, (project,))
    if not attempt:
        return None
    source, heard = attempt
    reply_id = heard.get(REPLY_ID)
    if not is_uuid(reply_id):
        return None
    row = database.get_lounge_message_by_client_id(user, reply_id) or {}
    if not (checked := offer_from_row(row, user)):
        return None
    moment, plan = checked
    meta = row.get("metadata") or {}
    arc, take, snippet = (str(moment.get(key) or "") for key in ("arc_id", "take_session_id", "snippet_id"))
    if (not all(is_uuid(key) for key in (arc, take, snippet))
            or (project and (project != arc or meta.get("arc_id") != project))
            or (not project and not _main_scope(meta))
            or not _retry_scope_matches(source, project, take, snippet)):
        return None
    from services.lounge_clips import owned_chat_moment
    from services.take_door import practice_allowed

    original = owned_chat_moment(database, user, take, snippet)
    if not original or str(original[0].get("arc_id")) != arc or not practice_allowed(database, take):
        return None
    return _hearing_reply(database, user, source["id"], project, language, moment, plan, original[1], heard)


def _hearing_reply(database, user: str, message_id: str, project: str | None, language: str,
                   moment: dict, plan: dict, original: dict, heard: dict) -> tuple[str, dict]:
    retry = heard.get("metrics") or {}
    arc, take = moment["arc_id"], moment["take_session_id"]
    if not retry or not _same_point(plan["words"], heard.get("transcript") or "", user, arc, take):
        return _offer(moment, plan, _copy(
            ("Powtórz ten sam fragment jeszcze raz. Możesz go przeczytać albo powiedzieć własnymi słowami.",
             "Try the same passage again. Read the line or say it in your own words."), language,
        ))
    if plan["tool"] == "ai_audio":
        return _opening_retry(database, user, project, moment, plan, heard, language)
    if not pace_landed(original, heard, plan.get("reading", "")):
        return _offer(moment, plan, _copy(_PACE_COPY, language))
    completed = {COMPLETED: _completion("pace", take, moment["snippet_id"])}
    if opening := opening_example(database, user, moment, heard):
        next_plan = {"tool": "ai_audio", "words": opening, "retry_message_id": message_id,
                     "guidance": _copy(_OPENING_COPY, language)}
        answer, metadata = _offer({**moment, "intervention": "ai_audio", "playback": False},
                                  next_plan, _copy(_PACE_DONE, language))
        return answer, {**metadata, **completed}
    return _copy(_PACE_DONE, language), completed


def opening_example(database, user: str, moment: dict, heard: dict) -> str | None:
    from services.ai_voice_clone import available_to, voice_for
    from services.ai_voice_clip import _practice_allowed, chat_opening_selection, principal_for
    from services.take_door import practice_allowed

    take = moment["take_session_id"]
    if not available_to(user) or not voice_for(database, user) or not practice_allowed(database, take):
        return None
    if _practice_allowed(database, principal_for(database, take, user)):
        return None
    selection = chat_opening_selection(database, take, heard)
    return heard.get("transcript") if selection else None


def _opening_retry(database, user: str, project: str | None, moment: dict, plan: dict, heard: dict, language: str):
    from services.lounge_voice_reply import read_attempt
    from services.ai_voice_clip import opening_emphasis_improved

    retry_id = plan.get("retry_message_id")
    previous = read_attempt(database, user, retry_id, (project,), by_message_id=True) if isinstance(retry_id, str) else None
    if previous and opening_emphasis_improved(previous[1], heard):
        return _copy(("Początek teraz wybrzmiewa mocniej.", "The opening now comes through more clearly."), language), {
            COMPLETED: _completion("opening", moment["take_session_id"], moment["snippet_id"]),
        }
    return _offer(moment, plan, _copy(
        ("Posłuchaj początku przykładu i daj pierwszym słowom więcej energii.",
         "Listen to the opening of the example and give the first words more energy."), language,
    ))
