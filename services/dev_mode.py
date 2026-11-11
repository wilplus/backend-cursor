"""Developer mode in Build (N648): what Will measures in a host's chat, in
plain numbers, for the host only (N647 item 7, N648 item 7).

  GET /v2/chats/setup/dev                       the screens' numbers
  GET /v2/chats/setup/dev/charts/<name>.csv     one chart's counts, a file

Behind the ring row ``chat_builder`` (``routes/v2/chats.py``
``_builder_or_404``) and the host's own blank-setup recipe: anyone else gets
404. No provider call; reads only.

THE LIST (N648 item 2). ``CAPABILITIES`` is the one list of what the
speaking coach does, each with its status today: ``built``, ``being_built``
or ``not_started``. Its labels are the pinned prototype's
(docs/design/the-blank-setup-2026-11-10/the-blank-setup.html, ``CLOSE``).
The pull request that builds a thing flips its own row; "{n} of the {m}" is
counted from it, never typed.

WHAT I NOTICE (N648 item 3). Each of the host's own models in their chat:
its level by the model's own gates (``services/model_head.py``: no head is
"Still learning"; a head "Learns from cases"; the owner's check passed is
"Checked by you"; the exam passed and gate two open is "Passed its exam"),
what it still needs for the next one, its segments (its settled examples),
and how often the experts agreed (the exam's cases right, once computed;
before that the owner's check, kept of answered). The experiments run come
from the silent tries, not built yet: ``None``.

WHAT I SAY (N648 item 4). Each line of the walk as the walk's own reader
gives it (``chat_replies.walk_view``): its words, on or off, "Helped {a}
of {b}" shown at once, and how many more answers until ``ENOUGH_TO_TELL``.

CHARTS (N648 item 5). Counts by week, never a person. Walks run and "Did
this help?" read the same lines ``chat_replies.helped`` reads; one chat is
one person, so a week with 1 to 4 chats is hidden. A week with at least
one and fewer than ``SMALLEST_WEEK`` people shows ``None`` with
``fewer_than``, so nobody can be singled out; every chart follows it.
"""
from __future__ import annotations

import csv
import io
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from services import model_head as rules
from services.chats import ChatsError, _not_found

logger = logging.getLogger(__name__)

BUILT, BEING_BUILT, NOT_STARTED = "built", "being_built", "not_started"

#: What the speaking coach does, and how far a host's chat is (N648 item 2).
#: Flip a row in the pull request that builds it.
CAPABILITIES: tuple[dict, ...] = tuple({"key": k, "label": label, "status": status} for k, label, status in (
    ("name_hello_why", "Its name, its hello, why people come", BUILT),
    ("joins_first_questions", "Who joins, and their first questions", BUILT),
    ("what_people_ask", "What people can ask", BUILT),
    ("own_models_answer", "Your own models answer in the chat", BUILT),
    ("walk_steps_chosen", "The walk's steps and what people get are chosen", BUILT),
    ("live_and_build", "Live and Build in one chat", BUILT),
    ("walk_in_chat", "The walk runs in your chat", BUILT),
    ("take_in_chat", "People record a Take in your chat", BEING_BUILT),
    ("transcript_ideal_text", "The transcript and the Ideal Text", BEING_BUILT),
    ("notices_as_settings", "What it notices, as settings", BEING_BUILT),
    ("says_and_helped", "What it says, and whether it helped", BUILT),
    ("silent_tries", "Silent tries before a change", BEING_BUILT),
    ("practice", "Practice and exercises", BEING_BUILT),
    ("plan_feelings", "The plan and the feelings check", BEING_BUILT),
    ("coaches_moments", "Coaches answer the moments", BEING_BUILT),
))

#: The four levels, a model's own gates (N566, N616), in order.
LEVELS = ("Still learning", "Learns from cases", "Checked by you", "Passed its exam")

#: The smallest count of people a week shows; fewer (but some) is hidden.
SMALLEST_WEEK = 5
#: How many weeks a chart holds (the prototype: the last eight).
WEEKS = 8
#: The charts this module can count today (N648 item 5); the Ideal Text's
#: comes with its neighbour.
CHARTS = ("people", "walks", "helped")


def _rows(query: Any) -> list[dict]:
    return query.execute().data or []


# ── How close to the speaking coach ─────────────────────────────────────────
def close() -> dict:
    built = sum(1 for c in CAPABILITIES if c["status"] == BUILT)
    return {"done": built, "of": len(CAPABILITIES), "items": [dict(c) for c in CAPABILITIES]}


