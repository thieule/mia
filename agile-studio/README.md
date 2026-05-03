# Agile Studio

Hệ thống quản lý Agile **tách service** khỏi `agent/core`: **cùng MySQL host** với backend/agent (trong Docker: service `mysql`, cổng nội bộ `3306`), **database riêng `agile_studio`** — khác `ai_workflow`. HTTP API riêng. Dùng để lưu **dự án**, **member** (người hoặc AI), **gán member vào dự án**, **user story** (trạng thái), **comment** — agent/workspace chỉ cần gọi API hoặc đồng bộ qua `workspace_ref`.

## Mô hình dữ liệu

| Bảng | Mô tả |
|------|--------|
| `members` | `member_type`: `human` \| `ai`; AI có thể gắn `agent_id` (ID agent runtime). |
| `projects` | `slug` duy nhất, `workspace_ref`, cột JSON `settings_json` (GitHub, Slack/Discord webhook, `documents_storage_path`, `notes`, …). |
| `project_members` | Gán member vào dự án + `role` (`owner`, `admin`, `member`, `viewer`, …). |
| `stories` | Story theo từng project, số `story_number` tăng tự động; khóa hiển thị `{slug}-{number}`; `status` gồm `icebox` (mặc định), `backlog`, luồng làm (`ready` / `in_progress` / `review`), `done`, `cancelled`. |
| `story_comments` | Comment trên story; `author_member_id` phải là member của **cùng dự án**. |
| `users` | Đăng nhập web: `email` (duy nhất), `password_hash` (bcrypt), `display_name`, liên kết 1–1 `member_id` (member `human` tạo khi đăng ký). |

**Đăng nhập:** API `POST /api/v1/auth/register`, `POST /api/v1/auth/login`, `GET /api/v1/auth/me` (Bearer JWT). Các route khác (dự án, story, …) yêu cầu header `Authorization: Bearer <token>`. Biến môi trường `AGILE_JWT_SECRET` (production), `AGILE_JWT_EXPIRE_MINUTES` (tuỳ chọn). Nếu DB đã có trước khi có bảng `users`, chạy một lần: `schema/migrate_users.sql`.

**Trạng thái story:** `icebox`, `backlog`, `ready`, `in_progress`, `review`, `done`, `cancelled`. Trên UI Kanban: **Icebox** / **Backlog** / **Current** (gộp `ready` + `in_progress` + `review`) / **Done**.

**Luồng gợi ý:** tạo dự án → tạo member (human/AI) → `POST .../projects/{id}/members` → tạo story (assignee/reporter chỉ được chọn trong danh sách member đã gán).

## Cài database (MySQL)

```bash
# Tạo DB ``agile_studio`` + bảng + GRANT cho user ``app`` (cùng server với ``ai_workflow``). Ví dụ port 3307:
mysql -h127.0.0.1 -P3307 -uroot -proot < schema/init_mysql.sql
```

Nếu DB **đã tạo trước** khi có `settings_json`, chạy thêm: `schema/migrate_project_settings_json.sql` (một lần).

URL kết nối — **cùng host, khác database** so với backend:

`mysql+pymysql://app:app@127.0.0.1:3307/agile_studio`

## Docker Compose (repo `poc-ai`)

Trong `docker-compose.yml`:

- **`agile-studio`** — build `./agile-studio/Dockerfile`, cổng **`9120`**, `AGILE_DATABASE_URL=mysql+pymysql://app:app@mysql:3306/agile_studio`. Thư mục `agile_hub/` được **mount** vào container: đổi Python (vd. `schemas.py`) chỉ cần **restart** service, không bắt buộc rebuild image (vẫn nên `--build` khi đổi `requirements.txt`). API: `http://localhost:9120/api/v1/`, health: `GET /health`. Trong network Docker: `http://agile-studio:9120`.

