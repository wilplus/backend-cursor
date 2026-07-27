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

import base64
import io
import json
import logging
import re
import zipfile
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


def to_markdown(tasks: list[dict], image_names: dict | None = None) -> str:
    """Whole active backlog → paste-ready markdown, in priority order.

    `image_names` maps task id -> [relative path, ...] and is supplied by the ZIP
    export, where the screenshots ride along as real files: linking those beats an
    inline data: URI, which GitHub and most editors refuse to render and which
    inflates the text by ~4/3 of the image. Without the map the data: URI is
    embedded as before, so a plain .md still stands on its own.
    """
    lines = ["# WillpowerLab — backlog (user stories · tasks)\n"]
    for i, t in enumerate(sorted(tasks, key=sort_key), 1):
        p = f"P{t.get('priority', 2)}"
        tag = " · ".join(x for x in [t.get("theme"), t.get("epic")] if x)
        lines.append(f"## {i}. [{p}] {t.get('user_story') or '(task)'}")
        if tag:
            lines.append(f"_{tag}_")
        lines.append("")
        lines.append((t.get("body") or "").strip())
        # Embed the source bug's screenshots so the exported file is self-contained
        # (data: URIs render as images in markdown viewers).
        srcs = (image_names or {}).get(t.get("id")) if image_names else (t.get("images") or [])
        for j, src in enumerate(srcs or [], 1):
            if src:
                lines.append("")
                lines.append(f"![screenshot {j}]({src})")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


# ─────────────────────── export bundle (markdown + images) ───────────────────

_DATA_URL_RE = re.compile(r"^data:(?P<mime>[^;,]+)?(?:;base64)?,(?P<payload>.*)$", re.DOTALL)
_MIME_EXT = {"image/jpeg": "jpg", "image/jpg": "jpg", "image/png": "png",
             "image/gif": "gif", "image/webp": "webp"}


def _decode_data_url(url: str) -> tuple[bytes, str] | None:
    """(raw bytes, extension) for a data: URL, or None if it isn't one / won't decode."""
    if not url or not isinstance(url, str) or not url.startswith("data:"):
        return None
    m = _DATA_URL_RE.match(url)
    if not m:
        return None
    mime = (m.group("mime") or "image/jpeg").strip() or "image/jpeg"
    try:
        raw = base64.b64decode(m.group("payload"), validate=False)
    except Exception:  # noqa: BLE001
        return None
    if not raw:
        return None
    return raw, _MIME_EXT.get(mime, "jpg")


_PDF_MAX_W_MM = 100      # a phone screenshot stays readable, a page stays scannable
_PDF_MAX_H_MM = 95


def export_pdf(tasks: list[dict] | None = None) -> tuple[bytes, str, str]:
    """The active backlog as a PDF with each screenshot under its own task.

    A PDF is the one format where the images are guaranteed to travel: a rich-text
    paste drops data: URI images in many targets (they arrive as empty boxes), and
    a .md with data: URIs renders in almost nothing. Here they're embedded.

    reportlab is imported lazily and a missing/failed import degrades to the ZIP
    rather than taking Export down.
    """
    rows = hydrate_images(_active_rows()) if tasks is None else tasks
    ordered = sorted(rows, key=sort_key)
    try:
        payload = _render_pdf(ordered)
    except Exception:  # noqa: BLE001
        logger.warning("dev_tasks: PDF render failed, falling back to the ZIP export",
                       exc_info=True)
        return export_bundle(ordered)
    return payload, "application/pdf", "willpowerlab-backlog.pdf"


