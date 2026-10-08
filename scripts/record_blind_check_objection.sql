-- Record a speaker's objection to the coach's blind accuracy check.
-- Privacy 3.4 §4 (founder 2026-10-08, N66.2): "You can object to it at any
-- time by writing to contact@willpowerlab.com: from then on no clip of yours
-- is chosen for a check. Objecting costs you nothing else."
--
-- RUN BY HAND IN THE SUPABASE SQL EDITOR (service role) when such an email
-- arrives. Put the sender's account email and your own name in the two
-- quoted values below. It records one objection per person and is safe to
-- run twice: a second run changes nothing and shows the first record. From
-- then on the blind check never samples a clip of that person, under any of
-- their principals (services/error_presence_audit.py, 0451). Nothing else
-- about their account changes: practice, feedback and coach review go on.
--
-- Expect ONE row with the principal and the time the objection was recorded.
-- No row: no account has that email; check the address and run it again.

SELECT public.record_blind_check_objection_v1(
         principal.id, 'founder: artur@willonski.com') AS recorded
  FROM public.owner_principals principal
  JOIN auth.users account ON account.id = principal.user_id
 WHERE lower(account.email) = lower('speaker@example.com');
