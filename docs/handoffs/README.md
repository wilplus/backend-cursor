# Handoffs — dated messages between the two repos (backend copy)

These files are conversation, not reference: each is a point-in-time handoff,
answer or debug note written for the other repo's maintainer. They were moved
here from `docs/` on 2026-09-14 (audit Q-A10) so that `docs/` itself carries
the living documents. Nothing in `routes/`, `services/` or the tests reads any
file in this directory.

Deliberately **not** moved:

- `docs/HANDOFF.md` — the system-level maintainer index, referenced from `AGENTS.md`.
- `docs/BE-HANDOFF-analysis-state-push.md` — still the live push contract; `services/realtime_notify.py`, `services/db.py` and `test_analysis_state_broadcast.py` cite it by path.
- `docs/CLAUDE-HANDOFF-CONFIDENT-MOMENT-*.md` — listed by path in the reviewed-file checksum manifest `docs/MLC3-CONFIDENT-MOMENT-POINT7-BACKEND-SHA256.txt`; moving them would break the freeze.

| File | First committed | Title |
|---|---|---|
| [`BE-ANSWER-legacy-credits-2026-08-01.md`](BE-ANSWER-legacy-credits-2026-08-01.md) | 2026-08-01 | BE → FE: the legacy credits are settled. The balance has two halves now. |
| [`BE-ANSWER-plan-checkout-2026-07-31.md`](BE-ANSWER-plan-checkout-2026-07-31.md) | 2026-07-31 | BE → FE: the plans are sellable. Answers, and two bugs you did not ask about. |
| [`BE-ANSWER-stress-lane-deletion-2026-08-03.md`](BE-ANSWER-stress-lane-deletion-2026-08-03.md) | 2026-08-03 | BE answer — stress lane deleted, peer-review validation loop wired |
| [`BE-HANDOFF-ideal-text-add-rearrange.md`](BE-HANDOFF-ideal-text-add-rearrange.md) | 2026-07-28 | BE → FE handoff — add & rearrange text in the ideal-text area while recording (T1 · 1.2) |
| [`BE-HANDOFF-ideal-text-slide-linkage.md`](BE-HANDOFF-ideal-text-slide-linkage.md) | 2026-08-03 | BE → FE handoff — slide linkage on the ideal-text GET (answers FE PR #222) |
| [`BE-HANDOFF-tab-session1-completion-gate.md`](BE-HANDOFF-tab-session1-completion-gate.md) | 2026-06-04 | BE handoff — Session-1 completion gate (≥1 charisma + ≥1 stress + ≥60s) |
| [`BE-HANDOFF-tab1-comment-sink-split.md`](BE-HANDOFF-tab1-comment-sink-split.md) | 2026-06-04 | BE handoff — split the comment sinks (user-visible vs. pipeline-only) |
| [`BE-HANDOFF-tab1-edit-gate.md`](BE-HANDOFF-tab1-edit-gate.md) | 2026-06-04 | BE handoff — Tab 1: >5-word-change save gate (anti-lazy-admin) |
| [`BE-HANDOFF-tab1-snippet-rerank.md`](BE-HANDOFF-tab1-snippet-rerank.md) | 2026-06-04 | BE handoff — Admin Tab 1: snippet list re-rank + transcript hiding |
| [`BE-HANDOFF-tab3-private-admin-notes.md`](BE-HANDOFF-tab3-private-admin-notes.md) | 2026-06-04 | BE handoff — Admin Tab 3: private admin notes panel |
| [`BE-HANDOFF-task7-signup-cta-human-at-heart.md`](BE-HANDOFF-task7-signup-cta-human-at-heart.md) | 2026-06-04 | BE handoff — Task 7: "4h human-at-heart" CTA + post-signup confirmation |
| [`BE-HANDOFF-task8-sharing-consent-modal.md`](BE-HANDOFF-task8-sharing-consent-modal.md) | 2026-06-04 | BE handoff — Task 8: data-sharing consent modal at session 2 |
| [`BE-HANDOFF-task9-files-tab-ui.md`](BE-HANDOFF-task9-files-tab-ui.md) | 2026-06-04 | BE handoff — Task 9: admin Tab 4 (Files) Next.js page |
| [`DEBUG-HANDOFF-2026-08-10.md`](DEBUG-HANDOFF-2026-08-10.md) | 2026-08-10 | DEBUG HANDOFF — 2026-08-10 evening session |
| [`FE-HANDOFF-2026-07-27-backlog-wave.md`](FE-HANDOFF-2026-07-27-backlog-wave.md) | 2026-07-27 | FE handoff — the backlog wave (2026-07-27) |
| [`FE-HANDOFF-2026-07-31-life-panel-doc-dock.md`](FE-HANDOFF-2026-07-31-life-panel-doc-dock.md) | 2026-07-31 | FE handoff — the Life Panel document dock, answered (2026-07-31) |
| [`FE-HANDOFF-2026-08-03-bff-and-upload-defenses.md`](FE-HANDOFF-2026-08-03-bff-and-upload-defenses.md) | 2026-08-03 | FE handoff — one BFF idiom + lab upload defenses (2026-08-03) |
| [`FE-HANDOFF-2026-08-03-life-period-reviews.md`](FE-HANDOFF-2026-08-03-life-period-reviews.md) | 2026-08-03 | FE handoff — the monthly + quarterly reviews (piece 5, 2026-08-03) |
| [`FE-HANDOFF-2026-08-03-variant-picker.md`](FE-HANDOFF-2026-08-03-variant-picker.md) | 2026-08-03 | FE handoff — the block variant PICKER, revisions & restore (2026-08-03) |
| [`FE-HANDOFF-2026-08-03-wins-derive.md`](FE-HANDOFF-2026-08-03-wins-derive.md) | 2026-08-03 | FE handoff — wins → proposed principles (piece 6, 2026-08-03) |
| [`FE-HANDOFF-2026-08-04-step2-peer-review.md`](FE-HANDOFF-2026-08-04-step2-peer-review.md) | 2026-08-04 | FE handoff — coaching chat STEP 2 becomes the peer-review flag |
