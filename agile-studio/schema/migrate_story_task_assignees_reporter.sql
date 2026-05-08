-- Add reporter + multi-assignee join table for story_tasks.
-- Run once if DB already has story_tasks without these: mysql ... < schema/migrate_story_task_assignees_reporter.sql

ALTER TABLE story_tasks
  ADD COLUMN reporter_id INT UNSIGNED NULL AFTER sort_order,
  ADD KEY idx_story_tasks_reporter (reporter_id),
  ADD CONSTRAINT fk_story_tasks_reporter FOREIGN KEY (reporter_id) REFERENCES members (id) ON DELETE SET NULL;

CREATE TABLE IF NOT EXISTS story_task_assignees (
  task_id    INT UNSIGNED NOT NULL,
  member_id  INT UNSIGNED NOT NULL,
  PRIMARY KEY (task_id, member_id),
  KEY idx_story_task_assignees_member (member_id),
  CONSTRAINT fk_story_task_assignees_task FOREIGN KEY (task_id) REFERENCES story_tasks (id) ON DELETE CASCADE,
  CONSTRAINT fk_story_task_assignees_member FOREIGN KEY (member_id) REFERENCES members (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
