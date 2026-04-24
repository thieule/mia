# Workflow runtime — API cho Agile Studio (discovery + session + webhook)

**Hướng dẫn tích hợp cho developer client (luồng kết nối, session, webhook):** [CLIENT_INTEGRATION.md](./CLIENT_INTEGRATION.md)

Một process HTTP (`python working_queue_webhook.py`) phục vụ:

- **Health** — `GET /v1/health`
- **Root** — `GET /` — liên kết tới discovery, session, enqueue
- **Discovery** — `GET /v1/discovery` hoặc `GET /v1/agents` (giống nhau): danh sách AI, URL webhook, hướng dẫn auth
- **Session** — `POST /v1/sessions` — gửi **một bí mật kết nối** (`WORKFLOW_RUNTIME_CONNECT_SECRET` trên server) → nhận **session_key** dùng cho mọi API sau (Bearer)
- **Queue** — `POST /v1/working-queue/tasks` — đổ task / notification (như tài liệu [WORKING_QUEUE_WEBHOOK.md](./WORKING_QUEUE_WEBHOOK.md))
- **Event webhook** — `POST /v1/events/agile-story` — nhận event từ Agile Studio, runtime tự route thành queue task/notification cho agent phù hợp
- **Đăng ký quan tâm (tùy chọn)** — `POST /v1/agents/{id}/register` — ghi audit `studio_data/agent_interest.jsonl`

Xem thêm: [ARCHITECTURE.md](./ARCHITECTURE.md).

## Auth (một bí mật + session)

1. **Trên server** cấu hình **một** biến: `WORKFLOW_RUNTIME_CONNECT_SECRET` (≥ 12 ký tự). (Tùy chọn: vẫn đọc tên cũ `WORKING_QUEUE_WEBHOOK_BEARER_TOKEN` / `WORKFLOW_STUDIO_BOOTSTRAP_SECRET` cho tới khi bạn đổi tên env.)
2. **Client** gửi giá trị đó **một lần** trong `POST /v1/sessions` (body `secret`) — **không** dùng Bearer ở bước này.
3. Phản hồi trả về `session_key` (tiền tố `wrs_`) — dùng **`Authorization: Bearer <session_key>`** cho mọi API còn lại: discovery, enqueue, register.
4. Script/CI: gọi `POST /v1/sessions` (có thể lúc deploy), lưu `session_key` trong biến môi trường run; khi 401, gọi lại bước 2.

**Lưu ý bảo mật:** HTTPS, không log `Authorization` / `secret`.

## Discovery (sau khi đã có session)

`GET /v1/discovery` cần header `Authorization: Bearer <session_key>`.

Trả về:

- `runtime` — tên, `public_base_url` (từ `WORKFLOW_RUNTIME_PUBLIC_BASE_URL` nếu set, không thì suy từ request)
- `auth` — tóm tắt
- `webhook` — `url` đủ, header mẫu, field body chính
- `agents` — mỗi phần: `id`, `name`, `role`, `description`, `workspace`, `supported_item_kinds`

Nội dung hiển thị tới từ:

1. Bản **map** workspace: `working_queue_webhook_agents.json` (bắt buộc có từng `agentId`)
2. (Tùy) **catalog** `studio_agents_catalog.json` (sao từ [studio_agents_catalog.example.json](../studio_agents_catalog.example.json)) — tên, role, mô tả

## Tạo session (không cần Bearer; chỉ body `secret`)

```http
POST /v1/sessions
Content-Type: application/json

{"secret":"<cùng giá trị WORKFLOW_RUNTIME_CONNECT_SECRET trên server>"}
```

**201** ví dụ:

```json
{
  "session_key": "wrs_…",
  "token_type": "bearer",
  "usage": "Dùng Authorization: Bearer <session_key> với mọi API đã bảo vệ",
  "ttl_hint_days": 30
}
```

Thời hạn tham chiếu `WORKFLOW_STUDIO_SESSION_TTL_DAYS` (0 = vô hạn theo cấu hình; implement hiện tại vẫn lưu cặp thời gian trên file).

## Đăng ký quan tâm (optional)

`POST /v1/agents/pm/register` (Bearer `session_key`), body tùy ý, ví dụ:

```json
{ "client_id": "agile-studio-prod", "project_key": "ORCH", "note": "team Alpha" }
```

## Event webhook (Agile Story)

`POST /v1/events/agile-story` (Bearer `session_key`), body tập trung vào event story.

Ví dụ:

```json
{
  "event_type": "story.created",
  "event_id": "evt-12001",
  "timestamp": "2026-04-23T10:30:00Z",
  "project": { "id": "PRJ-42", "name": "Commerce Revamp" },
  "story": { "id": "ST-77", "title": "Checkout by QR", "status": "todo" },
  "metadata": { "actor": "alice@studio" }
}
```

Runtime sẽ:

1. Xác định `agent_id` theo **workflow YAML**:
   - Ưu tiên `agent_id` trong payload (nếu có)
   - Nếu không có: match rule trong `WORKFLOW_RUNTIME_EVENT_WORKFLOW_FILE` (mặc định `workflows/agile-studio.events.workflow.yaml`)
   - Nếu không match rule: dùng `routing.defaultAgentId` trong YAML (hoặc fallback nội bộ)
2. Dựng message/action từ event
3. Enqueue vào `working_queue/pending` của agent tương ứng

Response `201` chứa `task_id`, `routed_agent_id`, `project_id`.

## Cấp phát tệp

- `studio_data/studio_sessions.json` — map session (không nên public)
- `studio_data/agent_interest.jsonl` — cột tùy từng dòng
- Cùng cấp `working_queue/…/state/` theo từng agent — xem WORKING_QUEUE_WEBHOOK
