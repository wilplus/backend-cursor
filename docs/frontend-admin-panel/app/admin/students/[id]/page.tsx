"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ChevronLeft, FileText, Send } from "lucide-react";
import SectionCard from "@/components/admin/SectionCard";
import { adminApi, type StudentProfile, type Exercise, type PostQuestion, type Task } from "@/lib/api/admin-client";
import { toast } from "sonner";

function Chip({
  label,
  selected,
  onToggle,
}: {
  label: string;
  selected: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onToggle}
      className={`
        rounded-lg border-2 px-3 py-2 text-sm font-medium transition-all
        ${selected
          ? "border-[hsl(24_95%_53%)] bg-[hsl(24_100%_97%)] text-[hsl(24_95%_40%)]"
          : "border-border hover:border-[hsl(24_95%_53%_/_.5)]"
        }
      `}
    >
      {label}
    </button>
  );
}

export default function AdminStudentProfilePage({ params }: { params: { id: string } }) {
  const id = typeof params.id === "string" ? params.id : params.id[0];
  const [profile, setProfile] = useState<StudentProfile | null>(null);
  const [exercises, setExercises] = useState<Exercise[]>([]);
  const [tasks, setTasks] = useState<Task[]>([]);
  const [postQuestions, setPostQuestions] = useState<PostQuestion[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [expandedSessionId, setExpandedSessionId] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    const fetchProfile = adminApi.getStudentProfile(id);
    const fetchExercises = adminApi.getExercises().catch(() => [] as Exercise[]);
    const fetchTasks = adminApi.getTasks().catch(() => [] as Task[]);
    const fetchQuestions = adminApi.getPostQuestions().catch(() => [] as PostQuestion[]);
    Promise.all([fetchProfile, fetchExercises, fetchTasks, fetchQuestions])
      .then(([p, ex, t, q]) => {
        setProfile(p);
        setExercises(ex);
        setTasks(t);
        setPostQuestions(q);
      })
      .catch((e) => {
        toast.error(e.message);
        setProfile(null);
      })
      .finally(() => setLoading(false));
  }, [id]);

  useEffect(() => load(), [load]);

  const [overridesDraft, setOverridesDraft] = useState({
    show_exercise_step: true,
    intended_emotion_prompt: "",
    keywords_prompt: "",
    emotion_check_question_text: "",
    assigned_post_question_ids: [] as string[],
    assigned_next_exercise_id: "",
    assigned_next_task_ids: [] as string[],
  });
  const [speakerDraft, setSpeakerDraft] = useState({
    main_goal: "",
    motivation: "",
    strong_points: "",
    weak_points: "",
    charismatic_traits: "",
    hobbies_interests: "",
    personality_type: "",
    coach_notes: "",
  });

  useEffect(() => {
    if (!profile) return;
    const o = profile.overrides || {};
    setOverridesDraft({
      show_exercise_step: o.show_exercise_step !== false,
      intended_emotion_prompt: o.intended_emotion_prompt ?? "",
      keywords_prompt: o.keywords_prompt ?? "",
      emotion_check_question_text: o.emotion_check_question_text ?? "",
      assigned_post_question_ids: o.assigned_post_question_ids ?? [],
      assigned_next_exercise_id: o.assigned_next_exercise_id ?? "",
      assigned_next_task_ids: o.assigned_next_task_ids ?? [],
    });
    const s = profile.speaker_profile || {};
    setSpeakerDraft({
      main_goal: s.main_goal ?? "",
      motivation: s.motivation ?? "",
      strong_points: s.strong_points ?? "",
      weak_points: s.weak_points ?? "",
      charismatic_traits: s.charismatic_traits ?? "",
      hobbies_interests: s.hobbies_interests ?? "",
      personality_type: s.personality_type ?? "",
      coach_notes: s.coach_notes ?? "",
    });
  }, [profile]);

  const saveOverrides = () => {
    setSaving(true);
    const payload: Record<string, unknown> = {
      show_exercise_step: overridesDraft.show_exercise_step,
      intended_emotion_prompt: overridesDraft.intended_emotion_prompt || undefined,
      keywords_prompt: overridesDraft.keywords_prompt || undefined,
      emotion_check_question_text: overridesDraft.emotion_check_question_text || undefined,
      assigned_next_exercise_id: overridesDraft.assigned_next_exercise_id || undefined,
      assigned_next_task_ids: overridesDraft.assigned_next_task_ids.length > 0 ? overridesDraft.assigned_next_task_ids : undefined,
    };
    if (overridesDraft.assigned_post_question_ids.length === 3) {
      payload.assigned_post_question_ids = overridesDraft.assigned_post_question_ids;
    }
    adminApi
      .putOverrides(id, payload)
      .then(() => toast.success("Overrides saved"))
      .catch((e) => toast.error(e.message))
      .finally(() => setSaving(false));
  };

  const saveSpeakerProfile = () => {
    setSaving(true);
    adminApi
      .putSpeakerProfile(id, speakerDraft)
      .then(() => toast.success("Speaker profile saved"))
      .catch((e) => toast.error(e.message))
      .finally(() => setSaving(false));
  };

  const sendAssignment = () => {
    adminApi
      .sendAssignment(id)
      .then(() => toast.success("Assignment sent"))
      .catch((e) => toast.error(e.message));
  };

  const togglePostQuestion = (qId: string) => {
    setOverridesDraft((prev) => {
      const ids = prev.assigned_post_question_ids.includes(qId)
        ? prev.assigned_post_question_ids.filter((x) => x !== qId)
        : [...prev.assigned_post_question_ids, qId].slice(0, 3);
      return { ...prev, assigned_post_question_ids: ids };
    });
  };

  const toggleExercise = (exId: string) => {
    setOverridesDraft((prev) => ({
      ...prev,
      assigned_next_exercise_id: prev.assigned_next_exercise_id === exId ? "" : exId,
    }));
  };

  const toggleTask = (taskId: string) => {
    setOverridesDraft((prev) => {
      const ids = prev.assigned_next_task_ids.includes(taskId)
        ? prev.assigned_next_task_ids.filter((x) => x !== taskId)
        : [...prev.assigned_next_task_ids, taskId];
      return { ...prev, assigned_next_task_ids: ids };
    });
  };

  if (loading || !profile) {
    return <p className="text-muted-foreground">Loading…</p>;
  }

  const postCount = overridesDraft.assigned_post_question_ids.length;
  const postError = postCount > 0 && postCount !== 3;

  return (
    <div className="space-y-6">
      <div>
        <Link
          href="/admin/students"
          className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground"
        >
          <ChevronLeft className="h-4 w-4" /> Students
        </Link>
        <div className="mt-2 flex flex-wrap items-center justify-between gap-4">
          <h1 className="text-3xl font-bold">
            {profile.email || profile.user_id}
          </h1>
          <button
            type="button"
            onClick={sendAssignment}
            className="inline-flex items-center gap-2 rounded-md bg-[hsl(24_95%_53%)] px-4 py-2 text-sm font-medium text-white hover:opacity-90"
          >
            <Send className="h-4 w-4" /> Send Homework
          </button>
        </div>
      </div>

      <SectionCard
        title="Homework Configuration"
        description="Assign exercise and post-recording questions for this student."
        action={
          <button
            type="button"
            onClick={saveOverrides}
            disabled={saving || postError}
            className="rounded-md bg-[hsl(24_95%_53%)] px-3 py-2 text-sm font-medium text-white hover:opacity-90 disabled:opacity-50"
          >
            Save
          </button>
        }
      >
        <div className="space-y-4">
          <div className="flex items-center gap-2">
            <input
              type="checkbox"
              id="show_exercise_step"
              checked={overridesDraft.show_exercise_step}
              onChange={(e) =>
                setOverridesDraft((p) => ({ ...p, show_exercise_step: e.target.checked }))
              }
              className="h-4 w-4 rounded border-input"
            />
            <label htmlFor="show_exercise_step" className="text-sm font-medium">
              Show exercise step for this student
            </label>
          </div>
          <p className="text-xs text-muted-foreground">
            When on, this student sees the exercise step after the 3 universal questions. When off, they skip it. Which exercise (or auto by task score) is set below.
          </p>
          <div>
            <p className="mb-2 text-sm font-medium">Next exercise (optional, when step is on)</p>
            <div className="flex flex-wrap gap-2">
              {exercises.map((e) => (
                <Chip
                  key={e.id}
                  label={e.title}
                  selected={overridesDraft.assigned_next_exercise_id === e.id}
                  onToggle={() => toggleExercise(e.id)}
                />
              ))}
              {exercises.length === 0 && (
                <span className="text-sm text-muted-foreground">No exercises in pool. Add them on the Exercises tab.</span>
              )}
            </div>
          </div>
          <div>
            <p className="mb-2 text-sm font-medium">Tasks for this student (multi-select)</p>
            <p className="mb-2 text-xs text-muted-foreground">Choose which tasks are available for this student. Newly added tasks appear here.</p>
            <div className="flex flex-wrap gap-2">
              {tasks.map((t) => (
                <Chip
                  key={t.id}
                  label={t.title}
                  selected={overridesDraft.assigned_next_task_ids.includes(t.id)}
                  onToggle={() => toggleTask(t.id)}
                />
              ))}
              {tasks.length === 0 && (
                <span className="text-sm text-muted-foreground">No tasks in pool. Add them on the Tasks tab.</span>
              )}
            </div>
          </div>
          <div>
            <p className="mb-2 text-sm font-medium">
              Post-Recording Questions ({postCount}/3 selected)
            </p>
            <p className="mb-2 text-xs text-muted-foreground">All questions from the pool; newly added ones appear here. Select exactly 3.</p>
            {postError && (
              <p className="mb-2 text-sm text-destructive">Select exactly 3 questions.</p>
            )}
            <div className="flex flex-wrap gap-2">
              {postQuestions.map((q) => (
                <Chip
                  key={q.id}
                  label={q.text.slice(0, 30) + (q.text.length > 30 ? "…" : "")}
                  selected={overridesDraft.assigned_post_question_ids.includes(q.id)}
                  onToggle={() => togglePostQuestion(q.id)}
                />
              ))}
            </div>
            {postQuestions.length === 0 && (
              <span className="text-sm text-muted-foreground">No questions in pool. Add them on the Questions tab.</span>
            )}
          </div>
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <label className="mb-2 block text-sm font-medium">Intended emotion prompt</label>
              <textarea
                className="min-h-[80px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus-visible:ring-2 focus-visible:ring-ring"
                rows={2}
                value={overridesDraft.intended_emotion_prompt}
                onChange={(e) =>
                  setOverridesDraft((p) => ({ ...p, intended_emotion_prompt: e.target.value }))
                }
              />
            </div>
            <div>
              <label className="mb-2 block text-sm font-medium">Keywords prompt</label>
              <textarea
                className="min-h-[80px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus-visible:ring-2 focus-visible:ring-ring"
                rows={2}
                value={overridesDraft.keywords_prompt}
                onChange={(e) =>
                  setOverridesDraft((p) => ({ ...p, keywords_prompt: e.target.value }))
                }
              />
            </div>
          </div>
          <div>
            <label className="mb-2 block text-sm font-medium">Emotion check question text</label>
            <input
              className="h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus-visible:ring-2 focus-visible:ring-ring"
              value={overridesDraft.emotion_check_question_text}
              onChange={(e) =>
                setOverridesDraft((p) => ({ ...p, emotion_check_question_text: e.target.value }))
              }
            />
          </div>
        </div>
      </SectionCard>

      <SectionCard
        title="Speaker Profile"
        description="Goals, motivation, and coach notes."
        action={
          <button
            type="button"
            onClick={saveSpeakerProfile}
            disabled={saving}
            className="rounded-md bg-[hsl(24_95%_53%)] px-3 py-2 text-sm font-medium text-white hover:opacity-90 disabled:opacity-50"
          >
            Save
          </button>
        }
      >
        <div className="grid gap-4 sm:grid-cols-2">
          {(
            [
              ["main_goal", "Main Goal", 2],
              ["motivation", "Motivation", 2],
              ["strong_points", "Strong Points", 2],
              ["weak_points", "Weak Points", 2],
              ["charismatic_traits", "Charismatic Traits", 2],
              ["hobbies_interests", "Hobbies & Interests", 2],
              ["personality_type", "Personality Type", 1],
            ] as const
          ).map(([key, label, rows]) => (
            <div key={key} className={key === "personality_type" ? "" : "sm:col-span-1"}>
              <label className="mb-2 block text-sm font-medium">{label}</label>
              {rows === 1 ? (
                <input
                  className="h-10 w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus-visible:ring-2 focus-visible:ring-ring"
                  value={speakerDraft[key]}
                  onChange={(e) => setSpeakerDraft((p) => ({ ...p, [key]: e.target.value }))}
                />
              ) : (
                <textarea
                  className="min-h-[80px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus-visible:ring-2 focus-visible:ring-ring"
                  rows={2}
                  value={speakerDraft[key]}
                  onChange={(e) => setSpeakerDraft((p) => ({ ...p, [key]: e.target.value }))}
                />
              )}
            </div>
          ))}
          <div className="sm:col-span-2">
            <label className="mb-2 block text-sm font-medium">Coach Notes</label>
            <textarea
              className="min-h-[100px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm focus-visible:ring-2 focus-visible:ring-ring"
              rows={3}
              value={speakerDraft.coach_notes}
              onChange={(e) => setSpeakerDraft((p) => ({ ...p, coach_notes: e.target.value }))}
            />
          </div>
        </div>
      </SectionCard>

      <SectionCard title="Session History" description="Recent sessions and reports.">
        <div className="space-y-2">
          {profile.sessions.length === 0 ? (
            <p className="text-sm text-muted-foreground">No sessions yet.</p>
          ) : (
            profile.sessions.map((s) => (
              <div
                key={s.id}
                className="rounded-xl border border-border bg-card shadow-sm overflow-hidden"
              >
                <button
                  type="button"
                  className="flex w-full items-center justify-between p-4 text-left hover:bg-muted/30"
                  onClick={() =>
                    setExpandedSessionId((x) => (x === s.id ? null : s.id))
                  }
                >
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm text-muted-foreground">
                      {s.created_at?.slice(0, 10)}
                    </span>
                    {s.task_score != null && (
                      <span className="rounded-md border border-border px-2 py-0.5 text-xs">
                        Task: {Math.round((s.task_score ?? 0) * 100)}%
                      </span>
                    )}
                    {s.recording_preview?.performance_score_v2 != null && (
                      <span className="rounded-md border border-border px-2 py-0.5 text-xs">
                        Performance: {Math.round((s.recording_preview.performance_score_v2 ?? 0) * 100)}%
                      </span>
                    )}
                  </div>
                  <FileText
                    className={`h-4 w-4 shrink-0 text-muted-foreground transition-transform ${expandedSessionId === s.id ? "rotate-180" : ""}`}
                  />
                </button>
                {expandedSessionId === s.id && (
                  <div className="animate-fade-in border-t border-border bg-muted/30 p-4">
                    {s.report_preview?.report_text_preview && (
                      <div className="mb-3">
                        <p className="mb-1 text-sm font-medium">Summary</p>
                        <p className="text-sm text-muted-foreground whitespace-pre-wrap">
                          {s.report_preview.report_text_preview}
                        </p>
                      </div>
                    )}
                    {s.recording_preview?.transcription_preview && (
                      <div>
                        <p className="mb-1 text-sm font-medium">Transcript Preview</p>
                        <p className="text-sm text-muted-foreground">
                          &quot;{s.recording_preview.transcription_preview}…&quot;
                        </p>
                      </div>
                    )}
                  </div>
                )}
              </div>
            ))
          )}
        </div>
      </SectionCard>
    </div>
  );
}
