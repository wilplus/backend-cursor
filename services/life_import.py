"""The Life Panel — importers (BE-3, founder-directed 2026-07-26).

Moves a four-year corpus out of four silos and into Supabase behind RLS. This
is the step the whole phasing exists to protect: P1 before P2 deliberately, so
that if the shell slips the corpus is already safe.

It also closes a live exposure. Both Firestore mirrors are unauthenticated and
the 12-character sync code IS the credential: anyone holding it reads every
reflection in the archive, with no rate limit and no audit trail (§4.2). That
is an independent reason to run this beyond convenience.

Three sources, three planners
─────────────────────────────
  principles-app  ``{principles, wins, prayer}``   → cases + principles + wins
                                                     + phrases
  timeline        ``{events: [...]}``              → event items
  strategy        the transcribed daily/weekly docs → life_strategy v1 + bets
                                                     + goals + habits

Every planner is a PURE function producing rows; ``apply_plan`` is the only
thing that writes. That split is what makes ``--dry-run`` honest — the dry run
executes the identical planning code, not a parallel description of it.

What must survive, each one a test (BE-3)
─────────────────────────────────────────
  * ``createdAt`` — the corpus spans 2022→2026 and the dates carry meaning.
  * category strings mapped to the fixed six; ANYTHING UNMAPPED goes to a
    review queue, never silently coerced. A mis-mapped category is a lie about
    a four-year-old reflection and it is invisible once written.
  * multi-principle and multi-category cases — both exist in the corpus. One
    case produced "Focus on saving your own life first" AND "Don't try to
    understand it all"; the scooter/drift case carries Wishful thinking AND
    Hubris.
  * the Polish text VERBATIM. No translation, no normalisation, no cleanup
    pass. Several reflections are code-switched mid-paragraph and that is the
    record.
  * the manual drag-to-reorder order → ``order_key``.
  * the ``prayer.v1`` blob split into phrase rows on quote boundaries;
    anything unsplittable stays as one note so nothing is lost.

Idempotency
───────────
Every planned row carries an ``external_id`` derived from the source id (or,
absent one, a content hash). The unique partial indexes on
``(user_id, external_id)`` make a re-run an update rather than a duplicate, so
the importer can be run, checked, fixed and run again — which is how a
one-shot migration of an irreplaceable corpus should behave.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from typing import Any, Iterable, Optional

from services import life_panel as lp

logger = logging.getLogger(__name__)

# Accepted key spellings per field. The exports come from two hand-rolled
# localStorage apps written years apart, so the field names are not
# guaranteed; reading a list of aliases is honest about that where hard-coding
# one spelling would silently import an archive of empty strings.
_CASE_KEYS: dict[str, tuple[str, ...]] = {
    "case_at_hand": ("caseAtHand", "case_at_hand", "case", "sytuacja",
                     "title", "problem"),
    "principles_applied": ("principlesApplied", "principles_applied",
                           "principles", "zasady"),
    "reflections": ("reflections", "reflection", "refleksje", "notes",
                    "body", "text"),
    "category": ("category", "categories", "kategoria", "tags", "tag"),
    "created_at": ("createdAt", "created_at", "date", "ts", "timestamp"),
    "occurred_on": ("occurredOn", "occurred_on", "eventDate", "when"),
    "new_principle": ("newPrinciple", "new_principle", "principle", "lesson",
                      "zasada"),
    "order": ("order", "orderKey", "order_key", "index", "position", "sort"),
    "id": ("id", "uid", "key", "_id"),
}

_WIN_KEYS: dict[str, tuple[str, ...]] = {
    "body": ("text", "body", "win", "title", "content"),
    "created_at": ("createdAt", "created_at", "date", "ts"),
    "order": ("order", "orderKey", "index", "position"),
    "id": ("id", "uid", "key", "_id"),
}

_EVENT_KEYS: dict[str, tuple[str, ...]] = {
    "title": ("title", "label", "name", "text"),
    "body": ("description", "body", "notes", "detail"),
    "due_label": ("dateLabel", "label", "due", "when"),
    "due_at": ("date", "start", "startDate", "at", "due_at"),
    "category": ("category", "categoryColor", "color", "bet", "type"),
    "created_at": ("createdAt", "created_at", "ts"),
    "order": ("order", "index", "position"),
    "id": ("id", "uid", "key", "_id"),
}


def _pick(row: dict, keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in row and row[key] not in (None, ""):
            return row[key]
    return None


def _text(value: Any) -> str:
    """Verbatim. Whitespace at the ends only — never the middle, never the
    characters. The corpus is code-switched Polish/English and every
    'normalisation' is a small edit to somebody's confession."""
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return "\n".join(_text(v) for v in value if v not in (None, ""))
    return str(value).strip()


