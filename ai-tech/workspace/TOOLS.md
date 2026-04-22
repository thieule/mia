# Tools (Mia tech)

## What loads

- **Built-ins:** `read_file`, `write_file`, `edit_file`, `list_dir`, `glob`, `grep`, `notebook_edit`, **`web_search`**, **`web_fetch`**, **`exec`**, **`message`**, **`spawn`**, **`cron`** (when enabled on the gateway).
- **MCP (from `config/config.json`):**
  - **`registry`** — `mcp_registry_find_tools`, `mcp_registry_list_all_tools` (catalog; not every entry is installed).
  - **`pytest_runner`** — run suites; reports under `TEST_RUNS_PATH_MIA_TECH` (default `workspace/agent/test-runs/`).
  - **`github`** — GitHub MCP when `GITHUB_MCP_AUTH_HEADER` is set (PAT or App token via `start.py`).

## Workspace boundary

- **`restrictToWorkspace`** follows `config/config.json` (often **true** for Mia tech): when **true**, **`read_file`** / **`grep`** are limited to the workspace root; when **false**, you may read monorepo siblings. Still avoid reading secrets (`.env`, key files) unless the user explicitly asks and policy allows.
- Prefer **writing** long-lived content to **`agent/`** (and `admin/` only when policy says so).

## Writes and mutating commands

- **`admin/PRE_IMPLEMENTATION_APPROVAL.md`** applies: **confirm the idea and scope with an admin** before **`write_file`**, **`edit_file`**, mutating **`exec`**, or implementation **`spawn`**. Read-only tools are not gated by that flow unless policy is extended.

## Tests and “done”

- **`admin/TESTING_AND_DEFINITION_OF_DONE.md`**: implementation changes need **unit tests**; run **`pytest`** (via **`mcp_pytest_runner_*`** or **`exec`**) and report results **before** stating the task is **done**. Do not claim completion on failing or skipped runs without an admin-documented exception.
- **`admin/DOCUMENTATION_AND_COMPLETION_CHECKLIST.md`**: update **docs**, add **supplementary** material if needed, and write **`projects/<slug>/docs/COMPLETION_CHECKLIST.md`** (or repo-equivalent) **before** “done”. Template: **`docs/templates/COMPLETION_CHECKLIST.template.md`**.

## Code language (repository)

- **`admin/CODE_COMMENTS_AND_ERRORS_ENGLISH.md`**: comments, docstrings, exceptions, operator-facing errors/logs, and **markdown docs** you add under policy (README, `docs/`, checklists) must be **English**.

## Diagrams

- **Mermaid** in markdown responses is encouraged for architecture and sequences.
- Keep node IDs simple; label edges when ambiguity is likely.
