# Willab canonical product contract

Status: founder-locked on 2026-08-22.

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
   only through direct user editing or an explicitly accepted proposal.
10. The document hierarchy is Project -> ordered Slides -> ordered Paragraphs
    -> exact text spans.
11. Paragraph is the canonical unit for identity, editing, protection,
    feedback attachment, and root-phrase generation. Part, chunk, segment, and
    API piece are not alternative product names for an Ideal Text Paragraph.
12. A Paragraph keeps its ID through ordinary wording edits. Split and merge
    operations create new Paragraph IDs; prior IDs remain only in history and
    provenance.

## 3. Decisions, protection, anchors, and roots

13. Accepting a proposal and protecting a Paragraph are separate user actions.
14. Protection blocks machine rewrite, restructure, add, and cut proposals.
    Vocal feedback may still reference protected text. A coach may raise a
    material correction as an explicit proposal. Nobody silently changes
    protected text.
15. Feedback, accepted anchors, and root phrases are separate layers.
16. Orange styling exclusively marks exact text the user explicitly accepted
    as a speaking anchor.
17. Every Paragraph has one root phrase. Without an accepted anchor it is a
    neutral 3-5-word fallback. An accepted anchor replaces that fallback.
18. Confident Voice and Great Formulation may create an anchor through a
    separate acceptance action. Rewrite for Clarity changes text but does not
    create an anchor. Protection remains separate.
19. A rewrite overlapping an accepted anchor requires warning and
    confirmation. Applying it removes the anchor and returns the Paragraph to
    a neutral root. Undo restores the complete prior text, anchor, root, and
    decision state.
20. Presentation Mode and export render slide image, one root per Paragraph,
    and normal-sized Ideal Text. They never duplicate a flagship phrase as a
    separate third text layer.

## 4. Feedback and Manager arbitration

21. The only user-facing feedback families are Confident Voice, Great
    Formulation, and Rewrite for Clarity. Moment, star, intervention, lane,
    device, candidate, and suggestion kind are internal terms.
22. Detectors create internal Candidates. The Manager evaluates evidence,
    relevance, quality, collisions, and budget. Only Manager-approved
    Candidates become user-facing Feedback.
23. Machine Feedback appears immediately after processing. Coach review is
    asynchronous and never blocks the next Take.
24. A Take surfaces at most three Feedback items. Confident Voice occupies the
    first position when any defensible candidate exists. When all families
    have evidence, prefer one of each. An unsupported family yields its slot
    to the strongest supported family, so repeated families are allowed.
    Fewer than three is valid; feedback is never manufactured.
25. Strong, data-backed feedback ranks before uncertain feedback. A defensible
    lower-confidence item may fill unused capacity with calibrated Possible
    language. Exaggerated praise is forbidden.
26. After the first Confident Voice position, useful cross-slide coverage is
    preferred unless a same-slide candidate is materially stronger or more
    important.
27. Rewrite for Clarity is reserved for wording that materially harms
    comprehension, structure, meaning, or the intended call to action. Cosmetic
    polish does not consume this family.
28. Every surfaced Feedback item references exact Project, Take, Slide,
    Paragraph, and evidence span. Confident Voice additionally requires a
    playable audio interval. Great Formulation and Rewrite for Clarity do not.

## 5. Confidence, learning provenance, and Voice Album

29. A user's Confident Voice Yes/No answer is separate from anchor acceptance.
    Yes permits a later Use as anchor choice. No blocks project styling and
    receives a neutral acknowledgement. Either answer may offer optional
    micro-practice when acoustically relevant.
30. Owner confidence answers are routing and personalization signals. They may
    provide the owner leg of Voice Album eligibility, but never become blind
    peer labels, coach labels, model-training ground truth, or
    model-correctness votes.
31. Machine prediction, blind human rating, anchored owner route, nonblind
    model review, coach judgment, and detector verdict are separate provenance
    types and are never stored under one semantic label.
32. An exact clip or selected practice attempt enters the Voice Album only
    when Machine Yes, User Yes, and Coach Yes independently refer to that same
    recording. Signals cannot be transferred between recordings.
33. Saving a practice attempt never admits it directly. The coach judges the
    selected practice attempt itself.
34. User Yes / Coach Yes admits silently. User No / Coach Yes may later become
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