def _external_id(prefix: str, row: dict, keys: tuple[str, ...],
                 fallback_text: str) -> str:
    """A stable id for this source row.

    Prefers the source's own id. Without one, a content hash — which means a
    re-import after the founder EDITS a row in the old app creates a second
    row rather than updating the first. That is the safe direction: the
    importer never overwrites a reflection because two of them looked alike."""
    raw = _pick(row, keys)
    if raw:
        return f"{prefix}:{raw}"
    digest = hashlib.sha256(fallback_text.encode("utf-8")).hexdigest()[:24]
    return f"{prefix}:sha:{digest}"


def _order_key(row: dict, keys: tuple[str, ...], index: int) -> float:
    """The manual drag order, preserved. Falls back to file order, which IS
    the drag order in a localStorage array."""
    raw = _pick(row, keys)
    try:
        return float(raw) * 1000.0 if raw is not None else float(index + 1) * 1000.0
    except (TypeError, ValueError):
        return float(index + 1) * 1000.0


def _iso(value: Any) -> Optional[str]:
    """A source timestamp → ISO-8601, or None.

    Accepts ISO strings and epoch millis/seconds (localStorage apps write
    both). None when it cannot be read — and the caller then leaves created_at
    to the database default rather than inventing a date, because a wrong date
    on a 2022 reflection is worse than a missing one."""
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        from datetime import datetime, timezone
        seconds = float(value)
        if seconds > 1e11:          # milliseconds
            seconds /= 1000.0
        try:
            return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat()
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip()
    if not text:
        return None
    from datetime import datetime, timezone
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z",
                "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%d/%m/%Y", "%d.%m.%Y"):
        try:
            parsed = datetime.strptime(text.replace("Z", "+0000"), fmt)
        except ValueError:
            continue
        # A naive source timestamp is read as UTC rather than left naive: the
        # column is timestamptz, and handing Postgres a naive value makes the
        # date depend on the server's zone — which would silently move a
        # 2022 reflection by a day.
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.isoformat()
    return None


def _date_only(value: Any) -> Optional[str]:
    iso = _iso(value)
    return iso[:10] if iso else None


# ═════════════════════════════════════════════════════════════════════════
# principles-app
# ═════════════════════════════════════════════════════════════════════════

def plan_cases(user_id: str, principles: Iterable[dict]) -> dict:
    """``{cases: [...], items: [...], review: [...]}`` for the principles list.

    A case row and its principle(s) are SPLIT — unlike the current app's
    single row. The corpus justifies it: several cases produced TWO principles,
    and several carry TWO categories. One row cannot hold either without
    losing something.
    """
    cases: list[dict] = []
    items: list[dict] = []
    review: list[dict] = []

    for index, raw in enumerate(principles or []):
        if not isinstance(raw, dict):
            continue
        case_text = _text(_pick(raw, _CASE_KEYS["case_at_hand"]))
        reflections = _text(_pick(raw, _CASE_KEYS["reflections"]))
        applied = _text(_pick(raw, _CASE_KEYS["principles_applied"]))
        if not any((case_text, reflections, applied)):
            continue

        external = _external_id("principles", raw, _CASE_KEYS["id"],
                                f"{case_text}\n{reflections}")

        # Multi-category: the source may hold a string, a comma-separated
        # string, or a list. All three appear.
        raw_categories = _pick(raw, _CASE_KEYS["category"])
        if isinstance(raw_categories, str):
            raw_categories = [c for c in re.split(r"[,;/|]", raw_categories)
                              if c.strip()]
        raw_categories = raw_categories if isinstance(raw_categories, list) else []

        mapped: list[str] = []
        unmapped: list[str] = []
        for candidate in raw_categories:
            key = lp.map_import_category(_text(candidate))
            if key:
                if key not in mapped:
                    mapped.append(key)
            elif _text(candidate):
                unmapped.append(_text(candidate))

        if unmapped:
            # NEVER silently coerced. The row still imports — with its
            # categories parked in import_category_raw — so the reflection is
            # safe while a human decides what the label meant.
            review.append({"external_id": external, "unmapped": unmapped,
                           "case_at_hand": case_text[:120]})

        created = _iso(_pick(raw, _CASE_KEYS["created_at"]))
        case_row: dict[str, Any] = {
            "external_id": external,
            "case_at_hand": case_text,
            "principles_applied": applied,
            # Verbatim, always. This field is also never model-written (N5) —
            # on the import path it comes from the export, on the API path
            # from the request body, and from nowhere else.
            "reflections": reflections,
            "category": mapped,
            "occurred_on": _date_only(_pick(raw, _CASE_KEYS["occurred_on"])),
            "status": "active",
        }
        if unmapped:
            case_row["import_category_raw"] = "; ".join(unmapped)
        if created:
            case_row["created_at"] = created
        cases.append(case_row)

        # Multi-principle: one case can teach two. Split on newlines and on
        # the numbered/bulleted forms the export uses.
        principle_text = _text(_pick(raw, _CASE_KEYS["new_principle"]))
        for offset, line in enumerate(_split_principles(principle_text)):
            item = {
                "external_id": f"{external}#p{offset}",
                "kind": "principle",
                "title": line,
                "body": line,
                "status": "active",
                "order_key": _order_key(raw, _CASE_KEYS["order"], index)
                + offset,
                # Wired up by apply_plan once the case row has an id.
                "_case_external_id": external,
            }
            if created:
                item["created_at"] = created
            items.append(item)

    return {"cases": cases, "items": items, "review": review}


