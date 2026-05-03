# Agile Studio MCP Tools Reference

Tài liệu này mô tả các MCP tools hiện có trong `mcp_server/app.py`, gồm:
- Danh sách tool
- Cấu trúc `params`
- Cấu trúc `response` (thành công/lỗi)

Lưu ý chung:
- Tất cả tool trả về **JSON string**.
- Khi lỗi nghiệp vụ, tool thường trả về object có key `error`.
- Một số tool parse JSON từ chuỗi (`patch_json`, `create_json`), nếu sai schema sẽ trả `{"error": "..."}`.

---

## 1) Health / Info

### `agile_studio_info()`
- **Params**: không có.
- **Response success**:
  - `name: string`
  - `agile_database_url_set: boolean`
  - `note: string`
  - `releases: string`

---

## 2) Members

### `agile_members_list(limit=200)`
- **Params**:
  - `limit: int` (1..500)
- **Response success**: `MemberOut[]`
  - mỗi phần tử gồm các field member chuẩn (vd: `id`, `display_name`, `member_type`, `email`, `agent_id`, timestamps...)

### `agile_member_get(member_id)`
- **Params**:
  - `member_id: int`
- **Response success**: `MemberOut`
- **Response error**:
  - `{"error":"not_found","member_id":<int>}`

### `agile_member_create(display_name, member_type="human", email="", agent_id="")`
- **Params**:
  - `display_name: string`
  - `member_type: string` (`human` | `ai`)
  - `email: string`
  - `agent_id: string` (thường dùng cho AI member)
- **Response success**: `MemberOut`

---

## 3) Workflow Templates (Master Data)

### `agile_workflow_templates_list(limit=200)`
- **Params**:
  - `limit: int` (1..500)
- **Response success**: `WorkflowTemplateOut[]`
  - mỗi phần tử gồm: `id`, `name`, `description`, `created_at`

### `agile_workflow_template_create(name, description="")`
- **Params**:
  - `name: string`
  - `description: string`
- **Response success**: `WorkflowTemplateOut`
- **Response error**:
  - `{"error":"workflow template name may already exist","detail":"..."}`

---

## 4) Projects

## Project output dùng chung trong MCP
Các tool project trả `project` theo shape mở rộng:
- Field gốc từ `project_to_out(...)`:
  - `id`, `slug`, `name`, `description`, `status`, `workspace_ref`, `settings`, `created_at`, `updated_at`
- Trong `settings` có thể có:
  - `workflow_template_id`
  - `storage_overview`
  - và các field public settings khác
- Field mở rộng cho AI:
  - `workflow_template: WorkflowTemplateOut | null`
  - `project_workflow: { configured:boolean, template_id:int|null, template_name:string|null, template_description:string|null }`
  - `project_storage: { configured:boolean, overview:string|null }`

### `agile_projects_list(limit=100)`
- **Params**:
  - `limit: int` (1..500)
- **Response success**: `ProjectOutEnriched[]` (theo shape ở trên)

### `agile_project_get(project_id)`
- **Params**:
  - `project_id: int`
- **Response success**: `ProjectOutEnriched`
- **Response error**:
  - `{"error":"not_found","project_id":<int>}`

### `agile_project_create(slug, name, description="", status="active", workspace_ref="")`
- **Params**:
  - `slug: string`
  - `name: string`
  - `description: string`
  - `status: string`
  - `workspace_ref: string`
- **Response success**: `ProjectOutEnriched` + thêm:
  - `chat_sync: { ok:boolean, error?:string }`
- **Response error**:
  - `{"error":"slug may already exist","detail":"..."}`
  - hoặc `{"error":"..."}`

### `agile_project_update(project_id, patch_json="{}")`
- **Params**:
  - `project_id: int`
  - `patch_json: string(JSON)` với các field patch project:
    - top-level: `name`, `description`, `status`, `workspace_ref`, `settings`
    - `settings` theo `ProjectSettingsWrite` (ví dụ: `workflow_template_id`, `storage_overview`, ...)
- **Response success**: `ProjectOutEnriched`
- **Response error**:
  - `{"error":"not_found","project_id":<int>}`
  - `{"error":"..."}`

---

## 5) Project Members

### `agile_project_members_list(project_id)`
- **Params**:
  - `project_id: int`
- **Response success**: mảng object:
  - `project_id: int`
  - `member_id: int`
  - `role: string`
  - `joined_at: string|null`
  - `member: MemberOut|null`
- **Response error**:
  - `{"error":"not_found","project_id":<int>}`

### `agile_project_member_add(project_id, member_id, role="member")`
- **Params**:
  - `project_id: int`
  - `member_id: int`
  - `role: string`
- **Response success**:
  - object link member-project (như list) + `chat_sync: { ok:boolean, error?:string }`
- **Response error**:
  - `{"error":"not_found","project_id":<int>}`
  - `{"error":"not_found","member_id":<int>}`
  - `{"error":"member may already be in project","detail":"..."}`
  - `{"error":"..."}`

### `agile_project_member_remove(project_id, member_id)`
- **Params**:
  - `project_id: int`
  - `member_id: int`
- **Response success**:
  - `{"ok":true}`
- **Response error**:
  - `{"error":"not_found","project_id":<int>,"member_id":<int>}`

---

## 6) Releases

### `agile_releases_list(project_id)`
- **Params**:
  - `project_id: int`
