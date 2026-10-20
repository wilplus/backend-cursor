"use client";

import { useCallback, useEffect, useState } from "react";
import SectionCard from "@/components/admin/SectionCard";
import { adminApi, type Exercise } from "@/lib/api/admin-client";
import { toast } from "sonner";

export default function AdminExercisesPage() {
  const [exercises, setExercises] = useState<Exercise[]>([]);
  const [loading, setLoading] = useState(true);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [editing, setEditing] = useState<Exercise | null>(null);
  const [form, setForm] = useState({
    title: "",
    video_url: "",
    description: "",
    min_task_score: 0,
    max_task_score: 1,
  });

  const load = useCallback(() => {
    setLoading(true);
    adminApi
      .getExercises()
      .then(setExercises)
      .catch((e) => toast.error(e.message))
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => load(), [load]);

  const openCreate = () => {
    setEditing(null);
    setForm({
      title: "",
      video_url: "",
      description: "",
      min_task_score: 0,
      max_task_score: 1,
    });
    setDialogOpen(true);
  };

  const openEdit = (e: Exercise) => {
    setEditing(e);
    setForm({
      title: e.title ?? "",
      video_url: e.video_url ?? "",
      description: e.description ?? "",
      min_task_score: e.min_task_score ?? 0,
      max_task_score: e.max_task_score ?? 1,
    });
    setDialogOpen(true);
  };

  const save = () => {
    if (!form.title.trim()) {
      toast.error("Title is required");
      return;
    }
    if (editing) {
      adminApi
        .updateExercise(editing.id, form)
        .then(() => {
          toast.success("Exercise updated");
          setDialogOpen(false);
          load();
        })
        .catch((e) => toast.error(e.message));
    } else {
      adminApi
        .createExercise(form)
        .then(() => {
          toast.success("Exercise created");
          setDialogOpen(false);
          load();
        })
        .catch((e) => toast.error(e.message));
    }
  };

  if (loading) return <p className="text-muted-foreground">Loading exercises…</p>;

  return (
    <div className="space-y-6">
      <h1 className="text-3xl font-bold">Exercises</h1>

      <SectionCard
        title="Exercise pool"
        description="List of exercises. Who sees the exercise step (and which one) is set per student on their profile."
        action={
          <button
            type="button"
            onClick={openCreate}
            className="rounded-md bg-[hsl(24_95%_53%)] px-4 py-2 text-sm font-medium text-white hover:opacity-90"
          >
            Add exercise
          </button>
        }
      >
        <ul className="space-y-2">
          {exercises.length === 0 ? (
            <li className="text-sm text-muted-foreground">No exercises. Add one to assign to students on their profile.</li>
          ) : (
            exercises.map((e) => (
              <li
                key={e.id}
                className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border bg-muted/30 px-4 py-3"
              >
                <div>
                  <span className="font-medium">{e.title}</span>
                  {e.description && (
                    <p className="mt-1 text-sm text-muted-foreground line-clamp-1">{e.description}</p>
                  )}
                </div>
                <div className="flex gap-2">
                  <button
                    type="button"
                    onClick={() => openEdit(e)}
                    className="rounded-md border border-input px-3 py-1.5 text-sm hover:bg-muted"
                  >
                    Edit
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
            <h2 className="text-lg font-semibold">{editing ? "Edit exercise" : "New exercise"}</h2>
            <div className="mt-4 space-y-4">
              <div>
                <label className="mb-2 block text-sm font-medium">Title</label>
                <input
                  className="h-10 w-full rounded-md border border-input px-3 py-2 text-sm"
                  value={form.title}
                  onChange={(e) => setForm((p) => ({ ...p, title: e.target.value }))}
                />
              </div>
              <div>
                <label className="mb-2 block text-sm font-medium">Video URL</label>
                <input
                  className="h-10 w-full rounded-md border border-input px-3 py-2 text-sm"
                  value={form.video_url}
                  onChange={(e) => setForm((p) => ({ ...p, video_url: e.target.value }))}
                />
              </div>
              <div>
                <label className="mb-2 block text-sm font-medium">Description</label>
                <textarea
                  className="min-h-[80px] w-full rounded-md border border-input px-3 py-2 text-sm"
                  rows={2}
                  value={form.description}
                  onChange={(e) => setForm((p) => ({ ...p, description: e.target.value }))}
                />
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="mb-2 block text-sm font-medium">Min task score</label>
                  <input
                    type="number"
                    min={0}
                    max={1}
                    step={0.1}
                    className="h-10 w-full rounded-md border border-input px-3 py-2 text-sm"
                    value={form.min_task_score}
                    onChange={(e) =>
                      setForm((p) => ({ ...p, min_task_score: parseFloat(e.target.value) || 0 }))
                    }
                  />
                </div>
                <div>
                  <label className="mb-2 block text-sm font-medium">Max task score</label>
                  <input
                    type="number"
                    min={0}
                    max={1}
                    step={0.1}
                    className="h-10 w-full rounded-md border border-input px-3 py-2 text-sm"
                    value={form.max_task_score}
                    onChange={(e) =>
                      setForm((p) => ({ ...p, max_task_score: parseFloat(e.target.value) || 1 }))
                    }
                  />
                </div>
              </div>
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
