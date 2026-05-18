# Cơ sở dữ liệu quản lý agent, prompt, skill, state và working queue (MySQL)

Bảng `mia_*` nằm trong database **`agent`** (tách khỏi **`agile_studio`** — Hub/MCP Agile chỉ dùng `AGILE_DATABASE_URL`).

**DDL:** [`../schema/migrate_mia_agent_prompts_skills_mysql.sql`](../schema/migrate_mia_agent_prompts_skills_mysql.sql)  
**Working queue v2** (`priority`, `dedupe_key`): [`../schema/migrate_mia_working_queue_v2.sql`](../schema/migrate_mia_working_queue_v2.sql)

Docker: `docker/mysql-init/02-agent.sql` tạo database `agent` khi volume MySQL mới.

## Biến môi trường (URL database `agent`)

| Biến | Vai trò |
|------|---------|
| `MIA_AGENT_DATABASE_URL` | **Chuẩn** — vd. `mysql+pymysql://app:app@127.0.0.1:3307/agent` |
| `API_CENTER_AGENT_DB_URL` | Alias (API Center) |
| `MIA_AGENT_SYNC_DATABASE_URL` | Alias (script sync prompt/skill) |
| `MIA_WORKING_QUEUE_DB_URL` | Override chỉ cho WQ mirror (hiếm) |

**Không** dùng `AGILE_DATABASE_URL` cho bảng `mia_*`. Code từ chối nếu URL trỏ nhầm `agile_studio`.

Resolver: [`../agent_db.py`](../agent_db.py) (API Center), `mia.agent_db_url` (gateway).

## Bối cảnh file-based (runtime)

| Thành phần | Vị trí điển hình |
|------------|------------------|
| Danh sách agent runtime | `api-center/agents.json` |
| Prompt bootstrap | `<workspace>/{AGENTS,SOUL,USER,TOOLS}.md` |
| Skill | `<workspace>/skills/<name>/SKILL.md` |
| Session | `<workspace>/sessions/*.json` (chưa trong DDL) |
| Working queue (chạy thật) | `<workspace>/working_queue/**/*.json` |

## Bảng MySQL

| Bảng | Mục đích |
|------|----------|
| `mia_agents` | Registry (`mia-ba`, …), workspace, gateway |
| `mia_agent_prompts` | Prompt bootstrap đầy đủ |
| `mia_workspace_skills` | `SKILL.md` workspace + builtin |
| `mia_working_queue_tasks` | Mirror queue + dedupe |
| `mia_working_queue_events` | Ledger sự kiện |
| `mia_agent_state_kv` | State KV theo agent |

## Chạy migration (database `agent`)

```bash
mysql -h127.0.0.1 -P3307 -uapp -p agent < api-center/schema/migrate_mia_agent_prompts_skills_mysql.sql
mysql -h127.0.0.1 -P3307 -uapp -p agent < api-center/schema/migrate_mia_working_queue_v2.sql
```

Nếu DB `agent` đã có schema thủ công (như production hiện tại), chỉ cần bước v2 khi thiếu cột `priority` / `dedupe_key`.

## Đồng bộ file `.md` → DB

Script quét **mọi** `*.md` trong `workspace/` (trừ `skills/`, `working_queue/`, `sessions/`): bootstrap gốc, `policy/`, `project/`, `projects/`, `docs/`, `memory/MEMORY.md`, `HEARTBEAT.md`, v.v. Skills vẫn vào `mia_workspace_skills`.

```bash
export MIA_AGENT_DATABASE_URL='mysql+pymysql://app:app@127.0.0.1:3307/agent'
pip install pymysql
python api-center/scripts/sync_agent_prompts_skills_from_workspace.py
# Tuỳ chọn: xóa prompt DB không còn file trong workspace
python api-center/scripts/sync_agent_prompts_skills_from_workspace.py --prune-prompts
```

## Working queue trong code

- Poller đọc/ghi **file JSON** trong workspace.
- **Dual-write** `mia_working_queue_*` khi `MIA_AGENT_DATABASE_URL` + `agentId` / `MIA_AGENT_ID`.
- API Center: allowlist webhook, dedup (`API_CENTER_WQ_DEDUP_WINDOW_S`).

## Liên quan Agile Studio

- **Agile Studio / MCP:** `AGILE_DATABASE_URL` → database `agile_studio` only.
- **Mia agents / API Center admin / WQ mirror:** `MIA_AGENT_DATABASE_URL` → database `agent`.