_PRINCIPLE_SPLIT = re.compile(r"(?:\r?\n)+|(?:^|\s)[-•*]\s+|(?:^|\s)\d+[.)]\s+")


def _split_principles(text: str) -> list[str]:
    """One principle field → the one or two principles it actually holds.

    Conservative: only splits on line breaks and explicit list markers. A
    sentence break is NOT a split — several principles in the corpus are two
    sentences long, and splitting them would turn one principle into two
    half-principles."""
    if not text:
        return []
    parts = [p.strip(" \t-•*") for p in _PRINCIPLE_SPLIT.split(text) if p]
    return [p for p in parts if len(p) > 2]


def plan_wins(user_id: str, wins: Iterable[Any]) -> list[dict]:
    rows: list[dict] = []
    for index, raw in enumerate(wins or []):
        row = raw if isinstance(raw, dict) else {"text": raw}
        body = _text(_pick(row, _WIN_KEYS["body"]))
        if not body:
            continue
        item = {
            "external_id": _external_id("wins", row, _WIN_KEYS["id"], body),
            "kind": "win",
            "title": body[:500],
            "body": body,
            "status": "active",
            "order_key": _order_key(row, _WIN_KEYS["order"], index),
        }
        created = _iso(_pick(row, _WIN_KEYS["created_at"]))
        if created:
            item["created_at"] = created
        rows.append(item)
    return rows


# Typographic quote pairs, in the order the corpus uses them. Polish „…"
# first: it is the dominant form in this archive and its closing mark is the
# same character English uses to OPEN, so trying the English pair first would
# mis-split every Polish quotation.
_QUOTE_PAIRS: tuple[tuple[str, str], ...] = (
    ("„", "”"), ("“", "”"), ("«", "»"), ("\"", "\""),
)

# The single quote is NOT a quote pair here. It is an apostrophe far more
# often than it is a quotation mark in this corpus ("Don't try to understand
# it all" is an actual principle), and pairing on it would slice phrases
# mid-word. The cost of leaving it out is that a genuinely single-quoted
# phrase stays in the leftover note — nothing is lost, it is just not split.
# The cost of leaving it in is garbage on the wall. Asymmetric costs again.

# Openers that may not appear INSIDE an asymmetric match. Deliberately only
# the asymmetric openers: adding the apostrophe here would break every
# contraction, and adding the straight quote would break a nested quotation.
_ASYMMETRIC_OPENERS = "„“«"

# Where a phrase lands when nothing says otherwise. The panel groups the wall
# by collection, and a row with none renders under "Uncollected" — which reads
# as a filing mistake rather than as a phrase somebody wanted kept.
PHRASE_DEFAULT_COLLECTION = "wall"

# Smart phrases are short. Anything longer than this that happens to sit
# between two quote marks is a paragraph, not a phrase.
_MAX_PHRASE_CHARS = 600


