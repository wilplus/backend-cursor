"use client";

import { useCallback, useEffect, useState } from "react";
import SectionCard from "@/components/admin/SectionCard";
import { adminApi, type PostQuestion } from "@/lib/api/admin-client";
import { toast } from "sonner";

const ANSWER_TYPES = [
  { value: "yes_no", label: "Yes / No" },
  { value: "scale_1_5", label: "Scale 1–5" },
  { value: "text", label: "Text" },
] as const;

export default function AdminQuestionsPage() {
  const [questions, setQuestions] = useState<PostQuestion[]>([]);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<PostQuestion | null>(null);
  const [form, setForm] = useState({
    code: "",
    text: "",
    answer_type: "text" as "yes_no" | "scale_1_5" | "text",
    is_active: true,
  });

  const load = useCallback(() => {
    setLoading(true);
    adminApi
      .getPostQuestions()
      .then(setQuestions)
      .catch((e) => toast.error(e.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => load(), [load]);

  const openCreate = () => {
    setEditing(null);
    setForm({
      code: "",
      text: "",
      answer_type: "text",
      is_active: true,
    });
    setDialogOpen(true);
  };

  const openEdit = (q: PostQuestion) => {
    setEditing(q);
    setForm({
      code: q.code ?? "",
      text: q.text ?? "",
      answer_type: (q.answer_type as "yes_no" | "scale_1_5" | "text") || "text",
      is_active: q.is_active !== false,
    });
    setDialogOpen(true);
  };

  const save = () => {
    if (!form.text.trim()) {
      toast.error("Question text is required");
      return;
    }
    const payload = {
      text: form.text.trim(),
      answer_type: form.answer_type,
      is_active: form.is_active,
      ...(form.code.trim() ? { code: form.code.trim() } : {}),
    };
    if (editing) {
      adminApi
        .updatePostQuestion(editing.id, payload)
        .then(() => {
          toast.success("Question updated");
          setDialogOpen(false);
          load();
        })
        .catch((e) => toast.error(e.message));
    } else {
      adminApi
        .createPostQuestion(payload)
        .then(() => {
          toast.success("Question added");
          setDialogOpen(false);
          load();
        })
        .catch((e) => toast.error(e.message));
    }
  };

  const remove = (id: string) => {
    if (!confirm("Delete this question? It will be removed from the pool (students may have it assigned).")) return;
    adminApi
      .deletePostQuestion(id)
      .then(() => {
        toast.success("Question deleted");
        load();
      })
      .catch((e) => toast.error(e.message));
  };

  if (loading) return <p className="text-muted-foreground">Loading questions…</p>;

  return (
    <div className="space-y-6">
      <h1 className="text-3xl font-bold">Post-Recording Questions</h1>

      <SectionCard
        title="Question pool"
        description="Questions shown after a recording. Assign 0 or any number per student on their profile."
        action={
          <button
            type="button"
            onClick={openCreate}
            className="rounded-md bg-[hsl(24_95%_53%)] px-4 py-2 text-sm font-medium text-white hover:opacity-90"
          >
            Add question
          </button>
        }
      >
        <ul className="space-y-2">
          {questions.length === 0 ? (
            <li className="text-sm text-muted-foreground">No questions. Add one to assign to students.</li>
          ) : (
            questions.map((q) => (
              <li
                key={q.id}
                className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border bg-muted/30 px-4 py-3"
              >
                <div>
                  {q.code && (
                    <span className="mr-2 text-xs text-muted-foreground font-mono">{q.code}</span>
                  )}
                  <span className="font-medium">{q.text}</span>
                  <span className="ml-2 text-xs text-muted-foreground">({q.answer_type})</span>
                  {q.is_active === false && (
                    <span className="ml-2 text-xs text-muted-foreground">(inactive)</span>
                  )}
                </div>
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() => openEdit(q)}
                    className="rounded-md border border-input px-3 py-1.5 text-sm hover:bg-muted"
                  >
                    Edit
                  </button>
                  <button
                    type="button"
                    onClick={() => remove(q.id)}
                    className="rounded-md px-3 py-1.5 text-sm text-destructive hover:bg-destructive/10"
                  >
                    Delete
                  </button>
                </div>
              </li>
            ))
          )}
        </ul>
      </SectionCard>

      {dialogOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="w-full max-w-lg rounded-xl bg-card p-6 shadow-lg">
            <h2 className="text-lg font-semibold">{editing ? "Edit question" : "New question"}</h2>
            <div className="mt-4 space-y-4">
              <div>
                <label className="mb-2 block text-sm font-medium">Code (optional)</label>
                <input
                  className="h-10 w-full rounded-md border border-input px-3 py-2 text-sm"
                  placeholder="e.g. emotion_achieved_check"
                  value={form.code}
                  onChange={(e) => setForm((p) => ({ ...p, code: e.target.value }))}
                />
                <p className="mt-1 text-xs text-muted-foreground">Unique code for this question; leave empty to auto-generate.</p>
              </div>
              <div>
                <label className="mb-2 block text-sm font-medium">Question text</label>
                <textarea
                  className="min-h-[80px] w-full rounded-md border border-input px-3 py-2 text-sm"
                  rows={2}
                  value={form.text}
                  onChange={(e) => setForm((p) => ({ ...p, text: e.target.value }))}
                />
              </div>
              <div>
                <label className="mb-2 block text-sm font-medium">Answer type</label>
                <select
                  className="h-10 w-full rounded-md border border-input px-3 py-2 text-sm bg-background"
                  value={form.answer_type}
                  onChange={(e) =>
                    setForm((p) => ({ ...p, answer_type: e.target.value as "yes_no" | "scale_1_5" | "text" }))
                  }
                >
                  {ANSWER_TYPES.map(({ value, label }) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
              </div>
              {editing && (
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={form.is_active}
                    onChange={(e) => setForm((p) => ({ ...p, is_active: e.target.checked }))}
                  />
                  Active (available when assigning to students)
                </label>
              )}
            </div>
            <div className="mt-6 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setDialogOpen(false)}
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
