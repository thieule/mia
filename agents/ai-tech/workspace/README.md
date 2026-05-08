# Mia tech workspace (repo seed)

**Mia tech** is the **technical-line** assistant (design, code, research, GitHub, tests). This directory is the nanobot **workspace** (`./workspace` in `config/config.json`). Committed markdown seeds role and tool hints; `memory/`, `cron/`, and `sessions/` are runtime paths (see `../.gitignore`).

| Path | Role |
|------|------|
| **`AGENTS.md`** | Primary role, priorities, boundaries |
| **`docs/AI_PROJECT_WORKSPACE_SPEC.md`** | Per-project Git layout: MCP + user + `memory/MEMORY.md` — no fixed repo in prompts |
| **`TOOLS.md`** | How file/MCP/exec tools are expected to be used here |
| **`SOUL.md`**, **`USER.md`** | Voice and team context |
| **`policy/`** | Human-maintained **rules only** (approval, tests, docs closure, English in repo) |
| **`agent/`** | Notes, design drafts, investigation logs, pytest JSON runs (`agent/test-runs/`) |
| **`docs/`** | Specs, templates, **operator** references (audit trail how-to — not policy); start at **`docs/README.md`** |

