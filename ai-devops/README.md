# Mia DevOps

**Tên gọi chính thức:** **Mia DevOps** — tên **M** + **DevOps** (cả cụm DevOps dùng như tên sản phẩm). Thư mục: `ai-devops/`.

Standalone deployment for **Mia DevOps** — hỗ trợ **triển khai**, **cấu hình hạ tầng** (Docker, Compose, Nginx, systemd, cloud CLIs nếu có trên máy chạy gateway), **CI/CD** (GitHub / workflows qua MCP), **runbook**, kiểm thử tự động qua `pytest` MCP, và **registry** để tìm thêm MCP. **`exec`** mặc định **300s** cho lệnh dài; **`restrictToWorkspace: false`** để đọc cùng monorepo (cẩn trọng với bí mật trên môi trường mở — xem [docs/DEVOPS_SETUP.md](./docs/DEVOPS_SETUP.md)).

Sử dụng cùng gói **mia** (`../core`), gateway mặc định **18794**, token Discord `DISCORD_BOT_TOKEN_MIA_DEVOPS`.

## Repo layout

```text
core/
ai-tools/
ai-devops/
  config/config.json
  start.py
  EXAMPLE_.env
  workspace/
  docs/
```

## Quick start

1. `cd ai-devops`
2. `copy EXAMPLE_.env .env` — `OPENROUTER_API_KEY`, `BRAVE_API_KEY`, `AI_TOOL_SECRET`, tùy chọn `GITHUB_TOKEN`
3. `python start.py`

Bật Discord: điền `DISCORD_BOT_TOKEN_MIA_DEVOPS` và `DISCORD_ADMIN_USER_IDS`, rồi `"channels.discord.enabled": true` trong `config/config.json`.

## Tài liệu

- [docs/README.md](./docs/README.md)
- [docs/DEVOPS_SETUP.md](./docs/DEVOPS_SETUP.md) — port, công cụ, **mở rộng MCP** (thêm tool DevOps)
- [workspace/admin/](./workspace/admin/) — chính sách phê duyệt, audit

## Các dòng khác (cùng monorepo)

- [Mia tech — ../ai-tech/README.md](../ai-tech/README.md) — kỹ thuật / code (port **18792**)
- [Mia BA — ../ai-ba/README.md](../ai-ba/README.md) — business analysis (port **18793**)
- [Mia QC — ../ai-qc/README.md](../ai-qc/README.md) — test API, UI/E2E (port **18795**)
