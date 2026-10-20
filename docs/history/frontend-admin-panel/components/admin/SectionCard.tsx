"use client";

import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";

interface SectionCardProps {
  title: string;
  description?: string;
  action?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}

export default function SectionCard({
  title,
  description,
  action,
  children,
  className,
}: SectionCardProps) {
  return (
    <Card className={cn("rounded-xl bg-card p-6 shadow-sm", className)}>
      <div className="space-y-1">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <h2 className="text-lg font-semibold">{title}</h2>
          {action != null && <div className="flex items-center gap-2">{action}</div>}
        </div>
        {description != null && (
          <p className="text-sm text-muted-foreground">{description}</p>
        )}
      </div>
      <div className="mt-4">{children}</div>
    </Card>
  );
}
