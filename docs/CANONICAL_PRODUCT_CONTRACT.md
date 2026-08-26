# Willab canonical product contract

Status: founder-locked on 2026-08-26.

This document is the product source of truth for the frontend and backend.
Historical prompts, handoffs, schemas, routes, names, and tests are evidence of
past implementations, not competing product definitions. When they conflict
with this contract, this contract wins.

## 1. Project, deck, recording, and Take

1. A Project is the canonical rehearsal container. One Project ID equals one
   Arc ID. Arc is an internal or legacy term, not a second product entity.
2. Project isolation uses immutable Project ID plus authenticated owner ID.
   Display names may repeat and never participate in identity.
3. A Project owns its setup, one slide structure, Takes, Ideal Text, feedback,
   anchors, and journey state.
4. A slide structure is either an uploaded PDF or a project-specific deckless
   structure. It may be replaced before the first completed Take and is
   immutable afterward. A changed deck starts a new Project.
5. A Recording Attempt is the preserved submitted audio. A Take exists and
   counts only after processing succeeds. Retrying processing reuses the same
   Recording Attempt and never increments the Take count.
6. Read, practice, import, and processing-retry sessions do not become Takes.

## 2. Ideal Text and document structure

7. Ideal Text is the sole canonical presentation document. Best Presentation
   as a separate assembled product artifact is retired.
8. Take 1 creates the initial project-specific Ideal Text. Later Takes never
   replace it with the latest transcript or reconstruct it from best fragments.
9. Later Takes produce evidence, feedback, and proposals. Ideal Text changes
   only through direct user editing, an explicitly accepted proposal, or a
   prior **Keep evolving** choice for that Paragraph.
10. The document hierarchy is Project -> ordered Slides -> ordered Paragraphs
    -> exact text spans.
11. Paragraph is the canonical unit for identity, editing, protection,
    feedback attachment, and root-phrase generation. Part, chunk, segment, and
    API piece are not alternative product names for an Ideal Text Paragraph.
12. A Paragraph keeps its ID through ordinary wording edits. Split and merge
    operations create new Paragraph IDs; prior IDs remain only in history and
    provenance.

## 3. Decisions, protection, anchors, and roots

13. Resolving Feedback and committing a Paragraph are separate user actions.
    After this Take's Feedback for a Paragraph is resolved, the user explicitly
    chooses **Lock for next Take** or **Keep evolving**.
14. A lock is a hard version commit. It preserves the Paragraph's exact words
    through later Takes until the user explicitly edits or unlocks it. Keep
    evolving is explicit permission for a later Take's Manager-selected
    working version to replace that Paragraph; it is not an implicit unlock.
15. Protection blocks machine rewrite, restructure, add, and cut proposals.
    Vocal feedback may still reference protected text. A coach may raise a
    material correction as an explicit proposal. Nobody silently changes
    protected text.
16. Every edit, lock, unlock, keep-evolving choice, and root-phrase choice
    appends an immutable Paragraph revision with timestamp and provenance.
17. Feedback, version commits, and root phrases are separate layers.
18. Immediately after a lock, the app asks whether to make a proposed exact
    phrase orange, choose different exact words from that Paragraph, or skip.
    Orange styling is never inferred from praise or a confidence response.
19. A rewrite overlapping an accepted orange root requires warning and
    confirmation. Applying it removes the root styling. Editing or unlocking
    also clears stale root metadata. Undo restores the complete prior text,
    root, and decision state.
20. Presentation Mode and export render slide image, one root per Paragraph,
    and normal-sized Ideal Text. They never duplicate a flagship phrase as a
    separate third text layer.

## 4. Feedback and Manager arbitration

21. The only user-facing feedback families are Confident Voice, Actionable
    Improvement, and Evidence-backed Praise. Moment, star, intervention, lane,
    device, candidate, suggestion kind, and model score are internal terms.
22. Detectors create internal Candidates. The Manager evaluates evidence,
    relevance, quality, collisions, and budget. Only Manager-approved
    Candidates become user-facing Feedback.
23. Machine Feedback appears immediately after processing. Coach review is
    asynchronous and never blocks the next Take.
24. Every valid Take surfaces exactly three Feedback items, in this contract:
    (1) the highest-ranked Confident Voice candidate; (2) the highest-ranked
    actionable verbal/structure improvement; and (3) the highest-ranked
    evidence-backed praise. Families never borrow or surrender slots.
