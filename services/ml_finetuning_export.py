"""
Build OpenAI Chat fine-tuning JSONL examples from admin_annotation_events.

Each row becomes one line:
  {"messages":[{"role":"system",...},{"role":"user",...},{"role":"assistant",...}]}

Plaintext is required for training — handle exports under your privacy policy;
do not commit generated files to git.
"""
from __future__ import annotations

import json
from typing import Any, Optional

# Tune these to match your product voice; OpenAI fine-tuning uses system + user + assistant.
_DEFAULT_SYSTEM = (
    "You are an expert communication coach assistant. "
    "Write concise, encouraging, specific copy for students. "
    "Match the lead coach's tone and avoid generic filler."
)

_FIELD_SYSTEM_PROMPTS: dict[str, str] = {
    "email_draft": _DEFAULT_SYSTEM + " Focus: homework / assignment email to the student.",
    "email_message": _DEFAULT_SYSTEM + " Focus: homework / assignment email to the student.",
    "task_draft": _DEFAULT_SYSTEM + " Focus: a single clear homework task instruction.",
    "task_text": _DEFAULT_SYSTEM + " Focus: a single clear homework task instruction.",
    "script_draft": _DEFAULT_SYSTEM + " Focus: a short coach video script or talking points.",
    "video_script": _DEFAULT_SYSTEM + " Focus: a short coach video script or talking points.",
    "report_comment": _DEFAULT_SYSTEM + " Focus: written feedback on the student's report.",
    "report_grade": _DEFAULT_SYSTEM + " Focus: a fair numeric or letter grade with brief justification if needed.",
    "corrected_insight": _DEFAULT_SYSTEM + " Focus: coaching insight about the student's performance.",
    "coach_insight": _DEFAULT_SYSTEM + " Focus: coaching insight about the student's performance.",
    "coach_override_score": _DEFAULT_SYSTEM + " Focus: explaining or adjusting a performance score.",
    "coach_override_justification": _DEFAULT_SYSTEM + " Focus: justifying a coach override of model scoring.",
}


def _system_for_field(field_name: str | None) -> str:
    key = (field_name or "").strip()
    return _FIELD_SYSTEM_PROMPTS.get(key, _DEFAULT_SYSTEM)


def _session_blurb(session: dict[str, Any] | None) -> str:
    if not session:
        return ""
    bits: list[str] = []
    cs = (session.get("context_short") or "").strip()
    if cs:
        bits.append(f"Session summary: {cs}")
    st = session.get("status")
    if st:
        bits.append(f"Session status: {st}")
    sc = session.get("score_for_display")
    if sc is not None:
        bits.append(f"Score (display): {sc}")
    return "\n".join(bits) if bits else ""


def get_system_prompt_for_field(field_name: str | None) -> str:
    """Public accessor for shared export utilities."""
    return _system_for_field(field_name)


def build_session_blurb(session: dict[str, Any] | None) -> str:
    """Public accessor for shared export utilities."""
    return _session_blurb(session)


def event_to_openai_messages(
    row: dict[str, Any],
    *,
    session: dict[str, Any] | None = None,
) -> Optional[dict[str, Any]]:
    """
    One fine-tuning example, or None if the row should be skipped.
    """
    coach = (row.get("coach_final_text") or "").strip()
    if not coach:
        return None

    ai_draft = (row.get("ai_original_text") or "").strip()
    field = row.get("field_name")
    section = row.get("section_type")

    user_parts: list[str] = []
    blurb = _session_blurb(session)
    if blurb:
        user_parts.append(blurb)
    user_parts.append(f"Annotation: field={field!s} section={section!s}")
    rid = row.get("id")
    if rid:
        user_parts.append(f"event_id={rid}")
    if row.get("reason_chip"):
        user_parts.append(f"Coach reason tag: {row.get('reason_chip')}")
    if row.get("custom_reason"):
        cr = str(row.get("custom_reason")).strip()
        if cr:
            user_parts.append(f"Coach note: {cr}")
    if ai_draft:
        user_parts.append(f"AI draft to improve on:\n{ai_draft}")
    else:
        user_parts.append("AI draft was empty or missing; produce the coach-quality output from context only.")

    user_content = "\n\n".join(user_parts)

    return {
        "messages": [
            {"role": "system", "content": _system_for_field(str(field) if field else None)},
            {"role": "user", "content": user_content},
            {"role": "assistant", "content": coach},
        ]
    }


def example_to_jsonl_line(example: dict[str, Any]) -> str:
    return json.dumps(example, ensure_ascii=False)


def fetch_events_for_export(
    client,
    *,
    limit: int = 10_000,
    since_iso: str | None = None,
    field_names: set[str] | None = None,
) -> list[dict[str, Any]]:
    q = (
        client.table("admin_annotation_events")
        .select("*")
        .order("created_at", desc=False)
        .limit(min(max(1, limit), 50_000))
    )
    if since_iso:
        q = q.gt("created_at", since_iso)
    rows = q.execute().data or []
    if field_names:
        rows = [r for r in rows if str(r.get("field_name") or "") in field_names]
    return rows


def fetch_sessions_map(client, session_ids: list[str]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    ids = [s for s in {str(x) for x in session_ids if x} if s]
    for i in range(0, len(ids), 50):
        batch = ids[i : i + 50]
        res = (
            client.table("v2_sessions")
            .select("id, context_short, status, score_for_display")
            .in_("id", batch)
            .execute()
        )
        for row in res.data or []:
            sid = str(row.get("id") or "")
            if sid:
                out[sid] = row
    return out
