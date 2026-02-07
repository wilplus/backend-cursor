"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Users } from "lucide-react";
import { cn } from "@/lib/utils";

// Only Students tab. Tasks, questions, metrics are managed inside each student profile (modals), not as separate tabs.
const nav = [
  { href: "/admin/students", label: "Students", icon: Users },
];

export default function AdminShell({
  children,
  email,
  onLogout,
}: {
  children: React.ReactNode;
  email?: string | null;
  onLogout?: () => void;
}) {
  const pathname = usePathname();

  return (
    <div className="min-h-screen bg-[hsl(0_0%_99%)]">
      <header className="sticky top-0 z-10 h-14 border-b border-[hsl(220_13%_91%)] bg-card/80 backdrop-blur supports-[backdrop-filter]:bg-card/60">
        <div className="mx-auto flex h-full max-w-6xl items-center justify-between gap-4 px-4 md:px-6">
          <span className="text-lg font-bold text-foreground">Admin</span>
          <nav className="flex flex-1 items-center justify-center gap-1 overflow-x-auto py-2 md:overflow-visible">
            {nav.map(({ href, label, icon: Icon }) => (
              <Link
                key={href}
                href={href}
                className={cn(
                  "flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium transition-all",
                  pathname === href || pathname.startsWith(href + "/")
                    ? "bg-[hsl(24_100%_97%)] text-[hsl(24_95%_40%)]"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground"
                )}
              >
                <Icon className="h-4 w-4 shrink-0" />
                {label}
              </Link>
            ))}
          </nav>
          <div className="flex items-center gap-2">
            {email && (
              <span className="hidden max-w-[180px] truncate text-sm text-muted-foreground sm:inline">
                {email}
              </span>
            )}
            {onLogout && (
              <button
                type="button"
                onClick={onLogout}
                className="rounded-md border border-input bg-background px-3 py-2 text-sm font-medium hover:bg-muted"
              >
                Logout
              </button>
            )}
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-6xl p-4 md:p-6">
        <div className="animate-fade-in">{children}</div>
      </main>
    </div>
  );
}
