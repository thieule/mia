# Mia DevOps — setup, tools, and extending MCP

## Prerequisites

- Python **3.11+**
- **`../core`**, **`../ai-tools`**
- **`ai-devops/.env`** từ `EXAMPLE_.env`
- (Tuỳ nhiệm vụ) Trên host gateway: `docker`, `docker compose` / `kubectl` / `ssh` / `terraform` nếu bạn muốn agent gọi qua **`exec`** — gateway không cài sẵn; agent chỉ dùng những gì **PATH** có.

## Environment (tối thiểu)

| Variable | Role |
|----------|------|
| `OPENROUTER_API_KEY` | LLM |
| `BRAVE_API_KEY` | `web_search` (Brave) |
| `AI_TOOL_SECRET` | **registry** + **pytest_runner** (stdio) |
| `GITHUB_TOKEN` | GitHub MCP: Actions, issues, nội dung cho CI/CD |
| `DISCORD_BOT_TOKEN_MIA_DEVOPS` | (khi bật Discord) |

`start.py` gán `TEST_RUNS_PATH_MIA_DEVOPS` mặc định tới `workspace/agent/test-runs/` nếu trống.

## Cổng & tách line

| | Mia tech | Mia BA | **Mia DevOps** |
|---|--------|--------|----------------|
| Gateway | 18792 | 18793 | **18794** |
| Thư mục | `ai-tech/` | `ai-ba/` | `ai-devops/` |
| Token Discord | `DISCORD_BOT_TOKEN_MIA_TECH` | `DISCORD_BOT_TOKEN_MIA_BA` | `DISCORD_BOT_TOKEN_MIA_DEVOPS` |

Có thể chạy **cả ba** cùng lúc; mỗi bản một **port** riêng.

## Hành vi cấu hình mặc định

- **`tools.exec`:** `enable: true`, **`timeout: 300`** (giây) — dùng build/deploy/apply dài; giảm hoặc tăng tùy policy.
- **`restrictToWorkspace: false`** — cho phép `read_file` / `grep` ngoài `ai-devops/workspace` (ví dụ kịch bản ở `../`, repo sibling). Với môi trường **công cộng / Discord**, cân nhắc bật **`true`** và siết policy trong `workspace/admin/`.
- **MCP:** `registry` (tìm tool từ catalog), `pytest_runner` (nếu cần test sau thay code), `github` (PAT hoặc GitHub App qua `start.py` + biến env giốp các line khác).

## Thêm MCP hỗ trợ DevOps (khuyến nghị)

Kho `ai-tools` mặc định cung cấp **registry + pytest**; bạn có thể **bổ sung** server khác (Docker/K8s/Atlassian/…) theo tài liệu chính thức của từng server.

1. Cài bản command phù hợp hệ (ví dụ `npx`, `uvx`, hoặc `python` trỏ script cục bộ).
2. Sửa **`config/config.json`**, mục `tools.mcpServers` — cùng pattern với mục `registry` / `github`.
3. Truyền `env` cần thiết (token, kubeconfig, v.v.); **không** commit secret.
4. Khởi động lại gateway.

Gợi ý: **Atlassian** (Jira/Confluence runbook) — thử xem `../ai-tools/launchers/run_atlassian_mcp.py` và cấu hình env Jira/Confluence của team, rồi thêm block `mcpServers` tương ứng. **MCP từ npm (Docker/K8s cộng đồng):** tìm package trên mạng, kiểm tra trust, thử `npx` với mạng bị hạn chế nếu cần.

Sau khi cài thêm, dùng **`mcp_registry_list_all_tools`** để xác minh tên công cụ mới xuất hiện ở gateway.

## Bảo mật

- `exec` **rất mạnh** (chạy shell như user chạy gateway) — chỉ dùng trên host tin cậy, hoặc siết theo `admin/`.
- Không đưa **key**, **.pem**, mật khẩu server vào chat; dùng env / secret store phù hợp quy trình tổ chức bạn.
- Cân nhắc **`restrictToWorkspace: true`** khi mở rộng ra internet (Discord, IP công cộng).

## MCP command (`python`)

Các server dùng `command` / `args` tương tự [../ai-tech/docs/TECH_SETUP.md](../ai-tech/docs/TECH_SETUP.md) (đổi đường dẫn tới `../ai-devops/` nếu chạy từ thư mục này).
