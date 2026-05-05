-- Cây thư mục wiki + folder_id trên wiki_documents. Chạy một lần trên DB đã có wiki_documents.
USE agile_studio;

CREATE TABLE IF NOT EXISTS wiki_folders (
  id           INT UNSIGNED NOT NULL AUTO_INCREMENT,
  project_id   INT UNSIGNED NOT NULL,
  parent_id    INT UNSIGNED NULL COMMENT 'NULL = thư mục gốc',
  name         VARCHAR(255) NOT NULL,
  sort_order   INT          NOT NULL DEFAULT 0,
  created_at   DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at   DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  PRIMARY KEY (id),
  KEY idx_wf_project (project_id),
  KEY idx_wf_parent (parent_id),
  CONSTRAINT fk_wf_project FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE,
  CONSTRAINT fk_wf_parent FOREIGN KEY (parent_id) REFERENCES wiki_folders (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

ALTER TABLE wiki_documents
  ADD COLUMN folder_id INT UNSIGNED NULL AFTER project_id,
  ADD KEY idx_wiki_folder (project_id, folder_id),
  ADD CONSTRAINT fk_wiki_folder FOREIGN KEY (folder_id) REFERENCES wiki_folders (id) ON DELETE SET NULL;
