-- Idempotency for Stripe Checkout → homework credits (one row per completed checkout session).
-- Run in Supabase SQL Editor. Backend uses service role (bypasses RLS).

CREATE TABLE IF NOT EXISTS public.stripe_checkout_credit_grants (
  checkout_session_id text PRIMARY KEY,
  created_at timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE public.stripe_checkout_credit_grants IS
  'Prevents double-crediting when Stripe retries checkout.session.completed webhooks.';

ALTER TABLE public.stripe_checkout_credit_grants ENABLE ROW LEVEL SECURITY;
