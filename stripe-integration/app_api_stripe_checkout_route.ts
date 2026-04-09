/**
 * Stripe Checkout endpoint
 * Place this file at: app/api/stripe/checkout/route.ts
 *
 * Required env vars:
 *   STRIPE_SECRET_KEY         - from Stripe Dashboard > Developers > API Keys
 *   NEXT_PUBLIC_APP_URL       - your app's base URL (e.g. https://your-app.com)
 */
import Stripe from 'stripe';
import { NextRequest, NextResponse } from 'next/server';

const stripe = new Stripe(process.env.STRIPE_SECRET_KEY!);

/**
 * Map your Stripe Price IDs to the number of credits to grant.
 * Replace the placeholder IDs with your real ones from the Stripe Dashboard.
 *
 * To find Price IDs: Stripe Dashboard → Products → click a product → copy the Price ID (price_...)
 */
const CREDIT_PACKS: Record<string, number> = {
  'price_REPLACE_WITH_5_LESSON_PRICE_ID':  5,
  'price_REPLACE_WITH_10_LESSON_PRICE_ID': 10,
  'price_REPLACE_WITH_20_LESSON_PRICE_ID': 20,
};

export async function POST(req: NextRequest) {
  const { priceId, userId } = await req.json();

  if (!priceId || !CREDIT_PACKS[priceId]) {
    return NextResponse.json({ error: 'Invalid price ID' }, { status: 400 });
  }
  if (!userId) {
    return NextResponse.json({ error: 'userId is required' }, { status: 400 });
  }

  const session = await stripe.checkout.sessions.create({
    mode: 'payment',
    line_items: [{ price: priceId, quantity: 1 }],
    metadata: {
      user_id: userId,   // Supabase user UUID — passed to webhook to credit the right student
      price_id: priceId, // Used by webhook to look up how many credits to add
    },
    success_url: `${process.env.NEXT_PUBLIC_APP_URL}/credits?success=true`,
    cancel_url:  `${process.env.NEXT_PUBLIC_APP_URL}/credits?cancelled=true`,
  });

  return NextResponse.json({ url: session.url });
}
