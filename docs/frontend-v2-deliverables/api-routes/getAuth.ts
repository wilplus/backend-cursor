/**
 * Copy to src/app/api/v2/getAuth.ts (or keep a shared auth helper).
 * Implement with your Supabase server API (e.g. createServerComponentClient or getSession).
 * This file is used by all v2 route handlers to get the Bearer token.
 */
import { cookies } from "next/headers";

export async function getV2AccessToken(): Promise<string | null> {
  // Example: Supabase SSR with cookies. Replace with your actual auth.
  const { createServerClient } = await import("@supabase/ssr");
  const cookieStore = await cookies();
  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        get(name: string) {
          return cookieStore.get(name)?.value;
        },
      },
    }
  );
  const { data: { session } } = await supabase.auth.getSession();
  return session?.access_token ?? null;
}

export function getBackendUrl(): string {
  const url = process.env.NEXT_PUBLIC_BACKEND_URL || process.env.BACKEND_URL || "http://localhost:5000";
  return url.replace(/\/$/, "");
}
