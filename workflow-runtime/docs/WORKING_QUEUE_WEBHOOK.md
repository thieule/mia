# Webhook: enqueue từ xa vào `working_queue`

> **Tích hợp client (code luồng kết nối + webhook):** [CLIENT_INTEGRATION.md](./CLIENT_INTEGRATION.md)  
> **Agile Studio / API:** [STUDIO_API.md](./STUDIO_API.md) (`GET /v1/discovery`, `POST /v1/sessions`).

Dịch vụ nhỏ chạy riêng: **`workflow-runtime/working_queue_webhook.py`**. Nó ghi file JSON đúng format **`WorkingQueueTaskPayload`** (xem `core/mia/working_queue/models.py`) vào

`<agent-workspace>/working_queue/pending/<task_id>.json`

Gateway của agent tương ứng phải bật **`workingQueue.enabled: true`** thì nhiệm mới được poll và chạy.

## Cấu hình

1. **Sao bản map agent** (tên → đường dẫn `workspace` dưới gốc monorepo `a-agents`):

   ```text
   copy working_queue_webhook_agents.example.json working_queue_webhook_agents.json
   ```

2. **Biến môi trường** (bắt buộc):

   | Biến | Mô tả |
   |------|--------|
   | `WORKFLOW_RUNTIME_CONNECT_SECRET` | Một bí mật dài (≥ 12 ký tự). Client dùng **một lần** trong `POST /v1/sessions` `{ "secret" }` để nhận `session_key`; mọi API bảo vệ dùng `Authorization: Bearer <session_key>`. (Tùy cấu hình: vẫn đọc tên cũ `WORKING_QUEUE_WEBHOOK_BEARER_TOKEN` như giá trị tương đương nếu chưa đổi tên biến.) |
   | `WORKING_QUEUE_WEBHOOK_AGENTS_FILE` | (Tùy chọn) Đường dẫn tới file JSON map; mặc định: `workflow-runtime/working_queue_webhook_agents.json` |
   | `WORKING_QUEUE_SUBDIR` | (Tùy chọn) Tên thư mục queue dưới workspace; mặc định: `working_queue` (trùng với mia) |

   Script tự nạp **`workflow-runtime/.env`** nếu file tồn tại. Luồng auth đầy đủ: [STUDIO_API.md](./STUDIO_API.md), [CLIENT_INTEGRATION.md](./CLIENT_INTEGRATION.md).

3. **Chạy** (mặc định `127.0.0.1:18880` — chỉ nội bộ; production nên đặt sau reverse proxy + TLS):

   ```bash
   set WORKFLOW_RUNTIME_CONNECT_SECRET=your-long-random-secret
   python working_queue_webhook.py --port 18880
   ```

## API

### `GET /health` hoặc `GET /v1/health`

Không cần token. Trả về `{"status":"ok","service":"workflow_runtime"}`.

### `POST /v1/working-queue/tasks`

- **Header:** `Authorization: Bearer <session_key>` (lấy từ [POST /v1/sessions](./STUDIO_API.md)) **hoặc** `X-Api-Key: <session_key>`. Không dùng lại trực tiếp `WORKFLOW_RUNTIME_CONNECT_SECRET` lên mọi request.
- **Content-Type:** `application/json` (nên dùng); có thể bỏ trống nếu body là JSON hợp lệ.
- **Mã 201** khi ghi thành công; thân trả về: `task_id`, `item_kind`, `project_id`, `agent_id`, `queue_dir`, `session_hint`.

#### Thân yêu cầu (JSON)

**Bắt buộc:** `agent_id` (có trong file map), mô tả dự án theo `project_id` *hoặc* khối `project.id`, và mô tả công việc qua `message` *hoặc* `task.message`.

Các trường tùy chọn phổ biến: **`item_kind`**: `task` (mặc định — công việc cần làm) hoặc `notification` (thông báo / tín hiệu: AI xử lý ngắn, **không** mặc định coi như brief triển khai lớn). Cùng thư mục `pending/`, cùng poller, khác cách mia dựng prompt. `source_role`, `service`, `context` (object tùy ý), `story` / `stories`, `task_metadata`, khối `project: { "id", "name", ... }` (extra → `context.project_extra`).

**Gateway (mia):** với `notifyOnComplete: true`, gửi kết quả ra kênh ngoài mặc định **chỉ** khi `item_kind` nằm trong `notifyOnCompleteKinds` (mặc định `["task"]` — thông báo thường **không** forward ra Discord; thêm `notification` vào list nếu cần).

Hai kiểu viết tương đương (rút gọn so với payload hợp lệ tối thiểu):

**Kiểu phẳng**

```json
{
  "agent_id": "dev",
  "project_id": "PRJ-99",
  "project_name": "Cửa hàng mẫu",
  "message": "Sửa lỗi giỏ hàng theo JIRA ORD-42",
  "source_role": "jira",
  "service": "cart",
  "context": {
    "issue_key": "ORD-42",
    "sprint": "S12"
  }
}
```

**Kiểu lồng**

```json
{
  "agent_id": "pm",
  "project": {
    "id": "PRJ-99",
    "name": "Cửa hàng mẫu"
  },
  "task": {
    "message": "Cập nhật risk log và gửi status cho steering",
    "source_role": "confluence"
  },
  "stories": [
    { "id": "ST-1", "title": "Thanh toán", "status": "In Review" }
  ],
  "context": {
    "escalation": "độ 2"
  }
}
```

Cách map vào hàng đợi mia:

| Cột trong file JSON hàng đợi | Nguồn từ webhook |
|------------------------------|------------------|
| `project_id` | `project_id` hoặc `project.id` |
| `message` | `message` hoặc `task.message` |
| `source_role` | `source_role` / `task.source_role` (mặc định `webhook`) |
| `service` | `service` / `task.service` hoặc tên dự án nếu có |
| `context` | Gộp: `context`, `project` (chuẩn hóa), `story`/`stories`, `task_metadata` |
| `item_kind` | `task` (mặc định) hoặc `notification` — lưu trong file JSON hàng đợi, model `WorkingQueueTaskPayload` (mia) |

Sau mỗi bước, mia cập nhật **`working_queue/state/`** trên cùng agent: `summary.json` (tổng quan số lượng), `items/<task_id>.json` (trạng thái + preview kết quả), `ledger.jsonl` (chuỗi sự kiện). Bản ghi **đầy đủ** (kèm `context` lớn) vẫn nằm trong `pending/` → `done/` / `failed/`.

## Bảo mật

- Không lộ token trong URL; ưu tiên HTTPS phía trước dịch vụ.
- Token phải đủ dài, ngẫu nhiên; đặt cùng độ dài khi so sánh để tránh lộ độ dài thật.
- Bản map `workspace` bị ràng buộc **bên dưới thư mục gốc monorepo**; không thể dùng path vượt ra ngoài.

## Liên quan

- `core/mia/working_queue/submit_task` — ghi pending.
- `workflow-runtime/docs/ARCHITECTURE.md` — chế độ queue từ workflow YAML.
