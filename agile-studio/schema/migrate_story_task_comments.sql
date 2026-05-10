-- Ticket / story_task threaded comments (same shape as story_comments).
CREATE TABLE IF NOT EXISTS story_task_comments (
  id               INT UNSIGNED NOT NULL AUTO_INCREMENT,
  story_task_id    INT UNSIGNED NOT NULL,
  author_member_id INT UNSIGNED NOT NULL,
  body             TEXT            NOT NULL,
  created_at       DATETIME(3)   NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at       DATETIME(3)   NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  PRIMARY KEY (id),
  KEY idx_stc_task (story_task_id),
  CONSTRAINT fk_stc_task   FOREIGN KEY (story_task_id)    REFERENCES story_tasks (id) ON DELETE CASCADE,
  CONSTRAINT fk_stc_author FOREIGN KEY (author_member_id) REFERENCES members   (id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
