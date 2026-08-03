"""The Life Panel — pure domain layer (founder-directed, 2026-07-26).

Spec of record: PROMPT-life-panel.md · build prompt: PROMPT-BE-life-panel.md

Everything here is a pure function over dicts and strings. No DB, no Flask, no
network, no LLM — which is why this is also where the locked rules are
enforced and where the tests point. The store layer (services/life_store) does
the I/O; the engine layer (services/life_engine) does the LLM calls; both of
them ask *this* module what is allowed.

The locked rules that live here, and the function that is each one:

  L-1  the system never authors reflective prose
       ``validate_case_input`` — ``reflections`` is only ever taken from
       request input, never from a model. There is no writer for it here.
  L-2a immutable core: Section I (The Anchor) and the RANK of the three bets
       are hand-edited only
       ``is_immutable_target`` — a proposal against one is never created.
  L-2b change budget: at most one strategy proposal surfaced per day, the rest
       queue to the weekly review as a ranked batch of three, unactioned
       proposals expire after two weeks
       ``plan_proposal_status`` / ``weekly_batch`` / ``expiry_for``.
  L-3  surface paradoxes, never resolve them
       ``pair_conflicts`` returns BOTH sides; there is no picker.
  L-4  zero nudges — nothing in this module schedules, notifies or tracks
       silence. ``is_dormant_ok`` documents the trade rather than measuring it.
  L-5  every citation of a principle is logged as an application
       ``application_rows_for`` builds those rows for the caller to write.

Routing is by HASHTAG, not by classifier (§5): the user declares the intent, so
the system is never wrong about what they meant. ``parse_tag`` is the whole
router — deterministic, free, and unit-tested against the failure mode the
spec asks for (``#lift me up`` must parse as ``#lift`` + prose, not
``#liftmeup``).
"""
from __future__ import annotations

import math
import re
import unicodedata
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable, Optional

__all__ = [
    "LifeError",
    "CATEGORIES", "CATEGORY_LABELS", "ITEM_KINDS", "HORIZONS",
    "STRATEGY_HORIZONS", "ITEM_TO_STRATEGY_HORIZON", "strategy_horizon_for",
    "BETS", "ADVISORS", "TAG_ROUTES", "PUBLIC_TAGS",
    "parse_tag", "tag_suggestions",
    "map_import_category", "normalize_categories",
    "validate_case_input", "validate_item_input",
    "is_immutable_target", "plan_proposal_status", "weekly_batch",
    "expiry_for", "is_expired",
    "phrase_relevance", "pick_phrase", "PHRASE_RELEVANCE_FLOOR",
    "PHRASE_REPEAT_WINDOW_DAYS",
    "pair_conflicts", "route_advisor", "ADVISOR_PRAYER_LINE",
    "parse_due_label", "next_order_key",
    "serialize_note", "serialize_case", "serialize_item",
    "serialize_proposal", "serialize_day", "serialize_week",
    "serialize_strategy", "application_rows_for",
    "week_start_for", "utc_now_iso",
]


class LifeError(Exception):
    """Validation failure. The message is FE-renderable — routes 400 with it
    verbatim, exactly like services.journal.JournalError."""


# ═════════════════════════════════════════════════════════════════════════
# The mistake taxonomy — FIXED, six entries (§3.1)
# ═════════════════════════════════════════════════════════════════════════
# Derived from the corpus, ordered by corpus frequency. Not free-text, not
# emergent. The model must PICK from this list; the seventh-category question
# is open with the founder (PROMPT-BE §Open), so proposing one is not
# implemented — an unmapped string goes to the review queue instead of
# inventing a category, which is the reversible choice.
CATEGORIES: tuple[str, ...] = (
    "hubris",                    # highest frequency
    "blind_spots",               # high
    "wishful_thinking",          # high
    "too_much_pleasure",         # medium
    "frivolous_decision_making", # low
    "perfectionist",             # low
)

CATEGORY_LABELS: dict[str, str] = {
    "hubris": "Hubris",
    "blind_spots": "Blind spots",
    "wishful_thinking": "Wishful thinking",
    "too_much_pleasure": "Too much pleasure",
    "frivolous_decision_making": "Frivolous decision making",
    "perfectionist": "Perfectionist",
}

# Import aliases → the fixed six. Keyed by a normalized form (lowercased,
# accents folded, non-alphanumerics collapsed to "_") so the same table serves
# the Polish and English spellings that both appear in the corpus.
#
# ANYTHING NOT IN HERE GOES TO A REVIEW QUEUE (BE-3). Silent coercion is the
# failure mode this table exists to prevent: a mis-mapped category is a lie
# about a four-year-old reflection, and it is invisible once written.
_CATEGORY_ALIASES: dict[str, str] = {
    "hubris": "hubris",
    "pycha": "hubris",
    "arrogance": "hubris",
    "ego": "hubris",
    "blind_spots": "blind_spots",
    "blind_spot": "blind_spots",
    "slepa_plamka": "blind_spots",
    "slepe_plamki": "blind_spots",
    "wishful_thinking": "wishful_thinking",
    "wishfull_thinking": "wishful_thinking",   # corpus typo, seen in export
    "myslenie_zyczeniowe": "wishful_thinking",
    "too_much_pleasure": "too_much_pleasure",
    "pleasure": "too_much_pleasure",
    "za_duzo_przyjemnosci": "too_much_pleasure",
    "frivolous_decision_making": "frivolous_decision_making",
    "frivolous": "frivolous_decision_making",
    "frivolous_decisions": "frivolous_decision_making",
    "lekkomyslnosc": "frivolous_decision_making",
    "perfectionist": "perfectionist",
    "perfectionism": "perfectionist",
    "perfekcjonizm": "perfectionist",
}


