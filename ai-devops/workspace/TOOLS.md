# Tools (Mia DevOps)

## What loads

- **Built-ins:** `read_file`, `write_file`, `edit_file`, `list_dir`, `glob`, `grep`, `notebook_edit`, **`web_search`**, **`web_fetch`**, **`exec`**, **`message`**, **`spawn`**, **`cron`** (if enabled on gateway).
- **MCP (`config/config.json`):**
  - **`registry`** — discover tools: `mcp_registry_find_tools`, `mcp_registry_list_all_tools` (use to validate new DevOps MCPs after config changes).
  - **`pytest_runner`** — when automation or app code is in scope; reports under `TEST_RUNS_PATH_MIA_DEVOPS` (default `workspace/agent/test-runs/`).
  - **`github`** — workflows, issues, API-oriented tasks when `GITHUB_MCP_AUTH_HEADER` is set.

## Workspace boundary

- This deployment often sets **`restrictToWorkspace`: false** so you can read **sibling** repos and infra files — still follow **`admin/PRE_IMPLEMENTATION_APPROVAL.md`** and avoid harvesting secrets.
- Durable runbooks and drafts under **`agent/`**.

## Exec (DevOps)

- **Timeout 300s** in default `config` — long builds/deploys; if a job exceeds policy, say so and suggest running outside the agent.
- **Never** `exec` destructive production commands without admin policy alignment.

## Adding more MCPs

- Team extends **`config/config.json`** (see **`docs/DEVOPS_SETUP.md`**) for Docker / K8s / Atlassian / other servers; then restart the gateway and verify via **registry** tools.