def _render_pdf(ordered: list[dict]) -> bytes:
    from xml.sax.saxutils import escape

    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.lib.utils import ImageReader
    from reportlab.platypus import (Image, KeepTogether, Paragraph,
                                    SimpleDocTemplate, Spacer)

    margin = 16 * mm
    avail = A4[0] - 2 * margin
    max_w, max_h = min(avail, _PDF_MAX_W_MM * mm), _PDF_MAX_H_MM * mm

    ss = getSampleStyleSheet()
    st_title = ParagraphStyle("wl_title", parent=ss["Title"], fontSize=18,
                              spaceAfter=10, alignment=0)
    st_story = ParagraphStyle("wl_story", parent=ss["Heading2"], fontSize=13,
                              spaceBefore=14, spaceAfter=2, textColor="#111214")
    st_tag = ParagraphStyle("wl_tag", parent=ss["Italic"], fontSize=9,
                            textColor="#6b7280", spaceAfter=6)
    st_body = ParagraphStyle("wl_body", parent=ss["BodyText"], fontSize=10.5, leading=15)
    st_cap = ParagraphStyle("wl_cap", parent=ss["BodyText"], fontSize=8,
                            textColor="#9aa0aa", spaceBefore=2, spaceAfter=10)

    flow: list[Any] = [Paragraph("WillpowerLab — backlog (user stories · tasks)", st_title)]
    for i, t in enumerate(ordered, 1):
        flow.append(Paragraph(
            f"{i}. [P{t.get('priority', 2)}] {escape(t.get('user_story') or '(task)')}",
            st_story))
        tag = " · ".join(x for x in [t.get("theme"), t.get("epic")] if x)
        if tag:
            flow.append(Paragraph(escape(tag), st_tag))
        body = escape((t.get("body") or "").strip()).replace("\n", "<br/>")
        if body:
            flow.append(Paragraph(body, st_body))
        n = 0
        for url in t.get("images") or []:
            decoded = _decode_data_url(url)
            if not decoded:
                continue                      # http(s) or unreadable: nothing to embed
            n += 1
            raw = decoded[0]
            try:
                iw, ih = ImageReader(io.BytesIO(raw)).getSize()
            except Exception:  # noqa: BLE001
                logger.warning("dev_tasks: unreadable image on task %s, skipped", t.get("id"))
                continue
            scale = min(max_w / iw, max_h / ih, 1.0)     # never scale a small shot UP
            # the image and its caption must never split across a page
            flow.append(KeepTogether([
                Spacer(1, 6),
                Image(io.BytesIO(raw), width=iw * scale, height=ih * scale, hAlign="LEFT"),
                Paragraph(f"screenshot {n} · task #{t.get('id')}", st_cap),
            ]))

    buf = io.BytesIO()
    SimpleDocTemplate(
        buf, pagesize=A4, leftMargin=margin, rightMargin=margin,
        topMargin=margin, bottomMargin=margin,
        title="WillpowerLab — backlog", author="dev-bugs",
    ).build(flow)
    return buf.getvalue()


def export_bundle(tasks: list[dict] | None = None) -> tuple[bytes, str, str]:
    """The active backlog as a download: (payload, mimetype, filename).

    A ZIP (`backlog.md` + `images/task-<id>-<n>.<ext>`) once any task carries a
    screenshot, so the markdown links real files that open anywhere — a .md with
    megabytes of inline base64 renders in almost nothing and can't be opened as an
    image. With no decodable image it stays a plain .md (self-contained, with any
    data: URI still embedded by to_markdown).

    http(s)-hosted images are left as links rather than fetched: an export must not
    depend on network egress or a slow third party.
    """
    rows = hydrate_images(_active_rows()) if tasks is None else tasks
    ordered = sorted(rows, key=sort_key)

    names: dict[Any, list[str]] = {}
    files: list[tuple[str, bytes]] = []
    for t in ordered:
        # numbered over what actually made it in, so the file name and the
        # "screenshot N" label in the markdown always agree even when one of a
        # task's images is unreadable
        n = 0
        for url in t.get("images") or []:
            decoded = _decode_data_url(url)
            if decoded:
                raw, ext = decoded
                n += 1
                path = f"images/task-{t.get('id')}-{n}.{ext}"
                files.append((path, raw))
                names.setdefault(t.get("id"), []).append(path)
            elif isinstance(url, str) and url.startswith(("http://", "https://")):
                n += 1
                names.setdefault(t.get("id"), []).append(url)

    if not files:
        return to_markdown(ordered).encode("utf-8"), "text/markdown", "willpowerlab-backlog.md"

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("backlog.md", to_markdown(ordered, image_names=names))
        for path, raw in files:
            z.writestr(path, raw)          # already-compressed JPEG/PNG; ZIP just carries it
    return buf.getvalue(), "application/zip", "willpowerlab-backlog.zip"


