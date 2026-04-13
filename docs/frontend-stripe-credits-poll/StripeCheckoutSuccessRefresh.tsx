/**
 * Copy to e.g. src/components/billing/StripeCheckoutSuccessRefresh.tsx
 * Use on your Stripe success_url page (client component).
 *
 * In the route that creates Checkout, before redirect, set sessionStorage:
 *   import { PRE_CHECKOUT_CREDITS_KEY } from "@/lib/homework/pollCreditsAfterCheckout";
 *   sessionStorage.setItem(PRE_CHECKOUT_CREDITS_KEY, String(currentCredits));
 */
"use client";

import { useEffect, useState } from "react";
import { pollCreditsAfterCheckout } from "@/lib/homework/pollCreditsAfterCheckout";

export function StripeCheckoutSuccessRefresh(props: {
  onCredits?: (credits: number) => void;
  onDone?: (result: { credits: number | null; pending: boolean }) => void;
}) {
  const { onCredits, onDone } = props;
  const [label, setLabel] = useState("Updating your balance…");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const result = await pollCreditsAfterCheckout();
      if (cancelled) return;
      if (result.ok) {
        setLabel(`Credits: ${result.credits}`);
        onCredits?.(result.credits);
        onDone?.({ credits: result.credits, pending: false });
        return;
      }
      setLabel("Could not refresh credits — open Homework or refresh the page.");
      onDone?.({ credits: null, pending: true });
    })();
    return () => {
      cancelled = true;
    };
  }, [onCredits, onDone]);

  return <p className="text-sm text-muted-foreground">{label}</p>;
}
