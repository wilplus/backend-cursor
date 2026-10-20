# MLC-3 Confident Moment Coaching Bundle — Speaker-Binding Authorization D48

Status: proposed final authorization closure. D48 retains D38–D47 except where
strengthened here. No gate, dataset, or learning change.

Before comparing speakers, the internal root-practice guard requires both
opaque binding IDs to belong to the acting acquisition principal. It freshly
reruns that principal's exact current Bundle-to-offer correlation and requires
`source_target_speaker_binding_id` to equal the sole value derived by that
current `available` result. It separately derives the submitted practice
attempt's current acquisition revision and requires
`practice_target_speaker_binding_id` to be that attempt's sole latest active,
resolved, non-superseded binding owned by the same principal. Only after these
authorization predicates pass may it compare their canonical speaker IDs.

Foreign ownership, substitution from another Bundle/offer or practice attempt,
stale/superseded identity, correlation drift, or any cardinality failure is
typed projection invalidity, never `not_supplied`, and creates no root action or
other record. Tests independently substitute each binding from another
principal, including bindings resolving to the same canonical speaker, and
require atomic rejection. Existing ordered locks and post-contention/replay
revalidation cover the complete derivation.

All D38–D47 read-only correlation, same-speaker, no-learning, privacy and
literal-default-off clauses remain in force. The migration stays unnumbered and
unmanifested.
