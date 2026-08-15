# HANDOFF — the Unification PR: Game · Feedback · Paid Unlock · Voice Album under the Confidence Quorum

**Date:** 2026-08-15 · **Repos:** `backend-cursor` (primary), `frontend-cursor` (read surfaces)
**Branch:** `claude/acoustic-highlight-detection-clarify-eu4psl`
**Status:** ⚠️ **SCOPED, NOT EXECUTED.** This document is the handoff describing the work. No unification code was written — see §7 for why, and what is needed to unblock it.

---

## 0 · Companion ruling shipped with this handoff

**The §9 acoustic highlight detector is APPROVED for V1 as-is; calibration is DEFERRED.** Recorded in `docs/SPEC.md` §9 and in the `services/snippet_salience.py` docstring. In one line: what ships is five uncalibrated equal-weight components off the existing feature blob; it diverges from SPEC §9's four named v1.0 parameters on three of four; §3.1 makes that safe because the detector owes **recall** and the two-human quorum owes **truth**. The plan of record is to let the loop run, accumulate quorum-settled labels, and fit the detector on that corpus in a separate pilot. Do not add weight-tuning machinery in the meantime.

---

## 1 · What "the Unification PR" means

Today the system has **four different, mutually incompatible answers** to one question: *"is this moment good?"* Each of the four surfaces below decides it its own way, off its own signals, in its own vocabulary — two of them still in the **retired charisma/challenge-threat** vocabulary. The Unification PR makes **`services/label_quorum.py` the single authority**: one settled label per snippet, two humans, machine as router only (founder 2026-08-11, decisions log §J), and every surface reads its answer from there instead of re-deriving one.

The value is not tidiness. It is that four gates means four different definitions of the product's core noun, and three of them are drifting from the construct the SPEC actually defines (`conf-q-v1`, §17).

---

## 2 · Current state, per surface — the actual seams

### 2.1 Voice Album — `services/voice_album.py`
Entry is a **three-signal alignment**, verbatim founder rule (2026-08-13/14): acoustic `EMPHASIZE` star (`moment_suggestions`) **AND** user applied it (`ideal_decision_ledger`, kind `emphasize`, decision `approved`) **AND** coach tagged `strong` on a **published** session. Reconciled by `refresh_voice_album` — a mirror, not a graveyard: withdrawn signals remove the entry.

- **Does not consult the quorum at all.** This is the biggest seam: SPEC §9.1 says a moment enters the album at quorum; the shipped module enters it at signal-alignment.
- Note the coach half is a **`strong` tag**, not a confidence rating. Different construct, different instrument.
- Capture-only; no read surface ships from here (needs founder-signed copy — LIVE LOOP).

### 2.2 The Game — `services/game_engine.py`, `routes/v2/arcs.py:1429`
Rounds mix the arc owner's **coach-confirmed challenge-labeled** moments with **threat** moments as decoys. Answers persist to `snippet_peer_labels` (`source='game'`) as second-order signal, explicitly **never joined into `training_labels`**. Round order is deterministic, ranked by voice source (own → consented app users → YouTube corpus, founder 2026-08-14).

- **Runs on the retired construct.** Challenge/threat is a *corpus* claim now (`services/challenge_threat.py`), not a live product construct.
- **Writes to the wrong table.** `label_quorum` counts rows in `confidence_labels` with lanes `("coach", "game_peer")`. The game currently writes `snippet_peer_labels` — so **every game answer is invisible to quorum today.** The lane vocabulary (`game_peer`, `game_owner`) already exists in `label_quorum`; the producer does not populate it.
- Rule 2 (owner ≠ peer) is already modelled — self-report is excluded from quorum and kept for rater calibration.

### 2.3 Feedback page (the readout / star lane) — `services/moment_confidence.py`, `moment_suggestions.py`
Already **re-pointed onto `confidence`** — this is the one surface substantially done. `moment_confidence` resolves **panel label → machine read** and drives the emphasize/replace/no-star decision, replacing the retired `moment_direction.py` potentiometer.

- Remaining gap: "panel label" should mean **quorum-settled** label, not any label row. Confirm `moment_confidence` reads through `label_quorum.resolve()` rather than raw rows.

### 2.4 Paid Unlock — `services/arc_entitlement.py`
$25 / 25 credits per arc unlocks exactly four surfaces: coach-corrected ideal text, the cross-take **breakthroughs list**, **the game**, and the snippet library. Record/analyse/send-to-coach/readout are always free; 402 only on opening a paid surface; the 402 body carries a price, never a score (AC-9).

- **The breakthroughs list is charisma-vocabulary.** `challenge_threat.detect_breakthroughs` defines a breakthrough as a coach `challenge` mark (founder 2026-06-26). A paid surface is selling a retired construct.
- The gate itself is construct-neutral and correct. **Do not touch pricing or gate shape in this PR.**

---

## 3 · Target state

| Surface | From | To |
|---|---|---|
| Album | 3-signal alignment (`strong` tag + star + user apply) | quorum-settled `confidence` label as the entry predicate, per §9.1 |
| Game | writes `snippet_peer_labels`, challenge/threat rounds | writes `confidence_labels` with lane `game_peer` / `game_owner`; rounds drawn by `routing_priority()` |
| Feedback | panel-or-machine read (done) | panel half reads through `label_quorum.resolve()` |
| Paid unlock | breakthroughs = coach `challenge` mark | breakthroughs = quorum-settled confident moments; gate shape unchanged |

