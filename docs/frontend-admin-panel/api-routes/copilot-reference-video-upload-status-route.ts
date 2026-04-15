/**
 * BFF: GET /api/admin/copilot/reference-videos/upload-jobs/[jobId]
 * Proxy to: GET {BACKEND_URL}/v2/admin/copilot/reference-videos/upload-jobs/{jobId}
 * Authorization: Bearer <supabase access token> (same as other admin routes).
 *
 * Upload: add form field track_progress=1 (or query ?track_progress=1) on POST .../reference-videos/upload.
 * On 202 Accepted, poll this GET every ~500ms until job.stage is "completed" or "failed".
 * Use job.percent (0–100) and job.message for the secondary progress bar; client upload progress stays separate.
 */
