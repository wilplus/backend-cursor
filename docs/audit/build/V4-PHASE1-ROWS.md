# V4 Phase 1 · one row per pull request

Written 2026-10-07 (build plan D-ML-6). It splits `V4_BRIEF.md` Phase 1 and
the ledger rows B1.1 to BEXIT into pull-request-sized rows. Each row names
the tests that prove it. Every row serves nothing to a speaker: V4 is
measured dark beside V3 until the founder's switch (QG3 A, V22a B). Every
read stays inside the machine (AC-9), every input keeps its own provenance
(L3), every migration gets a GPT check before it merges, and nothing new
reaches a screen without the founder's signature.

| Row | What | Migration | Tests | Waits on |
|---|---|---|---|---|
| **B1.1a** | The dark frame logs every pick: each candidate V3 weighed, its chance of being picked (1 for V3's pick, 0 for the other eligible ones, none for an excluded one), the Take's seed and the policy version. Frame schema -v6; the service frame drops the log. | 0441 (writer accepts -v6 and checks the log) | `tests/test_v4_pick_logging.py`; `tests/test_the_shadow_writer_keeps_the_pick_log_postgres.py`; `tests/test_the_shadow_writer_accepts_the_frame_the_code_builds_postgres.py` (now 0431 then 0441) | GPT-0441 |
| **B1.1b** | Pick logging for every speaker (V1 A): `dark_enabled` drops the founder-only scope. One switch, no migration. Config first: `TAKE_FEEDBACK_POLICY_V3_MODE=dark` on every service that runs the Take pipeline. | none | `tests/test_take_feedback_policy_v3.py::test_dark_activation…` updated to every speaker | founder confirms the widening |
| **B1.2** | A seeded random 20% of moments per Take (V2 A all moments, V3 A round up), drawn from the B1.1 seed and stored apart from the machine's picks. | table for the random draws | unit: the same seed draws the same moments; 20% rounded up; PG: stored apart from picks | B1.1a |
| **B1.3** | willfidence-v1 (machine only), per moment: S, partial W from the four signed word signals, the four boxes and the judge spread; stamp "willfidence-v1-machine". Includes Take and speaker willfidence (QG8 A). | table for the reads | unit per signal against its signed definition; AC-9 probe (no route returns it) | founder signs S-B1 (the four definitions) |
| **B1.4** | Fast read on every practise try, p90 at most 5 s from Stop, never blocking (O5). | table for timings | unit: a late read is stored and treated as "not reached yet"; report of p90 | B1.3 |
| **B1.4b** | The reached bar from blind coach answers (V8 A, V9 A), placeholder 0.6, versioned. | none or a small versions table | unit: the bar where coaches say Yes about 7 in 10 | B1.3, B1.8/B1.9 answers |
| **B1.5** | Outcome per pick: did the picked paragraph's willfidence rise by the next Take, matched by paragraph identity (V10 B, V11 B, V12 A). | table for outcomes | unit: matched by paragraph id across rewording; PG | B1.3, D-ML-2 (merged) |
| **B1.6** | The V4 picker, dark beside V3: rank = importance × (1 − S·W) × sureness; importance from one batched role call per Take using the signed role list; V3's pick, logged, on a block V4 is very unsure of (V15 A, V15a A). | table for V4 picks | unit: rank order; fallback logged per block; coverage stays a target | founder approves S-B1b (roles), B1.3 |
| **B1.7** | Answer counts per clip as soft-label data; the label quorum stays humans only (Q3). | 0442 | PG: counts apart from the label ledger; MACHINE_VOTES=0 | GPT-0442 |
| **B1.8 / B1.9** | The two blind coach sheets: "Pick the moment for feedback" and "Which sounds surer" (V18 A, V19 A, V20 A; QG4 B, QG9 A). Backend queues, then the screens in the coach panel's look. | queues | BLIND COACH e2e; queue slices 40/40/20 hidden from the coach | founder signs S-B8 (prototype) |
| **BEXIT** | The exit-gate report (V21 A): V4 beats V3 on golden-set agreement and next-Take rise, coverage holds, practise read p90 ≤ 5 s, reached bar calibrated; falling back on 4 of 5 blocks fails it (V15a A). Then the founder's switch: a few speakers, then everyone (V22a B). | none | report fixture test | every row above |
