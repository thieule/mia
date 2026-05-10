-- Tickets (story_tasks) scoped by project; optional links to one or many stories via story_task_stories.
-- Run after existing agile_studio schema with story_tasks.story_id NOT NULL.

USE agile_studio;

-- 1) Project scope on each task (required for orphan tickets)
ALTER TABLE story_tasks
  ADD COLUMN project_id INT UNSIGNED NULL AFTER id;

UPDATE story_tasks st
INNER JOIN stories s ON s.id = st.story_id
SET st.project_id = s.project_id;

ALTER TABLE story_tasks
  MODIFY COLUMN project_id INT UNSIGNED NOT NULL,
  ADD CONSTRAINT fk_story_tasks_project FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE,
  ADD KEY idx_story_tasks_project (project_id);

-- 2) Many-to-many: task ↔ story
CREATE TABLE IF NOT EXISTS story_task_stories (
  task_id   INT UNSIGNED NOT NULL,
  story_id  INT UNSIGNED NOT NULL,
  PRIMARY KEY (task_id, story_id),
  KEY idx_story_task_stories_story (story_id),
  CONSTRAINT fk_sts_task FOREIGN KEY (task_id) REFERENCES story_tasks (id) ON DELETE CASCADE,
  CONSTRAINT fk_sts_story FOREIGN KEY (story_id) REFERENCES stories (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT IGNORE INTO story_task_stories (task_id, story_id)
SELECT id, story_id FROM story_tasks;

-- 3) Drop legacy single FK column
ALTER TABLE story_tasks DROP FOREIGN KEY fk_story_tasks_story;
ALTER TABLE story_tasks DROP COLUMN story_id;
