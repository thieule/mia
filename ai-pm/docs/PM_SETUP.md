# Mia PM — setup and operations

## Prerequisites

- Python **3.11+**
- Thư mục cùng cấp **`../core`**, **`../ai-tools`**
- **`ai-pm/.env`** (sao từ `EXAMPLE_.env`)

## Biến môi trường (tối thiểu)

| Variable | Role |
|----------|------|
| `OPENROUTER_API_KEY` | LLM |
| `BRAVE_API_KEY` | `web_search` (Brave) |
| `AI_TOOL_SECRET` | Bắt buộc cho **registry** và **pytest_runner** |
| `GITHUB_TOKEN` | Tùy chọn; PAT cho GitHub MCP |

`start.py` gán `TEST_RUNS_PATH_MIA_PM` mặc định tới `workspace/agent/test-runs/` khi chưa set.

## Port và tách instance

| | **Mia PM (`ai-pm/`)** |
|--|--------|
| Gateway (mặc định) | **18797** |
| Config | `ai-pm/config/config.json` |
| Discord token env | `DISCORD_BOT_TOKEN_MIA_PM` |

Trong config đã commit, **Discord tắt**; bật sau khi điền token và `DISCORD_ADMIN_USER_IDS`.

## Bảo mật

- **`restrictToWorkspace`:** thường **true** — công cụ file giới hạn trong workspace.
- **`exec`** bật — dùng có kiểm soát (báo cáo, script, export).
- Các chính sách trong `workspace/admin/` (phê duyệt trước khi sửa, test khi đổi code, v.v.) vẫn áp dụng.

## Thêm MCP

Sửa `config/config.json` tại `tools.mcpServers`. Khởi động lại gateway sau khi đổi.
