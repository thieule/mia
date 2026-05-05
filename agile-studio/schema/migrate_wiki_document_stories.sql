-- Nhiều story có thể liên kết tới cùng một wiki doc (bảng wiki_document_stories).
-- Chạy một lần trên DB đã có wiki_documents.story_id. Idempotent phần tạo bảng + copy.
USE agile_studio;

CREATE TABLE IF NOT EXISTS wiki_document_stories (
  wiki_document_id CHAR(36)     NOT NULL,
  story_id         INT UNSIGNED NOT NULL,
  PRIMARY KEY (wiki_document_id, story_id),
  KEY idx_wds_story (story_id),
  CONSTRAINT fk_wds_doc FOREIGN KEY (wiki_document_id) REFERENCES wiki_documents (id) ON DELETE CASCADE,
  CONSTRAINT fk_wds_story FOREIGN KEY (story_id) REFERENCES stories (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT IGNORE INTO wiki_document_stories (wiki_document_id, story_id)
SELECT id, story_id FROM wiki_documents WHERE story_id IS NOT NULL;

ALTER TABLE wiki_documents DROP FOREIGN KEY fk_wiki_story;
ALTER TABLE wiki_documents DROP INDEX idx_wiki_story;
ALTER TABLE wiki_documents DROP COLUMN story_id;
