/**
 * Example background worker task (Inngest/BullMQ/cron job) for async video processing.
 *
 * Required env:
 * - NEXT_PUBLIC_BACKEND_URL or BACKEND_URL
 * - COPILOT_VIDEO_PIPELINE_SECRET
 */

type QueueJob = {
  draftId: string;
};

const backendUrl = process.env.BACKEND_URL || process.env.NEXT_PUBLIC_BACKEND_URL;
const internalSecret = process.env.COPILOT_VIDEO_PIPELINE_SECRET;

if (!backendUrl) {
  throw new Error("Missing BACKEND_URL (or NEXT_PUBLIC_BACKEND_URL)");
}
if (!internalSecret) {
  throw new Error("Missing COPILOT_VIDEO_PIPELINE_SECRET");
}

export async function processCopilotVideoJob(job: QueueJob) {
  const res = await fetch(
    `${backendUrl.replace(/\/$/, "")}/v2/admin/internal/copilot/drafts/${job.draftId}/pipeline/process`,
    {
      method: "POST",
      headers: {
        "X-Internal-Secret": internalSecret,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({}),
    }
  );

  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(data?.error || `Pipeline failed (${res.status})`);
  }
  return data;
}
