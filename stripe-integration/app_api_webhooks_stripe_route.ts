/**
 * Stripe Webhook handler
 * Place this file at: app/api/webhooks/stripe/route.ts
 *
 * Required env vars:
 *   STRIPE_SECRET_KEY                  - from Stripe Dashboard > Developers > API Keys
 *   STRIPE_WEBHOOK_SECRET              - from Stripe Dashboard > Developers > Webhooks > your endpoint > Signing secret
 *   INTERNAL_CREDITS_WEBHOOK_SECRET    - shared secret with the backend (same value as backend env var)
 *   BACKEND_URL                        - your Flask backend base URL (e.g. https://your-backend.com)
 *
 * Register in Stripe Dashboard:
 *   Developers → Webhooks → Add endpoint
 *   URL: https://your-app.com/api/webhooks/stripe
 *   Event: checkout.session.completed
 */
import Stripe from 'stripe';
import { NextRequest, NextResponse } from 'next/server';

const stripe = new Stripe(process.env.STRIPE_SECRET_KEY!);

/**
 * Must match exactly what's in app/api/stripe/checkout/route.ts
 */
const CREDIT_PACKS: Record<string, number> = {
  'price_REPLACE_WITH_5_LESSON_PRICE_ID':  5,
  'price_REPLACE_WITH_10_LESSON_PRICE_ID': 10,
  'price_REPLACE_WITH_20_LESSON_PRICE_ID': 20,
};

export async function POST(req: NextRequest) {
  const body = await req.text();
  const sig  = req.headers.get('stripe-signature');

  if (!sig) {
    return NextResponse.json({ error: 'Missing stripe-signature header' }, { status: 400 });
  }

  // 1. Verify the request genuinely came from Stripe
  let event: Stripe.Event;
  try {
    event = stripe.webhooks.constructEvent(body, sig, process.env.STRIPE_WEBHOOK_SECRET!);
  } catch (err) {
    console.error('[stripe-webhook] Signature verification failed:', err);
    return NextResponse.json({ error: 'Invalid signature' }, { status: 400 });
  }

  // 2. Only act on successful payments
  if (event.type === 'checkout.session.completed') {
    const session = event.data.object as Stripe.Checkout.Session;

    const userId  = session.metadata?.user_id;
    const priceId = session.metadata?.price_id;
    const delta   = priceId ? CREDIT_PACKS[priceId] : undefined;

    if (!userId || !delta) {
      // Log but return 200 so Stripe doesn't keep retrying
      console.error('[stripe-webhook] Missing metadata in session', session.id, { userId, priceId });
      return NextResponse.json({ received: true, warning: 'Missing metadata — credits not added' });
    }

    // 3. Tell the backend to increment this student's credits
    const backendRes = await fetch(
      `${process.env.BACKEND_URL}/v2/internal/student-credits/increment`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-Internal-Secret': process.env.INTERNAL_CREDITS_WEBHOOK_SECRET!,
        },
        body: JSON.stringify({ user_id: userId, delta }),
      }
    );

    if (!backendRes.ok) {
      const text = await backendRes.text();
      console.error('[stripe-webhook] Backend credit increment failed:', backendRes.status, text);
      // Return 500 so Stripe retries (it will retry up to ~3 days)
      return NextResponse.json({ error: 'Backend failed' }, { status: 500 });
    }

    const result = await backendRes.json();
    console.log(`[stripe-webhook] Added ${delta} credits to user ${userId}. New balance: ${result.credits}`);
  }

  return NextResponse.json({ received: true });
}
