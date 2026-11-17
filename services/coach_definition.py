"""A speaking-coach document (frontend docs/chat-builder/DESIGN.md).

The walk keeps today's constants unless a document for this person was
published. A paste is stored and checked. It is not imported and not run.
Preview validates and returns. It does not write.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Optional

SCHEMA = 1
SLUG = "speaking-coach"
CLOCK = 300
PLUGIN_TYPES = ("REWRITE", "EMPHASISE", "ADD", "NOTICE")
SCREENS = {
    "walk.page", "walk.message", "walk.audio", "walk.clearer", "walk.practise",
    "walk.tempo", "walk.aiVoice", "walk.others", "walk.words", "walk.done",
    "walk.end", "shell.historyCard", "shell.idealText", "shell.recording",
    "shell.picker", "will.composer", "will.sunday", "will.plan",
}
PINNED = {
    "tempo_stretch.GREEN_LOW": 0.275,
    "tempo_stretch.GREEN_HIGH": 0.725,
    "tempo_land.MIN_MS": 20000,
    "tempo_land.GREEN_SHARE": 0.8,
}
_BANNED = (
    (re.compile(r"\beval\s*\("), "eval"),
    (re.compile(r"\bexec\s*\("), "exec"),
    (re.compile(r"\bsubprocess\b"), "subprocess"),
    (re.compile(r"\bfetch\s*\("), "network"),
    (re.compile(r"\bXMLHttpRequest\b"), "network"),
    (re.compile(r"\bimport\s+(?:os|socket|http|urllib|requests)\b"), "network"),
    (re.compile(r"\bfrom\s+['\"]react['\"]"), "component"),
    (re.compile(r"<[A-Z][A-Za-z0-9]*(\s|/>|>)"), "component"),
)
_DIGIT = re.compile(r"\d")
_MANIFEST = re.compile(r"^(?:#\s*|//\s*)?(id|role|interventionType|hears|step):\s*(\S.*?)\s*$")


class CoachRefused(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def refuse(document: Any) -> Optional[str]:
    """None when the document may be stored. A code when it may not."""
    if not isinstance(document, dict) or document.get("schema") != SCHEMA or document.get("id") != SLUG:
        return "COACH_UNKNOWN"
    return (_refuse_shell(document) or _refuse_steps((document.get("walk") or {}).get("steps") or [])
            or _refuse_plugins(document.get("plugins") or []))


def _refuse_shell(document: dict) -> Optional[str]:
    shell = document.get("shell") or {}
    if shell.get("recordingClockSeconds") != CLOCK:
        return "COACH_CLOCK"
    if shell.get("publicLink") != "hardcoded_will":
        return "COACH_PUBLIC_LINK"
    if shell.get("surfaces") != ["feedback_walk", "ideal_text"]:
        return "COACH_SURFACES"
    will = document.get("will") or {}
    if will.get("recording") or will.get("composer") != "text":
        return "COACH_WILL"
    if (document.get("theme") or {}).get("canvasMaxPx") != 1080:
        return "COACH_CANVAS"
    pinned = {row.get("name"): row.get("value")
              for row in (document.get("noticing") or {}).get("pinned") or [] if isinstance(row, dict)}
    for name, value in PINNED.items():
        if pinned.get(name) != value:
            return "COACH_PINNED"
    return None


def _refuse_steps(steps: Any) -> Optional[str]:
    for step in steps:
        reason = _refuse_step(step)
        if reason:
            return reason
    return None


def _refuse_step(step: Any) -> Optional[str]:
    if not isinstance(step, dict) or step.get("screen") not in SCREENS:
        return "COACH_UNKNOWN_SCREEN"
    if step.get("key") == "tempo" and step.get("voice"):
        return "COACH_SNIPER_VOICE"
    lines = [step.get("fixed") or ""]
    lines += list(step.get("lines") or [])
    lines += [v.get("fixed") or "" for v in (step.get("variants") or []) if isinstance(v, dict)]
    lines += list(step.get("choices") or [])
    if any(isinstance(line, str) and _DIGIT.search(line) for line in lines):
        return "COACH_NUMBER"
    return None


def _refuse_plugins(plugins: Any) -> Optional[str]:
    for plugin in plugins:
        if not isinstance(plugin, dict) or plugin.get("interventionType") not in PLUGIN_TYPES:
            return "COACH_PLUGIN_TYPE"
    return None


def check_plugin(source: Any) -> dict:
    """Store-and-check. Does not import, exec, or eval the source."""
    text = source if isinstance(source, str) else ""
    reasons: list[str] = []
    if len(text.encode("utf-8")) > 32 * 1024:
        reasons.append("too_long")
    for pattern, reason in _BANNED:
        if pattern.search(text):
            reasons.append(reason)
    found: dict[str, str] = {}
    for line in text.splitlines()[:30]:
        match = _MANIFEST.match(line)
        if match:
            found[match.group(1)] = match.group(2)
    manifest = None
    if all(key in found for key in ("id", "role", "interventionType", "hears", "step")):
        manifest = {key: found[key] for key in ("id", "role", "interventionType", "hears", "step")}
        if manifest["role"] != "detector":
            reasons.append("role")
        if manifest["interventionType"] not in PLUGIN_TYPES:
            reasons.append("type")
        step = manifest["step"]
        if not (step.startswith("walk.") or step.startswith("shell.") or step.startswith("will.")):
            reasons.append("screen")
    else:
        reasons.append("manifest")
    if not reasons:
        status = "checked"
    elif reasons == ["manifest"]:
        status = "draft"
    else:
        status = "rejected"
    return {
        "status": status,
        "hash": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "source": text,
        "reasons": reasons,
        "manifest": manifest,
    }


def _key(user_id: str) -> str:
    return f"coach_definition:{user_id}:{SLUG}"


def _read(database: Any, user_id: str) -> Optional[dict]:
    raw = database.get_runtime_config(_key(user_id))
    if not raw:
        return None
    try:
        loaded = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return loaded if isinstance(loaded, dict) else None


def _write(database: Any, user_id: str, record: dict) -> None:
    key = _key(user_id)
    entry = database.get_runtime_config_entry(key) if hasattr(database, "get_runtime_config_entry") else None
    expected = entry.get("updated_at") if isinstance(entry, dict) else None
    database.put_runtime_config_entry(key, json.dumps(record), updated_by=user_id, expected_updated_at=expected)


def read_draft(database: Any, user_id: str) -> Optional[dict]:
    record = _read(database, user_id)
    if not record:
        return None
    return record.get("document")


def save_draft(database: Any, user_id: str, document: Any) -> dict:
    reason = refuse(document)
    if reason:
        raise CoachRefused(reason)
    record = _read(database, user_id) or {"versions": []}
    version = int(record.get("version") or 0) + 1
    document = {**document, "version": version}
    versions = list(record.get("versions") or [])
    versions.append({"version": version, "status": "draft"})
    saved = {"status": "draft", "version": version, "document": document, "versions": versions[-20:]}
    _write(database, user_id, saved)
    return saved


def publish(database: Any, user_id: str) -> dict:
    record = _read(database, user_id)
    if not record or not record.get("document"):
        raise CoachRefused("COACH_UNKNOWN")
    reason = refuse(record["document"])
    if reason:
        raise CoachRefused(reason)
    record = {**record, "status": "published"}
    _write(database, user_id, record)
    return record


def dial_value(database: Any, user_id: str, name: str) -> Optional[float]:
    """A published dial, or None so the caller keeps noticing_settings."""
    try:
        document = read_active(database, user_id)
    except Exception:  # noqa: BLE001 -- a missing store is today's constants
        return None
    if not document:
        return None
    for row in (document.get("noticing") or {}).get("dials") or []:
        if isinstance(row, dict) and row.get("name") == name and isinstance(row.get("default"), (int, float)) and not isinstance(row.get("default"), bool):
            return float(row["default"])
    return None


def read_active(database: Any, user_id: str) -> Optional[dict]:
    record = _read(database, user_id)
    if not record or record.get("status") != "published":
        return None
    return record.get("document")


def preview(document: Any) -> dict:
    """Validate only. Callers must not write around this."""
    reason = refuse(document)
    if reason:
        raise CoachRefused(reason)
    keys = [step.get("key") for step in (document.get("walk") or {}).get("steps") or [] if isinstance(step, dict)]
    return {"ok": True, "keys": keys, "wrote": False}


def keep_plugin(database: Any, user_id: str, source: Any) -> dict:
    checked = check_plugin(source)
    record = _read(database, user_id) or {"status": "draft", "version": 0, "document": None, "versions": []}
    plugins = [row for row in record.get("plugins") or [] if row.get("hash") != checked["hash"]]
    plugins.append({key: checked[key] for key in ("status", "hash", "reasons", "manifest")})
    record = {**record, "plugins": plugins[-20:]}
    _write(database, user_id, record)
    return checked
