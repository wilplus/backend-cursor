"""One closed set of `runtime_config` keys that can name a model, one gate.

LEGACY-1, J1-2 and R-13 (audit 2026-09-22) are one defect wearing three
names: ``runtime_config`` is a service-role-writable table with no RLS, and
five of its keys are read straight into the ``model`` argument of an OpenAI
chat completion. Two of those five compose the Take-1 Ideal Text and every
Say It Stronger card. A row appearing in that table therefore changed the
words in a speaker's document, within the sixty-second cache TTL, with no
flag consulted, no evaluation recorded and nothing in the codebase surprised.

The three constants that documented this lane as switched off
(``MLC2_DATASET_RELEASES_ENABLED``, ``MLC2_TRAINING_ENABLED``,
``MLC2_PROMOTION_ENABLED``) were read only by the readiness evaluators. They
are now load-bearing.

Two properties, and the module exists to make both testable in one place:

  CLOSED   a key that is not in ``MODEL_CONFIG_KEYS`` is never resolved into
           a model id. Adding a key is a code change, reviewable as one.
  GATED    reading one of them requires ``Config.MLC2_PROMOTION_ENABLED``.
           Shut — which is how it ships — the caller's own default is used
           and one ``promotion_disabled`` line is logged.

This is the Python half. The database half is
``migrations/guard_runtime_config_model_keys.sql``, because a Python gate
cannot bind a psql session holding the service-role key.

NOTHING HERE OPENS ANYTHING. Every default is the shipped one.
"""
from __future__ import annotations

import logging
from typing import Callable, Optional

logger = logging.getLogger(__name__)


# THE ALLOWLIST. Literal on purpose: a list computed from the registry it is
# supposed to constrain is not a constraint. Adding a key here is a reviewable
# code change, and `tests/test_runtime_config_keys_are_enumerated.py` fails if
# a trainable surface's key is missing from it, or if any key read anywhere in
# services/, scripts/ or routes/ is absent.
#
# `openai_surface_model_moment_suggestion` is deliberately NOT here: the
# canonical registry rejects that alias (E-6), so the surface no longer exists
# to be promoted. The SQL trigger still covers the key by prefix.
MODEL_CONFIG_KEYS = frozenset({
    # Learned surfaces, promoted by scripts/promote_openai_model.py.
    "openai_surface_model_say_it_stronger",
    "openai_surface_model_coach_comment_draft",
    "openai_surface_model_ideal_text",
    # The two ungoverned chat surfaces (R-13). Neither is a learned surface
    # and neither has a writer in this repository; they are listed because
    # they are READ, and an unlisted readable key is the hole this closes.
    "openai_chat_model",
    "openai_copilot_model",
})


def promotion_is_enabled() -> bool:
    """The one place the promotion gate is read."""
    from config import Config

    return bool(getattr(Config, "MLC2_PROMOTION_ENABLED", False))


def resolve_gated_model(
    key: str,
    *,
    read: Callable[[str], object],
    default: Optional[str] = None,
) -> Optional[str]:
    """The stored model for ``key``, or ``default`` while the gate is shut.

    Raises ``ValueError`` for a key outside the allowlist — a caller that
    invents a key is a bug, not a configuration, and must not fall back
    quietly into reading it.
    """
    name = str(key or "").strip()
    if name not in MODEL_CONFIG_KEYS:
        raise ValueError(
            f"{name!r} is not an enumerated runtime model key; add it to "
            "services.runtime_model_gate.MODEL_CONFIG_KEYS and guard it in "
            "migrations/guard_runtime_config_model_keys.sql first"
        )
    if not promotion_is_enabled():
        # Not a warning: this is the shipped posture, and a warning per call
        # would train the operator to ignore the log. It is logged at all
        # because "the row is there and is not being served" is otherwise
        # indistinguishable from "the row is not there".
        logger.info(
            "runtime_model_gate key=%s promotion_disabled served=default", name,
        )
        return default
    try:
        raw = read(name)
    except Exception as exc:
        logger.warning("runtime_model_gate key=%s read_failed err=%s", name, exc)
        return default
    # Mock objects, JSON objects and malformed values must never be
    # stringified into an OpenAI model identifier.
    value = raw.strip() if isinstance(raw, str) else None
    return value or default
