# Coach surface namespace — `/v2/coach/*` is canonical (delta)

**Status:** locked 2026-06-06. Supersedes the earlier "re-gate `/admin/*`, no
twins" decision.

## What changed and why

The §B pre-flight chose to re-gate the existing `/admin/*` routes for the coach
role (avoid building redundant route twins). That was correct **given the
information then** — it assumed the FE hadn't committed to a namespace.

It had. The frontend (frontend-cursor **PR #73** "F.2+F.3+F.4", and PR 2's
queue) shipped against **`/v2/coach/*`** — BFF proxies built, fields named
`direction_label` / `coach_state`, ~960 lines. So the choice was no longer
"twins vs no-twins"; it was "which side eats the alignment churn." Aligning the
BE is less work, on the safer side, and lands the *better* architecture anyway:
the coach surface is a new purpose-built thing (we killed the Tab-1 reuse), so
it deserves its own `/coach/*` namespace, not a re-gated admin route.

## The canonical coach surface (BE)

| Method | Route | Handler | Notes |
|---|---|---|---|
| GET  | `/v2/coach/queue` | `v2_coach_queue` | pseudonymized rows, FIFO oldest-first |
| GET  | `/v2/coach/sessions/<id>` | `v2_coach_get_session` | per-snippet `coach_state` (both lanes), identity-stripped |
| POST | `/v2/coach/sessions/<id>/snippets/<id>` | `v2_coach_save_snippet` | body `direction_label`/`note`/`tag`/`surfaced`; echoes `coach_state` |
| POST | `/v2/coach/sessions/<id>/video` | `v2_coach_session_video` | coach feedback video |
| POST | `/v2/internal/publish-session-results` | `v2_internal_publish_session_results` | publish — the FE's `publishWillabSession` POSTs here (confirmed); `@require_admin_or_coach` |

All gated `@require_admin_or_coach`. Every response is **pseudonymized**
(`pseudonym` + `domain` only — never `user_id`/name/email; §S.4 / §14 red-line 6).

## Superseded / do not resurrect

- `/v2/admin/sessions/<id>/snippets/<id>` and `/v2/admin/sessions/<id>/video`
  were repointed to `/v2/coach/*` (not duplicated).
- `/v2/admin/review-queue` and `/v2/admin/sessions/<id>/readout` were reverted
  to `@require_admin` (admin-only legacy tooling). Coaches use `/v2/coach/*`.
- **Do not** "helpfully" re-consolidate the coach routes back under `/admin/*`.
  The FE depends on `/v2/coach/*`.

## Functional fix bundled with the alignment (not cosmetic)

The coach session read folds **both** lanes into per-snippet `coach_state`
(`training_labels` → `direction_label`; `coach_snippet_drafts` →
`note`/`tag`/`surfaced`). Before, only the label round-tripped, so a coach who
labeled half a session, left, and returned would find their **notes and tags
gone**. `coach_snippet_drafts.surfaced` now defaults **false** (a snippet
reaches the user only when explicitly surfaced — FE/spec default).
