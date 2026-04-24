# Mia PM

Triển khai **Mia PM** — trợ lý **quản lý dự án / sản phẩm**: charter, ưu tiên, lịch, gán trách nhiệm (tài liệu), theo dõi tiến độ, **rủi ro**, **báo cáo**; `exec` và web; GitHub qua MCP khi cần. Cùng gói **mia** với `../core`, **gateway riêng** (mặc định **18797**), `workspace/`, token Discord tùy chọn `DISCORD_BOT_TOKEN_MIA_PM` (Discord tắt mặc định trong `config/config.json`).

## Cấu trúc (tóm tắt)

```
ai-pm/
  config/       # config.json — gateway, Discord, tool toggles, MCP
  start.py     # cài mia + ai-tools (registry, pytest MCP), nạp .env, chạy gateway
  EXAMPLE_.env
  workspace/   # bộ não triển khai — dự án, báo cáo, tài liệu PM
```

## Cách chạy nhanh

1. `cd ai-pm`
2. Tạo `.env` từ `EXAMPLE_.env` (OpenRouter, `AI_TOOL_SECRET`, …).
3. `python start.py` (hoặc `--validate-only` / `--skip-install` — xem `start.py`).

- **Gọi mô hình thử:** `http --json POST :18797/health` (hoặc tích hợp client tương ứ).

Xem thêm: **[docs/PM_SETUP.md](docs/PM_SETUP.md)**, gợi ý biến môi trường: **[../core/EXAMPLE_.env](../core/EXAMPLE_.env)**.

## Liên quan

- [../ai-tech/README.md](../ai-tech/README.md) — Kiến trúc (**18792**)
- [../ai-ba/README.md](../ai-ba/README.md) — BA (**18793**)
- [../ai-devops/README.md](../ai-devops/README.md) — DevOps (**18794**)
- [../ai-qc/README.md](../ai-qc/README.md) — QC (**18795**)
- [../ai-dev/README.md](../ai-dev/README.md) — Lập trình viên (**18796**)
- [../workflow-runtime/](../workflow-runtime/) — hàng đợi workflow, phê duyệt (human-in-the-loop)

## MCP mặc định (qua `config/config.json`)

- **MCP:** `registry`, `pytest_runner` (`TEST_RUNS_PATH_MIA_PM`), **GitHub** (cần token / GitHub App qua `start.py`).