# ── What I notice ───────────────────────────────────────────────────────────
def level_of(versions: list[dict]) -> int:
    """0 to 3 by the gates of any version (a later one never lowers it)."""
    gates = [rules.gates(v) for v in versions if v.get("status") != "retired"]
    if any(g["share"] for g in gates):
        return 3
    if any(g["owner_chat"] for g in gates):
        return 2
    return 1 if any(v.get("head") for v in versions if v.get("status") != "retired") else 0


def _short_of_settled(settled: list[dict], answers: list[str]) -> int:
    """How many more settled cases before a head may be fitted: at least
    MIN_SETTLED in all, and MIN_PER_ANSWER of each answer."""
    each = {a: 0 for a in answers}
    for e in settled:
        if str(e.get("known_answer")) in each:
            each[str(e["known_answer"])] += 1
    per = sum(max(0, rules.MIN_PER_ANSWER - n) for n in each.values())
    return max(rules.MIN_SETTLED - len(settled), per, 0)


def notice_row(model: dict, versions: list[dict], examples: list[dict], settled: list[dict],
               exam_target: int) -> dict:
    """One thing noticed: its level, what it needs, its segments, and the
    experts' agreement, all plain counts. Pure."""
    from services.model_head_store import latest_with_head
    lv = level_of(versions)
    head = latest_with_head(versions)
    answers = rules.answers_of(model.get("recipe"))
    need: Optional[dict[str, Any]]
    have, of = 1, 1
    if lv == 0:
        more = _short_of_settled(settled, answers)
        have, of = len(settled), len(settled) + more
        need = {"step": "settle", "more": more, "have": have, "of": of}
    elif lv == 1:
        items = ((head or {}).get("owner_check") or {}).get("items") or []
        done = sum(1 for i in items if i.get("kept") is not None)
        have, of = done, rules.CHECK_SIZE
        need = {"step": "check", "have": have, "of": of}
    elif lv == 2:
        cases = sum(1 for e in examples if e.get("in_exam"))
        have, of = min(cases, exam_target), exam_target
        need = {"step": "exam", "have": have, "of": of}
    else:
        need = None
    pct = round(100 * have / of) if of else 0
    return {"model_id": str(model["id"]), "q": (model.get("recipe") or {}).get("question") or model.get("name"),
            "level": lv, "level_name": LEVELS[lv], "next_name": LEVELS[lv + 1] if lv < 3 else None,
            "need": need, "pct": max(0, min(100, pct)),
            "segments": len(settled), "examples": len(examples),
            "experiments": None, "agreed": agreed(head)}


def agreed(version: Optional[dict]) -> Optional[dict]:
    """{"a", "b"}: the exam's cases the head got right, of those scored,
    once the app computed it; before that the owner's check, kept of
    answered; None when neither has an answer yet."""
    v = version or {}
    exam = v.get("exam") or {}
    right = exam.get("right") if exam.get("computed") else None
    if isinstance(right, dict) and right:
        return {"a": sum(1 for ok in right.values() if ok), "b": len(right), "from": "exam"}
    items = [i for i in ((v.get("owner_check") or {}).get("items") or []) if i.get("kept") is not None]
    if items:
        return {"a": sum(1 for i in items if i["kept"]), "b": len(items), "from": "check"}
    return None


def _own_models(database: Any, host: str, recipe: dict) -> list[dict]:
    """The host's own models in their chat, and only the ones they own."""
    from services import model_launchpad_store as models
    ids = [str(m["model_id"]) for m in recipe.get("models") or [] if m.get("own", True) and m.get("model_id")]
    if not ids:
        return []
    found = {str(r["id"]): r for r in _rows(database.client.table(models.MODELS)
                                            .select("id,name,owner_id,status,recipe,targets").in_("id", ids))}
    return [found[i] for i in ids if i in found and str(found[i].get("owner_id")) == host]


def notice(database: Any, host: str, recipe: dict) -> list[dict]:
    from services import model_head_store as store
    from services.model_setup import EXAM_CASES
    out = []
    for m in _own_models(database, host, recipe):
        try:
            examples = store._examples(database, str(m["id"]))
            settled = store.settled_examples(database, m, examples)
            vs = store.versions(database, str(m["id"]))
        except Exception:  # noqa: BLE001 -- one model unread never hides the others
            logger.warning("dev mode: a model could not be read model=%s", m.get("id"), exc_info=True)
            continue
        target = int((m.get("targets") or {}).get("exam") or EXAM_CASES)
        out.append(notice_row(m, vs, examples, settled, target))
    return out


# ── Charts ──────────────────────────────────────────────────────────────────
def _monday(day: datetime) -> datetime:
    d = day.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return d - timedelta(days=d.weekday())


