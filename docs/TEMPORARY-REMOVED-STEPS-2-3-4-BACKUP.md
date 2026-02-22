# TEMPORARY: Removed steps 2–4 code (full delete)

Steps 2 (metric questions), 3 (final task + recording 2), and 4 (post-questions) were **fully removed** from the homework flow. Current flow: **start → recording 1 → report**.

To **restore** the full flow, re-apply the code below into `routes/homework.py` in the order given, and revert the recording-1 and recording-upload-url logic to use the branches that return `task_block` / `final_task_ready` / `post_questions`.

---

## 1. Constants (add after STATUS_COMPLETING_FROM_RECORDING_1)

```python
# Default final task when admin enables skip_metric_questions (student goes straight to recording 2)
DEFAULT_FINAL_TASK_WHEN_SKIP_METRICS = "Do your best on your next recording. Focus on clear pacing and minimal fillers."
```

---

## 2. Helper _build_task_block_for_session (insert before _storage_path_for_session)

```python
def _build_task_block_for_session(session: dict, session_id: str, user_id: str):
    """Build task_block dict for a session in task_block status. Returns None if not task_block or questions missing."""
    if session.get("status") != STATUS_TASK_BLOCK:
        return None
    q1 = (session.get("session_metric_question_1") or "").strip()
    q2 = (session.get("session_metric_question_2") or "").strip()
    q3 = (session.get("session_metric_question_3") or "").strip()
    if not (q1 and q2 and q3):
        prefs = db.v2_get_user_metric_questions(user_id)
        q1 = (q1 or prefs.get("metric_question_1") or "").strip()
        q2 = (q2 or prefs.get("metric_question_2") or "").strip()
        q3 = (q3 or prefs.get("metric_question_3") or "").strip()
        if not (q1 and q2 and q3):
            return None
        db.v2_update_session(session_id, user_id, {
            "session_metric_question_1": q1,
            "session_metric_question_2": q2,
            "session_metric_question_3": q3,
        })
    return {
        "metric_question_1": {"id": None, "position": 1, "text": q1},
        "metric_question_2": {"id": None, "position": 2, "text": q2},
        "metric_question_3": {"id": None, "position": 3, "text": q3},
    }
```

---

## 3. recording-upload-url: allow recording "2" and task_block idempotency

In `homework_recording_upload_url`, use:

- `if recording not in ("1", "2"):` for the input check.
- For rec "1": if status != WARM_UP, then if status == TASK_BLOCK return 200 with task_block from _build_task_block_for_session; else 409.
- For rec "2": if status != FINAL_TASK_READY → 409.
- Then return storage_path and bucket.

(See git history for exact diff.)

---

## 4. Helpers _is_recording_1_ready and _recording_1_processing_failed (insert before homework_submit_recording_1)

```python
def _is_recording_1_ready(session: dict) -> bool:
    """True iff session is task_block and recording-1 job has set performance_score_1 and context_short (ready for metric-answers)."""
    if session.get("status") != STATUS_TASK_BLOCK:
        return False
    if session.get("performance_score_1") is None:
        return False
    if not (session.get("context_short") or "").strip():
        return False
    return True


def _recording_1_processing_failed(session: dict) -> bool:
    """True iff recording-1 processing explicitly failed."""
    return session.get("recording_1_processing_status") == "failed"
```

---

## 5. recording-1: restore branches after enqueue_recording_1_job

After `enqueue_recording_1_job(...)` keep the initial update to STATUS_TASK_BLOCK and session_metric_question_1/2/3. Then:

- If no focus_tasks → set STATUS_COMPLETING_FROM_RECORDING_1, return report_generating.
- Else if overrides.skip_metric_questions → set STATUS_FINAL_TASK_READY, final_task_text = DEFAULT_FINAL_TASK_WHEN_SKIP_METRICS, return final_task_ready.
- Else return 200 with status task_block and task_block.

Idempotency (same storage_path re-POST): if not “temporarily skip”, return task_block and recording_id etc.; else (when steps 2–4 removed) return report_generating.

(See git history for exact code.)

---

## 6. GET /session/<id>/task-block (full route)

Restore the route and handler `homework_get_task_block` (lines 381–434 in original file). See git history.

---

## 7. POST /session/<id>/metric-answers (full route)

Restore the route and handler `homework_submit_metric_answers` (lines 741–849 in original file). See git history.

---

## 8. POST /session/<id>/recording-2 (full route)

Restore the route and handler `homework_submit_recording_2` (lines 853–929 in original file). See git history.

---

## 9. _complete_homework_session (helper)

Restore the full function `_complete_homework_session` used by recording-2 (skip_post_questions) and post-answers (lines 931–1183 in original file). See git history.

---

## 10. GET /session/<id>/questions (full route)

Restore the route and handler `homework_get_questions` (lines 1187–1205 in original file). See git history.

---

## 11. POST /session/<id>/post-answers (full route)

Restore the route and handler `homework_submit_post_answers` (lines 1208–1294 in original file). See git history.

---

**Restore from git:** `git show <commit_before_removal>:routes/homework.py` to get the full file, then re-apply only the “simplified” recording-1 and upload-url logic if you want to keep other changes.
