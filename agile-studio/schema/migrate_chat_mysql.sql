-- Chat persistence + triggers (DB agile_studio đã tồn tại).
-- Chạy: mysql -h127.0.0.1 -P3307 -uroot -p agile_studio < schema/migrate_chat_mysql.sql

USE agile_studio;

CREATE TABLE IF NOT EXISTS chat_channels (
  id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  project_id INT UNSIGNED NOT NULL,
  kind VARCHAR(24) NOT NULL COMMENT 'project_channel | direct',
  channel_name VARCHAR(64) NULL,
  member_low_id INT UNSIGNED NULL,
  member_high_id INT UNSIGNED NULL,
  channel_key VARCHAR(160) NOT NULL,
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
