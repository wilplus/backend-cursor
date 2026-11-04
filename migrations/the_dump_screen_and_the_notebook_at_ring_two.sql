-- the_dump_screen_and_the_notebook_at_ring_two (founder 2026-11-04, N507:
-- "Ok set it yourself", then "Both at ring 2"; the dump screen N506; rules:
-- frontend docs/flows/principles.md)
--
-- Two ring rows at ring 2:
--
--   dump_screen     The dump screen (N506): one screen that only listens,
--                   tap to start, tap to stop, double tap to close. New row.
--   voice_notebook  The notebook the dump screen writes into (N194, N411).
--                   Made at ring 6 by a_voice_notebook_keeps_the_founders_notes;
--                   N507 item 3 brings it down to ring 2 with the dump screen.
--
-- dump_screen: made only if the founder has not made it already (ON CONFLICT
-- DO NOTHING), with its first audit entry (NOT EXISTS), as N264's migration
-- did. voice_notebook: lowered to 2 only while it is above 2 and not killed,
-- so a kill or a lower ring the founder set stays as it is; the change gets
-- its audit entry in the same statement. No table is created or changed.
-- Nothing dropped. No environment variable needed. Idempotent; one
-- transaction.

BEGIN;

INSERT INTO public.feature_rings (feature, min_ring, note, changed_by)
VALUES ('dump_screen', 2,
        'The dump screen (N506, N507): one screen that only listens, the '
        'voice notebook''s way in; "Open to the dump screen" in Settings.',
        'migration:the_dump_screen_and_the_notebook_at_ring_two')
ON CONFLICT (feature) DO NOTHING;

INSERT INTO public.feature_ring_changes
    (feature, min_ring, attribute_rule, consent_purpose, killed, one_way, note,
     changed_by, changed_at)
SELECT f.feature, f.min_ring, f.attribute_rule, f.consent_purpose, f.killed,
       f.one_way, f.note, f.changed_by, f.changed_at
  FROM public.feature_rings f
 WHERE f.feature = 'dump_screen'
   AND NOT EXISTS (SELECT 1 FROM public.feature_ring_changes c
                    WHERE c.feature = f.feature);

WITH lowered AS (
    UPDATE public.feature_rings
       SET min_ring = 2,
           changed_by = 'migration:the_dump_screen_and_the_notebook_at_ring_two',
           changed_at = now()
     WHERE feature = 'voice_notebook'
       AND min_ring > 2
       AND NOT killed
    RETURNING feature, min_ring, attribute_rule, consent_purpose, killed,
              one_way, note, changed_by, changed_at
)
INSERT INTO public.feature_ring_changes
    (feature, min_ring, attribute_rule, consent_purpose, killed, one_way, note,
     changed_by, changed_at)
SELECT feature, min_ring, attribute_rule, consent_purpose, killed, one_way,
       note, changed_by, changed_at
  FROM lowered;

COMMIT;
