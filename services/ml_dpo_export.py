"""
Build OpenAI preference/DPO JSONL examples from admin_annotation_events.

Format per line:
{
  "input": { "messages": [...] },
  "preferred_output": [{ "role": "assistant", "content": "..." }],
  "non_preferred_output": [{ "role": "assistant", "content": "..." }]
}
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any, Optional

from services.ml_finetuning_export import (
    build_session_blurb,
    fetch_events_for_export,
    fetch_sessions_map,
    get_system_prompt_for_field,
)
from services.ml_surface_contracts import (
    contract_for_surface,
    fields_for_surface,
    surface_for_annotation_field,
)


def parse_csv_set(raw: str | None) -> set[str] | None:
    if not raw:
        return None
    out = {x.strip() for x in raw.split(",") if x.strip()}
    return out or None


def _similarity(a: str, b: str) -> float:
    if not a and not b:
        return 1.0
    return SequenceMatcher(a=a, b=b).ratio()


def _stable_bucket(value: str, modulo: int = 10000) -> int:
    h = hashlib.sha256(value.encode("utf-8")).hexdigest()
    return int(h[:8], 16) % modulo


def _build_user_prompt(row: dict[str, Any], session: dict[str, Any] | None) -> str:
    field = str(row.get("field_name") or "").strip()
    section = str(row.get("section_type") or "").strip()
    parts: list[str] = []
    blurb = build_session_blurb(session)
    if blurb:
        parts.append(blurb)
    parts.append(f"Task type: {field or 'unknown'} (section: {section or 'unknown'})")
    reason_chip = str(row.get("reason_chip") or "").strip()
    if reason_chip:
        parts.append(f"Coach reason tag: {reason_chip}")
    custom_reason = str(row.get("custom_reason") or "").strip()
    if custom_reason:
        parts.append(f"Coach note: {custom_reason}")
    parts.append(
        "Write the best final coach response for this task type. "
        "Be specific, concise, and aligned with coach style."
    )
    return "\n\n".join(parts)


@dataclass
class DpoFilterConfig:
    surface: str
    min_preferred_chars: int = 20
    min_non_preferred_chars: int = 20
    max_similarity: float = 0.985
    require_reason_chip: bool = False
    reason_chips: set[str] | None = None

    def __post_init__(self) -> None:
        # Normalize aliases once. Every row handled by this config must belong
        # to this one surface; mixed-task preference files are forbidden.
        self.surface = contract_for_surface(self.surface).id


@dataclass
class DpoExportStats:
    scanned: int = 0
    kept: int = 0
    skipped: int = 0
    skipped_by_reason: dict[str, int] = field(default_factory=dict)

    def skip(self, reason: str) -> None:
        self.skipped += 1
        self.skipped_by_reason[reason] = self.skipped_by_reason.get(reason, 0) + 1


def row_to_dpo_example(
    row: dict[str, Any],
    *,
    session: dict[str, Any] | None,
    cfg: DpoFilterConfig,
) -> tuple[Optional[dict[str, Any]], Optional[str]]:
    field = str(row.get("field_name") or "").strip()
    if surface_for_annotation_field(field) != cfg.surface:
        return None, "surface_filtered_out"

    reason_chip = str(row.get("reason_chip") or "").strip()
    if cfg.reason_chips is not None and reason_chip not in cfg.reason_chips:
        return None, "reason_filtered_out"
    if cfg.require_reason_chip and not reason_chip:
        return None, "missing_reason_chip"

    preferred = str(row.get("coach_final_text") or "").strip()
    non_preferred = str(row.get("ai_original_text") or "").strip()

    if not preferred:
        return None, "missing_preferred_text"
    if not non_preferred:
        return None, "missing_non_preferred_text"
    if len(preferred) < cfg.min_preferred_chars:
        return None, "preferred_too_short"
    if len(non_preferred) < cfg.min_non_preferred_chars:
        return None, "non_preferred_too_short"

    sim = _similarity(preferred, non_preferred)
    if sim >= cfg.max_similarity:
        return None, "too_similar"

    user_prompt = _build_user_prompt(row, session)
    system_prompt = get_system_prompt_for_field(field)
    example = {
        "input": {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]
        },
        "preferred_output": [{"role": "assistant", "content": preferred}],
        "non_preferred_output": [{"role": "assistant", "content": non_preferred}],
    }
    return example, None


def split_train_val(
    examples: list[dict[str, Any]],
    *,
    val_ratio: float,
    seed_key: str = "_split_group",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    r = max(0.0, min(0.5, float(val_ratio)))
    if r <= 0:
        return examples, []
    threshold = int(r * 10000)
    train: list[dict[str, Any]] = []
    val: list[dict[str, Any]] = []
    for ex in examples:
        # The group is the owner, not the annotation event. Because projects
        # have one immutable owner, this simultaneously prevents the same user
        # and any of their projects from crossing train/validation.
        group = str(ex.get(seed_key) or "").strip()
        if not group:
            raise ValueError(
                "DPO example is missing its owner split group; refusing a "
                "leaky event-level split"
            )
        bucket = _stable_bucket(group, 10000)
        if bucket < threshold:
            val.append(ex)
        else:
            train.append(ex)
    train_groups = {str(ex[seed_key]) for ex in train}
    val_groups = {str(ex[seed_key]) for ex in val}
    overlap = train_groups & val_groups
    if overlap:
        raise AssertionError("DPO split leaked owner groups across partitions")
    return train, val


def example_jsonl_line(example: dict[str, Any]) -> str:
    return json.dumps(example, ensure_ascii=False)


def build_dpo_examples(
    client,
    *,
    limit: int,
    since_iso: str | None,
    cfg: DpoFilterConfig,
    enrich_sessions: bool,
) -> tuple[list[dict[str, Any]], DpoExportStats]:
    rows = fetch_events_for_export(
        client,
        limit=limit,
        since_iso=since_iso,
        field_names=fields_for_surface(cfg.surface),
    )
    sessions: dict[str, dict[str, Any]] = {}
    if enrich_sessions:
        session_ids = [str(r.get("session_id") or "") for r in rows]
        sessions = fetch_sessions_map(client, session_ids)

    stats = DpoExportStats(scanned=len(rows))
    out: list[dict[str, Any]] = []
    for row in rows:
        sid = str(row.get("session_id") or "").strip() or None
        sess = sessions.get(sid) if sid else None
        ex, reason = row_to_dpo_example(row, session=sess, cfg=cfg)
        if ex is None:
            stats.skip(reason or "skipped")
            continue
        owner = str(row.get("user_id") or "").strip()
        if not owner:
            stats.skip("missing_owner_split_group")
            continue
        # Internal export metadata is removed before OpenAI upload. The owner
        # id is needed only to make the split safe; it never enters JSONL.
        ex["_surface"] = cfg.surface
        ex["_split_group"] = f"user:{owner}"
        ex["event_id"] = str(row.get("id") or "")
        out.append(ex)
        stats.kept += 1
    return out, stats
