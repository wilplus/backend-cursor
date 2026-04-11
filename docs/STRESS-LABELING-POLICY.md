# Stress Labeling Policy (Coach-Led)

## Roles
- Student records own homework audio.
- Coach/admin reviews snippets and applies labels.
- Model learns from coach labels to scale coach judgment.

## Label Rubric
- `stress`: audible tremor/instability, strained or pressured voice, recurrent tension markers.
- `no_stress`: stable phonation, controlled breath, no clear tremor pattern.
- `uncertain`: do not force a label; skip/defer clip.

## Labeling Rules
- Label options are binary: `stress` / `no_stress`.
- For `stress`, a short note is required (why this was marked stress).
- Each label stores coach attribution (`labeled_by_admin_id`, `labeled_by_admin_email`, `labeled_at`).

## Quality Control
- Weekly audit sample: 10% of recently labeled snippets.
- Track disagreement rate between primary labels and audit pass.
- If disagreement rate > 10%, recalibrate rubric with concrete examples before next batch.

## Training/Eval Guardrails
- Split by `user_id` (default) to prevent train/val leakage across a student.
- Optional stricter split by `session_id`.
- Target metrics on validation:
  - Recall (`stress`) >= 0.85
  - Precision (`stress`) >= 0.75
  - False-positive rate (`no_stress`) <= 0.30

