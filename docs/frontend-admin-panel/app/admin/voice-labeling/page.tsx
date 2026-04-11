"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { RefreshCcw, WandSparkles } from "lucide-react";
import { toast } from "sonner";
import SectionCard from "@/components/admin/SectionCard";
import { adminApi, type StressSnippet, type StressSnippetSettings } from "@/lib/api/admin-client";

function fmtMs(ms?: number | null) {
  const n = Number(ms || 0);
  return `${(n / 1000).toFixed(1)}s`;
}

export default function VoiceLabelingPage() {
  const [settings, setSettings] = useState<StressSnippetSettings | null>(null);
  const [snippets, setSnippets] = useState<StressSnippet[]>([]);
  const [loading, setLoading] = useState(true);
  const [savingSwitch, setSavingSwitch] = useState(false);
  const [labelingId, setLabelingId] = useState<string | null>(null);
  const [recordingId, setRecordingId] = useState("");
  const [generateBusy, setGenerateBusy] = useState(false);
  const [labelState, setLabelState] = useState<"all" | "labeled" | "unlabeled">("unlabeled");
  const [sourceType, setSourceType] = useState<"all" | "student" | "internet">("student");
  const [notesBySnippetId, setNotesBySnippetId] = useState<Record<string, string>>({});

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [settingsRes, listRes] = await Promise.all([
        adminApi.getStressSnippetSettings(),
        adminApi.listStressSnippets({ source_type: sourceType, label_state: labelState, limit: 80, offset: 0 }),
      ]);
      setSettings(settingsRes);
      setSnippets(listRes.snippets || []);
    } catch (e) {
      toast.error((e as Error)?.message ?? "Failed to load stress snippets");
    } finally {
      setLoading(false);
    }
  }, [labelState, sourceType]);

  useEffect(() => {
    void load();
  }, [load]);

  const unlabeledCount = useMemo(() => snippets.filter((s) => !s.coach_label).length, [snippets]);

  async function toggleAutoExtract(nextValue: boolean) {
    if (!settings) return;
    setSavingSwitch(true);
    try {
      const res = await adminApi.updateStressSnippetSettings(nextValue);
      setSettings(res.settings);
      toast.success(nextValue ? "Auto-extract enabled" : "Auto-extract disabled");
    } catch (e) {
      toast.error((e as Error)?.message ?? "Failed to update setting");
    } finally {
      setSavingSwitch(false);
    }
  }

  async function runGenerate() {
    const rid = recordingId.trim();
    if (!rid) {
      toast.error("Paste a recording ID first");
      return;
    }
    setGenerateBusy(true);
    try {
      const out = await adminApi.generateStressSnippets(rid, { max_snippets: 8, clip_seconds: 10, clear_existing: true });
      toast.success(`Generated ${out.generated_count} snippet(s)`);
      await load();
    } catch (e) {
      toast.error((e as Error)?.message ?? "Snippet generation failed");
    } finally {
      setGenerateBusy(false);
    }
  }

  async function setLabel(snippet: StressSnippet, label: "stress" | "no_stress") {
    setLabelingId(snippet.id);
    try {
      const notes = (notesBySnippetId[snippet.id] || "").trim();
      await adminApi.labelStressSnippet(snippet.id, { label, notes: notes || null });
      setSnippets((prev) =>
        prev.map((s) => (s.id === snippet.id ? { ...s, coach_label: label, coach_label_notes: notes || null } : s))
      );
      toast.success("Label saved");
    } catch (e) {
      toast.error((e as Error)?.message ?? "Failed to save label");
    } finally {
      setLabelingId(null);
    }
  }

  return (
    <div className="space-y-4">
      <SectionCard title="Stress Snippet Controls">
        <div className="grid gap-3 md:grid-cols-2">
          <div className="rounded-lg border border-border p-3">
            <p className="text-sm font-medium">Auto extract from student uploads</p>
            <p className="text-xs text-muted-foreground mt-1">
              When on, snippets are generated automatically after recording-1 processing.
            </p>
            <button
              type="button"
              disabled={!settings || savingSwitch}
              onClick={() => toggleAutoExtract(!(settings?.auto_extract_enabled ?? true))}
              className="mt-3 rounded-md border px-3 py-2 text-sm hover:bg-muted disabled:opacity-60"
            >
              {savingSwitch
                ? "Saving..."
                : settings?.auto_extract_enabled
                ? "ON (click to disable)"
                : "OFF (click to enable)"}
            </button>
          </div>

          <div className="rounded-lg border border-border p-3">
            <p className="text-sm font-medium">Generate now for one recording</p>
            <p className="text-xs text-muted-foreground mt-1">
              Use right after upload if you want snippets immediately for labeling.
            </p>
            <div className="mt-3 flex gap-2">
              <input
                className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm"
                placeholder="Paste recording UUID"
                value={recordingId}
                onChange={(e) => setRecordingId(e.target.value)}
              />
              <button
                type="button"
                onClick={runGenerate}
                disabled={generateBusy}
                className="inline-flex items-center gap-2 rounded-md border px-3 py-2 text-sm hover:bg-muted disabled:opacity-60"
              >
                <WandSparkles className="h-4 w-4" />
                {generateBusy ? "Generating..." : "Generate"}
              </button>
            </div>
          </div>
        </div>
      </SectionCard>

      <SectionCard title="Snippet Inbox">
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <select
            className="rounded-md border border-input bg-background px-2 py-1.5 text-sm"
            value={sourceType}
            onChange={(e) => setSourceType(e.target.value as "all" | "student" | "internet")}
          >
            <option value="all">All sources</option>
            <option value="student">Student</option>
            <option value="internet">Internet</option>
          </select>
          <select
            className="rounded-md border border-input bg-background px-2 py-1.5 text-sm"
            value={labelState}
            onChange={(e) => setLabelState(e.target.value as "all" | "labeled" | "unlabeled")}
          >
            <option value="unlabeled">Unlabeled</option>
            <option value="all">All labels</option>
            <option value="labeled">Labeled only</option>
          </select>
          <button
            type="button"
            onClick={() => void load()}
            className="inline-flex items-center gap-2 rounded-md border px-3 py-1.5 text-sm hover:bg-muted"
          >
            <RefreshCcw className="h-4 w-4" />
            Refresh
          </button>
          <span className="text-xs text-muted-foreground">
            showing {snippets.length} snippet(s), unlabeled in view: {unlabeledCount}
          </span>
        </div>

        {loading ? (
          <p className="text-sm text-muted-foreground">Loading snippets...</p>
        ) : snippets.length === 0 ? (
          <p className="text-sm text-muted-foreground">No snippets for this filter yet.</p>
        ) : (
          <div className="space-y-3">
            {snippets.map((s) => (
              <div key={s.id} className="rounded-lg border border-border p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <p className="text-sm font-medium">
                    {s.source_type} / {s.scenario} / {fmtMs(s.start_ms)} - {fmtMs(s.end_ms)}
                  </p>
                  <p className="text-xs text-muted-foreground">recording: {s.recording_id}</p>
                </div>
                {s.audio_url ? (
                  <audio controls preload="none" className="mt-2 w-full">
                    <source src={s.audio_url} />
                  </audio>
                ) : null}
                {s.transcript_excerpt ? (
                  <p className="mt-2 text-xs text-muted-foreground">{s.transcript_excerpt}</p>
                ) : null}
                <div className="mt-2 grid gap-2 md:grid-cols-[1fr_auto_auto]">
                  <input
                    className="rounded-md border border-input bg-background px-3 py-2 text-sm"
                    placeholder="Optional label note"
                    value={notesBySnippetId[s.id] ?? (s.coach_label_notes || "")}
                    onChange={(e) => setNotesBySnippetId((prev) => ({ ...prev, [s.id]: e.target.value }))}
                  />
                  <button
                    type="button"
                    disabled={labelingId === s.id}
                    onClick={() => void setLabel(s, "stress")}
                    className="rounded-md border border-red-700 bg-red-600 px-3 py-2 text-sm font-medium text-white shadow-sm hover:bg-red-700 disabled:opacity-60"
                  >
                    Stress
                  </button>
                  <button
                    type="button"
                    disabled={labelingId === s.id}
                    onClick={() => void setLabel(s, "no_stress")}
                    className="rounded-md border border-green-700 bg-green-600 px-3 py-2 text-sm font-medium text-white shadow-sm hover:bg-green-700 disabled:opacity-60"
                  >
                    No stress
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}
      </SectionCard>
    </div>
  );
}
