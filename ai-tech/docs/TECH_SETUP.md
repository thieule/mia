# Mia tech — setup and operations

## Prerequisites

- Python **3.11+**
- Sibling directories **`../core`** (mia-ai / nanobot source) and **`../ai-tools`** (local MCP servers)
- **`ai-tech/.env`** (copy from `EXAMPLE_.env`)

## Environment variables (minimum)

| Variable | Role |
|----------|------|
| `OPENROUTER_API_KEY` | LLM provider |
| `BRAVE_API_KEY` | `web_search` (Brave provider in config) |
| `AI_TOOL_SECRET` | Required for **registry** and **pytest_runner** MCP (stdio servers validate on startup) |
| `GITHUB_TOKEN` | Optional; PAT for GitHub MCP when not using GitHub App |

`start.py` sets `TEST_RUNS_PATH_MIA_TECH` by default to `workspace/agent/test-runs/` when unset or empty.

## Ports and isolation

| | **Mia (example deployment)** | **Mia tech (`ai-tech/`)** |
|--|--------|--------|
| Gateway (default) | 18791 | **18792** |
| Config | `mia/config/config.json` | `ai-tech/config/config.json` |
| Discord token env | `DISCORD_BOT_TOKEN` | `DISCORD_BOT_TOKEN_MIA_TECH` |

Discord is **disabled** in the committed default config; enable it only after filling the token and `DISCORD_ADMIN_USER_IDS`.

## MCP command (`python`)

`config.json` launches local MCPs with **`python`** on `PATH`. If your machine only has the Windows **`py`** launcher, either add `python` to `PATH` or change `command` in the JSON to `py` with suitable `args` (e.g. `["-3.12", "../ai-tools/registry/server.py"]`).

## Security

- **`restrictToWorkspace`: false** allows reading (and, with `write_file`, modifying) files **anywhere** on disk if the model uses absolute paths. Acceptable for **trusted local dev**; for Discord-facing or shared servers, set **`restrictToWorkspace`** to **true** and document allowed roots in `workspace/admin/`.
- **`exec`** is **on** — treat gateway credentials and network access like a developer shell.
- **Admin gate before coding:** workspace policy in **`../workspace/admin/PRE_IMPLEMENTATION_APPROVAL.md`** — Mia tech must get **explicit admin confirmation** before mutating tools run; set **`DISCORD_ADMIN_USER_IDS`** when Discord is enabled so admins are identifiable.
- **Tests before “done”:** **`../workspace/admin/TESTING_AND_DEFINITION_OF_DONE.md`** — code changes require **unit tests** and a **pytest run** with reported results before claiming work is complete.
- **Docs before “done”:** **`../workspace/admin/DOCUMENTATION_AND_COMPLETION_CHECKLIST.md`** — update documentation, add **`projects/<slug>/docs/`** per module where applicable, and file **`COMPLETION_CHECKLIST.md`**; template under **`../workspace/docs/templates/`**.
- **English in repo:** **`../workspace/admin/CODE_COMMENTS_AND_ERRORS_ENGLISH.md`** — comments, docstrings, error/log strings, and **policy-driven documentation** (README, `docs/`, checklists) must be **English** (unless an admin exception is recorded there).
- **Audit / what Mia tech did:** **`../workspace/admin/AUDIT_LOG_AND_OBSERVABILITY.md`** — session **JSONL** under `workspace/sessions/`, gateway **stdout** logs, **Git** history, and **completion checklists**; not a separate tamper-proof SIEM by default.

## Adding more MCPs

Edit `config/config.json` under `tools.mcpServers` (same patterns as `mia/config/config.json`). Restart the gateway after changes.
