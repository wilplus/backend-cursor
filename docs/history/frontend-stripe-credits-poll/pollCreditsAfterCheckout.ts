/**
 * Copy into your Next.js app (e.g. src/lib/homework/pollCreditsAfterCheckout.ts).
 *
 * Before redirecting to Stripe Checkout, store the current balance:
 *   sessionStorage.setItem(PRE_CHECKOUT_CREDITS_KEY, String(credits));
 *
 * On success, pass checkoutSessionId from the URL (?session_id=cs_...) so the
 * client calls POST /v2/homework/stripe/claim-checkout first (instant); polling
 * is only a fallback if that fails.
 */

export const PRE_CHECKOUT_CREDITS_KEY = "homework_credits_before_checkout";

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export type PollCreditsResult =
  | { ok: true; credits: number }
  | { ok: false; reason: "unauthorized" | "timeout" | "bad_response" };

/** Prefer this on the success page when ?session_id=cs_... is present. */
export async function claimStripeCheckoutCredits(
  checkoutSessionId: string,
  claimPath = "/api/homework/stripe/claim-checkout",
): Promise<
  | { ok: true; credits: number; duplicate?: boolean }
  | { ok: false; status: number; body: unknown }
> {
  const res = await fetch(claimPath, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ checkout_session_id: checkoutSessionId }),
  });
  let data: unknown = {};
  try {
    data = await res.json();
  } catch {
    data = {};
  }
  if (!res.ok) {
    return { ok: false, status: res.status, body: data };
  }
  const d = data as { credits?: unknown; duplicate?: unknown };
  const credits =
    typeof d.credits === "number" ? d.credits : Number(d.credits);
  if (!Number.isFinite(credits)) {
    return { ok: false, status: res.status, body: data };
  }
  return {
    ok: true,
    credits,
    duplicate: Boolean(d.duplicate),
  };
}

export async function pollCreditsAfterCheckout(options?: {
  intervalMs?: number;
  maxWaitMs?: number;
  statusPath?: string;
  /** From Stripe success_url (?session_id=) — triggers immediate server-side grant */
  checkoutSessionId?: string;
}): Promise<PollCreditsResult> {
  const intervalMs = options?.intervalMs ?? 1000;
  const maxWaitMs = options?.maxWaitMs ?? 30000;
  const statusPath = options?.statusPath ?? "/api/homework/session/status";
  const cs = (options?.checkoutSessionId ?? "").trim();

  if (cs) {
    const claimed = await claimStripeCheckoutCredits(cs);
    if (claimed.ok) {
      if (typeof window !== "undefined") {
        window.sessionStorage.removeItem(PRE_CHECKOUT_CREDITS_KEY);
      }
      return { ok: true, credits: claimed.credits };
    }
  }

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