def split_phrases(blob: str) -> tuple[list[str], str]:
    """``prayer.v1`` → ``(phrases, leftover)``.

    The blob is a single text field being used as a dump (§3.5). Quoted
    segments become phrase rows; everything else comes back as ``leftover``
    for the caller to keep as ONE note.

    Nothing is discarded, ever. "Anything it can't split stays as one note so
    nothing is lost" is the requirement, and the leftover return value is how
    that promise is kept rather than asserted."""
    text = blob if isinstance(blob, str) else ""
    if not text.strip():
        return [], ""

    phrases: list[str] = []
    consumed: list[tuple[int, int]] = []
    for opener, closer in _QUOTE_PAIRS:
        # The captured group may not contain another OPENER. Without that
        # exclusion an unclosed quote — and there are unclosed quotes in a
        # hand-typed dump — lets the non-greedy match run to the next closer
        # several phrases later, welding three aphorisms into one row.
        excluded = (_ASYMMETRIC_OPENERS if opener != closer
                    else re.escape(opener))
        pattern = re.compile(
            f"{re.escape(opener)}([^{excluded}]+?){re.escape(closer)}",
            re.DOTALL,
        )
        for match in pattern.finditer(text):
            if any(start <= match.start() < end for start, end in consumed):
                continue
            body = match.group(1).strip()
            # A "phrase" this long is a mis-split, not an aphorism. Skipping it
            # leaves the text in `leftover`, so it survives as a note instead
            # of becoming a wall entry nobody wants returned to them.
            if 2 < len(body) <= _MAX_PHRASE_CHARS:
                phrases.append(body)
                consumed.append((match.start(), match.end()))

    if not phrases:
        # Unsplittable. The whole blob survives as one note — losing a dump of
        # smart phrases to a regex that found no quotes would be the exact
        # failure this function exists to prevent.
        return [], text.strip()

    consumed.sort()
    leftover_parts: list[str] = []
    cursor = 0
    for start, end in consumed:
        leftover_parts.append(text[cursor:start])
        cursor = end
    leftover_parts.append(text[cursor:])
    leftover = "\n".join(p.strip() for p in leftover_parts if p.strip())
    return phrases, leftover


def plan_phrases(user_id: str, blob: Any,
                 *, collection: str = PHRASE_DEFAULT_COLLECTION) -> dict:
    """``{items, notes}`` — phrase rows plus whatever could not be split."""
    phrases, leftover = split_phrases(blob if isinstance(blob, str)
                                      else json.dumps(blob, ensure_ascii=False)
                                      if blob else "")
    items = [{
        "external_id": _external_id("phrase", {}, (), phrase),
        "kind": "phrase",
        "title": phrase[:500],
        "body": phrase,
        "collection": collection,
        "status": "active",
        "order_key": float(i + 1) * 1000.0,
    } for i, phrase in enumerate(phrases)]
    notes = ([{"body": leftover, "source": "import"}] if leftover else [])
    return {"items": items, "notes": notes}


# ═════════════════════════════════════════════════════════════════════════
# timeline
# ═════════════════════════════════════════════════════════════════════════

def plan_events(user_id: str, events: Iterable[dict]) -> list[dict]:
    """The timeline export → ``event`` items.

    ``categoryColor`` already matches the bets' 🟢🔵🟣, so it is kept as the
    body prefix rather than being re-derived — the canvas colours the bands
    from it today and re-deriving would be a chance to get it wrong."""
    rows: list[dict] = []
    for index, raw in enumerate(events or []):
        if not isinstance(raw, dict):
            continue
        title = _text(_pick(raw, _EVENT_KEYS["title"]))
        if not title:
            continue
        label = _text(_pick(raw, _EVENT_KEYS["due_label"])) or None
        due_at = _date_only(_pick(raw, _EVENT_KEYS["due_at"])) \
            or lp.parse_due_label(label)
        item = {
            "external_id": _external_id("timeline", raw, _EVENT_KEYS["id"],
                                        title),
            "kind": "event",
            "title": title,
            "body": _text(_pick(raw, _EVENT_KEYS["body"])),
            "status": "active",
            "due_label": label,
            "due_at": due_at,
            "collection": _text(_pick(raw, _EVENT_KEYS["category"])) or None,
            "order_key": _order_key(raw, _EVENT_KEYS["order"], index),
        }
        created = _iso(_pick(raw, _EVENT_KEYS["created_at"]))
        if created:
            item["created_at"] = created
        rows.append(item)
    return rows


