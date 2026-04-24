# Mia tech

Standalone deployment for **Mia tech** — a **technical** assistant: architecture, troubleshooting, diagrams (Mermaid / ASCII), reading and searching code across the monorepo, GitHub via MCP, web research, optional pytest runs, and shell **`exec`** for builds and CLI tools.

Uses the same **mia** package as other deployments (`../core`), **separate gateway** (default port **18792**), **separate workspace** (`workspace/`), and optional **Discord** bot token `DISCORD_BOT_TOKEN_MIA_TECH`.

## Repo layout

```text
core/
ai-tools/
ai-tech/                    # this directory (Mia tech deployment)
  config/config.json
  start.py
  EXAMPLE_.env
  workspace/        # ai workspace (AGENTS.md, TOOLS.md, …)
  docs/
```

## Quick start

1. `cd ai-tech`
2. `copy EXAMPLE_.env .env` (or `cp` on Unix) — set at least `OPENROUTER_API_KEY`, `BRAVE_API_KEY`, **`AI_TOOL_SECRET`**, and optionally `GITHUB_TOKEN`.
3. `python start.py`

Flags: `--validate-only`, `--skip-install`, `--no-workspace-init`, `--quiet-pip`.

## Documentation

- [docs/README.md](./docs/README.md) — index
- [docs/TECH_SETUP.md](./docs/TECH_SETUP.md) — ports, tools, security notes
- **Governance:** [Pre-implementation approval](./workspace/admin/PRE_IMPLEMENTATION_APPROVAL.md) · [Testing & definition of done](./workspace/admin/TESTING_AND_DEFINITION_OF_DONE.md) · [Documentation & completion checklist](./workspace/admin/DOCUMENTATION_AND_COMPLETION_CHECKLIST.md) · [English: code + repo docs](./workspace/admin/CODE_COMMENTS_AND_ERRORS_ENGLISH.md) · [Audit trail & observability](./workspace/admin/AUDIT_LOG_AND_OBSERVABILITY.md)

## Defaults (config)

- **`restrictToWorkspace`** — set in `config/config.json` (**true** = file tools limited to the workspace; **false** = may read monorepo siblings). Prefer writing long-lived notes under `workspace/agent/`.
- **MCP:** `registry`, `pytest_runner`, remote **GitHub** MCP (needs `GITHUB_TOKEN` or GitHub App env vars).
- **`exec`:** enabled (timeout 180s) for `git`, `pytest`, package managers, etc.

## Related deployment (same monorepo)

- **Mia BA** — [../ai-ba/README.md](../ai-ba/README.md): **business analysis** assistant; default gateway **18793** (`ai-ba/`).
- **Mia DevOps** — [../ai-devops/README.md](../ai-devops/README.md): **deploy / infra / ops** assistant; default gateway **18794** (`ai-devops/`).
- **Mia QC** — [../ai-qc/README.md](../ai-qc/README.md): **API + UI / E2E testing**; default gateway **18795** (`ai-qc/`).