ITEM_KINDS: tuple[str, ...] = (
    "principle", "win", "phrase", "bet", "goal", "task", "habit",
    "distraction", "event",
)

ITEM_STATUSES: tuple[str, ...] = (
    "proposed", "active", "retired", "dismissed", "done", "archived",
)

# "week" was ADDED (2026-07-31) to close the weekly gap below. It is the only
# item horizon that is not safe to write blind: the other seven have been in
# life_items_horizon_check since the panel shipped, and this one arrives with
# migrations/add_life_items_week_horizon.sql. Everything that WRITES a horizon
# degrades rather than losing the row — see apply-proposed.
HORIZONS: tuple[str, ...] = (
    "now", "week", "month", "quarter", "year", "five_year", "ten_year",
    "twenty_year",
)

# The horizons that predate the week migration, and so are accepted by every
# database this code can meet. Kept as its own tuple rather than derived by
# subtracting "week", so the fallback path states what it is relying on.
HORIZONS_BEFORE_WEEK: tuple[str, ...] = (
    "now", "month", "quarter", "year", "five_year", "ten_year", "twenty_year",
)

STRATEGY_HORIZONS: tuple[str, ...] = (
    "daily", "weekly", "monthly", "quarterly", "yearly", "five_year",
    "ten_year", "twenty_year",
)

# HORIZONS and STRATEGY_HORIZONS are deliberately different vocabularies for
# different tables: an ITEM's horizon (life_items.horizon) is when that goal is
# due; a STRATEGY horizon (life_strategy_versions.horizon) is which of the eight
# documents you are looking at. They coincide only on the long end.
#
# The setup flow folds drafted ITEMS onto STRATEGY screens, so it needs the
# translation. Kept as one table rather than inline so both sides of the seam
# read the same mapping.
#
# The mapping is now TOTAL in both directions: every item horizon folds onto a
# strategy screen, and every strategy screen has an item horizon that reaches
# it. "weekly" used to be the exception — nothing in HORIZONS meant "this
# week", so that screen could never pre-fill from a document and its rows
# always fell to the remainder review. "week" closes it.
#
# "now" still means "now" and still folds onto "daily". It was NOT widened to
# cover the week: re-pointing it would move every existing [NOW] goal off the
# daily screen it has been rendering on, which is a change to what people
# already wrote, made on their behalf, to fix a screen they never complained
# about.
ITEM_TO_STRATEGY_HORIZON: dict[str, str] = {
    "now": "daily",
    "week": "weekly",
    "month": "monthly",
    "quarter": "quarterly",
    "year": "yearly",
    "five_year": "five_year",
    "ten_year": "ten_year",
    "twenty_year": "twenty_year",
}


def strategy_horizon_for(item_horizon: Any) -> Optional[str]:
    """The strategy screen an item with this horizon folds onto, or None.

    None (unknown or absent horizon) is a valid answer, not a failure: the
    setup flow routes those rows to its remainder review rather than dropping
    them, so an unmapped horizon degrades to "shown, not auto-filled".
    """
    if not isinstance(item_horizon, str):
        return None
    return ITEM_TO_STRATEGY_HORIZON.get(item_horizon.strip().lower())

NOTE_SOURCES: tuple[str, ...] = ("chat", "form", "import")

APPLICATION_CONTEXTS: tuple[str, ...] = (
    "case", "diff", "conflict", "board", "lookup", "phrase",
)


# ═════════════════════════════════════════════════════════════════════════
# The three bets — RANKED, not equal (§3.2)
# ═════════════════════════════════════════════════════════════════════════
# The rank is load-bearing: when the router proposes a task it must be able to
# say which bet it serves, and Bet 3 never outranks Bet 2 in a daily plan.
# That is the founder's own stated rule ("It does not drive daily execution —
# Bet 2 does"), encoded.
#
# The rank is ALSO immutable core (L-2a) — see is_immutable_target.
BETS: tuple[dict[str, Any], ...] = (
    {"rank": 1, "key": "life", "emoji": "🟢", "title": "The Life",
     "body": "family · faith · community"},
    {"rank": 2, "key": "company", "emoji": "🔵", "title": "The Company",
     "body": "willab — the active bet"},
    {"rank": 3, "key": "dream", "emoji": "🟣", "title": "The Dream",
     "body": "research · 7T · horizon 2035"},
)

# ANSWERED by the founder 2026-07-26: Bet 3 is eligible for the daily card
# from day one. (Was False while the question was open — the weekly document's
# "it does not drive daily execution" read as an exclusion.)
#
# Why this does not contradict the weekly document: the rule that matters is
# the one below it — "Bet 3 never outranks Bet 2 in a daily plan" — and that is
# enforced by the SORT, not by exclusion. Goals are ordered by bet rank first,
# so a 🟣 item can only reach the ONE THING slot when Bets 1 and 2 have nothing
# left to offer, which is precisely the day you want the dream on the card
# rather than an empty card. On every other day it fills the tail, never the
# head. Excluding it entirely was a stronger claim than the document makes.
BET_3_DRIVES_DAILY_EXECUTION = True


# ═════════════════════════════════════════════════════════════════════════
# The hashtag router (§5) — deterministic, no classifier
# ═════════════════════════════════════════════════════════════════════════
# You declare the intent; the system does not guess. Free, and never wrong
# about what you meant.
TAG_ROUTES: dict[str, str] = {
    # case → new principle
    "principle": "case",
    "sin": "case",
    "mistake": "case",
    "error": "case",
    "problem": "case",
    # compared against the strategy doc; inconsistencies flagged (BE-6)
    "data": "goal_diff",
    "observation": "goal_diff",
    "reflection": "goal_diff",
    "idea": "goal_diff",
    "finding": "goal_diff",
    # wins
    "win": "win",
    "wins": "win",
    "wygrane": "win",
    "liftmeup": "win",
    # the phrase wall — the ONLY way in
    "add": "phrase",
    # the daily card
    "edit": "edit",
}

