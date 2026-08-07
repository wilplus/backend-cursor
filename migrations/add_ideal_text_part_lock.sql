-- 0256 · ideal_text_part.locked_at — the lock, and therefore the layer.
--
-- SPEC-parts-locking-and-layers §3.1 / §4, PR 3. Step 0 (0255) deliberately
-- shipped identity WITHOUT this column, so the schema never claimed a
-- capability the code did not have. This is that capability arriving.
--
-- ── ONE NULLABLE TIMESTAMP IS THE WHOLE FEATURE ─────────────────────────────
--
-- §4:  allowed_layer(part) = part.locked_at IS NULL ? 'composition'
--                                                   : 'accentuation'
--
-- THE PHASE IS NEVER STORED. There is no `phase` column here and there must
-- not be one: a stored phase can desync from the lock that is supposed to
-- imply it, and then two places disagree about whether a rewrite is legal on
-- this paragraph. A derived one cannot. Deriving it also buys progressive
-- locking (part 1 locked while part 2 is open) with no special case at all —
-- it is simply what per-part state means.
--
-- A TIMESTAMP, NOT A BOOLEAN, and the difference is not decoration. §6 turns
-- decisions into the only ground truth this product will ever collect about
-- manager-engine precision, and "when did this part stop accepting rewrites"
-- is what makes an intervention's decision interpretable afterwards — a
-- disregard BEFORE the lock and one after it mean different things. A boolean
-- throws that away and cannot be reconstructed.
--
-- ── UNLOCK IS AN UPDATE TO NULL, NOT A NEW ROW (R5) ─────────────────────────
--
-- The cognitive cost of a permanent mistake during practice is too high, so
-- unlocking is allowed and simply clears the column. That does lose the
-- previous lock time. Accepted deliberately: the lock is a live UI state, not
-- an audit trail, and the thing §6 actually needs recorded is the DECISION on
-- each intervention — which lives on its own row and is never rewritten by a
-- lock or an unlock.
--
-- Idempotent. Safe to re-run. Non-destructive: additive nullable column, and
-- every existing row reads as 'composition', which is exactly where a
-- document that has never been locked should be.

BEGIN;

ALTER TABLE public.ideal_text_part
    ADD COLUMN IF NOT EXISTS locked_at TIMESTAMPTZ NULL;

-- The read PR 3 actually performs: "which parts of this document are locked".
-- Partial, because the locked set is the small one and the question is never
-- asked the other way round.
CREATE INDEX IF NOT EXISTS idx_ideal_text_part_locked
    ON public.ideal_text_part (arc_id, user_id)
    WHERE locked_at IS NOT NULL;

COMMENT ON COLUMN public.ideal_text_part.locked_at IS
    'NULL = open (composition: interventions may change the words). NOT NULL '
    '= locked (accentuation: interventions may only style words already '
    'there). SPEC §4 — the PHASE IS DERIVED FROM THIS AND NEVER STORED, so it '
    'cannot desync. A timestamp rather than a boolean because a decision made '
    'before the lock and one made after it mean different things, and §6 '
    'depends on telling them apart.';

COMMIT;