- **`agile-studio-web`** (tuỳ chọn) — Vite + React trong `web/`, cổng **`5175`**, proxy `/agile-api` → service `agile-studio`. Trên host: `http://localhost:5175`. `node_modules` nằm trong `./agile-studio/web` (bind mount); mỗi lần container chạy sẽ `npm install` — sau khi thêm dependency trên host, **tạo lại** service: `docker compose up -d --force-recreate agile-studio-web`. Nếu trước đây dùng volume tên `agile_studio_web_node_modules`, có thể xóa volume thừa: `docker volume ls` rồi `docker volume rm <tên_project>_agile_studio_web_node_modules`.

```bash
docker compose up -d --build agile-studio agile-studio-web
```

Nếu DB `agile_studio` chưa có: chạy `schema/init_mysql.sql` vào MySQL (xem mục trên) hoặc để API tạo bảng qua `create_all` ở lần khởi động đầu.

## Giao diện web (`web/`)

Ứng dụng Vite + React (Bootstrap 5): **panel « Dự án »** (thanh trên) chứa danh sách + tạo dự án; **workspace** Board / Đội ngũ; **Tạo story** là màn hình riêng (không nằm trong khung Kanban); chi tiết / comment story trong drawer bên phải.

**Cùng máy (API chạy sẵn cổng 9120):**

```bash
cd agile-studio/web
npm install
npm run dev
```

Mở `http://localhost:5175`. Dev server proxy `VITE_PROXY_AGILE_API` (mặc định `http://127.0.0.1:9120`) — request từ trình duyệt đi qua `/agile-api/...`.

**Build tĩnh** (cần trỏ API rõ ràng):

```bash
cd agile-studio/web
VITE_AGILE_API_BASE=http://127.0.0.1:9120 npm run build
```

Kết quả trong `web/dist/` — phục vụ bằng bất kỳ static server nào; biến `VITE_AGILE_API_BASE` được bake vào bundle lúc build.

## Chạy API (local, không Docker)

```bash
cd agile-studio
pip install -r requirements.txt
export AGILE_DATABASE_URL='mysql+pymysql://app:app@127.0.0.1:3307/agile_studio'
export AGILE_LISTEN_PORT=9120   # tuỳ chọn
PYTHONPATH=. uvicorn agile_hub.main:app --host 127.0.0.1 --port 9120
```

- `GET /health` — kiểm tra sống.
- Toàn bộ REST dưới prefix **`/api/v1`** (xem `agile_hub/api/router.py`).

## Biến môi trường

| Biến | Ý nghĩa |
|------|---------|
| `AGILE_DATABASE_URL` | Bắt buộc — SQLAlchemy URL (MySQL khuyến nghị). |
| `AGILE_LISTEN_PORT` | Cổng HTTP (mặc định 9120). |
| `AGILE_LISTEN_HOST` | Host bind (mặc định 127.0.0.1). |

Khi API khởi động, service gọi `Base.metadata.create_all()` (bảng chưa có thì tạo; đã có từ `init_mysql.sql` thì thường không đổi). Có thể chỉ dùng một trong hai: **chỉ SQL init** hoặc **chỉ để app tạo bảng** (dev).

## Kết nối agent / workspace runtime (bước tiếp)

1. Đặt `projects.workspace_ref` / `instance.yaml` `paths.projects_dir` thống nhất với `projects.workspace_ref` trên Agile Studio.
2. Thêm tool HTTP trong agent (vd. `httpx`) gọi `AGILE_STUDIO_BASE_URL=http://127.0.0.1:9120/api/v1` — hoặc gộp router vào gateway FastAPI nếu muốn một cổng duy nhất.
3. Member `member_type=ai` + `agent_id` trùng `agent_id` trong `instance.yaml` để truy vết.

## Cấu trúc thư mục

```
agile-studio/
  README.md
  requirements.txt
  web/                 # UI Vite + React
  schema/
    init_mysql.sql
  agile_hub/
    main.py          # FastAPI app
    config.py
    db.py
    models.py
    schemas.py
    crud.py
    api/
      router.py
      deps.py
```
