# Founder lock — the coach panel, the learning machine and the removals (2026-09-30, for October)

`LOCKED 2026-09-30 · A1–A8 all yes · B1–B10 all yes · C1–C10 as logged, C11 yes · E1–E10 as logged · L1–L9 all yes`

Recorded by the founder in chat on 2026-09-30 from four decision pages: the
coach panel redevelopment (C), the phase-two readiness page (E), the unified
coach map (A, B) and the learning machine (L). The build plan that executes
them: <https://claude.ai/artifact/1BfKdMJemTSGDNmFhxaWn3>. Where a code
comment cites a letter below, this file is what it means. The contract
clauses these answers changed are named per item; the contract wins on
wording, this file on intent.

## A — the unified coach walk (all yes)

| # | Locked |
|---|--------|
| A1 | The judgement screen is the speaker's own Feedback sheet, rendered for the coach: one instrument, the five answers with the coach's words. |
| A2 | Read is its own screen after the judgement: the passage, the speaker's answer, the coach's answer, the goal, what reached the coach and why. |
| A3 | Adding an answer is the same three screens for every kind: Words, Video, Home. |
| A4 | The model draft, where one exists for the kind, is in the field the coach edits; never shown to the speaker as drafted. |
| A5 | Video is recorded in the panel itself (upload as the fallback), never by URL. |
| A6 | Home files the answer into the library under its pattern and shares it in one tap; sharing stays a separate, explicit act. |
| A7 | After an answer the walk moves on by itself to the next open moment, then to the Take word. |
| A8 | The exercise lane (the coach's library) is the same screens, entered from the Library rather than from a moment. |

Contract: 35g-2, 35g-2a, 35g-5 (the walk), 35g-6 (the Take word).

## B — the removals (all yes)

| # | Locked | Build plan |
|---|--------|-----------|
| B1 | Remove the Feedbacks review (star verdicts): the overlay, its blind pass, the per-arc rows on the student detail, and the backend star lane's coach endpoints. The V2 lane's tables stay. | P2-17 |
| B2 | Remove the coach's Ideal Text edit and approve, and the speaker's "Reviewed" badge. A coach never edits the speaker's document (L1). | P2-18 |
| B3 | Replace the arc-level Publish (Wrap up, Ideal text, Message, Review and send, Delivered) with per-moment Share plus one optional screen after the last moment, "A word for this Take" (words and video), which the speaker reads as "Your coach". | P2-5, P2-12, P2-19 |
| B4 | Remove the wrap-up page (pre-recording feelings, re-cut snippets). | P2-19 |
| B5 | Remove the slide-mapping correction control; the slide stays as a thumbnail on Read. | P2-19 |
| B6 | Remove the confidence label chips (the second instrument). One instrument in the product. | P2-19 |
| B7 | Retire /coach/compare, /coach/audit, /coach/corpus/summary, the /coach/willab redirects, and the three off-flag composers. | P2-20 |
| B8 | Retire the /cms exercise lane, /cms/gaps and /cms/jar; posts stay in /cms; gaps and jar become ledger rows on the founder's pace panel. | P2-20, ML-4 |
| B9 | The corpus workbench keeps its import; its labelling screen is the Judge screen. | P2-16 |
| B10 | Desktop: a rail from 1024 px with speakers, Takes and moment states as words; the sheet centred; no third pane, no table view. | P2-14 |

Contract: 41 (amended), 63–66 (new retirements).

## C — the coach panel redevelopment

| # | Answer | Locked |
|---|--------|--------|
| C1 | no | The model never rewrites an exercise instruction into the speaker's situation at serve time. The coach's signed instruction stays as written; the speaker's own passage is the context; the coach may add one personal line per moment, signed by them. |
| C2 | yes | On every error, praise or rewrite request the model drafts the answer from the moment (a script, a praise line, a clearer version); the coach edits; the final is saved; the (draft, final) pair is recorded. |
| C3 | yes | One card per moment on the speaker's sheet, chosen by the follow-up matrix. |
| C4 | yes | Every coach answer also lands in the library under the pattern it treats, so the next speaker with that pattern is served from the library first. A clearer version never does (one speaker's passage). |
| C5 | yes | Three preference surfaces, one rule: a pair is recorded only when a draft was shown and the final differs; stamped with surface, model version, pattern and moment; never from owner answers; never across surfaces. |
| C6 | yes | Weekly: export each surface's new pairs with a signed manifest; train when a surface has 200 new pairs; the founder promotes after the golden evaluation. Never daily. |
| C7 | yes | The coach can name a new speaking error from the panel: name, definition, the one question. It enters as observed, routes nothing. |
| C8 | no | The adequacy endpoint stays the detectors on the attempt, as the signed label spec says; the coach's naming feeds only the shadow-cue validation. |
| C9 | yes | The ledger (jar, per-exercise counts, shadow cues, pairs) is a founder-only page. |
| C10 | yes | A shadow cue is promoted by a person, after the weekly report shows READY (30 named, 80% caught), with the report drafting the migration text. *Amended 2026-10-05 (decisions log N48.5 Q24 A): READY is 30 coaches' Yes answers in the blind error audit, 80% of them caught; naming on the moment was retired (N45 Q9).* |
| C11 | yes | Accept writes a new version of the Paragraph, labelled "Correction accepted" (the rewrite amendment: show the text, Accept, then record the accepted text). |

Contract: 29b, 35f, 35g-2, 35g-2a, 35g-3a (shadow), 35k.

## E — phase-two readiness

| # | Answer | Locked |
|---|--------|--------|
| E1 | yes | The machine's own rewrites and praise reach V3: model rows stamped with version and evidence; the fallback fires only when nothing eligible exists; the delivery and structural praise detectors switched on. |
| E2 | yes | Three exercises seeded now, one per detected error, filmed by the founder, active and tagged. |
| E3 | yes | The praise and rewrite catalogue keyed by pattern is the floor, with the model's wording on top; authored by kind. |
| E4 | yes | The coach answers by kind: a praise line, a clearer version, or a video, served on the moment like a shared exercise. |
| E5 | yes | A new coach exercise must name the main error it fixes, and the request carries the in-app recorder. |
| E6 | no | The queue stays oldest speaker first; no grouping by kind. |
| E7 | yes | One weekly job runs readiness, the shadow-cue validation and the ledger snapshot, and writes a founder-only report. It promotes nothing. |
| E8 | yes | Once the fair test clears its bar and the founder promotes, learned adequacy orders exercises of equal fit. Not before. |
| E9 | no | The bar (300 attempts, 30 per exercise) stays; a descriptive weekly view instead. |
| E10 | yes | Next recognitions: promote the three shadow verbal cues through coach naming, then add low volume and flat pitch into shadow. *Amended 2026-10-05 (N48.5 Q24 A): through coaches' Yes answers in the blind error audit, not naming. Low volume and flat pitch are not in the audit (their library questions ask about the absence of the error), so they cannot reach READY until the founder decides how they are asked.* |

Contract: 24f, 35a–35c, 35f, 35g-2, 35g-3a (shadow), 35k.

## L — the learning machine (all yes)

| # | Locked |
|---|--------|
| L1 | Door 1: the training-consent switch goes to counsel now, with the question of which pairs need a speaker's yes. |
| L2 | The walk's pair recording lands before the arc-level Publish is removed, so the pair count never drops to zero (build plan ML-5: a week of walk pairs on the ledger before P2-19 merges). *Waived by the founder on 2026-10-01 ("do P2-19 now"): the walk's pair recording was live, the week was not; P2-19 merged that day (decisions log N17).* |
| L3 | The failing daily annotation cron is replaced by the weekly export job; its Dockerfile is removed. |
| L4 | The weekly readiness job and the founder's pace panel exist before any door opens. |
| L5 | Doors 2, 3 and 4 open one surface at a time, exercise script first, each by a reviewed change the founder authorises, never a toggle. |
| L6 | The golden evaluation set is the founder's: fifty moments judged per surface, sealed, before door 3 opens. |
| L7 | The four small things fixed (the unexpected-receipt rule, the stale dark comments, the label map, the dead cron). |
| L8 | The MLC-3 exercise service loop is retired in favour of the unified walk: routes 410, tables stay, monitors off. |
| L9 | The confidence read stays rules until the SPEC's evaluation (two blind humans per clip, the kill rule at 100 labels) passes. |

Contract: 35c, 35g-3a (shadow), 35k, 66.

## Fences and locks, restated for this lock

- AC-9: the ledger, the pace, the research view and every count about the machine are founder- or research-facing only; the speaker sees no number at any door.
- BLIND COACH: the coach answers the one confidence question before anything about the moment is revealed; a promoted model changes drafts the coach edits, never a badge.
- CONSTRUCT: a pattern is named with its written definition and its one question before it is observed, shadow or detected.
- L1: a coach never edits the speaker's document; B2 removes the last path that could.
- L2: the catalogue and every coach answer are Manager-ranked before they surface; nothing raw reaches the speaker.
- L3: owner answers route, coach answers judge, machine reads predict; pairs are provenance, never labels.