- **Response success**: `ReleaseOut[]`
- **Response error**:
  - `{"error":"not_found","project_id":<int>}`

### `agile_release_get(release_id)`
- **Params**:
  - `release_id: int`
- **Response success**: `ReleaseOut`
- **Response error**:
  - `{"error":"not_found","release_id":<int>}`

### `agile_release_create(project_id, name, description="", status="planning", starts_at="", ends_at="", released_at="")`
- **Params**:
  - `project_id: int`
  - `name: string`
  - `description: string`
  - `status: string`
  - `starts_at: string` (ISO-8601 hoặc `YYYY-MM-DD`, rỗng = bỏ qua)
  - `ends_at: string` (ISO-8601 hoặc `YYYY-MM-DD`, rỗng = bỏ qua)
  - `released_at: string` (ISO-8601 hoặc `YYYY-MM-DD`, rỗng = bỏ qua)
- **Response success**: `ReleaseOut`
- **Response error**:
  - `{"error":"not_found","project_id":<int>}`
  - `{"error":"starts_at invalid: ..."}`
  - `{"error":"..."}`

### `agile_release_update(release_id, patch_json="{}")`
- **Params**:
  - `release_id: int`
  - `patch_json: string(JSON)` chứa các field patch:
    - `name`, `description`, `status`, `released_at`, `starts_at`, `ends_at`
    - Cho phép `null` hoặc `""` để clear các field datetime khi key có mặt
- **Response success**: `ReleaseOut`
- **Response error**:
  - `{"error":"not_found","release_id":<int>}`
  - `{"error":"..."}`

### `agile_release_delete(release_id)`
- **Params**:
  - `release_id: int`
- **Response success**:
  - `{"ok":true,"release_id":<int>}`
- **Response error**:
  - `{"error":"not_found","release_id":<int>}`

---

## 7) Stories

### `agile_stories_list(project_id, status="")`
- **Params**:
  - `project_id: int`
  - `status: string` (rỗng = lấy tất cả)
- **Response success**: `StoryOut[]`
- **Response error**:
  - `{"error":"not_found","project_id":<int>}`

### `agile_story_get(story_id)`
- **Params**:
  - `story_id: int`
- **Response success**: `StoryOut`
- **Response error**:
  - `{"error":"not_found","story_id":<int>}`

### `agile_story_create(project_id, create_json)`
- **Params**:
  - `project_id: int`
  - `create_json: string(JSON)` theo `StoryCreate`, thường dùng:
    - `title` (required)
    - `description`, `status`, `priority`, `story_points`
    - `release_id`, `release_label`
    - `assignee_id` (legacy), `assignee_ids`
    - `reporter_id`
- **Response success**: `StoryOut`
- **Response error**:
  - `{"error":"not_found","project_id":<int>}`
  - `{"error":"..."}`

### `agile_story_update(story_id, patch_json="{}")`
- **Params**:
  - `story_id: int`
  - `patch_json: string(JSON)` theo `StoryPatch`, chỉ gửi field cần update
- **Response success**: `StoryOut`
- **Response error**:
  - `{"error":"not_found","story_id":<int>}`
  - `{"error":"project missing","story_id":<int>}`
  - `{"error":"..."}`

---

## 8) Comments

### `agile_comments_list(story_id)`
- **Params**:
  - `story_id: int`
- **Response success**: `CommentOut[]`
- **Response error**:
  - `{"error":"not_found","story_id":<int>}`

### `agile_comment_create(story_id, author_member_id, …)`
- **Params**:
  - `story_id: int`
  - `author_member_id: int` (member phải thuộc project)
  - Một trong các field nội dung (ít nhất một chuỗi không rỗng):
    - `body`, `body_text`, `text`, `content`, `message` (string)
- **Response success**: `CommentOut`
- **Response error**:
  - `{"error":"not_found","story_id":<int>}`
  - `{"error":"..."}`
- **Mention rule**:
  - format `@mention_key`
  - `mention_key = display_name bỏ khoảng trắng + lowercase`
  - mention không hợp lệ -> lỗi

### `agile_comment_update(story_id, comment_id, new_body, editor_member_id)`
- **Params**:
  - `story_id: int`
  - `comment_id: int`
  - `new_body: string`
  - `editor_member_id: int` (phải là author)
- **Response success**: `CommentOut`
- **Response error**:
  - `{"error":"not_found","story_id":<int>}`
  - `{"error":"not_found","comment_id":<int>}`
  - `{"error":"..."}`

### `agile_comment_delete(story_id, comment_id, editor_member_id)`
- **Params**:
  - `story_id: int`
  - `comment_id: int`
  - `editor_member_id: int` (phải là author)
- **Response success**:
  - `{"ok":true}`
- **Response error**:
  - `{"error":"not_found","story_id":<int>}`
  - `{"error":"not_found","comment_id":<int>}`
  - `{"error":"..."}`

---

## 9) Gợi ý chuẩn hoá khi gọi tool từ AI

- Luôn parse response dưới dạng JSON object/array.
- Kiểm tra key `error` trước khi dùng dữ liệu.
- Với các tool `*_create` / `*_update` dùng JSON string:
  - Chuẩn bị object trước, rồi `JSON.stringify`.
  - Chỉ gửi field cần update cho `patch_json`.
- Với project:
  - Ưu tiên đọc `project_workflow` và `project_storage` để ra quyết định nhanh.
  - Nếu cần chi tiết workflow đầy đủ, dùng `workflow_template`.
