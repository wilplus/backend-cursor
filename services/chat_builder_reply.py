"""A visitor's reply, from the host's saved chat.

``POST /v2/chats/<id>/reply`` is what the chat builder's visitor try calls.
The recipe is the host's own (``people_profiles.chat_recipe``), never a
table keyed by the browser's chat id. Taught pairs live in
``chat_reply_examples``; a draft the visitor must not see lives in
``chat_reply_drafts``. Both are written by the service role only. Until
those tables exist, a draft is still withheld and a missing example is
simply absent.

Who answers, as the builder's rule:

  * ``you``: nothing is written and the visitor is told the host will answer.
  * ``shadow``, or a chat about health, law or money: the reply is kept for
    the host to send. The visitor does not see it.
  * ``assistant``: sent only after the host's own 20 answers, and never when
    the chat is about health, law or money. Before that, the visitor waits.

A photo (up to 4 MB) goes to the model as an image. A PDF (up to 8 MB) is
read with pypdf and the text is put in the same prompt. A recording is
measured in ``services/chat_voice.py`` and the walk comes back with the
reply. No score and no feeling is returned.

The model call is ``services.llm.chat_complete`` on the existing OpenAI
client (``OPENAI_MODEL``, default gpt-4o-mini). The key never leaves the
server.
"""
from __future__ import annotations

import base64
import logging
import os
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)

PHOTO_MAX = 4 * 1024 * 1024
FILE_MAX = 8 * 1024 * 1024
ASSISTANT_READY = 20
_TEXT_CAP = 8000
_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
_FEELING = re.compile(
    r"\b(confident|nervous|anxious|calm|happy|sad|angry|emotion|arousal|overwhelmed|tense)\b",
    re.I)
_OUT = {
    "answer": "Answer in the host's own words. One short message.",
    "words": "Tidy what the person said. Keep their meaning.",
    "todo": "Give a short list of next steps.",
    "mark": "Point at the spot in words.",
}


def reply_act(who: str, care: bool, host_answers: int) -> str:
    """Who may see a model reply. ``you`` never calls the model."""
    if who == "you":
        return "none"
    if care or who == "shadow":
        return "draft"
    if host_answers < ASSISTANT_READY:
        return "wait"
    return "send"


def is_care(recipe: dict) -> bool:
    """Health, law or money, or not yet answered: the host sends each reply."""
    if recipe.get("care") is True:
        return True
    return recipe.get("sensitive") is not False


def strip_person_scores(text: str) -> str:
    """Drop a score or a number that is about the person. A step count may stay."""
    text = re.sub(r"\b\d{1,3}\s*/\s*10\b", "", text)
    text = re.sub(r"\b\d{1,3}\s*%", "", text)
    text = re.sub(r"\bscore\s*(of|is|:)?\s*\d+(\.\d+)?\b", "", text, flags=re.I)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"\s+([.!?])", r"\1", text)
    return re.sub(r"\.{2,}", ".", text).strip()


def strip_feelings(text: str) -> str:
    """Drop a sentence that names a feeling. The recording's facts do not."""
    parts = re.split(r"(?<=[.!?])\s+", text)
    kept = [part for part in parts if part and not _FEELING.search(part)]
    return " ".join(kept).strip()


def _lines(name: str, items: list[str]) -> list[str]:
    clean = [item.strip() for item in items if item and item.strip()]
    if not clean:
        return []
    return [name, *[f"- {item}" for item in clean]]


def _example_lines(examples: list[dict]) -> list[str]:
    kept = [item for item in examples
            if (item.get("ask") or "").strip() or (item.get("answer") or "").strip()]
    if not kept:
        return []
    lines = ["Examples of how the host answered:"]
    for example in kept:
        lines.append(f"Person: {(example.get('ask') or '').strip()}")
        lines.append(f"Host: {(example.get('answer') or '').strip()}")
    return lines


def _pick_lines(picks: list[dict]) -> list[str]:
    if not picks:
        return []
    lines = ["Also choose one option for each question below. "
             "Use the person's photo, document, or recording when one is attached."]
    for pick in picks:
        opts = ", ".join(str(opt) for opt in (pick.get("opts") or []))
        lines.append(f"{pick.get('q')} Options: {opts}.")
    return lines


def _attachment_lines(extra: dict) -> list[str]:
    lines = []
    voice = [str(line) for line in (extra.get("voice") or []) if str(line).strip()]
    if voice:
        lines.append("Facts about the recording. Use these, and do not invent a feeling:")
        lines.extend(voice)
    if extra.get("has_image"):
        lines.append("A photo is attached. Look at it before you answer.")
    file_text = str(extra.get("file_text") or "").strip()
    if file_text:
        lines.append("Text from the file they sent:")
        lines.append(file_text[:_TEXT_CAP])
    return lines