# ═════════════════════════════════════════════════════════════════════════
# strategy documents
# ═════════════════════════════════════════════════════════════════════════

def plan_strategy(user_id: str, payload: dict) -> dict:
    """The transcribed daily/weekly documents → ``life_strategy`` v1 plus the
    bet / goal / habit rows.

    The three bets are seeded from ``lp.BETS`` in their locked rank when the
    payload does not carry them — the rank is immutable core (L-2a), so it is
    never taken from a free-form transcription that could have reordered it.
    """
    documents = payload.get("documents") if isinstance(payload, dict) else None
    documents = documents if isinstance(documents, dict) else {}
    strategy = [
        {"horizon": horizon, "body": _text(body)}
        for horizon, body in documents.items()
        if str(horizon).strip().lower() in lp.STRATEGY_HORIZONS
        and _text(body)
    ]

    items: list[dict] = []
    for bet in lp.BETS:
        items.append({
            "external_id": f"bet:{bet['key']}",
            "kind": "bet",
            "title": f"{bet['emoji']} {bet['title']}",
            "body": bet["body"],
            "status": "active",
            # order_key IS the rank for bets. Locked (L-2a).
            "order_key": float(bet["rank"]),
        })

    for index, raw in enumerate(payload.get("goals") or []):
        if not isinstance(raw, dict):
            continue
        title = _text(raw.get("title") or raw.get("text"))
        if not title:
            continue
        label = _text(raw.get("due_label") or raw.get("due")) or None
        horizon = str(raw.get("horizon") or "").strip().lower()
        items.append({
            "external_id": _external_id("goal", raw, ("id",), title),
            "kind": "goal",
            "title": title,
            "body": _text(raw.get("body")),
            "status": "active",
            "horizon": horizon if horizon in lp.HORIZONS else None,
            "due_label": label,
            # THE MODEL'S RESOLVED DATE LEADS (founder 2026-08-01). The label
            # is the person's own wording and stays exactly as written; the
            # date is what places a marker on the timeline. parse_due_label
            # only ever handled the notations it was taught — "[Jul '27]",
            # "2035", "Aug" — and returned None for anything else, so a goal
            # written "to July 2031" had no date at all and could never appear
            # on the canvas. Extraction resolves it now, and the parser stays
            # as the fallback for a row the model gave nothing for.
            "due_at": (_date_only(raw.get("due_date"))
                       or lp.parse_due_label(label)),
            "collection": _text(raw.get("bet")) or None,
            "order_key": float(index + 1) * 1000.0,
        })

    for kind, key in (("habit", "habits"), ("distraction", "distractions")):
        for index, raw in enumerate(payload.get(key) or []):
            row = raw if isinstance(raw, dict) else {"title": raw}
            title = _text(row.get("title") or row.get("text"))
            if not title:
                continue
            items.append({
                "external_id": _external_id(kind, row, ("id",), title),
                "kind": kind,
                "title": title,
                # For a distraction the body is the ENVIRONMENTAL RESPONSE,
                # not a description: Section IV pairs every distraction with a
                # design response, never with willpower.
                "body": _text(row.get("response") or row.get("body")),
                "status": "active",
                "order_key": float(index + 1) * 1000.0,
            })

    return {"strategy": strategy, "items": items}


# ═════════════════════════════════════════════════════════════════════════
# The runner
# ═════════════════════════════════════════════════════════════════════════

def build_plan(user_id: str, *, principles_export: Optional[dict] = None,
               timeline_export: Optional[dict] = None,
               strategy_export: Optional[dict] = None) -> dict:
    """Everything that WOULD be written, as data. Pure — no I/O."""
    plan: dict[str, Any] = {"cases": [], "items": [], "notes": [],
                            "strategy": [], "review": []}

    if principles_export:
        cases = plan_cases(user_id, principles_export.get("principles") or [])
        plan["cases"].extend(cases["cases"])
        plan["items"].extend(cases["items"])
        plan["review"].extend(cases["review"])
        plan["items"].extend(
            plan_wins(user_id, principles_export.get("wins") or []))
        phrases = plan_phrases(user_id, principles_export.get("prayer"))
        plan["items"].extend(phrases["items"])
        plan["notes"].extend(phrases["notes"])

    if timeline_export:
        events = (timeline_export.get("events")
                  if isinstance(timeline_export, dict) else timeline_export)
        plan["items"].extend(plan_events(user_id, events or []))

    if strategy_export:
        strategy = plan_strategy(user_id, strategy_export)
        plan["strategy"].extend(strategy["strategy"])
        plan["items"].extend(strategy["items"])

    plan["counts"] = {
        "cases": len(plan["cases"]),
        "items": len(plan["items"]),
        "notes": len(plan["notes"]),
        "strategy": len(plan["strategy"]),
        "needs_review": len(plan["review"]),
    }
    return plan


