-- Professional ticket fields: drop legacy response/report, add priority, type, due date, acceptance criteria.
-- Run after migrate_story_task_ticket_fields.sql when those columns exist.
-- mysql ... < schema/migrate_story_ticket_pro_fields.sql

ALTER TABLE story_tasks
  DROP COLUMN response,
  DROP COLUMN report,
  ADD COLUMN ticket_priority VARCHAR(16) NOT NULL DEFAULT 'medium' COMMENT 'low|medium|high|urgent' AFTER task_status,
  ADD COLUMN ticket_type VARCHAR(24) NOT NULL DEFAULT 'task' AFTER ticket_priority,
  ADD COLUMN due_at DATETIME(3) NULL AFTER ticket_type,
  ADD COLUMN acceptance_criteria MEDIUMTEXT NULL AFTER due_at,
  ADD KEY idx_story_tasks_ticket_priority (ticket_priority),
  ADD KEY idx_story_tasks_ticket_type (ticket_type),
  ADD KEY idx_story_tasks_due_at (due_at);
