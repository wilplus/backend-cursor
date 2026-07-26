"""The Life Panel — the hashtag router (BE-5, founder-directed 2026-07-26).

ONE public function, ``handle_note``. It is what the chat route calls and what
``POST /v2/life/notes`` calls, so the two entrances behave identically.

Routing is by HASHTAG, not by classifier (§5). The user declares the intent, so
the system is never wrong about what they meant: deterministic, free, and
unambiguous. There is no model in the routing decision — only in what happens
after it.

The order of operations is deliberate and load-bearing:

  1. GATE   — consent first (L-6: nothing is written before it), then setup.
  2. STORE  — the note lands in life_notes REGARDLESS of tag. Capture never
              fails and never blocks. If the derivation below explodes, the
              note is already safe.
  3. DERIVE — the route's engine call. Every result is a PROPOSAL.
  4. ATTACH — the single best-fitting wall phrase, or nothing at all.

Step 2 before step 3 is the whole reliability story. An OpenAI outage, a bad
schema day, a timeout — all of them cost the derivation and none of them cost
the note.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Optional

from config import Config
from services import life_panel as lp
from services import life_store as store
from services import life_engine as engine

logger = logging.getLogger(__name__)
config = Config()


# ═════════════════════════════════════════════════════════════════════════
# USER-FACING COPY — HELD FOR FOUNDER SIGN-OFF BEFORE IT SHIPS
# ═════════════════════════════════════════════════════════════════════════
# The house standing constraint: product copy is held for founder sign-off,
# and §6.2 names the redirect line specifically ("The redirect line is product
# copy on a live surface → founder sign-off before it ships").
#
# Every string a user can read is in this ONE dict so the review is a single
# diff rather than a grep. These are PLACEHOLDERS with the right shape, not
# approved wording. LIFE_PANEL_ENABLED defaults to 0, so nothing here reaches
# a user until the flag is flipped — which is the gate that makes shipping the
# code before the copy safe.
COPY: dict[str, str] = {
    "needs_setup": (
        "Saved. The engine needs your setup answers before it can work on "
        "this — finish the Principles setup and this note runs automatically, "
        "exactly as you wrote it."
    ),
    "captured": "Captured.",
    "card_edited": "Today's one thing is updated.",
    "win_saved": "On the wall.",
    "phrase_saved": "Added to the phrase wall.",
    "case_no_derivation": (
        "Saved. Couldn't work it through just now — it's in the queue as you "
        "wrote it."
    ),
    "conflict_intro": "Two of your principles pull opposite ways here:",
    "retire_question": "Does this retire #{n}?",
}


_VIEW_FOR_ROUTE: dict[str, str] = {
    "case": "principles",
    "goal_diff": "strategy",
    "win": "wins",
    "phrase": "phrases",
    "edit": "today",
    "capture": "notes",
}


def _panel_link(route: str) -> str:
    return f"/panel/{_VIEW_FOR_ROUTE.get(route, 'notes')}"


def is_enabled() -> bool:
    """The global kill switch. Off ⇒ the router is never reached and chat is
    byte-identical to today (N3)."""
    return bool(getattr(config, "LIFE_PANEL_ENABLED", False))


def is_allowlisted(user_id: Optional[str]) -> bool:
    """Founder-only surfaces (the prayer link, coach-only entries).

    NOT the principles engine — that ships public behind the consent screen
    (L-6). Non-members get 404s and absent menu entries, never a 403: a 403
    confirms the surface exists."""
    if not user_id:
        return False
    return str(user_id) in set(getattr(config, "LIFE_PANEL_ALLOWLIST", ()) or ())


# ── consent cache — a live-loop protection, not an optimisation ──────────
#
# With LIFE_PANEL_ENABLED=1 the chat route asks "has this user consented?" on
# EVERY signed-in turn, so that the per-user block (BE-9) can be retrieved for
# participants. Uncached, that is a Supabase round trip added to the shipped
# chat path for every user — including everyone who will never touch this
# feature — and a `#` message pays it twice. Scaffolding must not make the
# live loop slower; that is the whole premise of the fence.
#
# Consent is append-only and changes at most twice in a user's life (grant,
# and the hard delete that removes it), so a short TTL is safe. Both events
# call `invalidate_consent`, which is what makes this a cache rather than a
# staleness bug: without the invalidation on grant, a user who just accepted
# would keep being treated as a non-participant for five minutes, and without
# the one on delete a wiped account would keep passing the gate and could
# write fresh rows into the account it just emptied.
_CONSENT_TTL_SECONDS = 300
_CONSENT_CACHE_MAX = 5000
_consent_cache: dict[str, tuple[float, bool]] = {}


def invalidate_consent(user_id: str) -> None:
    """Drop the cached answer for one user. Called on grant and on hard
    delete — the only two moments the answer can change."""
    for key in [k for k in _consent_cache if k.startswith(f"{user_id}:")]:
        _consent_cache.pop(key, None)


def has_consented(user_id: str) -> bool:
    version = getattr(config, "LIFE_PANEL_CONSENT_VERSION", "1.0")
    key = f"{user_id}:{version}"
    hit = _consent_cache.get(key)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    answer = bool(store.get_consent(user_id, version=version))
    if len(_consent_cache) >= _CONSENT_CACHE_MAX:
        # Bounded rather than clever. This runs in a web worker that gets
        # recycled; an LRU here would be more machinery than the problem.
        _consent_cache.clear()
    _consent_cache[key] = (time.monotonic() + _CONSENT_TTL_SECONDS, answer)
    return answer


def handle_note(user_id: str, text: str, *,
                source: str = "chat") -> Optional[dict]:
    """Route one captured note. Returns None when this text is not ours.

    None means "the caller should carry on as if the Life Panel did not
    exist". The chat route depends on that: an untagged message from a
    participating user, or ANY message from a non-participating one, must fall
    through to the existing path completely untouched.

    On a match, returns::

        {
          "route":   "case" | "goal_diff" | "win" | "phrase" | "edit"
                     | "capture",
          "answer":  str,          # the chat bubble
          "link":    "/panel/...", # where the card opens
          "note_id": str | None,
          "card":    {...} | None, # the route's payload (proposals, never
                                   # commitments)
          "phrase":  {...} | None, # the wall phrase attached to this answer
        }
    """
    tag, route, remainder = lp.parse_tag(text)

    # An untagged note is not an instruction. §5: no tag = capture only, no
    # action, surfaced in a weekly untagged review. From CHAT specifically it
    # is not even that — a participating user's ordinary chat message must
    # reach the librarian exactly as before, so we hand it straight back.
    if tag is None and source == "chat":
        return None

    # ── 1. GATE ──────────────────────────────────────────────────────────
    # Consent first, and a non-consented user gets NOTHING FROM US — not even
    # an explanation. Returning None hands the turn back to the existing chat
    # path completely untouched, which is what N3 requires: for a user who has
    # not opted in, this feature does not exist and their chat is byte-
    # identical to main.
    #
    # It also satisfies L-6/BE-10 the strict way: consent is recorded before
    # ANY life row is written, and life_notes is a life row.
    #
    # (§1.4 reads "a `#` note is still stored, not executed" for the
    # not-consented case, which cannot be true at the same time as "consent
    # before any life row is written". Resolved in favour of consent — it is
    # the launch blocker and the legal gate, and §6.2's keep-the-note rule is
    # written about the SETUP gate, not this one. Called out here rather than
    # settled silently: if the founder wants a pre-consent note kept, this is
    # the one branch to change, and N3's test moves with it.)
    if not has_consented(user_id):
        return None

    setup_done = store.setup_completed(user_id)

    # ── 2. STORE — always, before anything can fail ──────────────────────
    # A note typed before setup completes is KEPT and replayed the moment
    # setup finishes (§6.2). Someone who reaches for `#mistake` is holding a
    # thought they wanted recorded; losing it to a redirect teaches them the
    # tag costs something, and then they stop reaching for it.
    pending = not setup_done and route != "capture"
    note = store.insert_note(user_id, text or "", source=source, tag=tag,
                             pending_replay=pending)
    note_id = str(note.get("id")) if note else None

    if pending:
        return {
            "route": route, "answer": COPY["needs_setup"],
            "link": "/panel/principles", "note_id": note_id, "card": None,
            "phrase": None, "blocked": "setup",
        }

    # ── 3. DERIVE ────────────────────────────────────────────────────────
    card: Optional[dict] = None
    answer = COPY["captured"]

    try:
        if route == "case":
            card = engine.derive_case(user_id, remainder)
            answer = _case_answer(card)
        elif route == "goal_diff":
            card = engine.compare_to_strategy(user_id, remainder,
                                              note_id=note_id)
            answer = _diff_answer(card)
        elif route == "win":
            card = store.insert_item(user_id, {
                "kind": "win", "title": remainder[:500], "body": remainder,
                "origin_note_id": note_id,
                "order_key": lp.next_order_key(
                    store.list_items(user_id, kind="win")),
            })
            answer = COPY["win_saved"]
        elif route == "phrase":
            card = store.insert_item(user_id, {
                "kind": "phrase", "title": remainder[:500], "body": remainder,
                "collection": "wall", "origin_note_id": note_id,
                "order_key": lp.next_order_key(
                    store.list_items(user_id, kind="phrase")),
            })
            answer = COPY["phrase_saved"]
        elif route == "edit":
            card = engine.edit_daily_card(user_id, remainder)
            # On refusal the engine says WHY (no card yet, empty text); on
            # success there is nothing to explain, so the confirmation is the
            # answer.
            answer = (card.get("message")
                      or (COPY["card_edited"] if card.get("ok")
                          else COPY["captured"])) if card else COPY["captured"]
    except Exception as e:
        # The note is already stored. A failed derivation costs the card, not
        # the record — which is the entire reason step 2 runs first.
        logger.warning("life: derivation failed user=%s route=%s: %s",
                       user_id, route, e)
        card = None
        answer = COPY["case_no_derivation"] if route == "case" else \
            COPY["captured"]

    # ── 4. ATTACH — the founder's own words, or silence ──────────────────
    # EVERY `#` note's answer carries the best-fitting wall phrase — and only
    # a `#` note. An untagged note is capture only, no action (§5), and an
    # aphorism returned on it would be exactly the action the tag was supposed
    # to be required for.
    #
    # `#add` is excluded too: attaching a phrase to the act of adding a phrase
    # is a mirror pointed at a mirror.
    phrase = None
    if tag is not None and route != "phrase":
        try:
            phrase = engine.attach_phrase(user_id, remainder or text or "")
        except Exception as e:
            logger.warning("life: phrase attach failed user=%s: %s",
                           user_id, e)

    return {
        "route": route,
        "answer": answer,
        "link": _panel_link(route),
        "note_id": note_id,
        "card": card,
        "phrase": (lp.serialize_item(phrase) if phrase else None),
    }


def _case_answer(card: Optional[dict]) -> str:
    """The bubble for a `#mistake`. States what is PROPOSED, never what was
    decided — nothing has been written to the archive at this point."""
    if not card:
        return COPY["case_no_derivation"]
    bits: list[str] = []
    labels = [lp.CATEGORY_LABELS[c] for c in (card.get("category") or [])]
    if labels:
        bits.append("👾 " + " · ".join(labels))
    applied = card.get("principles") or []
    if applied:
        bits.append(
            f"{len(applied)} of your principles bore on this."
        )
    if card.get("new_principle"):
        bits.append("⚜️ " + card["new_principle"])
    if card.get("conflicts"):
        # L-3 — both sides, never a resolution.
        bits.append(COPY["conflict_intro"])
    return "\n".join(bits) if bits else COPY["captured"]


def _diff_answer(card: Optional[dict]) -> str:
    """The bubble for an `#observation`."""
    if not card:
        return COPY["captured"]
    kind = card.get("kind")
    if kind == "report":
        # L-2a — the immutable core is reported against, never proposed
        # against. The report is the whole answer; there is no button.
        return card.get("report") or COPY["captured"]
    if kind == "proposal":
        if card.get("status") == "queued":
            # L-2b — today's one slot is spent. Said out loud: a silently
            # queued proposal looks like a system that ignored you.
            return "Noted — it's queued for the weekly review."
        return "One change to review."
    return COPY["captured"]
