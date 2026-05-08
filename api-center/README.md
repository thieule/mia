# API Center

Standalone service, independent from `workflow-runtime`.

Integration doc for Agile Studio: `AGILE_STUDIO_INTEGRATION.md`.

## Purpose

- Session handshake between Agile Studio and AI backend
- Reconnect session key
- Return list of AI agents for member picker
- Receive/store MCP API key from Agile Studio
- Chat bridge contract (HTTP + WebSocket)
- Webhook notification routing vào working queue theo agent

## Start

```bash
cd api-center
pip install -r requirements.txt
python api_center.py
```

Start API Center and auto-start all agents in `agents.json`:

```bash
python api_center.py --start-agents
```

Start only selected agents:

```bash
python api_center.py --start-agents --agent-ids "mia-dev,mia-tech"
```

By default each agent launcher gets `--skip-install`. You can override:

```bash
python api_center.py --start-agents --agent-start-args "--skip-install --quiet-pip"
```

Default: `127.0.0.1:18881`.

Thư mục **`agents/`** ở gốc monorepo gồm **`core/`** (gói mia), **`ai-tools/`** (MCP cục bộ) và các triển khai **`ai-*`** (gateway + workspace). `agents.json` dùng đường dẫn tương đối dạng **`agents/…/workspace`**.

## Env

Copy `EXAMPLE_.env` to `.env` and set:

- `API_CENTER_CONNECT_SECRET` (required, >= 12 chars)

Optional:

- `API_CENTER_PORT`
- `API_CENTER_PUBLIC_BASE_URL`
- `API_CENTER_AGENTS_FILE`
- `API_CENTER_CATALOG_FILE`
- `API_CENTER_SESSION_TTL_DAYS`
- `API_CENTER_MCP_REPLY_PATH` (default: `/agent-chat/reply`)
- `API_CENTER_AGILE_REPLY_URL` (fallback callback API — nên trỏ Agile Studio: `http://127.0.0.1:9120/api/v1/integrations/api-center/agent-reply` nếu Hub và Agile cùng máy)
- `API_CENTER_AGILE_REPLY_TOKEN` (bắt buộc nếu dùng callback: phải **cùng giá trị** với `AGILE_AGENT_REPLY_TOKEN` trên Agile Studio)
- `API_CENTER_CHAT_WAIT_TIMEOUT_S` (default: `45`, thời gian chờ kết quả agent)
- `API_CENTER_WORKING_QUEUE_SUBDIR` (default: `working_queue`)
- `API_CENTER_CORE_DIR` (optional, mặc định `../agents/core`)
- `API_CENTER_ADMIN_SECRET` (optional nhưng **bắt buộc** nếu gọi admin API; thiếu → các route `/v1/admin/*` trả `503`)
- `API_CENTER_AGENT_DB_URL` hoặc `AGILE_DATABASE_URL` / `MIA_AGENT_SYNC_DATABASE_URL` (MySQL; dùng cho ghi `mia_agents`, `mia_agent_prompts` — xem `docs/AGENT_STATE_DATABASE.md` và `schema/migrate_mia_agent_prompts_skills_mysql.sql`)

## Admin API (quản lý agent + DB)

Dùng cho vận hành: tạo agent mới (scaffold thư mục giống mẫu `agents/ai-tech`, cập nhật `agents.json`, ghi DB), liệt kê, xóa agent, thêm/xóa prompt trong DB.

- **Auth:** header `X-Api-Center-Admin-Secret` phải khớp `API_CENTER_ADMIN_SECRET` (không dùng Bearer session).
- **DB:** cần URL MySQL và đã chạy migration; tạo agent mà không cấu hình DB sẽ nhận lỗi sau khi rollback file/thư mục (xem chi tiết trong code `agent_management` / `api_center`).

| Method | Path | Mô tả ngắn |
|--------|------|------------|
| `GET` | `/v1/admin/agents` | Danh sách agent runtime (sau merge catalog) + `db_agents` nếu DB khả dụng |
| `POST` | `/v1/admin/agents` | Tạo agent: body gồm `id` (vd. `mia-demo`), **`gateway_port`** (bắt buộc), tùy chọn `display_name`, `workspace_folder` (`ai-...`), `template` (mặc định `ai-tech`), `role`, `description` |
| `DELETE` | `/v1/admin/agents/{agent_id}` | Xóa khỏi `agents.json` + DB; query `purge_workspace=true` để xóa luôn thư mục `agents/ai-...` |
| `GET` | `/v1/admin/agents/{agent_id}/prompts` | Liệt kê prompt (metadata, không trả full nội dung dài) |
| `POST` | `/v1/admin/agents/{agent_id}/prompts` | Body: `kind`, `label`, `content` |
| `DELETE` | `/v1/admin/agents/{agent_id}/prompts` | Query: `kind`, `label` |

Sau tạo/xóa agent, runtime đọc lại `agents.json`; nếu khởi động với `--start-agents`, tiến trình con agent được restart theo cấu hình mới.

Đồng bộ file `.md` trong workspace → DB: `scripts/sync_agent_prompts_skills_from_workspace.py`.

## Endpoints

- `GET /v1/health` (**requires Bearer session_key**)
- `POST /v1/sessions` (public, `{ "secret": "..." }`)
- `POST /v1/sessions/reconnect` (public, same contract)
- `GET /v1/agents` (Bearer session_key)
- `POST /v1/mcp/credentials` (Bearer session_key, save API key)
- `GET /v1/mcp/credentials/{server_id}` (Bearer session_key, metadata only, masked key)
- `POST /v1/chat/dispatch` (Bearer session_key)
- `GET /ws/agent-chat?session_key=...` (WebSocket)
- `POST /v1/webhooks/agile-notifications` (Bearer session_key)
- Admin (header `X-Api-Center-Admin-Secret`): xem bảng mục **Admin API** phía trên

## MCP credential payload

```json
{
  "mcp_server_id": "agile-studio",
  "mcp_url": "https://agile.example.com/mcp",
  "api_key": "mcp_xxx_secret_key",
  "metadata": {
    "workspace": "agile-studio-prod",
    "issued_by": "user@example.com"
  }
}
```

Stored in `api-center/data/mcp_credentials.json`.

## Auth rule

- Tất cả API cần `Authorization: Bearer <session_key>`.
- Chỉ riêng API tạo/reconnect session (`POST /v1/sessions`, `POST /v1/sessions/reconnect`) dùng `secret`.

## Tech stack

- FastAPI + Uvicorn