def apply_plan(user_id: str, plan: dict, *, dry_run: bool = True) -> dict:
    """Write the plan. ``dry_run=True`` (the DEFAULT) writes nothing.

    Defaulting to dry-run is deliberate: the destructive direction should
    require a word, not the absence of one. The counts a dry run reports come
    from the same planning code the real run executes, so "what it says it
    will do" and "what it does" cannot drift."""
    result = {"dry_run": dry_run, "written": {"cases": 0, "items": 0,
                                              "notes": 0, "strategy": 0},
              "review": plan.get("review") or [],
              "planned": plan.get("counts") or {}}
    if dry_run:
        return result

    from services import life_store as store

    case_ids: dict[str, str] = {}
    for row in plan.get("cases") or []:
        written = store.insert_case(user_id, row)
        if written:
            case_ids[str(row.get("external_id"))] = str(written.get("id"))
            result["written"]["cases"] += 1

    for row in plan.get("items") or []:
        payload = {k: v for k, v in row.items() if not k.startswith("_")}
        parent = row.get("_case_external_id")
        if parent and parent in case_ids:
            payload["origin_case_id"] = case_ids[parent]
        if store.insert_item(user_id, payload):
            result["written"]["items"] += 1

    for row in plan.get("notes") or []:
        if store.insert_note(user_id, row.get("body") or "",
                             source=row.get("source") or "import"):
            result["written"]["notes"] += 1

    for row in plan.get("strategy") or []:
        if store.insert_strategy_version(user_id, horizon=row["horizon"],
                                         body=row["body"]):
            result["written"]["strategy"] += 1

    return result


# ═════════════════════════════════════════════════════════════════════════
# Setup strategy-document uploads (founder-approved item 9, 2026-07-30)
# ═════════════════════════════════════════════════════════════════════════
# The setup wizard's optional "Current strategy" upload. This is an IMPORT
# concern — external material entering the panel — which is why the table I/O
# lives here rather than growing services/life_store (out of scope for this
# change; the direction life → db stays one-way either way, following the
# services/dev_tasks.py precedent of a module owning its own table through
# ``db.client``).
#
# ONLY THE EXTRACTED TEXT IS STORED, never the binary (see
# migrations/add_life_setup_documents.sql for the full rationale). The
# extracted_text column is confession-adjacent material and is NEVER returned
# by the listing helpers — only the route that feeds it to the engine reads it.

_SETUP_DOCUMENTS_TABLE = "life_setup_documents"


def _doc_table():
    from services.db import db
    return db.client.table(_SETUP_DOCUMENTS_TABLE)


def _doc_rows(result: Any) -> list[dict]:
    data = getattr(result, "data", None)
    return list(data) if isinstance(data, list) else []


def insert_setup_document(user_id: str, *, file_name: str, mime_type: str,
                          extracted_text: str, char_count: int,
                          status: str) -> Optional[dict]:
    """One uploaded document → one row of extracted text. Returns the row
    WITHOUT extracted_text (the caller serialises metadata only)."""
    try:
        res = _doc_table().insert({
            "user_id": user_id,
            "file_name": (file_name or "")[:300] or None,
            "mime_type": (mime_type or "")[:150] or None,
            "extracted_text": extracted_text or "",
            "char_count": int(char_count or 0),
            "status": status if status in ("processed", "extraction_failed")
            else "extraction_failed",
        }).execute()
        rows = _doc_rows(res)
        if not rows:
            return None
        row = dict(rows[0])
        row.pop("extracted_text", None)
        return row
    except Exception as e:
        logger.error("life: insert_setup_document failed user=%s: %s",
                     user_id, e)
        return None


def list_setup_documents(user_id: str, *, limit: int = 20) -> list[dict]:
    """Metadata only, latest first. extracted_text never rides a listing."""
    try:
        res = (_doc_table()
               .select("id, file_name, mime_type, char_count, status, "
                       "created_at")
               .eq("user_id", user_id)
               .order("created_at", desc=True)
               .limit(max(1, min(100, limit))).execute())
        return _doc_rows(res)
    except Exception as e:
        logger.warning("life: list_setup_documents failed user=%s: %s",
                       user_id, e)
        return []


