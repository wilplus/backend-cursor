-- will_answers_worries_and_sales_at_ring_five (founder 2026-10-29, N264:
-- "Set the rings yourself."; the features N241 O and P, signed N258; rules:
-- frontend docs/flows/principles.md §1 O, P)
--
-- Two ring rows, at ring 5 (people who know it is a test):
--
--   in_control      Will's answer to a worry, under a # note's "Noted.":
--                   the worry sorted, ending on one thing in their control
--                   (services/in_control.py).
--   sales_framing   The sales steps: "Which step did it stall at?" under a
--                   sales note, and a sales week's Sunday note asks "Which
--                   step was it?" (services/sales_framing.py,
--                   services/sunday_note.py).
--
-- Until now each feature stayed off because its row did not exist; the
-- founder was to make the rows on the CEO panel's rings page (N241, N258).
-- N264 has this migration make them instead, with their first audit
-- entries, as 0498 did for your_why and strengths. A row the founder made in
-- the meantime stays exactly as it is (ON CONFLICT DO NOTHING), and its audit
-- trail is not touched (NOT EXISTS). No table is created or changed. No
-- environment variable needed. Idempotent; one transaction.

BEGIN;

INSERT INTO public.feature_rings (feature, min_ring, note, changed_by)
VALUES ('in_control', 5,
        'What is in your control (N241 O, signed N258): Will''s answer to a '
        'worry under a # note, ending on one thing in their control.',
        'migration:will_answers_worries_and_sales_at_ring_five'),
       ('sales_framing', 5,
        'The sales framing (N241 P, signed N258): the four steps under a '
        'sales note and in a sales week''s Sunday note.',
        'migration:will_answers_worries_and_sales_at_ring_five')
ON CONFLICT (feature) DO NOTHING;

-- The rows' first entries in their audit trail, as 0394 wrote for its seeds.
INSERT INTO public.feature_ring_changes
    (feature, min_ring, attribute_rule, consent_purpose, killed, one_way, note,
     changed_by, changed_at)
SELECT f.feature, f.min_ring, f.attribute_rule, f.consent_purpose, f.killed,
       f.one_way, f.note, f.changed_by, f.changed_at
  FROM public.feature_rings f
 WHERE f.feature IN ('in_control', 'sales_framing')
   AND NOT EXISTS (SELECT 1 FROM public.feature_ring_changes c
                    WHERE c.feature = f.feature);

COMMIT;
