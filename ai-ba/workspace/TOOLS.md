# Tools (Mia BA)

## What loads

- **Built-ins:** `read_file`, `write_file`, `edit_file`, `list_dir`, `glob`, `grep`, `notebook_edit`, **`web_search`**, **`web_fetch`**, **`exec`**, **`message`**, **`spawn`**, **`cron`** (when enabled on the gateway).
- **MCP (from `config/config.json`):**
  - **`registry`** — `mcp_registry_find_tools`, `mcp_registry_list_all_tools`.
  - **`pytest_runner`** — when analysis touches a repo with automated tests; reports under `TEST_RUNS_PATH_MIA_BA` (default `workspace/agent/test-runs/`).
  - **`github`** — GitHub MCP when `GITHUB_MCP_AUTH_HEADER` is set (via `start.py` / `.env`).

## Workspace boundary

- **`restrictToWorkspace`** is **true** by default for Mia BA: file tools stay under the workspace unless config/policy changes.
- Prefer **writing** BA artefacts under **`agent/`** (and `admin/` only when policy allows).

## Writes and mutating commands

- **`admin/PRE_IMPLEMENTATION_APPROVAL.md`** applies before durable **mutations** (writes, mutating `exec`, implementation `spawn`) per policy.

## Tests and “done”

- **Code in scope:** **`admin/TESTING_AND_DEFINITION_OF_DONE.md`**.
- **Analysis / docs in scope:** **`admin/DOCUMENTATION_AND_COMPLETION_CHECKLIST.md`**.

## Code language (repository)

- **`admin/CODE_COMMENTS_AND_ERRORS_ENGLISH.md`** for anything committed to Git.

## Diagrams

- **Mermaid** for BPM-style flows, sequences, and simple data lineage; keep IDs ASCII-safe.
