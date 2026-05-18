-- Mia agent state — **toàn bộ schema trên MySQL** (một file duy nhất).
-- Prompt + skill (nội dung đầy đủ), working queue, state KV.
-- Chạy trên database ``agent`` (tách khỏi agile_studio):
--
--   mysql -h127.0.0.1 -P3307 -uapp -p agent < api-center/schema/migrate_mia_agent_prompts_skills_mysql.sql
--
-- Đồng bộ .md → DB:  python api-center/scripts/sync_agent_prompts_skills_from_workspace.py

SET NAMES utf8mb4;

-- ---------------------------------------------------------------------------
-- Agents registry (đồng bộ từ api-center/agents.json + meta)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS mia_agents (
  id              VARCHAR(64)     NOT NULL COMMENT 'vd. mia-ba, mia-tech',
  display_name    VARCHAR(255)    NOT NULL,
  workspace_root  VARCHAR(1024)   NOT NULL COMMENT 'đường dẫn tương đối repo, vd. agents/ai-ba/workspace',
  config_path     VARCHAR(1024)   NULL,
  gateway_port    INT             NULL,
  metadata        JSON            NULL,
  created_at      DATETIME(6)     NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at      DATETIME(6)     NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------------------------------------------------------------------
-- Bootstrap prompts (AGENTS / SOUL / USER / TOOLS) — full text, không path file
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS mia_agent_prompts (
  id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  agent_id        VARCHAR(64)     NOT NULL,
  kind            VARCHAR(64)     NOT NULL COMMENT 'bootstrap_agents|bootstrap_soul|bootstrap_user|bootstrap_tools|other',
  label           VARCHAR(255)    NOT NULL DEFAULT '' COMMENT 'vd. AGENTS.md',
  content_sha256  CHAR(64)        NOT NULL,
  content         LONGTEXT        NOT NULL,
  updated_at      DATETIME(6)     NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  UNIQUE KEY uq_mia_agent_prompt (agent_id, kind, label),
  CONSTRAINT fk_mia_agent_prompts_agent FOREIGN KEY (agent_id) REFERENCES mia_agents (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------------------------------------------------------------------
-- Skills (SKILL.md) — full body, không path file
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS mia_workspace_skills (
  agent_id        VARCHAR(64)     NOT NULL,
  skill_name      VARCHAR(255)    NOT NULL,
  source          VARCHAR(16)     NOT NULL COMMENT 'workspace | builtin',
  body_sha256     CHAR(64)        NOT NULL,
  body            LONGTEXT        NOT NULL,
  last_scanned_at DATETIME(6)     NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  PRIMARY KEY (agent_id, skill_name, source),
  CONSTRAINT fk_mia_workspace_skills_agent FOREIGN KEY (agent_id) REFERENCES mia_agents (id) ON DELETE CASCADE,
  CONSTRAINT chk_mia_workspace_skills_source CHECK (source IN ('workspace', 'builtin'))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------------------------------------------------------------------
-- Working queue (mirror / future thay cho file JSON)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS mia_working_queue_tasks (
  id              VARCHAR(64)     NOT NULL,
  agent_id        VARCHAR(64)     NOT NULL,
  project_id      VARCHAR(512)    NOT NULL,
  item_kind       VARCHAR(32)     NOT NULL DEFAULT 'task',
  status          VARCHAR(32)     NOT NULL COMMENT 'pending|processing|done|failed',
  location        VARCHAR(32)     NOT NULL COMMENT 'pending|processing|done|failed',
  message         LONGTEXT        NOT NULL,
  source_role     VARCHAR(128)    NOT NULL DEFAULT 'user',
  service         VARCHAR(512)    NULL,
  enqueued_by     VARCHAR(512)    NULL,
  context         JSON            NOT NULL DEFAULT (JSON_OBJECT()),
  created_at      DATETIME(6)     NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at      DATETIME(6)     NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  completed_at    DATETIME(6)     NULL,
  error           LONGTEXT        NULL,
  result_excerpt  LONGTEXT        NULL,
  PRIMARY KEY (id),
  KEY idx_mia_wq_agent_location (agent_id, location),
  KEY idx_mia_wq_agent_project (agent_id, project_id(191)),
  CONSTRAINT fk_mia_wq_tasks_agent FOREIGN KEY (agent_id) REFERENCES mia_agents (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS mia_working_queue_events (
  id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  task_id         VARCHAR(64)     NOT NULL,
  event           VARCHAR(64)     NOT NULL,
  detail          JSON            NOT NULL DEFAULT (JSON_OBJECT()),
  created_at      DATETIME(6)     NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (id),
  KEY idx_mia_wq_events_task (task_id),
  CONSTRAINT fk_mia_wq_events_task FOREIGN KEY (task_id) REFERENCES mia_working_queue_tasks (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ---------------------------------------------------------------------------
-- Key-value state (gateway flags, poller, …)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS mia_agent_state_kv (
  agent_id        VARCHAR(64)     NOT NULL,
  namespace       VARCHAR(128)    NOT NULL,
  entry_key       VARCHAR(255)    NOT NULL,
  value           JSON            NOT NULL,
  updated_at      DATETIME(6)     NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  PRIMARY KEY (agent_id, namespace, entry_key),
  CONSTRAINT fk_mia_state_kv_agent FOREIGN KEY (agent_id) REFERENCES mia_agents (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