def build_prompt(setup: dict, message: str, extra: Optional[dict] = None) -> str:
    """The prompt. It forbids a score or a number about the person, and a feeling."""
    extra = extra or {}
    parts = [
        f"You write for the host, who does this: {(setup.get('spec') or '').strip() or 'help people'}.",
        f"Their first line to a visitor is: {(setup.get('hello') or '').strip() or 'Hello.'}",
        _OUT.get(setup.get("out") or "answer", _OUT["answer"]),
        "Never give a score, a mark out of ten, or any number about the person.",
        "Do not name a feeling. Do not say the person is confident, nervous, calm, or anxious.",
        "Write the way a careful person speaks. Short sentences. No jargon.",
        *_lines("Questions the host asks:", list(setup.get("questions") or [])),
        *_lines("Taps a visitor can choose:", list(setup.get("taps") or [])),
        *_example_lines(list(setup.get("examples") or [])),
        *_pick_lines(list(extra.get("picks") or [])),
        *_attachment_lines(extra),
        f"The person sent: {message.strip()}",
    ]
    return "\n".join(part for part in parts if part)


def _questions(recipe: dict) -> list[str]:
    found = []
    for item in recipe.get("questions") or []:
        text = item.get("q") if isinstance(item, dict) else item
        if str(text or "").strip():
            found.append(str(text).strip())
    return found


def _picks(recipe: dict) -> list[dict]:
    picks = []
    for item in recipe.get("models") or []:
        if not isinstance(item, dict) or item.get("gives") not in (None, "pick"):
            continue
        picks.append({"q": item.get("q") or "", "opts": list(item.get("opts") or [])})
    return picks


def _walk_choice(recipe: dict) -> tuple[list[str], bool]:
    """The host's saved walk, or the three steps with no Ideal Text yet."""
    walk = recipe.get("walk") if isinstance(recipe.get("walk"), dict) else None
    if not walk:
        return ["best", "fix", "words"], False
    steps = [step for step in (walk.get("steps") or []) if step in ("best", "fix", "words")]
    return (steps or ["best", "fix", "words"]), walk.get("out") == "ideal_text"


def setup_of(recipe: dict, examples: list[dict], host_answers: int) -> dict:
    steps, ideal = _walk_choice(recipe)
    return {
        "spec": str(recipe.get("spec") or ""),
        "hello": str(recipe.get("hello") or ""),
        "questions": _questions(recipe),
        "taps": [str(tap) for tap in (recipe.get("taps") or []) if str(tap).strip()],
        "out": str(recipe.get("out") or "answer"),
        "who": str(recipe.get("who") or "shadow"),
        "care": is_care(recipe),
        "examples": examples,
        "host_answers": host_answers,
        "picks": _picks(recipe),
        "steps": steps,
        "ideal": ideal,
    }


def _mime(value: Any) -> str:
    mime = str(value or "image/jpeg").split(";", 1)[0].strip().lower()
    return mime if mime in _IMAGE_TYPES else ""


