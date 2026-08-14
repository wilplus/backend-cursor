# Appendix C — Intervention Contract: Finding → Intervention → Presentation

**Last updated:** 2026-08-10.

**Companion to SPEC.md v3.** Defines the rigid layer between detection (Appendix A) and what the user sees. Inherits §8 (triage), §11 (delivery constraints), Appendix B (state modulation).

> **Amended by SPEC.md §0 decisions D9–D12.** Severity is dropped from the presentation signature; lexical overlap routes to `CUT` only; four template bands not three; unadjudicated comments are withheld rather than flagged `pending`; an `ALBUM` surface joins the registry; C.8's one-file test carries a `NOTICE` carve-out. All amendments are applied inline below. Where this document and SPEC.md conflict, **SPEC.md wins.**

> **Amended 2026-08-10 — the serving layer shipped.** The closed set is live code: the type mapping, type-keyed presentation, the ≤3 budget, the mix caps and the accent window are enforced in `services/intervention_candidates.py`. §11's / C.4's "exactly one per session" is superseded by the founder's §R1 budget (max 3 per take). Implementation state, the shipped registry, and the ops-page row→type mapping: **C.10**.

---

## C.0 · What breaks, and why

The thing that rots in systems like this is **detectors knowing about presentation**.

If V5 knows it renders as an orange upward wedge, then thirty-one findings × four learner states × two engines × three surfaces is a combinatorial mess with no single place to change anything. Add a finding, touch the UI. Change an icon, hunt through detectors. Six months in, nobody can answer "what does the user actually see for X7?"

**The fix is an intermediate layer that is closed while the layers on both sides stay open.**

```
FINDINGS            INTERVENTION TYPES        PRESENTATION
open set            CLOSED SET — 8            derived, single registry
grows forever       changes ~never            never keyed on finding_id
V1…V23, X1…X8   →   REWRITE, EMPHASISE…   →   icon, colour, verb, affordance
```

Findings multiply. Intervention types don't. Presentation depends **only** on the intervention type, severity, and learner state — **never on which finding produced it.**

That single rule is what makes the structure rigid. Everything below implements it.

---

## C.1 · The one rule, stated as an assertion

```python
# This must hold for every rendered item, at every layer.
assert presentation_of(finding) == presentation_of(
    finding.intervention_type, user_state
)
# finding_id is NOT an input to presentation. Ever.
```

**Severity is not in the signature (D9).** §11 surfaces exactly one finding per session, so there is no ordering and no comparison for severity to encode — and §8.2's triage emits a *selection* priority that is consumed and discarded once the winner is picked. Nothing produces a severity, and nothing would render it.

If a designer asks for "a special icon just for slide-reading," the answer is: slide-reading is a `REWRITE`, and if it genuinely needs different presentation then either its intervention type is wrong or the closed set is missing a member — and adding a member is a deliberate, rare, reviewed change.

---

## C.2 · The closed set — 8 intervention types

Defined by **what the user is asked to do**, not by what was detected. This is why the set stays small: thirty-one findings collapse into eight actions.

| # | Type | The ask | Example findings |
|---|---|---|---|
| 1 | `REWRITE` | Change these words | X5 slide reading, X7 jargon, concreteness, pronoun profile, conversational style, hedges |
| 2 | `RESTRUCTURE` | Change the order | V18 bridging load, deck order, refutation placement, V21 segmentation |
| 3 | `EMPHASISE` | Land harder here | **V5 orphaned salience**, V11 deflated list, V12 contrast pair, V13 missing pause |
| 4 | `DE_EMPHASISE` | Stop stressing this | V4 misplaced emphasis, V19 given-info emphasis |
| 5 | `ADD` | Something is missing | V20 unsignposted seam, V22 unrefuted counterargument, V23 unresolved loop |
| 6 | `CUT` | Something is extraneous | topic drift, **V15 lexical overlap / verbatim slide text**, V17 orphan slide |
| 7 | `NOTICE` | No action — awareness only | **All ALBUM output.** X2, X3, X4, X6, confidence moments |
| 8 | `REHEARSE` | Do a practice action | spaced schedule, retrieval rehearsal, if-then plan |

**Three properties of this set that must be preserved:**

