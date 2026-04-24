# Agile Studio Integration Guide (API Center)

Tài liệu này dành cho team Agile Studio để tích hợp với `api-center`.

## 1) Mục tiêu tích hợp

API Center hiện hỗ trợ:

- Handshake bằng `secret` -> nhận `session_key`
- Reconnect `session_key`
- Lấy danh sách AI agents để load member picker
- Nhận và lưu thông tin kết nối MCP (`mcp_url` + `api_key`)
- Chat bridge qua HTTP và WebSocket (mention policy + private policy)
- Webhook notification để route thay đổi data tới đúng agent qua working queue

---

## 2) Base URL và auth rule

Ví dụ base URL:

- Local: `http://127.0.0.1:18881`
- Production: `https://api-center.your-domain.com`

### Auth rule (quan trọng)

- Chỉ **2 endpoint** dùng `secret`:
  - `POST /v1/sessions`
  - `POST /v1/sessions/reconnect`
- Tất cả endpoint còn lại bắt buộc:
  - `Authorization: Bearer <session_key>`

---

## 2.1 Quick start (10 phút)

Checklist để team Agile Studio tích hợp nhanh, theo đúng thứ tự:

1. Gọi `POST /v1/sessions` với `secret` để lấy `session_key`.
2. Dùng `session_key` gọi `GET /v1/agents` để lấy danh sách agent hợp lệ.
3. (Khuyến nghị) Gọi `POST /v1/mcp/credentials` để API Center có kênh đẩy reply về Agile Studio.
4. Tích hợp luồng chat:
   - Realtime: mở `ws://.../ws/agent-chat?session_key=...`
   - Hoặc HTTP: gọi `POST /v1/chat/dispatch`
5. Tích hợp luồng webhook notification:
   - Gọi `POST /v1/webhooks/agile-notifications`
   - Truyền rõ `target_agent_id` hoặc `agent_ids`.

Kết quả mong đợi:

- Chat nhận được `chat.agent.ack` và (khi đủ điều kiện) `chat.agent.reply`.
- Webhook trả về danh sách `task_id` đã route vào queue từng agent.

## 2.2 Hai luồng tích hợp (rõ trách nhiệm)

- **Luồng Chat (conversation)**:
  - Mục tiêu: user chat với AI như chat app bình thường.
  - Endpoint: `POST /v1/chat/dispatch` hoặc `WS /ws/agent-chat`.
  - Có policy mention/private để quyết định agent có trả lời hay không.

- **Luồng Webhook (data-change notification)**:
  - Mục tiêu: Agile Studio bắn event thay đổi data (story/project/status/...) vào hệ thống AI.
  - Endpoint: `POST /v1/webhooks/agile-notifications`.
  - API Center chỉ route vào working queue đúng agent, không phải phiên chat trực tiếp.

---

## 3) API contract

## 3.1 Health (cần session)

`GET /v1/health`

Headers:

- `Authorization: Bearer <session_key>`

Response:

```json
{
  "status": "ok",
  "service": "api_center"
}
```

## 3.2 Create Session

`POST /v1/sessions`

Body:

```json
{
  "secret": "same-value-as-API_CENTER_CONNECT_SECRET"
}
```

Response `201`:

```json
{
  "session_key": "acs_xxxxxxxxx",
  "token_type": "bearer",
  "endpoints": {
    "agents": "http://127.0.0.1:18881/v1/agents",
    "chat_dispatch": "http://127.0.0.1:18881/v1/chat/dispatch",
    "chat_ws": "ws://127.0.0.1:18881/ws/agent-chat?session_key=acs_xxxxxxxxx",
    "agile_notifications_webhook": "http://127.0.0.1:18881/v1/webhooks/agile-notifications"
  }
}
```

## 3.3 Reconnect Session

`POST /v1/sessions/reconnect`

Body giống `POST /v1/sessions`.

Response: trả `session_key` mới.
Response cũng bao gồm `endpoints` như `POST /v1/sessions`.

## 3.4 Get Agents (member picker)

`GET /v1/agents`

Headers:

- `Authorization: Bearer <session_key>`

Response:

```json
{
  "agents": [
    {
      "id": "dev",
      "name": "Mia dev",
      "role": "Software implementation",
      "description": "Code changes, tests, refactors, and delivery.",
      "workspace": "ai-dev/workspace",
      "supported_item_kinds": ["task", "notification"]
    }
  ],
  "count": 1
}
```

## 3.5 Save MCP Credentials

`POST /v1/mcp/credentials`

Headers:

- `Authorization: Bearer <session_key>`
- `Content-Type: application/json`

Body:

