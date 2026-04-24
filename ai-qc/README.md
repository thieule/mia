# Mia QC

**Tên gọi:** **Mia QC** — Quality Control / testing line: **API** (contract, status, schema, pytest), **giao diện** (E2E, smoke, accessibility gợi ý), kế hoạch kiểm thử, báo cáo lỗi có bước tái hiện.

Thư mục: `ai-qc/`. Gateway mặc định **18795**, token `DISCORD_BOT_TOKEN_MIA_QC`.

- **`pytest_runner` MCP** + **`exec`** (timeout 300s) cho suite dài / Playwright / `npx`.
- **`registry`** để tìm thêm MCP khi team bổ sung.
- **`restrictToWorkspace: false`** — đọc repo test / app ở monorepo; vẫn tuân **`admin/`** và không lộ secret.

## Quick start

1. `cd ai-qc`
2. `copy EXAMPLE_.env .env` — điền `OPENROUTER_API_KEY`, `BRAVE_API_KEY`, `AI_TOOL_SECRET`
3. `python start.py`

Xem [docs/QC_SETUP.md](./docs/QC_SETUP.md) (API, UI/E2E, mở rộng MCP).

## Các dòng khác

- [Mia tech — ../ai-tech/README.md](../ai-tech/README.md) — **18792**
- [Mia BA — ../ai-ba/README.md](../ai-ba/README.md) — **18793**
- [Mia DevOps — ../ai-devops/README.md](../ai-devops/README.md) — **18794**
