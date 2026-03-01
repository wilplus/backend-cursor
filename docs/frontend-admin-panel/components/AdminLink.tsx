"use client";

import Link from "next/link";

const ADMIN_EMAIL = "artur@willonski.com";

/**
 * Renders an "Admin" link to /admin only when the current user's email is the designated admin.
 * Use this in your main app layout next to the logo so that artur@willonski.com can reach the admin panel.
 */
export default function AdminLink({ email }: { email: string | null | undefined }) {
  if (!email || email !== ADMIN_EMAIL) return null;
  return (
    <Link
      href="/admin"
      className="rounded-md border border-input bg-background px-3 py-2 text-sm font-medium hover:bg-muted"
    >
      Admin
    </Link>
  );
}