```json
{
  "mcp_server_id": "agile-studio",
  "mcp_url": "https://agile-studio.example.com/mcp",
  "api_key": "mcp_xxx_secret",
  "metadata": {
    "workspace": "prod",
    "issued_by": "user@example.com"
  }
}
```

Response `201`:

```json
{
  "ok": true,
  "mcp_server_id": "agile-studio",
  "mcp_url": "https://agile-studio.example.com/mcp",
  "stored": true,
  "updated_at": 1760000000.0
}
```

## 3.6 Get MCP Credential Metadata

`GET /v1/mcp/credentials/{server_id}`

Headers:

- `Authorization: Bearer <session_key>`

Response:

```json
{
  "mcp_server_id": "agile-studio",
  "mcp_url": "https://agile-studio.example.com/mcp",
  "has_api_key": true,
  "api_key_masked": "mcp***et",
  "created_at": 1760000000.0,
  "updated_at": 1760000100.0,
  "metadata": {
    "workspace": "prod"
  }
}
```

## 3.7 Chat Dispatch (HTTP)

`POST /v1/chat/dispatch`

Mục đích:

- Đây là endpoint HTTP để gửi **1 message chat** vào API Center.
- Dùng khi:
  - backend Agile Studio muốn gọi request/response đồng bộ,
  - hoặc frontend không duy trì được WebSocket ổn định,
  - hoặc cần fallback khi WS bị gián đoạn.
- Nói ngắn gọn: `chat_dispatch` là bản HTTP của luồng chat.

Khác nhau giữa `chat_dispatch` và `WS /ws/agent-chat`:

- `chat_dispatch`:
  - 1 request -> 1 response JSON.
  - Dễ tích hợp với backend service, job queue, retry qua HTTP.
- `ws/agent-chat`:
  - Kênh realtime 2 chiều.
  - Tối ưu cho UX chat liên tục như app chat.

Flow xử lý bên trong `chat_dispatch`:

1. Validate payload (`project_id`, `channel_id`, `channel_type`, `sender`, `message`).
2. Áp policy mention/private:
   - group/public/project_channel: chỉ phản hồi khi có mention hoặc `target_agent_id`.
   - direct/private/dm: luôn phản hồi.
3. Resolve agent đích.
4. Enqueue task vào working queue agent (direct).
5. Chờ ngắn hạn để lấy kết quả xử lý queue.
6. Trả `reply_text` + trạng thái enqueue/wait.
7. Đồng thời thử đẩy reply ra Agile Studio:
   - ưu tiên MCP,
   - fallback API callback.

Headers:

- `Authorization: Bearer <session_key>`
- `Content-Type: application/json`

Body (contract v1):

```json
{
  "trace_id": "tr_1745400000000",
  "project_id": "proj_123",
  "project_context": {
    "name": "CRM Revamp"
  },
  "channel_id": "chn_abc",
  "channel_type": "group",
  "sender": {
    "id": "u_01",
    "name": "ThieuLe"
  },
  "message": "@tech xem giúp impact kiến trúc",
  "mentions": ["tech"],
  "target_agent_id": "tech",
  "story_context": {
    "story_id": "S-102",
    "status": "backlog_unstart"
  },
  "conversation_history": [
    {
      "sender_id": "u_01",
      "sender_type": "human",
      "content": "PO đã approve story",
      "created_at": "2026-04-23T09:10:00Z"
    }
  ],
  "callback_api_url": "https://agile-studio.example.com/api/ai/chat/reply"
}
```

Response `200`:

```json
{
  "ok": true,
  "event": "chat.agent.ack",
  "trace_id": "tr_1745400000000",
  "project_id": "proj_123",
  "channel_id": "chn_abc",
  "channel_type": "group",
  "selected_agent_id": "tech",
  "should_respond": true,
  "reply_text": "Nội dung phản hồi thật từ agent (result_excerpt từ working queue)",
  "agent_task_id": "4b4f0f5f3f3b4ee2a0b734f628f9d52b",
  "agent_dispatch_status": "direct_enqueued:done",
  "policy": {
    "rule": "mentionAgentInGroup || isDirectAgentChannel",
    "mention_hit": true
  },
  "context_window": {
    "conversation_history_items": 1,
    "project_context_present": true,
    "story_context_present": true
  },
  "delivery_mode": "mcp",
  "delivery_status": "mcp:200"
}
```

Các field quan trọng trong response:

- `should_respond`: policy có cho agent trả lời hay không.
- `selected_agent_id`: agent được chọn để xử lý.
- `agent_task_id`: id queue item đã tạo trong working queue.
- `agent_dispatch_status`: trạng thái enqueue + trạng thái chờ (`done`/`failed`/`timeout`).
- `delivery_mode` + `delivery_status`: trạng thái gửi reply ngược về Agile Studio (MCP/API).

