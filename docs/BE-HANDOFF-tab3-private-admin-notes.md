# BE handoff — Admin Tab 3: private admin notes panel

Status: **BE COMPLETE. FE work only.** No code changes needed on the backend for the panel itself. One known gap (LLM injection) is flagged at the bottom as a separate work item.

---

## What FE wires against (already live on `main`)

### GET — load current notes
```
GET /api/v2/admin/users/<userId>/context
  → backend: GET /v2/admin/user(s)/<userId>/context  (both singular & plural paths work)
  → headers: Authorization: Bearer <admin JWT>
```

Response (relevant slice):
```jsonc
{
  "user": {
    "id":   "<uuid>",
    "email": "...",
    "name":  "...",
    "private_admin_notes": "string | null"
  },
  "sessions": [ /* ... */ ]
}
```

### PATCH — save edited notes
```
PATCH /api/v2/admin/users/<userId>/context
  → backend: PATCH /v2/admin/user(s)/<userId>/context
  → headers: Authorization: Bearer <admin JWT>,
             Content-Type: application/json
  → body:    { "private_admin_notes": "any free text, or null to clear" }
```

Response: same shape as GET (full context payload re-rendered from one request — FE can replace local state from the PATCH response directly, no follow-up GET needed).

**Both methods route through `@require_admin`** → 403 FORBIDDEN for non-admin tokens. The endpoint never appears in any user-facing route; the `user_settings.private_admin_notes` column has no read path outside `/v2/admin/...`.

---

## FE deliverables

- One big `<textarea>` on Tab 3, bound to `user.private_admin_notes` from the context GET.
- Debounced PATCH on edit (300–500ms is fine — admin-only surface, no throughput concerns).
- Visual confirm "Saved" / spinner / error state — server returns 200 with the updated payload on success, 400 INVALID_INPUT for malformed body, 500 V2_ERROR on DB failure.
- Hide / never render this field on any user-facing page. Tab 3 is admin-only by route; the JSON should never reach a non-admin frontend bundle.

The previous Tab 3 inputs (`custom_llm_instructions`, `coach_override_profile`, behavioural-profile family) were removed from this endpoint in commit `b004659` — Tab 3 is intentionally minimal: notes only, plus the read-only identity header (`id`, `email`, `name`).

---

## Behaviour quirks to know

- **Partial update semantics**: the PATCH writes only keys present in the body. To clear notes send `{ "private_admin_notes": null }`. Omitting the key leaves the existing value untouched.
- **Whitespace-only strings**: trimmed server-side → an empty / whitespace-only body becomes a clear (`NULL` in the DB).
- **No history / audit log**: writes overwrite the column. If the admin wants to recover an older note revision, they can't — flag if this matters and we can add an append-only ledger in a follow-up.
- **No length limit enforced server-side**: there's no `maxLength` check on the column. Postgres `TEXT` is effectively unbounded. FE can impose its own UI cap (suggest ~4000 chars to match the chat UI's textarea conventions) but BE won't reject.

---

## The known gap — LLM injection (separate work item)

The brainstorm's full intent says the notes should "serve the system to know what to not ask." Today the column is **stored but not piped into any LLM system prompt**:

- `_augment_interview_prompt_with_profile` ([routes/v2_routes.py:~8650](routes/v2_routes.py:8650)) reads `user_settings.custom_llm_instructions` and splices it as `[COACHING CONTEXT] Admin Notes:`. It does NOT read `private_admin_notes`.
- `_augment_coaching_system_prompt` ([routes/v2_routes.py:~8815](routes/v2_routes.py:8815)) — same.
- `services/master_doc_rag.py` (FAQ chat) — does not read `private_admin_notes`.
- `services/coaching_state_machine.py::build_state_machine_system_prompt` — does not read `private_admin_notes`.

So the FE saving notes today is silent storage only. Until the BE wires injection, the admin's notes have no effect on what the bot asks the user.

**To close the gap (BE follow-up, ~20 LOC):**
1. Read `private_admin_notes` inside each `_augment_*` helper (same `db.get_user_settings(user_id)` call that's already there).
2. Splice as a new prompt block:
   ```
   [PRIVATE ADMIN CONTEXT — do not ask about / surface to the user]
   <notes verbatim>
   ```
3. Make sure the LLM prompt's existing rules (no quoting from this block, treat as background only) are explicit so the model doesn't echo the notes back to the user.

Flag if you want this wired now or after FE ships the input UI. I'd recommend after — gives you a chance to verify the input round-trip is clean before adding the LLM consumer.

---

## Acceptance — what FE should confirm

- Loading Tab 3 shows the saved notes verbatim in the textarea (or empty if never set).
- Editing → debounced PATCH → server returns 200 with the updated payload → textarea retains focus + shows "Saved" indicator.
- Reloading the page (or another admin's session) sees the saved value.
- Non-admin tokens hitting the endpoint get 403 (verify with a non-admin Bearer; should never see the notes).
- No user-facing page displays the notes (grep FE codebase for `private_admin_notes` outside the Tab 3 component).
