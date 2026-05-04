# Mia BA

**Tên gọi chính thức:** **Mia BA** (M + BA in hoa). Thư mục triển khai: `ai-ba/`.

Standalone deployment for **Mia BA** — a **business analysis** assistant: customer needs analysis, requirements discovery, **research** (web + GitHub MCP when configured), **long-form specs** (markdown under `workspace/agent/`), **phased planning** and traceability, user stories, acceptance criteria, process and data flows (Mermaid), stakeholder comms, gap analysis, and prioritisation. Deep engagements follow **`workspace/project/BA_DELIVERY_PLAYBOOK.md`**. Project specs should live in **Git** using **`agile_project_get`** / **`agile_projects_list`** (Agile Studio MCP) for `github_repository`, `documents_storage_path`, and related settings — not guessed paths.

**Deliverable convention:** each **BA output pack** (a folder you hand off—often under `workspace/projects/<slug>/` or the path from Agile) must include a **`README.md` at the pack root** with an **index table** of every spec file so other AIs (e.g. Mia tech) open that README first. Policy: [workspace/AGENTS.md](./workspace/AGENTS.md).

Uses the same **mia** package as other deployments (`../core`), **separate gateway** (default port **18793**), **separate workspace** (`workspace/`), and optional **Discord** bot token `DISCORD_BOT_TOKEN_MIA_BA`.

## Repo layout

```text
core/
ai-tools/
ai-ba/                     # this directory (Mia BA deployment)
  config/config.json
  start.py
  EXAMPLE_.env
  workspace/        # BA workspace (policies, drafts, projects/…)
  docs/
```

## Quick start

1. `cd ai-ba`
2. Copy `EXAMPLE_.env` → `.env` — set at least `OPENROUTER_API_KEY`, `BRAVE_API_KEY`, **`AI_TOOL_SECRET`**, and optionally `GITHUB_TOKEN`.
3. Set `discord.enabled` to **true** in `config/config.json` only after you add `DISCORD_BOT_TOKEN_MIA_BA` and `DISCORD_ADMIN_USER_IDS`.
4. `python start.py`

Flags: `--validate-only`, `--skip-install`, `--no-workspace-init`, `--quiet-pip`.

## Documentation

- [workspace/README.md](./workspace/README.md) — workspace orientation (vs **deliverable** packs; each pack has its own `README.md` index per [workspace/AGENTS.md](./workspace/AGENTS.md))
- [docs/README.md](./docs/README.md) — operator doc index
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
