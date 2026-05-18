-- Working queue v2: priority + dedupe_key (database ``agent``)
-- mysql -h127.0.0.1 -P3307 -uapp -p agent < api-center/schema/migrate_mia_working_queue_v2.sql

ALTER TABLE mia_working_queue_tasks
  ADD COLUMN priority TINYINT NOT NULL DEFAULT 1 COMMENT '0=high (chat/task), 1=notification' AFTER item_kind;

ALTER TABLE mia_working_queue_tasks
  ADD COLUMN dedupe_key VARCHAR(512) NULL COMMENT 'coalesce Agile webhooks' AFTER context;

CREATE INDEX idx_mia_wq_agent_dedupe_loc
  ON mia_working_queue_tasks (agent_id, dedupe_key(191), location);

CREATE INDEX idx_mia_wq_agent_priority_pending
  ON mia_working_queue_tasks (agent_id, location, priority, updated_at);
