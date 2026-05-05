-- Agile Studio — database ``agile_studio`` trên **cùng MySQL host** với ``ai_workflow`` (compose: service ``mysql``).
-- Docker Compose: service ``agile-studio-db-init`` chạy file này sau khi ``mysql`` healthy (mỗi lần ``up``, idempotent).
-- Chạy tay: mysql -h127.0.0.1 -P3307 -uroot -p < schema/init_mysql.sql

CREATE DATABASE IF NOT EXISTS agile_studio
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE agile_studio;

CREATE TABLE IF NOT EXISTS members (
  id            INT UNSIGNED NOT NULL AUTO_INCREMENT,
  member_type   VARCHAR(16)     NOT NULL COMMENT 'human | ai',
  display_name  VARCHAR(255)    NOT NULL,
  email         VARCHAR(320)    NULL,
  agent_id      VARCHAR(128)    NULL COMMENT 'ID agent runtime khi member_type=ai',
  meta_json     JSON            NULL,
  created_at    DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at    DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  PRIMARY KEY (id),
  KEY idx_members_type (member_type),
  KEY idx_members_agent (agent_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS users (
  id             INT UNSIGNED NOT NULL AUTO_INCREMENT,
  email          VARCHAR(320)    NOT NULL,
  password_hash  VARCHAR(255)    NOT NULL,
  display_name   VARCHAR(255)    NOT NULL,
  member_id      INT UNSIGNED    NOT NULL COMMENT 'Member human gắn với tài khoản đăng nhập',
  created_at     DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at     DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  PRIMARY KEY (id),
  UNIQUE KEY uq_users_email (email),
  UNIQUE KEY uq_users_member (member_id),
  CONSTRAINT fk_users_member FOREIGN KEY (member_id) REFERENCES members (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS projects (
  id              INT UNSIGNED NOT NULL AUTO_INCREMENT,
  slug            VARCHAR(64)     NOT NULL COMMENT 'khóa URL, duy nhất',
  name            VARCHAR(255)    NOT NULL,
  description     TEXT            NULL,
  status          VARCHAR(24)     NOT NULL DEFAULT 'active' COMMENT 'active | archived',
  workspace_ref   VARCHAR(512)    NULL COMMENT 'tham chiếu workspace runtime, vd. projects/my-app',
  settings_json   JSON            NULL COMMENT 'github, slack/discord webhooks, documents path, notes',
  created_at      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  PRIMARY KEY (id),
  UNIQUE KEY uq_projects_slug (slug),
  KEY idx_projects_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS workflow_templates (
  id            INT UNSIGNED NOT NULL AUTO_INCREMENT,
  name          VARCHAR(255)    NOT NULL,
  description   TEXT            NULL,
  created_at    DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at    DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  PRIMARY KEY (id),
  UNIQUE KEY uq_workflow_templates_name (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS api_center_connections (
  id               INT UNSIGNED NOT NULL COMMENT 'singleton row id=1',
  endpoint         VARCHAR(2048) NOT NULL,
  connect_secret   VARCHAR(1024) NOT NULL,
  session_key      VARCHAR(2048) NULL,
  mcp_api_key      VARCHAR(2048) NULL,
  api_endpoints_json JSON NULL,
  created_at       DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at       DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS project_members (
  project_id  INT UNSIGNED NOT NULL,
  member_id   INT UNSIGNED NOT NULL,
  role        VARCHAR(64)     NOT NULL DEFAULT 'member' COMMENT 'owner | admin | member | viewer',
  joined_at   DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (project_id, member_id),
  CONSTRAINT fk_pm_project FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE,
  CONSTRAINT fk_pm_member FOREIGN KEY (member_id) REFERENCES members (id) ON DELETE CASCADE,
  KEY idx_pm_member (member_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS stories (
  id              INT UNSIGNED NOT NULL AUTO_INCREMENT,
  project_id      INT UNSIGNED NOT NULL,
  story_number    INT UNSIGNED NOT NULL,
  title           VARCHAR(500)    NOT NULL,
  description     MEDIUMTEXT      NULL,
  status          VARCHAR(32)     NOT NULL DEFAULT 'icebox_in_progress'
    COMMENT 'icebox_in_progress | icebox_approved | icebox_rejected | icebox_feedback | backlog_unstart | current_unstart | current_started | current_review | current_delivery | done',
  priority        VARCHAR(24)     NULL,
  story_points    DECIMAL(6,2)    NULL,
  release_label   VARCHAR(64)     NULL,
  release_id      INT UNSIGNED    NULL,
  assignee_id     INT UNSIGNED    NULL,
  reporter_id     INT UNSIGNED    NULL,
  created_at      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at      DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  PRIMARY KEY (id),
  UNIQUE KEY uq_stories_project_num (project_id, story_number),
  KEY idx_stories_project_status (project_id, status),
  KEY idx_stories_assignee (assignee_id),
  KEY idx_stories_release (release_id),
  CONSTRAINT fk_stories_project FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE,
  CONSTRAINT fk_stories_assignee FOREIGN KEY (assignee_id) REFERENCES members (id) ON DELETE SET NULL,
  CONSTRAINT fk_stories_reporter FOREIGN KEY (reporter_id) REFERENCES members (id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS story_assignees (
  story_id   INT UNSIGNED NOT NULL,
  member_id  INT UNSIGNED NOT NULL,
  PRIMARY KEY (story_id, member_id),
  KEY idx_sa_member (member_id),
  CONSTRAINT fk_sa_story  FOREIGN KEY (story_id)  REFERENCES stories  (id)   ON DELETE CASCADE,
  CONSTRAINT fk_sa_member FOREIGN KEY (member_id) REFERENCES members  (id)   ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS story_comments (
  id               INT UNSIGNED NOT NULL AUTO_INCREMENT,
  story_id         INT UNSIGNED NOT NULL,
  author_member_id INT UNSIGNED NOT NULL,
  body             TEXT            NOT NULL,
  created_at       DATETIME(3)   NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at       DATETIME(3)   NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  PRIMARY KEY (id),
  KEY idx_comments_story (story_id),
  CONSTRAINT fk_comments_story FOREIGN KEY (story_id) REFERENCES stories (id) ON DELETE CASCADE,
  CONSTRAINT fk_comments_author FOREIGN KEY (author_member_id) REFERENCES members (id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS story_status_events (
  id               INT UNSIGNED NOT NULL AUTO_INCREMENT,
  story_id         INT UNSIGNED NOT NULL,
  actor_member_id  INT UNSIGNED NOT NULL,
  from_status      VARCHAR(32)  NOT NULL,
  to_status        VARCHAR(32)  NOT NULL,
  created_at       DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (id),
  KEY idx_sse_story_time (story_id, created_at),
  KEY idx_sse_actor (actor_member_id),
  CONSTRAINT fk_sse_story FOREIGN KEY (story_id) REFERENCES stories (id) ON DELETE CASCADE,
  CONSTRAINT fk_sse_actor FOREIGN KEY (actor_member_id) REFERENCES members (id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS story_tasks (
  id          INT UNSIGNED NOT NULL AUTO_INCREMENT,
  story_id    INT UNSIGNED NOT NULL,
  title       VARCHAR(500)    NOT NULL,
  body        MEDIUMTEXT      NULL,
  done        TINYINT(1)      NOT NULL DEFAULT 0,
  sort_order  INT UNSIGNED    NOT NULL DEFAULT 0,
  reporter_id INT UNSIGNED    NULL,
  created_at  DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at  DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  PRIMARY KEY (id),
  KEY idx_story_tasks_story (story_id),
  KEY idx_story_tasks_reporter (reporter_id),
  CONSTRAINT fk_story_tasks_story FOREIGN KEY (story_id) REFERENCES stories (id) ON DELETE CASCADE,
  CONSTRAINT fk_story_tasks_reporter FOREIGN KEY (reporter_id) REFERENCES members (id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS story_task_assignees (
  task_id    INT UNSIGNED NOT NULL,
  member_id  INT UNSIGNED NOT NULL,
  PRIMARY KEY (task_id, member_id),
  KEY idx_story_task_assignees_member (member_id),
  CONSTRAINT fk_story_task_assignees_task FOREIGN KEY (task_id) REFERENCES story_tasks (id) ON DELETE CASCADE,
  CONSTRAINT fk_story_task_assignees_member FOREIGN KEY (member_id) REFERENCES members (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Chat (cùng DB; chat-service đọc/ghi qua mysql2)
CREATE TABLE IF NOT EXISTS chat_channels (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  project_id INT UNSIGNED NOT NULL,
  kind VARCHAR(24) NOT NULL COMMENT 'project_channel | direct',
  channel_name VARCHAR(64) NULL COMMENT 'vd. general khi kind=project_channel',
  member_low_id INT UNSIGNED NULL COMMENT 'DM: min(member_id); general: NULL',
  member_high_id INT UNSIGNED NULL COMMENT 'DM: max(member_id); general: NULL',
  channel_key VARCHAR(160) NOT NULL COMMENT 'room id API/socket: {pid}_general | {pid}_dm_{lo}_{hi}',
  created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (id),
  UNIQUE KEY uq_chat_channels_key (channel_key),
  KEY idx_chat_channels_project (project_id),
  CONSTRAINT fk_cc_project FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE,
  CONSTRAINT fk_cc_member_low FOREIGN KEY (member_low_id) REFERENCES members (id) ON DELETE CASCADE,
  CONSTRAINT fk_cc_member_high FOREIGN KEY (member_high_id) REFERENCES members (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS chat_messages (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  channel_id BIGINT UNSIGNED NOT NULL,
  sender_member_id INT UNSIGNED NOT NULL,
  sender_name VARCHAR(255) NULL,
  content TEXT NOT NULL,
  created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (id),
  KEY idx_chat_messages_channel_time (channel_id, id),
  CONSTRAINT fk_cm_channel FOREIGN KEY (channel_id) REFERENCES chat_channels (id) ON DELETE CASCADE,
  CONSTRAINT fk_cm_sender FOREIGN KEY (sender_member_id) REFERENCES members (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS chat_message_reactions (
  message_id BIGINT UNSIGNED NOT NULL,
  member_id INT UNSIGNED NOT NULL,
  reaction_type VARCHAR(24) NOT NULL COMMENT 'seen | like | love | doing | wow | angry | happy',
  created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (message_id, member_id, reaction_type),
  KEY idx_cmr_message (message_id),
  KEY idx_cmr_member (member_id),
  CONSTRAINT fk_cmr_message FOREIGN KEY (message_id) REFERENCES chat_messages (id) ON DELETE CASCADE,
  CONSTRAINT fk_cmr_member FOREIGN KEY (member_id) REFERENCES members (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS wiki_folders (
  id           INT UNSIGNED NOT NULL AUTO_INCREMENT,
  project_id   INT UNSIGNED NOT NULL,
  parent_id    INT UNSIGNED NULL COMMENT 'NULL = gốc',
  name         VARCHAR(255) NOT NULL,
  sort_order   INT          NOT NULL DEFAULT 0,
  created_at   DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at   DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  PRIMARY KEY (id),
  KEY idx_wf_project (project_id),
  KEY idx_wf_parent (parent_id),
  CONSTRAINT fk_wf_project FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE,
  CONSTRAINT fk_wf_parent FOREIGN KEY (parent_id) REFERENCES wiki_folders (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS wiki_documents (
  id                 CHAR(36)       NOT NULL COMMENT 'doc_id UUID',
  project_id         INT UNSIGNED   NOT NULL,
  folder_id          INT UNSIGNED   NULL COMMENT 'wiki_folders; NULL = ngoài thư mục',
  slug               VARCHAR(128)   NOT NULL,
  title              VARCHAR(500)   NOT NULL,
  content            MEDIUMTEXT     NOT NULL,
  tags_json          JSON           NULL,
  author_member_id   INT UNSIGNED   NOT NULL,
  is_draft           TINYINT(1)     NOT NULL DEFAULT 1,
  embedding_json     JSON           NULL,
  created_at         DATETIME(3)    NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at         DATETIME(3)    NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  PRIMARY KEY (id),
  UNIQUE KEY uq_wiki_project_slug (project_id, slug),
  KEY idx_wiki_project (project_id),
  KEY idx_wiki_folder (project_id, folder_id),
  KEY idx_wiki_updated (project_id, updated_at),
  FULLTEXT KEY ft_wiki_title_content (title, content),
  CONSTRAINT fk_wiki_project FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE,
  CONSTRAINT fk_wiki_folder FOREIGN KEY (folder_id) REFERENCES wiki_folders (id) ON DELETE SET NULL,
  CONSTRAINT fk_wiki_author FOREIGN KEY (author_member_id) REFERENCES members (id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS wiki_document_stories (
  wiki_document_id CHAR(36)       NOT NULL,
  story_id         INT UNSIGNED   NOT NULL,
  PRIMARY KEY (wiki_document_id, story_id),
  KEY idx_wds_story (story_id),
  CONSTRAINT fk_wds_doc FOREIGN KEY (wiki_document_id) REFERENCES wiki_documents (id) ON DELETE CASCADE,
  CONSTRAINT fk_wds_story FOREIGN KEY (story_id) REFERENCES stories (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Dự án / thành viên đã có trước khi có bảng chat (idempotent)
INSERT IGNORE INTO chat_channels (project_id, kind, channel_name, member_low_id, member_high_id, channel_key)
SELECT id, 'project_channel', 'general', NULL, NULL, CONCAT(id, '_general') FROM projects;

INSERT IGNORE INTO chat_channels (project_id, kind, channel_name, member_low_id, member_high_id, channel_key)
SELECT
  pm1.project_id,
  'direct',
  NULL,
  LEAST(pm1.member_id, pm2.member_id),
  GREATEST(pm1.member_id, pm2.member_id),
  CONCAT(pm1.project_id, '_dm_', LEAST(pm1.member_id, pm2.member_id), '_', GREATEST(pm1.member_id, pm2.member_id))
FROM project_members pm1
INNER JOIN project_members pm2
  ON pm2.project_id = pm1.project_id AND pm2.member_id > pm1.member_id;

DELIMITER $$
DROP TRIGGER IF EXISTS trg_projects_ai_chat_general$$
CREATE TRIGGER trg_projects_ai_chat_general
AFTER INSERT ON projects
FOR EACH ROW
BEGIN
  INSERT IGNORE INTO chat_channels (project_id, kind, channel_name, member_low_id, member_high_id, channel_key)
  VALUES (NEW.id, 'project_channel', 'general', NULL, NULL, CONCAT(NEW.id, '_general'));
END$$
DROP TRIGGER IF EXISTS trg_project_members_ai_chat_direct$$
CREATE TRIGGER trg_project_members_ai_chat_direct
AFTER INSERT ON project_members
FOR EACH ROW
BEGIN
  INSERT IGNORE INTO chat_channels (project_id, kind, channel_name, member_low_id, member_high_id, channel_key)
  SELECT
    NEW.project_id,
    'direct',
    NULL,
    LEAST(NEW.member_id, pm.member_id),
    GREATEST(NEW.member_id, pm.member_id),
    CONCAT(NEW.project_id, '_dm_', LEAST(NEW.member_id, pm.member_id), '_', GREATEST(NEW.member_id, pm.member_id))
  FROM project_members pm
  WHERE pm.project_id = NEW.project_id
    AND pm.member_id <> NEW.member_id;
END$$
DELIMITER ;

-- User ``app`` (MYSQL_USER) mặc định chỉ có quyền trên ``MYSQL_DATABASE`` (= ``ai_workflow``).
GRANT ALL PRIVILEGES ON agile_studio.* TO 'app'@'%';
FLUSH PRIVILEGES;
