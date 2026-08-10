# DEBUG HANDOFF — 2026-08-10 evening session

**Audience:** the comprehensive debugging + final-fixing session the founder is
launching. Read this before touching anything. It is the distilled state of a
full day of work: what shipped, what is verified, what is broken, what was
guessed wrong (so you do not repeat it), and the exact next diagnostics.

**The founder's framing, verbatim:** the product has moved from
charisma/stress/random-feedback to *engines tightly connected to the
interventions and the coach panel* — "it needs to be ripped off whatever is
left and build and reworked again." But every "this is dead" claim today
turned out to be partly wrong on inspection, so **map before ripping**.

---

## 1 · What is VERIFIED WORKING as of tonight

| thing | evidence |
|---|---|
| `charisma_snippets` → `snippets` rename, both services | boot probes on web+worker log `resolved to 'snippets' (SNIPPETS_TABLE env)` / `is readable`; take at 15:32 wrote 2 rows **through the queue** (worker-confirmed) |
| provenance Phase A (0257–0259) | seed hash matches (`205b3bd3…`), `label_revision` snapshot 9=9, boot check live, `dimension_evaluations` rows now stamped (`detector_version`,`provenance` visible in worker log INSERTs) |
| stress_snippets retired in place | no writer, no reader, rows frozen, 0261 comment applied (auto, via MIGRATE_ON_BOOT) |
| pipeline admin panel `/admin/pipeline` + `@require_admin` BE routes | Task IV merged both repos (#371, #254) |
| durable queue + worker | job 15:32 enqueued→completed→snippets written; boot sweep clean |
| migrations auto-apply in prod | `MIGRATE_ON_BOOT=1`; deploy log shows `[migrate] … nothing pending` — **merging a migration IS running it** (see CONFIG-FIRST rule, CLAUDE.md + docs/MIGRATIONS.md) |

Merged today: #363–#374 (backend), #252–#254 (frontend). All squash-merges.

---

## 2 · OPEN BUGS (numbered; work top-down)

### B1 — Star drought: `moment_suggestions` frozen since 2026-08-03 10:20

- 152 rows total, 0 since 2026-08-03 — the exact day #322 moved star
  generation from the web process into the worker (`services/analysis_worker.py`).
- Tonight's take: gate `if arc_id and recording_kind == "spoken"` **opened**
  (proven: the eager ideal-text assembly inside the same block ran and
  persisted v=3), `MOMENT_SUGGESTIONS_ENABLED` **is on in the worker**
  (proven: the assembly's `include_suggestion_anchors=_moment_suggestions_enabled()`
  GET to `moment_suggestions` fired). The generator ran and stored zero.
- #374 (merged, `c84cb83`) added an **unconditional funnel line**:
  `moment_suggestion: sid=… arc=… seen=N stored=N (no_text= capped= decided= no_gen= errored=) unstarred=N`
- ⚠️ **LOG SEARCH TRAP:** every generator line starts `moment_suggestion:`
  — **SINGULAR**. Searching `moment_suggestions` (plural, the table name)
  matches only REST URLs and **hides every generator line**. This is why the
  founder's post-redeploy search "found nothing changed."

**Next diagnostics (in order):**
1. Worker logs, search `moment_suggestion:` (singular, colon) around the last
   take → read the funnel numbers.
2. `SELECT kind, trigger, COUNT(*) FROM moment_suggestions GROUP BY 1,2 ORDER BY 3 DESC;`
   → attributes the 152 historical rows to lanes.
3. **Prime suspect:** `DELIVERY_STARS_ENABLED` / `STRUCTURAL_STARS_ENABLED`
   set on the *backend* Railway service but **not on the worker** (the reader
   moved processes on 2026-08-03 — same per-service split that broke
   `SNIPPETS_TABLE` twice today). The acoustic lane alone rarely fires on calm
   speech, so worker-missing delivery/structural flags would produce exactly
   `seen>0 stored=0` every take. Confirm against the funnel line + the GROUP BY
   before flipping anything.

### B2 — No accept/reject offers on the student ideal text

The approve/reject layer the founder expects IS the tracked-changes system
(`routes/v2/explore_ideal_text.py` `_tracked_changes_block` → seven lanes →
`services/intervention_candidates.select()` → manager-engine budget). Stars
(`moment_suggestions`) feed several lanes, so B1 starves it — but B1 may not
be the only cause. `POLISH_AS_SUGGESTIONS_ENABLED` **is on** (founder
confirmed), so polish diffs should offer even with zero stars. Determine why
the served `changes` list is empty: producer-dead vs manager-gate
(gamma_control 12% / withhold 20% can legitimately suppress) vs FE render
condition. The workflow map (§6) enumerates the exact conditions.

### B3 — FE flow: stale text after a take; loading only appears on NEXT record tap

Founder's required flow, verbatim intent: **record → loading → text. Every
take.** Today: after a take completes, the old text still shows; only when
tapping to record again does loading/transcription appear.
W4/W5 (`analysisPending` prop) + W6 merged today in FE #254 and the symptom
persists — so either the marker/resume-watch lifecycle misses the real path
(check: marker written where? cleared by `isLabOverlay(state)` effect while
the user is still in the Lab?), the overlay only refetches while OPEN, or the
deployed Vercel build predates #254. Map in §6; treat as top FE priority.

### B4 — "Random reassembly, no lock-in"

Reassembly after every take is by design (F1: re-rank + reassemble). What is
missing is the *visible* offer/lock layer (B1+B2) and possibly a stronger
lock-in interaction than today's typed-edit auto-lock (`ideal_text_parts`,
`locked_at`, composition/accentuation layers — all live since #363/#253).
This is a SPEC question, not (only) a bug — see §5 questions to the founder.
Do not "fix" assembly randomness by freezing ranking; that breaks F1/L2.

### B5 — Sweep-chain multiplication in the worker

16:43:31–35: **nine** `run_sweep_loop` jobs in 4 seconds, ~3 Supabase queries
each. The boot lease ("sweep chain already running elsewhere") prevents new
chains at boot but evidently not accumulation across deploys. Continuous query
burn. Fix sketch: per-fire lease/ownership, not boot-only. Map in §6.

### B6 — Two sessions' snippets unrecovered

`c5f3749d-9d26-4513-83c9-cece3a729a02`, `623db2f8-8e8e-4eed-8147-34dba72002d8`
lost their derived snippets in today's rename windows (jobs completed,
snippets=0). Re-cut was run but wrote nothing and returned no visible error.
Both sessions: `results_published_at` NULL. Diagnostic:

```sql
SELECT s.id, s.recording_1_id, r.storage_path, r.audio_url
  FROM public.v2_sessions s
  LEFT JOIN public.recordings r ON r.id = s.recording_1_id
 WHERE s.id IN ('c5f3749d-9d26-4513-83c9-cece3a729a02',
                '623db2f8-8e8e-4eed-8147-34dba72002d8');
```
`recording_1_id` NULL → nothing to re-cut from (genuinely unrecoverable).
Otherwise check backend log for `recut:` lines (fetch failure / 409 labels →
needs `?force=true`). Parent recordings themselves were never at risk.

### B7 — Coach panel rebuild (SPEC, awaiting founder answers in §5)

Founder's description: the **Lab** is ONE scrollable coach panel — star
review as the body, **confident voices folded into the top** (same card
design, not a separate panel), **YouTube/uploaded-video labeling** a separate
view in the same design language, and a **two-state toggle: live users vs
uploaded recordings**. Current FE pieces affected:
`CoachStarVerdictOverlay.tsx`, `ReviewGroupOverlay.tsx`,
`ConfidentVoicesShelf.tsx` (rendered from `LibraryOverlay`), `coachChrome.tsx`,
`/coach/corpus`. **Do not build this until B1/B2 are fixed** — the panel
currently renders "No stars fired on this arc" because the producer is dark,
and redesigning an empty container flatters the wrong problem.

---

## 3 · WRONG HYPOTHESES TODAY (do not repeat)

1. **"Worker flag `MOMENT_SUGGESTIONS_ENABLED` is off"** — disproved by the
   assembly's flag-gated anchors GET running in the same job.
2. **"`arc_id` missing from job payload"** — disproved by SQL (payload_arc
   present, `spoken`, take_idx sane).
3. **"`recording_kind` guard blocks it"** — disproved same query.
4. **"PostgREST schema cache was the rename blocker"** — real hazard, now
   fixed in 0260 (`NOTIFY pgrst` in-transaction), but the actual blocker was
   the unset env var + per-service split.
5. **"A student take writes `snippets` via the web path"** — it goes through
   the queue when async is on; and earlier, "no job ran for the 15:32 take"
   was a truncated-screenshot misread.
6. **"snippet loss caused the star drought"** — timeline refutes it (drought
   started 2026-08-03; snippet loss was today). Zero snippets *would* force
   zero stars, but tonight seen=3 → stored=0 with snippets present.

**Meta-lessons that kept paying:** observe, don't infer (the boot probes and
the funnel line each settled in seconds what hypothesis-chains got wrong);
Railway env is PER-SERVICE (three separate incidents today); text-matching
fences trip on their own explanatory prose (multiple times this repo); log
search terms must match the emitted string, not the table name.

---

## 4 · Standing constraints that bind the debugging session

- **CONFIG-FIRST RULE** (new today, CLAUDE.md): `MIGRATE_ON_BOOT=1` in prod —
  merging a migration runs it at next container start. Env-dependent
  migrations: set the var on EVERY service first.
- Fences: AC-9 (no user-facing scores), CONSTRUCT, BLIND COACH, LIVE LOOP
  (user-facing copy needs founder sign-off). L1/L2/L3 locked choices.
- Never auto-drop tables/columns. Gate-routed PRs, squash-merge.
- Do NOT blanket-enable the off-by-default flags. Each has an exit condition
  in `docs/OPS-FLAGS-AND-RELEASES.md`; several gate FE-dependent behavior
  (`INSTANT_IDEAL_TEXT_ENABLED` needs FE variant handling; deploy order BE →
  FE → flip). Flip only what a diagnosis names, one at a time, and set it on
  the service whose PROCESS reads it.

---

## 5 · OPEN QUESTIONS FOR THE FOUNDER (the E2E spec)

> **✅ ANSWERED 2026-08-10, all seven — the authoritative spec is
> [`docs/SPEC-lockin-loop-and-coach-panel.md`](SPEC-lockin-loop-and-coach-panel.md)
> ("exact product spec, do not deviate").** Headlines: strictly blocking
> loading screen; three lock triggers (edit / accept / explicit "Lock it"),
> Accept-chip → "Lock it" button flow; locked text takes NOTHING except a
> confident-voice "better version pending…" prompt (narrows the R1
> accentuation allowance); Confident Voice renders as a Star, other feedback
> underline/bold, styling driven by the interventions ops table; budget = 3
> per recording (= BUDGET_CEILING); live "you are here" anchoring display
> during recording (F1-CORE adjacent); coach Lab panel two states — live =
> full loop, uploaded = confident-voice recognition only, blind
> triangulation; restore-first, then rebuild panels.
>
> **B1's root cause is CONFIRMED AND FIXED by the founder:** the star flags
> were disabled on the worker service; now enabled. Verification sequence:
> spec §7. The questions below are retained only as the record of what was
> asked.

