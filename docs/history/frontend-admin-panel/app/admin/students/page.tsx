"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { adminApi, type StudentListItem } from "@/lib/api/admin-client";

export default function AdminStudentsPage() {
  const [students, setStudents] = useState<StudentListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    adminApi
      .getStudents({ limit: 50, offset: 0 })
      .then((res) => setStudents(res.students))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <p className="text-muted-foreground">Loading students…</p>;
  if (error) return <p className="text-destructive">Error: {error}</p>;

  return (
    <div className="space-y-6">
      <h1 className="text-3xl font-bold">Students</h1>
      <ul className="space-y-2">
        {students.length === 0 ? (
          <li className="text-sm text-muted-foreground">No students yet.</li>
        ) : (
          students.map((s) => (
            <li key={s.user_id}>
              <Link
                href={`/admin/students/${s.user_id}`}
                className="block rounded-xl border border-border bg-card p-4 shadow-sm transition-colors hover:bg-muted/50"
              >
                <span className="font-medium">{s.user_id}</span>
                <span className="ml-2 text-sm text-muted-foreground">(view profile)</span>
              </Link>
            </li>
          ))
        )}
      </ul>
    </div>
  );
}