# ─────────────────────────── GPT-4o transform ───────────────────────────

def _openai_client():
    try:
        from services.openai_service import openai_service
        return openai_service.client
    except Exception:
        return None


def classify_bug(bug_text: str) -> dict | None:
    """GPT-4o → task classification dict, or None if OpenAI is unavailable/failed."""
    client = _openai_client()
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

_COLS = "id,bug_id,body,user_story,theme,epic,phase,epic_rank,story_rank,priority,order_key,pinned,bump_reason,bumped_at,images,status,created_at,archived_at"


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
        "images": bug.get("images") or [],   # carry the bug's screenshots onto the task
    }
    res = db.client.table(_TABLE).insert(row).execute()
    inserted = res.data[0] if res.data else None
    if inserted:
        try:
            reevaluate(inserted)
        except Exception:  # noqa: BLE001
            logger.exception("dev_tasks: reeval failed")
    return inserted


# ─────────────────── Level-1 re-evaluation (flag-gated) ───────────────────
# When a NEW P1/P2 task arrives, bump UP the priority of a few RELATED existing
# tasks (the new task makes them more urgent). Bounded + safe: pins are never
# touched, only bumps (never demotes), capped per event, each stamped with a
# reason, and gated by DEV_TASKS_REEVAL_ENABLED (default off). Only `priority`
# changes — the frozen epic/story ranks stay put, so a moved task stays inside
# its own epic and the list can't churn wildly.

_REEVAL_SYSTEM = (
    "You maintain a solo founder's dev backlog. A NEW task just arrived. Given the "
    "existing tasks, return ONLY the ones the new task makes MORE urgent (a lower "
    "priority number = more urgent) because they're connected / blocking / a "
    "prerequisite. Be conservative — usually 0-2 items. NEVER lower urgency (never "
    'a higher number). JSON: {"changes":[{"id":<int>,"new_priority":1|2|3,"reason":"<one line>"}]}'
)


def _reeval_digest(tasks: list[dict], limit: int = 200) -> str:
    out = []
    for t in tasks[:limit]:
        label = (t.get("user_story") or t.get("body") or "").strip().replace("\n", " ")[:120]
        out.append(f'- id={t.get("id")} P{t.get("priority", 2)} [{t.get("theme")}/{t.get("epic")}] {label}')
    return "\n".join(out)


def _reeval_llm(new_task: dict, existing: list[dict]) -> list[dict]:
    client = _openai_client()
    if not client:
        return []
    new_label = (new_task.get("user_story") or new_task.get("body") or "").strip()[:400]
    user = (
        f'NEW TASK (P{new_task.get("priority")}) [{new_task.get("theme")}/{new_task.get("epic")}]: {new_label}'
        f"\n\nEXISTING TASKS:\n{_reeval_digest(existing)}"
    )
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": _REEVAL_SYSTEM}, {"role": "user", "content": user}],
            response_format={"type": "json_object"},
            temperature=0.2,
            timeout=40,
        )
        data = json.loads((resp.choices[0].message.content or "").strip())
        ch = data.get("changes")
        return ch if isinstance(ch, list) else []
    except Exception as e:  # noqa: BLE001
        logger.warning("dev_tasks: reeval LLM failed: %s", e)
        return []


