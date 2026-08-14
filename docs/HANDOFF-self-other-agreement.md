# HANDOFF — Self–Other Agreement (SOA) and the learning profile

**Audience:** a coding agent picking this up cold.
**Status:** SPEC + staged plan. **Stage 2 is NOT authorised to start** — read §7 before writing a line.
**Author:** audit of `backend-cursor` @ `main` (51bfd4e) and `frontend-cursor`, 2026-08-14.
**Branch:** `claude/learning-profile-soa-h27q7t`.

---

## 0 · TL;DR for the impatient

The founder asked: *is self–other agreement built, what's it worth now, is it MVP?*

Answers: **no**, **near zero today**, **not MVP**.

But the audit turned up something more actionable than SOA itself: **`services/state_ratings.py:aggregate()` — the function that computes the panel label every SOA number would be measured against — has no production caller.** It is written, documented, unit-tested, and dead. Nothing in the running system ever turns rating rows into a panel label.

So the work splits cleanly:

| Stage | What | Gate | Verdict |
|---|---|---|---|
| **0** | Keep capturing. Change nothing. | — | **In effect now** |
| **1** | Wire the dead aggregator: panel labels + corpus visibility, admin-only | none — do it | **AUTHORISED** |
| **2** | SOA decomposition (bias / accuracy / ρ), off-surface | ≥20 users × ≥10 paired clips | **BLOCKED on data** |
| **3** | Progression state + calibration interventions | Stage 2 stable + founder sign-off on copy | **BLOCKED on 2 + founder** |

**Do Stage 1. Do not do Stage 2 or 3 yet.** Stage 1 is what makes Stage 2 possible *and* is worth doing on its own merits.

---

## 1 · Decision-filter verdict (required by CLAUDE.md)

```
VERDICT:  Stage 1 → JUSTIFIED-SCAFFOLDING · Stage 2 → DEFER · Stage 3 → DEFER (founder sign-off)
CATEGORY: Stage 1 → F2 · Stage 2/3 → SCAFFOLDING (DRIFT if surfaced as a number)
WHY:      SOA measures the user's self-knowledge. It moves neither (a) per-slide
          transcription nor (b) best-per-slide ranking, and `game_owner` is excluded
          from PANEL_LANES so it never reaches the L2 blend. Stage 1 is different:
          it closes the named hole at docs/ENGINE-MAP.md:77 ("still missing: the
          agreement aggregator joining coach + peer + self labels"), which is the
          F2 corpus path — it reduces manual coach load by making panel quorum
          computable. Stage 2/3 are neutral-and-someday (DEFER, not DRIFT) as long
          as they stay off-surface; the moment the gap is rendered to a user as a
          number they become REJECT under AC-9 + CONSTRUCT.
REDIRECT: Stage 1 only. If Stage 1 is done and there is spare capacity, the F1
          targets take precedence over Stage 2: word→slide bucketing at the
          two-clocks boundary, then transcription fidelity on hard audio.
```

One-line stamp for the PR:

```
FILTER: JUSTIFIED-SCAFFOLDING — cat {F2} — fences {clear: admin-only, no user surface} — locks {clear} — redirect: n/a (closes ENGINE-MAP:77)
```

---

## 2 · The construct, in one paragraph

Self–other agreement is the gap between how a speaker rates their own clip and how independent listeners rate the same clip. Cronbach's decomposition splits it into three **independent** components that most systems collapse into one number:

```
signed   = mean(self_i − observer_agg_i)        # ELEVATION / bias  — "your 7 is the room's 5"
absolute = mean(|self_i − observer_agg_i|)      # ACCURACY
rho      = corr(self_i, observer_agg_i)         # DISCRIMINATION    — can they rank their own clips?
```

Bias and discrimination need **opposite interventions**. A user at bias +1.2 with ρ=0.7 orders their clips correctly and only needs their anchor moved — one sentence. A user at bias ≈0 with ρ≈0 is right on average and cannot tell their good clips from their bad ones; recalibration does nothing for them, they need paired contrast work. This is Appendix B's second axis: `FRAGILE` is **low ρ**, not high bias.