Contract tối thiểu khuyến nghị cho client:

- Bắt buộc gửi:
  - `project_id`, `channel_id`, `channel_type`, `sender`, `message`
- Nên gửi:
  - `target_agent_id` (để route rõ ràng)
  - `trace_id` (để trace end-to-end)
  - `conversation_history` (để agent có ngữ cảnh tốt hơn)

## 3.8 Chat Bridge (WebSocket)

`GET /ws/agent-chat?session_key=<session_key>`

Auth:

- Query `session_key`, hoặc header `Authorization: Bearer <session_key>`

Event inbound:

- `chat.message.created`
  - `payload` dùng cùng schema như `POST /v1/chat/dispatch`

Event outbound:

- `chat.connected`: kết nối thành công
- `chat.agent.ack`: API Center đã xử lý policy và chọn agent
- `chat.agent.reply`: có phản hồi và đã thử dispatch ra ngoài
- `chat.agent.error`: payload/event không hợp lệ

Ví dụ client WebSocket (browser/Node):

```ts
const ws = new WebSocket(`ws://127.0.0.1:18881/ws/agent-chat?session_key=${sessionKey}`);

ws.onopen = () => {
  ws.send(JSON.stringify({
    event: "chat.message.created",
    payload: {
      project_id: "proj_123",
      channel_id: "chn_private_001",
      channel_type: "direct",
      sender: { id: "u_01", name: "ThieuLe" },
      message: "Mia dev giúp tôi review API này",
      target_agent_id: "dev"
    }
  }));
};

ws.onmessage = (evt) => {
  console.log("WS message:", evt.data);
};
```

Lưu ý quan trọng:

- Phải dùng URL `ws://` hoặc `wss://`.
- Nếu gọi như HTTP GET thường (`http://.../ws/agent-chat`) sẽ gặp `404 Not Found`.

## 3.9 Agile Notifications Webhook

`POST /v1/webhooks/agile-notifications`

Mục tiêu: Agile Studio gửi notification về thay đổi data (story/project/status/...) để API Center route vào working queue đúng agent.

Headers:

- `Authorization: Bearer <session_key>`
- `Content-Type: application/json`

Body mẫu:

```json
{
  "trace_id": "tr_1745401111000",
  "event_type": "story.status_changed",
  "project_id": "proj_123",
  "project_name": "CRM Revamp",
  "summary": "Story S-102 moved backlog -> current",
  "changed_fields": ["status", "assignee"],
  "target_agent_id": "dev",
  "agent_ids": ["tech", "pm"],
  "item_kind": "notification",
  "source_role": "agile_studio_webhook",
  "service": "agile-studio",
  "data": {
    "story_id": "S-102",
    "from_status": "backlog_unstart",
    "to_status": "current_unstart"
  }
}
```

Routing rule:

- Ưu tiên các field định tuyến: `target_agent_id`, `agent_id`, `agent_ids[]`, `routing.agent_id`
- Mỗi agent đích sẽ được tạo một queue item riêng.
- `item_kind` mặc định là `notification`.
- Nếu payload không có agent đích hợp lệ, API trả `400`.

Response `200`:

```json
{
  "ok": true,
  "event": "webhook.notification.ack",
  "trace_id": "tr_1745401111000",
  "project_id": "proj_123",
  "item_kind": "notification",
  "routed_count": 3,
  "routed": [
    {
      "agent_id": "dev",
      "ok": true,
      "status": "direct_enqueued",
      "task_id": "4ad9..."
    }
  ]
}
```

---

## 4) Luồng chuẩn phía Agile Studio

1. User nhập connect secret (hoặc app lấy từ secure source)
2. Gọi `POST /v1/sessions` -> nhận `session_key`
3. Lưu `session_key` (memory/secure storage)
4. Gọi `GET /v1/agents` để render member picker
5. Khi user bật MCP access:
   - lấy `mcp_url`, `api_key`
   - gọi `POST /v1/mcp/credentials`
6. Khi 401 hoặc user bấm reconnect:
   - gọi `POST /v1/sessions/reconnect`
   - thay `session_key` mới
7. Chat integration:
   - Mở WS `GET /ws/agent-chat?session_key=...`
   - Push event `chat.message.created`
   - Nhận `chat.agent.ack` ngay
   - Nhận `chat.agent.reply` (nếu policy cho phép)
8. Webhook integration (notification):
   - Gọi `POST /v1/webhooks/agile-notifications`
   - Truyền rõ agent đích (`target_agent_id` hoặc `agent_ids`)
   - API Center route vào queue của từng agent và trả về danh sách `task_id`

