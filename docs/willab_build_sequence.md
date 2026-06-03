# willab — Unified Build Sequence
**The merge of the two clearing maps.** Consumes `docs/willab_clearing_map_fe.md` (FE: what exists) + `docs/willab_clearing_map_be.md` (BE: what exists) + the contract (`docs/willab_be_contract_v0.3.md`) into one **dependency-ordered** plan both agents pull from.

**How to read:** each item is tagged **[BE]**, **[FE]**, or **[FE+BE]** (a handshake), with **depends-on** and **status**. Build top-to-bottom; items in the same phase with no shared dep run in parallel across the two repos. **Cross-repo handshakes** (§ at the end) are the meeting points that must be coordinated — those are where out-of-order building breaks.

**Status legend:** ✅ done · 🟢 unblocked (build now) · 🟡 gated (needs a decision below) · ⛔ blocked (depends on an unfinished item).

---

## Gating decisions (resolve to unblock the 🟡 items)
| # | Decision | Blocks | Status |
|---|---|---|---|
| D1 | **Homework REPLACE/COEXIST + keep-or-drop realtime-scoring & assigned-curriculum** | the retirement list (Phase 5 BE) + whether realtime/curriculum become willab builds | 🔴 OPEN — awaiting product call |
| D2 | **§7.1 label schema** (direction-v1 vs 28-scenario) | `labels` store + the coach-authoring *training lane* (Phase 3 BE) | 🔴 OPEN — Science/design |
| D3 | §7.4 idempotency key | send-gate | ✅ resolved = `recording_id` |
| D4 | §7.9 lounge batch ceiling + RLS | lounge merge hardening | ✅ resolved (MAX_BATCH=200 + RLS shipped) |
| D5 | profile home (`v2_speaker_profiles` vs `user_settings`) | profile build | 🟢 leaning `v2_speaker_profiles`; BE to confirm it's not homework-written |

---

## Phase 0 — Foundations (parallel, no cross-deps)
| Item | Own | Depends | Status |
|---|---|---|---|
| `lounge_messages` store + endpoints | BE | — | ✅ `0033bfa` (migration ran) |
| Lounge localStorage + merge-on-signup glue | FE | BE lounge endpoints | 🟢 unblocked (BE live) |
| `profile` (domain enum + goal) + `session_context` (add `domain_vocabulary`) | BE | D5 | 🟢 unblocked (D5 is a confirm, not a blocker) |
| Welcome / consent screen | FE | — | 🟢 unblocked |
| Min-content gate relocation (strip contrast, keep ≥60s + has-speech) | BE | — | 🟢 unblocked |
| **Readout pipeline: 6 missing features + real VAD/pause segmentation** | BE | — | 🟢 unblocked — **START NOW, it's the long pole** |

## Phase 1 — Lab capture path
| Item | Own | Depends | Status |
|---|---|---|---|
| DomainChips + Intake surface | FE | Phase 0 BE `profile` endpoint | ⛔→🟢 when profile lands |
| Lab overlay shell + `session_context` form | FE | Phase 0 BE `session_context` + min-content gate | ⛔→🟢 |
| Readout payload shape (upload→processing→snippets w/ 10 features) | BE | Phase 0 Readout features + segmentation | ⛔ on the long pole |

## Phase 2 — Readout + Lounge home
| Item | Own | Depends | Status |
|---|---|---|---|
| Readout card (per-snippet, reuse SnippetPlayer) | FE | Phase 1 BE Readout payload | ⛔ |
| Lounge-as-home restructure (phase-machine inversion) | FE | Phase 0 lounge glue | 🟢 can start (big FE) |
| Warm-opener relocate (dad-joke → optional Lounge first-touch) | FE | Lounge home | ⛔→🟢 |

## Phase 3 — Review + publish + Insights
| Item | Own | Depends | Status |
|---|---|---|---|
| Publish pivot — add `insights_payload` + re-point signals → status region | BE | reuse `/v2/internal/publish-session-results` | 🟢 (insights half) |
| Publish pivot — fire training-annotation event + `labels` store | BE | D2 | 🟡 gated |
| Coach authoring surface (insights assembly + label UI) | FE+BE | publish pivot; D2 for the label lane | 🟡 partial |
| Status region (linear single-active) | FE | BE publish re-point | ⛔→🟢 |
| Insights view (annotated Readout) | FE | BE publish carrying `insights_payload` | ⛔ |

## Phase 4 — Send-gate + library
| Item | Own | Depends | Status |
|---|---|---|---|
| Send-gate: idempotency (`recording_id`) + merge-then-send + offline queue | BE | recording state machine | 🟢 (D3 resolved) |
| Send-gate glue (park→OAuth→merge-then-send) | FE | BE send-gate | ⛔ |
| `strong_sides_library` + ingest-on-read + bot library context | BE | publish/Insights | ⛔ |
| Lounge bot library wiring + librarian guardrail | FE+BE | library store | ⛔ |

## Phase 5 — Deletions (ONLY after replacements are live)
| Item | Own | Depends | Status |
|---|---|---|---|
| 🔴 AC-9 fix — kill `freemium_tease.kpi_score` (rides with funnel deletion) | BE | funnel cutover | 🟡 (do early if funnel lingers) |
| Strip contrast gate · delete contextual-next-question · icebreaker→DORMANT · remove user-facing KPI/charisma_profile | BE | replacements live | ⛔ sequence-after |
| Delete AcousticMetricsBubble · user-labeling · retire `reviewing` phase | FE | replacements live | ⛔ sequence-after |
| Homework retirement list (route-by-route) | FE+BE | **D1** | 🔴 gated |

---

## Cross-repo handshakes (coordinate these — out-of-order = breakage)
1. **Readout payload (§3.3):** BE must publish the 10-feature snippet shape *before* FE builds the Readout card. **BE-first.**
2. **`profile` + `session_context` endpoints (§3.1/3.2):** BE-first; FE Intake + Lab form consume them.
3. **Publish re-point (§6a):** BE flips `results_published_at` + carries `insights_payload`; FE status region + Insights consume the signal. **BE-first.**
4. **Send-gate (§3.5/3.6):** BE owns merge-then-send ordering + idempotency; FE owns park-before-redirect. Agree the callback contract before either builds.
5. **Lounge (§3.15):** ✅ BE live; FE builds the glue now.

## The rule for staying shippable mid-migration (FE map §9.4)
Build the new surface → re-point shared signals → **only then** delete the old. Never delete a live surface (`/chat`, the public funnel, `reviewing`) before its willab replacement exists. Phase 5 is last for exactly this reason.

---
## Where this lives / how to use it
- This doc is in the **BE repo**; relay it to the FE agent (or mirror into the FE repo) so both pull from one order.
- **Next unblocked BE slice:** `profile` + `session_context` (Phase 0), then start the Readout-feature long pole.
- **Next unblocked FE slices:** Lounge localStorage+merge glue, Welcome/consent screen, the Lounge-as-home restructure.
- Re-merge this doc whenever either clearing map changes or a gating decision (D1/D2) resolves.
