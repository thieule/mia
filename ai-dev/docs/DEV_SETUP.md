# Mia dev — setup and operations

## Prerequisites

- Python **3.11+**
- Thư mục cùng cấp **`../core`**, **`../ai-tools`**
- **`ai-dev/.env`** (sao từ `EXAMPLE_.env`)

## Biến môi trường (tối thiểu)

| Variable | Role |
|----------|------|
| `OPENROUTER_API_KEY` | LLM |
| `BRAVE_API_KEY` | `web_search` (Brave) |
| `AI_TOOL_SECRET` | Bắt buộc cho **registry** và **pytest_runner** |
| `GITHUB_TOKEN` | Tùy chọn; PAT cho GitHub MCP |

`start.py` gán `TEST_RUNS_PATH_MIA_DEV` mặc định tới `workspace/agent/test-runs/` khi chưa set.

## Port và tách instance

| | **Mia dev (`ai-dev/`)** |
|--|--------|
| Gateway (mặc định) | **18796** |
| Config | `ai-dev/config/config.json` |
| Discord token env | `DISCORD_BOT_TOKEN_MIA_DEV` |

Trong config đã commit, **Discord tắt**; bật sau khi điền token và `DISCORD_ADMIN_USER_IDS`.

## Bảo mật

- **`restrictToWorkspace`:** thường **true** — công cụ file giới hạn trong workspace.
- **`exec`** bật — xử lý gateway như shell dev đáng tin.
- Các chính sách trong `workspace/admin/` (phê duyệt trước khi sửa, test trước khi “done”, v.v.) vẫn áp dụng.

## Thêm MCP

Sửa `config/config.json` tại `tools.mcpServers`. Khởi động lại gateway sau khi đổi.
