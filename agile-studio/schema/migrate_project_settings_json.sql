-- Chạy một lần nếu DB đã tồn tại trước khi có cột settings_json:
-- mysql -h... -uroot -p agile_studio < schema/migrate_project_settings_json.sql

USE agile_studio;

ALTER TABLE projects
  ADD COLUMN settings_json JSON NULL COMMENT 'github, documents path, ...' AFTER workspace_ref;
