# Mia BA

**Tên gọi chính thức:** **Mia BA** (M + BA in hoa). Thư mục triển khai: `ai-ba/`.

Standalone deployment for **Mia BA** — a **business analysis** assistant: requirements, user stories, acceptance criteria, process and data flows (Mermaid), stakeholder comms, gap analysis, prioritisation, and **research** via web + GitHub MCP when configured.

Uses the same **mia** package as other deployments (`../core`), **separate gateway** (default port **18793**), **separate workspace** (`workspace/`), and optional **Discord** bot token `DISCORD_BOT_TOKEN_MIA_BA`.

## Repo layout

```text
core/
ai-tools/
ai-ba/                     # this directory (Mia BA deployment)
  config/config.json
  start.py
  EXAMPLE_.env
  workspace/        # BA workspace (AGENTS.md, TOOLS.md, …)
  docs/
```

## Quick start

1. `cd ai-ba`
2. Copy `EXAMPLE_.env` → `.env` — set at least `OPENROUTER_API_KEY`, `BRAVE_API_KEY`, **`AI_TOOL_SECRET`**, and optionally `GITHUB_TOKEN`.
3. Set `discord.enabled` to **true** in `config/config.json` only after you add `DISCORD_BOT_TOKEN_MIA_BA` and `DISCORD_ADMIN_USER_IDS`.
4. `python start.py`

Flags: `--validate-only`, `--skip-install`, `--no-workspace-init`, `--quiet-pip`.

## Documentation

- [docs/README.md](./docs/README.md) — index
- [docs/BA_SETUP.md](./docs/BA_SETUP.md) — ports, tools, security notes
- **Governance:** same pattern as Mia tech — see [workspace/admin/](./workspace/admin/)

## Defaults (config)

- **`restrictToWorkspace`: true** — BA artefacts stay under `workspace/` unless you widen policy.
- **MCP:** `registry`, `pytest_runner` (for repos that still run tests), remote **GitHub** MCP when auth is set.
- **`exec`:** enabled for spreadsheets export, `git` for docs repos, etc., within policy.

## Related deployment

- **Mia tech** (`../ai-tech/`) — engineering / code-focused line; default gateway **18792**.
- **Mia DevOps** (`../ai-devops/`) — deploy, infra, CI/CD; default gateway **18794**.
- **Mia QC** (`../ai-qc/`) — test API, UI/E2E, QC; default gateway **18795**.
- **Mia PM** (`../ai-pm/`) — dự án, ưu tiên, lịch, rủi ro, báo cáo; default gateway **18797**.
