/**
 * Copy to src/app/api/getAuth.ts (or your auth helper). Used by all BFF routes.
 */
import { cookies } from "next/headers";

export async function getV2AccessToken(): Promise<string | null> {
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