- **`EMPHASISE` and `DE_EMPHASISE` are separate types, not one signed type.** They need opposite remedies and opposite phrasing, and collapsing them into "emphasis score" was already flagged as forbidden in Appendix A.11.
- **`NOTICE` is the only type with no action verb.** It's the Album Engine's entire output surface. Rendering it with an action affordance would misrepresent a perceptual observation as a task.
- **`REHEARSE` does not attach to a span.** It's the only type whose anchor is `WHOLE_TALK` or null. Everything else points at something.
- **Lexical overlap belongs to `CUT` alone (D10).** It previously appeared under both `REWRITE` and `CUT`, which violates C2 in the set's own examples. The remedy is *stop saying the slide's words*, not *find better ones*.

**Adding a ninth type is a reviewed architectural change**, not a feature. The test: does it require a genuinely different *affordance*? If the user does the same kind of thing, it's an existing type.

---

## C.3 · Schemas

### Finding — what a detector emits

```python
@dataclass(frozen=True)
class Finding:
    finding_id: str            # "V5", "X7" — stable, versioned
    detector_version: str
    intervention_type: InterventionType   # exactly ONE
    scope: Scope               # SNIPPET | TALK | CONTEXT  (§4)
    engine: Engine             # FEEDBACK | ALBUM
    grade: Literal["A","B","C"]
    certainty: float           # detector confidence, 0–1
    anchor: Anchor
    evidence: Evidence
    # severity is NOT set here — it is computed by triage (§8.2)
```

**Exactly one intervention type per finding.** If a finding seems to need two — "rewrite this *and* emphasise it" — it is two findings. They will compete in triage and one will win, which is correct: the user gets one note.

### Anchor — uniform, regardless of channel

```python
@dataclass(frozen=True)
class Anchor:
    span_kind: Literal["POINT", "RANGE", "WHOLE_TALK"]
    t_start: float | None
    t_end: float | None
    transcript_range: tuple[int, int] | None   # char offsets
    slide_index: int | None
```

One anchor shape for verbal-only, vocal-only and cross-modal findings. The UI highlights the same way whatever produced it. **This is what lets §11's "a few marks only, system-generated" cap be enforced in one place** — the renderer counts anchors, not findings.

### Evidence — the channels, kept separate but uniform

```python
@dataclass(frozen=True)
class Metric:
    name: str
    value: float
    expected: float | tuple[float, float]
    unit: str
    channel: Literal["verbal", "vocal"]

@dataclass(frozen=True)
class Evidence:
    metrics: list[Metric]              # both channels, same shape
    quote: str | None                  # the actual words, for FEEDBACK
    audio_ref: AudioRef | None         # the actual span, for ALBUM/NOTICE
    contributing: list[str]            # finding_ids that fed a cross-modal item
```

`contributing` is how cross-modal findings stay auditable: X5 lists `["V15", "S_voc.variance", "pause.variance"]`, so a coach reading the comment can see the three weak signals that produced one confident finding.

---

## C.4 · Presentation registry — one file, keyed on type

```python
PRESENTATION: dict[InterventionType, Presentation] = {
    REWRITE:      P(icon="pencil",        verb="Reword",   affordance=INLINE_DIFF,   surface=SESSION_NOTE),
    RESTRUCTURE:  P(icon="reorder",       verb="Reorder",  affordance=TWO_OPTIONS,   surface=SESSION_NOTE),
    EMPHASISE:    P(icon="wedge-up",      verb="Land it",  affordance=PLAY_SPAN,     surface=SESSION_NOTE),
    DE_EMPHASISE: P(icon="wedge-down",    verb="Ease off", affordance=PLAY_SPAN,     surface=SESSION_NOTE),
    ADD:          P(icon="plus-circle",   verb="Add",      affordance=INLINE_INSERT, surface=SESSION_NOTE),
    CUT:          P(icon="minus-circle",  verb="Cut",      affordance=INLINE_DIFF,   surface=SESSION_NOTE),
    NOTICE:       P(icon="waveform",      verb=None,       affordance=PLAY_SPAN,     surface=GAME_MODAL),
    REHEARSE:     P(icon="repeat",        verb="Schedule", affordance=CALENDAR,      surface=PRACTICE_TAB),
}
```

### Colour rules — these are load-bearing, not aesthetic