Two constraints that are part of the spec, not caveats:
- **ρ needs N.** One self/observer pair is noise. ~10+ paired clips before ρ is estimable; bias stabilises much faster.
- **Prospective ≠ retrospective.** Anticipatory calibration (predict-then-reveal, SPEC §3.3) and retrospective calibration (rating a clip you already recorded) dissociate. Both may feed one score, but every row must be **tagged** with which it is.

---

## 3 · Current state — verified inventory

Everything in this section was verified against the tree. File:line references are load-bearing; if one doesn't match, the tree moved and you should re-audit before trusting the rest.

### 3.1 What exists and works

**The instrument.** `services/state_ratings.py` — state-generic ternary rating. `VALUES = ("yes","no","neutral")`, mapped `_VALUE_TERM = {yes:+1.0, neutral:0.0, no:−1.0}`. Separate `unrateable` control (a judgment about the *rater*, not the moment). `LANES = ("bootstrap","coach","game_peer","game_owner")`. Pure module, no I/O, unit-tested in `test_state_ratings.py`.

**The table.** `public.confidence_labels`, extended in place by `migrations/add_state_generic_ratings.sql` (manifest 0246), exposed as the view `public.state_ratings`. Keyed `(snippet_id, rater_id)` so multiple raters per clip aggregate. Carries `lane`, `state_id`, `question_id`, `question_version`, `saw_model_output`, `latency_ms`, `probe_score_at_time`, `model_version_at_time`. Indexed for the agreement pull: `idx_confidence_labels_state_lane_created`.

**Self ratings — three of them, on three scales.** Only one is SOA-usable:

| Source | Scale | Unit | Usable for SOA? |
|---|---|---|---|
| `v2_sessions.student_self_rating` (mig. 0154) | 1–5 | whole session | **No** — no observer counterpart at session grain |
| `coaching_attempts.self_rating` (mig. 0138) | 1–10 | one chat attempt | **No** — graded against an LLM score, not humans |
| `confidence_labels` lane `game_owner` (mig. 0246) | ternary → ±1 | **one clip** | **YES** |

The `game_owner` row is the only self rating that sits on the same clip, same instrument, and — critically — **the same numeric scale** as the observer aggregate. Both land in `[−1, +1]`. No rescaling needed, and none should be invented.