def _when(value: Any) -> Optional[datetime]:
    try:
        when = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def weekly(events: list[tuple[datetime, str]], now: datetime, *, weeks: int = WEEKS) -> list[dict]:
    """``events``: (when, who) pairs, ``who`` only to count once a week. The
    last ``weeks`` weeks, oldest first, each {"week", "count"}; a week of
    1 to SMALLEST_WEEK - 1 people gives count None and "fewer_than". Pure."""
    start = _monday(now) - timedelta(weeks=weeks - 1)
    people: dict[str, set[str]] = {(start + timedelta(weeks=i)).date().isoformat(): set() for i in range(weeks)}
    for when, who in events:
        key = _monday(when).date().isoformat()
        if key in people:
            people[key].add(who)
    out: list[dict] = []
    for week, seen in people.items():
        n = len(seen)
        out.append({"week": week, "count": n} if n == 0 or n >= SMALLEST_WEEK
                   else {"week": week, "count": None, "fewer_than": SMALLEST_WEEK})
    return out


def _host_threads(database: Any, host: str) -> list[str]:
    """The chats people came to the host through: their join link, or their
    chat on a website (``assistants.whose``)."""
    links = [str(r["id"]) for r in _rows(database.client.table("chat_links").select("id").eq("user_id", host))]
    threads = set()
    if links:
        threads |= {str(r["id"]) for r in _rows(database.client.table("chat_threads").select("id")
                                                .in_("link_id", links))}
    threads |= {str(r["id"]) for r in _rows(database.client.table("chat_threads").select("id")
                                            .eq("widget_owner_id", host))}
    return sorted(threads)


def people_events(database: Any, host: str, since: datetime) -> list[tuple[datetime, str]]:
    """(when, who) for each message a person other than the host wrote or
    recorded in the host's chats since ``since``. ``who`` stays here."""
    from services.assistants import MEMBERS, MESSAGES
    threads = _host_threads(database, host)
    if not threads:
        return []
    members = _rows(database.client.table(MEMBERS).select("id,user_id").in_("thread_id", threads))
    others = {str(m["id"]): str(m.get("user_id") or m["id"]) for m in members if str(m.get("user_id")) != host}
    if not others:
        return []
    rows = _rows(database.client.table(MESSAGES).select("author_member_id,created_at")
                 .in_("thread_id", threads).gte("created_at", since.isoformat()))
    out = []
    for r in rows:
        who, when = others.get(str(r.get("author_member_id"))), _when(r.get("created_at"))
        if who and when:
            out.append((when, who))
    return out


def walk_events(database: Any, host: str, since: datetime) -> list[dict]:
    """Each line of the walk the host's chat said since ``since``:
    {"when", "chat", "reply", "useful"}. ``chat`` and ``reply`` stay here,
    only to count chats and walks; ``useful`` is "yes", "no" or None
    (Skip or no answer). The same messages ``chat_replies.helped`` reads."""
    from services.chat_replies import MESSAGES, _host_members
    members = _host_members(database, host)
    ids = {str(m["id"]) for m in members}
    threads = sorted({str(m["thread_id"]) for m in members})
    if not threads:
        return []
    rows = _rows(database.client.table(MESSAGES).select("thread_id,author_member_id,meta,created_at")
                 .in_("thread_id", threads).gte("created_at", since.isoformat()))
    out = []
    for r in rows:
        raw = r.get("meta")
        meta: dict = raw if isinstance(raw, dict) else {}
        when = _when(r.get("created_at"))
        if not isinstance(meta.get("walk_line"), dict) or str(r.get("author_member_id")) not in ids or not when:
            continue
        reply = (meta.get("reply") or {}).get("to") if isinstance(meta.get("reply"), dict) else None
        out.append({"when": when, "chat": str(r.get("thread_id")), "reply": str(reply or r.get("created_at")),
                    "useful": meta.get("useful") if meta.get("useful") in ("yes", "no") else None})
    return out


def _weeks(now: datetime, weeks: int = WEEKS) -> list[str]:
    start = _monday(now) - timedelta(weeks=weeks - 1)
    return [(start + timedelta(weeks=i)).date().isoformat() for i in range(weeks)]


def walks_weekly(events: list[dict], now: datetime) -> list[dict]:
    """Walks run each week (one walk: the lines said in reply to one
    message), hidden as "fewer than 5" when they came from 1 to 4 chats,
    one chat being one person. Pure."""
    walks: dict[str, set] = {w: set() for w in _weeks(now)}
    chats: dict[str, set] = {w: set() for w in walks}
    for e in events:
        w = _monday(e["when"]).date().isoformat()
        if w in walks:
            walks[w].add((e["chat"], e["reply"]))
            chats[w].add(e["chat"])
    return [_shown(w, len(walks[w]), len(chats[w])) for w in walks]


