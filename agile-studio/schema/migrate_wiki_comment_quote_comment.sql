-- Quote another message inside a thread reply (optional quoted_comment_id + snapshot text).
ALTER TABLE wiki_comments
  ADD COLUMN quoted_comment_id CHAR(36) NULL COMMENT 'quoted peer comment in same thread' AFTER parent_id,
  ADD COLUMN quoted_excerpt MEDIUMTEXT NULL COMMENT 'snapshot of quoted body for display' AFTER quoted_comment_id,
  ADD COLUMN quoted_author_display_name VARCHAR(255) NULL COMMENT 'author snapshot when quoted' AFTER quoted_excerpt,
  ADD KEY idx_wc_quoted (quoted_comment_id),
  ADD CONSTRAINT fk_wc_quoted FOREIGN KEY (quoted_comment_id) REFERENCES wiki_comments (id) ON DELETE SET NULL;
