/**
 * Copy into your Next.js app (e.g. src/lib/homework/pollCreditsAfterCheckout.ts).
 *
 * Before redirecting to Stripe Checkout, store the current balance:
 *   sessionStorage.setItem(PRE_CHECKOUT_CREDITS_KEY, String(credits));
 *
 * On the Checkout success page, call pollCreditsAfterCheckout() so the UI
 * catches the webhook as soon as Supabase reflects the new balance.
 */

export const PRE_CHECKOUT_CREDITS_KEY = "homework_credits_before_checkout";

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export type PollCreditsResult =
  | { ok: true; credits: number }
  | { ok: false; reason: "unauthorized" | "timeout" | "bad_response" };

export async function pollCreditsAfterCheckout(options?: {
  intervalMs?: number;
  maxWaitMs?: number;
  statusPath?: string;
}): Promise<PollCreditsResult> {
  const intervalMs = options?.intervalMs ?? 1000;
  const maxWaitMs = options?.maxWaitMs ?? 30000;
  const statusPath = options?.statusPath ?? "/api/homework/session/status";

  const rawPrev =
    typeof window !== "undefined"
      ? window.sessionStorage.getItem(PRE_CHECKOUT_CREDITS_KEY)
      : null;
  const previousCredits =
    rawPrev !== null && rawPrev !== "" ? Number(rawPrev) : NaN;
  const hasPrevious = Number.isFinite(previousCredits);

  const deadline = Date.now() + maxWaitMs;
  let lastCredits: number | null = null;

  while (Date.now() < deadline) {
    const res = await fetch(statusPath, { credentials: "include" });
    if (res.status === 401) {
      return { ok: false, reason: "unauthorized" };
    }
    if (!res.ok) {
      await sleep(intervalMs);
      continue;
    }
    const data = (await res.json()) as { credits?: unknown };
    const c =
      typeof data.credits === "number"
        ? data.credits
        : Number(data.credits);
    if (!Number.isFinite(c)) {
      return { ok: false, reason: "bad_response" };
    }
    lastCredits = c;

    if (hasPrevious && c > previousCredits) {
      window.sessionStorage.removeItem(PRE_CHECKOUT_CREDITS_KEY);
      return { ok: true, credits: c };
    }

    await sleep(intervalMs);
  }

  window.sessionStorage.removeItem(PRE_CHECKOUT_CREDITS_KEY);
  if (lastCredits !== null) {
    return { ok: true, credits: lastCredits };
  }
  return { ok: false, reason: "timeout" };
}
