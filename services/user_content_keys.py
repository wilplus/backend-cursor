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

Four storage modules mint public URLs — ``coach_video_storage``,
``audio_storage``, ``lab_audio_storage`` and ``user_media_storage`` — for four
buckets, and a key can be written by one and read through another. (This
paragraph said THREE until 2026-09-23; ``user_media_storage`` was the one it
missed, and it was missing the check too.) If they disagree about what counts
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
#:
#: ``casual_voice/`` joined 2026-09-23 (P1). It was missed when this list was
#: written, and the miss is instructive: ``audio_public_url``'s own docstring
#: says "everything this bucket holds under ``session_recordings/`` and
#: ``guest_funnel/`` is a recording of someone speaking" — but
#: ``casual_voice_analytics`` writes ``casual_voice/<user>/<row>.webm`` through
#: ``put_audio_bytes`` into that SAME bucket. The sentence described the list,
#: not the bucket, and a third prefix of retained user voice sat outside it
#: getting permanent public URLs. Which is the exposure this module exists to
#: stop.
#:
#: ``mlc3-practice/`` joined the same day, and it is the better argument for
#: the test than ``casual_voice/`` is: nobody found it by reading. It is a
#: speaker re-recording a passage they were given to practise
#: (``practice_attempt_orchestrator``), and
#: ``tests/test_object_key_prefixes_are_classified.py`` surfaced it on its
#: first run, from a list nobody had to maintain. That test now fails when any
#: newly-written object key is classified neither way, which is the only way
#: FAIL TOWARD SIGNING can hold: a prefix that never reaches the question
#: cannot fail toward anything.
USER_CONTENT_PREFIXES: tuple[str, ...] = (
    "session_recordings/",
    "guest_funnel/",
    "willab_lab/",
    "charisma_snippets/",
    "snippets/",
    "willab_presentations/",
    "casual_voice/",
    "mlc3-practice/",
    # Per-person audit PDFs (migrations/add_user_audits.sql). Missed when this
    # list was written; found in the 2026-09-25 private-bucket audit.
    "willab_audits/",
)

#: Object-key prefixes this codebase writes that are deliberately NOT user
#: content, each with the reason. Listed rather than assumed, because the whole
#: defect this module addresses was a prefix nobody had classified either way.
#:
#: ``journal/``   media attached to a Journal post — material the author
#:                publishes on purpose, on a surface built to show it, not a
#:                recording captured while someone practises.
#: ``coach-feedback/`` and ``copilot/``
#:                coach-authored media on a surface that already gates access,
#:                per the split described above.
NON_USER_CONTENT_PREFIXES: tuple[str, ...] = (
    "journal/",
    "coach-feedback/",
    "copilot/",
)

#: Every prefix above, so a test can assert that a newly-written object key is
#: classified one way or the other before it ships. FAIL TOWARD SIGNING means
#: nothing if a prefix can simply never reach the question.
CLASSIFIED_PREFIXES: tuple[str, ...] = (
    USER_CONTENT_PREFIXES + NON_USER_CONTENT_PREFIXES
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