## 4.1 Flow đề xuất trong production

- **Frontend**:
  - Giữ kết nối WS để chat realtime.
  - Khi WS rớt, fallback tạm sang `POST /v1/chat/dispatch`.
- **Backend Agile Studio**:
  - Khi có thay đổi data nghiệp vụ, gọi webhook notification.
  - Retry với backoff nếu gặp `5xx`.
- **Session handling**:
  - Khi gặp `401`, gọi lại `POST /v1/sessions/reconnect`, cập nhật token mới rồi retry request.

---

## 5) Error handling guideline

| HTTP | Ý nghĩa | Cách xử lý |
|------|---------|------------|
| 400 | Payload thiếu/sai | Hiển thị lỗi field cho user/dev |
| 401 | Secret/session sai hoặc hết hạn | Reconnect session |
| 404 | Không có credential theo `server_id` | Cho phép user tạo mới |
| 5xx | Lỗi server tạm thời | Retry có backoff + alert |

---

## 5.1 Troubleshooting nhanh

- **WS 404 tại `/ws/agent-chat`**
  - Nguyên nhân: gọi sai giao thức (`http://` thay vì `ws://` / `wss://`).
  - Cách xử lý: dùng WebSocket client thật, không dùng REST client thông thường.

- **`chat.agent.ack` có `should_respond=false`**
  - Nguyên nhân: channel nhóm nhưng không mention đúng agent.
  - Cách xử lý: thêm `target_agent_id` hoặc `mentions`/`@agentId`.

- **Webhook trả `400 No routable target agent`**
  - Nguyên nhân: thiếu `target_agent_id` / `agent_ids` hoặc id không nằm trong `GET /v1/agents`.
  - Cách xử lý: lấy agent list trước, validate id ở phía Agile Studio trước khi gửi.

- **`agent_dispatch_status` timeout**
  - Nguyên nhân: agent chưa xử lý xong queue trong thời gian chờ.
  - Cách xử lý: hiển thị trạng thái "đang xử lý", cho phép user chờ/poll lại.

## 6) Mention/private policy

- Channel nhóm (`group`/`public`/`project_channel`): agent chỉ trả lời khi có mention (`mentions` hoặc trong `message` có `@agentId`).
- Channel riêng (`direct`/`private`/`dm`/`agent_dm`): agent luôn trả lời.
- Nếu `target_agent_id` có trong payload thì API Center ưu tiên agent đó.
- Nếu không có `target_agent_id`, API Center tự suy luận từ `mentions` hoặc text mention.
- Rule hiện tại: `mentionAgentInGroup || isDirectAgentChannel`.

## 7) Reply adapter (MCP first, API fallback)

- Bước 1: nếu có credential MCP của agent đích (`mcp_server_id == agent_id`) thì đẩy reply qua MCP trước.
- Bước 2: nếu chưa có, thử credential `agile-studio`.
- Bước 3: fallback sang HTTP callback API (`callback_api_url` trong payload hoặc `API_CENTER_AGILE_REPLY_URL` trong env).
- API Center ghi `delivery_mode` và `delivery_status` để client audit.

## 8) Direct agent bridge (không qua runtime)

- Khi policy cho phép phản hồi, API Center ghi thẳng queue item vào thư mục `working_queue/pending` của agent đích.
- Message chat được đóng gói thành queue task cho đúng `agent_id`.
- API Center chờ trong `API_CENTER_CHAT_WAIT_TIMEOUT_S` giây để đọc trạng thái trong `working_queue/state/items/<task_id>.json`.
- Nếu `done`, lấy `result_excerpt` làm `reply_text`.
- Nếu timeout, trả `reply_text` dạng "đang xử lý" + `agent_task_id` để client theo dõi.

## 9) Frontend pseudo code (TypeScript)

```ts
const BASE = "http://127.0.0.1:18881";

async function createSession(secret: string): Promise<string> {
  const res = await fetch(`${BASE}/v1/sessions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ secret }),
  });
  if (!res.ok) throw new Error(await res.text());
  const data = await res.json();
  return data.session_key as string;
}

async function getAgents(sessionKey: string) {
  const res = await fetch(`${BASE}/v1/agents`, {
    headers: { Authorization: `Bearer ${sessionKey}` },
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

async function saveMcpCredential(sessionKey: string, payload: {
  mcp_server_id: string;
  mcp_url: string;
  api_key: string;
  metadata?: Record<string, unknown>;
}) {
  const res = await fetch(`${BASE}/v1/mcp/credentials`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${sessionKey}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}
```