# The `#` autocomplete list. Four aliases per route are easy to build and
# impossible to memorise; the picker is what keeps the guide page from having
# to be load-bearing.
#
# `#sin` stays a WORKING alias but is deliberately off the public list (§5).
_HIDDEN_TAGS: frozenset[str] = frozenset({"sin"})

PUBLIC_TAGS: tuple[str, ...] = tuple(
    t for t in TAG_ROUTES if t not in _HIDDEN_TAGS
)

_TAG_HINTS: dict[str, str] = {
    "case": "a mistake → a new principle",
    "goal_diff": "checked against your strategy",
    "win": "a win, for the wall",
    "phrase": "add to the smart-phrase wall",
    "edit": "edit today's card",
}

# A tag is the FIRST token, matched case-insensitively, terminated by
# whitespace. That is the whole grammar. `#lift me up` therefore parses as
# `#lift` (unknown) + prose → capture only, which is the DESIRED failure mode:
# hashtags break at whitespace, so `#liftmeup` is one word on purpose.
_TAG_RE = re.compile(r"^\s*#([^\s#]+)")


def parse_tag(text: Optional[str]) -> tuple[Optional[str], str, str]:
    """``(tag, route, remainder)`` for one captured note.

    ``tag`` is the normalized tag WITHOUT the ``#`` (None when the text does
    not start with one, or when the tag is unknown). ``route`` is one of
    ``case`` / ``goal_diff`` / ``win`` / ``phrase`` / ``edit`` / ``capture``.
    ``remainder`` is the prose after the tag — the note body the engine works
    on.

    An unknown tag returns ``(None, "capture", <the original text>)``: the
    text is kept whole, because the user meant to write ``#lift me up`` and
    losing the ``#lift`` would silently edit their note.
    """
    raw = (text or "")
    m = _TAG_RE.match(raw)
    if not m:
        return None, "capture", raw.strip()
    tag = m.group(1).strip().lower()
    # Strip trailing punctuation a normal typist adds ("#mistake:").
    tag = tag.rstrip(".,:;!?—-")
    route = TAG_ROUTES.get(tag)
    if not route:
        return None, "capture", raw.strip()
    return tag, route, raw[m.end():].strip()


def tag_suggestions() -> list[dict[str, str]]:
    """The `#` autocomplete payload. Typing `#` alone opens this list."""
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for tag in PUBLIC_TAGS:
        route = TAG_ROUTES[tag]
        key = (route, tag)
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "tag": f"#{tag}",
            "route": route,
            "hint": _TAG_HINTS.get(route, ""),
        })
    return out


# ═════════════════════════════════════════════════════════════════════════
# Normalization helpers
# ═════════════════════════════════════════════════════════════════════════

def _fold(text: str) -> str:
    """Lowercase + accents folded + non-alphanumerics collapsed to ``_``.

    Used ONLY for MATCHING (category aliases, proposal targets). It is never
    used on stored prose: the corpus is code-switched Polish/English and the
    text is the record — no translation, no normalisation, no cleanup pass."""
    if not isinstance(text, str):
        return ""
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    # Polish ł has no combining form — NFKD leaves it intact.
    stripped = stripped.replace("ł", "l").replace("Ł", "L")
    return re.sub(r"[^a-z0-9]+", "_", stripped.lower()).strip("_")


def map_import_category(raw: Optional[str]) -> Optional[str]:
    """One corpus category string → one of the fixed six, or None.

    None means "unmapped" and the caller MUST park it in the review queue.
    Never guesses: a category the table does not know is a category a human
    has to look at."""
    key = _fold(raw or "")
    if not key:
        return None
    return _CATEGORY_ALIASES.get(key)


def normalize_categories(values: Any) -> list[str]:
    """A proposed/approved category list → the valid, de-duplicated subset.

    Order-preserving. Anything outside the fixed six is dropped, not coerced:
    the model picks FROM the list or it picks nothing."""
    if isinstance(values, str):
        values = [values]
    if not isinstance(values, (list, tuple)):
        return []
    out: list[str] = []
    for v in values:
        if not isinstance(v, str):
            continue
        key = v.strip().lower()
        if key not in CATEGORIES:
            key = map_import_category(v) or ""
        if key in CATEGORIES and key not in out:
            out.append(key)
    return out


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def week_start_for(d: date) -> date:
    """The Monday of ``d``'s week. The review runs on Sunday; the week it
    reviews starts Monday, so the key is stable whichever day you open it."""
    return d - timedelta(days=d.weekday())


# ═════════════════════════════════════════════════════════════════════════
# Case + item validation (N5 lives here)
# ═════════════════════════════════════════════════════════════════════════

_MAX_BODY = 20000
_MAX_TITLE = 500


def _text(body: dict, key: str, *, max_len: int, required: bool = False) -> str:
    raw = body.get(key)
    if raw is None:
        if required:
            raise LifeError(f"{key}: required")
        return ""
    if not isinstance(raw, str):
        raise LifeError(f"{key}: must be a string")
    value = raw.strip()
    if required and not value:
        raise LifeError(f"{key}: required")
    if len(value) > max_len:
        raise LifeError(f"{key}: at most {max_len} characters")
    return value