def helped_weekly(events: list[dict], now: datetime) -> list[dict]:
    """"Did this help?" each week: {"week", "count": Yes, "of": Yes or No}
    by the week the line was said; Skip and no answer are left out. Hidden
    when the answers came from 1 to 4 chats. Pure."""
    yes: dict[str, int] = {w: 0 for w in _weeks(now)}
    of: dict[str, int] = dict(yes)
    chats: dict[str, set] = {w: set() for w in yes}
    for e in events:
        w = _monday(e["when"]).date().isoformat()
        if w in yes and e["useful"]:
            of[w] += 1
            yes[w] += e["useful"] == "yes"
            chats[w].add(e["chat"])
    out = []
    for w in yes:
        row = _shown(w, yes[w], len(chats[w]))
        if row["count"] is not None:
            row["of"] = of[w]
        out.append(row)
    return out


def _shown(week: str, count: int, people: int) -> dict:
    if people == 0 or people >= SMALLEST_WEEK:
        return {"week": week, "count": count}
    return {"week": week, "count": None, "fewer_than": SMALLEST_WEEK}


def charts(database: Any, host: str, now: Optional[datetime] = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    since = _monday(now) - timedelta(weeks=WEEKS - 1)
    try:
        people: Optional[list[dict]] = weekly(people_events(database, host, since), now)
    except Exception:  # noqa: BLE001 -- unknown is shown as not counted, never as zero
        logger.warning("dev mode: the people chart could not be read", exc_info=True)
        people = None
    walks: Optional[list[dict]] = None
    helped: Optional[list[dict]] = None
    try:
        events = walk_events(database, host, since)
        walks, helped = walks_weekly(events, now), helped_weekly(events, now)
    except Exception:  # noqa: BLE001 -- unknown is shown as not counted, never as zero
        logger.warning("dev mode: the walk charts could not be read", exc_info=True)
    return [{"name": "people", "weeks": people},
            {"name": "walks", "weeks": walks},
            {"name": "helped", "weeks": helped},
            # Not built on purpose (coordinator, 11 November 2026): a Take made in
            # a host's chat is tagged for its speaker only (services/take_door.py,
            # meta.made_here), so a count of them would let the host subtract what
            # they see and learn who recorded. It waits for the founder's decision
            # on whether a host sees a Take made in their chat; when built, count
            # only what the host can already see, or hide any week where the count
            # minus what the host can see is 1 to 4. The walks chart counts only
            # walk lines in the host's own messages, never a Take.
            {"name": "ideal_texts", "weeks": None}]


#: A line's "Helped {a} of {b}" is shown at once; this many answers are
#: enough to tell (coordinator's answer e, a placeholder the founder may change).
ENOUGH_TO_TELL = 30


def says(database: Any, host: str) -> list[dict]:
    """"What I say" (N648 item 4): each line of the walk as the walk's own
    reader gives it (``chat_replies.walk_view``, N647 items 6 and 7), with
    how many more answers are needed before its result can be told."""
    from services.chat_replies import walk_view
    out = []
    for line in walk_view(database, host).get("say") or []:
        b = (line.get("helped") or {}).get("b") or 0
        out.append({**line, "more_to_tell": max(0, ENOUGH_TO_TELL - b), "enough_at": ENOUGH_TO_TELL})
    return out


def chart_csv(chart: dict) -> str:
    """One chart as a CSV file: week, count ("fewer than 5" when hidden)."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    rows = chart.get("weeks") or []
    with_of = any("of" in r for r in rows) or chart.get("name") == "helped"
    w.writerow(["week", "count", "of"] if with_of else ["week", "count"])
    for row in rows:
        count = row["count"] if row["count"] is not None else f"fewer than {row.get('fewer_than', SMALLEST_WEEK)}"
        w.writerow([row["week"], count, row.get("of", "")] if with_of else [row["week"], count])
    return buf.getvalue()


# ── The routes' work ────────────────────────────────────────────────────────
def _host_recipe(database: Any, user_id: Any) -> tuple[str, dict]:
    from services.chat_recipes import mine
    host = str(user_id)
    recipe = mine(database, host)
    if not recipe:
        raise _not_found()
    return host, recipe


def read(database: Any, user_id: Any, now: Optional[datetime] = None) -> dict:
    """GET /v2/chats/setup/dev: the host's numbers."""
    host, recipe = _host_recipe(database, user_id)
    return {"close": close(), "notice": notice(database, host, recipe), "says": says(database, host),
            "charts": charts(database, host, now)}


def chart_file(database: Any, user_id: Any, name: str, now: Optional[datetime] = None) -> str:
    host, _recipe = _host_recipe(database, user_id)
    if name not in CHARTS:
        raise _not_found()
    chart = next(c for c in charts(database, host, now) if c["name"] == name)
    if chart["weeks"] is None:
        raise ChatsError("UNAVAILABLE", "Not counted right now.", 503)
    return chart_csv(chart)
