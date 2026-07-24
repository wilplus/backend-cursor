"""dev-tasks — GPT-4o-authored, user-story-centered backlog for dev.willpowerlab.com.

A bug saved in dev-bugs is turned by GPT-4o into ONE user-story-centered task
(leads with the user-journey fragment it unlocks), classified Theme → Epic →
Story and slotted into a single prioritized list — highest on top.

Stability (the load-bearing property): the list is sorted by `order_key` and is
NEVER whole-list re-ranked. Theme rank is fixed (T1>T2>T3>T4); an epic's/story's
rank is FROZEN the first time it appears (reused by later tasks in the same
epic/story), so same-epic tasks always group together and the order can't churn
as tasks amass. A manual drag sets `pinned=true` + a midpoint `order_key` that
survives future GPT-4o runs.

Ranking direction comes from the founder's "Product Delivery Master" doc (ten
phases; Legal/GDPR + Data/measurement are the non-shortcut-able ones) plus the
T1–T4 backlog — distilled into the prompt below.

Pure planning fns (`plan_insert`, `plan_reorder`) hold the logic and are unit
tested without a DB; thin wrappers do the Supabase I/O via the shared client.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from config import Config
from services.db import db

logger = logging.getLogger(__name__)
config = Config()

_TABLE = "dev_tasks"
_THEME_RANK = {"T1": 1, "T2": 2, "T3": 3, "T4": 4}
_DEFAULT_THEME_RANK = 5           # unknown/none theme sorts last
_BUCKET = 1000.0                  # width of a (theme,epic,story,priority) slot; also the priority gap

# Distilled ranking reference (backlog themes/epics + the delivery-phase direction).
_REFERENCE = """THEMES (fixed priority order, T1 highest):
T1 — People get fast human feedback on how they speak, for ~$5
T2 — Build the model-ready annotation asset (1,000 coach annotations)
T3 — Automate the coach's judgment (shadow model)
T4 — Trust, compliance & reliability

EPICS: 1.1 versioning engine · 1.2 Ideal-Text & Recording UX · 1.3 Setup & Context Inputs ·
1.4 Onboarding · 1.5 Arc Validation · 2.1 Audio-only Annotation · 2.2 Annotation Schema ·
2.3 Coach Workflow · 2.4 Content Safety/Threat signal · 2.5 Context-Generation ·
3.1 Shadow Breakthrough Detection · 3.2 Progressive Shortening · 3.3 Simulation Depth ·
4.1 Legal & Consent (GDPR) · 4.2 Measurement & Instrumentation · 4.3 Release & Reliability

TEN DELIVERY PHASES (which stage of delivery a task belongs to):
1 Strategy/Discovery · 2 Design/UX · 3 Definition/Requirements · 4 Engineering ·
5 Quality/Testing · 6 Release/Ops · 7 Data/Measurement · 8 Go-to-Market · 9 Legal/Compliance · 10 Post-launch loop

DIRECTION (from the Product Delivery Master doc): the two phases that CANNOT be shortcut are
9 (Legal/GDPR — payments + EU voice data) and 7 (Data/measurement — you can't tell if it worked
without a few tracked events). Rank tasks touching those, and the F1 critical path (per-slide
transcript + best-per-slide ranking = T1/1.1/1.2), as most crucial within their theme."""

_SYSTEM = f"""You convert one raw developer bug/note into ONE user-story-centered task for a coding agent.
Lead with the user-journey fragment the task makes possible. Use this reference to classify and rank:

{_REFERENCE}