Write paths for the owner lane:
- BE: `routes/v2/user_sessions.py:1977` — `PUT /v2/user/snippets/<snippet_id>/owner-confidence-label`. Owner-scoped (404 if the snippet's session isn't the caller's — no existence oracle). Blind at the ask; FE disables the control after commit, so `saw_model_output=false` holds by construction (invariant I1).
- FE: `src/app/api/v2/user/snippets/[snippetId]/owner-confidence-label/route.ts` → `src/services/api/stateRatings.ts:97`.
- Lane resolution: `services/state_ratings.py:198` `resolve_lane(...)` → `"game_owner" if is_owner else "game_peer"`.

**Observer ratings.** Same table, lanes `coach` and `game_peer`. `PANEL_LANES = ("coach","game_peer")`. Coach is a **peer** for confidence labels (equal weight, no privileged vote on a percept) and a **truth source** for comments — two roles, never merged (SPEC-DECISIONS-LOG §D1).

**Read helpers already on `db`:**
- `services/db.py:13928` `get_confidence_labels_by_snippet_ids(ids) -> {snippet_id: [rows]}`
- `services/db.py:13945` `get_own_state_ratings_for_session(session_id, rater_id)` — deliberately single-rater-scoped; **do not widen this one**, the scope is the independence guarantee
- `services/db.py:14010` `get_confidence_label_corpus(source=None, limit=5000)` — the training-side pull, newest first
- `services/db.py:13516` `upsert_state_rating(...)`

### 3.2 The dead code at the centre of this

**`services/state_ratings.py:242` — `aggregate(rows, *, lanes=PANEL_LANES)`.** Returns `{value, agreement, n_raters, quality, by_value, unrateable_n}` for one snippet. `value` is the signed mean over ±1 — i.e. exactly `observer_agg_i`. `quality = (n/(n+k)) · (0.5 + 0.5·agreement)` (`state_ratings.py:219`), so a 5-rater 60% panel outweighs a 2-rater unanimous one, by decision.

**It has no production caller.** Grep for it across `services/` and `routes/`: the only hits are its own definition and `test_state_ratings.py`. The panel label is computed nowhere at runtime. This is the hole `docs/ENGINE-MAP.md:77` names.

`game_owner` is excluded from `PANEL_LANES` on purpose (`state_ratings.py:65-70`): the owner knows what they intended, so their answer is self-assessment, not independent judgment. **That exclusion is correct and must not be changed.** SOA doesn't need the owner *in* the panel — it needs the owner label compared *against* the panel. Different operation.

### 3.3 What is missing

1. **No panel labels at runtime.** `aggregate()` is never called. `observer_agg_i` does not exist outside a unit test.
2. **No decomposition, and no correlation code anywhere.** `grep -rn "corrcoef\|pearson\|spearman\|kendall" --include=*.py .` → zero hits. The only agreement math in the repo is `db.get_shadow_agreement()` / `services/learning_trace.py:128` `_shadow_agreement_over_time()`, which is **model-vs-coach**, not user-vs-room.
3. **No pairing.** Nothing joins an owner row to a panel label on the same `snippet_id`. Nothing counts, per user, how many such pairs exist — so the N-gate can't even be evaluated today.
4. **No prospective/retrospective tag.** SPEC §3.3's sequential gate *is* implemented, but for **corpus integrity** (stop raters anchoring on the machine), not calibration: it never stores a prediction and never diffs it. Appendix B.0's claim that "calibration comes free from the predict-then-reveal gate… no extra instrumentation" **is not true of the shipped gate**. Treat that line as aspirational.
5. **`FRAGILE` is unreachable.** `services/manager_engine.py` has all four states and `G_BY_STATE = {NOVICE:1.0, APPRENTICE:0.75, FRAGILE:1.0, GRADUATE:0.5}`, correctly encoding "do not fade FRAGILE". But `services/intervention_candidates.py:154` hardcodes `LANE_STATE = me.APPRENTICE` with the comment *"There is no progression tracking for the LLM lanes… When real progression tracking lands, read the user's actual state and delete this."* Nothing computes a state, so the low-ρ band cannot be entered.
6. **Appendix B.7's telemetry has no table.** `predicted_history`, `calibration`, `state`, `state_changed_at` per `(user_id, dimension_id)` — none of it exists.

### 3.4 The cautionary tale — read this before proposing a new column

`user_settings.inferred_learner_profile` (migration 0194, in the manifest, live in prod) documents a shape containing `"self_rating_gap": 0.05` — the signed/elevation term, specified two migrations ago.

**`services/learner_profile.py`, named in that migration's header, in `config.py:308`, and in `services/db.py:8076`, does not exist in the repo.** It was removed in "the excision" — see `routes/v2/coaching.py:407` and `routes/v2/user_chat.py:221`. The feeder query `db.list_recent_coaching_attempts_for_user()` (`services/db.py:8065`) still selects `self_rating` and has no consumer.

So there is already a live column for this exact feature, written by nothing and read by nothing. **Do not add a second one.** See §5.3 — Stage 2 computes on read, and storage is earned by a consumer, not by a plan.

---

## 4 · Stage 0 — in effect now, no work

Keep the `game_owner` capture running. It already earns its keep as plumbing independent of SOA: coach + owner are the two labels that make a snippet "twice labelled" and admit it to the game (`routes/v2/user_sessions.py:1986`). N accumulates for free.

This is the position `docs/SPEC-DECISIONS-LOG.md` §G already takes: *"Log the inputs now (per-user dimension aggregates, calibration, intervention response) so it isn't zero later."*

**Action: none. Do not remove or refactor the owner lane.**

---

## 5 · Stage 1 — wire the aggregator (AUTHORISED)

**Goal:** panel labels become a real runtime object, and the corpus becomes visible in the admin learning trace. No user surface. No new table.

**Why this and not SOA:** it closes a named hole, it pays off with the raters that exist today rather than users who don't, it makes panel quorum computable (which is what reduces manual coach load), and it produces `observer_agg_i` — without which Stage 2 is not implementable at all.

### 5.1 Scope

**A. A panel-label service.** New pure module `services/panel_labels.py` (pure = no DB, no clock, no randomness — same contract as `state_ratings.py` and `manager_engine.py`; the DB read lives in `db`, the assembly lives here).

```
def panel_for_snippets(rows_by_snippet: dict) -> dict:
    """{snippet_id: aggregate(...) or None} for a batch.

    Thin, on purpose: state_ratings.aggregate() already does the work per
    snippet and is already tested. This exists so the batch shape has one
    home and one test, instead of three callers each re-deriving it.
    """
```

Rules the implementation must hold:
- Call `state_ratings.aggregate(rows)` with the **default** `lanes=PANEL_LANES`. Never pass `lanes=LANES` outside a deliberate corpus pull.
- A snippet with no eligible answered row maps to `None`, not to a fabricated neutral. Absence is not a middling rating.
- Never mutate the input rows.

**B. Corpus visibility in the learning trace.** `services/learning_trace.py` already has the right shape — `_confidence_corpus()` at line 236, wired into `build_learning_trace()` (line 535), served admin-only at `routes/v2/admin.py:1994` `GET /v2/admin/learning/trace`.

Add a `panel` section reporting, over the capped scan (`_LABEL_SCAN_LIMIT`):
- snippets with ≥1 panel-lane answer
- distribution of `n_raters` (how many clips have 1 / 2 / 3+ observers)
- distribution of `agreement` and mean `quality`
- snippets meeting **panel quorum** (define: `n_raters >= 2` in panel lanes) — this is the number that says whether the panel is real yet
- **`soa_readiness`**: users with ≥1 `game_owner` row on a snippet that also has a quorum panel label, and the per-user pair count distribution

That last field is the whole point: it is how the founder finds out when Stage 2's gate opens, without anyone guessing. It is also cheap — it falls straight out of the same scan.

Follow the existing idiom exactly: build the section behind `_section(errors, "name", fn)` so a failure records an error and returns `None` rather than blanking the whole trace. Include a `note` string, like every other section has, saying what the numbers mean and that nothing trains on them.

**C. No FE work.** The trace is admin-only and already has a surface.

### 5.2 Explicitly out of scope for Stage 1

- Do **not** compute bias / accuracy / ρ. That's Stage 2 and it's gated.
- Do **not** add `game_owner` to `PANEL_LANES`.
- Do **not** write panel labels back onto `charisma_snippets` or into `power_score`. Panel labels feeding the ranking blend is an **L2 change** and needs a founder decision; §7.2 of SPEC describes the intended term but that wiring is not this task.
- Do **not** touch `snippet_confidence_reviews`. Those flags are **non-blind** (the reviewer saw the AI's choice first) and are quarantined in their own table under their own provenance. Blending them into the blind corpus is a founder call on weighting that has not been made.

### 5.3 Storage policy (applies to Stage 2 as well)

**Compute on read. Do not add a table or a column.**

The scan is capped and the trace is admin-only and infrequently hit. Adding a `panel_labels` table now would (a) need a migration, which in this repo means *running it in prod on merge* — `MIGRATE_ON_BOOT=1`, see CLAUDE.md — and (b) risk becoming a second `inferred_learner_profile`: a column with a beautiful docstring and no writer.

Storage is earned when a consumer exists that can't afford the recompute. Name the consumer in the PR or don't add the column.

### 5.4 Tests

New `test_panel_labels.py`, following the repo's plain-`unittest` idiom (see `test_state_ratings.py`):
- batch of snippets → correct `{id: agg}` mapping
- snippet with only `game_owner` rows → `None` (the owner is not a panel)
- snippet with only `bootstrap` rows → `None`
- snippet with all raters `unrateable` → `None`, and `unrateable_n` preserved
- mixed lanes → only panel lanes counted
- empty / malformed input → `{}` or `None`, never a raise
- input rows not mutated

Extend `test_learning_trace.py` for the new section: present when rows exist, and the section degrades to `None` with a recorded error rather than failing the whole trace when the underlying read throws.

### 5.5 Acceptance criteria

- [ ] `state_ratings.aggregate()` has at least one production caller reachable from an HTTP route.
- [ ] `GET /v2/admin/learning/trace` returns the new `panel` section including `soa_readiness`.
- [ ] No new migration, no new column, no FE change.
- [ ] `PANEL_LANES` unchanged; `game_owner` still excluded.
- [ ] Nothing new is serialised toward a non-admin caller.
- [ ] `./scripts/local_ci.sh` exits 0.

---

## 6 · Stage 2 — SOA decomposition (BLOCKED — do not start)

Written down now so the gate is legible and so Stage 1 produces the right readiness numbers. **Do not implement until §7's gate is met and the founder says go.**

### 6.1 The gate

- **≥20 users**, each with **≥10 paired clips** (a clip with a `game_owner` row *and* a panel label at `n_raters ≥ 2`).
- Read the number off Stage 1's `soa_readiness`. Do not estimate it.

Rationale: ρ on 3 pairs is noise that will be acted on and then quietly re-tuned. Bias stabilises faster and is tempting to ship early — resist; a bias number with no ρ next to it invites exactly the misdiagnosis the construct exists to prevent (recalibrating a user whose real problem is discrimination).

### 6.2 The computation (pure module, `services/self_other_agreement.py`)

```
soa(pairs) -> {
    n_pairs, signed, absolute, rho, rho_estimable, quality_mean, tag
}
```

Where each pair is `(self_value, observer_value, quality, n_raters, tag)` and:

- **Scales already match.** Self is `_VALUE_TERM[value] ∈ {−1, 0, +1}`; observer is `aggregate()["value"] ∈ [−1, +1]`. **Do not rescale, do not normalise, do not invent a 1–10 mapping.** If you find yourself writing a scale conversion, you have picked the wrong self-rating source — see §3.1.
- `signed = mean(self − obs)` — the elevation/bias term. Sign convention: **positive = user rates themselves above the room.**
- `absolute = mean(|self − obs|)` — accuracy.
- `rho = corr(self, obs)` — Pearson over the pairs. **Must return `None`, never `0.0`, when undefined:** a user who answers `yes` to every clip has zero variance and no correlation exists. Reporting 0.0 there says "cannot discriminate" when the truth is "cannot be measured" — and those route to different interventions. Set `rho_estimable=False` and say why.
- **Pair eligibility:** drop pairs where the owner row is `unrateable` (no self value) — count them separately, abstention is a signal. Drop pairs where the panel has `n_raters < 2`; one observer is not "the room". Keep `quality` per pair so quality-weighting can be added later without re-pulling.
- **`tag ∈ {"retrospective", "prospective"}`**, stored per pair, never mixed into one number without the split also being reported. Today every pair is `"retrospective"` — the owner rates a clip already recorded. A prospective pair would require a predict-before-reveal capture that does not exist (§3.3 is a blind-rating gate, not a prediction gate). Populate the field anyway so the dissociation stays recordable the day a prospective source lands.
- Pure module: no DB, no clock. Unit-testable without a session, same as `state_ratings.py`.

### 6.3 Surface

**Admin learning trace only.** A `soa` section next to `panel`, aggregate across users, plus a per-user breakdown behind the existing admin auth. Compute on read (§5.3).

**Nothing reaches a user in Stage 2.** Not a badge, not a sentence, not a hint.

### 6.4 Tests

Cover at minimum: known-answer fixtures for all three statistics; zero-variance self → `rho=None, rho_estimable=False`; zero-variance observer → same; below-N → statistics suppressed with a reason, not silently returned on 3 pairs; `unrateable` pairs excluded and counted; `n_raters < 2` pairs excluded; sign convention asserted explicitly (a user who says `yes` where the room says `no` yields **positive** signed).

---

## 7 · Stage 3 — interventions and progression state (BLOCKED × 2)

Requires Stage 2 stable **and** founder sign-off on user-facing copy. Sketched only.

- **Bias → recalibrate.** One qualitative sentence. The doc's own example, *"your 7 is the room's 5,"* **cannot ship as written** — it is a number about the user, which AC-9 fences. The compliant form is qualitative: *"you're harder on yourself than the room is."* Copy needs founder sign-off regardless (LIVE LOOP; R13 — "just a tiny copy tweak" is not exempt).
- **Low ρ → paired contrast.** A/B two of the user's *own* clips: "which sounded more certain?" Note there is already an A/B surface — `services/ab_slide_pairs.py`, `frontend-cursor/src/app/coach/compare/` — but it is **coach-side slide-text comparison**, not a speaker contrasting their own audio. Related shape, different feature; reuse the blinding helpers (`src/app/coach/compare/blinding.test.ts`) rather than the flow.
- **Progression state.** Only here does it become honest to compute a real state and delete `intervention_candidates.py:154`'s hardcoded `LANE_STATE`. `FRAGILE` is defined by **low ρ**, not high bias (Appendix B.2.1) — a state machine that reads performance alone will graduate exactly the users who most need holding, which Appendix B calls "the single most common way this class of system fails." Per Appendix B.0, state is keyed `(user_id, dimension_id)`; **anything reading a global user level is wrong.**

---

## 8 · Fences and invariants — non-negotiable

| Fence | What it forbids here | Where it bites |
|---|---|---|
| **AC-9** | No scores, verdicts, ratios or numbers to users. The SOA gap **is** a score about the user. | Any Stage 3 copy. Any temptation to show a badge in Stage 1/2. |
| **CONSTRUCT** | "Charisma" stays a qualitative badge, never a surfaced score/ratio/classifier output. | Don't let a calibration number become a charisma proxy on the way out. |
| **BLIND COACH** | Coach labels stay blind; the shadow model never surfaces a guess. | Don't pre-fill or hint a panel value in any rating UI. |
| **I1 — blind-stream integrity** | The rating step never receives model scores or comments; enforced at the **data layer**, not the UI. | If you touch a rating payload, the score object and comment must not be in it. `saw_model_output` is stored so the invariant is auditable — keep writing it. |
| **LIVE LOOP** | Never break record→transcribe→coach→read. Gate-routed merges. Copy needs founder sign-off. | Stage 1 touches an admin read path only — keep it that way. |
| **Lane separation** | `snippet_confidence_reviews` is **non-blind** and must never blend into the blind corpus without a founder weighting decision. | Do not join it into panel labels "for more data". |
| **Owner ≠ panel** | `game_owner` stays out of `PANEL_LANES`. | The fix for SOA is to *compare* self against panel, never to *include* self in panel. |

---

## 9 · Engineering constraints for whoever implements this

- **Branch off `origin/main`**, ship via PR. Never push to `main`.
- **CI:** Actions is out of minutes (founder ruling 2026-08-11: **do not upgrade**). The gate is **`./scripts/local_ci.sh`** — it rebuilds the `checks` job environment (python 3.12, pinned `ruff`/`mypy`, `requirements.txt`) and runs its steps in the job's order. An ad-hoc `pytest && ruff && mypy` is **not** the job: the system `mypy` is a major version behind the pin and passes real type errors. Document the override in the squash commit. `test_local_ci_mirror.py` fails if the script and the workflow drift.
- **Migrations (only if you break §5.3's rule):** append to `migrations/manifest.txt` as `<version>\t<filename>`, tab-separated, append-only. Idempotent (`IF NOT EXISTS`), degrade gracefully, never drop a table or column. **⚠️ In prod, merging a migration IS running it** — `MIGRATE_ON_BOOT=1`, `bin/railway-web.sh` applies pending migrations during container start, before the app boots.
- **CONFIG-FIRST:** if any of this ever depends on an env var, set it on **every** Railway service (web, worker, cron) *before* merging, and verify from each service's **boot log**, not the Railway UI.
- **Style:** pure modules for policy (no DB/clock/randomness), DB reads in `services/db.py`, routes thin. Match the surrounding comment density — this codebase explains *why* in the file, and a silent constant here gets tuned by whoever is annoyed by it first.
- **Failure posture:** every new read degrades to empty/`None` and logs a warning. Nothing added here may raise into a request path.

---

## 10 · Open questions for the founder

Do not guess these; none of them block Stage 1.

1. **Does the panel label eventually feed `power_score`?** SPEC §7.2 describes the term (`_W_CONF_PANEL × quality`), but wiring it is an **L2** change to the ranking blend. Stage 1 deliberately stops short.
2. **Quality-weighting the SOA pairs.** Should a pair with a 5-rater unanimous panel count more than a 2-rater split? Stage 2 stores `quality` per pair so this is a later decision, not a re-pull.
3. **Does a prospective capture get built?** Without one, "predict-then-reveal calibration" stays retrospective-only and Appendix B.0's "comes free" claim stays false. Cheapest honest version: ask for a predicted label *before* the take, not before the reveal.
4. **Whose corpus for cross-user comparison?** Already open in `SPEC-DECISIONS-LOG.md` §I.2 — pooled ranks users against each other, which AC-9 fences.

---

## 11 · Traps — things that look right and aren't

1. **"Just use the 1–10 self-rating, there's more of it."** `coaching_attempts.self_rating` is graded against an **LLM** score, not human observers. Computing SOA from it measures agreement-with-the-machine, which is the exact contamination D2 exists to prevent. It is not a smaller version of the right data; it is different data.
2. **"Add `game_owner` to `PANEL_LANES` so self and other are comparable."** Backwards. That makes the observer aggregate contain the self rating and drives the gap toward zero mechanically.
3. **"`aggregate()` is dead code, delete it."** It is the correct implementation of a specified thing that was never wired. Wire it.
4. **"Ship bias now, ρ later — bias stabilises faster."** True and still wrong. A bias number alone routes low-ρ users to recalibration, which does nothing for them, and Appendix B.2.1 says that plateau is this system's characteristic failure.
5. **"Store the profile in `inferred_learner_profile`, the column already exists."** It exists, is in the manifest, is live in prod, and has **no writer and no reader** because `services/learner_profile.py` was excised. Reviving it means reviving the whole excised path; that is a founder decision, not a convenience.
6. **"Return `rho=0.0` when it's undefined, it's simpler."** 0.0 means *cannot discriminate*; undefined means *cannot be measured*. They route to different interventions. Return `None`.
7. **"The trace is admin-only, so AC-9 doesn't apply."** Correct today and one route change away from being false. Keep the numbers machine-facing by construction, not by the current audience.

---

## 12 · Reference index

| Thing | Location |
|---|---|
| Ternary instrument, `aggregate()`, `quality()`, `resolve_lane()` | `services/state_ratings.py` |
| Panel lanes constant + rationale | `services/state_ratings.py:58-70` |
| Owner-label write route | `routes/v2/user_sessions.py:1977` |
| Owner-label FE proxy / client | `frontend-cursor/src/app/api/v2/user/snippets/[snippetId]/owner-confidence-label/route.ts`, `src/services/api/stateRatings.ts:97` |
| Label read helpers | `services/db.py:13928`, `:13945`, `:14010` |
| Learning trace assembly | `services/learning_trace.py:236`, `:535` |
| Admin trace route | `routes/v2/admin.py:1994` |
| Shadow (model-vs-coach) agreement — *not* SOA | `services/db.py:14912`, `services/learning_trace.py:128` |
| Four states, `G_BY_STATE`, FRAGILE policy | `services/manager_engine.py:40-116` |
| Hardcoded progression state (delete in Stage 3) | `services/intervention_candidates.py:154` |
| Dead learner-profile column | `migrations/add_inferred_learner_profile_to_user_settings.sql` |
| The named gap | `docs/ENGINE-MAP.md:77` |
| Four-state model, calibration, B.7 telemetry | `docs/SPEC-APPENDIX-B-progression.md` |
| Sequential reveal gate (§3.3), panel weighting (§7.2), invariants (I1/I10) | `docs/SPEC.md` |
| Lane decisions, `PANEL_LANES` note, open questions | `docs/SPEC-DECISIONS-LOG.md` |
| Peer-review quarantine rationale | `migrations/add_snippet_confidence_reviews.sql` |
| Decision filter (full, R1–R14) | `docs/willab_decision_filter.md` |
| Local CI gate | `scripts/local_ci.sh` |

---

## 13 · One-paragraph summary for the PR description

> Self–other agreement is not built. The capture exists — the `game_owner` lane writes a blind ternary self-label on the same clip, same instrument and same ±1 scale as the coach/peer panel — but the panel label it would be compared against is never computed at runtime: `state_ratings.aggregate()` has no production caller. This PR wires it, adds panel + SOA-readiness visibility to the admin learning trace, and adds no user surface, no migration and no new column. The SOA statistics themselves (signed bias, absolute accuracy, ρ) are specified in `docs/HANDOFF-self-other-agreement.md` §6 and deliberately not implemented: ρ needs ~10 paired clips per user and the readiness number added here is how we will know when that threshold is met.
