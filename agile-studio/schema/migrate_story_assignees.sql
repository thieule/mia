-- Add multi-assignee for stories. Run once on existing DB (idempotent for MySQL 8+ via IF NOT EXISTS for table only).
-- mysql -h... -u... -p agile_studio < schema/migrate_story_assignees.sql

USE agile_studio;

CREATE TABLE IF NOT EXISTS story_assignees (
  story_id   INT UNSIGNED NOT NULL,
  member_id  INT UNSIGNED NOT NULL,
  PRIMARY KEY (story_id, member_id),
  KEY idx_sa_member (member_id),
  CONSTRAINT fk_sa_story  FOREIGN KEY (story_id)  REFERENCES stories  (id)   ON DELETE CASCADE,
  CONSTRAINT fk_sa_member FOREIGN KEY (member_id) REFERENCES members  (id)   ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Backfill from legacy single assignee
INSERT IGNORE INTO story_assignees (story_id, member_id)
SELECT id, assignee_id FROM stories WHERE assignee_id IS NOT NULL;
