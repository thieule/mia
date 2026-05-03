USE agile_studio;

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
