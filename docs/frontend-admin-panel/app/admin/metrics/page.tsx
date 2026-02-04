"use client";

import { useCallback, useEffect, useState } from "react";
import SectionCard from "@/components/admin/SectionCard";
import { adminApi, type MetricQuestion } from "@/lib/api/admin-client";
import { toast } from "sonner";

export default function AdminMetricsPage() {
  const [questions, setQuestions] = useState<MetricQuestion[]>([]);
  const [loading, setLoading] = useState(true);
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<MetricQuestion | null>(null);
  const [form, setForm] = useState({ position: 1 as 1 | 2, text: "" });

  const load = useCallback(() => {
    setLoading(true);
    adminApi
      .getMetricQuestions()
      .then(setQuestions)
      .catch((e) => toast.error(e.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => load(), [load]);

  const openCreate = (position: 1 | 2) => {
    setEditing(null);
    setForm({ position, text: "" });
    setModalOpen(true);
  };

  const openEdit = (q: MetricQuestion) => {
    setEditing(q);
    setForm({ position: q.position, text: q.text });
    setModalOpen(true);
  };

  const save = () => {
    if (!form.text.trim()) {
      toast.error("Question text is required");
      return;
    }
    if (editing) {
      adminApi
        .updateMetricQuestion(editing.id, { text: form.text.trim() })
        .then(() => {
          toast.success("Metric question updated");
          setModalOpen(false);
          load();
        })
        .catch((e) => toast.error(e.message));
    } else {
      adminApi
        .createMetricQuestion({ position: form.position, text: form.text.trim() })
        .then(() => {
          toast.success("Metric question added");
          setModalOpen(false);
          load();
        })
        .catch((e) => toast.error(e.message));
    }
  };

  const remove = (id: string) => {
    if (!confirm("Delete this metric question?")) return;
    adminApi
      .deleteMetricQuestion(id)
      .then(() => {
        toast.success("Metric question deleted");
        load();
      })
      .catch((e) => toast.error(e.message));
  };

  if (loading) return <p className="text-muted-foreground">Loading…</p>;

  const q1 = questions.find((q) => q.position === 1);
  const q2 = questions.find((q) => q.position === 2);

  return (
    <div className="space-y-6">
      <h1 className="text-3xl font-bold">Metrics</h1>

      <SectionCard
        title="Metric questions"
        description="Two questions (metric_question_1, metric_question_2) shown in the AI-generated task block after recording_1. Used with context_short + focus_task."
        action={null}
      >
        <div className="space-y-4">
          <div>
            <p className="mb-2 text-sm font-medium">Question 1 (position 1)</p>
            {q1 ? (
              <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border bg-muted/30 px-4 py-3">
                <p className="text-sm">{q1.text}</p>
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() => openEdit(q1)}
                    className="rounded-md border border-input px-3 py-1.5 text-sm hover:bg-muted"
                  >
                    Edit
                  </button>
                  <button
                    type="button"
                    onClick={() => remove(q1.id)}
                    className="rounded-md px-3 py-1.5 text-sm text-destructive hover:bg-destructive/10"
                  >
                    Delete
                  </button>
                </div>
              </div>
            ) : (
              <button
                type="button"
                onClick={() => openCreate(1)}
                className="rounded-md border border-dashed border-border px-4 py-2 text-sm text-muted-foreground hover:bg-muted"
              >
                Add question 1
              </button>
            )}
          </div>
          <div>
            <p className="mb-2 text-sm font-medium">Question 2 (position 2)</p>
            {q2 ? (
              <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border bg-muted/30 px-4 py-3">
                <p className="text-sm">{q2.text}</p>
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() => openEdit(q2)}
                    className="rounded-md border border-input px-3 py-1.5 text-sm hover:bg-muted"
                  >
                    Edit
                  </button>
                  <button
                    type="button"
                    onClick={() => remove(q2.id)}
                    className="rounded-md px-3 py-1.5 text-sm text-destructive hover:bg-destructive/10"
                  >
                    Delete
                  </button>
                </div>
              </div>
            ) : (
              <button
                type="button"
                onClick={() => openCreate(2)}
                className="rounded-md border border-dashed border-border px-4 py-2 text-sm text-muted-foreground hover:bg-muted"
              >
                Add question 2
              </button>
            )}
          </div>
        </div>
      </SectionCard>

      {modalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="w-full max-w-lg rounded-xl bg-card p-6 shadow-lg">
            <h2 className="text-lg font-semibold">{editing ? "Edit metric question" : "New metric question"}</h2>
            <div className="mt-4 space-y-4">
              {!editing && (
                <div>
                  <label className="mb-2 block text-sm font-medium">Position</label>
                  <select
                    className="h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                    value={form.position}
                    onChange={(e) => setForm((p) => ({ ...p, position: parseInt(e.target.value, 10) as 1 | 2 }))}
                  >
                    <option value={1}>1 (metric_question_1)</option>
                    <option value={2}>2 (metric_question_2)</option>
                  </select>
                </div>
              )}
              <div>
                <label className="mb-2 block text-sm font-medium">Question text</label>
                <textarea
                  className="min-h-[80px] w-full rounded-md border border-input px-3 py-2 text-sm"
                  rows={2}
                  value={form.text}
                  onChange={(e) => setForm((p) => ({ ...p, text: e.target.value }))}
                />
              </div>
            </div>
            <div className="mt-6 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setModalOpen(false)}
                className="rounded-md border border-input px-4 py-2 text-sm hover:bg-muted"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={save}
                className="rounded-md bg-[hsl(24_95%_53%)] px-4 py-2 text-sm font-medium text-white hover:opacity-90"
              >
                Save
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
