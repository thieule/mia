# Mia dev

Triển khai **Mia dev** — trợ lý **lập trình / triển khai**: đọc–sửa code, chạy lệnh (`exec`), pytest, GitHub qua MCP, tìm kiếm web. Cùng gói **mia** với các deploy khác (`../core`), **gateway riêng** (mặc định **18796**), **workspace riêng** (`workspace/`), token Discord tùy chọn `DISCORD_BOT_TOKEN_MIA_DEV` (Discord tắt mặc định trong `config/config.json`).

## Cấu trúc

```text
core/
ai-tools/
ai-dev/
  config/config.json
  start.py
  EXAMPLE_.env
  workspace/
  docs/
```

## Chạy nhanh

1. `cd ai-dev`
2. `copy EXAMPLE_.env .env` — điền tối thiểu `OPENROUTER_API_KEY`, `BRAVE_API_KEY`, `AI_TOOL_SECRET`, và tùy chọn `GITHUB_TOKEN`.
3. `python start.py`

Cờ: `--validate-only`, `--skip-install`, `--no-workspace-init`, `--quiet-pip`.

## Tài liệu

- [docs/README.md](./docs/README.md) — mục lục
- [docs/DEV_SETUP.md](./docs/DEV_SETUP.md) — port, công cụ, ghi chú bảo mật
- Chính sách workspace: [PRE_IMPLEMENTATION_APPROVAL](./workspace/admin/PRE_IMPLEMENTATION_APPROVAL.md) · [TESTING_AND_DEFINITION_OF_DONE](./workspace/admin/TESTING_AND_DEFINITION_OF_DONE.md) · v.v. (kế thừa từ template)

## Cấu hình mặc định

- **`restrictToWorkspace`** — thường **true** (công cụ file giới hạn trong workspace). Ghi ghi chú dài dưới `workspace/agent/`.
- **MCP:** `registry`, `pytest_runner` (`TEST_RUNS_PATH_MIA_DEV`), **GitHub** (cần token / GitHub App qua `start.py`).
- **`exec`:** bật, timeout **300s**.

## Deploy liên quan (cùng monorepo)

- [../ai-tech/README.md](../ai-tech/README.md) — thiết kế / kiến trúc (gateway **18792**)
- [../ai-ba/README.md](../ai-ba/README.md) — BA (**18793**)
- [../ai-devops/README.md](../ai-devops/README.md) — DevOps (**18794**)
- [../ai-qc/README.md](../ai-qc/README.md) — QC (**18795**)
- [../ai-pm/README.md](../ai-pm/README.md) — PM (**18797**)
