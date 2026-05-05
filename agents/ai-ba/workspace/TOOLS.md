# Tools (Mia BA)

## What loads

- **Built-ins:** `read_file`, `write_file`, `edit_file`, `list_dir`, `glob`, `grep`, `notebook_edit`, **`web_search`**, **`web_fetch`**, **`exec`**, **`message`**, **`spawn`**, **`cron`** (when enabled on the gateway).
- **`web_search` providers** (see `config/config.json` → `tools.web.search.provider`): **duckduckgo** and **wikipedia** need no API key; **wikipedia** uses `WIKIPEDIA_ORIGIN` (optional, default English Wikipedia). **searxng** is free if you set an instance URL.
- **MCP (from `config/config.json`):**
  - **`registry`** — `mcp_registry_find_tools`, `mcp_registry_list_all_tools`.
  - **`pytest_runner`** — when analysis touches a repo with automated tests; reports under `TEST_RUNS_PATH_MIA_BA` (default `workspace/agent/test-runs/`).
  - **`github`** — GitHub MCP when `GITHUB_MCP_AUTH_HEADER` is set (via `start.py` / `.env`).
  - **`agile-studio`** — **`agile_project_get`** / **`agile_projects_list`**: read **`settings.github_repository`**, **`documents_storage_path`**, **`storage_overview`**, **`workspace_ref`** so specs target the right Git layout.

## Workspace boundary

- **`restrictToWorkspace`** is **true** by default for Mia BA: file tools stay under the workspace unless config/policy changes.
- Prefer **canonical specs in Git** when MCP exposes repo paths (see playbook); otherwise drafts under **`agent/`** (and `policy/` only when those human-maintained files explicitly allow).

## Writes and mutating commands

- **`policy/PRE_IMPLEMENTATION_APPROVAL.md`** applies before durable **mutations** (writes, mutating `exec`, implementation `spawn`) per policy.

## Tests and “done”

- **Code in scope:** **`policy/TESTING_AND_DEFINITION_OF_DONE.md`**.
- **Analysis / docs in scope:** **`policy/DOCUMENTATION_AND_COMPLETION_CHECKLIST.md`**.

## Code language (repository)

- **`policy/CODE_COMMENTS_AND_ERRORS_ENGLISH.md`** for anything committed to Git.

## Diagrams

- **Mermaid** for BPM-style flows, sequences, and simple data lineage; keep IDs ASCII-safe.

## Deep BA mode (requirements research, long docs, planning)

- **`web_search` / `web_fetch`** — external benchmarks, regulation summaries, competitor framing; always tie findings back to **actionable requirements**.
- **Long markdown** — primary target path from **`agile_project_get`** (`documents_storage_path` / Git); drafts under **`workspace/agent/requirements/`** when Git metadata is missing; keep an index file when splitting across many parts.
- **`spawn`** — parallel research branches when **`policy/PRE_IMPLEMENTATION_APPROVAL.md`** allows; consolidate into one narrative.
- **Playbook** — follow **`project/BA_DELIVERY_PLAYBOOK.md`** for intake → evidence → FR/NFR layers → planning → traceability.