**Invariant across all four:** `label_quorum` is the only module that decides *settled / not settled*. Nothing downstream re-derives it.

---

## 4 · Fences this PR runs directly at

Every one of these is an automatic REJECT if breached, not a tradeable cost.

1. **BLIND COACH** — the machine holds no vote (`machine_votes: 0` rides every resolution). The game must not show a player the machine's proposal, and `machine_value` is stamped **server-side** at write time (I1). Any FE round payload carrying a proposal kills the PR.
2. **AC-9** — no surface may render a settled label as a score, count, or "N of M raters agreed". The album never names the state; the read is qualitative.
3. **CONSTRUCT / SPEC §3.2** — the challenge/threat rows in `training_labels` are a **corpus**, versioned not rewritten. Re-pointing the game's *vocabulary* is a **data decision on an existing corpus**, deliberately left for its own call. **This PR must not migrate or overwrite those labels in place.**
4. **LIVE LOOP** — the album read surface and any changed game/unlock copy need founder sign-off before shipping.
5. **L2** — `power_score` blends panel-or-machine confidence, **exactly once, never summed** (§7.2/D8). Album entry stays out of ranking: `_W_B` was deleted 2026-08-14 and must not return.

---

## 5 · Recommended sequencing — four PRs, not one

The "massive single PR" framing is the main risk here. Split:

1. **Game → `confidence_labels`.** Highest value, lowest risk: dual-write to `confidence_labels` with the correct lane, keep `snippet_peer_labels` writing untouched. Every game answer starts counting toward quorum on day one. Nothing is removed.
2. **Feedback panel half through `resolve()`.** Small, verifiable, no data migration.
3. **Album entry predicate.** Needs a founder call first — see §7. Behind a flag, reconciliation-safe (the mirror rule means a wrong predicate is reversible by a refresh, not a corrupt append).
4. **Breakthroughs re-point.** Touches a paid surface and user-facing copy → founder sign-off, last.

**Config-first rule applies** to steps 1 and 3: any env var the new read path depends on must be set on **web, worker and cron** before merge, verified from each service's **boot log**, not the Railway UI. `MIGRATE_ON_BOOT=1` means merging a migration *is* running it in prod.

---

## 6 · Decision-filter verdict

```
VERDICT:  ADVANCE-F2 (for the unification) / JUSTIFIED-SCAFFOLDING (for this handoff + the §9 ruling)
CATEGORY: F2
WHY:      Collapsing four moment-gates onto the two-human quorum is F2 work — it is
          how the coach-clone's corpus stops being four incompatible corpora, and
          step 1 alone converts every game answer into quorum signal (reduces manual
          coach load, SPEC §9.1/§J). It touches F1 only through the panel half of
          power_score, which stays panel-or-machine, exactly once (L2 clear).
          Fences clear AS SCOPED — but §4.1/§4.3 are live tripwires during execution.
REDIRECT: F2 yields to open F1-CORE work. If per-slide bucketing or transcription
          fidelity has anything in flight, that goes first; ship §5 step 1 as the
          cheap standalone win in the meantime.
```

`FILTER: ADVANCE-F2 — cat {F2} — fences {clear} — locks {clear} — redirect: {sequence behind open F1-CORE; ship game→confidence_labels first}`

---

## 7 · Why this was not executed, and what unblocks it

Three things are genuinely undecided, and each changes the code materially:

1. **Does the album's three-signal rule survive, or does quorum replace it?** The founder locked the three-signal rule verbatim on 2026-08-13/14; SPEC §9.1 says quorum. These are in direct conflict and the conflict is not mine to resolve. **Options:** quorum *replaces* alignment · quorum is a *fourth* signal · alignment stays and §9.1 is amended. Each is a different module.
2. **What happens to the game's existing `snippet_peer_labels` history?** Dual-write forward is safe. Backfilling into `confidence_labels` is a corpus decision under §3.2 and needs an explicit call.
3. **Copy for every changed surface** is founder-signed by LIVE LOOP — including whatever replaces "breakthrough" on a paid surface.

Answer 1 and 2 and step 1 of §5 can be written immediately. Nothing else should be until then.

---

## 8 · Files a next session should open first

| Path | Why |
|---|---|
| `services/label_quorum.py` | the four rules; `QUORUM_LANES`, `resolve()`, `routing_priority()` |
| `services/confidence_labels.py` | `SOURCES = ("coach","game","peer")`, the stratified queue |
| `services/voice_album.py` | `refresh_voice_album` — the reconciliation contract |
| `services/game_engine.py` + `routes/v2/arcs.py:1429` | round build + the answer write |
| `services/moment_confidence.py` | the already-re-pointed panel→machine resolution |
| `services/challenge_threat.py` | what survives as corpus, and `detect_breakthroughs` |
| `services/arc_entitlement.py` | the four paid surfaces; do not change the gate |
| `docs/SPEC-DECISIONS-LOG.md` §J | the router-not-rater ruling that supersedes §9.1's three-way |

**Gate:** `scripts/local_ci.sh` is the merge evidence while Actions minutes are out — not an ad-hoc `pytest && ruff && mypy`.
