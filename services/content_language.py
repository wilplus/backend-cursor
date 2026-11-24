"""Content-language routing for generated coaching text.

UI locale is deliberately not part of this module. A coaching response is
written in the language of the immediate recording or typed message; IP,
browser locale and profile preferences never select it.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

DEFAULT_CONTENT_LANGUAGE = "en"
_ISO_639_1 = re.compile(r"^[a-z]{2}$")
_WORD = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿĄąĆćĘęŁłŃńÓóŚśŹźŻż]+")
_LANGUAGE_NAMES = {
    "en": "English", "pl": "Polish", "de": "German", "es": "Spanish",
    "fr": "French", "it": "Italian", "pt": "Portuguese", "nl": "Dutch",
    "cs": "Czech", "uk": "Ukrainian",
}
_MARKERS = {
    "en": frozenset(
        "the and or to of in for is are was were this that with your you we they "
        "can will would could have has do does what how why from on as a an it".split()
    ),
    "pl": frozenset(
        "i oraz albo do z w na jest są był była było ten ta to że się dla "
        "nie tak jak czy ale aby przez przy można chcę chce mamy mają "
        "twoją twoje mój moja moje więc wiesz znaczy możesz mozesz "
        "odpowiedź odpowiedz odpowiedzieć odpowiedziec wyjaśnić wyjasnic "
        "dlaczego gdzie kiedy jestem mam mieć miec chcesz proszę prosze "
        "potrzebuję potrzebuje pomóc pomoc wzorzec wzorce ostatnio "
        "powtarza ciągle ciagle znowu".split()
    ),
}
_PL_DIACRITICS = frozenset("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ")
# High-confidence unaccented Polish phrases.  Individual words such as
# ``co`` are ambiguous in a short English message, but these combinations
# are ordinary Polish and let brief typed turns avoid falling through to an
# English fallback without consulting browser/UI locale.
_PL_UNACCENTED_PHRASES = (
    "nie wiem", "co robisz", "czy moge", "czy mozesz", "pomoz mi",
    "prosze cie", "jak mam", "co mam", "nie rozumiem", "o co chodzi",
    "co teraz", "jak zaczac", "dziekuje bardzo", "jestem gotowy",
    "mozemy zaczac", "wytlumacz mi", "czy masz rade",
)
# A few single unaccented forms are unambiguously Polish in a short typed
# turn.  Keep this deliberately small: common English words must still fall
# back to English unless there is stronger immediate-message evidence.
_PL_UNACCENTED_WORDS = frozenset({
    "czesc", "hej", "dziekuje", "prosze", "pomoz", "mozemy", "zaczac", "wytlumacz",
})
_EN_FIRST_PERSON_QUESTION = re.compile(r"\b(?:do|did|am|can|could|should|would|will) i\b")


def normalize_language(value: Any) -> Optional[str]:
    """Return a lower-case ISO-639-1 code, or ``None`` for unknown input."""
    if not isinstance(value, str):
        return None
    code = value.strip().lower()
    return code if _ISO_639_1.fullmatch(code) else None


def language_name(value: Any) -> str:
    code = normalize_language(value) or DEFAULT_CONTENT_LANGUAGE
    return _LANGUAGE_NAMES.get(code, code)


def detect_typed_language(text: Any) -> Optional[str]:
    """Detect only from the immediate typed message, with bounded markers."""
    if not isinstance(text, str):
        return None
    words = [word.lower() for word in _WORD.findall(text) if word]
    if not words:
        return None
    if any(char in _PL_DIACRITICS for char in text):
        return "pl"
    lowered = " ".join(words)
    if any(phrase in lowered for phrase in _PL_UNACCENTED_PHRASES):
        return "pl"
    if any(word in _PL_UNACCENTED_WORDS for word in words):
        return "pl"
    if _EN_FIRST_PERSON_QUESTION.search(lowered):
        return "en"
    scores = {
        code: sum(1 for word in words if word in markers)
        for code, markers in _MARKERS.items()
    }
    best = max(scores, key=lambda code: scores[code])
    other = "pl" if best == "en" else "en"
    return best if scores[best] >= 2 and scores[best] > scores[other] else None


def resolve_content_language(
    *, recording_language: Any = None, typed_message: Any = None,
    fallback: Any = DEFAULT_CONTENT_LANGUAGE,
) -> str:
    """Resolve from content evidence only; the fallback is never an IP locale."""
    return (
        normalize_language(recording_language)
        or detect_typed_language(typed_message)
        or normalize_language(fallback)
        or DEFAULT_CONTENT_LANGUAGE
    )


def language_instruction(target_language: Any) -> str:
    """The explicit instruction shared by generated coaching prompts."""
    code = normalize_language(target_language)
    if not code:
        return ""
    return (
        f"\n\nTARGET CONTENT LANGUAGE: {language_name(code)} ({code}). "
        "Write every generated coaching sentence in this language. Preserve "
        "the speaker's transcript and quoted words exactly; never translate, "
        "replace, or clean source words in order to change their language."
    )


def validate_output_language(text: Any, target_language: Any) -> bool:
    """Return whether generated prose is consistent with the explicit target."""
    target = normalize_language(target_language)
    if not target or not isinstance(text, str):
        return bool(not target)
    words = [word.lower() for word in _WORD.findall(text) if word]
    if len(words) < 3 or target not in _MARKERS:
        return True
    scores = {
        code: sum(1 for word in words if word in markers)
        for code, markers in _MARKERS.items()
    }
    if target == "pl":
        return any(char in _PL_DIACRITICS for char in text) or scores["pl"] >= scores["en"]
    if target == "en":
        return scores["pl"] == 0 or scores["en"] >= scores["pl"]
    return True


def safe_fallback(target_language: Any, *, default: str,
                  polish: Optional[str] = None) -> str:
    """Choose an existing safe fallback without consulting UI locale."""
    return polish if normalize_language(target_language) == "pl" and polish else default


def complete_in_language(
    generate: Callable[..., Any], *, target_language: Any, system: str,
    user: str, messages_override: Optional[list[dict[str, str]]] = None,
    return_last_on_failure: bool = False,
    **kwargs: Any,
) -> Any:
    """Generate with one bounded language retry, then fail closed.

    A caller with a stronger deterministic safety guard may request the last
    response so it can sanitize it before applying the language fallback.
    """
    target = normalize_language(target_language)
    instruction = language_instruction(target)
    if not instruction:
        if messages_override is not None:
            kwargs = {**kwargs, "messages_override": messages_override}
        return generate(system=system, user=user, **kwargs)

    def with_instruction(messages: Optional[list[dict[str, str]]]):
        if messages is None:
            return None
        out = [dict(message) for message in messages]
        for message in out:
            if message.get("role") == "system":
                message["content"] = str(message.get("content") or "") + instruction
                break
        return out

    current_user = user
    current_system = system + instruction
    current_messages = with_instruction(messages_override)
    last_result = None
    for attempt in range(2):
        result = generate(
            system=current_system, user=current_user,
            messages_override=current_messages, **kwargs,
        )
        last_result = result
        text = getattr(result, "text", None) if result is not None else None
        if not isinstance(text, str) and result is not None:
            structured = getattr(result, "parsed", None)
            if isinstance(structured, dict):
                text = " ".join(
                    value for value in structured.values()
                    if isinstance(value, str)
                )
        if isinstance(text, str):
            try:
                structured = json.loads(text)
            except (TypeError, ValueError):
                structured = None
            if isinstance(structured, dict):
                text = " ".join(
                    value for value in structured.values()
                    if isinstance(value, str)
                )
        if validate_output_language(text, target):
            return result
        if attempt == 0:
            retry_instruction = (
                "Your previous answer was not in the target language. Rewrite "
                "the same answer now, without translating or changing the "
                "speaker's quoted words."
            )
            current_system += "\n\n" + retry_instruction
            if current_messages:
                current_messages = [dict(message) for message in current_messages]
                current_messages.append({"role": "user", "content": retry_instruction})
    logger.warning("content-language output rejected target=%s", target)
    if return_last_on_failure:
        return last_result
    return None


def recording_target_language(recording: Any = None, session_context: Any = None,
                              *, fallback: Any = DEFAULT_CONTENT_LANGUAGE) -> str:
    """Resolve a Take target from persisted recording evidence first."""
    row = recording if isinstance(recording, dict) else {}
    context = session_context if isinstance(session_context, dict) else {}
    return resolve_content_language(
        recording_language=(
            row.get("transcription_language")
            or context.get("transcription_language")
        ),
        fallback=fallback,
    )