def _decode(data: str, limit: int) -> dict:
    if not isinstance(data, str) or not data:
        return {"error": "unreadable"}
    if len(data) > (limit * 4 // 3) + 8:
        return {"error": "too-big"}
    try:
        raw = base64.b64decode(data, validate=True)
    except ValueError:
        return {"error": "unreadable"}
    if len(raw) > limit:
        return {"error": "too-big"}
    if not raw:
        return {"error": "unreadable"}
    return {"raw": raw}


def pdf_text(raw: bytes) -> str:
    from io import BytesIO
    from pypdf import PdfReader
    reader = PdfReader(BytesIO(raw))
    pages = reader.pages[:30]
    return "\n".join((page.extract_text() or "") for page in pages).strip()[:_TEXT_CAP]


def _file_text(raw: bytes, name: str) -> dict:
    try:
        if str(name or "").lower().endswith(".pdf"):
            text = pdf_text(raw)
        else:
            text = raw.decode("utf-8")
    except Exception:
        logger.warning("chat_builder_reply: the file could not be read", exc_info=True)
        return {"error": "unreadable"}
    text = text.strip()
    if not text:
        return {"error": "unreadable"}
    return {"file_text": text[:_TEXT_CAP]}


def read_upload(kind: str, payload: dict) -> dict:
    """The attachment, or ``{error}``. ``empty`` means there was nothing to answer."""
    message = str(payload.get("text") or "").strip()
    raw_data = payload.get("data")
    data = raw_data if isinstance(raw_data, str) else ""
    name = str(payload.get("name") or "")
    if kind == "photo":
        got = _decode(data, PHOTO_MAX)
        if got.get("error"):
            return got
        mime = _mime(payload.get("mime"))
        if not mime:
            return {"error": "unreadable"}
        image = base64.b64encode(got["raw"]).decode("ascii")
        return {"image": image, "mime": mime, "message": message or name or "They sent a photo."}
    if kind == "file":
        got = _decode(data, FILE_MAX)
        if got.get("error"):
            return got
        text = _file_text(got["raw"], name)
        if text.get("error"):
            return text
        return {**text, "message": message or name or "They sent a file."}
    if kind == "rec":
        from services.chat_voice import prepare
        got = prepare(data, name or "talk.webm")
        if got.get("error"):
            return got
        return {**got, "message": message}
    if not message:
        return {"error": "empty"}
    return {"message": message}


def reply_model() -> str:
    return (os.environ.get("OPENAI_MODEL") or "gpt-4o-mini").strip() or "gpt-4o-mini"


def complete(prompt: str, image: Optional[str], mime: str, user_id: str) -> str:
    """One chat call on the shared client. Empty when the provider is down."""
    from typing import cast

    from services.llm import chat_complete
    from services.llm_config import LLMSpec
    spec = LLMSpec(model=reply_model(), temperature=0.4, max_tokens=450, timeout_seconds=30.0)
    if image:
        content: Any = [{"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{image}"}}]
    else:
        content = prompt
    messages = cast(list, [{"role": "user", "content": content}])
    result = chat_complete(
        spec=spec, system="You write one short message for the host.",
        user=prompt, surface="chat_builder_reply", user_id=user_id,
        messages_override=messages,
    )
    return strip_feelings(strip_person_scores(getattr(result, "text", "") or ""))


def _rows(query: Any) -> list[dict]:
    data = getattr(query.execute(), "data", None)
    return list(data or [])


def load_examples(database: Any, host_id: str) -> list[dict]:
    """The host's taught pairs, newest first, up to 20. None when the table is not there yet."""
    try:
        rows = _rows(database.client.table("chat_reply_examples").select("ask, answer")
                     .eq("host_id", str(host_id)).order("created_at", desc=True).limit(20))
    except Exception:
        logger.warning("chat_builder_reply: taught answers could not be read", exc_info=True)
        return []
    return [{"ask": str(row.get("ask") or ""), "answer": str(row.get("answer") or "")} for row in rows]


def remember_example(database: Any, host_id: str, ask: str, answer: str, chat_id: str) -> None:
    """What the person asked, and the host's own words. Best-effort."""
    ask, answer = " ".join(str(ask or "").split()), " ".join(str(answer or "").split())
    if not ask or not answer:
        return
    try:
        database.client.table("chat_reply_examples").insert({
            "host_id": str(host_id), "chat_id": str(chat_id or "")[:80],
            "ask": ask[:2000], "answer": answer[:4000],
        }).execute()
    except Exception:
        logger.warning("chat_builder_reply: the taught pair was not kept", exc_info=True)


def save_draft(database: Any, host_id: str, chat_id: str, said: str, answer: str,
               walk: Optional[list]) -> None:
    try:
        database.client.table("chat_reply_drafts").insert({
            "host_id": str(host_id), "chat_id": str(chat_id or "")[:80],
            "said": " ".join(str(said or "").split())[:2000],
            "answer": str(answer or "")[:4000], "status": "draft",
            "walk": walk,
        }).execute()
    except Exception:
        logger.warning("chat_builder_reply: the draft was not kept", exc_info=True)


def waiting_drafts(database: Any, host_id: str, recipe: dict) -> list[dict]:
    """Drafts from the builder's visitor try, oldest first, in the host's list."""
    try:
        rows = _rows(database.client.table("chat_reply_drafts")
                     .select("id, chat_id, said, answer, created_at")
                     .eq("host_id", str(host_id)).eq("status", "draft").limit(100))
    except Exception:
        logger.warning("chat_builder_reply: drafts could not be read", exc_info=True)
        return []
    rows.sort(key=lambda row: str(row.get("created_at") or ""))
    sensitive = recipe.get("sensitive") is not False
    return [{"message_id": str(row.get("id") or ""), "thread_id": str(row.get("chat_id") or ""),
             "from": "Visitor", "said": row.get("said") or "", "answer": row.get("answer") or "",
             "lines": [], "sensitive": sensitive} for row in rows if row.get("id")]


