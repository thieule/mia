# Agile Studio — context for AI assistants

Use this document as **system or user prompt material** when an AI must reason about Agile Studio behavior, APIs, or MCP tools. Detailed tool signatures live in `mcp_server/MCP_TOOLS_REFERENCE.md`.

Agent deployments (e.g. separate agent repos) often **avoid linking** to this file on disk so tooling stays valid if Agile Studio is vendored or split — **paste excerpts** or attach this file in the session when needed.

---

## What Agile Studio is

**Agile Studio** is a separate service (FastAPI + MySQL DB `agile_studio`) for lightweight agile planning: projects, human/AI **members**, **stories**, **story tasks**, **releases**, **comments**, optional **chat** hooks, and a **React** web UI. It can link to developer workspaces via `workspace_ref` on a project.

- **HTTP API:** `/api/v1/...` (often on port `9120`). Most routes require **JWT** (`Authorization: Bearer ...`) for browser users.
- **MCP server:** `mcp_server/` talks to the **same database** via `AGILE_DATABASE_URL` — **no JWT**; tools return **JSON strings** (parse and check `error`).

---

## Core concepts

| Concept | Meaning |
|--------|---------|
| **Member** | A person or AI identity: `member_type` = `human` \| `ai`. AI members may have `agent_id` (runtime agent id). Members are global; they are not “in” a project until linked. |
| **Project** | Container for stories, releases, project-scoped chat channels, etc. Has unique `slug`, optional `workspace_ref`, `settings_json` (workflow template, storage notes, webhooks, …). |
| **Project member** | Join table: a **member** is added to a **project** with a **role** (`owner`, `admin`, `member`, `viewer`, …). **Story assignees, task assignees, reporters, and comment authors must be project members** of that story’s project. |
| **Workflow template** | Master-data template selected per project (`settings.workflow_template_id`). **Creating/updating stories** requires the project to have a valid workflow template selected. |
| **Story** | A work item in a project; auto-numbered per project; human-readable **story key** = `{project_slug}-{story_number}` (e.g. `demo-42`). Has status, priority, points, optional **release**, **release_label** (free tag), multiple **assignees** (`assignee_ids`; `assignee_id` is legacy “first”), optional **reporter_id**, markdown **description**. |
| **Story status** | Stored as granular workflow states (see below). Older labels (`icebox`, `backlog`, `ready`, …) are **normalized** by the API to the canonical set. |
| **Story task** | A **checklist-style task inside a story** — **not** a separate Kanban card. Fields: `title`, optional markdown **`body`**, **`done`**, **`sort_order`**, multiple **`assignee_ids`**, optional **`reporter_id`**. Assignees/reporter must be **project members**. |
| **Release** | Milestone / shipping window per project (`planning` \| `active` \| `released` \| `archived`) with optional `starts_at` / `ends_at` / `released_at`. Stories may reference `release_id`. |
| **Comment** | Thread on a story; `author_member_id` must belong to the project. Supports **@mentions** (see Mention rules). |
| **User (web login)** | Registered human: `users` row linked 1:1 to a **`human` member**. Used for JWT and the SPA; agents often use MCP or service accounts differently. |

---

## Canonical story statuses

API accepts these **primary** values (use them in MCP/API unless you intentionally send legacy aliases):

`icebox_in_progress`, `icebox_approved`, `icebox_rejected`, `icebox_feedback`, `backlog_unstart`, `current_unstart`, `current_started`, `current_review`, `current_delivery`, `done`.

**Legacy aliases** accepted and mapped internally, for example:

- `icebox` → `icebox_in_progress`
- `backlog` → `backlog_unstart`
- `ready` → `current_unstart`
- `in_progress` → `current_started`
- `review` → `current_review`
- `cancelled` → `icebox_rejected`

The **Kanban UI** groups some of these visually (Icebox / Backlog / Current / Done) — semantics are driven by the exact status strings above.

---

## Major features (for planning & automation)

1. **Projects & settings** — CRUD projects; patch `settings` (workflow template, storage overview, integrations metadata).
2. **Members & roster** — Create members; list/add/remove **project members** with roles.
3. **Workflow templates** — Shared templates created in master data; project must reference one before story mutations.
4. **Stories** — List/create/patch stories; filter list by `status`; story detail includes **full `tasks` array** when returned from `agile_story_get` / `agile_story_create` / `agile_story_update` (MCP).
5. **Story tasks** — List/get/create/update/delete tasks under a story (`/stories/{id}/tasks` or MCP equivalents). Separate from Kanban columns.
6. **Releases** — Plan and attach stories to releases.
7. **Comments** — List/create/update/delete with author/editor member checks and mention validation.
8. **Notifications / real-time** — Web app may receive events (story updates, comments, etc.) via gateway; agents may subscribe depending on deployment.
9. **Chat (MCP / services)** — Additional MCP tools for project chat channels/messages where enabled (same DB-backed chat model as configured in compose).
10. **MCP tooling** — Full mirror of many operations without JWT (see reference doc).

---

## Mention rules (@ in comments)

- Format: `@mention_key` where **`mention_key` = member’s display name with whitespace removed, lowercased** (same idea as `@FirstLast` keyed by normalized token).
- Invalid mention tokens **fail validation** — only mention members that exist / are intended to be alerted per product rules.

---

## Integration expectations

- **`workspace_ref`**: String on the project aligning with workspace/agent layout (paths or repo ids as your org defines).
- **`AGILE_STUDIO_BASE_URL`**: Typical base for HTTP agents, e.g. `http://127.0.0.1:9120/api/v1`.
- **`AGILE_DATABASE_URL`**: SQLAlchemy URL for API and MCP (`mysql+pymysql://.../agile_studio`).

---

## MCP usage reminders (concise)

- All tools → **parse JSON string**; on failure object, read **`error`**.
- **`create_json` / `patch_json`**: Pass a JSON **string** (e.g. serialize an object; for PATCH only include fields that change).
- **Story tasks:** `agile_story_tasks_list`, `agile_story_task_get`, `agile_story_task_create`, `agile_story_task_update`, `agile_story_task_delete`.
- **Project context:** Enriched project payloads may include `project_workflow`, `project_storage`, `workflow_template` — use them before creating stories.

---

## When in doubt

- Prefer **`agile_story_get(story_id)`** for a full picture including **tasks**.
- Before assigning anyone on a story or task, ensure they appear in **`agile_project_members_list(project_id)`** (or create/add the link first).
- For exact field names and error shapes, cross-check **`agile_hub/schemas.py`** and **`mcp_server/MCP_TOOLS_REFERENCE.md`**.
