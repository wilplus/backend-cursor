"""The corpus's learn/test split, by speaker (founder 2026-10-06, CO1 A,
decisions log N56.4; migration 0433).

THE RULE. "Labels are split by speaker: 80% to learn from, 20% held out for
testing, decided by a fixed hash and never re-shuffled." Every label on an
imported clip takes the split of the import's SPEAKER, so one voice is never
on both sides: a model tested on a voice it learned from would read better
than it is.

THE SPEAKER KEY. The import's "Whose voice this is" field (``speaker_label``),
normalised (NFKC, trimmed, case-folded, inner whitespace collapsed), so
"Jane Doe" and " jane  doe" are one speaker. An import with no speaker name is
a speaker of its own, keyed ``import:<session_id>``: it can never join another
import's group by accident. Not the importing coach's user id: the coach
uploads many voices, and keying on the uploader (``confidence_dataset.
speaker_key`` prefers owner/user ids) would put the whole corpus in one group.

THE HASH. ``sha256(f"{SPLIT_SALT}:{speaker_key}")`` read as an integer, mod
100; under ``TEST_PERCENT`` (20) is ``test``, the rest ``train``. Pure and
deterministic.

NEVER RE-SHUFFLED. The first assignment of a speaker is stored
(``corpus_speaker_splits``, written insert-once; the table refuses an UPDATE
or a DELETE), and the stored row wins over any later computation, so editing
``SPLIT_SALT`` one day moves no speaker who already has a split. The table
holds a digest of the key, never the name, and no user id.

NOTHING TRAINS ON IT. This module assigns and reads; no dataset release,
training run, evaluation or promotion reads it while their constants stay
closed. Nothing here reaches a speaker or a coach (AC-9).
"""
from __future__ import annotations

import hashlib
import logging
import re
import unicodedata
from typing import Any, Optional

logger = logging.getLogger(__name__)

#: Fixed for the life of the corpus. A stored assignment outlives any edit.
SPLIT_SALT = "willab-corpus-speaker-split-2026-10-06"
SPLIT_VERSION = "corpus-speaker-sha256-80-20-v1"
TEST_PERCENT = 20
TRAIN = "train"
TEST = "test"
SPLITS = (TRAIN, TEST)
TABLE = "corpus_speaker_splits"
#: Domain separation: the stored digest is not the split hash.
_DIGEST_PREFIX = "corpus-speaker:"
_SPACE_RE = re.compile(r"\s+", re.UNICODE)


def normalise_speaker_label(raw: Any) -> Optional[str]:
    """NFKC, trimmed, case-folded, inner whitespace collapsed; None when
    nothing is left. Pure."""
    if not isinstance(raw, str):
        return None
    text = _SPACE_RE.sub(" ", unicodedata.normalize("NFKC", raw)).strip()
    return text.casefold() or None


def speaker_key_for(speaker_label: Any, session_id: Any) -> str:
    """The import's speaker key: its normalised speaker name, else the import
    itself (``import:<session_id>``). Pure."""
    name = normalise_speaker_label(speaker_label)
    if name:
        return name
    return f"import:{str(session_id or '').strip()}"


def corpus_split(speaker_key: str) -> str:
    """``'train'`` or ``'test'`` for one speaker key, by the fixed hash. Pure;
    use the stored assignment where one exists (``assign_speaker_split``)."""
    digest = hashlib.sha256(f"{SPLIT_SALT}:{speaker_key}".encode("utf-8"))
    return TEST if int(digest.hexdigest(), 16) % 100 < TEST_PERCENT else TRAIN


def speaker_key_digest(speaker_key: str) -> str:
    """What the table stores for a speaker key: never the name itself."""
    return hashlib.sha256(
        f"{_DIGEST_PREFIX}{speaker_key}".encode("utf-8")).hexdigest()


def _stored(row: Any) -> Optional[dict]:
    if not isinstance(row, dict) or row.get("split") not in SPLITS:
        return None
    return {"split": row["split"], "split_version": row.get("split_version"),
            "assigned_at": row.get("assigned_at")}


def read_speaker_split(database: Any, speaker_key: str) -> Optional[dict]:
    """The stored ``{split, split_version, assigned_at}`` for a speaker key,
    or None when none is stored or the table cannot be read."""
    try:
        rows = (database.client.table(TABLE)
                .select("split, split_version, assigned_at")
                .eq("speaker_key_sha256", speaker_key_digest(speaker_key))
                .limit(1).execute().data) or []
    except Exception as error:  # noqa: BLE001 - logged; None is "unknown"
        logger.warning("corpus split read failed: %s", error, exc_info=True)
        return None
    return _stored(rows[0]) if rows else None


def assign_speaker_split(database: Any, speaker_key: str) -> Optional[dict]:
    """Store this speaker's split if none is stored, then return the stored
    one: the first assignment wins, a later computation never replaces it.

    Insert-once (``ON CONFLICT DO NOTHING``), so two imports of one speaker
    racing each other both read back the same row. None when the table
    cannot be written or read: the import stands, and the next import of the
    same speaker, or ``import_split`` later, assigns it.
    """
    row = {
        "speaker_key_sha256": speaker_key_digest(speaker_key),
        "split": corpus_split(speaker_key),
        "split_version": SPLIT_VERSION,
    }
    try:
        (database.client.table(TABLE)
         .upsert(row, on_conflict="speaker_key_sha256", ignore_duplicates=True)
         .execute())
    except Exception as error:  # noqa: BLE001 - logged; the read decides
        logger.warning("corpus split assignment failed: %s", error,
                       exc_info=True)
    return read_speaker_split(database, speaker_key)


def import_speaker_key(session: Any) -> Optional[str]:
    """The speaker key of one import session row, or None for a row that is
    not a training import."""
    if not isinstance(session, dict) or not session.get("id"):
        return None
    if session.get("source") not in (None, "training_import"):
        return None
    ctx = session.get("intake_context")
    ctx = ctx if isinstance(ctx, dict) else {}
    return speaker_key_for(ctx.get("speaker_label"), session.get("id"))


def import_split(database: Any, session_id: Any) -> Optional[dict]:
    """For one import session, its speaker's stored split:
    ``{session_id, split, split_version, assigned_at}``. None when the session
    is not an import or its speaker has no stored split yet (it is assigned
    when the import's analysis finishes). Read only; nothing trains on it."""
    try:
        session = database.v2_get_session_by_id(str(session_id)) or {}
    except Exception as error:  # noqa: BLE001 - logged; None is "unknown"
        logger.warning("corpus split session read failed sid=%s: %s",
                       session_id, error, exc_info=True)
        return None
    key = import_speaker_key(session)
    if key is None:
        return None
    stored = read_speaker_split(database, key)
    if stored is None:
        return None
    return {"session_id": str(session_id), **stored}
