# Mia BA — setup and operations

## Prerequisites

- Python **3.11+**
- Sibling directories **`../core`** (mia-ai / nanobot source) and **`../ai-tools`** (local MCP servers)
- **`ai-ba/.env`** (copy from `EXAMPLE_.env`)

## Environment variables (minimum)

| Variable | Role |
|----------|------|
| `OPENROUTER_API_KEY` | LLM provider |
| `BRAVE_API_KEY` | `web_search` (Brave provider in config) |
| `AI_TOOL_SECRET` | Required for **registry** and **pytest_runner** MCP (stdio servers validate on startup) |
| `GITHUB_TOKEN` | Optional; PAT for GitHub MCP when not using GitHub App |

`start.py` sets `TEST_RUNS_PATH_MIA_BA` by default to `workspace/agent/test-runs/` when unset or empty.

## Ports and isolation

| | **Mia tech** | **Mia BA (`ai-ba/`)** |
|--|--------|--------|
| Gateway (default) | **18792** | **18793** |
| Config | `ai-tech/config/config.json` | `ai-ba/config/config.json` |
| Discord token env | `DISCORD_BOT_TOKEN_MIA_TECH` | `DISCORD_BOT_TOKEN_MIA_BA` |

Discord is **disabled** in the committed default `config.json` for Mia BA; enable it only after filling the token and `DISCORD_ADMIN_USER_IDS`.

## MCP command (`python`)

`config.json` launches local MCPs with **`python`** on `PATH`. If your machine only has the Windows **`py`** launcher, either add `python` to `PATH` or change `command` in the JSON to `py` with suitable `args` (e.g. `["-3.12", "../ai-tools/registry/server.py"]`).

## Security

- **`restrictToWorkspace`: true** (default here) limits file tools to the workspace — preferred for BA-facing or shared servers.
- **`exec`** is **on** — treat gateway credentials and network access like a trusted analyst shell.
- **Admin gate before mutating:** workspace policy in **`../workspace/admin/PRE_IMPLEMENTATION_APPROVAL.md`** — Mia BA must get **explicit admin confirmation** before mutating tools run when policy applies.
- **Tests before “done”** (when the task changes **code**): **`../workspace/admin/TESTING_AND_DEFINITION_OF_DONE.md`**. Pure BA deliverables (requirements docs, diagrams in chat) follow **`../workspace/admin/DOCUMENTATION_AND_COMPLETION_CHECKLIST.md`**.
- **English in repo:** **`../workspace/admin/CODE_COMMENTS_AND_ERRORS_ENGLISH.md`**
- **Audit:** **`../workspace/admin/AUDIT_LOG_AND_OBSERVABILITY.md`**

## Adding more MCPs

Edit `config/config.json` under `tools.mcpServers`. Restart the gateway after changes.
