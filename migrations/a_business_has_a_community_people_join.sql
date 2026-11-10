-- a_business_has_a_community_people_join (matching, settled: the business is
-- the pool; founder, the Claude Code chat, 9 November 2026, N559 item 1,
-- with N572's tree: "a member's link whose business has a community: Join /
-- Not now")
--
-- Someone new for a Take comes from the speaker's business community, and
-- joining is how a person belongs to it (N559 item 1). The matcher read the
-- passcode communities (community_members), which N471 retired: a bug to
-- fix (N95). Three tables, read only by the matcher and the offer's routes:
--
--   business_communities         One per business: its name and the account
--                                that holds it (owner_id), its first member;
--                                empty once that account is gone.
--                                Made by the founder from the admin route
--                                until a screen makes them.
--   business_community_members   Who joined (Join), and when. Only these
--                                people are suggested to each other as
--                                someone new after a Take.
--   business_community_offers    The newcomer's one offer (N559 item 1):
--                                the community of the business of the person
--                                whose link they came by (inviter_id), asked
--                                once, while Take 1 is processed; answer
--                                'joined' or 'not_now'. Not now is never
--                                asked again on its own (one row per person
--                                and community).
--
-- Nothing is a number on screen and nothing is a recording. Service role
-- only, nothing for anon or authenticated.
--
-- Every person is an account id with a foreign key to auth.users, so the
-- database itself keeps the rule (outside review, Grok, 10 November 2026;
-- services/data_purge_registry.py does the same on erasure):
--   a member's row and an offer's row go with that person's account
--   (ON DELETE CASCADE);
--   an offer's inviter is cleared when the inviter's account goes
--   (ON DELETE SET NULL): the offer and its answer stay the newcomer's;
--   a community outlives its owner: owner_id is cleared, the community and
--   its members stay (ON DELETE SET NULL, so owner_id may be empty).
--
-- No environment variable, no ring row: until rows exist the routes answer
-- as if nobody had joined, and nobody new is suggested.
--
-- Idempotent and additive: CREATE ... IF NOT EXISTS; nothing is dropped and
-- no existing row is written, rewritten or removed. One transaction.
--
-- Rollback (a new forward migration): leave it; dropping it is a separate,
-- previewed retention operation.

BEGIN;

CREATE TABLE IF NOT EXISTS public.business_communities (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id    UUID REFERENCES auth.users (id) ON DELETE SET NULL,
    name        TEXT NOT NULL CHECK (char_length(btrim(name)) BETWEEN 1 AND 80),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    closed_at   TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS business_communities_by_owner
    ON public.business_communities (owner_id);

CREATE TABLE IF NOT EXISTS public.business_community_members (
    community_id UUID NOT NULL
                 REFERENCES public.business_communities (id) ON DELETE CASCADE,
    user_id      UUID NOT NULL REFERENCES auth.users (id) ON DELETE CASCADE,
    joined_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (community_id, user_id)
);
CREATE INDEX IF NOT EXISTS business_community_members_by_user
    ON public.business_community_members (user_id);

CREATE TABLE IF NOT EXISTS public.business_community_offers (
    user_id      UUID NOT NULL REFERENCES auth.users (id) ON DELETE CASCADE,
    community_id UUID NOT NULL
                 REFERENCES public.business_communities (id) ON DELETE CASCADE,
    inviter_id   UUID REFERENCES auth.users (id) ON DELETE SET NULL,
    answer       TEXT CHECK (answer IS NULL OR answer IN ('joined', 'not_now')),
    offered_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    answered_at  TIMESTAMPTZ,
    PRIMARY KEY (user_id, community_id)
);
CREATE INDEX IF NOT EXISTS business_community_offers_by_inviter
    ON public.business_community_offers (inviter_id);

ALTER TABLE public.business_communities ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.business_community_members ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.business_community_offers ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.business_communities FROM PUBLIC, anon, authenticated;
REVOKE ALL ON TABLE public.business_community_members FROM PUBLIC, anon, authenticated;
REVOKE ALL ON TABLE public.business_community_offers FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.business_communities TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.business_community_members TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.business_community_offers TO service_role;

COMMIT;