1. **Student loop:** after a recording stops — is the screen a *blocking*
   "working on your take" state (old text inaccessible) until the new text is
   ready, which then opens/replaces automatically? Or may the student browse
   the old text during analysis with a visible "updating…" state?
2. **Lock-in:** what locks a paragraph? (a) typing an edit (today's
   auto-lock), (b) accepting a suggestion on it, (c) an explicit per-paragraph
   lock control, (d) a dedicated post-take review screen where the student
   accepts/rejects each change BEFORE the new text replaces the old. If (d):
   what does one row of that screen show (old vs new, reason line, play
   button?).
3. **What needs approval:** only text edits (polish/wording), or ALSO the
   ranking swaps — when take 3's version of a paragraph outranks take 2's, is
   the swap automatic (pure F1) with only edits gated, or does the swap itself
   need accept? (This decides how deep accept/reject cuts into F1 assembly —
   founder-level because it touches L1/L2 semantics.)
4. **Offer sources & look:** offers come from the engine lanes under the
   Appendix-H budget (already built). Should they render as inline
   accept/reject chips in the text (replace/insert = composition) plus
   advice/bold accents (delivery/structural = accentuation)? Does the old
   grey-star overlay UI survive anywhere, or is chips-in-text the only
   surface?
5. **Coach Lab panel:** confirm §B7's structure, the fate of each existing
   panel (fold vs retire: ReviewGroupOverlay, ConfidentVoicesShelf,
   CoachStarVerdictOverlay, /coach/corpus), and that the two states are
   exactly "live users" / "uploaded recordings" everywhere (including the
   YouTube labeling view).
6. **Restore vs rewire:** fix the existing star pipeline first so offers flow
   again (config-level, likely small), THEN rebuild panels on live data —or—
   skip restoration and rebuild offers straight from the engines?
   (Recommendation: restore first; the engine lanes consume the same tables,
   so restoration is on the critical path either way.)
7. **Definition of done:** the exact demo that closes this: e.g. "record take
   2 → loading → new text opens with N accept/reject chips → accept one →
   paragraph locks → coach opens Lab → star review populated → labels one."

---

## 6 · Verified system maps

A five-agent verification sweep (flags-by-process, star funnel, offers
pipeline, FE flow, sweep chain) ran against both repos tonight; its findings
are appended below this line when complete. Trust the maps over memory.

### 6.1 · Flag inventory, by PROCESS (the per-service trap, mapped)

# Feature-flag inventory — backend-cursor (traced 2026-08-10)

