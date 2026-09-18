"""Which object keys hold USER content, and therefore must never be handed
out on a public bucket URL.

WHY THIS EXISTS (DPIA RISK-11, found 2026-09-17).

``coach-feedback-videos`` and ``user-interview-audio`` are both served through
Cloudflare **public development URLs** (``R2_PUBLIC_BASE_URL``,
``R2_AUDIO_PUBLIC_BASE_URL``). A public URL for an object is permanent and
unauthenticated: once it leaves our systems — forwarded, screenshotted, in a
referrer header, in a support ticket — it grants access to that recording
forever, and it cannot be revoked or expired short of deleting the object.

Keys embed UUIDs, so nothing is enumerable and there is no listing. The
exposure is the single leaked URL, not a browsable archive. That is still an
Art 32 problem for voice recordings, and the codebase already implements the
ordinary control — short-lived presigned GETs.

THE SPLIT THIS MODULE ENCODES.

Not everything in those buckets is user content, and the distinction is load
bearing, because the public path exists for a reason. Slide decks
(``willab_presentations/``) are served from stored refs that are read years
after they are written; when they were signed with a 7-day TTL and nothing
re-signed them, every deck went dark a week after upload — reported 2026-09-16,
fixed by moving decks to the permanent public URL. Coach-authored media
(``coach-feedback/``, ``copilot/``) is the coach's own material on a surface
that already gates access.

So: user recordings sign, everything else keeps the public path it has.

WHY A SEPARATE MODULE RATHER THAN A CONSTANT IN ONE OF THEM.

Three storage modules mint public URLs — ``coach_video_storage``,
``audio_storage`` and ``lab_audio_storage`` — for three buckets, and a key can
be written by one and read through another. If they disagree about what counts
as user content, a recording is signed on one surface and public on another,
which is the same as not signing it. One list, imported by all three.

FAIL TOWARD SIGNING. An unknown prefix that should have been listed here stays
public, which is the exposure. A prefix listed here that did not need to be
costs a signature and a shorter-lived URL. Those are not symmetric, so when in
doubt, add it.

WHAT THIS DOES NOT CLOSE. The buckets remain publicly readable, so every URL
already issued stays valid. Only a private-bucket migration closes that; it is
DPIA M11.4 and it is a founder decision.
"""
from __future__ import annotations

from typing import Any

#: Key prefixes holding recordings of, or uploads by, an end user.
#:
#: ``session_recordings/``  concatenated full session audio
#: ``guest_funnel/``        per-turn audio captured before an account exists
#: ``willab_lab/``          uploaded Take audio
#: ``charisma_snippets/``   extracted clips of user speech (historical prefix)
#: ``snippets/``            the same, under the post-rename prefix
#: ``willab_presentations/`` uploaded slide decks
#:
#: Decks joined the list 2026-09-18. They were held back a day because they are
#: the prefix the permanent public URL was introduced FOR: signed with a 7-day
#: TTL and nothing re-signing them, every deck went dark a week after upload
#: (reported 2026-09-16). Moving them back onto signed URLs is only safe once
#: the read path mints a FRESH signature from the object key on every read, so
#: that no stored URL has to stay valid. ``refreshed_media_url`` now does that,
#: which retires the incident's root cause rather than avoiding it.
#:
#: ``charisma_snippets/`` is the R2 object prefix, NOT the table — the table was
#: renamed to ``snippets`` (migration 0260) and the object prefix deliberately
#: was not, because existing rows carry existing keys and rewriting 382 objects
#: buys nothing. Both spellings are listed so a future writer using the new one
#: is covered on the day it lands rather than the day someone notices.
USER_CONTENT_PREFIXES: tuple[str, ...] = (
    "session_recordings/",
    "guest_funnel/",
    "willab_lab/",
    "charisma_snippets/",
    "snippets/",
    "willab_presentations/",
)


def is_user_content_key(storage_key: Any) -> bool:
    """True when ``storage_key`` addresses user content.

    Takes a bucket-relative key, not a URL. Leading slashes are tolerated
    because callers disagree about them. Anything that is not a non-empty
    string is False: a missing key cannot be user content, and raising here
    would turn a cosmetic read into a 500.
    """
    if not isinstance(storage_key, str):
        return False
    key = storage_key.strip().lstrip("/")
    if not key:
        return False
    return key.startswith(USER_CONTENT_PREFIXES)