def validate_case_input(body: dict, *, partial: bool = False) -> dict:
    """The case write contract — the five slots.

    L-1 / N5 IS THIS FUNCTION. ``reflections`` is read from the request and
    from nowhere else: reflections are written by the founder and polished
    through the Ideal Text tool EXTERNALLY, then pasted in. There is no code
    path in this repo that generates that field, and no call into the F1
    ideal-text pipeline. The system may propose the 👾 category and the ⚜️
    one-liner, and may retrieve which existing principles bore on the case —
    it never authors the reflective prose.

    ``category`` here is the APPROVED list (user-supplied). The model's
    suggestion is a separate column and never lands in this dict.
    """
    if not isinstance(body, dict):
        raise LifeError("body: must be an object")
    out: dict[str, Any] = {}

    if "case_at_hand" in body or not partial:
        out["case_at_hand"] = _text(
            body, "case_at_hand", max_len=_MAX_BODY, required=not partial)
    for key in ("principles_applied", "reflections"):
        if key in body or not partial:
            out[key] = _text(body, key, max_len=_MAX_BODY)

    if "category" in body:
        out["category"] = normalize_categories(body.get("category"))

    if "occurred_on" in body:
        raw = body.get("occurred_on")
        if raw in (None, ""):
            out["occurred_on"] = None
        elif isinstance(raw, str):
            try:
                out["occurred_on"] = date.fromisoformat(raw[:10]).isoformat()
            except ValueError:
                raise LifeError("occurred_on: must be YYYY-MM-DD")
        else:
            raise LifeError("occurred_on: must be YYYY-MM-DD or null")

    if not out:
        raise LifeError("no fields to update")
    return out


def validate_item_input(body: dict, *, partial: bool = False) -> dict:
    """The life_items write contract, shared by every kind."""
    if not isinstance(body, dict):
        raise LifeError("body: must be an object")
    out: dict[str, Any] = {}

    if not partial:
        kind = body.get("kind")
        if not isinstance(kind, str) or kind.strip() not in ITEM_KINDS:
            raise LifeError(
                f"kind: must be one of {', '.join(ITEM_KINDS)}")
        out["kind"] = kind.strip()
    elif "kind" in body:
        # The kind is the discriminator — changing it after the fact would
        # silently move a row between views (and past a different validator).
        raise LifeError("kind: cannot be changed after creation")

    if "title" in body or not partial:
        out["title"] = _text(body, "title", max_len=_MAX_TITLE)
    if "body" in body or not partial:
        out["body"] = _text(body, "body", max_len=_MAX_BODY)

    if "measure" in body:
        # "How you will know it happened" — the goal's own metric, in the
        # person's words (piece 3, 2026-08-02). Free text by design: the
        # evening holds the day against this SENTENCE, it never computes
        # against it (AC-9).
        out["measure"] = _text(body, "measure", max_len=500) or None

    if "status" in body:
        status = body.get("status")
        if not isinstance(status, str) or status not in ITEM_STATUSES:
            raise LifeError(
                f"status: must be one of {', '.join(ITEM_STATUSES)}")
        out["status"] = status

    if "horizon" in body:
        horizon = body.get("horizon")
        if horizon in (None, ""):
            out["horizon"] = None
        elif isinstance(horizon, str) and horizon in HORIZONS:
            out["horizon"] = horizon
        else:
            raise LifeError(f"horizon: must be one of {', '.join(HORIZONS)}")

    if "collection" in body:
        out["collection"] = _text(body, "collection", max_len=120) or None

    if "due_label" in body:
        label = _text(body, "due_label", max_len=120) or None
        out["due_label"] = label
        # The LABEL is the source of truth; due_at is the parse where it is
        # unambiguous, and null otherwise. Never the other way round.
        out["due_at"] = parse_due_label(label)

    for key in ("bet_id", "parent_id", "origin_note_id", "origin_case_id"):
        if key in body:
            raw = body.get(key)
            if raw in (None, ""):
                out[key] = None
            elif isinstance(raw, str):
                out[key] = raw.strip()
            else:
                raise LifeError(f"{key}: must be an id string or null")

    if "order_key" in body:
        try:
            out["order_key"] = float(body.get("order_key"))
        except (TypeError, ValueError):
            raise LifeError("order_key: must be a number")

    if not out:
        raise LifeError("no fields to update")
    return out


def next_order_key(existing: Iterable[dict]) -> float:
    """Append at the end of a manually ordered list, leaving room to drag."""
    keys = [
        float(r.get("order_key") or 0.0)
        for r in (existing or []) if isinstance(r, dict)
    ]
    return (max(keys) + 1000.0) if keys else 1000.0


# ═════════════════════════════════════════════════════════════════════════
# L-2a — the immutable core
# ═════════════════════════════════════════════════════════════════════════
# Section I (The Anchor) and the RANK of the three bets are hand-edited only.
# Never proposed, never redrafted.
#
# Why this is not optional: L-2 lets the system draft the strategy documents.
# Without an immutable core, the standard the system judges alignment against
# is a standard the system wrote — and the 20-year vision can drift through
# eight months of individually reasonable approvals. Each approval looks fine;
# the destination moves.
#
# Matching is SEGMENT-based on the folded target, and deliberately broad: an
# over-refusal costs a report-only answer (which is still useful and still
# tells the founder about the inconsistency), while an under-refusal is a
# silent edit to the thing that must not move. Asymmetric costs, asymmetric
# matcher.
_IMMUTABLE_SEGMENTS: frozenset[str] = frozenset({"anchor", "rank", "ranks",
                                                 "ranking"})
_IMMUTABLE_PAIRS: tuple[tuple[str, str], ...] = (
    ("section", "i"),
    ("section", "1"),
)


def is_immutable_target(target: Optional[str]) -> bool:
    """True when a proposal against ``target`` must never be created.

    The caller's contract on True: report the inconsistency and STOP. Do not
    write a life_proposals row, do not surface an approve button."""
    folded = _fold(target or "")
    if not folded:
        # An unaddressed proposal cannot be reviewed, so it cannot be created
        # either. Refusing the blank target keeps "every change is gated"
        # true by construction.
        return True
    segments = folded.split("_")
    if _IMMUTABLE_SEGMENTS & set(segments):
        return True
    for a, b in _IMMUTABLE_PAIRS:
        for i in range(len(segments) - 1):
            if segments[i] == a and segments[i + 1] == b:
                return True
    return False