def plan_bump(existing: list[dict], task: dict, new_priority: int) -> float:
    """order_key for `task` at `new_priority` — appends to the end of its new
    (theme,epic,story,priority) bucket, so it lands in the right priority slot
    within its own epic (epic/story ranks stay frozen)."""
    trank = _THEME_RANK.get(task.get("theme"), _DEFAULT_THEME_RANK)
    base = (trank * 1e12 + _clamp(task.get("epic_rank"), 1, 900, 50) * 1e9
            + _clamp(task.get("story_rank"), 1, 900, 50) * 1e6 + new_priority * _BUCKET)
    in_bucket = [
        float(t["order_key"]) for t in existing
        if t.get("id") != task.get("id") and t.get("order_key") is not None
        and base <= float(t["order_key"]) < base + _BUCKET
    ]
    return (max(in_bucket) + 1) if in_bucket else base


def reevaluate(new_task: dict) -> list[dict]:
    """Level-1 re-eval after a new task lands. Returns the applied bumps ([] if
    disabled / new task is low-priority / nothing related)."""
    if not getattr(config, "DEV_TASKS_REEVAL_ENABLED", False):
        return []
    if _clamp(new_task.get("priority"), 1, 3, 3) > 2:   # only a P1/P2 new task triggers a re-eval
        return []
    existing = [t for t in _active_rows() if t.get("id") != new_task.get("id")]
    if not existing:
        return []
    cap = _clamp(getattr(config, "DEV_TASKS_REEVAL_MAX_CHANGES", 3), 1, 20, 3)
    by_id = {t.get("id"): t for t in existing}
    applied = []
    for d in _reeval_llm(new_task, existing):
        if len(applied) >= cap:
            break
        t = by_id.get(d.get("id"))
        if not t or t.get("pinned"):            # never touch a manually-pinned task
            continue
        newp = _clamp(d.get("new_priority"), 1, 3, 0)
        cur = _clamp(t.get("priority"), 1, 3, 2)
        if newp < 1 or newp >= cur:             # bump UP only (lower = more urgent); ignore no-ops / demotions
            continue
        db.client.table(_TABLE).update({
            "priority": newp,
            "order_key": plan_bump(existing, t, newp),
            "bump_reason": (d.get("reason") or "")[:300],
            "bumped_at": "now()",
        }).eq("id", t.get("id")).eq("pinned", False).execute()
        applied.append({"id": t.get("id"), "from": cur, "to": newp})
    if applied:
        logger.info("dev_tasks reeval: bumped %d task(s) after new task %s", len(applied), new_task.get("id"))
    return applied


def hydrate_images(rows: list[dict]) -> list[dict]:
    """Fill an empty `images` array from the task's source bug, in memory.

    `dev_tasks.images` is only written at generation time, and the column landed
    after the tasks did (migrations/add_dev_tasks_images.sql, default '[]'), so
    older tasks are empty even though their bug still holds the screenshot. Rather
    than make the founder run a backfill before Copy/Export work, read repairs
    itself: one extra query, and only when some task is actually missing images.

    scripts/backfill_dev_task_images.py makes it permanent (after which this is a
    no-op). Failures here are swallowed — a missing screenshot must never take the
    task list down.
    """
    missing = [r for r in rows if not (r.get("images") or []) and r.get("bug_id")]
    if not missing:
        return rows
    try:
        res = (
            db.client.table("dev_bugs")
            .select("id,image_url,images")
            .in_("id", sorted({int(r["bug_id"]) for r in missing}))
            .execute()
        )
        from services.dev_bugs import _bug_images
        by_bug = {row["id"]: _bug_images(row) for row in (res.data or [])}
    except Exception:  # noqa: BLE001
        logger.warning("dev_tasks: could not hydrate task images from dev_bugs", exc_info=True)
        return rows
    for r in missing:
        imgs = by_bug.get(int(r["bug_id"])) or []
        if imgs:
            r["images"] = imgs
    return rows


def list_tasks(view: str = "active") -> list[dict]:
    if view == "archive":
        res = db.client.table(_TABLE).select(_COLS).eq("status", "archived") \
            .order("archived_at", desc=True).execute()
        return hydrate_images(res.data or [])
    rows = hydrate_images(_active_rows())
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
    """Plain-markdown export (no image files). Kept for callers that want text."""
    return to_markdown(_active_rows())