def send_kept_draft(database: Any, host_id: str, message_id: str, body: Any) -> Optional[dict]:
    """Send one builder draft, or None when this id is not one of them.

    A changed answer is kept as a taught pair and, as every other changed
    draft, teaches a model still learning on the host's cards.
    """
    from services import chat_recipes
    try:
        rows = _rows(database.client.table("chat_reply_drafts").select("*")
                     .eq("id", str(message_id)).eq("host_id", str(host_id)).eq("status", "draft")
                     .limit(1))
    except Exception:
        logger.warning("chat_builder_reply: the draft could not be read", exc_info=True)
        return None
    if not rows:
        return None
    draft = rows[0]
    own = (body or {}).get("body") if isinstance(body, dict) else None
    answer = str(draft.get("answer") or "")
    changed = None
    if own is not None:
        from services.chats import ChatsError
        from services.chat_replies import MAX_SAID
        changed = " ".join(str(own).split())
        if not changed or len(changed) > MAX_SAID:
            raise ChatsError("NOT_ALLOWED", f"Write 1 to {MAX_SAID} characters.")
        answer = changed
    if not answer:
        from services.chats import ChatsError
        raise ChatsError("NOT_ALLOWED", "Write the answer.")
    try:
        database.client.table("chat_reply_drafts").update(
            {"status": "sent", "answer": answer}).eq("id", str(draft["id"])).execute()
    except Exception:
        logger.warning("chat_builder_reply: the draft was not marked sent", exc_info=True)
    if changed and changed != (draft.get("answer") or ""):
        remember_example(database, host_id, str(draft.get("said") or ""), answer,
                         str(draft.get("chat_id") or ""))
        chat_recipes.teach(database, host_id, changed)
    return {"message": {"id": str(draft["id"]), "body": answer}}


def _held_or_sent(act: str, reply: str, walk: Optional[list], database: Any, user_id: str,
                  chat_id: str, said: str) -> tuple[dict, int]:
    if act == "draft":
        save_draft(database, user_id, chat_id, said, reply, walk)
        return {"shown": False, "held": True, "reply": None}, 200
    body: dict[str, Any] = {"shown": True, "reply": reply or None}
    if walk:
        body["walk"] = walk
    return body, 200


def _with_voice(upload: dict, user_id: str, message: str, extra: dict) -> tuple[str, dict, dict]:
    from services.chat_voice import hear
    heard = hear(upload["raw"], upload["name"], upload["audio"], upload["rate"], user_id)
    extra["voice"] = heard["facts"]
    extra["file_text"] = heard["transcript"]
    message = message or heard["transcript"] or "They sent a recording."
    found = heard.get("measures")
    return message, found if isinstance(found, dict) else {}, extra


def reply(database: Any, user_id: str, chat_id: str, payload: Any, *,
          recipe: dict, host_answers: int) -> tuple[dict, int]:
    """The visitor's answer. ``(body, status)`` in the shape the builder reads."""
    payload = payload if isinstance(payload, dict) else {}
    kind = str(payload.get("kind") or "text")
    upload = read_upload(kind, payload)
    if upload.get("error") == "empty":
        return {"error": "empty"}, 400
    if upload.get("error"):
        return {"error": upload["error"]}, 200
    setup = setup_of(recipe, load_examples(database, user_id), host_answers)
    act = reply_act(setup["who"], setup["care"], host_answers)
    if act == "none":
        return {"shown": False, "quiet": True, "reply": None}, 200
    if act == "wait":
        return {"shown": False, "wait": True, "reply": None}, 200
    message = str(upload.get("message") or "")
    extra: dict[str, Any] = {"picks": setup["picks"]}
    measures = None
    if kind == "rec":
        message, measures, extra = _with_voice(upload, user_id, message, extra)
    elif kind == "photo":
        extra["has_image"] = True
    elif kind == "file":
        extra["file_text"] = upload.get("file_text") or ""
    prompt = build_prompt(setup, message or "They sent a file.", extra)
    image = upload.get("image") if kind == "photo" else None
    text = complete(prompt, image, str(upload.get("mime") or "image/jpeg"), user_id)
    walk = None
    if measures is not None:
        from services.chat_voice import walk_from
        walk = walk_from(measures, setup["steps"], setup["ideal"])
        if not text and walk:
            text = str(walk[0]["text"])
    return _held_or_sent(act, text, walk, database, user_id, chat_id, message)