Process legend: **web** = app.py → routes/* (gunicorn); **worker** = worker.py → services.pipeline_jobs → services.analysis_worker → services.lab_recording → … (RQ service). The full take pipeline (`services/analysis_worker.run_full_analysis`) executes in **three modes**: sync in-request (web), daemon thread (web, `ASYNC_ANALYSIS_ENABLED`), and queue (worker, `services/pipeline_jobs.py:262,307`) — so every pipeline-side flag is **both**, and the worker copy of the variable is load-bearing whenever `PIPELINE_QUEUE_ENABLED=1`. The three cron Dockerfiles (annotation/devbugs/life-reminders) are curl pokes into web webhooks — they execute no Python, so no flag classifies as "cron".

| flag | default | readers (file:line) | process | notes |
|---|---|---|---|---|
| `SNIPPETS_TABLE` | `charisma_snippets` | services/snippet_tables.py:76 (sole env read; :101 logs source) — constant then imported by services/db.py:12, services/session_concatenation.py:61, services/directive_suggestions.py:38, routes/v2/admin.py:34, routes/v2/user_chat.py:33, scripts/* (corpus_base_rates:42, backfill_few_shot_annotations:58, backfill_snippet_transcripts:32, backfill_snippet_wpm_fillers:32, phase_a0_diagnostics:39, smoke_rlhf_capture:51) | **both** (+ every ops script) | Resolved once at import in EVERY process that imports services.db. Boot probes: app.py:57 (web), worker.py:74-78 (worker — added after today's incident). Must be set on web AND worker AND any script env. |
| `PIPELINE_QUEUE_ENABLED` | `0` | services/job_queue.py:53 (via `_flag`, job_queue.py:35-36); callers routes/v2/common.py:143-144 (web dispatch), app.py:306 (web boot sweep), services/pipeline_jobs.py:116 (worker re-enqueue/sweep) | **both** | Worker boot error text (worker.py:175) confirms the worker service needs it set. |
| `ASYNC_ANALYSIS_ENABLED` | `0` | routes/v2/common.py:129; used routes/v2/lab_recording.py:864,875 (imported :36, routes/v2_routes.py:52) | **web** | Chooses daemon-vs-sync dispatch only; setting it on the worker does nothing. |
| `MOMENT_SUGGESTIONS_ENABLED` | `0` | routes/v2/arcs.py:774 (serve path), services/analysis_worker.py:41 (generate path, used :224,:263) | **both** | Duplicated reader by design (analysis_worker.py:38-40). Web-only set = generated nothing on queued takes; worker-only set = generates but web serve path treats it off. |
| `MOMENT_SUGGESTIONS_MAX_PER_TAKE` | `8` (int) | config.py:182-183; consumed services/moment_suggestions.py:253 | **both** (pipeline) | Config attr evaluated at import in both processes; consumer is pipeline-side. |
| `MOMENT_REPLACE_STICKINESS_MAX_PCT` | `15` (int) | config.py:179-180; consumed services/moment_suggestions.py:258 | **both** (pipeline) | Star-tuning; same worker exposure as the star flags. |
| `DELIVERY_STARS_ENABLED` | `0` | services/moment_suggestions.py:191 (used :202, inside `generate_for_session`, only caller services/analysis_worker.py:227-229) | **both** (pipeline) | **This is the suspected silent-off case**: with queue mode on, the WORKER generates delivery stars — flag set only on web = permanently off, no error. |
| `DELIVERY_STAR_Z` | `1.2` (float) | config.py:188; consumed services/moment_suggestions.py:209 | **both** (pipeline) | |
| `DELIVERY_STARS_MAX_PER_TAKE` | `3` (int) | config.py:189; consumed services/moment_suggestions.py:208 | **both** (pipeline) | |
| `STRUCTURAL_STARS_ENABLED` | `0` | services/moment_suggestions.py:149 (used :159) | **both** (pipeline) | Same exposure as delivery stars. |
| `STRUCTURAL_STARS_MAX_PER_TAKE` | `3` (int) | config.py:193-194; consumed services/moment_suggestions.py:163 | **both** (pipeline) | |
| `DELIVERY_ALIGNMENT_ENABLED` | `0` | services/delivery_alignment.py:73; gated call services/moment_suggestions.py:450-453 | **both** (pipeline) | Runs inside star generation → worker under queue mode. |
| `POLISH_AS_SUGGESTIONS_ENABLED` | `0` | services/ideal_text_block.py:48 (used :285,:440); web read routes/v2/explore_ideal_text.py:115,176 | **both** | Assembly (worker) + serve (web). |
| `LIVING_TRANSCRIPT_ENABLED` | `0` (**ON in prod per ops doc**) | services/ideal_text_block.py:188 (helper `_living_transcript_enabled`); worker via maybe_assemble_ideal_text (analysis_worker.py:218,260) and ideal_text_block.py:403,413; web via routes/v2/arcs.py:189-191, routes/v2/user_sessions.py:1766-1767, routes/v2/explore_ideal_text.py:128,155,880-881,947-951,1007-1011,1196-1198,1451-1452 | **both** | If the prod "ON" lives only on the web service, worker-assembled documents use the legacy source while web serves living-transcript — silent split-brain. |
| `MASTER_DOCUMENT_ENABLED` | `0` | services/master_document.py:54; worker: services/analysis_worker.py:249-253; web: routes/v2/user_sessions.py:1773-1776, routes/v2/explore_ideal_text.py:117,128,948-951,1009-1011,1197-1198,1289-1290,1461-1465,1910-1913 | **both** | Worker writes skeleton/upgrade offers; web serves/decides blocks. Needs both services. |
| `TAKE_ALIGNMENT_ENABLED` | `0` | services/take_alignment.py:62; called from services/master_document.py:394 (`process_new_take`) | **both** (pipeline) | Effectively worker-side under queue mode. |
| `BLOCK_VARIANTS_ENABLED` | `0` | services/ideal_text_variants.py:64 (`variants_enabled`); only caller routes/v2/explore_ideal_text.py:1008-1011 | **web** | READ gate only — variant writes "dual-run" ungated in the worker (ideal_text_variants.py:60-63), so web-only set is correct by design. |
| `INSTANT_IDEAL_TEXT_ENABLED` | `0` | routes/v2/explore_ideal_text.py:95 | **web** | |
| `COACH_PREFILL_ENABLED` | `0` | services/lab_recording.py:246 (used :1099,:1437) | **both** (pipeline) | Prefill drafts built during take processing → worker under queue mode. |
| `PIECES_CANONICAL_ENABLED` | `1` | services/lab_recording.py:236 (used :498) | **both** (pipeline) | Kill-switch: an explicit `0` must reach the worker to take effect. |
| `SENTENCE_BOUNDARY_SPLIT_ENABLED` | `1` | services/slide_word_split.py:565 | **both** | Cutter used by pipeline (lab_recording.py:347,363,458,474,499,1020,1061,1615,1670) and web (routes/v2/user_sessions.py:593,1363). |
| `SLIDE_PAUSE_SNAP_ENABLED` | off (`""`) | services/slide_word_split.py:36 | **both** | F1 two-clocks mitigation; NOT in OPS-FLAGS doc. Flipping it web-only would snap boundaries differently per execution mode — direct F1 segmentation divergence. |
| `VOICE_CONFIDENCE_ENABLED` | `1` | services/voice_confidence.py:283 (`enabled`); called services/lab_recording.py:615-619 | **both** (pipeline) | Compute+persist at record time. |
| `VOICE_CONFIDENCE_SEX_INFERENCE_ENABLED` | `1` | services/voice_confidence.py:293 (used :325) | **both** (pipeline) | Via resolve_take_sex in pipeline + scripts/backfill_voice_confidence.py. |
| `VOICE_CONFIDENCE_RANKING_ENABLED` | `0` | services/voice_confidence.py:275 (`ranking_enabled`, used :659 in `rank_term`; cache key best_presentation.py:528-529) | **both** | rank_term fires in web reads (routes/v2/arcs.py:257,318; coach.py:1813) AND worker compose (ideal_text_block.py:268,376; arc_notifications.py:100 from analysis_worker). A future flip must hit both or ranking diverges by process. |
| `TOKEN_PRICING_ENABLED` | `0` | services/token_account.py:109 (`enabled`, the live reader); config.py:535 (attr — **no consumer found, vestigial**) | **both** | Web: routes/token_routes.py:42, routes/v2/arcs.py:646-648,1272, routes/v2/coaching.py:1452, services/tier_checkout.py:118,196, stripe_subscription_tiers.py:137. **Worker: services/lab_recording.py:432-436 — the per-take band charge settles inside the pipeline.** Web-only flip = takes never charged under queue mode, silently. |
| `LLM_USAGE_ENABLED` | `1` | services/llm_usage.py:74 | **both** | Recorders called from web chat (master_doc_rag.py:942,1115,1309; life_engine.py:253; baseline_summary.py:125) and pipeline (openai_service.py:369, snippet_transcription.py:111, snippet_drafts.py:152, coach_comment_drafter.py:107, stickiness.py:226, llm.py:169). Kill-switch must reach both. |
| `MANAGER_CONTROLS_ENABLED` | `1` | services/intervention_candidates.py:187 (only caller: routes/v2/explore_ideal_text.py:1454 `select`) | **web** | The three randomisation arms run on the polled explore surface. Set on web; worker copy unnecessary today. |
| `LOUNGE_ROUTER_ENABLED` | ON (off only on explicit `0/false/no/off`) | services/master_doc_rag.py:869 | **web** | Lounge intent router; **absent from OPS-FLAGS-AND-RELEASES.md** (violates its own "when you add a flag" rule). |
| `RATE_LIMIT_ENABLED` | `1` (rate_limits.py:96 `_flag` default) | services/rate_limits.py:363,398 | **web** | Flask limiter only. Not in ops doc. |
| `LIFE_PANEL_ENABLED` | `0` | config.py:469; consumers routes/v2/coaching.py:1476,1642, services/life_chat.py:82, routes/life_routes.py (gate), routes/life_reminders_webhook.py:51, scripts/generate_life_daily_cards.py:57 | **web** (+ manual script) | Life-reminders "cron" is a curl poke at the web webhook, so web-service var is the effective one. |
| `GUEST_FUNNEL_ENABLED` | `false` | config.py:651; consumers routes/v2/funnel.py:56,276; direct os.environ echo routes/v2/publish.py:89 | **web** | |
| `AUDIT_SURFACE_ENABLED` | `false` | config.py:657; consumer routes/v2/coaching.py:1540 | **web** | |
| `COMMUNITY_CONTENT_ENABLED` | `1` | config.py:427; consumer routes/journal.py:426 | **web** | |
| `JOURNAL_IMAGE_ENABLED` | `1` | config.py:437; consumer services/journal_image.py:148 | **web** | |
| `DEV_TASKS_ENABLED` | `false` | config.py:584; consumer routes/dev_bugs.py:92 | **web** | devbugs cron is a curl poke at web. |
| `DEV_TASKS_REEVAL_ENABLED` | `false` | config.py:590; consumer services/dev_tasks.py:483 (route-invoked) | **web** | |
| `LONGITUDINAL_FIRST_QUESTION_ENABLED` | `true` | config.py:335-338; consumer routes/v2/user_chat.py:454 | **web** | |
| `BASELINE_SUMMARY_ENABLED` | `true` | config.py:353-356; consumers routes/v2/user_chat.py:474,588 | **web** | |
| `LEARNER_PROFILE_INJECTION_ENABLED` | off (`""`) | config.py:315-318 — **no code consumer found** (only docstring routes/v2/coaching.py:386) | **dead** | Defined, never consulted. |
| `LEARNER_MIRROR_ENABLED` | off (`""`) | config.py:365-368 — **no code consumer found** | **dead** | Docstring claims it gates /v2/user/mirror; no gate exists in routes. |
| `COPILOT_VIDEO_PIPELINE_ENABLED` | `false` | config.py:620 — **no code consumer found** (retrain webhook gates on COPILOT_VIDEO_RETRAIN_SECRET instead, routes/internal_webhooks.py:307) | **dead** | |
| `DIAGNOSE_SESSION_STATE_ENABLED` | `false` | config.py:645 — **no code consumer found** | **dead** | |
| INTERVENTION/EXPLORATION constants | — | **NOT env-read.** Hardcoded in services/manager_engine.py: `EXPLORATION_RATE=0.10` (:129), `GAMMA_CONTROL=0.12` (:148), `INTERVENTION_RANDOMISATION=0.20` (:149), salts :154-156 | n/a | Only env control over the experiment is `MANAGER_CONTROLS_ENABLED` (web). Changing rates requires a deploy, not Railway config — the audit premise that these are env constants is false. |

## OPS-FLAGS-AND-RELEASES.md discrepancies (item 3)

The doc's framing — "a flip is a config change... scoped to one environment" — treats each flag as ONE switch; only the `SNIPPETS_TABLE` section says "every service — web **and** worker." Flags whose actual reader process contradicts that single-flip implication:

1. **Star lane (`MOMENT_SUGGESTIONS_ENABLED`, `POLISH_AS_SUGGESTIONS_ENABLED`, `DELIVERY_STARS_ENABLED`, `STRUCTURAL_STARS_ENABLED`)** — doc's OFF table implies one flip; generation runs in the WORKER under queue mode, serving runs in web. Web-only set = stars silently never generated (the exact suspected star-flag failure); worker-only set = generated but not served.
2. **`LIVING_TRANSCRIPT_ENABLED` "already ON in prod"** — reader is both-process; if prod's ON is web-service-only, worker assemblies use the legacy document source. Verify the worker service's env now.
3. **`MASTER_DOCUMENT_ENABLED`** — worker writes the skeleton/upgrade offers (analysis_worker.py:249-253); doc doesn't say to set it on the worker.
4. **`TOKEN_PRICING_ENABLED`** — the per-take charge settles inside the pipeline (lab_recording.py:432); a web-only flip runs the token UI while queued takes are never charged.
5. **`VOICE_CONFIDENCE_RANKING_ENABLED`** ("off by decision") and the ON-table kill-switches (`LLM_USAGE`, `PIECES_CANONICAL`, `SENTENCE_BOUNDARY_SPLIT`, `VOICE_CONFIDENCE`, `VOICE_CONFIDENCE_SEX_INFERENCE`) — all read in the worker; an explicit `0` (or future `1`) applied to one service produces per-process divergence in an F1 surface.
6. **`DELIVERY_ALIGNMENT_ENABLED`, `TAKE_ALIGNMENT_ENABLED`, `COACH_PREFILL_ENABLED`** — listed with no service qualifier; all pipeline-side (worker).
7. **Absent from the doc entirely**: `LOUNGE_ROUTER_ENABLED`, `SLIDE_PAUSE_SNAP_ENABLED`, `RATE_LIMIT_ENABLED`, `MOMENT_SUGGESTIONS_MAX_PER_TAKE` + star-tuning constants, and all config.py product flags (`LIFE_PANEL_ENABLED` etc.) — violating the doc's own "when you add a flag" rule. The four dead config.py flags should be deleted or documented.
8. Correct as implied (no mismatch): `ASYNC_ANALYSIS_ENABLED` (web), `INSTANT_IDEAL_TEXT_ENABLED` (web), `BLOCK_VARIANTS_ENABLED` (web read-gate; worker writes deliberately ungated), `MANAGER_CONTROLS_ENABLED` (web), `SNIPPETS_TABLE` (doc already corrected to per-service).

## WORKER-READ FLAGS

Every variable below is read in the worker process (worker.py → pipeline_jobs → analysis_worker → lab_recording/ideal_text_block/master_document/moment_suggestions/voice_confidence/token_account/llm_usage) and MUST be set on the worker Railway service to take effect there:

- `SNIPPETS_TABLE`
- `PIPELINE_QUEUE_ENABLED`
- `MOMENT_SUGGESTIONS_ENABLED`
- `MOMENT_SUGGESTIONS_MAX_PER_TAKE`
- `MOMENT_REPLACE_STICKINESS_MAX_PCT`
- `DELIVERY_STARS_ENABLED`, `DELIVERY_STAR_Z`, `DELIVERY_STARS_MAX_PER_TAKE`
- `STRUCTURAL_STARS_ENABLED`, `STRUCTURAL_STARS_MAX_PER_TAKE`
- `DELIVERY_ALIGNMENT_ENABLED`
- `POLISH_AS_SUGGESTIONS_ENABLED`
- `LIVING_TRANSCRIPT_ENABLED`
- `MASTER_DOCUMENT_ENABLED`
- `TAKE_ALIGNMENT_ENABLED`
- `COACH_PREFILL_ENABLED`
- `PIECES_CANONICAL_ENABLED`
- `SENTENCE_BOUNDARY_SPLIT_ENABLED`
- `SLIDE_PAUSE_SNAP_ENABLED`
- `VOICE_CONFIDENCE_ENABLED`
- `VOICE_CONFIDENCE_SEX_INFERENCE_ENABLED`
- `VOICE_CONFIDENCE_RANKING_ENABLED`
- `TOKEN_PRICING_ENABLED`
- `LLM_USAGE_ENABLED`

(Also worker-required infrastructure vars per worker.py:157-163,175: `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `OPENAI_API_KEY`, `REDIS_URL`, plus `WORKER_COUNT`, `PIPELINE_QUEUE_NAME`, `PIPELINE_JOB_TIMEOUT_SECONDS` if customized — any of these differing between services changes worker behavior silently.)

### 6.2 · Star funnel — every way generate_for_session stores zero

# Decision map — `services/moment_suggestions.py::generate_for_session`

**Entry preconditions (before any snippet is considered)**
- Caller gate: `services/analysis_worker.py:224` — `_moment_suggestions_enabled()` (`analysis_worker.py:37-42`) reads env `MOMENT_SUGGESTIONS_ENABLED`, default `"0"` = OFF. If off, `generate_for_session` is never called.
- `moment_suggestions.py:241-242` — falsy `session_id` or `arc_id` → return 0.
- Module import itself can fail: `moment_suggestions.py:31-32` imports the prompt registry (`services/prompts/moment_suggestions.py`, extracted **2026-08-03** — same date the rows stopped). An import error there aborts the whole call and is swallowed at `analysis_worker.py:231-235` as `"lab: moment suggestions failed sid=%s: %s (non-fatal)"`.
- Any exception in setup (readout build `moment_suggestions.py:264-265`, Config, imports) → outer `except` at `moment_suggestions.py:509-512`, returns 0 with `"moment_suggestion: session pass failed sid=%s: %s"`.
- Snippet source: `build_readout_from_session(session_id, include_slide_scores=True)` (`moment_suggestions.py:264-265`; `services/lab_recording.py:1261`). Per-snippet keys used: `id`, `transcript` (`lab_recording.py:1331-1335`), `features` = `build_readout_features(metrics)` (`lab_recording.py:1339`, map at `lab_recording.py:40-52`), `slide_stickiness` (coach-only, `lab_recording.py:1381-1383`, only if `metrics.slide_stickiness` exists), `acoustic_read` (coach-only, `lab_recording.py:1391-1393`, only if `metrics.acoustic_read` was stamped at record time).

---

## 1. Acoustic lane — every path by which a snippet produces NO star (loop `moment_suggestions.py:338-409`)

In order per snippet:

**1a. No id / empty transcript** — `moment_suggestions.py:343-344` → counter `no_text`. Dead for all lanes.

**1b. `resolve_moment_direction(None, acoustic_read)` returns None** — `moment_suggestions.py:346-347`; `services/moment_direction.py:31-44`. Coach label is hardcoded `None` here, so direction comes purely from `tone_hint(acoustic_read)` (`services/acoustic_read.py:274-287`):
- needs `snip["acoustic_read"]` to be a dict with numeric `"potentiometer"`;
- `potentiometer >= 0.35` (`TONE_HINT_THRESHOLD`, `acoustic_read.py:62`) → `"confident"` → direction `"charisma"`;
- `potentiometer <= -0.35` → `"stressed"` → direction `"threat"`;
- otherwise None.
Ways `acoustic_read` yields no direction: absent from metrics (never stamped); stamped **cold-start neutral 0.0** — no user baseline AND take has < 6 pieces (`_MIN_PIECES_FOR_WITHIN_TAKE_READ`, `acoustic_read.py:70`, stamp at `221-231`) — *a 3-snippet take from a user without ≥8 historical piece samples (`_BASELINE_MIN_SAMPLES`, `acoustic_read.py:76`) deterministically reads 0.0*; or the needle simply sits inside the ±0.35 band.

**1c. `resolve_suggestion_kind` returns None** — `moment_suggestions.py:351-357`; `moment_direction.py:47-66`. Kind is non-None only if:
- `direction == "threat"` → `"replace"`, OR
- `has_profanity(transcript)` (`services/text_flags.py:30-35`; whole-word English list, `text_flags.py:13-27`) → `"replace"`, OR
- `slide_stickiness` numeric (from `snip["slide_stickiness"].composite`, `moment_suggestions.py:348-350`) and `<= 0.15` (`MOMENT_REPLACE_STICKINESS_MAX_PCT`, default 15, `config.py:179-180`; converted at `moment_suggestions.py:256-259`) → `"replace"`, OR
- `direction == "charisma"` → `"emphasize"`.
All four false → kind None → snippet routed to `_unstarred` (`moment_suggestions.py:354-357`) — still a candidate for congruence/delivery/structural, but no acoustic star.

**1d. Per-take cap** — `moment_suggestions.py:358-363`: `stored >= MOMENT_SUGGESTIONS_MAX_PER_TAKE` (default 8, `config.py:182-183`) → counter `capped`, logged `"moment_suggestion: acoustic cap %d hit sid=%s"`. NOTE: a capped snippet is dropped entirely — it is NOT added to `_unstarred`.

**1e. Decision-ledger skip** — `moment_suggestions.py:371-375`: `(kind, normalize_phrase(transcript))` ∈ `ledger_keys(database.list_ideal_decisions(arc_id))` → counter `decided`, snippet goes to `_unstarred`. `ledger_keys` (`services/ideal_decision_ledger.py:61-69`) includes **both approved and dismissed** rows; `normalize_phrase` = lowercase + whitespace-collapse (`ideal_decision_ledger.py:37-43`). Ledger read is best-effort — an exception yields an empty set (`moment_suggestions.py:299-303`), never a skip.

**1f. Phrase-recurs (protected wording) skip** — `moment_suggestions.py:382-387`: only when `kind == "replace"` AND `direction is None` AND no profanity (i.e. a pure stickiness replace) AND `phrase_recurs(transcript, _take_texts)` — normalized phrase ≥ 4 chars appearing in ≥ 2 spoken takes of the arc (`services/protected_phrases.py:91-99`; corpus from `collect_take_texts`, `protected_phrases.py:62-88`). Snippet goes to `_unstarred`. **No counter increments for this path** (unstarred grows, nothing else).

**1g. `generate_moment_suggestion` returns falsy** — `moment_suggestions.py:392-399` → counter `no_gen`. Every way (`moment_suggestions.py:39-96`):
1. `kind` not in `("emphasize","replace")` (`:48-49`) — impossible from this caller.
2. transcript not str / blank (`:50-51`) — impossible (checked at 1a).
3. Import failure of `services.llm` / `services.llm_config` / `services.say_it_stronger` (`:52-55`) → caught at `:94-96` → `"moment_suggestion: generation failed: %s"`.
4. `chat_complete` returns None (`services/llm.py:64-222`), four sub-ways:
   - OpenAIService construction raised → `"llm.chat surface=%s init_failed err=%s"` (`llm.py:111-118`);
   - `service.client` is None — **`OPENAI_API_KEY` unset in this process** (`services/openai_service.py:161-173`) → `"llm.chat surface=%s client_unavailable"` (`llm.py:119-123`);
   - API call raised (network / 4xx / 5xx / client timeout `OPENAI_TIMEOUT_SECONDS`) → `"... call_failed err=%s"` (`llm.py:139-148`);
   - empty completion content → `"... empty_response"` (`llm.py:182-189`).
5. `result.parsed` not a dict (`moment_suggestions.py:81-83`): JSON parse failed (`llm.py:191-205`, logged `json_parse_failed`, result still returned with `parsed=None` — note `SPEC_MOMENT_SUGGESTION` has `max_tokens=300`, `response_format=json_object`, `llm_config.py:325-332`; truncation ⇒ invalid JSON ⇒ this path), or the model returned a JSON non-object.
6. Schema mismatch inside a valid dict: `kind=="replace"` and `_guard_copy(replacement)` falsy (`moment_suggestions.py:86-90`) — replacement missing/empty, **contains any digit** (`_DIGIT_RE = r"\d"`, `services/say_it_stronger.py:50`), or matches the construct fence `_GUARD_CONSTRUCT_RE` (`say_it_stronger.py:51-58`) → None ("a replace star without a replacement is dead").
7. Both `why` and `replacement` killed by `_guard_copy` (`moment_suggestions.py:91-92`) — e.g. an emphasize whose `why` contains a digit.
8. Any other exception → `:94-96` → None.
9. **"Eval gate": there is no runtime eval gate.** The prompt-registry lockfile/golden-eval gate (`services/prompts/registry.py`, `prompts.lock.json`, `services/prompts/__init__.py:11-14`) runs in CI only. Its runtime footprint is solely the top-level import at `moment_suggestions.py:31-32` (see Entry preconditions).

**1h. `upsert_moment_suggestion` returns False** — `moment_suggestions.py:400-403`; `services/db.py:11008-11039`:
- falsy `snippet_id`/`arc_id`, or `kind` not in `SUGGESTION_KINDS = ("emphasize","replace","structure","delivery")` (`db.py:11006,11015-11017`) — the caller's kinds are always valid;
- table missing → `"upsert_moment_suggestion: table missing (run migrations/add_moment_suggestions.sql)"` (`db.py:11033-11035`);
- any Supabase/PostgREST exception (RLS, CHECK constraint on kind/trigger, FK, network) → `"upsert_moment_suggestion failed snip=%s: %s"` (`db.py:11037-11039`).
**IMPORTANT:** a False upsert here increments NO funnel counter — the funnel would show `seen>0 stored=0` with all drop counters 0 and `unstarred < seen`. This is the one invisible path in the funnel line.

**1i. Per-snippet exception** — `moment_suggestions.py:404-409` → counter `errored`, `"moment_suggestion: snippet failed sid=%s snip=%s: %s"`.

---

## 2. The behavioural lanes (run on `_unstarred` only)

**Shared prerequisite — the delivery baseline** (`moment_suggestions.py:419-422`; `services/delivery_stars.py:99-133`):
1. Cross-take: needs `session["user_id"]`; pools `metrics` from snippets of the user's last 5 sessions (`v2_list_user_lab_sessions(limit=5)`); `feature_stats(min_samples=8)` — a feature survives only with ≥ 8 numeric values and sd > 0 (`delivery_stars.py:78-96`).
2. Else within-take: needs ≥ 6 pieces whose `normalize_features()` is non-empty (`_MIN_PIECES_WITHIN_TAKE`, `delivery_stars.py:61`, `:125-129`), `min_samples=6`.
3. Else `None` → **congruence and delivery lanes are fully silent** (`_generate_delivery` returns [] at `moment_suggestions.py:203`; `generate_congruence_stars` returns [] at `delivery_alignment.py:155`), and `emphasis_z` ordering for structural is all-None (structural itself still runs). *A 3-snippet take from a user with < 8 historical samples has no baseline, by construction.*
Features come from `snip["features"]` (readout spelling: `speech_rate`, `loudness_range`), folded onto `wpm`/`dynamic_db`/`f0_sd`/`pause_ratio` by `normalize_features` aliases (`delivery_stars.py:54-57,64-75`).

**2a. Congruence (runs FIRST)** — `moment_suggestions.py:448-460`; `services/delivery_alignment.py`:
- Flag `DELIVERY_ALIGNMENT_ENABLED`, default OFF (`delivery_alignment.py:69-74`).
- Needs `arc_id`, non-empty `_unstarred`, baseline (`:155`).
- Candidate: `arousal_z(feats, baseline) <= -0.6` (`_CONGRUENCE_AROUSAL_MAX`, `:60`; `arousal_z` at `delivery_stars.py:205-231` needs ≥ 1 measurable feature with baseline sd > 0).
- At most 2 LLM attempts (`_MAX_LLM_ATTEMPTS`, `:55`), `SPEC_DELIVERY_ALIGNMENT` (`llm_config.py:131-138`, max_tokens 20); `words_positive` must be explicitly truthy (`:114-117`); all `chat_complete` failure modes above yield None → not positive.
- Upsert `("delivery", trigger="congruence")` (`:165-166`); cap 1 per take (`break`, `:168`).

**2b. Measured delivery** — `_generate_delivery` (`moment_suggestions.py:195-231`), candidates = `_unstarred` minus congruence-starred (`:462-466`):
- Flag `DELIVERY_STARS_ENABLED`, default OFF (`moment_suggestions.py:189-192`); needs `arc_id`, candidates, baseline (`:202-203`).
- Cap `DELIVERY_STARS_MAX_PER_TAKE` (default 3) and `DELIVERY_STAR_Z` (default 1.2) (`config.py:188-189`; fallback 3/1.2 at `moment_suggestions.py:207-211`).
- `detect_delivery_issue` (`delivery_stars.py:136-176`), deterministic, no LLM: needs non-empty normalized feats AND baseline entry per feature; devices: `emphasis` (z of `f0_sd` or `dynamic_db` ≤ −1.2), `pace_fast` (z wpm ≥ 1.2), `pace_slow` (z wpm ≤ −1.2), `pause` (z pause_ratio ≤ −1.2); strongest |z| wins; nothing clears the bar → None → no star.
- Upsert `("delivery", trigger=device)` (`moment_suggestions.py:222-223`).

**2c. Structural** — `_generate_structural` (`moment_suggestions.py:153-186`), candidates = `_unstarred` minus delivery/congruence-starred, sorted flattest-first by `emphasis_z` (`:471-486`; `delivery_stars.py:179-193`):
- Flag `STRUCTURAL_STARS_ENABLED`, default OFF (`moment_suggestions.py:147-150`); needs `arc_id` + candidates (`:159`).
- Cap `STRUCTURAL_STARS_MAX_PER_TAKE` (default 3, `config.py:193-194`; fallback 2 if Config raises, `moment_suggestions.py:161-165`); cap ≤ 0 → 0.
- `detect_structural_device` (`:102-144`): LLM (`SPEC_MOMENT_SUGGESTION` + `STRUCT_SYSTEM`); all `chat_complete` failure modes → None; parsed must be dict; `device` ∈ `("contrast","list_of_three")` (`_STRUCT_DEVICES`, `:99`) — a `"none"` verdict drops; `quote` non-empty; **anti-hallucination pin**: quote must be a case-insensitive verbatim substring of the transcript (`:131-134`), else `"structural_star: quote not verbatim — dropped"`.
- Upsert `("structure", replacement=None, why=<verbatim quote>, trigger=device)` (`:176-178`).

---

## 3. Attributing the 152 historical rows

SQL to run:

```sql
SELECT kind, trigger, COUNT(*) FROM moment_suggestions GROUP BY 1,2 ORDER BY 3 DESC;
```

There are exactly **four writers** of `moment_suggestions` in the codebase (all via `db.upsert_moment_suggestion`). Lane per result row:

| (kind, trigger) | Lane / write site | Gating flag(s) |
|---|---|---|
| `('replace','polish')` | **Polish-as-suggestions at assembly** — `services/ideal_text_block.py:465-466` (NOT `generate_for_session` at all) | `POLISH_AS_SUGGESTIONS_ENABLED` (`ideal_text_block.py:44-49`), on top of `MOMENT_SUGGESTIONS_ENABLED` |
| `('emphasize','charisma')` | Acoustic lane, clean charisma lean — `moment_suggestions.py:388-391,400-402` | `MOMENT_SUGGESTIONS_ENABLED` |
| `('replace','threat')` | Acoustic lane, threat direction | `MOMENT_SUGGESTIONS_ENABLED` |
| `('replace','profanity')` | Acoustic lane, profanity (no threat) | `MOMENT_SUGGESTIONS_ENABLED` |
| `('replace','stickiness')` | Acoustic lane, low slide-stickiness only | `MOMENT_SUGGESTIONS_ENABLED` (stickiness value needs a deck run producing `metrics.slide_stickiness`) |
| `('delivery','emphasis'/'pace_fast'/'pace_slow'/'pause')` | Measured delivery — `moment_suggestions.py:222-223` | `DELIVERY_STARS_ENABLED` (+ baseline resolvable) |
| `('delivery','congruence')` | Congruence — `services/delivery_alignment.py:165-166` | `DELIVERY_ALIGNMENT_ENABLED` (+ baseline) |
| `('structure','contrast'/'list_of_three')` | Structural — `moment_suggestions.py:176-178` | `STRUCTURAL_STARS_ENABLED` |
| `(any, NULL)` | Legacy rows predating the trigger vocabulary/column | — |

Reading it: whichever (kind,trigger) combination dominates the 152 tells you which lane was actually producing before 2026-08-03 — and therefore which flag/prerequisite to check **in the worker process** (per `docs/ASYNC-PIPELINE-QUEUE.md:124`, flags are per-Railway-service; a writer service missing a lane flag goes silently inert — same failure class as the CONFIG-FIRST incident). Notably, if the bulk is `('replace','polish')`, the silent generator is `ideal_text_block.py`, not `generate_for_session`.

Diagnostic corollary for tonight's `seen=3, stored=0`: a 3-piece take from a user without ≥8 historical piece-samples deterministically yields potentiometer 0.0 (cold-start floor 6, `acoustic_read.py:70,221-231`) → no direction; no baseline (cross-take needs 8 samples, within-take needs 6 pieces) → congruence + delivery silent; so absent profanity / low stickiness, only the structural lane (flag + LLM) could ever store — zero stars is the by-design outcome unless the funnel shows `no_gen>0` or `unstarred < seen` (invisible upsert-False path, §1h).

---

## 4. Exact log format strings (grep-ready)

`services/moment_suggestions.py`:
- `moment_suggestion: generation failed: %s` (WARNING, :95)
- `structural_star: quote not verbatim — dropped` (INFO, :133)
- `structural_star: detection failed: %s` (WARNING, :143)
- `structural_star: snippet failed snip=%s: %s` (WARNING, :181)
- `structural_star: stored %d arc=%s` (INFO, :185 — only when >0)
- `delivery_star: snippet failed snip=%s: %s` (WARNING, :226)
- `delivery_star: stored %d arc=%s` (INFO, :230 — only when >0)
- `moment_suggestions: context doc read failed arc=%s: %s` (WARNING, :290)
- `moment_suggestion: acoustic cap %d hit sid=%s` (INFO, :361)
- `moment_suggestion: snippet failed sid=%s snip=%s: %s` (WARNING, :407)
- `moment_suggestion: congruence failed sid=%s: %s` (WARNING, :459)
- `moment_suggestion: sid=%s arc=%s seen=%d stored=%d (no_text=%d capped=%d decided=%d no_gen=%d errored=%d) unstarred=%d` (INFO, :502-507 — the funnel line, added 2026-08-10, always emitted)
- `moment_suggestion: session pass failed sid=%s: %s` (WARNING, :510)

`services/analysis_worker.py`:
- `lab: moment suggestions failed sid=%s: %s (non-fatal)` (WARNING, :232-235 — catches module-import failure too)

`services/llm.py` (surface values from this pipeline: `moment_suggestion`, `structural_star`, `delivery_alignment`):
- `llm.chat surface=%s init_failed err=%s` (:116)
- `llm.chat surface=%s client_unavailable` (:121)
- `llm.chat surface=%s model=%s duration_ms=%d user=%s call_failed err=%s` (:144-147)
- `llm.chat surface=%s model=%s duration_ms=%d user=%s empty_response` (:184-188)
- `llm.chat surface=%s model=%s duration_ms=%d user=%s json_parse_failed raw_head=%r err=%s` (:198-203)
- `llm.chat surface=%s model=%s duration_ms=%d user=%s prompt_tokens=%s completion_tokens=%s` (INFO success, :207-212)

`services/db.py`:
- `upsert_moment_suggestion: table missing (run migrations/add_moment_suggestions.sql)` (WARNING, :11033-11035)
- `upsert_moment_suggestion failed snip=%s: %s` (WARNING, :11037)

`services/delivery_stars.py`:
- `delivery_stars: baseline resolve failed: %s` (WARNING, :132)

`services/delivery_alignment.py`:
- `delivery_alignment: congruence generation failed err=%s (non-fatal)` (WARNING, :170-173)

`services/protected_phrases.py`:
- `protected_phrases: take texts failed arc=%s: %s` (WARNING, :86)

`services/ideal_text_block.py` (polish lane writer):
- `ideal_text: polish persist failed arc=%s: %s` (WARNING, :468)

Useful grep substrings: `moment_suggestion:` · `structural_star:` · `delivery_star:` · `delivery_alignment:` · `llm.chat surface=moment_suggestion` · `llm.chat surface=structural_star` · `lab: moment suggestions failed` · `upsert_moment_suggestion`.

### 6.3 · Offers / tracked-changes pipeline — why `changes` can be empty

# Accept/Reject offer pipeline audit — `/explore/arc/<arc_id>/ideal-text` GET

## 0. The serve path in one line

`v2_explore_get_ideal_text` (routes/v2/explore_ideal_text.py:246-825) builds `_text` (machine/verified/edit/composed), then spreads `**_tracked_changes_block(arc_id, _text, user_id, _latest_take_sid)` into the payload (routes/v2/explore_ideal_text.py:806-811). `_tracked_changes_block` (routes/v2/explore_ideal_text.py:1422-1626) is the only place `changes` (and `additions`) is produced. Note the three distinct empty shapes: **key absent** (`{}` returned — flag off, no doc, or any exception, :1453, :1484, :1626), **`changes: []`** (span-check failure, :1619-1622, or gate returned nothing), and a normal empty selection.

## 1. Every condition required for a non-empty `changes` list

### Flags (all read per-process; a worker/web env split fails silently — CONFIG-FIRST trap)

| Flag | Default | Where checked | Effect when off |
|---|---|---|---|
| `LIVING_TRANSCRIPT_ENABLED` | **OFF** (`"0"`) | services/ideal_text_block.py:188; gate at routes/v2/explore_ideal_text.py:1451-1453 | `_tracked_changes_block` returns `{}` — the `changes` key never exists. Hard prerequisite for ALL seven lanes. |
| `MASTER_DOCUMENT_ENABLED` | **OFF** | services/master_document.py:53-55; route :1465 | OFF → doc = latest-take transcript (**the whole text is replaced on every take** — services/transcript_document.py:110-121, decision #4). This is the founder's "reshuffles freely" symptom. OFF also kills the `new_take` lane and `additions`; ON enables them but disables `prior_take` (:1539, :1558). ON-but-no-skeleton demotes `_master_on = False` at :1475-1480 (same reshuffling behavior until the next take builds the skeleton in the worker). |
| `MOMENT_SUGGESTIONS_ENABLED` | **OFF** | routes/v2/arcs.py:769-775; **producer gate** at services/analysis_worker.py:224-230 | `generate_for_session` never runs → no `moment_suggestions` rows → polish/wording/profanity/delivery/structural lanes have no raw material. (Serve-side, `_tracked_changes_block` reads the table unconditionally at :1489 — the gate is at generation time.) |
| `POLISH_AS_SUGGESTIONS_ENABLED` | **OFF** | services/ideal_text_block.py:44-49; producer at :440-466 | No polish suggestion rows. **See lane table: structurally dead under living-transcript anyway.** |
| `DELIVERY_STARS_ENABLED` | **OFF** | services/moment_suggestions.py:189-192 | No `kind='delivery'` rows. |
| `STRUCTURAL_STARS_ENABLED` | **OFF** | services/moment_suggestions.py:147-150 | No `kind='structure'` rows. |
| `MANAGER_CONTROLS_ENABLED` | **ON** (`"1"` — flipped 2026-08-10) | services/intervention_candidates.py:157-188 | ON + non-empty `user_id` arms three randomisations that **legitimately suppress offers**: gamma_control 12% per (user,lane) permanently (manager_engine.py:148, :172-191), withhold 20% per (user,lane,session) — slot consumed, never backfilled (manager_engine.py:149, :194-222, :642-656), ε-explore 10% rank swap (:129, :634-640). |
| `TAKE_ALIGNMENT_ENABLED` | — | services/master_document.py:394-407 | Affects deckless take→block mapping quality only. |

### Data preconditions (tables that must have rows)

1. **A spoken take with transcribed snippets** — `build_transcript_document` returns `None` without `get_arc_sessions` spoken rows + `get_snippets_by_session` rows (services/transcript_document.py:110-124, :159); `if not doc: return {}` at route :1483-1484.
2. **`coach_arc_ideal_text.auto_text`** — the served `_text` (route :298-301). Empty text → every anchor drops.
3. **`moment_suggestions` rows** (db.py:11041) for the five star lanes — written only by the analysis worker.
4. **`ideal_text_blocks` skeleton rows** for the master lanes — built ONLY in the worker via `process_new_take` → `build_skeleton` (services/master_document.py:125-232, :498-502; analysis_worker.py:248-254), never on the GET (master_document.py:249-253). `new_take` additionally needs a row with `status='pending_upgrade'`; `additions` needs `status='candidate'`.
5. **Measured snippets** — both cross-take lanes refuse comparison unless BOTH sides carry `metrics.overall_score` (prior_take_changes.py:221-228; master_document.py:562-565: `s_inc is None or s_new is None → continue`).
6. **Anchors must survive**: each piece's text must be found verbatim (monotonically) in the served text (`relocate_pieces`, transcript_document.py:188-211; window equality check tracked_changes.py:164-169; #219 rule prior_take_changes.py:237-238; upgrade regex search master_document.py:794-797). A student wholesale edit (`_user_edited`, route :403-408) or a composed/locked text that diverges kills every anchor — **by design**.
7. **Decision history suppresses**: `ideal_decision_ledger` decided rows (route :1571-1576; moment_suggestions.py:296-303, :371-375), applied map (`_applied`, route :1491-1504; tracked_changes.py:148-155), block `rejected_take_session_ids` (master_document.py:555-558), settled blocks.

### The manager-engine gate (`intervention_candidates.select`, route :1600-1605)

Order (intervention_candidates.py:330-406): **fail-closed try/except** (any exception → `[]`, :404-406) →
1. `filter_by_layer` (R1, :280-327) — runs BEFORE budget; see §4.
2. `to_candidates` (:216-256) — change must have `source` in the seven `LANE_SOURCES` (:96-104) AND a span with `end > start` (:191-213; zero-width refused).
3. `arbitrate` (manager_engine.py:552-678): gamma_control holdout (12%) → PPV floor (passes: `LANE_PPV = PPV_FLOOR = 0.70`, `>=` compare, intervention_candidates.py:131, manager_engine.py:345-352) → cooldown/mastery (passes: `sessions_since_fired=999`, `p_mastery={}`, intervention_candidates.py:269-277) → priority (grade B=0.6, uniform → document order) → collision resolution (`independent_subset`, :397-415 — overlapping spans lose all but one) → **budget ≤3** (`LANE_STATE = APPRENTICE`, intervention_candidates.py:154; `budget()` manager_engine.py:418-444) → exploration swap (10%, deterministic per (user,session) — `exploration_roll` manager_engine.py:225-251, which is also why a poll no longer reshuffles the notes) → **withhold last** (20% per (user,lane,session), slot consumed, :642-656).
4. Arms persisted to `intervention_arms` only when controls ran (`_record_arms`, route :1610-1611, :1395-1419) keyed on `_arm_sid` = the arc's latest spoken take (route :1599 — the doc-level id is None under the master flag).
5. Post-gate: `verify_changes` — any span/quote mismatch serves `changes: []` with a warning (route :1619-1622).

`additions` (candidate blocks) ride **outside** the budget and the span check (route :1613-1618; rationale master_document.py:842-853).

## 2. The seven lanes — raw material and why each is empty today

| Lane | `source` | Raw material (service + table) | What makes it empty |
|---|---|---|---|
| **polish** | `replace`/polish | `moment_suggestions` row `kind='replace', trigger='polish'` — written by `maybe_assemble_ideal_text` from `auto["polish"]` (services/ideal_text_block.py:440-466), gated `POLISH_AS_SUGGESTIONS_ENABLED` | **Structurally dead under the living transcript**: `auto["polish"]` is populated only by the legacy `assemble_ideal_text_block` (ideal_text_block.py:341-352); `assemble_transcript_document` (:242) and `assemble_master_document` (master_document.py:307) both return `"polish": []`. With `LIVING_TRANSCRIPT_ENABLED=1` no polish row is ever written again — only stale pre-flip rows can serve. Also suppressed by rule 4a recurrence (:463) and prior non-polish star on the snippet (:456). |
| **wording** | `replace`/wording or `bold` | `moment_suggestions` `kind='emphasize'` or `kind='replace'` with trigger threat/stickiness/charisma — `generate_for_session` (services/moment_suggestions.py:234-508) in the worker (analysis_worker.py:224-230) | `MOMENT_SUGGESTIONS_ENABLED` off in the **worker** env; LLM generation returning nothing / `_guard_copy` killing the string (`no_gen`, :392-399); cap `MOMENT_SUGGESTIONS_MAX_PER_TAKE` (8, :253); ledger-decided (:371-375); protected recurring phrasing (:381-387); no acoustic direction and stickiness above threshold → `kind=None` (:346-357). A `replace` row without `replacement_text` is dead at serve (tracked_changes.py:228-230). |
| **profanity** | `replace`/profanity | Same producer; `has_profanity` branch (moment_suggestions.py:388-391) | Same worker flag; still needs the LLM replacement to generate. No profanity spoken → nothing (healthy). |
| **delivery** | `advice`/delivery | `moment_suggestions` `kind='delivery'` — `_generate_delivery` (moment_suggestions.py:195-231), deterministic vs baseline | `DELIVERY_STARS_ENABLED` off; **no baseline** (`resolve_delivery_baseline`: needs cross-take history or ≥6 pieces in-take, :419-423); z below `DELIVERY_STAR_Z` (1.2); cap 3; snippet already carries an acoustic star (one star per snippet, :333-337). Serve-side: `advice` kind → dropped on any *unlocked* part when parts exist (§4). |
| **structural** | `advice`/structural | `moment_suggestions` `kind='structure'` — `_generate_structural` + `detect_structural_device` (moment_suggestions.py:99-186) | `STRUCTURAL_STARS_ENABLED` off; cap 2; non-verbatim quote dropped (anti-hallucination pin :131-134); delivery star claimed the snippet first. Same §4 advice-on-unlocked-part drop. |
| **prior_take** | `replace`/prior_take | `build_prior_take_changes` (services/prior_take_changes.py:181-263) comparing the current doc to the previous spoken take's transcript (`snippets` metrics via `get_snippet_by_id`) | **Skipped entirely when `_master_on`** (route :1558). Needs ≥2 spoken takes (`_previous_spoken_session`, route :1348-1363); fragment similarity ≥0.55 under monotonic alignment (:45, :68-94); **both** snippets measured (`activation is None → continue`, :221-222 — unmeasured takes past the LLM metrics budget produce silence); old must beat new by >0.04 power_score (:227-228); already-decided `source='prior_take'` ledger rows suppress (:208, route :1571-1576); span must still slice to the text (:237-238). |
| **new_take** | `replace`/new_take | `upgrade_changes` (services/master_document.py:757-818) reading `ideal_text_blocks` `status='pending_upgrade'` — rows written by `process_new_take` in the **worker** (master_document.py:474-666; analysis_worker.py:248-254) | `MASTER_DOCUMENT_ENABLED` off at serve OR at analysis time (worker env!); no skeleton (first take only seeds, :501-503 — take 1 never offers); challenger must beat incumbent by >0.04 with both sides measured (:562-567); self-duel skip (:553-554); take already on the block's rejected list (:555-558); segment didn't map (decked: exact `slide_index` match only, :379-387; deckless: alignment/proportional); incumbent text no longer findable in the served doc (:794-797). |

(`additions` — the eighth surface: `block_additions` on `status='candidate'` rows, master_document.py:821-884; empty when no decked slide was ever spoken that the skeleton lacks, or text already verbatim in the master :870-871.)

## 3. Empty-but-healthy vs. empty-because-dead

### Healthy-empty (working as designed)
- **Take 1 under the master flag** — the first take seeds the skeleton and offers nothing (master_document.py:501-503).
- **Margins not met** — challenger/prior fragment didn't beat by >0.04 (`_MIN_MARGIN`): silence is the designed outcome (master_document.py:566-567, prior_take_changes.py:227-228).
- **Everything already decided** — ledger rows, `rejected_take_session_ids`, applied suggestions.
- **Controls suppressed the (user,lane)** — gamma 12% permanent / withhold 20% per session. *Proof:* `intervention_arms` rows with `arm='CONTROL'`/`'WITHHELD'` for the session (manager_engine.py:471-549; db.py:13141).
- **Locked parts held offers pending** (R1) — suppressed ≠ refused; unlock brings them back (§4).
- **Student's wholesale edit is on screen** — anchors intentionally drop (#219; tracked_changes.py:167-169).
- **Nothing star-worthy** — the funnel line shows `seen>0 stored=0` with all drop counters explained (moment_suggestions.py:488-507).

### Dead-producer (broken)
- **`MOMENT_SUGGESTIONS_ENABLED` unset on the worker service** — `generate_for_session` never called; the funnel log line is *entirely absent* for new takes.
- **`MASTER_DOCUMENT_ENABLED` split between web and worker** — serve reads blocks that `process_new_take` never writes: `ideal_text_blocks` empty/settled forever while the GET looks healthy. (Exactly the CONFIG-FIRST per-service trap.)
- **Polish lane under living transcript** — producer structurally dead (see table); no flag will resurrect it without code.
- **LLM outage/guard kills generation** — funnel line shows high `no_gen`.
- **Unmeasured snippets** — `metrics.overall_score` NULL on either side starves BOTH cross-take lanes.
- **Gate fails closed** — `select()` exception returns `[]` (intervention_candidates.py:404-406).
- **Span-check regression** — `verify_changes` false serves `changes: []` every request (route :1619-1622).

### Distinguishing log lines
| Line | Meaning |
|---|---|
| `moment_suggestion: sid=… seen=N stored=M (no_text= capped= decided= no_gen= errored=) unstarred=` (moment_suggestions.py:502-507, always logged) | **Absent** = producer never ran (flag off in worker). `seen=0` = transcription/snippet problem, not a star problem. `stored=0, no_gen>0` = LLM dead. `stored=0`, all counters 0 = healthy thresholds. |
| `lab: moment suggestions failed sid=…` (analysis_worker.py:231-235) | Producer crashed. |
| `lab: master-document take processing failed …` (analysis_worker.py:255-259); `master_document: skeleton build failed` (:229-231); `take processing failed` (:663-665) | new_take/additions producer dead. |
| `take_alignment: … onto … (coverage=…)` / `off-script, proportional fallback` (master_document.py:400-407) | Deckless mapping quality. |
| `tracked changes: span check failed arc=… (serving none)` (route :1620) | Served-empty despite live candidates — anchor regression. |
| `tracked changes failed arc=…` (route :1625) | Whole block swallowed — key absent. |
| `intervention selection failed: …` (intervention_candidates.py:405) | Gate failed closed. |
| `upgrade changes failed` / `block additions failed` / `prior-take changes failed` (route :1543, :1555, :1581) | One lane's serve-side build died (others continue). |
| `intervention arms not recorded session=…` (route :1418) | Experiment record dropping (controls running blind). |
| `save: N offer(s) held pending behind a lock` (route :1259) | Lock-held offers exist. |
| `compose failed arc=…` / `locked parts failed arc=…` (route :525, :1391) | Parts lane degraded (fails open — no lock filtering). |

### Distinguishing DB queries
- `SELECT snippet_id, kind, trigger FROM moment_suggestions WHERE arc_id=…` — rows exist ⇒ producers alive; empty `changes` then is serve-side (gate/anchors/controls). No rows ⇒ producer dead or flags off.
- `SELECT block_key, status, challenger_take_session_id, rejected_take_session_ids FROM ideal_text_blocks WHERE arc_id=…` — no rows = skeleton never built (worker flag); all `settled` + empty rejected = margins/self-duel (healthy); `pending_upgrade` rows present but nothing served = serve gate/anchor/controls.
- `SELECT dimension_id, arm FROM intervention_arms WHERE session_id=<latest take>` — `CONTROL`/`WITHHELD` rows = legitimate suppression; **no rows at all while candidates should exist** = they never reached the gate.
- `SELECT kind, decision, source FROM ideal_decision_ledger WHERE arc_id=…` — decided rows = healthy suppression.
- `SELECT id, locked_at FROM ideal_text_parts WHERE arc_id=… AND user_id=…` — see §4.
- Snippet metrics: `metrics->>'overall_score' IS NULL` on the takes involved ⇒ both cross-take lanes cannot fire.

## 4. Per-part locking — where it gates the lanes

- **Storage**: `ideal_text_parts` (db.py:10851), `locked_at` column; locks minted by the user-edit PUT's auto-lock (route :1855-1872, add-only) and the R3/R5-gated `PUT /parts/<part_id>/lock` (route :1629-1738, which itself re-runs `_tracked_changes_block` and 409s `UNDECIDED` if served changes sit inside the part, :1701-1726).
- **Compose**: the GET composes locked paragraphs verbatim + refreshed machine text (route :499-525, `compose_locked`); under compose `user_edited` is forced false (:776) and the per-paragraph fence is mechanical — anchors into typed paragraphs just fail to match and drop (:485-498).
- **The layer filter** (`filter_by_layer`, intervention_candidates.py:280-327, fed by `_locked_parts`, route :1366-1392 → `select(parts=…)` :1600-1605), running BEFORE the budget:
  - `allowed_layer` derives the phase from `locked_at` (services/ideal_text_parts.py:96-106): **locked → accentuation only** (`bold`, `advice`), **open → composition only** (`replace`, `insert`) — the mapping in `_LAYER_BY_KIND` (:79-84).
  - So with parts stored: a locked paragraph can never receive polish/wording-replace/profanity/prior_take/new_take (all `replace`), and **an open paragraph can never receive delivery/structural advice or an emphasis bold**. The filter is exclusive both ways — merely having parts stored (which happens automatically after any parts-carrying edit save or compose persist) silences the accentuation lanes on every unlocked paragraph.
  - A span straddling two parts is dropped (`part_at`, ideal_text_parts.py:133-149); an unclassified kind is dropped (:87-93).
  - `parts` empty/stale → everything passes (fails open — `_locked_parts` returns `[]` on disagreement, route :1373-1381; intervention_candidates.py:290-294).
- **Save** holds (not resolves) offers whose block text sits inside a locked part (`covered_by_locked_part`, ideal_text_parts.py:161-192; route :1214-1260) — suppressed means pending, not refused.

## 5. Most likely explanation of the founder's report

The pair of symptoms — *no offers at all* AND *text reshuffles on every take* — is the signature of the document being the **latest-take transcript** rather than the persistent master: either `MASTER_DOCUMENT_ENABLED=0` (or 0 on the **worker** so no skeleton/`pending_upgrade` rows are ever written while the web flag looks on — check `ideal_text_blocks` for the arc first), leaving `new_take`/`additions` dead and the whole text swapping per take (transcript_document.py:110-121); with the star lanes simultaneously starved by `MOMENT_SUGGESTIONS_ENABLED`/`DELIVERY_STARS_ENABLED`/`STRUCTURAL_STARS_ENABLED` off in the worker (no `moment_suggestions` rows — confirmed instantly by the always-on funnel log line's absence), the polish lane structurally dead under living transcript, and `prior_take` silenced by unmeasured snippets (`overall_score` NULL) or the master flag being on at serve. The layer filter (parts present → advice dropped on open parts) and the 12%/20% controls can each shave further, but they cannot account for a total, every-lane blackout.

### 6.4 · FE flow — record → loading → text, and where it leaks

# Ideal-text staleness audit — actual wiring map

## 1. The `processing take` marker lifecycle

**Store** — `/home/user/frontend-cursor/src/lib/willab/processingTake.ts`: localStorage key `willab_processing_take` holding `{sessionId, arcId, takeIndex, startedAt}`; `clearProcessingTake(sessionId?)` is session-scoped (won't wipe a newer take's marker, processingTake.ts:48-56).

**The ONE writer** — `LabOverlay.tsx:471-477`, inside the upload effect (`LabOverlay.tsx:335-499`), and **only on the async-accept branch** `result.kind === "processing"` (202 or `body.state === "processing"`, mapped at `services/api/labRecording.ts:354-369`). Written the moment the 202 lands, while `state === "lab_processing"`. Both entry paths (live record and the Lounge-footer deckless upload, `LabOverlay.tsx:787-807`) funnel through this same effect — **Lounge never writes the marker**. The sync 201 path (`result.kind === "ok"`, LabOverlay.tsx:429-453) neither writes **nor clears** it.

**Clearers**
- LabOverlay's own live watch: `clearProcessingTake(liveSessionId)` on `failed` (LabOverlay.tsx:525) and on terminal success (LabOverlay.tsx:551), where terminal = `r.state === "ready" || r.state === "readout_ready" || (r.state !== "processing" && hasContent)` (LabOverlay.tsx:533-537). `liveSessionId` is gated `pollSessionId && state === "lab_processing"` (LabOverlay.tsx:507-508) — the Lab stops watching the instant state leaves `lab_processing`.
- Lounge resume watch: same terminal condition, `Lounge.tsx:480-508` (clear + `setProcessingResume(null)` + `reload()` on success; on `failed` it clears the marker but keeps a persistent `status:"failed"` note — the W6 change, Lounge.tsx:487-494).
- Staleness: >30 min clears quietly (Lounge.tsx:447-453, plus a live timeout at 463-471).

**Reader / resume watch** — `Lounge.tsx:427-460`, a `useEffect` keyed **only on `[state]`**:
- `isLabOverlay(state)` → stand down (`setResumeWatch(null)`) and keep a prior "analyzing" chip as-is, and `return` **without reading the marker** (Lounge.tsx:428-435).
- Otherwise `readProcessingTake()` → arm `processingResume {takeIndex, status:"analyzing"}` + `resumeWatch`.
- The watch subscribes via `useLabReadoutLive(resumeWatch.sessionId, …, 5000)` (Lounge.tsx:472-511): SSE-first to `GET /api/v2/lab/recordings/{sessionId}/events` (useLabReadoutLive.ts:84-87), falling back after 2 failed attempts to a 5s poll of `GET /api/v2/lab/recordings/{sessionId}/readout` via `fetchGuestLabReadout` (labRecording.ts:428-438); an immediate one-shot readout fetch fires on subscribe (useLabReadoutLive.ts:135).

## 2. `analysisPending` derivation and the overlay

- Derived in Lounge: `analysisPending={processingResume?.status === "analyzing"}` — Lounge.tsx:1068. Same predicate disables the Record button (Lounge.tsx:1026).
- **Not arc-scoped**: the marker's `arcId` is never compared to the overlay's `arcId` — any in-flight take makes *every* project's ideal text open into the loader.
- Overlay fetch effect: `IdealTextOverlay.tsx:251-352`, deps `[arcId, analysisPending, refetchNonce, refreshVariants]`. While `analysisPending` is true it holds in `status:"loading"` and returns before `fetchIdealText` (IdealTextOverlay.tsx:275-278); when it flips false the effect re-runs and fetches fresh (W5 — an in-place swap if the doc was already showing, per the `firstLoad`/`loadedArcRef` rule at 253-296). Pinned by test `blindLabelingIsBlind.test.ts:175-215`.
- **Closed overlay, later open**: the Lounge's overlay is conditionally mounted (`idealTextArcId && <IdealTextOverlay …>`, Lounge.tsx:1061) so every open is a fresh mount + fresh `fetchIdealText`. It does **not** show cached stale text — it shows stale text only when the fetch itself returns the old document while `analysisPending` is (wrongly) false. That's exactly what every sequence in §3 produces.
- **Second, unguarded mount**: `WillabSurface.tsx:187-199` mounts `IdealTextOverlay` for `pickedArcId` (Record → ProjectPicker → "continue project", WillabSurface.tsx:140-176) **without the `analysisPending` prop** — it always fetches immediately. Same for the in-Lab post-recording screen `IdealTextReadout` (LabOverlay.tsx:912-965), which `fetchIdealText(arcId)` on mount with no pending gate and no completion-driven refetch (IdealTextReadout.tsx:261-310; `sdNonce` bumps only on user actions).

## 3. Sequences that produce the symptom (old text after the take; loading only on the next record tap)

**S1 — Close the Lab before the 202 lands → the marker write is swallowed.**
Record → stop → `lab_processing` → user taps ✕ (`handleClose`, LabOverlay.tsx:717-731) or Back while `submitLabRecording` is still in flight. The state flip runs the upload effect's cleanup → `active = false` (LabOverlay.tsx:496-498); when the 202 resolves, `if (!active) return` (LabOverlay.tsx:428) discards everything: **`writeProcessingTake` never executes**, no `pollSessionId`, no summary bubble. The Lounge effect runs on the flip, finds no marker → no chip, Record enabled, `analysisPending=false`. Tapping the purple bubble fetches immediately → **old document rendered as current**; completion is never observed (no watch → no `reload()`, no flip). The "loading" the founder finally sees is the *next* take's own flow. The persisted-marker design only survives closure *after* the 202 has landed.

**S2 — `PROCESSING_TIMEOUT` (§A2) path: no marker ever exists.**
Upload errors with `code === "PROCESSING_TIMEOUT"` and no session to poll (labRecording.ts:322-331) → `uploadStillProcessing` panel → "Back to Lounge" (LabOverlay.tsx:1330-1347). The take keeps processing server-side; FE state is identical to S1: stale ideal text, no loading, no completion signal.

**S3 — Marker cleared at `readout_ready`, before the document is assembled.**
Both watchers treat `readout_ready` (and *any* non-`processing` state with content) as terminal (LabOverlay.tsx:533-537, Lounge.tsx:496-499) and clear the marker there — but the arc-level ideal-text reassembly and its thread bubble land at **pipeline end** (Lounge.tsx:504-507 comment). Window: marker gone, `analysisPending` false, document still the previous version.
- In-Lab: `IdealTextReadout` mounts at `goTo("readout")` and fetches instantly (IdealTextReadout.tsx:265) → adopts the **prior take's** text (294-297) and never re-pulls.
- In-Lounge: the W5 flip fires the refetch *at that same instant* → the refetch itself returns the old document and the loader ends. Same stale render, now blessed by the "fix". FE cannot distinguish "assembled" from "readout ready" with the current terminal predicate.

**S4 — Leftover marker after an abandoned slow analysis → the record-tap reveal.**
Slow panel "Record again" (LabOverlay.tsx:888-903) abandons the poll but deliberately keeps the old marker ("the marker + Lounge indicator keep tracking it"). If the fresh take then returns via the **sync 201** path (LabOverlay.tsx:429-453) the stale marker is never cleared (201 clears nothing). Back in the Lounge the `[state]`-keyed effect re-arms an "analyzing" chip from a dead session for up to 30 min: Record disabled (Lounge.tsx:1026), ideal text stuck on the **loader** (inverse symptom), until the 30-min cutoff or a terminal poll answer.

**S5 — The `[state]`-keyed arming effect is blind between state flips.**
`readProcessingTake()` runs *only* when `state` changes (Lounge.tsx:460) and never while `isLabOverlay(state)` (427-435). Overlay opens/closes (`idealTextArcId`, `feedbackTarget`, library) do **not** touch `state`, so a marker present but unseen (multi-tab: written by another tab/PWA instance; or S4's leftovers) stays invisible while the user reads old text — and surfaces exactly when they tap Record, because `goTo("lab_project_pick")` is the first state flip and `lab_project_pick` is *not* a lab-overlay state (useWillabFlow.ts:29, 44-53), so the effect finally reads the marker and the "analyzing" chip pops. This is the literal reported shape: **old text until the record tap, then loading**.

**S6 — Picker-mounted overlay ignores the pending analysis.**
`IdealTextActions` "New take" from an open ideal text is gated only by the BE's `canRecordTake` (IdealTextOverlay.tsx:932-938), not by `processingResume` — so a user can enter the Lab mid-analysis; the Lounge watch stands down (Lounge.tsx:433) and nothing watches the old session while they're in the Lab. And any route into WillabSurface's `pickedArcId` overlay (WillabSurface.tsx:187-199) fetches with `analysisPending` hard-false regardless of the marker.

## 4. Accept/reject chips for tracked changes

Render sites — **`TrackedText.tsx`** is the renderer (strike + proposal spans at TrackedText.tsx:198-217; tap → `TrackedPopover` with **Accept / Keep mine** buttons, TrackedText.tsx:331-353; `advice` renders a star, no buttons, 155-179). It is mounted only through `PieceBadgeText` (`PieceBadges.tsx:295, 310, 414`), which both `IdealTextOverlay.tsx:831-862` and `IdealTextReadout.tsx:799-827` feed with `suggestions={sd.suggestions}` + `onDecideTracked`.

Gate chain for a chip to appear:
1. `PieceBadges.tsx:262-270`: `rendersTracked` requires `onDecideTracked` present **and `ideal.keyMoments.length === 0`** (`starsPresent` — while the BE still serves `key_moments`, the tracked lane is *never drawn*) **and** at least one suggestion surviving resolution.
2. Resolution (`lib/willab/trackedChanges.ts`): `verifies` (28-34) drops anything with `status` `approved`/`dismissed`, span out of range, or `text.slice(start,end) !== quote` (**exact match** against the served text — a one-character drift kills the chip silently); overlaps are packed greedily (39-51); paragraph rebasing drops straddlers (135-143).
3. API shape (`services/api/idealText.ts:253-341`, field `changes` — `suggestions` tolerated as alias, idealText.ts:1016-1018): each entry needs a numeric `span.start`/`span.end` (or top-level), `end > start`, non-empty `quote`, `kind ∈ {replace,bold,advice}`; `replace` additionally needs non-empty `proposed_text`; `advice` needs a known `device` else dropped. Decision-routability is required or the entry is dropped (idealText.ts:333-341): `source:"new_take"` → `block_key` + `take_session_id`; `source:"prior_take"` → `snippet_id`; everything else → `snippet_id` + `take_session_id`.
4. Decisions route by source (`decideTracked`, IdealTextOverlay.tsx:532-583 / IdealTextReadout.tsx:466-542): `new_take` → block-decide, `prior_take` → prior-take decide, else suggestion-feedback; accept triggers a fenced refetch.

So: a chip requires the BE to serve `changes[]` with a byte-exact quote/span against the *served* `text`, `status:"pending"` (or absent), the routing IDs for its source, **and** an empty `key_moments` — any stale document (§3) that shifts offsets silently drops every chip with no error surface.

### 6.5 · Sweep-chain multiplication

## 1. How N immortal chains coexist with a "singleton" lease

**The lease is checked exactly once per chain — at boot, never per iteration.**

- `worker.py:214-223` — the only `acquire_sweep_lease` call site. It gates *starting a new chain* (`job_queue.py:109-134`, a `SET NX EX` at `job_queue.py:131`).
- `services/pipeline_jobs.py:525-534` — every iteration ends in a `finally` that (a) `renew_sweep_lease(...)` and (b) `job_queue.enqueue(SWEEP_LOOP_PATH, delay_seconds=interval)`. **Unconditionally.** Even if the sweep body raised. There is no "do I still own the lease?" check, no NX, no exit path. Once a chain exists, it is immortal by construction.
- `job_queue.py:137-148` — `renew_sweep_lease` is a **blind `SET key "1" EX ttl`** (line 146). The key's value is the constant `"1"` — it carries no chain identity. So nine chains all renewing the same key are indistinguishable from one healthy chain. The lease can only answer "does *some* chain exist?", never "am *I* the chain?". It is a presence flag, not an ownership lease.

So the boot log is telling the truth and is useless at the same time: at 16:xx boot, `acquire` fails (the nine existing chains keep the key alive), worker.py logs "sweep chain already running elsewhere — not starting a second" (`worker.py:221-223`) — and correctly declines to start a **tenth**. Nothing ever culls the existing nine.

**Where the nine came from (two feeders):**

1. **Legacy accumulation, never drained.** The lease was added *after* chains had already multiplied (the comment at `worker.py:207-213` and `job_queue.py:112-117` admits "ten restarts left ten immortal chains… eleven sweeps in four seconds"). The fix only prevents *new* chains at boot; the already-queued `run_sweep_loop` payloads sit in Redis (`enqueue_in` scheduled-job zset — `job_queue.py:196-199`), fire, and re-enqueue themselves forever via the `finally`. The pre-existing chains were grandfathered in as immortals.
2. **The deploy/TTL race adds +1 per long gap.** Lease TTL = interval × 3 = 15 min (`pipeline_jobs.py:493-500`). The chain only runs when a worker with `with_scheduler` is alive (`worker.py:249`). During any worker downtime > 15 min (long deploy, crash loop, Railway pause), the lease key **expires while the chain itself is merely paused** — its scheduled RQ job persists in Redis, unexpired. Next boot: key absent → `acquire` succeeds → chain N+1 enqueued (`worker.py:216-219`). Then the old chain's scheduled job fires, blindly renews the shared key, and re-enqueues → both now immortal. (A Redis wipe removes chains; anything short of that only adds them.)

**Why they fire within 4 seconds of each other:** during a worker gap, *all* chains' scheduled jobs come due; when the scheduler-bearing slot boots it drains them in one burst. Each then re-arms at `now + 300s` from its own execution time (`pipeline_jobs.py:532-534`), so the chains phase-lock and stay clustered forever — nine sweeps in a 4-second window every 5 minutes, exactly tonight's log.

## 2. Query cost

Per iteration (quiet path, nothing stale), from the code:

| call | queries |
|---|---|
| `sweep_stale_jobs` → `list_stale_processing_jobs` (`db.py:4837-4872`) | 2 (processing + pending selects) |
| `sweep_orphaned_sessions` → `list_orphaned_processing_sessions` (`db.py:4958-5022`) | 1 (+1 guard query only when candidates exist) |
| `log_saturation` → `queue_health` (`pipeline_health.py:82-120`) | 2 (`list_active` + `list_recent_finished`) |

≈ **5 Supabase queries/iteration** in code (the ~3 observed is the same shape, likely a partial window). At the default 300 s interval (`pipeline_jobs.py:494`):

- **9 chains × 5 q ÷ 300 s ≈ 45 queries / 5 min ≈ 9/min ≈ 13,000/day** (≈ 7,800/day at the observed 3/iter) — vs the intended 1,440/day. Plus 9 forked work horses per burst (each re-dialing Supabase TLS) and 9 permanent RQ scheduler entries.
- When stale rows *do* exist, all 9 chains see them and race: 9× `release_processing_job_for_retry` + 9× duplicate `enqueue` of the same job id (`pipeline_jobs.py:427-431`). The CAS claim (`pipeline_jobs.py:358-360`) keeps this *correct*, but each duplicate delivery costs another fork + 2-4 queries.
- Growth is monotonic: +5 q/interval per qualifying deploy gap, forever.

## 3. Minimal fix — chain-id ownership, checked per iteration

Make the lease value the **chain's identity** and make re-enqueue conditional on ownership, with takeover-on-absence so the queue can never end up with zero sweepers.

```python
# worker.py boot (replaces worker.py:216-219)
chain_id = uuid4().hex
if job_queue.acquire_sweep_lease(chain_id, ttl_seconds=interval * 3):
    job_queue.enqueue(pipeline_jobs.SWEEP_LOOP_PATH, chain_id,
                      delay_seconds=interval)
```

```python
# job_queue.py — value becomes the owner id
def acquire_sweep_lease(chain_id, *, ttl_seconds):     # SET key chain_id NX EX
def renew_sweep_lease(chain_id, *, ttl_seconds) -> bool:
    """Renew ONLY if we still own it: SET NX first (takeover if absent),
    else GET and compare; returns ownership."""
    if conn.set(SWEEP_LEASE_KEY, chain_id, nx=True, ex=ttl_seconds):
        return True                                     # took over a dead chain
    if (conn.get(SWEEP_LEASE_KEY) or b"").decode() == chain_id:
        conn.set(SWEEP_LEASE_KEY, chain_id, ex=ttl_seconds)
        return True
    return False
    # On a Redis *error*: return True (fail open) — a transiently duplicated
    # sweep is CAS-safe; a stopped chain is not.
```

```python
# pipeline_jobs.py run_sweep_loop (default arg keeps already-queued legacy
# payloads, which call it with NO args, from crashing)
def run_sweep_loop(chain_id: Optional[str] = None) -> None:
    try:
        counts = sweep_stale_jobs()
        ...
    finally:
        if chain_id and job_queue.renew_sweep_lease(
                chain_id, ttl_seconds=sweep_interval_seconds() * SWEEP_LEASE_INTERVALS):
            job_queue.enqueue(SWEEP_LOOP_PATH, chain_id,
                              delay_seconds=sweep_interval_seconds())
        # else: not the owner (or a legacy no-id chain) — do NOT re-enqueue.
        # This iteration is the chain's last; it dies here.
```

Why this is the minimal safe shape:

- **Self-culling:** on the first post-deploy burst, the nine legacy chains call `run_sweep_loop()` with `chain_id=None` → skip re-enqueue → all drain within one interval. Among new-style chains, exactly one id matches the key; every other duplicate exits. Converges to 1 without any manual Redis surgery.
- **Never zero sweepers:** (a) the `SET NX` takeover inside `renew` means the first firing chain after an owner death adopts the lease rather than dying with it; (b) the owner still re-enqueues in `finally` even when the sweep body raised (immortality is preserved for the single owner); (c) if the owner's re-enqueue fails (broker down), the key expires after 3 intervals and the next worker boot re-acquires — the existing self-heal at `worker.py:214-219` is untouched; (d) the web-boot sweep and `POST /v2/internal/jobs/sweep` backstops (`pipeline_jobs.py:29-30`) are unaffected.
- **Safe with existing CAS:** the fix never touches `claim_processing_job` / `release_processing_job_for_retry`; any transient two-owner overlap during handover only duplicates sweep *reads*, and duplicate job deliveries are already deduped at `pipeline_jobs.py:358-360`.
- **Stays through the queue:** no timer thread in the worker parent — the fork-safety constraint (`pipeline_jobs.py:506-509`: db-touching threads would share inherited httpx sockets with forked children) is respected.

One optional hardening, not required: on boot, when `acquire` fails, log the current key holder's chain_id so "already running elsewhere" names *which* chain — turns the next incident's log from a riddle into a pointer.

`FILTER: ADVANCE-F1-SURFACE — cat {F1-SURFACE} — fences {clear} — locks {clear} — redirect: n/a (hardens the record→take recovery path: sweeper correctness + query waste on the F1 job pipeline)`

---

## 7 · Also pending (non-blocking)

- `intervention_arms` health query — still never run:
  `SELECT arm, COUNT(*) FROM intervention_arms GROUP BY arm;`
  (empty CONTROL after a day of live suggestions = recording failure, escalate).
- Token grant for `a.willonski@gmail.com` — waiting on founder: amount, and
  tokens (`bonus_balance` — non-expiring, recommended) vs credits. Then the
  admin grant panel (founder approved the concept; money-writing surface —
  cap per request, ledger `admin_adjust` every grant).
- Task VI: engine architecture doc + backlog matrix (this handoff is a seed).
- Task III Phase B: ON HOLD pending privacy/TOS review.
- PR #237 (frontend, Cloudflare Worker activation) — founder ops task.
- mypy pre-existing: 1 stub error in `scripts/manual_smoke.py` (harmless).
