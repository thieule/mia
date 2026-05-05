# Cơ sở dữ liệu quản lý agent, prompt, skill, state và working queue (MySQL)

Toàn bộ DDL nằm trong **một file** chạy trên **MySQL** (cùng kiểu stack với Agile Studio trong repo: `mysql+pymysql://…/agile_studio`).

**File DDL duy nhất:** [`../schema/migrate_mia_agent_prompts_skills_mysql.sql`](../schema/migrate_mia_agent_prompts_skills_mysql.sql)

## Bối cảnh hiện tại (file-based trong `mia` core)

| Thành phần | Vị trí điển hình |
|------------|------------------|
| Danh sách agent runtime | `api-center/agents.json` (mỗi `workspace` dạng `agents/ai-*/workspace`) |
| Prompt bootstrap | `<workspace>/{AGENTS,SOUL,USER,TOOLS}.md` |
| Skill | `<workspace>/skills/<name>/SKILL.md` |
| Session | `<workspace>/sessions/*.json` (chưa đưa vào DDL; payload lớn) |
| Working queue | `<workspace>/working_queue/**/*.json` |

## Bảng MySQL (tiền tố `mia_`)

| Bảng | Mục đích |
|------|----------|
| `mia_agents` | Registry agent (`mia-ba`, …), workspace root, config, metadata |
| `mia_agent_prompts` | Nội dung đầy đủ prompt bootstrap (`kind`, `label`, `content`, hash) |
| `mia_workspace_skills` | Nội dung đầy đủ `SKILL.md` (`body`, hash), `source` workspace/builtin |
| `mia_working_queue_tasks` | Task queue (tương lai / mirror `WorkingQueueTaskPayload` + `location`) |
| `mia_working_queue_events` | Ledger sự kiện (thay `ledger.jsonl`) |
| `mia_agent_state_kv` | State key-value (`namespace`, `entry_key`, `value` JSON) |

## Chạy migration

```bash
mysql -h127.0.0.1 -P3307 -uroot -p agile_studio < api-center/schema/migrate_mia_agent_prompts_skills_mysql.sql
```

## Đồng bộ file `.md` → DB (prompt + skill)

```bash
export AGILE_DATABASE_URL='mysql+pymysql://app:app@127.0.0.1:3307/agile_studio'
pip install pymysql   # hoặc dùng venv api-center đã có requirements.txt
python api-center/scripts/sync_agent_prompts_skills_from_workspace.py
```

Tuỳ chọn: `--dry-run`, `--builtin-skills`.

## Sơ đồ quan hệ

```mermaid
erDiagram
  mia_agents ||--o{ mia_agent_prompts : has
  mia_agents ||--o{ mia_workspace_skills : has
  mia_agents ||--o{ mia_working_queue_tasks : owns
  mia_agents ||--o{ mia_agent_state_kv : has
  mia_working_queue_tasks ||--o{ mia_working_queue_events : logs
```

## Working queue trong code

- **Hiện tại** vẫn dùng file JSON (`WorkingQueueStore`).
- **Bước sau**: dual-write hoặc store SQL — bảng `mia_working_queue_*` đã sẵn trong migration.

## Liên quan Agile Studio

Các bảng `mia_*` đặt trong cùng database `agile_studio` (hoặc DB riêng nếu bạn tách) để dễ vận hành; không đổi schema bảng Agile có sẵn.

## Đổi layout repo (`ai-*` → `agents/ai-*`)

Nếu bạn đã có dòng trong `mia_agents` / prompt với `workspace_root` kiểu `ai-ba/workspace`, cập nhật thủ công (ví dụ):

```sql
UPDATE mia_agents SET workspace_root = CONCAT('agents/', workspace_root) WHERE workspace_root NOT LIKE 'agents/%';
UPDATE mia_agents SET config_path = CONCAT('agents/', config_path) WHERE config_path IS NOT NULL AND config_path NOT LIKE 'agents/%';
```

Điều chỉnh điều kiện `WHERE` cho khớp dữ liệu thực tế trước khi chạy trên production.

## Gói `core` và `ai-tools` trong `agents/`

Mã nguồn mia (`agents/core/`) và MCP cục bộ (`agents/ai-tools/`) nằm cùng cấp với các deploy `agents/ai-*`. Script đồng bộ builtin skill đọc từ `agents/core/mia/skills`.