# ═════════════════════════════════════════════════════════════════════════
# L-2b — the change budget
# ═════════════════════════════════════════════════════════════════════════
# At most ONE strategy-change proposal surfaced per day; the rest queue to the
# weekly review and arrive as a ranked batch of three. Unactioned proposals
# expire after two weeks rather than accumulating.
#
# Scarcity is what keeps "approve" meaningful. A daily stream of diffs becomes
# a rubber stamp within three weeks, and the rubber stamp IS the drift this
# whole gate exists to prevent.
DAILY_PROPOSAL_BUDGET = 1
WEEKLY_BATCH_SIZE = 3
PROPOSAL_EXPIRY_DAYS = 14


def plan_proposal_status(*, already_surfaced_today: int) -> str:
    """``"surfaced"`` or ``"queued"`` for a proposal being created now.

    The caller passes the COUNT FROM THE DATABASE (a query over
    ``surfaced_on = today``), never a number it kept in memory: a process-local
    counter drifts across workers and resets on every restart, and the budget
    would quietly become "one per worker per day"."""
    try:
        n = int(already_surfaced_today)
    except (TypeError, ValueError):
        n = 0
    return "queued" if n >= DAILY_PROPOSAL_BUDGET else "surfaced"


def expiry_for(created: Optional[datetime] = None) -> str:
    """When an unactioned proposal expires — two weeks out, ISO-8601."""
    base = created or datetime.now(timezone.utc)
    return (base + timedelta(days=PROPOSAL_EXPIRY_DAYS)).isoformat()


def is_expired(row: dict, *, now: Optional[datetime] = None) -> bool:
    """True when a queued proposal has aged out. Only `queued` rows expire —
    a proposal already surfaced is in front of the founder, and one already
    decided is history."""
    if (row or {}).get("status") != "queued":
        return False
    raw = (row or {}).get("expires_at")
    if not raw:
        return False
    try:
        when = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return False
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when <= (now or datetime.now(timezone.utc))


def weekly_batch(queued: Iterable[dict]) -> list[dict]:
    """The weekly review's ranked batch of three, highest rank first.

    Everything past the third stays queued for the following week (or expires
    first). Truncation is not silent — the route reports how many were held
    back, because "here are your three" reads as "that was everything" if the
    remainder is invisible."""
    rows = [r for r in (queued or []) if isinstance(r, dict)]
    rows.sort(
        key=lambda r: (-float(r.get("rank") or 0.0), str(r.get("created_at") or "")),
    )
    return rows[:WEEKLY_BATCH_SIZE]


# ═════════════════════════════════════════════════════════════════════════
# The phrase wall — a retrieval base, not a destination (§5)
# ═════════════════════════════════════════════════════════════════════════
# Every `#` note's answer carries the single best-fitting phrase from the wall
# — the founder's own words returned at the moment they apply. `#add` is the
# only way in.
#
# Two rules, both load-bearing:
#   * a RELEVANCE FLOOR — if nothing clears the bar, attach NOTHING. A
#     mismatched aphorism on a `#sin` note about addiction is worse than
#     silence, and the failure is not neutral: it teaches the founder the wall
#     is noise.
#   * NO REPEAT inside a rolling window, or the wall collapses to three
#     favourites and stops being a wall.
#
# Scoring is deterministic set-cosine over content tokens — free, instant, and
# explainable. An LLM here would spend a call per note to be less predictable.
PHRASE_RELEVANCE_FLOOR = 0.15
PHRASE_MIN_SHARED_TOKENS = 2
PHRASE_REPEAT_WINDOW_DAYS = 30

# Code-switched on purpose: several reflections switch Polish/English
# mid-paragraph and that is the record, so the stoplist has to cover both or
# the overlap score is dominated by function words in whichever language the
# note happens to be in.
_STOPWORDS: frozenset[str] = frozenset("""
the and that this with from have been what when your you are was for not but
all can will would they them there then than into more most some such only
over just very about after before because could should did does had his her
its our their who whom while where how why any each other than
nie sie jest tego tym jak tak ale czy dla jego jej oraz przez przy tylko tez
zeby aby bym bys ktory ktora ktore wszystko bardzo mnie mam byc mi ci to co
sobie jestem bylem bylam jesli zawsze nigdy kiedy gdzie moze musi nawet juz
tam tutaj ten ten ta te oni one nas wam wami nam
""".split())


def _content_tokens(text: str) -> set[str]:
    """Folded tokens with the stoplist and 1–2 character noise removed.

    Folding here is for MATCHING only — the stored text is never touched."""
    folded = _fold(text or "")
    return {
        t for t in folded.split("_")
        if len(t) >= 3 and t not in _STOPWORDS and not t.isdigit()
    }


def phrase_relevance(note_text: str, phrase_text: str) -> float:
    """0.0–1.0 set-cosine over content tokens.

    Returns 0.0 on a single shared token: one word in common between a note
    and an aphorism is coincidence, and coincidence is exactly what the floor
    exists to keep off the answer."""
    a = _content_tokens(note_text)
    b = _content_tokens(phrase_text)
    if not a or not b:
        return 0.0
    shared = a & b
    if len(shared) < PHRASE_MIN_SHARED_TOKENS:
        return 0.0
    return len(shared) / math.sqrt(len(a) * len(b))