25. Each family ranks its complete candidate pool and selects its best
    available item, not the first match. Weak evidence is allowed with
    tentative language. Feedback never invents words, praise, or certainty.
    Missing or unusable audio/transcription may fail the whole set; ordinary
    weak evidence may not.
26. The three-item set is frozen for the Take. Responding to one item never
    causes a previously hidden replacement to appear.
27. Actionable Improvement covers a verbal correction, stronger formulation,
    or material structure improvement. Praise must quote or otherwise identify
    real textual evidence; modest praise is valid when it is the best honest
    candidate.
28. Every surfaced Feedback item references exact Project, Take, Slide,
    Paragraph, and evidence span. Confident Voice additionally requires a
    playable audio interval. Actionable Improvement and Praise do not.

## 5. Confidence, learning provenance, and Voice Album

29. Confident Voice offers primary responses Yes — Confident, In-between, and
    No — Not confident, plus secondary Not sure and Audio unclear. The response
    is an immutable self-report tied to the exact clip and Take.
30. No blocks orange styling and Voice Album admission for that exact clip and
    suppresses that exact clip from resurfacing. It does not penalize the
    Paragraph, the user's voice, or materially stronger audio in a future Take.
    Yes permits later styling consideration but never applies styling itself.
    Owner answers remain self-reports, not model-training ground truth.
31. Machine prediction, blind human rating, anchored owner route, nonblind
    model review, coach judgment, and detector verdict are separate provenance
    types and are never stored under one semantic label.
32. An exact clip or selected practice attempt enters the Voice Album only
    when Machine Yes, User Yes, and Coach Yes independently refer to that same
    recording. Signals cannot be transferred between recordings.
33. Saving a practice attempt never admits it directly. The coach judges the
    selected practice attempt itself.
34. The coach must not see the user label, machine prediction, or other ratings
    before submitting an immutable independent judgment. After submission they
    are revealed for comparison and training analysis. The original coach
    judgment is never editable; reconsideration is a separately timestamped,
    provenance-bearing revision. User Yes / Coach Yes admits silently. User
    No / Coach Yes may later become
    a separate Album disagreement exercise and never enables project styling.
    User Yes / Coach No requires coach re-review and may produce a calm
    explanation after confirmed No. User No / Coach No is silent. Coach review
    never changes project styling already accepted by the user. The Voice
    Album introduction is emitted once per user after the first eligible clip
    and Take 3 completion; it never repeats for later Projects.
35. Blind peer confidence rating is retained exclusively for internal model
    training and evaluation. It has separate provenance, access, and serving
    rules and has zero authority over user Feedback, key moments, Manager
    selection, Ideal Text or presentation ranking, styling, root phrases,
    journey behavior, coach decisions, or Voice Album eligibility. The blind
    peer quorum never appears in the rehearsal or personal coaching loop.

## 6. Coach review and learning lineage

35a. Confident Voice, Actionable Improvement, and Praise responses use
    separate schemas and remain separate datasets. Shown is not positive, skip
    is not rejection, and a user response is not a gold label.
35b. Actionable Improvement offers Apply suggestion, Edit myself, and Keep
    wording. Praise offers Useful, Not useful, and Not sure. Praise responses
    never style text.
35c. Every surfaced set writes an immutable exposure ledger containing the
    complete candidate set, evidence and internal scores, selected candidate,
    model and prompt version, user action, and later coach-judgment provenance.
35d. Evidence-backed verbal corrections and praise wording/explanations may
    create surface-specific DPO pairs. Praise selection/ranking is not trained
    until the exposure ledger is complete. The three families are never merged
    into one undifferentiated training set.
36. Every Machine Feedback item retains a review lineage. The coach may confirm
    it, refine its explanation, reject it, or materially correct it. The
    original machine output remains in history.
37. Routine agreement is silent. Explanation refinement does not change user
    text. A material correction becomes a new accept/reject proposal if the
    user has seen or acted on the original.
38. Machine-versus-coach outcomes are the learning comparison. Coach actions
    never silently change accepted user text.
39. Coach review and delivery are item-level. Feedback items and clips may
    reach the user independently. Take-level reviewed or finalized state is an
    aggregate summary only and never gates immediate feedback or the next Take.
40. The coach does not own or publish a competing full-document version.
    Ideal Text remains the user's canonical document. Coach wording changes
    are explicit correction proposals with preserved machine lineage and a
    user accept/reject decision.