Return STRICT JSON only:
{{
  "theme": "T1"|"T2"|"T3"|"T4",
  "epic": "<one epic label from the list, e.g. '1.2 Ideal-Text & Recording UX'>",
  "user_story": "As a <role>, I want <journey fragment>, so that <payoff>",
  "body": "<the full, self-contained task a coding agent can execute: what to build + acceptance>",
  "priority": 1|2|3,               // 1 = do first
  "epic_rank": <int 1..50>,        // how crucial this epic is WITHIN its theme (1 = most crucial)
  "story_rank": <int 1..50>,       // how crucial this story is WITHIN its epic (1 = most crucial)
  "phase": <int 1..10>             // delivery phase
}}"""


# ─────────────────────────── pure planning (unit-tested, no DB) ───────────────────────────

def _clamp(v: Any, lo: int, hi: int, default: int) -> int:
    try:
        return max(lo, min(hi, int(v)))
    except (TypeError, ValueError):
        return default


def sort_key(t: dict) -> tuple:
    """Display order: order_key asc, then id asc (stable tiebreak)."""
    return (float(t.get("order_key") or 0.0), int(t.get("id") or 0))


def plan_insert(existing: list[dict], cls: dict) -> dict:
    """Compute {epic_rank, story_rank, order_key} for a new task.

    Freezes epic_rank/story_rank to the value an existing same-epic/same-story task
    already has (stability), else takes GPT-4o's. Slots the new task at the end of
    its (theme,epic,story,priority) bucket so existing tasks never move.
    """
    theme = cls.get("theme")
    epic = cls.get("epic")
    story = cls.get("user_story")
    trank = _THEME_RANK.get(theme, _DEFAULT_THEME_RANK)

    epic_rank = next(
        (t["epic_rank"] for t in existing if t.get("theme") == theme and t.get("epic") == epic),
        None,
    )
    if epic_rank is None:
        epic_rank = _clamp(cls.get("epic_rank"), 1, 900, 50)

    story_rank = next(
        (t["story_rank"] for t in existing
         if t.get("theme") == theme and t.get("epic") == epic and t.get("user_story") == story),
        None,
    )
    if story_rank is None:
        story_rank = _clamp(cls.get("story_rank"), 1, 900, 50)

    priority = _clamp(cls.get("priority"), 1, 3, 2)
    base = trank * 1e12 + epic_rank * 1e9 + story_rank * 1e6 + priority * _BUCKET
    in_bucket = [
        float(t["order_key"]) for t in existing
        if t.get("order_key") is not None and base <= float(t["order_key"]) < base + _BUCKET
    ]
    order_key = (max(in_bucket) + 1) if in_bucket else base
    return {"epic_rank": epic_rank, "story_rank": story_rank, "order_key": order_key}


def plan_reorder(active: list[dict], task_id: int, after_id: int | None) -> float:
    """New order_key to place `task_id` directly after `after_id` (or at the top if None)."""
    others = [t for t in sorted(active, key=sort_key) if int(t["id"]) != int(task_id)]
    if not others:
        return 0.0
    if after_id is None:
        return sort_key(others[0])[0] - 1.0
    idx = next((i for i, t in enumerate(others) if int(t["id"]) == int(after_id)), None)
    if idx is None:
        return sort_key(others[-1])[0] + 1.0
    a = sort_key(others[idx])[0]
    if idx + 1 < len(others):
        return (a + sort_key(others[idx + 1])[0]) / 2.0
    return a + 1.0


def to_markdown(tasks: list[dict]) -> str:
    """Whole active backlog → paste-ready markdown, in priority order."""
    lines = ["# WillpowerLab — backlog (user stories · tasks)\n"]
    for i, t in enumerate(sorted(tasks, key=sort_key), 1):
        p = f"P{t.get('priority', 2)}"
        tag = " · ".join(x for x in [t.get("theme"), t.get("epic")] if x)
        lines.append(f"## {i}. [{p}] {t.get('user_story') or '(task)'}")
        if tag:
            lines.append(f"_{tag}_")
        lines.append("")
        lines.append((t.get("body") or "").strip())
        lines.append("")
    return "\n".join(lines).strip() + "\n"


# ─────────────────────────── GPT-4o transform ───────────────────────────

def classify_bug(bug_text: str) -> dict | None:
    """GPT-4o → task classification dict, or None if OpenAI is unavailable/failed."""
    try:
        from services.openai_service import openai_service
        client = openai_service.client
    except Exception:
        client = None
    if not client:
        logger.info("dev_tasks: OpenAI client unavailable — skipping task generation")
        return None
    try:
        resp = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": bug_text.strip()[:4000]},
            ],
            response_format={"type": "json_object"},
            temperature=0.3,
            timeout=40,
        )
        raw = (resp.choices[0].message.content or "").strip()
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except Exception as e:  # noqa: BLE001
        logger.warning("dev_tasks: GPT-4o classify failed: %s", e)
        return None


# ─────────────────────────── DB wrappers ───────────────────────────

_COLS = "id,bug_id,body,user_story,theme,epic,phase,epic_rank,story_rank,priority,order_key,pinned,status,created_at,archived_at"


def _active_rows() -> list[dict]:
    res = db.client.table(_TABLE).select(_COLS).eq("status", "active").execute()
    return res.data or []


def generate_task_for_bug(bug: dict) -> dict | None:
    """Best-effort: bug → GPT-4o task → inserted row. Returns None on any failure
    (so saving a bug never breaks if OpenAI is down)."""
    text = (bug.get("text") or "").strip()
    if not text:
        return None
    cls = classify_bug(text)
    if not cls:
        return None
    plan = plan_insert(_active_rows(), cls)
    row = {
        "bug_id": bug.get("id"),
        "body": (cls.get("body") or text)[:8000],
        "user_story": cls.get("user_story"),
        "theme": cls.get("theme"),
        "epic": cls.get("epic"),
        "phase": _clamp(cls.get("phase"), 1, 10, 4) if cls.get("phase") is not None else None,
        "priority": _clamp(cls.get("priority"), 1, 3, 2),
        "epic_rank": plan["epic_rank"],
        "story_rank": plan["story_rank"],
        "order_key": plan["order_key"],
    }
    res = db.client.table(_TABLE).insert(row).execute()
    return res.data[0] if res.data else None


def list_tasks(view: str = "active") -> list[dict]:
    if view == "archive":
        res = db.client.table(_TABLE).select(_COLS).eq("status", "archived") \
            .order("archived_at", desc=True).execute()
        return res.data or []
    rows = _active_rows()
    return sorted(rows, key=sort_key)


def reorder_task(task_id: int, after_id: int | None) -> None:
    new_key = plan_reorder(_active_rows(), task_id, after_id)
    db.client.table(_TABLE).update({"order_key": new_key, "pinned": True}) \
        .eq("id", task_id).execute()


def update_task(task_id: int, fields: dict) -> dict | None:
    allowed = {k: v for k, v in fields.items() if k in ("body", "user_story", "priority")}
    if not allowed:
        return None
    res = db.client.table(_TABLE).update(allowed).eq("id", task_id).execute()
    return res.data[0] if res.data else None


def delete_task(task_id: int) -> None:
    db.client.table(_TABLE).delete().eq("id", task_id).execute()


def set_done(task_id: int) -> None:
    db.client.table(_TABLE).update({"status": "archived", "archived_at": "now()"}) \
        .eq("id", task_id).execute()


def restore_task(task_id: int) -> None:
    """Un-archive: recompute a fresh order_key so it slots back by priority (un-pinned)."""
    res = db.client.table(_TABLE).select(_COLS).eq("id", task_id).execute()
    row = res.data[0] if res.data else None
    if not row:
        return
    plan = plan_insert(_active_rows(), {
        "theme": row.get("theme"), "epic": row.get("epic"),
        "user_story": row.get("user_story"), "priority": row.get("priority"),
        "epic_rank": row.get("epic_rank"), "story_rank": row.get("story_rank"),
    })
    db.client.table(_TABLE).update({
        "status": "active", "archived_at": None, "pinned": False,
        "order_key": plan["order_key"],
    }).eq("id", task_id).execute()


def export_markdown() -> str:
    return to_markdown(_active_rows())
