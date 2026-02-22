# How to bring back steps 2–4 (metric questions, recording 2, post-questions)

Steps 2–4 were **fully removed** from the homework flow. Current flow is: **start → recording 1 → report** only.

To **restore** the full flow (metric questions → final task → recording 2 → post-questions → report), use one of the options below.

---

## Option A: Restore from git history (recommended)

1. Find the last commit **before** steps 2–4 were removed:
   ```bash
   git log --oneline routes/homework.py
   ```
2. Restore `routes/homework.py` from that commit:
   ```bash
   git show <commit_hash>:routes/homework.py > routes/homework.py
   ```
   Or use `git checkout <commit_hash> -- routes/homework.py` and then re-apply any later changes you want to keep (e.g. other fixes).

3. If you only want to re-add the removed routes and logic (and keep other edits since then), use the backup doc (Option B) and paste the code back manually.

---

## Option B: Restore from the backup doc

1. Open **`docs/TEMPORARY-REMOVED-STEPS-2-3-4-BACKUP.md`** in this repo. It describes what was removed and in what order.
2. Re-add in `routes/homework.py`:
   - The constant **`DEFAULT_FINAL_TASK_WHEN_SKIP_METRICS`**
   - The helper **`_build_task_block_for_session`** (before `_storage_path_for_session`)
   - In **recording-upload-url**: allow `recording` `"1"` and `"2"`; for rec `"1"` when status is `task_block`, return 200 with `task_block` from `_build_task_block_for_session`; for rec `"2"` require status `final_task_ready`
   - Helpers **`_is_recording_1_ready`** and **`_recording_1_processing_failed`**
   - In **recording-1**: after `enqueue_recording_1_job`, restore the branches: no focus tasks → `completing_from_recording_1`; else skip_metric_questions → `final_task_ready` with default task; else return `task_block`. Restore idempotency to return `task_block` when not “skip” mode. Restore storing `session_metric_question_1/2/3` when updating session.
   - Route **GET** `/session/<id>/task-block`
   - Route **POST** `/session/<id>/metric-answers`
   - Route **POST** `/session/<id>/recording-2`
   - Helper **`_complete_homework_session`**
   - Route **GET** `/session/<id>/questions`
   - Route **POST** `/session/<id>/post-answers`
3. Re-add the imports that were removed: `openai_service`, `v2_flow_service` (`select_focus_task_for_performance_score_1`), `metrics_v2` (`compute_performance_score_1`, `compute_metrics_v2`), `count_fillers`, `compute_wpm` from `utils.metrics`.

---

## After restoring

- Update the module docstring at the top of **`routes/homework.py`** to describe the full flow again (warm_up → recording_1 → task block + metric answers → recording_2 → questions → report).
- Update **`.cursor/rules/architecture-taskmaster.mdc`**: remove or adjust the “TEMPORARY: Steps 2–4 are fully removed” note so the documented flow matches the code.
- You can keep or remove **`docs/TEMPORARY-REMOVED-STEPS-2-3-4-BACKUP.md`** and **`docs/BRING_IT_BACK.md`** once the full flow is restored and stable.