1. **Hue encodes type, and only type.** Severity is not encoded at all (D9) — there is one item on screen, so there is nothing to rank it against.
2. **No red/green evaluative coding.** A finding rendered red reads as *you were bad*, which is person-adjacent framing and the exact mechanism behind the 38% of feedback interventions that reduce performance. Findings are tasks, not verdicts.
3. **`NOTICE` sits outside the categorical ramp** — a distinct neutral, because it's an observation, not an action. If it looks like the other seven, users will try to *do* something about a perceptual state, which isn't available.
4. **No severity badges.** "HIGH" / "CRITICAL" chips are normative signals and invite comparison. There is no severity to badge.
5. Bind to design-system tokens (`--intv-rewrite`, `--intv-emphasise`…). No hex in the finding layer, ever.

### Surface routing follows the engine

| Surface | Receives | Constraint |
|---|---|---|
| `SESSION_NOTE` | FEEDBACK types 1–6 | ~~Exactly one per session (§11)~~ **≤3 per serve** (founder §R1, 2026-08-10 — see C.10) |
| `GAME_MODAL` | `NOTICE` — **labelling** | Blind rating first; comment revealed after commit, and **only if adjudicated** (§3.3) |
| `ALBUM` | `NOTICE` — **review** | Distinct from `GAME_MODAL`. Predict-then-reveal is a mandatory hard gate. Capped at the 5 most recent that qualified. **Never names the state** (AC-9) |
| `PRACTICE_TAB` | `REHEARSE` | Between attempts, never during |
| — | anything, in LIVE mode | Suppressed except sparse external-focus cues |

**There is no `pending` presentation (D12).** An unadjudicated moment plays with **no comment at all** — not with a comment marked provisional. At ~15 labels/week most moments are never adjudicated, so a pending marker would be the default state rather than the exception, and a mostly-unverified surface trains users to ignore the distinction entirely.

---

## C.5 · How verbal and vocal liaise into one intervention

**The rule: the intervention type is determined by the remedy, not by the modality of the evidence.**

A cross-modal detection does not produce a cross-modal intervention. It produces an ordinary one, with two channels of evidence behind it.

| Finding | Verbal evidence | Vocal evidence | Type | Why that type |
|---|---|---|---|---|
| **V5** orphaned salience | high `S_verb` | low `S_voc` | `EMPHASISE` | The words are right; the delivery isn't |
| **V4** misplaced emphasis | low `S_verb` | high `S_voc` | `DE_EMPHASISE` | Same two channels, opposite residual, opposite remedy |
| **X7** jargon w/o slowdown | jargon density | no rate drop, no pause | `REWRITE` | Cheapest fix is glossing the term, not pausing before it |
| **X5** slide reading | high lexical overlap | flat prosody, low pause variance | `REWRITE` | Fix the slide, not the voice |
| **X1** confidence–content inversion | hedges on high-`S_verb` spans | — | `REWRITE` | Cut the hedge |
| **X2** emphasis–certainty conflict | hedge markers | high `S_voc` same span | `NOTICE` | Perceptual — "sounds performed" needs witnesses, not an edit |
| **X3** load at the seams | topic boundary | within-clause pause spike | `NOTICE` | Asserts something sounded a certain way |
| **V11** deflated list | three-part list detected | item 3 under-emphasised | `EMPHASISE` | The device exists; it wasn't landed |

Note **V5 and V4 are the same two curves with the sign flipped**, and they route to different types with opposite verbs. That's the clearest demonstration that type follows remedy: identical evidence structure, opposite ask.

And note **X2/X3 go to `NOTICE` while X5/X7 go to `REWRITE`**, even though all four are cross-modal. Per SPEC.md §2, the split is whether the claim needs a witness — not whether the evidence had two channels.

---

## C.6 · Comment generation contract

The writer is **not** free-form per finding. That's how you get thirty-one voices and no consistency.

```
template = TEMPLATES[intervention_type][state_band]
comment  = writer(template, evidence, anchor)
```

- **Templates are keyed on `intervention_type` × state band** (Appendix B), not on `finding_id`. **Eight types × four bands = thirty-two templates** (D11). That's the whole surface. Four, not three: Appendix B.1 defines four states, and `FRAGILE` must not share a band with `GRADUATE` — its whole design is that it needs *different* treatment despite performing well.
- **The writer fills from `evidence`**, and every claim in the output must trace to a metric or the quote. This is what makes a coach's edit meaningful — they're correcting a grounded statement, not rewriting prose.
- **State modulates phrasing and specificity, never type or icon.** A NOVICE gets the exact word and a worked example; a GRADUATE gets "your transitions again." Same type, same icon, same colour — different text and different cohesion (Appendix B.2).
- **`NOTICE` templates contain no imperative.** If a `NOTICE` comment tells the user to do something, the template is wrong.