41. Per-item breakthrough videos and per-item Star Verdict videos are retired.
    A coach may share only an optional general Take-level video note. It is
    explicitly shared, never autoplays, never gates progress, and carries no
    detector label or Feedback verdict. Star Verdict review remains text-based.

## 7. Lifecycle and journey

42. Recording processing, Take completion, Ideal Text preparation, coach
    delivery, journey progress, and Feedback decisions are independent state
    machines. A UI status may project them but no universal pending, ready, or
    completed state controls them all.
43. Processing is durable when the user leaves the waiting screen. Failure
    preserves the Recording Attempt. Retry uses that same attempt and never
    routes the user to an unrelated Chat.
44. When processing and initial document/feedback preparation succeed, the app
    automatically opens that Project's Ideal Text.
45. Takes 1-3 follow Ideal Text -> See next steps -> stage-specific Chat bubble
    -> return to the next recording action. Refresh and reopening preserve the
    state and never repeat setup.
46. Take 3 completes the guided journey. Take 4+ is optional refinement and
    immediately offers Record again without another See-next-steps loop.
47. Accepted anchors persist across Takes and are never automatically
    replaced. First-time Paragraph/Slide coverage precedes replacement
    optimization. Replacement candidates must independently deserve
    attention. Unshown low-priority queues end after Take 3. No changes needed
    is a successful refinement result.

## 8. Commercial model

48. The free grant occurs once per user. It does not renew monthly.
49. Every purchase is a one-time package of tokens and any included coach
    review credits. Balances remain until consumed and do not renew.
50. There are no subscriptions, billing periods, renewal dates, or monthly
    plans.
51. Exhausted balances may block new paid actions but never remove access to
    existing Projects, Ideal Text, Feedback, exports, or Voice Album entries.

## 9. Legacy retirement

52. Obsolete runtime pipelines, behavioral fallbacks, adapters, and aliases are
    removed rather than retained as degraded paths.
53. Old Project data may be deleted instead of forcing permanent compatibility.
54. Database migration history remains for reproducibility. Obsolete live
    tables are removed only through explicit new migrations.
55. Any route, table, or behavior whose active use remains ambiguous requires
    an individual founder decision before removal.
56. Historical `best_presentation_ready` messages remain readable only as
    compatibility entry points to the live Ideal Text for that Project. They
    never rebuild, cache, or expose a separate Best Presentation document, and
    no new message is created under that legacy kind.
57. Breakthrough Moments is retired as a separate user-facing surface. Useful
    evidence may survive only when it already exists independently under a
    canonical Feedback family or an exact-clip Voice Album decision. It never
    creates a fourth feedback family, library, Chat action, or presentation
    artifact.
58. The former threat-to-challenge breakthrough detector and its labels are
    deleted, not repurposed as hidden Manager evidence.
59. The entire psychological threat/challenge framework is retired. Its
    priming experiment, condition and phrase capture, direction labels,
    classifier and shadow outputs, coach controls, user surfaces, runtime
    fields, and live database storage are deleted. Historical migrations stay
    immutable; an explicit cleanup migration removes the obsolete live schema.
    Pre-recording uses one supportive, non-manipulative framing and records no
    experimental condition.
60. The existing generic Game, its routes, and saved game sessions are retired.
    It is not renamed into Voice Album. Any Voice Album disagreement exercise
    is a purpose-specific personal flow inside Voice Album with its own state
    and the three-signal provenance rules above.
61. The direction-learning subsystem is removed completely, including its live
    `training_labels`, `shadow_predictions`, and `model_versions` tables. A
    future model registry must declare an explicit construct and provenance;
    the generic legacy registry is not retained empty.
62. The legacy Reflection Game and `reflection_clips` experiment are deleted
    completely, including their user and coach routes, decoy pool, agreement
    matrix, database accessors, and live table. They are not a source for the
    canonical Voice Album, which uses the three independent signals in §5.

## Non-negotiable provenance walls

- Project identity never derives from display name, topic, deck hash, or
  recency.
- Feedback candidates are not user-facing Feedback until Manager arbitration.
- Owner routing is not blind training ground truth.
- Blind peer labels and quorum are internal corpus evidence, never product
  decision inputs.
- Coach drafts, coach judgments, publication, and notification are distinct.
- Saved, accepted, protected, reviewed, and published are independent states.
- Legacy compatibility cannot silently select a different document,
  processing, feedback, learning, or billing policy.
