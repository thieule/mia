-- Ticket-style fields + watchers on story_tasks. Run once on existing DBs.
-- mysql ... < schema/migrate_story_task_ticket_fields.sql

ALTER TABLE story_tasks
  ADD COLUMN task_status VARCHAR(24) NOT NULL DEFAULT 'open' COMMENT 'open | in_progress | blocked | done' AFTER done,
  ADD COLUMN response MEDIUMTEXT NULL AFTER task_status,
  ADD COLUMN report MEDIUMTEXT NULL AFTER response,
  ADD KEY idx_story_tasks_status (task_status);

UPDATE story_tasks SET task_status = 'done' WHERE done = 1;

CREATE TABLE IF NOT EXISTS story_task_watchers (
  task_id   INT UNSIGNED NOT NULL,
  member_id INT UNSIGNED NOT NULL,
  created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (task_id, member_id),
  KEY idx_story_task_watchers_member (member_id),
  CONSTRAINT fk_story_task_watchers_task FOREIGN KEY (task_id) REFERENCES story_tasks (id) ON DELETE CASCADE,
  CONSTRAINT fk_story_task_watchers_member FOREIGN KEY (member_id) REFERENCES members (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