def pick_phrase(
    note_text: str,
    phrases: Iterable[dict],
    *,
    recently_used_ids: Optional[Iterable[str]] = None,
) -> Optional[dict]:
    """The single best-fitting wall phrase, or None.

    None is a first-class answer, not a failure: below the floor, or when every
    candidate that clears it was already used inside the rolling window, the
    right move is to attach nothing.

    The returned dict is the phrase ROW — the caller serializes it. The score
    is deliberately NOT part of the return shape: nothing in a life payload is
    a number the user reads.
    """
    blocked = {str(i) for i in (recently_used_ids or []) if i}
    best: Optional[dict] = None
    best_score = 0.0
    for row in (phrases or []):
        if not isinstance(row, dict):
            continue
        if str(row.get("id") or "") in blocked:
            continue
        text = (row.get("body") or row.get("title") or "")
        score = phrase_relevance(note_text, text)
        if score < PHRASE_RELEVANCE_FLOOR:
            continue
        # Ties break on the older phrase: the wall should reach back, not
        # orbit whatever was added last.
        if score > best_score or (
            score == best_score and best is not None
            and str(row.get("created_at") or "") < str(best.get("created_at") or "")
        ):
            best, best_score = row, score
    return best


# ═════════════════════════════════════════════════════════════════════════
# L-3 — surface paradoxes, never resolve them
# ═════════════════════════════════════════════════════════════════════════
# When two principles pull opposite ways, BOTH are shown and the founder
# weighs them. There is no picker in this module and there must never be one:
# the resolution is the founder's, and a system that resolves it is a system
# that has quietly replaced the archive's owner.
#
# Detection is cheap and precise — precomputed opposition markers over the
# RETRIEVED set only. The engine layer may add an LLM check on top; it may not
# add a decision.
_OPPOSITION_MARKERS: tuple[tuple[frozenset[str], frozenset[str]], ...] = (
    (frozenset({"alone", "own", "sam", "samemu", "self", "siebie"}),
     frozenset({"others", "feedback", "trusted", "ludzie", "innych", "rada"})),
    (frozenset({"fast", "quick", "speed", "szybko", "now", "teraz"}),
     frozenset({"slow", "patience", "wait", "wolno", "cierpliwosc"})),
    (frozenset({"validation", "approval", "praise", "uznanie"}),
     frozenset({"feedback", "critique", "honest", "szczery"})),
    (frozenset({"risk", "bet", "ryzyko"}),
     frozenset({"safety", "protect", "preserve", "bezpieczenstwo"})),
)


def pair_conflicts(principles: Iterable[dict]) -> list[tuple[dict, dict]]:
    """Opposing pairs inside one retrieved set. BOTH sides, every time.

    Returns pairs, not a winner. A caller looking for "which one applies"
    will not find it here — that is L-3, and it is the point."""
    rows = [p for p in (principles or []) if isinstance(p, dict)]
    pairs: list[tuple[dict, dict]] = []
    seen: set[tuple[str, str]] = set()
    for i, left in enumerate(rows):
        lt = _content_tokens(
            f"{left.get('title') or ''} {left.get('body') or ''}")
        for right in rows[i + 1:]:
            rt = _content_tokens(
                f"{right.get('title') or ''} {right.get('body') or ''}")
            for side_a, side_b in _OPPOSITION_MARKERS:
                if ((lt & side_a and rt & side_b)
                        or (lt & side_b and rt & side_a)):
                    key = (str(left.get("id")), str(right.get("id")))
                    if key not in seen:
                        seen.add(key)
                        pairs.append((left, right))
                    break
    return pairs


# ═════════════════════════════════════════════════════════════════════════
# The board (§5 / BE-7) — five advisors, routed by domain
# ═════════════════════════════════════════════════════════════════════════
ADVISORS: tuple[dict[str, Any], ...] = (
    {"key": "dalio", "name": "Ray Dalio",
     "lens": "principles, systems, radical transparency, decision machines",
     "markets": ("decision", "principle", "system", "process", "mistake",
                 "invest", "risk", "diversify", "economy", "cycle")},
    {"key": "munger", "name": "Charlie Munger",
     "lens": "mental models, inversion, incentives, the cost of being clever",
     "markets": ("money", "business", "incentive", "invert", "value",
                 "capital", "partner", "deal", "price", "margin")},
    {"key": "jobs", "name": "Steve Jobs",
     "lens": "product, focus, saying no, taste",
     "markets": ("product", "design", "focus", "simple", "customer", "user",
                 "launch", "brand", "feature", "craft")},
    {"key": "jp2", "name": "John Paul II",
     "lens": "vocation, suffering with meaning, the dignity of the person",
     "markets": ("faith", "god", "prayer", "family", "marriage", "suffering",
                 "wife", "child", "vocation", "sin", "forgive", "wiara",
                 "modlitwa", "rodzina")},
    {"key": "zanussi", "name": "Krzysztof Zanussi",
     "lens": "meaning, the examined life, art as a moral instrument",
     "markets": ("meaning", "art", "film", "story", "purpose", "death",
                 "truth", "beauty", "sens", "sztuka", "prawda")},
)

# The founder's own line, held: the board advises, it does not replace prayer.
ADVISOR_PRAYER_LINE = "The board advises. It does not replace prayer."

_DEFAULT_ADVISOR = "dalio"


def route_advisor(question: str) -> tuple[str, str]:
    """``(advisor_key, why)`` — deterministic domain routing.

    The answer says WHICH advisor was picked and WHY, so a bad routing is
    visible and correctable rather than felt as a vague wrongness."""
    tokens = _content_tokens(question or "")
    best_key, best_hits = _DEFAULT_ADVISOR, 0
    best_words: list[str] = []
    for advisor in ADVISORS:
        hits = [m for m in advisor["markets"] if m in tokens]
        if len(hits) > best_hits:
            best_key, best_hits, best_words = advisor["key"], len(hits), hits
    if not best_hits:
        return _DEFAULT_ADVISOR, (
            "no clear domain in the question — defaulting to the principles "
            "lens"
        )
    name = next(a["name"] for a in ADVISORS if a["key"] == best_key)
    return best_key, (
        f"{name} — the question is about {', '.join(sorted(best_words)[:3])}"
    )


