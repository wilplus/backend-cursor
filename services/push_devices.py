"""Push to the iPhone app (founder 2026-11-03, N385; N365 item 4).

Two pushes, in the iPhone app only: "The feedback from your coach is in!"
(N171's words, when its WhatsApp would go; ``coach_feedback_notice``) and a
new chat message, the sender's name over the line the chat list shows for it
(``chats``). Each push carries the app's ``path`` to open when tapped.

The app gives its address (Apple's device token) after iOS's own permission
question, asked once, after the first feedback (N385 item 2):

  POST   /v2/user/push-device  {token}   kept for the caller, once per token
  DELETE /v2/user/push-device  {token}   forgotten (sign-out)

Sent through Apple's push service (APNs) with a token key: nothing is sent
unless APNS_KEY_ID, APNS_TEAM_ID and APNS_AUTH_KEY (the .p8 key's text) are
set on Railway; APNS_TOPIC is the app's bundle id (com.willpowerlab.app).
An address is tried on Apple's production service, then its sandbox (an app
run from Xcode), and keeps the one that answered. Apple's "no longer
valid" (410, BadDeviceToken on both) forgets the address.

Best-effort everywhere (LIVE LOOP): a push never fails or slows the save or
the send that caused it; ``push_later`` runs it beside the request. The
addresses go with the account (services/data_purge_registry.py).
"""
from __future__ import annotations

import logging
import os
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

TABLE = "push_devices"
DEFAULT_TOPIC = "com.willpowerlab.app"
_HOSTS = {"production": "https://api.push.apple.com",
          "sandbox": "https://api.sandbox.push.apple.com"}
#: An APNs device token: hex, 32 bytes today; room for longer ones.
_TOKEN = re.compile(r"^[0-9a-f]{64,200}$")
#: A token key's JWT lasts an hour at Apple; renewed well before.
_JWT_MAX_AGE_S = 50 * 60

_jwt_lock = threading.Lock()
_jwt_cache: dict[str, Any] = {"key": None, "token": None, "at": 0.0}


class PushDeviceError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code, self.status = code, status


def _table(database: Any) -> Any:
    return database.client.table(TABLE)


def _token_of(body: Any) -> str:
    token = (body or {}).get("token") if isinstance(body, dict) else None
    token = token.strip().lower() if isinstance(token, str) else ""
    if not _TOKEN.match(token):
        raise PushDeviceError("NOT_ALLOWED", "Not a device token.")
    return token


def save(database: Any, user_id: str, body: Any) -> dict:
    """Keep the caller's iPhone address; one row per token, the latest
    account's (a phone signed into another account moves with it)."""
    token = _token_of(body)
    now = datetime.now(timezone.utc).isoformat()
    _table(database).delete().eq("token", token).execute()
    _table(database).insert({"user_id": str(user_id), "token": token, "platform": "ios",
                             "last_seen_at": now}).execute()
    return {"ok": True}


def remove(database: Any, user_id: str, body: Any) -> dict:
    token = _token_of(body)
    _table(database).delete().eq("token", token).eq("user_id", str(user_id)).execute()
    return {"ok": True}


def _config() -> Optional[dict]:
    key_id = (os.environ.get("APNS_KEY_ID") or "").strip()
    team_id = (os.environ.get("APNS_TEAM_ID") or "").strip()
    # Railway keeps one line; a key pasted with "\n" in it is read back whole.
    key = (os.environ.get("APNS_AUTH_KEY") or "").strip().replace("\\n", "\n")
    if not (key_id and team_id and key):
        return None
    return {"key_id": key_id, "team_id": team_id, "key": key,
            "topic": (os.environ.get("APNS_TOPIC") or "").strip() or DEFAULT_TOPIC}


def _bearer(cfg: dict) -> str:
    import jwt

    with _jwt_lock:
        fresh = time.time() - _jwt_cache["at"] < _JWT_MAX_AGE_S
        if _jwt_cache["token"] and fresh and _jwt_cache["key"] == cfg["key_id"]:
            return str(_jwt_cache["token"])
        token = jwt.encode({"iss": cfg["team_id"], "iat": int(time.time())}, cfg["key"],
                           algorithm="ES256", headers={"kid": cfg["key_id"]})
        _jwt_cache.update(key=cfg["key_id"], token=token, at=time.time())
        return str(token)


def _send(client: Any, cfg: dict, token: str, environment: str, payload: dict) -> tuple[int, str]:
    """One push to one address on one of Apple's two services: (status, reason)."""
    res = client.post(f"{_HOSTS[environment]}/3/device/{token}", json=payload, headers={
        "authorization": f"bearer {_bearer(cfg)}", "apns-topic": cfg["topic"],
        "apns-push-type": "alert", "apns-priority": "10"})
    reason = ""
    if res.status_code != 200:
        try:
            reason = str((res.json() or {}).get("reason") or "")
        except ValueError:
            reason = ""
    return res.status_code, reason


def payload_of(*, title: Optional[str], body: str, path: str) -> dict:
    alert: Any = {"title": title, "body": body} if title else body
    return {"aps": {"alert": alert, "sound": "default"}, "path": path}


def push(database: Any, user_id: str, *, title: Optional[str], body: str, path: str,
         client: Any = None) -> int:
    """Push to every iPhone of ``user_id``; the number Apple accepted. Never raises."""
    try:
        cfg = _config()
        if not cfg or not user_id:
            return 0
        rows = (_table(database).select("token,environment").eq("user_id", str(user_id))
                .execute().data or [])
        if not rows:
            return 0
        if client is None:
            import httpx

            client = httpx.Client(http2=True, timeout=10.0)
        payload = payload_of(title=title, body=body, path=path)
        sent = 0
        for row in rows:
            sent += _push_one(database, client, cfg, row, payload)
        return sent
    except Exception as e:  # noqa: BLE001 -- a push never fails what caused it
        logger.warning("push: not sent user=%s: %s", user_id, e)
        return 0


def _push_one(database: Any, client: Any, cfg: dict, row: dict, payload: dict) -> int:
    token = str(row["token"])
    known = row.get("environment")
    tries = [known] if known in _HOSTS else ["production", "sandbox"]
    for environment in tries:
        status, reason = _send(client, cfg, token, environment, payload)
        if status == 200:
            if known != environment:
                _table(database).update({"environment": environment}).eq("token", token).execute()
            return 1
        if status == 410 or (status == 400 and reason == "BadDeviceToken" and environment == tries[-1]):
            _table(database).delete().eq("token", token).execute()
            return 0
        if not (status == 400 and reason == "BadDeviceToken"):
            logger.warning("push: Apple answered %s %s", status, reason)
            return 0
    return 0


def push_later(database: Any, user_id: str, *, title: Optional[str], body: str, path: str) -> None:
    """``push`` beside the request, so the send that caused it waits for nothing."""
    threading.Thread(target=push, args=(database, user_id), daemon=True,
                     kwargs={"title": title, "body": body, "path": path}).start()
