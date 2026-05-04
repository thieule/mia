# Mia BA — setup and operations

## Prerequisites

- Python **3.11+**
- Sibling directories **`../core`** (mia-ai / nanobot source) and **`../ai-tools`** (local MCP servers)
- **`ai-ba/.env`** (copy from `EXAMPLE_.env`)

## Environment variables (minimum)

| Variable | Role |
|----------|------|
| `OPENROUTER_API_KEY` | LLM provider |
| `BRAVE_API_KEY` | `web_search` when `provider` is **brave** |
| `WIKIPEDIA_ORIGIN` | Optional; wiki host for **wikipedia** provider (default `https://en.wikipedia.org`, e.g. `https://vi.wikipedia.org`) |
| `SEARXNG_BASE_URL` | Required for **searxng** provider when not set in config |
| `AI_TOOL_SECRET` | Required for **registry** and **pytest_runner** MCP (stdio servers validate on startup) |
| `GITHUB_TOKEN` | Optional; PAT for GitHub MCP when not using GitHub App |

**Free search providers** (no paid API key): **duckduckgo**, **wikipedia** (reference articles only), **searxng** (self-hosted or public instance URL). Set `tools.web.search.provider` in `config/config.json`.

`start.py` sets `TEST_RUNS_PATH_MIA_BA` by default to `workspace/agent/test-runs/` when unset or empty.

## Model reasoning (`reasoningEffort`)

In **`config/config.json`**, under **`agents.defaults`**, **`reasoningEffort`** is forwarded to the LLM provider as extended reasoning / thinking where the backend supports it (via Mia core `GenerationSettings`). Typical values include **`low`**, **`medium`**, **`high`**; some providers also accept **`minimal`**, **`none`**, or **`adaptive`** (e.g. Anthropic extended thinking budgets).

- **Mia BA default** in-repo is often **`medium`** — a balance of depth and latency/cost.
- For **maximum analytical depth** on complex BA engagements, try **`high`** (or **`adaptive`** on Anthropic-backed configs).
- Behaviour is **provider-specific** (Gemini OpenAI-compat, OpenAI reasoning models, Anthropic, DashScope “thinking”, etc.); if the API ignores an unsupported value, rely on the **playbook planning pass** in **`workspace/project/BA_DELIVERY_PLAYBOOK.md`** and **`workspace/AGENTS.md`** for structured visible reasoning.

Restart the gateway after changing **`reasoningEffort`**.

### Iterative reflect (`reflectAfterTools`)

Mia core can inject an **ephemeral** user message after each **successful tool batch** so the model reconciles plan vs observations before the next step (`Plan → Act → Observe → Reflect`). The message is **not saved** to session history.

In **`agents.defaults`**, set **`reflectAfterTools`: true** (optional **`reflectInstruction`** for a custom prompt body). Increases tokens per tool round; default in core is **false**.

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