def get_setup_document(user_id: str,
                       document_id: Optional[str] = None) -> Optional[dict]:
    """One document WITH its text — the newest processed one when no id is
    given. Owner-scoped like every life read."""
    try:
        query = _doc_table().select("*").eq("user_id", user_id)
        if document_id:
            query = query.eq("id", document_id)
        else:
            query = query.eq("status", "processed")
        rows = _doc_rows(query.order("created_at", desc=True)
                         .limit(1).execute())
        return rows[0] if rows else None
    except Exception as e:
        logger.warning("life: get_setup_document failed user=%s: %s",
                       user_id, e)
        return None


def latest_setup_document_text(user_id: str) -> str:
    """The newest processed upload's text, or "". What generate_documents
    injects so the crafted strategy aligns with the user's own document."""
    row = get_setup_document(user_id)
    return (row or {}).get("extracted_text") or ""


def delete_setup_documents(user_id: str) -> Optional[int]:
    """Hard-delete path (BE-10). Returns the removed count, or None on
    failure — the route reports a partial delete rather than claiming
    success."""
    try:
        res = _doc_table().delete().eq("user_id", user_id).execute()
        return len(_doc_rows(res))
    except Exception as e:
        logger.error("life: delete_setup_documents failed user=%s: %s",
                     user_id, e)
        return None


def export_setup_documents(user_id: str) -> Optional[list[dict]]:
    """Everything, INCLUDING extracted_text — an export exists so the user
    can leave with all of it. None on failure so the export can say so."""
    try:
        res = (_doc_table().select("*").eq("user_id", user_id)
               .limit(1000).execute())
        return _doc_rows(res)
    except Exception as e:
        logger.warning("life: export_setup_documents failed user=%s: %s",
                       user_id, e)
        return None


# ═════════════════════════════════════════════════════════════════════════
# Document-drafted items (item 9's review step)
# ═════════════════════════════════════════════════════════════════════════

# THE kind set for the document dock — what /setup/propose-from-document may
# emit AND what /setup/apply-proposed will create. One tuple on purpose: if
# the two ever disagree the user ticks rows, presses Add, and is told nothing
# was created with nothing to do about it. A test asserts the agreement rather
# than trusting this comment.
#
# Every entry is one of lp.ITEM_KINDS — the panel's closed nine. A tenth kind
# is an FE change (their renderer drops rows it does not know, by design), so
# it is never something this file may grow alone.
DOC_DRAFT_KINDS: tuple[str, ...] = ("bet", "goal", "habit", "distraction",
                                    "phrase", "principle", "win")

# The three the model reads as LINES rather than as structured goals: a
# phrases document is a list of lines someone wants handed back at the right
# moment, a principles document a list of rules they wrote for themselves, a
# wins document a list of what went well. Same taxonomy, reached from a file
# instead of from the chat.
DOC_DRAFT_LINE_KINDS: tuple[str, ...] = ("phrase", "principle", "win")

_CONFIRMABLE_KINDS = DOC_DRAFT_KINDS


def plan_document_lines(user_id: str, kind: str,
                        lines: Iterable[Any]) -> list[dict]:
    """Lines read out of an uploaded document → phrase / principle / win rows.

    PURE, like every other planner here: it returns rows, it writes nothing.
    The shape matches what ``plan_phrases`` / ``plan_cases`` / ``plan_wins``
    produce for the same kinds, so a row drafted from a file and the same row
    imported from the old app are indistinguishable once written — including
    the content-hash ``external_id``, which is what makes ticking the same
    line twice an update instead of a second copy on the wall.

    Duplicates inside ONE draft are dropped here rather than at insert time.
    The unique index would refuse the second row silently, and a user who
    ticked six rows and was told four were created has no way to find out
    which two the system quietly disagreed with.
    """
    if kind not in DOC_DRAFT_LINE_KINDS:
        return []
    rows: list[dict] = []
    seen: set[str] = set()
    for index, raw in enumerate(lines or []):
        source = raw if isinstance(raw, dict) else {"title": raw}
        text = _text(source.get("title") or source.get("text")
                     or source.get("body"))
        # Same floor as _split_principles: two characters is a bullet that
        # survived, not a line somebody wrote.
        if len(text) <= 2:
            continue
        external = _external_id(kind, {}, (), text)
        if external in seen:
            continue
        seen.add(external)
        title = text[:500]
        row: dict[str, Any] = {
            "external_id": external,
            "kind": kind,
            "title": title,
            # The body carries the full line ONLY when the title had to be
            # cut. Empty otherwise, so the review row renders once rather
            # than twice — while a 600-character phrase still keeps every
            # character it was written with.
            "body": text if text != title else "",
            "status": "active",
            "order_key": float(index + 1) * 1000.0,
        }
        if kind == "phrase":
            row["collection"] = PHRASE_DEFAULT_COLLECTION
        rows.append(row)
    return rows


