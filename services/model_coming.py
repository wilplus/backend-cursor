"""Models that learn from images, from video and from recordings: coming
(N642 item 6, N643 item 4, N645). "I want this" sends the founder one mail,
as a request for the feature, once per kind and person (N641 item 3's
vote); nothing is counted and no number is shown.

Kept without a table: the account's own Supabase user_metadata holds
``models_wanted`` = {kind: when asked}, as it holds the phone number
(services/admin_person.py). It goes with the account when the account is
deleted. For a person with the chat builder (ring ``chat_builder``) or the
AI models (ring ``ai_models``); anyone else gets 404.
"""
from __future__ import annotations

import html
import logging
from datetime import datetime, timezone
from typing import Any

from services.chats import ChatsError

logger = logging.getLogger(__name__)

#: Each kind and its title (N643 item 4, N645).
KINDS: tuple[tuple[str, str], ...] = (("images", "Images"), ("video", "Video"), ("recordings", "Recordings"))
_TITLES = dict(KINDS)
KEY = "models_wanted"


def on(database: Any, user_id: Any) -> bool:
    """The chat builder or the AI models. Fails closed."""
    from services import model_launchpad_store, rings
    from services.assistants import CHAT_BUILDER
    if not user_id:
        return False
    try:
        return (rings.feature_is_on_for_user(CHAT_BUILDER, str(user_id), database=database)
                or model_launchpad_store.enabled(database, str(user_id)))
    except Exception:  # noqa: BLE001 -- closed
        logger.warning("model_coming: the rings could not be read; closed", exc_info=True)
        return False


def _wanted(user_id: str) -> dict:
    """{kind: when} from the account's user_metadata; unread is none."""
    from services.admin_person import auth_user
    try:
        user = auth_user(user_id) or {}
    except Exception:  # noqa: BLE001 -- unread: each still offers "I want this"
        logger.warning("model_coming: the account could not be read", exc_info=True)
        return {}
    value = (user.get("user_metadata") or {}).get(KEY)
    return {k: v for k, v in value.items() if k in _TITLES} if isinstance(value, dict) else {}


def _list(wanted: dict) -> list[dict]:
    return [{"kind": kind, "title": title, "wanted": kind in wanted} for kind, title in KINDS]


def coming(database: Any, user_id: Any) -> dict:
    """GET /v2/models/coming: {"coming": [{kind, title, wanted}]}."""
    if not on(database, user_id):
        raise ChatsError("NOT_FOUND", "Not found.", 404)
    return {"coming": _list(_wanted(str(user_id)))}


def listed(user_id: Any) -> list[dict]:
    """The same list, for a read that already checked who may see it."""
    return _list(_wanted(str(user_id)))


def want(database: Any, user_id: Any, kind: Any, token_payload: Any) -> dict:
    """POST /v2/models/coming/<kind>/want: {"wanted": true}. The first time,
    kept and one mail to the founder; again, nothing more. A mail or a save
    that cannot be done is logged; the answer is the same."""
    if kind not in _TITLES or not on(database, user_id):
        raise ChatsError("NOT_FOUND", "Not found.", 404)
    user_id = str(user_id)
    wanted = _wanted(user_id)
    if kind in wanted:
        return {"wanted": True}
    from services.admin_person import set_metadata
    try:
        set_metadata(user_id, {KEY: {**wanted, kind: datetime.now(timezone.utc).isoformat()}})
    except Exception as e:  # noqa: BLE001 -- the mail still goes
        logger.warning("model_coming: the ask could not be kept: %s", e)
    _tell_founder(user_id, _name(token_payload), kind)
    return {"wanted": True}


def _name(token_payload: Any) -> str:
    from services.chat_links import name_of
    payload: dict = token_payload if isinstance(token_payload, dict) else {}
    raw = payload.get("user_metadata")
    meta: dict = raw if isinstance(raw, dict) else {}
    return " ".join(str(meta.get("full_name") or meta.get("name") or "").split()) or name_of(payload)


def _tell_founder(user_id: str, name: str, kind: str) -> None:
    """The feature request, by mail. Never fails the ask."""
    try:
        from config import Config
        from services.email_service import send_email_resend
        config = Config()
        title = _TITLES[kind]
        lines = [f"{name} (user {user_id}) wants models that learn from {title.lower()}.", "",
                 f"A request for the feature (N642 item 6, N645): {title}, coming."]
        send_email_resend(to=config.ADMIN_EMAIL, subject=f"{name} wants models that learn from {title.lower()}",
                          html="<br>".join(html.escape(line) for line in lines), text="\n".join(lines))
    except Exception as e:  # noqa: BLE001 -- the ask is kept either way
        logger.warning("model_coming: the request mail not sent: %s", e)
