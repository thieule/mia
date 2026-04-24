# Tools (Mia QC)

## What loads

- **Built-ins:** `read_file`, `write_file`, `edit_file`, `list_dir`, `glob`, `grep`, `notebook_edit`, **`web_search`**, **`web_fetch`**, **`exec`**, **`message`**, **`spawn`**, **`cron`** (if enabled).
- **MCP:**
  - **`pytest_runner`** — Python tests; results under `TEST_RUNS_PATH_MIA_QC` (default `workspace/agent/test-runs/`).
  - **`github`** — issues, PRs, workflow YAML for test pipelines.
  - **`registry`** — list/discover additional MCPs after the team extends `config.json`.

## API testing

- Prefer **pytest** + project conventions; use **`mcp_pytest_runner_*`** with clear scope (file/dir).
- **curl** / **httpx** patterns via **`exec`** or code under test — do not log secrets.

## UI / E2E

- **Playwright** / **Cypress** / **npm test** — typically `npx` or package scripts via **`exec`**; requires **Node** and browsers/install steps on the **host** running the gateway.
- If not installed: state **blocker** and the install one-liner from official docs (via `web_fetch` if needed).

## Workspace

- **`restrictToWorkspace`:** often **false** here so you can read app/test repos in the monorepo; still follow **`admin/`** and do not exfiltrate secrets.
