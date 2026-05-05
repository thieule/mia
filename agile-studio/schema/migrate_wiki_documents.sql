-- Wiki / Docs: lưu Markdown theo project_id (bắt buộc), tùy story_id; slug cho liên kết chéo.
-- Chạy sau khi init_mysql.sql (idempotent).

USE agile_studio;

CREATE TABLE IF NOT EXISTS wiki_documents (
  id                 CHAR(36)       NOT NULL COMMENT 'doc_id UUID',
  project_id         INT UNSIGNED   NOT NULL,
  story_id           INT UNSIGNED   NULL COMMENT 'NULL = tài liệu cấp project',
  slug               VARCHAR(128)   NOT NULL COMMENT 'duy nhất trên project',
  title              VARCHAR(500)   NOT NULL,
  content            MEDIUMTEXT     NOT NULL,
  tags_json          JSON           NULL,
  author_member_id   INT UNSIGNED   NOT NULL,
  is_draft           TINYINT(1)     NOT NULL DEFAULT 1,
  embedding_json     JSON           NULL COMMENT 'vector cho semantic search (dense)',
  created_at         DATETIME(3)    NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at         DATETIME(3)    NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  PRIMARY KEY (id),
  UNIQUE KEY uq_wiki_project_slug (project_id, slug),
  KEY idx_wiki_project (project_id),
  KEY idx_wiki_story (project_id, story_id),
  KEY idx_wiki_updated (project_id, updated_at),
  FULLTEXT KEY ft_wiki_title_content (title, content),
  CONSTRAINT fk_wiki_project FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE,
  CONSTRAINT fk_wiki_story FOREIGN KEY (story_id) REFERENCES stories (id) ON DELETE SET NULL,
  CONSTRAINT fk_wiki_author FOREIGN KEY (author_member_id) REFERENCES members (id) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