# ═════════════════════════════════════════════════════════════════════════
# Due labels (§3.2) — the label is the source of truth
# ═════════════════════════════════════════════════════════════════════════
_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
_YEAR_RE = re.compile(r"^(19|20)\d{2}$")


def parse_due_label(label: Optional[str], *,
                    today: Optional[date] = None) -> Optional[str]:
    """``"[Jul '27]"`` → ``"2027-07-01"``; ambiguity → None.

    Parsed where unambiguous, NULL otherwise — the label is what renders, and
    a wrong parse is worse than no parse because a timeline marker in the
    wrong year reads as a fact."""
    if not isinstance(label, str):
        return None
    text = label.strip().strip("[]").strip()
    if not text:
        return None
    ref = today or date.today()
    low = text.lower()

    if low in ("now", "today"):
        # "[NOW]" is a horizon, not a date. Giving it today's date would put a
        # standing intention on the timeline as a one-day marker.
        return None

    if _YEAR_RE.match(text):
        return date(int(text), 1, 1).isoformat()

    # "Jul '27" / "Jul 27" / "Jul 2027" / "Aug"
    m = re.match(r"^([a-z]{3,9})\.?\s*'?(\d{2,4})?$", low)
    if m:
        month = _MONTHS.get(m.group(1)[:3])
        if not month:
            return None
        raw_year = m.group(2)
        if raw_year:
            year = int(raw_year)
            if year < 100:
                year += 2000
        else:
            # A bare month means the NEXT occurrence — a "[Aug]" goal written
            # in September is next August, not eleven months in the past.
            year = ref.year if month >= ref.month else ref.year + 1
        try:
            return date(year, month, 1).isoformat()
        except ValueError:
            return None

    try:
        return date.fromisoformat(text[:10]).isoformat()
    except ValueError:
        return None


# ═════════════════════════════════════════════════════════════════════════
# L-5 — the application log
# ═════════════════════════════════════════════════════════════════════════

