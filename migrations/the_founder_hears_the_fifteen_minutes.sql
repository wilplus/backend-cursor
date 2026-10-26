-- the_founder_hears_the_fifteen_minutes (founder 2026-10-26, N180: the app
-- is the proverbial 15 minutes a day; N183: "You first, then everyone")
--
-- One ring row, nothing else: fifteen_minutes at ring 6 (the founder's
-- ring). Once a day, after about 15 minutes in the app, Will says in the
-- chat "That's your 15 minutes for today." and "Now go and live it, away
-- from the phone." (services/fifteen_minutes.py). The founder moves the row
-- to everyone from the admin rings page.
--
-- No table, no environment variable. Idempotent: ON CONFLICT DO NOTHING and
-- a guarded audit row, as the voice notebook's and life goals' rows.

BEGIN;

INSERT INTO public.feature_rings (feature, min_ring, note, changed_by)
VALUES ('fifteen_minutes', 6,
        'N180, N183: the once-a-day line after about 15 minutes in the app '
        '("That''s your 15 minutes for today.").',
        'migration:the_founder_hears_the_fifteen_minutes')
ON CONFLICT (feature) DO NOTHING;

INSERT INTO public.feature_ring_changes
    (feature, min_ring, attribute_rule, consent_purpose, killed, one_way, note,
     changed_by, changed_at)
SELECT f.feature, f.min_ring, f.attribute_rule, f.consent_purpose, f.killed,
       f.one_way, f.note, f.changed_by, f.changed_at
  FROM public.feature_rings f
 WHERE f.feature = 'fifteen_minutes'
   AND NOT EXISTS (SELECT 1 FROM public.feature_ring_changes c
                    WHERE c.feature = f.feature);

COMMIT;
