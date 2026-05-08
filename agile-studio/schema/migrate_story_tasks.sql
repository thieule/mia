-- Replace legacy story_subtasks (if any) with story_tasks (title + body).
-- Run once: mysql ... < schema/migrate_story_tasks.sql

DROP TABLE IF EXISTS story_subtasks;

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