def application_rows_for(
    user_id: str,
    principle_ids: Iterable[str],
    *,
    context: str,
    ref_id: Optional[str] = None,
) -> list[dict]:
    """Rows to append when principles are cited. Append-only by construction —
    there is no update helper, here or in the store.

    Over months this is what separates load-bearing principles from decorative
    ones: a principle cited eleven times in cases and conflicts is doing work;
    one cited never is a sentence you liked in 2023."""
    if context not in APPLICATION_CONTEXTS:
        raise LifeError(
            f"context: must be one of {', '.join(APPLICATION_CONTEXTS)}")
    rows: list[dict] = []
    seen: set[str] = set()
    for pid in (principle_ids or []):
        key = str(pid or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        row = {"user_id": user_id, "principle_id": key, "context": context}
        if ref_id:
            row["ref_id"] = str(ref_id)
        rows.append(row)
    return rows


# ═════════════════════════════════════════════════════════════════════════
# L-4 — zero nudges, stated once
# ═════════════════════════════════════════════════════════════════════════

def is_dormant_ok() -> bool:
    """Always True, and that is the whole feature.

    No pings, no notifications, no activity tracking, no silence detection, no
    character checks. Not typing means LIVING, not failing. The system is
    dormant until opened.

    The cost, stated once: the system now catches only the drift you bring to
    it. Losing focus and not opening the app is invisible to it BY DESIGN.
    That is the accepted trade — this function exists so a future reader finds
    the trade written down instead of discovering the gap and "fixing" it with
    a reminder email."""
    return True


# ═════════════════════════════════════════════════════════════════════════
# Serialization — the FE contract
# ═════════════════════════════════════════════════════════════════════════
# Nothing here emits a score, a verdict, a ratio, or a confidence. That is
# free in this feature (the read is qualitative anyway) and it keeps the
# payload honest with the house fence.

def _iso(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def serialize_note(row: dict) -> dict:
    return {
        "id": row.get("id"),
        "body": row.get("body") or "",
        "source": row.get("source") or "chat",
        "tag": row.get("tag"),
        "pending_replay": bool(row.get("pending_replay")),
        "created_at": _iso(row.get("created_at")),
    }


def serialize_case(row: dict, *, principles: Optional[list] = None,
                   applications: Optional[list] = None) -> dict:
    """The five slots + the derived principles hanging off this case.

    ``category`` is rendered as multiple 👾 lines by the FE — it is an array
    because the corpus has multi-category cases."""
    categories = normalize_categories(row.get("category"))
    proposed = normalize_categories(row.get("category_proposed"))
    out = {
        "id": row.get("id"),
        "case_at_hand": row.get("case_at_hand") or "",
        "category": categories,
        "category_labels": [CATEGORY_LABELS[c] for c in categories],
        "category_proposed": proposed,
        "category_proposed_labels": [CATEGORY_LABELS[c] for c in proposed],
        "principles_applied": row.get("principles_applied") or "",
        "reflections": row.get("reflections") or "",
        "occurred_on": _iso(row.get("occurred_on")),
        "status": row.get("status") or "draft",
        "needs_review": bool(row.get("import_category_raw")),
        "import_category_raw": row.get("import_category_raw"),
        "created_at": _iso(row.get("created_at")),
    }
    if principles is not None:
        out["principles"] = [serialize_item(p) for p in principles]
    if applications is not None:
        out["applications"] = [
            {"context": a.get("context"), "at": _iso(a.get("created_at"))}
            for a in applications
        ]
    return out


def serialize_item(row: dict) -> dict:
    return {
        "id": row.get("id"),
        "kind": row.get("kind"),
        "title": row.get("title") or "",
        "body": row.get("body") or "",
        "status": row.get("status") or "active",
        "order_key": float(row.get("order_key") or 0.0),
        "horizon": row.get("horizon"),
        "due_label": row.get("due_label"),
        "due_at": _iso(row.get("due_at")),
        # The goal's own success criterion, verbatim. Null for every row
        # written before the column existed — hence the plain .get.
        "measure": row.get("measure"),
        "bet_id": row.get("bet_id"),
        "parent_id": row.get("parent_id"),
        "collection": row.get("collection"),
        "origin_case_id": row.get("origin_case_id"),
        # Both provenance columns ride the serializer, and both are usually
        # null: a row typed into setup was derived from nothing. What they
        # answer together is "where did this come from" — a case the engine
        # worked from (origin_case_id) or a document the person uploaded and
        # ticked (origin_document_id). Absent on a row written before the
        # column existed, hence the plain .get.
        "origin_document_id": row.get("origin_document_id"),
        "created_at": _iso(row.get("created_at")),
    }


def serialize_proposal(row: dict, *, warrant: Optional[dict] = None) -> dict:
    """A proposed change + the founder's own principle that warrants it.

    ``warrant`` is not decoration. L-2 requires every proposed change to
    display one of the user's own principles as its justification — a change
    the archive cannot justify is a change the system invented."""
    out = {
        "id": row.get("id"),
        "kind": row.get("kind") or "strategy",
        "target": row.get("target") or "",
        "current": row.get("current") or "",
        "proposed": row.get("proposed") or "",
        # ALWAYS present, and always False here. A row in life_proposals is by
        # construction not against the immutable core — that is refused at
        # creation AND again on the write path (L-2a), so anything that
        # reached this table carries an approve button.
        #
        # It is emitted explicitly because the FE fail-safes on its ABSENCE:
        # a payload with no `report_only` is treated as report-only and grows
        # no approve button. That default is correct and must not change — it
        # is what stops an unrecognised payload sprouting a button over
        # Section I. But it means silence reads as "report", so a serializer
        # that simply omits the field would render every proposal
        # un-approvable and quietly kill the L-2 approve flow. Saying it out
        # loud is what keeps the FE's guard a guard rather than the mechanism.
        "report_only": False,
        "status": row.get("status") or "queued",
        "surfaced_on": _iso(row.get("surfaced_on")),
        "expires_at": _iso(row.get("expires_at")),
        "created_at": _iso(row.get("created_at")),
    }
    if warrant:
        out["warrant"] = {
            "id": warrant.get("id"),
            "title": warrant.get("title") or "",
            "body": warrant.get("body") or "",
        }
    return out


def serialize_day(row: dict) -> dict:
    return {
        "id": row.get("id"),
        "day": _iso(row.get("day")),
        "morning_checks": row.get("morning_checks") or {},
        "one_thing": row.get("one_thing") or "",
        # Which bet the ONE THING serves (§3.2). All three bets reach the card;
        # the rank rule is held by the ordering, and this is what makes that
        # ordering legible on the surface it governs.
        "one_thing_bet": row.get("one_thing_bet") or "",
        # Which GOAL the drafted action is toward — the goal's name and id
        # only. The rest of draft_meta (drafted, accepted, displacement) is
        # learner and gate data and NEVER reaches the wire
        # (docs/life-checkin-learning-contract.md).
        "one_thing_goal": ((row.get("draft_meta") or {}).get("one_thing")
                           or {}).get("goal") or "",
        "one_thing_goal_id": ((row.get("draft_meta") or {}).get("one_thing")
                              or {}).get("goal_id"),
        # The one thing's own measure, so the evening can hold the day
        # against it — the founder's sentence, never a computed number.
        "one_thing_measure": ((row.get("draft_meta") or {}).get("one_thing")
                              or {}).get("measure") or "",
        # Where the day landed, in their words (PATCH evening_measure).
        "evening_measure": row.get("evening_measure"),
        "focus_blocks": row.get("focus_blocks") or [],
        "distraction_flagged": row.get("distraction_flagged"),
        "evening_habits_ran": bool(row.get("evening_habits_ran")),
        "evening_one_thing": bool(row.get("evening_one_thing")),
        "evening_distraction": row.get("evening_distraction"),
        "evening_line": row.get("evening_line"),
        "edit_why": row.get("edit_why"),
        "generated_at": _iso(row.get("generated_at")),
        # The evening pass, nested so the FE branches on ONE field. Null
        # generated_at ⇒ the pass has not run and the evening section stays
        # closed. Never branch on the summary being non-empty: a recap can be
        # legitimately sparse on a quiet day, and that is not the same as
        # "it is not evening yet".
        "evening": {
            "generated_at": _iso(row.get("evening_generated_at")),
            "summary": row.get("evening_summary") or {},
        },
    }


def serialize_week(row: dict) -> dict:
    return {
        "id": row.get("id"),
        "week_start": _iso(row.get("week_start")),
        "habits_failed": row.get("habits_failed") or [],
        "goals_moved": row.get("goals_moved") or [],
        "main_distraction": row.get("main_distraction"),
        "environmental_change": row.get("environmental_change"),
        "becoming_sentence": row.get("becoming_sentence"),
        "reviewed_on": _iso(row.get("reviewed_on")),
    }


def serialize_strategy(row: dict) -> dict:
    return {
        "id": row.get("id"),
        "horizon": row.get("horizon") or "weekly",
        "body": row.get("body") or "",
        "version": int(row.get("version") or 1),
        "reviewed_on": _iso(row.get("reviewed_on")),
        "created_at": _iso(row.get("created_at")),
    }
