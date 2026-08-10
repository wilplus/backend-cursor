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

Answers to these define "wired end to end" for the fixing session.

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

<!-- WORKFLOW-MAPS -->

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
