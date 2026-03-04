"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { ChevronLeft, FileText, Send } from "lucide-react";
import SectionCard from "@/components/admin/SectionCard";
import { adminApi, type StudentProfile, type Exercise, type PostQuestion, type WarmUpTask } from "@/lib/api/admin-client";
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
  const [postQuestions, setPostQuestions] = useState<PostQuestion[]>([]);
  const [warmUpTasks, setWarmUpTasks] = useState<WarmUpTask[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [expandedSessionId, setExpandedSessionId] = useState<string | null>(null);
  const [warmUpModalOpen, setWarmUpModalOpen] = useState(false);
  const [warmUpEditing, setWarmUpEditing] = useState<WarmUpTask | null>(null);
  const [warmUpFormText, setWarmUpFormText] = useState("");
  const [warmUpFormScore, setWarmUpFormScore] = useState<number>(1);
  const [postQuestionModalOpen, setPostQuestionModalOpen] = useState(false);
  const [postQuestionEditing, setPostQuestionEditing] = useState<PostQuestion | null>(null);
  const [postQuestionFormText, setPostQuestionFormText] = useState("");
  const [postQuestionFormAnswerType, setPostQuestionFormAnswerType] = useState<"yes_no" | "scale_1_5" | "text">("text");
  const [savingGradeSessionId, setSavingGradeSessionId] = useState<string | null>(null);
  const sessionGradeSelectRefs = useRef<Record<string, HTMLSelectElement | null>>({});

  const load = useCallback(() => {
    setLoading(true);
    Promise.allSettled([
      adminApi.getStudentProfile(id),
      adminApi.getExercises(),
      adminApi.getPostQuestions(),
      adminApi.getWarmUpTasks(id),
    ])
      .then(([profileRes, exercisesRes, questionsRes, warmUpRes]) => {
        if (profileRes.status === "fulfilled") {
          setProfile(profileRes.value);
        } else {
          toast.error(profileRes.reason?.message ?? "Failed to load profile");
          setProfile(null);
        }
        setExercises(exercisesRes.status === "fulfilled" ? exercisesRes.value : []);
        setPostQuestions(questionsRes.status === "fulfilled" ? questionsRes.value : []);
        setWarmUpTasks(warmUpRes.status === "fulfilled" ? warmUpRes.value : []);
      })
      .finally(() => setLoading(false));
  }, [id]);

  useEffect(() => load(), [load]);

  const [overridesDraft, setOverridesDraft] = useState({
    show_exercise_step: true,
    skip_metric_questions: false,
    skip_post_questions: false,
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
      skip_metric_questions: o.skip_metric_questions === true,
      skip_post_questions: o.skip_post_questions === true,
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

  /** Save all form changes (overrides + speaker profile) in one go. */
  const saveAllChanges = () => {
    setSaving(true);
    const payload: Record<string, unknown> = {
      show_exercise_step: overridesDraft.show_exercise_step,
      skip_metric_questions: overridesDraft.skip_metric_questions,
      skip_post_questions: overridesDraft.skip_post_questions,
      intended_emotion_prompt: overridesDraft.intended_emotion_prompt || undefined,
      keywords_prompt: overridesDraft.keywords_prompt || undefined,
      emotion_check_question_text: overridesDraft.emotion_check_question_text || undefined,
      assigned_next_exercise_id: overridesDraft.assigned_next_exercise_id || undefined,
    };
    payload.assigned_post_question_ids = overridesDraft.assigned_post_question_ids;
    payload.assigned_next_task_ids = overridesDraft.assigned_next_task_ids;
    Promise.all([
      adminApi.putOverrides(id, payload),
      adminApi.putSpeakerProfile(id, speakerDraft),
    ])
      .then(() => {
        toast.success("All changes saved");
        load();
      })
      .catch((e) => toast.error(e?.message ?? "Failed to save"))
      .finally(() => setSaving(false));
  };

  const hasUnsavedChanges =
    profile &&
    (JSON.stringify({
      ...overridesDraft,
      assigned_post_question_ids: [...overridesDraft.assigned_post_question_ids].sort(),
      assigned_next_task_ids: [...(overridesDraft.assigned_next_task_ids ?? [])].sort(),
    }) !==
      JSON.stringify({
        show_exercise_step: profile.overrides?.show_exercise_step !== false,
        skip_metric_questions: profile.overrides?.skip_metric_questions === true,
        skip_post_questions: profile.overrides?.skip_post_questions === true,
        intended_emotion_prompt: profile.overrides?.intended_emotion_prompt ?? "",
        keywords_prompt: profile.overrides?.keywords_prompt ?? "",
        emotion_check_question_text: profile.overrides?.emotion_check_question_text ?? "",
        assigned_post_question_ids: (profile.overrides?.assigned_post_question_ids ?? []).slice().sort(),
        assigned_next_exercise_id: profile.overrides?.assigned_next_exercise_id ?? "",
        assigned_next_task_ids: (profile.overrides?.assigned_next_task_ids ?? []).slice().sort(),
      }) ||
      JSON.stringify(speakerDraft) !==
        JSON.stringify({
          main_goal: profile.speaker_profile?.main_goal ?? "",
          motivation: profile.speaker_profile?.motivation ?? "",
          strong_points: profile.speaker_profile?.strong_points ?? "",
          weak_points: profile.speaker_profile?.weak_points ?? "",
          charismatic_traits: profile.speaker_profile?.charismatic_traits ?? "",
          hobbies_interests: profile.speaker_profile?.hobbies_interests ?? "",
          personality_type: profile.speaker_profile?.personality_type ?? "",
          coach_notes: profile.speaker_profile?.coach_notes ?? "",
        }));

  const sendAssignment = () => {
    adminApi
      .sendAssignment(id)
      .then(() => toast.success("Assignment sent"))
      .catch((e) => toast.error(e.message));
  };

  const toggleExercise = (exId: string) => {
    setOverridesDraft((prev) => ({
      ...prev,
      assigned_next_exercise_id: prev.assigned_next_exercise_id === exId ? "" : exId,
    }));
  };

  const openWarmUpCreate = () => {
    setWarmUpEditing(null);
    setWarmUpFormText("");
    setWarmUpFormScore(1);
    setWarmUpModalOpen(true);
  };
  const openWarmUpEdit = (w: WarmUpTask) => {
    setWarmUpEditing(w);
    setWarmUpFormText(w.text);
    setWarmUpFormScore(w.max_performance_score ?? 1);
    setWarmUpModalOpen(true);
  };
  const saveWarmUp = () => {
    if (!warmUpFormText.trim()) {
      toast.error("Text is required");
      return;
    }
    const score = Math.min(1, Math.max(0, Number(warmUpFormScore) || 1));
    if (warmUpEditing) {
      adminApi
        .updateWarmUpTask(id, warmUpEditing.id, { text: warmUpFormText.trim(), max_performance_score: score })
        .then(() => {
          toast.success("Warm-up task updated");
          setWarmUpModalOpen(false);
          load();
        })
        .catch((e) => toast.error(e.message));
    } else {
      adminApi
        .createWarmUpTask(id, { text: warmUpFormText.trim(), order_index: warmUpTasks.length, max_performance_score: score })
        .then(() => {
          toast.success("Warm-up task added");
          setWarmUpModalOpen(false);
          load();
        })
        .catch((e) => toast.error(e.message));
    }
  };
  const saveWarmUpScore = (taskId: string, value: number) => {
    const score = Math.min(1, Math.max(0, value));
    adminApi
      .updateWarmUpTask(id, taskId, { max_performance_score: score })
      .then(() => {
        toast.success("Max score saved");
        load();
      })
      .catch((e) => toast.error(e.message));
  };
  const deleteWarmUp = (taskId: string) => {
    if (!confirm("Delete this warm-up task?")) return;
    adminApi
      .deleteWarmUpTask(id, taskId)
      .then(() => {
        toast.success("Warm-up task deleted");
        load();
      })
      .catch((e) => toast.error(e.message));
  };

  const ANSWER_TYPES = [
    { value: "yes_no" as const, label: "Yes / No" },
    { value: "scale_1_5" as const, label: "Scale 1–5" },
    { value: "text" as const, label: "Text" },
  ];
  const openPostQuestionCreate = () => {
    setPostQuestionEditing(null);
    setPostQuestionFormText("");
    setPostQuestionFormAnswerType("text");
    setPostQuestionModalOpen(true);
  };
  const openPostQuestionEdit = (q: PostQuestion) => {
    setPostQuestionEditing(q);
    setPostQuestionFormText(q.text);
    setPostQuestionFormAnswerType((q.answer_type as "yes_no" | "scale_1_5" | "text") || "text");
    setPostQuestionModalOpen(true);
  };
  const savePostQuestion = () => {
    if (!postQuestionFormText.trim()) {
      toast.error("Question text is required");
      return;
    }
    if (postQuestionEditing) {
      adminApi
        .updatePostQuestion(postQuestionEditing.id, {
          text: postQuestionFormText.trim(),
          answer_type: postQuestionFormAnswerType,
        })
        .then(() => {
          toast.success("Question updated");
          setPostQuestionModalOpen(false);
          load();
        })
        .catch((e) => toast.error(e.message));
    } else {
      adminApi
        .createPostQuestion({
          text: postQuestionFormText.trim(),
          answer_type: postQuestionFormAnswerType,
        })
        .then(({ question }) => {
          setOverridesDraft((p) => ({
            ...p,
            assigned_post_question_ids: [...p.assigned_post_question_ids, question.id],
          }));
          toast.success("Question added. Click “Save all changes” at the bottom to assign it.");
          setPostQuestionModalOpen(false);
        })
        .catch((e) => toast.error(e.message));
    }
  };
  const removePostQuestion = (qId: string) => {
    setOverridesDraft((p) => ({
      ...p,
      assigned_post_question_ids: p.assigned_post_question_ids.filter((id) => id !== qId),
    }));
  };
  const addPostQuestionFromPool = (qId: string) => {
    if (overridesDraft.assigned_post_question_ids.includes(qId)) return;
    setOverridesDraft((p) => ({
      ...p,
      assigned_post_question_ids: [...p.assigned_post_question_ids, qId],
    }));
  };

  if (loading || !profile) {
    return <p className="text-muted-foreground">Loading…</p>;
  }

  const assignedPostQuestions = overridesDraft.assigned_post_question_ids
    .map((qId) => postQuestions.find((q) => q.id === qId))
    .filter(Boolean) as PostQuestion[];
  const unassignedPostQuestions = postQuestions.filter(
    (q) => !overridesDraft.assigned_post_question_ids.includes(q.id)
  );

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
        title="Warm-up tasks"
        description="Task text the student sees before recording_1 (homework flow). Add, edit, delete per student."
        action={
          <button
            type="button"
            onClick={openWarmUpCreate}
            className="rounded-md bg-[hsl(24_95%_53%)] px-3 py-2 text-sm font-medium text-white hover:opacity-90"
          >
            Add warm-up task
          </button>
        }
      >
        <ul className="space-y-2">
          {warmUpTasks.length === 0 ? (
            <li className="text-sm text-muted-foreground">No warm-up tasks. Add one so the student sees task_warm_up before recording.</li>
          ) : (
            warmUpTasks.map((w) => (
              <li
                key={w.id}
                className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border bg-muted/30 px-4 py-3"
              >
                <p className="text-sm flex-1 min-w-0">{w.text}</p>
                <div className="flex items-center gap-2">
                  <label className="text-sm text-muted-foreground whitespace-nowrap">
                    Max score
                    <input
                      type="number"
                      min={0}
                      max={1}
                      step={0.1}
                      className="ml-2 w-14 rounded border border-input px-2 py-1 text-sm"
                      defaultValue={w.max_performance_score ?? 1}
                      onBlur={(e) => {
                        const v = Number(e.target.value);
                        if (!Number.isNaN(v) && v !== (w.max_performance_score ?? 1)) {
                          saveWarmUpScore(w.id, v);
                        }
                      }}
                    />
                  </label>
                  <button
                    type="button"
                    onClick={() => openWarmUpEdit(w)}
                    className="rounded-md border border-input px-3 py-1.5 text-sm hover:bg-muted"
                  >
                    Edit
                  </button>
                  <button
                    type="button"
                    onClick={() => deleteWarmUp(w.id)}
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

      {warmUpModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="w-full max-w-lg rounded-xl bg-card p-6 shadow-lg">
            <h2 className="text-lg font-semibold">{warmUpEditing ? "Edit warm-up task" : "New warm-up task"}</h2>
            <div className="mt-4">
              <label className="mb-2 block text-sm font-medium">Task text</label>
              <textarea
                className="min-h-[80px] w-full rounded-md border border-input px-3 py-2 text-sm"
                rows={3}
                value={warmUpFormText}
                onChange={(e) => setWarmUpFormText(e.target.value)}
              />
            </div>
            <div className="mt-4">
              <label className="mb-2 block text-sm font-medium">Max score (0–1)</label>
              <input
                type="number"
                min={0}
                max={1}
                step={0.1}
                className="w-24 rounded-md border border-input px-3 py-2 text-sm"
                value={warmUpFormScore}
                onChange={(e) => setWarmUpFormScore(Number(e.target.value) || 1)}
              />
            </div>
            <div className="mt-6 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setWarmUpModalOpen(false)}
                className="rounded-md border border-input px-4 py-2 text-sm hover:bg-muted"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={saveWarmUp}
                className="rounded-md bg-[hsl(24_95%_53%)] px-4 py-2 text-sm font-medium text-white hover:opacity-90"
              >
                Save
              </button>
            </div>
          </div>
        </div>
      )}

      {postQuestionModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="w-full max-w-lg rounded-xl bg-card p-6 shadow-lg max-h-[90vh] overflow-y-auto">
            <h2 className="text-lg font-semibold">
              {postQuestionEditing ? "Edit post-recording question" : "Add post-recording question"}
            </h2>
            {postQuestionEditing ? (
              <div className="mt-4 space-y-4">
                <div>
                  <label className="mb-2 block text-sm font-medium">Question text</label>
                  <textarea
                    className="min-h-[80px] w-full rounded-md border border-input px-3 py-2 text-sm"
                    rows={2}
                    value={postQuestionFormText}
                    onChange={(e) => setPostQuestionFormText(e.target.value)}
                  />
                </div>
                <div>
                  <label className="mb-2 block text-sm font-medium">Answer type</label>
                  <select
                    className="h-10 w-full rounded-md border border-input px-3 py-2 text-sm bg-background"
                    value={postQuestionFormAnswerType}
                    onChange={(e) =>
                      setPostQuestionFormAnswerType(e.target.value as "yes_no" | "scale_1_5" | "text")
                    }
                  >
                    {ANSWER_TYPES.map(({ value, label }) => (
                      <option key={value} value={value}>{label}</option>
                    ))}
                  </select>
                </div>
              </div>
            ) : (
              <div className="mt-4 space-y-4">
                <div>
                  <label className="mb-2 block text-sm font-medium">Create new question</label>
                  <textarea
                    className="min-h-[80px] w-full rounded-md border border-input px-3 py-2 text-sm"
                    rows={2}
                    placeholder="Question text"
                    value={postQuestionFormText}
                    onChange={(e) => setPostQuestionFormText(e.target.value)}
                  />
                  <div className="mt-2">
                    <label className="mb-1 block text-xs font-medium text-muted-foreground">Answer type</label>
                    <select
                      className="h-9 w-full rounded-md border border-input px-3 py-1.5 text-sm bg-background"
                      value={postQuestionFormAnswerType}
                      onChange={(e) =>
                        setPostQuestionFormAnswerType(e.target.value as "yes_no" | "scale_1_5" | "text")
                      }
                    >
                      {ANSWER_TYPES.map(({ value, label }) => (
                        <option key={value} value={value}>{label}</option>
                      ))}
                    </select>
                  </div>
                </div>
                {unassignedPostQuestions.length > 0 && (
                  <div>
                    <label className="mb-2 block text-sm font-medium">Or add from pool</label>
                    <ul className="space-y-1 rounded-md border border-input p-2 max-h-40 overflow-y-auto">
                      {unassignedPostQuestions.map((q) => (
                        <li key={q.id}>
                          <button
                            type="button"
                            onClick={() => {
                              addPostQuestionFromPool(q.id);
                              setPostQuestionModalOpen(false);
                            }}
                            className="w-full text-left rounded px-2 py-1.5 text-sm hover:bg-muted"
                          >
                            {q.text.slice(0, 60)}{q.text.length > 60 ? "…" : ""}
                          </button>
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            )}
            <div className="mt-6 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setPostQuestionModalOpen(false)}
                className="rounded-md border border-input px-4 py-2 text-sm hover:bg-muted"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={savePostQuestion}
                className="rounded-md bg-[hsl(24_95%_53%)] px-4 py-2 text-sm font-medium text-white hover:opacity-90"
              >
                Save
              </button>
            </div>
          </div>
        </div>
      )}

      <SectionCard
        title="Homework Configuration"
        description="Assign exercise and post-recording questions for this student. Changes are saved when you click “Save all changes” at the bottom."
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
          <div className="flex flex-col gap-2">
            <div className="flex items-center gap-2">
              <input
                type="checkbox"
                id="skip_metric_questions"
                checked={overridesDraft.skip_metric_questions}
                onChange={(e) =>
                  setOverridesDraft((p) => ({ ...p, skip_metric_questions: e.target.checked }))
                }
                className="h-4 w-4 rounded border-input"
              />
              <label htmlFor="skip_metric_questions" className="text-sm font-medium">
                Skip Step 2: Metric questions
              </label>
            </div>
            <div className="flex items-center gap-2">
              <input
                type="checkbox"
                id="skip_post_questions"
                checked={overridesDraft.skip_post_questions}
                onChange={(e) =>
                  setOverridesDraft((p) => ({ ...p, skip_post_questions: e.target.checked }))
                }
                className="h-4 w-4 rounded border-input"
              />
              <label htmlFor="skip_post_questions" className="text-sm font-medium">
                Skip Step 4: Post-questions
              </label>
            </div>
          </div>
          <p className="text-xs text-muted-foreground">
            When checked, the student skips that step in the homework flow. Backend returns these as <code className="rounded bg-muted px-1">skip_metric_questions</code> and <code className="rounded bg-muted px-1">skip_post_questions</code> in <code className="rounded bg-muted px-1">overrides</code>.
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
                <span className="text-sm text-muted-foreground">No exercises in pool. Add from this page if your app supports it.</span>
              )}
            </div>
          </div>
          <div>
            <p className="mb-2 text-sm font-medium">
              Post-Recording Questions ({assignedPostQuestions.length} assigned)
            </p>
            <p className="mb-2 text-xs text-muted-foreground">Optional. Add, edit, or remove questions for this student. No limit.</p>
            <div className="flex flex-wrap items-center gap-2 mb-2">
              <button
                type="button"
                onClick={openPostQuestionCreate}
                className="rounded-md bg-[hsl(24_95%_53%)] px-3 py-2 text-sm font-medium text-white hover:opacity-90"
              >
                Add post-recording question
              </button>
              {unassignedPostQuestions.length > 0 && (
                <span className="text-xs text-muted-foreground">
                  or add from pool ({unassignedPostQuestions.length} available)
                </span>
              )}
            </div>
            <ul className="space-y-2">
              {assignedPostQuestions.length === 0 ? (
                <li className="text-sm text-muted-foreground">No post-recording questions. Add one or assign from the pool.</li>
              ) : (
                assignedPostQuestions.map((q) => (
                  <li
                    key={q.id}
                    className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-border bg-muted/30 px-4 py-3"
                  >
                    <p className="text-sm flex-1 min-w-0">{q.text}</p>
                    <div className="flex items-center gap-2">
                      <button
                        type="button"
                        onClick={() => openPostQuestionEdit(q)}
                        className="rounded-md border border-input px-3 py-1.5 text-sm hover:bg-muted"
                      >
                        Edit
                      </button>
                      <button
                        type="button"
                        onClick={() => removePostQuestion(q.id)}
                        className="rounded-md px-3 py-1.5 text-sm text-destructive hover:bg-destructive/10"
                      >
                        Remove
                      </button>
                    </div>
                  </li>
                ))
              )}
            </ul>
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
        description="Goals, motivation, and coach notes. Changes are saved when you click “Save all changes” at the bottom."
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

      <div className="sticky bottom-0 z-10 -mx-4 -mb-4 flex items-center justify-between gap-4 rounded-lg border border-border bg-card px-4 py-4 shadow-sm md:-mx-6 md:px-6">
        {hasUnsavedChanges && (
          <span className="text-sm text-muted-foreground">You have unsaved changes</span>
        )}
        <div className="ml-auto">
          <button
            type="button"
            onClick={saveAllChanges}
            disabled={saving || !hasUnsavedChanges}
            className="rounded-md bg-[hsl(24_95%_53%)] px-6 py-2.5 text-sm font-medium text-white hover:opacity-90 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {saving ? "Saving…" : "Save all changes"}
          </button>
        </div>
      </div>

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
                  <div className="animate-fade-in border-t border-border bg-muted/30 p-4 space-y-4">
                    {s.report_preview?.report_text_preview && (
                      <div>
                        <p className="mb-1 text-sm font-medium">Report</p>
                        <div className="max-h-64 overflow-y-auto rounded-md border border-border bg-background p-3">
                          <p className="text-sm text-muted-foreground whitespace-pre-wrap">
                            {s.report_preview.report_text_preview}
                          </p>
                        </div>
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
                    {s.status === "completed" && (
                      <div className="flex flex-wrap items-center gap-2">
                        <label className="text-sm font-medium">Grade (1–10):</label>
                        <select
                          ref={(el) => { sessionGradeSelectRefs.current[s.id] = el; }}
                          className="rounded-md border border-border bg-background px-2 py-1.5 text-sm"
                          defaultValue={s.coach_grade ?? ""}
                        >
                          <option value="">Not graded</option>
                          {[1, 2, 3, 4, 5, 6, 7, 8, 9, 10].map((n) => (
                            <option key={n} value={n}>{n}</option>
                          ))}
                        </select>
                        <button
                          type="button"
                          disabled={savingGradeSessionId === s.id}
                          className="rounded-md bg-[hsl(24_95%_53%)] px-3 py-1.5 text-sm font-medium text-white hover:opacity-90 disabled:opacity-50"
                          onClick={async () => {
                            setSavingGradeSessionId(s.id);
                            try {
                              const selectEl = sessionGradeSelectRefs.current[s.id];
                              const raw = selectEl?.value ?? "";
                              const grade = raw === "" ? null : parseInt(raw, 10);
                              await adminApi.patchSession(id, s.id, { coach_grade: grade });
                              toast.success("Grade saved.");
                              load();
                            } catch (e) {
                              toast.error((e as Error)?.message ?? "Failed to save grade");
                            } finally {
                              setSavingGradeSessionId(null);
                            }
                          }}
                        >
                          {savingGradeSessionId === s.id ? "Saving…" : "Save grade"}
                        </button>
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
