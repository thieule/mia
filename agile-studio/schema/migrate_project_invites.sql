-- Project invites by email (run once on existing DBs).
USE agile_studio;

CREATE TABLE IF NOT EXISTS project_invites (
  id                   INT UNSIGNED NOT NULL AUTO_INCREMENT,
  project_id           INT UNSIGNED NOT NULL,
  email                VARCHAR(320) NOT NULL COMMENT 'normalized lowercase',
  token                VARCHAR(96)  NOT NULL COMMENT 'opaque URL token',
  role                 VARCHAR(64)  NOT NULL DEFAULT 'member',
  invited_by_member_id INT UNSIGNED NULL,
  created_at           DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  expires_at           DATETIME(3)  NOT NULL,
  accepted_at          DATETIME(3) NULL,
  revoked_at           DATETIME(3) NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_project_invites_token (token),
  KEY idx_pi_project_email (project_id, email),
  KEY idx_pi_email_pending (email, accepted_at, revoked_at),
  CONSTRAINT fk_pi_project FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE,
  CONSTRAINT fk_pi_inviter FOREIGN KEY (invited_by_member_id) REFERENCES members (id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