---

## C.7 · The invariants that keep it rigid

| # | Invariant | Enforced by |
|---|---|---|
| C1 | Presentation is a pure function of `(type, state)`. `finding_id` is never an input. | Assert in the render path; unit test over all findings |
| C2 | Exactly one `intervention_type` per finding. | Type system — the field is not a list |
| C3 | The type set is closed. Adding a member is a reviewed change. | Enum, plus a test that fails on unreviewed additions |
| C4 | One presentation registry, one file. | Lint rule: no icon/colour literals outside it |
| C5 | Every evidence claim in a comment traces to a `Metric` or `quote`. | Writer grounding check; reject ungrounded output |
| C6 | Anchor shape is uniform across channels. | Single `Anchor` type, no channel-specific variants |
| C7 | Severity does not exist as a rendered property (D9). Triage emits a selection priority, consumed and discarded. | `Finding` is frozen and has no severity field; `Presentation` takes no severity argument |
| C8 | `NOTICE` never renders an action affordance. | Registry, plus a test on the templates |
| C9 | Highlight count is capped at the renderer, counting anchors. | §11's "a few marks only" enforced in one place |

---

## C.8 · The test: adding a new finding

The structure is rigid if adding a detector touches **one file**.

```
1. Implement the detector.                    → detectors/v24_whatever.py
2. Declare it:
     finding_id, version, intervention_type,
     scope, engine, grade                     → same file
3. Emit Finding with Anchor + Evidence.       → same file
```

**Not touched:** the presentation registry, the templates, the renderer, the triage policy, the state model, the router.

If a new finding requires editing any of those, one of two things is true — its `intervention_type` is wrong, or the closed set genuinely needs a ninth member. Both are answerable in review, and both are rare. That's the definition of rigid: the open layer grows freely and the closed layer holds.

### The `NOTICE` carve-out — the test holds for FEEDBACK only

**Adding a `NOTICE` finding is not a one-file change. It is a scope decision.**

`NOTICE` routes to the Album Engine, and per SPEC.md §2 a perceptual claim needs witnesses. So a new `NOTICE` requires:

1. a **written operational definition** of the construct (§1.4)
2. a **panel question**, single-barrelled, version-stamped
3. a **label lane** and a place in the ternary schema
4. **panel capacity** — and at ~15 effective labels/week it is fully committed to confidence

That is a quarter of work, not a file. Stated explicitly because C.8 otherwise reads as a licence to add Album constructs cheaply, which is exactly what SPEC.md §1 exists to prevent.

---

## C.9 · What this structure explicitly refuses

| Refused | Why |
|---|---|
| Per-finding icons or colours | The coupling that rots the system. C1. |
| A signed "emphasis" type covering both directions | Opposite remedies, opposite phrasing. Appendix A.11. |
| Severity badges ("HIGH", "CRITICAL") | Normative framing; invites comparison; already encoded in weight and ordering. |
| Red/green finding colours | Reads as verdict on the person, not task on the work. |
| Free-form comments per finding | Thirty-one voices, no consistency, and coach edits stop being comparable. |
| Multiple findings surfaced together | §11 as amended: ≤3 per serve (C.10), at every learner state — never a wall of marks. |
| Cross-modal as a distinct intervention type | Modality is evidence, not remedy. C.5. |

---

## C.10 · Implementation state — the shipped serving layer (2026-08-10)

Everything above defines the contract; this section records how much of it is now load-bearing code, and where the working ops page fits. One file implements it: `services/intervention_candidates.py`.

### The one mapping, live

`intervention_type_of(change)` assigns every live change exactly one member of the C.2 closed set — the C2 invariant as a function, not a field convention:

| Live lane | C.2 type |
|---|---|
| `replace` / `new_take` / `prior_take` (block upgrades — L1's select) | `REWRITE` |
| `insert` | `ADD` |
| `bold` / `advice` (delivery & structural accents) | `EMPHASISE` |
| `trigger in ("confident", "charisma")` (Confident Voice — renamed 2026-08-13 with the construct retirement; historical rows keep the old word) | `NOTICE` |
| `source == "acoustic_swap"` (the swap lane, 2026-08-13 — this take delivered a LOCKED paragraph better; `kind='replace'`, exempt from the paragraph-grain decline because the paragraph IS its claim) | `REWRITE` |

Today's producers are the **composition lane and the Confident Voice star** — not the detector rows. The detectors still cannot fire (no `fire_at`; the chain stays cut on the detector side), but the serving side of the chain is no longer missing: the day a detector lands a threshold, it feeds this same gate.

### Presentation derives from type — C.1 holds in code

`TYPE_ROWS` is C.4's registry as shipped: keyed on the type and nothing else — `visual_of(change) = TYPE_ROWS[intervention_type_of(change)]["visual"]`; the lane is not an input. This surface has three affordances today:

| Types | Visual |
|---|---|
| `REWRITE` `RESTRUCTURE` `ADD` `CUT` | underline (inline diff) |
| `EMPHASISE` `DE_EMPHASISE` `REHEARSE` | bold |
| `NOTICE` | star — Confident Voice only (CONSTRUCT: a badge, never paint, never a number) |

The full C.4 registry (icons, verbs, affordances, surfaces) stands as the destination; `TYPE_ROWS` is its shipped subset plus one operational field the spec did not have — `serve_cap`.

### The budget — §11's "one" is superseded, and the ceiling is PER TAKE

Founder §R1 (SPEC-parts-locking-and-layers): **"max 3 interventions per take, total, across both layers"** — and, same day: *"each feedback needs to be there; full and end to end and waiting; not that it appears once the other is accepted."* Both are enforced now:

- `budget()` computes the flat cap (`LANE_STATE` is a declared policy dial, not inferred progression — see the budget-dial comment in the module);
- every explicit decision writes one `intervention_decisions` row (migration 0262 — SPEC §3.3's ground-truth table, doubling as the spend ledger; absence of a row is UNDECIDED per R4, and bulk/implicit paths are barred from writing);
- the serve subtracts the take's spent count inside `arbitrate(budget_spent=…)`, **before** the arms — so a decided offer keeps its slot, nothing trickles in behind an accept, the exploration swap cannot resurrect a spent budget, and the set on screen is chosen once and only shrinks. A reverted star deletes its row: undecided again, the slot returns.

### Mix caps — a reserve, not a ration

`REWRITE` carries `serve_cap = 2`. The cap binds **only while another servable type proposes**: an all-rewrite pool passes untouched (serving two of an available three would starve the student for no benefit), but the moment a metric-driven `EMPHASISE` or a `NOTICE` proposes alongside, the capped type stops being able to fill every slot ahead of it. Zero-width spans neither arm the cap nor spend it. Applied to the pool BEFORE arbitration, in document order — the engine's own tie-break, so which rewrites survive is the same answer the uncapped system gave.

### The two precision gates, in serve order

`select()` runs: **lock layer → accent window → type caps → arbitrate (≤3) → visual stamp.**

- **Lock layer (R1 gen-2, founder 2026-08-10):** an OPEN part takes everything; a LOCKED part takes **nothing** — except a Confident Voice detection (passes tagged `pending_better_version` with the founder's copy) and, since 2026-08-13, an **acoustic swap offer** (`source='acoustic_swap'`): the one lane built precisely to reach locked text, offering this take's better-delivered version of the same paragraph. Unclassified kinds and part-straddling spans drop. This is L1 enforced mechanically: nothing rewrites committed text.
- **Accent window (§F.4):** `EMPHASISE` / `DE_EMPHASISE` paint clamps to the intonation unit — `ACCENT_WINDOW_MAX_WORDS = 12`, two realised units — enforced at the offer gate AND again at ledger bake (the words stay, the paint is refused), so the two can never disagree. Confident Voice is exempt (a star at the span's end is not a wash); composition is exempt (block upgrades are legitimately block-sized).

### `NOTICE` is live — and where the blind lanes sit now

`NOTICE` is the first of the eight types to fire in production: the Confident Voice star, from **coach-verified** labels. The CONF *detector* stays OFF (ranking-inert until validated — ENGINE-MAP E10); the star lane does not depend on it. C.4's `GAME_MODAL` row stands for the user side (RATE_AND_REVEAL). On the coach side the blind lane is the snippet card's state ratings plus the confidence-question rows in the coach Feedbacks review panel (`DirectionLabel` retired 2026-08-07). BLIND COACH intact — the coach lane never shows the machine read.

### The ops page — its "eight" are rows; C.2's eight are types

The working ops table (the web page titled *Intervention contract*) carries eight **detector rows** — a coincidental eight, not the closed set. Per C.3 each row declares exactly one C.2 type; per C.1 its rendered mark derives from that type via the registry — the per-row mark column there (BOLD / HIGHLIGHT / UNDERLINE / COLOUR) is an **evidence pointer**, not a presentation choice a row gets to make.

| Row | Construct | C.2 type |
|---|---|---|
| CONF | vocal confidence | `NOTICE` — all Album output |
| SIS | sentence weakness | `REWRITE` |
| D10 | conversational style | `REWRITE` — C.2 lists it there |
| A2 | slide word overlap | `CUT` — SPEC.md D10: lexical overlap routes to `CUT` only |
| D7a | collective pronoun rate | `REWRITE` — pronoun profile |
| D7b | first-person singular | `REWRITE` — pronoun profile |
| D1 | concreteness | `REWRITE` — C.2 lists it there |
| A6 | topic discipline | `CUT` — topic drift |

(The detector row named D10 and the SPEC.md §0 decision named D10 are unrelated namesakes — the row is conversational style; the decision is the lexical-overlap routing.)

No current row is an `EMPHASISE`, `DE_EMPHASISE`, `RESTRUCTURE`, `ADD` or `REHEARSE` — those types' detector examples (the V-series) are not on the page yet. Today's live `EMPHASISE`s come from the composition lane's accent offers, not from a detector.

---

## C.11 — Slice 2 of the deck respec (founder 2026-08-11): the style lane, the proposal history, the maturity counter

**Amended 2026-08-11.** Three additions, all founder-decided in the transcript-review-deck respec; none alters C.2's closed type set or the visuals registry.

### The post-lock STYLE LANE (R1, third generation)

R1's locked-part rule is re-ruled by the founder: a **locked** part now takes **bold/colour proposals** — "when the text was already locked in there comes only the suggestion … to bolden the text or to colour a part". Mechanics:

- `filter_by_layer` passes a locked part's `kind == "bold"` changes TAGGED `style_lane: true`. Composition on locked text stays dropped (**L1's mechanical enforcement unchanged**); advice stays dropped (advice is not styling); the Confident-Voice tagged pass-through is unchanged.
- The gate splits tagged rows off **before** the budget machinery: they serve as `style_changes` beside `changes`, span-verified against the same document, still **§F.4 window-clamped** (an over-long accent paints sentences, lock or no lock), **never arm-assigned** (the experiment measures the budgeted serve only).
- **Outside the ≤3** (founder ruling: "Outside"): a style decision lands in `intervention_decisions` with `lane = "lane:style"`, which `spent_count` excludes. The row still lands — the learning loop records every explicit decision, budgeted or not.
- Surfacing: the FE shows a style proposal **only inside the chunk's modal** — locked text is never re-underlined on the page (underline stays reserved for waiting feedback).

### The PROPOSAL HISTORY (the ledger keeps the texts)

`intervention_decisions` grows `quote`, `proposed_text`, `why_key` (additive migration 0264). Every decide lane sends them when it has them; a dismissed proposal's `moment_suggestions` row is deleted, so without these columns its text is unrecoverable. The student GET serves `decision_history` (text-bearing rows, newest first); the deck's editor joins rows to a chunk **by words** (normalize-and-contain — spans die on every reassembly), lists them as "Proposals from earlier iterations", and "Use this wording" loads a past proposal into the draft — committing it is a fresh lock-in, decided step by step. Rows predating the migration carry no text and are not listed — never invented.

### The MATURITY COUNTER (a process count, never a score)

`ideal_text_part` grows `iteration` (additive migration 0265): **+1 on every lock-in, never on unlock**, surfaced on the parts block as a plain int and rendered in the modal kickers ("Locked in · N iterations"). It counts lock-in cycles survived — work done, not quality — and is therefore AC-9-clean by construction. Identity carries it: reconcile keeps a matched part's counter through reorders and rewords; genuinely new words start at 0.