def sanitize_confirmed_item(raw: Any) -> Optional[dict]:
    """One TICKED row from the setup review UI → life_items fields, or None.

    N5, as the founder restated it for this flow: whatever the user ticked in
    the review step gets created ACTIVE (the tick IS the explicit approve,
    made on a row that was fully displayed), unticked rows are never sent and
    never created, and nothing lands as a silent 'proposed'. Status is
    therefore FORCED to 'active' here regardless of what the client sent.

    That reading is what lets a PRINCIPLE through this path while the engine's
    own derived principles still wait in 'proposed'. The triage state exists
    so a bad prompt day cannot silently corrupt sixty principles earned over
    four years — silently being the load-bearing word. A principle drafted
    from a document was displayed verbatim on a screen and individually
    ticked by the person who wrote it in the first place; there is nothing
    left for triage to catch.

    A 'bet' row keeps the LOCKED rank from lp.BETS (L-2a): the uploaded
    document can word a bet, it can never reorder them."""
    if not isinstance(raw, dict):
        return None
    kind = str(raw.get("kind") or "").strip()
    if kind not in _CONFIRMABLE_KINDS:
        return None
    title = _text(raw.get("title"))[:500]
    if not title:
        return None
    label = _text(raw.get("due_label") or raw.get("dueLabel"))[:120] or None
    horizon = str(raw.get("horizon") or "").strip().lower()
    # `bet` is what the goals surface calls it on the way in, `collection` is
    # the column. BOTH are accepted so neither side has to translate; the FE's
    # mapping is belt-and-braces, not a requirement.
    collection = _text(raw.get("bet") or raw.get("collection"))[:120] or None
    if kind == "phrase" and not collection:
        # A phrase with no collection lands under "Uncollected". Defaulted
        # here as well as at draft time so a client that drops the field —
        # or a row hand-built by a caller that never saw the draft — still
        # reaches the wall.
        collection = PHRASE_DEFAULT_COLLECTION
    fields: dict[str, Any] = {
        "kind": kind,
        "title": title,
        "body": _text(raw.get("body"))[:8000],
        "status": "active",
        "horizon": horizon if horizon in lp.HORIZONS else None,
        "due_label": label,
        # The resolved date RIDES THE ROUND TRIP. A goal is drafted with a
        # due_at the extraction worked out, displayed, ticked, and posted back
        # here — and recomputing it from the label alone would silently throw
        # that away at the last step, so a goal written "to July 2031" would
        # draft with a date and then be CREATED without one. Both spellings
        # are accepted for the same reason bet/collection both are: neither
        # side should have to translate.
        "due_at": (_date_only(raw.get("due_at") or raw.get("dueAt")
                              or raw.get("due_date"))
                   or lp.parse_due_label(label)),
        "collection": collection,
    }
    external_id = _text(raw.get("external_id") or raw.get("externalId"))[:200]
    if external_id:
        # Round-tripped from plan_strategy so the unique partial index makes a
        # double-submit an update, not a duplicate.
        fields["external_id"] = external_id
    if kind == "bet":
        locked = next((b for b in lp.BETS
                       if f"{b['emoji']} {b['title']}" == title
                       or b["title"] == title), None)
        if not locked:
            # An invented bet is refused outright: three bets, locked rank.
            return None
        fields["title"] = f"{locked['emoji']} {locked['title']}"
        fields["external_id"] = f"bet:{locked['key']}"
        fields["order_key"] = float(locked["rank"])
        fields["horizon"] = None
    else:
        try:
            fields["order_key"] = float(raw.get("order_key"))
        except (TypeError, ValueError):
            fields["order_key"] = 0.0
    return fields
