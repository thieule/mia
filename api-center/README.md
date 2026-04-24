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
- `API_CENTER_AGILE_REPLY_URL` (fallback callback API)
- `API_CENTER_AGILE_REPLY_TOKEN` (optional bearer for fallback API)
- `API_CENTER_CHAT_WAIT_TIMEOUT_S` (default: `45`, thời gian chờ kết quả agent)
- `API_CENTER_WORKING_QUEUE_SUBDIR` (default: `working_queue`)
- `API_CENTER_CORE_DIR` (optional, mặc định `../core`)

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
