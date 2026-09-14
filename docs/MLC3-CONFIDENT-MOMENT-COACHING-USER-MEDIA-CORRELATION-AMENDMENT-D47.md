# MLC-3 Confident Moment Coaching Bundle — Exercise Source Speaker Amendment D47

Status: proposed narrow interface closure. D47 retains D38–D46 except where
extended here. No gate, dataset, or learning change.

The `available` result of `resolve_confident_moment_exercise_offer_v1` adds one
required UUID field: `source_target_speaker_binding_id`. PostgreSQL derives it
from the exact correlated offer's source audio/acquisition lineage. Under the
existing correlation serializers it requires exactly one latest active,
resolved, non-superseded target-speaker binding for the exact source recording
attempt and current acquisition revision. Missing, duplicate, stale,
superseded, unresolved, foreign, or changed lineage fails closed as projection
invalidity; it is never `not_supplied`. The structural `not_supplied` response
is unchanged and does not contain this field.

After practice self-speaker confirmation, the canonical existing response
supplies the separate `practice_target_speaker_binding_id`. The browser may pass
these two opaque exact IDs with the selected practice attempt to the existing
`save_owner_selected_root` source matrix. It may not derive, substitute, or
equate them. The root mutation's existing internal live-source guard remains
authoritative and revalidates both latest binding revisions and same-speaker
identity after contention and on replay.

Regressions prove exact available mapping, structural not-supplied shape,
missing/superseded/foreign source binding rejection, correlation/binding race in
both orders, hard-reload preservation, and successful practice selection using
the exact source plus practice binding IDs. No pair, preference, judgment,
improvement, adequacy, dataset, or learning record is created by correlation.

All D38–D46 privacy, currentness, same-speaker, read-only, no-offer-creation and
literal-default-off clauses remain in force. The migration stays unnumbered and
unmanifested.
